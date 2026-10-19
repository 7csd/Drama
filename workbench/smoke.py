"""Offline, real-FFmpeg acceptance exercise. Never uses cloud providers."""
import argparse
import asyncio
import json
from pathlib import Path

from .engine import Engine
from .models import DEMO_SCRIPT
from .providers import Provider
from .store import Store


async def drain(engine):
    count = 0
    while job := engine.claim():
        await engine.execute(job)
        count += 1
        if count > 500:
            raise RuntimeError("任务未收敛")
    with engine.store.transaction() as db:
        failures = [j for j in engine.store.list(db, "job") if j["status"] in ("failed", "blocked", "reconcile", "paused")]
    if failures:
        raise RuntimeError(json.dumps(failures, ensure_ascii=False, indent=2))


async def main(root):
    store = Store(root)
    engine = Engine(store, Provider(store))
    project = engine.create_project({"name": "离线验收 · 旧信", "budget": 50})
    for style in ("comic", "realistic"):
        style_name = "动态漫" if style == "comic" else "写实短剧"
        ep = engine.create_episode(project["id"], {"title": f"第一集 · {style_name}", "style": style,
            "script": DEMO_SCRIPT, "target_duration": 75, "aspect": "9:16"})
        engine.plan(ep["id"])
        await drain(engine)
        engine.approve(ep["id"], "script")
        engine.run(ep["id"], "assets")
        await drain(engine)
        engine.approve(ep["id"], "assets")
        engine.approve(ep["id"], "storyboard")
        engine.run(ep["id"], "sample")
        await drain(engine)
        def review(samples_only):
            for shot in engine.snapshot(project["id"])["shots"]:
                if shot["episode_id"] == ep["id"] and (shot["sample"] or not samples_only):
                    engine.review(shot["id"], {"identity": True, "continuity": True, "voice": True, "dialogue": True,
                        "lip_sync": True, "note": "自动化流程模拟；占位素材不代表真实人物、语音或口型质量"})
        review(True)
        engine.approve(ep["id"], "sample")
        before = {j["id"] for j in engine.snapshot(project["id"])["jobs"]}
        engine.run(ep["id"], "full")
        await drain(engine)
        # Review only the non-sample shots: re-reviewing samples intentionally invalidates their gate.
        for shot in engine.snapshot(project["id"])["shots"]:
            if shot["episode_id"] == ep["id"] and not shot["sample"]:
                engine.review(shot["id"], {"identity": True, "continuity": True, "voice": True, "dialogue": True,
                    "lip_sync": True, "note": "仅验证模拟审阅操作"})
        engine.run(ep["id"], "compose")
        await drain(engine)
        current = next(e for e in engine.snapshot(project["id"])["episodes"] if e["id"] == ep["id"])
        assert 60 <= current["delivery"]["duration"] <= 90
        assert store.media_path(current["delivery"]["bundle"]).is_file()
        print(f"{style}: {current['delivery']['duration']:.2f}s {store.media_path(current['delivery']['path'])}", flush=True)
    state = engine.snapshot(project["id"])
    (store.root / "acceptance-report.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    assert state["budget"]["spent_ceiling"] == 0
    print(f"PASS: {len(state['jobs'])} jobs, 2 exports, no cloud calls", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=".drama-validation")
    asyncio.run(main(Path(parser.parse_args().data)))
