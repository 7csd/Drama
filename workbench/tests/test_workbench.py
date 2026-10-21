import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from utils.production_cache import ensure_workspace_revision
from workbench.api import create_app
from workbench.engine import ASSET_FIELDS, SHOT_FIELDS, Conflict, Engine, parse_script
from workbench.models import DEMO_SCRIPT
from workbench.providers import CloudProvider, Provider, RateLimited
from workbench.store import Store


@pytest.fixture
def engine(tmp_path):
    return Engine(Store(tmp_path))


@pytest.fixture(autouse=True)
def no_live_switch_in_tests(monkeypatch):
    from workbench import config
    monkeypatch.setattr(config, "CONFIG_PATH", __import__("pathlib").Path("__missing_test_config__.yaml"))


def setup_episode(engine, style="comic", budget=50):
    project = engine.create_project({"name": "测试剧目", "budget": budget})
    ep = engine.create_episode(project["id"], {"title": "第一集", "style": style, "script": DEMO_SCRIPT,
        "target_duration": 75, "aspect": "9:16"})
    with engine.store.transaction() as db:
        engine.apply_plan(db, ep, parse_script(DEMO_SCRIPT, 75))
    return project, ep


def asset_job(engine, project, ep):
    engine.approve(ep["id"], "script")
    return engine.run(ep["id"], "assets")[0]


def editable(item, fields):
    return {**{key: item[key] for key in fields if key in item}, "version": item["version"]}


def ready_assets(engine, ep):
    with engine.store.transaction() as db:
        for asset in engine.used_assets(db, ep):
            asset.update(image=f"test/{asset['id']}.png", simulated=False)
            engine.store.put(db, "asset", asset)
    engine.approve(ep["id"], "script")
    engine.approve(ep["id"], "assets")
    engine.approve(ep["id"], "storyboard")


def test_two_styles_share_structure_but_separate_visual_assets(engine):
    project, first = setup_episode(engine)
    second = engine.create_episode(project["id"], {"title": "写实", "style": "realistic", "script": DEMO_SCRIPT,
        "target_duration": 75, "aspect": "9:16"})
    with engine.store.transaction() as db:
        engine.apply_plan(db, second, parse_script(DEMO_SCRIPT, 75))
    state = engine.snapshot(project["id"])
    assert len(state["assets"]) == 8  # 2 characters + 2 scenes per style
    assert len(state["shots"]) == 18
    assert {a["style"] for a in state["assets"]} == {"comic", "realistic"}


def test_generation_requires_review_gates(engine):
    project, ep = setup_episode(engine)
    with pytest.raises(Conflict, match="script"):
        engine.run(ep["id"], "assets")
    engine.approve(ep["id"], "script")
    with pytest.raises(Conflict, match="assets"):
        engine.run(ep["id"], "sample")
    with pytest.raises(Conflict, match="参考图"):
        engine.approve(ep["id"], "assets")


def test_duplicate_scheduling_reuses_job_identity(engine):
    project, ep = setup_episode(engine)
    first = asset_job(engine, project, ep)
    again = engine.run(ep["id"], "assets")
    assert first["id"] == again[0]["id"]
    assert len(engine.snapshot(project["id"])["jobs"]) == 4


def test_single_shot_edit_preserves_other_sources_and_versions(engine):
    project, ep = setup_episode(engine)
    ready_assets(engine, ep)
    original = engine.run(ep["id"], "sample")
    shot, other = engine.snapshot(project["id"])["shots"][:2]
    value = editable(shot, SHOT_FIELDS)
    value.pop("order")
    value["visual"] = "改成雨夜的近景"
    engine.update_shot(shot["id"], value)
    state = engine.snapshot(project["id"])
    current = next(s for s in state["shots"] if s["id"] == shot["id"])
    untouched = next(s for s in state["shots"] if s["id"] == other["id"])
    assert current["version"] == 2
    assert untouched == other
    assert state["episodes"][0]["gates"]["storyboard"] is False
    engine.approve(ep["id"], "storyboard")
    after = engine.run(ep["id"], "sample")
    assert {j["id"] for j in original if j["entity_id"] == other["id"]} == {j["id"] for j in after if j["entity_id"] == other["id"]}


def test_asset_changes_only_invalidate_dependent_shots(engine):
    project, ep = setup_episode(engine)
    ready_assets(engine, ep)
    state = engine.snapshot(project["id"])
    asset = next(a for a in state["assets"] if a["kind"] == "scene")
    engine.update_asset(asset["id"], editable(asset, ASSET_FIELDS))
    updated = {s["id"]: s for s in engine.snapshot(project["id"])["shots"]}
    for shot in state["shots"]:
        assert updated[shot["id"]]["version"] == shot["version"] + (asset["id"] in shot["asset_ids"])


def test_stale_editor_cannot_overwrite_a_newer_version(engine):
    project, ep = setup_episode(engine)
    asset = engine.snapshot(project["id"])["assets"][0]
    engine.update_asset(asset["id"], editable(asset, ASSET_FIELDS))
    with pytest.raises(Conflict):
        engine.update_asset(asset["id"], editable(asset, ASSET_FIELDS))


class PaidFake(Provider):
    mode = "live"

    def estimate(self, op, payload):
        return 6


def test_atomic_budget_reservation_under_competing_workers(engine):
    project, ep = setup_episode(engine, budget=10)
    engine.provider = PaidFake(engine.store)
    asset_job(engine, project, ep)
    other = Engine(engine.store, engine.provider)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda e: e.claim(), [engine, other]))
    assert sum(j is not None for j in claims) == 1
    assert engine.snapshot(project["id"])["budget"]["reserved"] == 6
    assert any(j["status"] == "paused" for j in engine.snapshot(project["id"])["jobs"])


def test_restart_preserves_unknown_submission_and_budget(engine):
    project, ep = setup_episode(engine)
    engine.provider = PaidFake(engine.store)
    asset_job(engine, project, ep)
    job = engine.claim()
    restarted = Engine(Store(engine.store.root), engine.provider)
    restarted.recover()
    state = restarted.snapshot(project["id"])
    recovered = next(j for j in state["jobs"] if j["id"] == job["id"])
    assert recovered["status"] == "reconcile"
    assert recovered["reserved"] == 6


class Ambiguous(PaidFake):
    async def submit(self, job, payload):
        raise httpx.ReadTimeout("submission response lost")


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("lost"), ValueError("invalid response JSON")])
def test_ambiguous_paid_submission_is_never_auto_retried(engine, failure):
    class Broken(Ambiguous):
        async def submit(self, job, payload):
            raise failure
    project, ep = setup_episode(engine)
    engine.provider = Broken(engine.store)
    asset_job(engine, project, ep)
    job = engine.claim()
    asyncio.run(engine.execute(job))
    state = engine.snapshot(project["id"])
    job = next(j for j in state["jobs"] if j["id"] == job["id"])
    assert job["status"] == "reconcile"
    assert job["attempts"] == 1
    assert job["reserved"] == 6


def test_rate_limit_has_two_retries_and_does_not_spend_budget(engine):
    class Limited(PaidFake):
        async def submit(self, job, payload):
            raise RateLimited("429")
    project, ep = setup_episode(engine)
    engine.provider = Limited(engine.store)
    job = asset_job(engine, project, ep)
    with engine.store.transaction() as db:
        for other in engine.store.list(db, "job"):
            if other["id"] != job["id"]:
                other["status"] = "cancelled"
                engine.store.put(db, "job", other)
    for _ in range(3):
        with engine.store.transaction() as db:
            current = engine.store.get(db, "job", job["id"])
            current["next_at"] = 0
            engine.store.put(db, "job", current)
        claimed = engine.claim()
        assert claimed["id"] == job["id"]
        asyncio.run(engine.execute(claimed))
    result = next(j for j in engine.snapshot(project["id"])["jobs"] if j["id"] == job["id"])
    assert result["attempts"] == 3
    assert result["status"] == "failed"
    assert result["spent"] == result["reserved"] == 0


def test_restart_queries_existing_remote_instead_of_submitting(engine):
    class PollOnly(PaidFake):
        async def submit(self, job, payload):
            pytest.fail("must not submit again")
        async def poll(self, job, payload):
            return {"done": False, "remote": job["remote"]}
    project, ep = setup_episode(engine)
    engine.provider = PollOnly(engine.store)
    job = asset_job(engine, project, ep)
    job = engine.claim()
    with engine.store.transaction() as db:
        for other in engine.store.list(db, "job"):
            if other["id"] != job["id"]:
                other["status"] = "cancelled"
                engine.store.put(db, "job", other)
        job["remote"] = {"request_id": "original"}
        engine.store.put(db, "job", job)
    engine.recover()
    asyncio.run(engine.execute(engine.claim()))
    current = next(j for j in engine.snapshot(project["id"])["jobs"] if j["id"] == job["id"])
    assert current["status"] == "submitted"
    assert current["remote"]["request_id"] == "original"


def test_old_result_is_retained_but_cannot_overwrite_edited_asset(engine):
    project, ep = setup_episode(engine)
    job = asset_job(engine, project, ep)
    job = engine.claim()
    asset = next(a for a in engine.snapshot(project["id"])["assets"] if a["id"] == job["entity_id"])
    engine.update_asset(asset["id"], editable(asset, ASSET_FIELDS))
    asyncio.run(engine.execute(job))
    state = engine.snapshot(project["id"])
    assert next(j for j in state["jobs"] if j["id"] == job["id"])["status"] == "obsolete"
    assert not next(a for a in state["assets"] if a["id"] == asset["id"])["image"]


def test_portrait_cache_change_archives_prior_outputs(tmp_path):
    ensure_workspace_revision(tmp_path, {"frame_size": "1280x720"})
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "video.mp4").write_bytes(b"original")
    (tmp_path / "storyboard.json").write_text("[]")
    ensure_workspace_revision(tmp_path, {"frame_size": "1280x720"})
    assert (tmp_path / "shots" / "video.mp4").exists()
    ensure_workspace_revision(tmp_path, {"frame_size": "720x1280"})
    assert not (tmp_path / "shots").exists()
    assert next((tmp_path / ".history").glob("*/shots/video.mp4")).read_bytes() == b"original"


def test_api_validation_origin_and_path_guards(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        assert client.post("/api/drama/projects", json={"name": "p", "budget": -1}).status_code == 422
        assert client.post("/api/drama/projects", json={"name": "p"}, headers={"Origin": "https://other.test"}).status_code == 403
        assert client.put("/api/drama/config", json={"api_key": "never-store-this"}).status_code == 400
        assert client.put("/api/drama/config", json={"cost_ceiling_cny": {"video": "NaN"}}).status_code == 400
        assert client.get("/api/drama/media/%2e%2e%2Fworkbench.sqlite3").status_code == 400


def test_script_revision_archives_shots_and_allows_replanning(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    engine = app.state.engine
    project, ep = setup_episode(engine)
    with TestClient(app) as client:
        assert client.put(f"/api/drama/episodes/{ep['id']}/script", json={"script": DEMO_SCRIPT + "动作：列车远去。"}).status_code == 200
    assert not engine.snapshot(project["id"])["shots"]
    assert engine.plan(ep["id"])["status"] == "queued"


def test_cloud_adapters_keep_secrets_out_of_payload_and_use_measured_voice(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-token")
    provider = CloudProvider(Store(tmp_path), {"cosyvoice_endpoint": "https://example.test/tts", "dashscope_api_key": "test-token"})
    captured = {}
    async def request(method, url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, json={"request_id": "voice-1", "output": {"audio": {"url": "https://example.test/voice.wav"}}})
    provider.request = request
    output = asyncio.run(provider.submit({"op": "tts", "id": "a"}, {"dialogue": "你好", "voice": "longxiaochun"}))
    assert output["remote"]["request_id"] == "voice-1"
    assert "test-token" not in json.dumps(output)
    assert captured["json"]["input"]["format"] == "wav"
    assert captured["json"]["input"]["voice"] == "longxiaochun"


def test_review_is_bound_to_the_generated_clip_not_only_the_shot(engine):
    project, ep = setup_episode(engine)
    with engine.store.transaction() as db:
        shot = engine.shots(db, ep["id"])[0]
        shot["outputs"]["qc"] = {"mechanical_passed": True, "simulated": True, "job_id": "first"}
        engine.store.put(db, "shot", shot)
    engine.review(shot["id"], dict(identity=True, continuity=True, voice=True, dialogue=True, lip_sync=True, note="simulation"))
    with engine.store.transaction() as db:
        shot = engine.store.get(db, "shot", shot["id"])
        assert engine.review_passed(db, shot)
        shot["outputs"]["qc"]["job_id"] = "second"
        assert not engine.review_passed(db, shot)


def test_blocked_dependencies_can_continue_after_a_definite_failure_is_fixed(engine):
    project, ep = setup_episode(engine)
    ready_assets(engine, ep)
    jobs = engine.run(ep["id"], "sample")
    target = next(j for j in jobs if j["op"] == "video")
    with engine.store.transaction() as db:
        for job in engine.store.list(db, "job"):
            if job["id"] == target["id"]:
                continue
            job["status"] = "failed" if job["id"] == target["dependencies"][0] else "succeeded" if job["id"] == target["dependencies"][1] else "cancelled"
            engine.store.put(db, "job", job)
    assert engine.claim() is None
    with engine.store.transaction() as db:
        assert engine.store.get(db, "job", target["id"])["status"] == "blocked"
        dep = engine.store.get(db, "job", target["dependencies"][0])
        dep["status"] = "succeeded"
        engine.store.put(db, "job", dep)
    assert engine.claim()["id"] == target["id"]


@pytest.mark.parametrize("op", ["asset_image", "keyframe", "video", "lipsync"])
def test_fal_adapters_submit_once_then_retrieve_original_result(tmp_path, monkeypatch, op):
    monkeypatch.setenv("FAL_KEY", "not-a-real-key")
    store = Store(tmp_path)
    provider = CloudProvider(store, {"fal_key": "not-a-real-key"})
    media_folder = store.media_path("input")
    media_folder.mkdir()
    (media_folder / "image.png").write_bytes(b"image")
    (media_folder / "video.mp4").write_bytes(b"video")
    (media_folder / "voice.wav").write_bytes(b"audio")
    calls = []
    async def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "POST":
            return httpx.Response(200, json={"request_id": "existing-request", "status_url": "https://queue.fal.run/model/requests/existing-request/status",
                                            "response_url": "https://queue.fal.run/model/requests/existing-request"})
        if url.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if "queue.fal.run" in url:
            return httpx.Response(200, json={"images": [{"url": "https://media.example/result"}], "video": {"url": "https://media.example/result"}, "seed": 123})
        return httpx.Response(200, content=b"generated-result")
    provider.request = request
    payload = {"aspect": "9:16", "style": "realistic", "duration": 7.2, "prompt": "Test shot", "references": ["input/image.png"],
               "image": "input/image.png", "video": "input/video.mp4", "audio": "input/voice.wav"}
    job = {"op": op, "id": "job"}
    submission = asyncio.run(provider.submit(job, payload))
    job["remote"] = submission["remote"]
    result = asyncio.run(provider.poll(job, payload))
    assert result["done"]
    assert result["result"]["request_id"] == "existing-request"
    assert result["result"]["seed"] == 123
    assert len([c for c in calls if c[0] == "POST"]) == 1
    if op in ("asset_image", "keyframe"):
        assert calls[0][2]["json"]["image_urls"][0].startswith("data:image/png;base64,")
    if op == "video":
        assert calls[0][2]["json"]["duration"] == "8"
        assert calls[0][2]["json"]["aspect_ratio"] == "9:16"
        assert calls[0][2]["json"]["generate_audio"] is False


def test_lipsync_padding_preserves_voice_and_adds_silence_instead_of_looping(tmp_path):
    import wave
    from workbench.media import pad_voice, wav_duration, write_srt
    source, padded = tmp_path / "voice.wav", tmp_path / "padded.wav"
    original = b"\x01\x02" * 24000
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(original)
    pad_voice(source, padded, 3.25)
    assert wav_duration(source) == 1
    assert wav_duration(padded) == 3.25
    with wave.open(str(padded), "rb") as audio:
        assert audio.readframes(24000) == original
        assert set(audio.readframes(54000)) == {0}
    subtitle = tmp_path / "subtitles.srt"
    write_srt(subtitle, [{"duration": 3.25, "speech_duration": 1, "dialogue": "你好"}])
    assert "00:00:01,000" in subtitle.read_text(encoding="utf-8")


def test_verified_invoice_updates_actual_cost_and_releases_estimate(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    engine = app.state.engine
    project, ep = setup_episode(engine)
    job = asset_job(engine, project, ep)
    with engine.store.transaction() as db:
        job.update(status="succeeded", spent=6, reserved=0)
        engine.store.put(db, "job", job)
    with TestClient(app) as client:
        response = client.patch(f"/api/drama/jobs/{job['id']}/cost", json={"actual_cost": 2.5})
        assert response.status_code == 200
    budget = engine.snapshot(project["id"])["budget"]
    assert budget["actual_known"] == budget["spent_ceiling"] == 2.5
    assert budget["remaining"] == 47.5


def test_revoking_a_gate_pauses_pending_generation_until_reapproved(engine):
    project, ep = setup_episode(engine)
    ready_assets(engine, ep)
    engine.run(ep["id"], "sample")
    with engine.store.transaction() as db:
        current = engine.store.get(db, "episode", ep["id"])
        current["approvals"].pop("storyboard")
        engine.store.put(db, "episode", current)
    assert engine.claim() is None
    assert engine.snapshot(project["id"])["budget"]["reserved"] == 0
    engine.approve(ep["id"], "storyboard")
    assert engine.claim()["status"] == "running"
