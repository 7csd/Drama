import asyncio
import copy
import json
import re
import time
import logging
from pathlib import Path

from .media import bundle, compose, pad_voice
from .providers import Provider, RateLimited, Rejected, RemoteFailed, load_provider
from .store import digest, uid


class Conflict(ValueError):
    pass


ASSET_FIELDS = ("name", "description", "costume", "voice", "style", "kind")
SHOT_FIELDS = ("visual", "dialogue", "speaker_id", "asset_ids", "duration", "framing", "sample", "order")
STYLE_NAMES = {"comic": "二维动画，统一线条、色彩、人物比例", "realistic": "写实电影，真实皮肤、自然灯光、稳定人物外观"}
TERMINAL = {"succeeded", "failed", "obsolete", "cancelled"}


def source_hash(item, kind):
    fields = ASSET_FIELDS if kind == "asset" else SHOT_FIELDS if kind == "shot" else ("script", "style", "aspect", "target_duration")
    return digest({key: item.get(key) for key in fields})


def parse_script(script, target_duration):
    """Transparent local parser; does not claim to generate or understand a screenplay."""
    characters, scenes, shots = [], [], []
    scene = "默认场景"
    framings = ["closeup", "two_shot", "profile", "action", "transition"]
    for line in script.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"[【\[]道具[：:]", line):
            continue
        match = re.match(r"[【\[]场景[：:](.+?)[】\]]$", line)
        if match:
            scene = match[1].strip()
            if scene not in scenes:
                scenes.append(scene)
            continue
        if scene not in scenes:
            scenes.append(scene)
        match = re.match(r"([^：:\n]{1,20})[：:](.+)$", line)
        speaker = match[1].strip() if match and match[1].strip() not in ("动作", "旁白", "画外音") else None
        dialogue = match[2].strip() if speaker else ""
        if speaker and speaker not in characters:
            characters.append(speaker)
        shots.append({"visual": line, "dialogue": dialogue, "speaker": speaker, "scene": scene,
                      "framing": framings[len(shots) % len(framings)]})
    if not shots:
        raise ValueError("剧本没有可拆解的内容")
    if len(shots) > 100:
        raise ValueError("首版单集最多 100 镜，请按集拆分剧本")
    for shot in shots:
        shot["duration"] = max(2, round(target_duration / len(shots), 2), len(shot["dialogue"]) / 4.5 + 0.3)
    props = []
    for line in script.splitlines():
        match = re.match(r"[【\[]道具[：:](.+?)[】\]]$", line.strip())
        if match:
            props.extend({"name": name.strip(), "description": name.strip()} for name in re.split(r"[、,，]", match[1]) if name.strip())
    return {"characters": [{"name": name, "description": f"{name}，请补充外观和身份设定"} for name in characters],
            "scenes": [{"name": name, "description": name} for name in scenes], "props": props, "shots": shots, "simulated": True}


class Engine:
    def __init__(self, store, provider=None):
        self.store = store
        self.provider = provider or load_provider(store)
        self.running = set()

    def create_project(self, data):
        with self.store.transaction() as db:
            return self.store.put(db, "project", {**data, "currency": "CNY"})

    def create_episode(self, project_id, data):
        with self.store.transaction() as db:
            self.store.get(db, "project", project_id)
            return self.store.put(db, "episode", {**data, "project_id": project_id, "approvals": {}, "planned_hash": None})

    def shots(self, db, episode_id):
        return sorted((s for s in self.store.list(db, "shot", episode_id=episode_id) if not s.get("archived")), key=lambda s: s["order"])

    def used_assets(self, db, ep):
        ids = {id for shot in self.shots(db, ep["id"]) for id in shot["asset_ids"]}
        return [a for a in self.store.list(db, "asset", project_id=ep["project_id"]) if a["id"] in ids]

    def gate_hash(self, db, ep, gate):
        if gate == "script":
            return digest({"script": ep["script"], "style": ep["style"]})
        if gate == "assets":
            return digest([{**{k: a.get(k) for k in ASSET_FIELDS}, "id": a["id"], "image": a.get("image")}
                           for a in self.used_assets(db, ep)])
        shots = self.shots(db, ep["id"])
        if gate == "storyboard":
            return digest({"shots": [source_hash(s, "shot") for s in shots], "assets": self.gate_hash(db, ep, "assets"),
                           "script": self.gate_hash(db, ep, "script"), "aspect": ep["aspect"]})
        return digest({"board": self.gate_hash(db, ep, "storyboard"), "reviews": [(s.get("review_id"), s.get("outputs", {}).get("qc", {}).get("job_id")) for s in shots if s["sample"]]})

    def approved(self, db, ep, gate):
        return ep.get("approvals", {}).get(gate, {}).get("digest") == self.gate_hash(db, ep, gate)

    def require(self, db, ep, *gates):
        if ep.get("planned_hash") != source_hash(ep, "episode"):
            raise Conflict("剧本已变更或尚未拆解，请先拆解并审阅")
        for gate in gates:
            if not self.approved(db, ep, gate):
                raise Conflict(f"请先完成 {gate} 审阅确认")

    def budget(self, db, project_id):
        project = self.store.get(db, "project", project_id)
        jobs = self.store.list(db, "job", project_id=project_id)
        held = sum(j.get("reserved", 0) for j in jobs)
        spent = sum(j.get("spent", 0) for j in jobs)
        actual = sum(j.get("actual_cost", 0) or 0 for j in jobs)
        unknown = sum(1 for j in jobs if j.get("spent", 0) > 0 and j.get("actual_cost") is None)
        return {"limit": project["budget"], "reserved": round(held, 4), "spent_ceiling": round(spent, 4),
                "actual_known": round(actual, 4), "unreconciled": unknown,
                "remaining": round(project["budget"] - held - spent, 4), "currency": "CNY"}

    def snapshot(self, project_id):
        with self.store.transaction() as db:
            project = self.store.get(db, "project", project_id)
            episodes = self.store.list(db, "episode", project_id=project_id)
            for ep in episodes:
                ep["gates"] = {g: self.approved(db, ep, g) for g in ("script", "assets", "storyboard", "sample")}
            return {"project": project, "episodes": episodes, "assets": self.store.list(db, "asset", project_id=project_id),
                    "shots": [s for s in self.store.list(db, "shot", project_id=project_id) if not s.get("archived")], "jobs": self.store.list(db, "job", project_id=project_id),
                    "reviews": self.store.list(db, "review", project_id=project_id), "budget": self.budget(db, project_id)}

    def plan(self, episode_id):
        with self.store.transaction() as db:
            ep = self.store.get(db, "episode", episode_id)
            if self.shots(db, episode_id):
                raise Conflict("已有分镜，请编辑现有分镜；重建剧本请新建一集，以保留历史")
            return self.enqueue(db, ep, "plan", "episode", ep,
                                {"script": ep["script"], "style": ep["style"], "aspect": ep["aspect"], "target_duration": ep["target_duration"]}, [])

    def apply_plan(self, db, ep, plan):
        asset_by_name = {}
        existing = self.store.list(db, "asset", project_id=ep["project_id"])
        for kind, entries in (("character", plan["characters"]), ("scene", plan["scenes"]), ("prop", plan.get("props", []))):
            for idx, entry in enumerate(entries):
                shared = next((a for a in existing if a["name"] == entry["name"] and a["kind"] == kind and a["style"] == ep["style"]), None)
                asset = shared or self.store.put(db, "asset", {"project_id": ep["project_id"], "kind": kind,
                    "name": entry["name"], "description": entry["description"], "costume": "",
                    "voice": "longxiaochun" if idx % 2 == 0 else "longxiaocheng", "style": ep["style"],
                    "image": None, "simulated": plan.get("simulated", False)})
                asset_by_name[(kind, entry["name"])] = asset["id"]
        seen_scenes = set()
        for idx, spec in enumerate(plan["shots"]):
            speaker = asset_by_name.get(("character", spec.get("speaker")))
            if spec.get("dialogue") and not speaker:
                raise ValueError(f"镜头 {idx + 1} 的对白缺少有效角色")
            scene = asset_by_name.get(("scene", spec.get("scene")))
            if not scene:
                raise ValueError(f"镜头 {idx + 1} 缺少场景")
            cast = spec.get("characters") or ([spec["speaker"]] if speaker else [c["name"] for c in plan["characters"]])
            unknown = [n for n in cast if ("character", n) not in asset_by_name]
            unknown.extend(n for n in spec.get("props", []) if ("prop", n) not in asset_by_name)
            if unknown:
                raise ValueError("分镜引用了未定义资产：" + "、".join(unknown))
            refs = [asset_by_name[("character", n)] for n in cast if ("character", n) in asset_by_name]
            refs.extend(asset_by_name[("prop", n)] for n in spec.get("props", []) if ("prop", n) in asset_by_name)
            sample = idx < 5 or scene not in seen_scenes
            seen_scenes.add(scene)
            self.store.put(db, "shot", {"project_id": ep["project_id"], "episode_id": ep["id"], "order": idx,
                "visual": spec["visual"], "dialogue": spec.get("dialogue", ""), "speaker_id": speaker,
                "asset_ids": list(dict.fromkeys(refs + [scene] + ([speaker] if speaker else []))),
                "duration": min(30, max(1, spec["duration"])), "framing": spec.get("framing", "closeup"),
                "sample": sample, "outputs": {}, "review_id": None})
        ep["planned_hash"] = source_hash(ep, "episode")
        ep["plan_simulated"] = plan.get("simulated", False)
        self.store.put(db, "episode", ep)

    def update_shot(self, id, data):
        with self.store.transaction() as db:
            shot = self.store.get(db, "shot", id)
            if shot["version"] != data.pop("version"):
                raise Conflict("镜头已被更新，请刷新后重试")
            ep = self.store.get(db, "episode", shot["episode_id"])
            for ref in data["asset_ids"]:
                asset = self.store.get(db, "asset", ref)
                if asset["project_id"] != ep["project_id"] or asset["style"] != ep["style"]:
                    raise ValueError("参考资产必须属于同一项目和风格")
            if data["dialogue"]:
                if data["speaker_id"] not in data["asset_ids"]:
                    raise ValueError("对白说话人必须绑定到镜头参考资产")
                if self.store.get(db, "asset", data["speaker_id"])["kind"] != "character":
                    raise ValueError("说话人必须是角色")
            shot.update(data, outputs={}, review_id=None)
            shot = self.store.put(db, "shot", shot, bump=True)
            self.invalidate(db, ep, ["storyboard", "sample"])
            return shot

    def invalidate(self, db, ep, gates):
        for gate in gates:
            ep["approvals"].pop(gate, None)
        ep.pop("delivery", None)
        self.store.put(db, "episode", ep)

    def update_asset(self, id, data):
        with self.store.transaction() as db:
            asset = self.store.get(db, "asset", id)
            if asset["version"] != data.pop("version"):
                raise Conflict("资产已被更新，请刷新后重试")
            asset.update(data)
            asset["image"] = None
            asset = self.store.put(db, "asset", asset, bump=True)
            self.invalidate_asset(db, asset)
            return asset

    def invalidate_asset(self, db, asset):
        affected = set()
        for shot in self.store.list(db, "shot", project_id=asset["project_id"]):
            if asset["id"] in shot["asset_ids"]:
                shot.update(outputs={}, review_id=None)
                self.store.put(db, "shot", shot, bump=True)
                affected.add(shot["episode_id"])
        for id in affected:
            self.invalidate(db, self.store.get(db, "episode", id), ["assets", "storyboard", "sample"])

    def approve(self, episode_id, gate):
        if gate not in ("script", "assets", "storyboard", "sample"):
            raise ValueError("未知的审阅阶段")
        with self.store.transaction() as db:
            ep = self.store.get(db, "episode", episode_id)
            self.require(db, ep, *({"script": [], "assets": ["script"], "storyboard": ["script", "assets"],
                                  "sample": ["script", "assets", "storyboard"]}[gate]))
            if gate == "assets":
                assets = self.used_assets(db, ep)
                if not assets or any(not a.get("image") or (a["kind"] == "character" and not a.get("voice")) for a in assets):
                    raise Conflict("请先生成／上传全部参考图，并绑定角色音色")
            if gate == "sample":
                samples = [s for s in self.shots(db, episode_id) if s["sample"]]
                if not samples or any(not self.review_passed(db, s) for s in samples):
                    raise Conflict("请先对全部样镜完成五项人工审片")
            review = self.store.put(db, "review", {"project_id": ep["project_id"], "episode_id": ep["id"],
                "stage": gate, "digest": self.gate_hash(db, ep, gate), "mode": self.provider.mode})
            ep["approvals"][gate] = {"digest": review["digest"], "review_id": review["id"]}
            return self.store.put(db, "episode", ep)

    def review_passed(self, db, shot):
        if not shot.get("review_id") or not shot.get("outputs", {}).get("qc", {}).get("mechanical_passed"):
            return False
        review = self.store.get(db, "review", shot["review_id"])
        return (review["source_hash"] == source_hash(shot, "shot")
                and review.get("qc_job_id") == shot["outputs"]["qc"].get("job_id")
                and review.get("mode") == self.provider.mode
                and all(review[k] for k in ("identity", "continuity", "voice", "dialogue", "lip_sync")))

    def review(self, shot_id, data):
        with self.store.transaction() as db:
            shot = self.store.get(db, "shot", shot_id)
            if not shot.get("outputs", {}).get("qc", {}).get("mechanical_passed"):
                raise Conflict("镜头素材尚未完成机械检查")
            if shot["outputs"]["qc"].get("simulated") != (self.provider.mode == "mock"):
                raise Conflict("当前素材与生产模式不一致，请按当前模式重新生成")
            review = self.store.put(db, "review", {**data, "project_id": shot["project_id"], "episode_id": shot["episode_id"],
                "shot_id": shot_id, "source_hash": source_hash(shot, "shot"), "mode": self.provider.mode,
                "qc_job_id": shot["outputs"]["qc"].get("job_id")})
            shot["review_id"] = review["id"]
            self.store.put(db, "shot", shot)
            ep = self.store.get(db, "episode", shot["episode_id"])
            self.invalidate(db, ep, ["sample"] if shot["sample"] else [])
            return review

    def enqueue(self, db, ep, op, kind, item, payload, deps):
        src = source_hash(item, kind)
        key = digest({"workflow_version": 1, "op": op, "item": item["id"], "version": item["version"], "source": src, "payload": payload,
                      "deps": deps, "provider": self.provider.signature})
        old = next((j for j in self.store.list(db, "job", episode_id=ep["id"]) if j["cache_key"] == key and j["status"] != "cancelled"), None)
        if old:
            return old
        self.provider.validate(op, payload)
        cost = self.provider.estimate(op, payload)
        return self.store.put(db, "job", {"project_id": ep["project_id"], "episode_id": ep["id"], "op": op,
            "entity_kind": kind, "entity_id": item["id"], "entity_version": item["version"], "source_hash": src,
            "cache_key": key, "input": payload, "dependencies": deps, "status": "queued", "attempts": 0,
            "requires_sample": (kind == "shot" and not item.get("sample")) or op == "compose",
            "reserved": 0, "spent": 0, "estimate": cost, "provider_mode": self.provider.mode,
            "provider_signature": self.provider.signature, "next_at": 0, "error": None})

    def run(self, episode_id, phase):
        with self.store.transaction() as db:
            ep = self.store.get(db, "episode", episode_id)
            if phase == "assets":
                self.require(db, ep, "script")
                jobs = []
                for asset in self.used_assets(db, ep):
                    if not asset.get("image"):
                        payload = {"prompt": f"{STYLE_NAMES[ep['style']]}。{asset['name']}：{asset['description']}。服装：{asset['costume']}。角色使用清晰设定图，场景无人物。",
                                   "aspect": ep["aspect"], "style": ep["style"]}
                        jobs.append(self.enqueue(db, ep, "asset_image", "asset", asset, payload, []))
                return jobs
            self.require(db, ep, "script", "assets", "storyboard")
            if phase in ("full", "compose"):
                self.require(db, ep, "sample")
            shots = self.shots(db, episode_id)
            if phase == "compose":
                if not shots or any(not self.review_passed(db, s) for s in shots):
                    raise Conflict("请先完成全部镜头的人工审片，再合成")
                total = sum(s["outputs"]["qc"]["duration"] for s in shots)
                if not 60 <= total <= 90:
                    raise Conflict(f"当前总时长 {total:.1f} 秒，首版验收要求 60—90 秒，请调整分镜")
                payload = {"aspect": ep["aspect"], "simulated": self.provider.mode == "mock", "shots": [self.compose_shot(s) for s in shots]}
                return [self.enqueue(db, ep, "compose", "episode", ep, payload, [])]
            jobs = []
            for shot in shots:
                if phase == "sample" and not shot["sample"]:
                    continue
                assets = [self.store.get(db, "asset", ref) for ref in shot["asset_ids"]]
                if self.provider.mode == "live" and any(a.get("simulated") for a in assets):
                    raise Conflict("真实生成不可使用模拟参考图，请上传或重新生成资产")
                speaker = self.store.get(db, "asset", shot["speaker_id"]) if shot["dialogue"] else None
                base = {"aspect": ep["aspect"], "style": ep["style"], "duration": shot["duration"],
                        "references": [a["image"] for a in assets], "asset_versions": {a["id"]: a["version"] for a in assets}}
                audio = self.enqueue(db, ep, "tts", "shot", shot, {**base, "dialogue": shot["dialogue"], "voice": speaker["voice"] if speaker else ""}, [])
                image = self.enqueue(db, ep, "keyframe", "shot", shot, {**base, "prompt": STYLE_NAMES[ep["style"]] + "。" + shot["visual"] + "。保持参考图人物、服装、场景一致。"}, [])
                video = self.enqueue(db, ep, "video", "shot", shot, {**base, "prompt": shot["visual"]}, [audio["id"], image["id"]])
                last = video
                if shot["dialogue"]:
                    last = self.enqueue(db, ep, "lipsync", "shot", shot, base, [audio["id"], video["id"]])
                qc = self.enqueue(db, ep, "qc", "shot", shot, base, [audio["id"], last["id"]])
                jobs.extend([audio, image, video] + ([last] if last is not video else []) + [qc])
            if not jobs:
                raise Conflict("没有选择样镜，请在分镜中勾选")
            return jobs

    def compose_shot(self, shot):
        out = shot["outputs"]
        return {"id": shot["id"], "video": (out.get("lipsync") or out["video"])["path"], "audio": out["tts"]["path"],
                "duration": out["qc"]["duration"], "speech_duration": out["tts"]["duration"], "dialogue": shot["dialogue"]}

    def is_current(self, db, job):
        item = self.store.get(db, job["entity_kind"], job["entity_id"])
        if item.get("archived") or job["entity_version"] != item["version"] or job["source_hash"] != source_hash(item, job["entity_kind"]):
            return False
        ep = self.store.get(db, "episode", job["episode_id"])
        if job["op"] == "asset_image" and ep.get("planned_hash") != source_hash(ep, "episode"):
            return False
        if job["op"] != "plan" and job["op"] != "asset_image":
            for id, version in job["input"].get("asset_versions", {}).items():
                if self.store.get(db, "asset", id)["version"] != version:
                    return False
        if job["op"] == "compose":
            return job["input"]["shots"] == [self.compose_shot(s) for s in self.shots(db, ep["id"]) if s.get("outputs", {}).get("qc")]
        return True

    def recover(self):
        with self.store.transaction() as db:
            for job in self.store.list(db, "job"):
                if job["status"] == "running":
                    if job.get("remote"):
                        job["status"] = "submitted"
                    elif job["provider_mode"] == "mock" or job["op"] in ("compose", "qc"):
                        job["status"] = "queued"
                    else:
                        job.update(status="reconcile", error="服务在提交期间中断，状态未知；请核对服务端任务，禁止自动重投")
                    self.store.put(db, "job", job)

    def claim(self):
        with self.store.transaction() as db:
            all_jobs = self.store.list(db, "job")
            indexed = {j["id"]: j for j in all_jobs}
            for job in all_jobs:
                if job["id"] in self.running or job["status"] not in ("queued", "submitted", "paused", "blocked") or job["next_at"] > time.time():
                    continue
                if job["provider_signature"] != self.provider.signature:
                    job.update(status="paused", error="生成配置已变化；请恢复原配置处理在途任务，或新建任务")
                    self.store.put(db, "job", job)
                    continue
                if not job.get("remote") and not self.is_current(db, job):
                    job["status"] = "obsolete"
                    self.store.put(db, "job", job)
                    continue
                deps = [indexed[id] for id in job["dependencies"]]
                if any(d["status"] in ("failed", "obsolete", "cancelled", "blocked") for d in deps):
                    job.update(status="blocked", error="依赖镜头失败或已过期，请修订后重新生成")
                    self.store.put(db, "job", job)
                    continue
                if any(d["status"] != "succeeded" for d in deps):
                    continue
                if not job.get("remote") and job["op"] != "plan":
                    ep = self.store.get(db, "episode", job["episode_id"])
                    gates = ["script"] if job["op"] == "asset_image" else ["script", "assets", "storyboard"]
                    if job.get("requires_sample"):
                        gates.append("sample")
                    if not all(self.approved(db, ep, g) for g in gates):
                        job.update(status="paused", error="审阅确认已过期，等待重新审阅后继续")
                        self.store.put(db, "job", job)
                        continue
                if not job.get("remote") and not job["reserved"]:
                    remaining = self.budget(db, job["project_id"])["remaining"]
                    if remaining + 1e-8 < job["estimate"]:
                        job.update(status="paused", error="项目预算不足，等待提高预算")
                        self.store.put(db, "job", job)
                        continue
                    job["reserved"] = job["estimate"]
                job.update(status="running", error=None)
                self.store.put(db, "job", job)
                return job
        return None

    def resolve_payload(self, job):
        payload = copy.deepcopy(job["input"])
        with self.store.transaction() as db:
            deps = [self.store.get(db, "job", id) for id in job["dependencies"]]
        by_op = {d["op"]: d["result"] for d in deps}
        audio = by_op.get("tts")
        if audio:
            payload["audio"] = audio["path"]
            payload["duration"] = max(payload["duration"], audio["duration"] + (0.25 if job["op"] != "tts" else 0))
        if "keyframe" in by_op:
            payload["image"] = by_op["keyframe"]["path"]
        video = by_op.get("lipsync") or by_op.get("video")
        if video:
            payload["video"] = video["path"]
        if job["op"] == "lipsync" and audio:
            folder = self.store.media_path(job["id"])
            folder.mkdir(exist_ok=True)
            padded = folder / "padded_voice.wav"
            pad_voice(self.store.media_path(audio["path"]), padded, payload["duration"])
            payload["original_audio"] = audio["path"]
            payload["audio"] = padded.relative_to(self.store.root / "media").as_posix()
        return payload

    async def execute(self, job):
        try:
            payload = self.resolve_payload(job)
            self.provider.validate(job["op"], payload)
            if not job.get("remote"):
                with self.store.transaction() as db:
                    current = self.store.get(db, "job", job["id"])
                    current["attempts"] += 1
                    current["resolved_input"] = payload
                    current["provider_settings"] = self.provider.public_config()
                    current["submission_started"] = self.provider.mode == "live" and job["op"] not in ("compose", "qc")
                    job = self.store.put(db, "job", current)
            if job["op"] == "plan":
                if self.provider.mode == "mock":
                    plan = parse_script(payload["script"], payload["target_duration"])
                else:
                    from .vimax_bridge import plan as vimax_plan
                    plan = await vimax_plan(self.store, job, payload, self.provider.config)
                outcome = {"done": True, "result": plan}
            elif job["op"] == "compose":
                outcome = {"done": True, "result": await compose(self.store, job, payload)}
            elif job["op"] == "qc":
                import imageio_ffmpeg
                def inspect():
                    frames = imageio_ffmpeg.read_frames(str(self.store.media_path(payload["video"])))
                    try:
                        metadata = next(frames)
                        next(frames)  # actually decode a frame, not just the header
                        return metadata
                    finally:
                        frames.close()
                info = await asyncio.to_thread(inspect)
                width, height = info["size"]
                target_ratio = 9 / 16 if payload["aspect"] == "9:16" else 16 / 9
                if abs(width / height - target_ratio) > 0.03:
                    raise ValueError("视频画幅不符合项目要求，请重做镜头")
                if info["duration"] + 0.3 < payload["duration"]:
                    raise ValueError("视频短于对白或计划时长，请拆分或重做镜头")
                outcome = {"done": True, "result": {"mechanical_passed": True, "duration": payload["duration"],
                    "width": width, "height": height, "simulated": self.provider.mode == "mock", "human_required": True,
                    "note": "已检查解码、画幅和时长；人物、声音、剧情及口型须人工审阅"}}
            elif job.get("remote"):
                outcome = await self.provider.poll(job, payload)
            else:
                outcome = await self.provider.submit(job, payload)
            with self.store.transaction() as db:
                job = self.store.get(db, "job", job["id"])
                if not outcome["done"]:
                    job.update(remote=outcome["remote"], status="submitted", next_at=time.time() + 3)
                else:
                    result = outcome["result"]
                    if self.provider.mode == "mock" or job["op"] in ("compose", "qc"):
                        result.setdefault("actual_cost", 0)
                    result["job_id"] = job["id"]
                    job.update(result=result, status="succeeded", spent=job["reserved"], reserved=0,
                               actual_cost=result.get("actual_cost"), finished_at=time.time())
                    if not self.is_current(db, job):
                        job["status"] = "obsolete"
                    else:
                        entity = self.store.get(db, job["entity_kind"], job["entity_id"])
                        if job["op"] == "plan":
                            self.apply_plan(db, entity, result)
                        elif job["op"] == "asset_image":
                            entity.update(image=result["path"], simulated=result["simulated"])
                            self.store.put(db, "asset", entity)
                        elif job["op"] == "compose":
                            self.store.put(db, "job", job)
                            project = self.store.get(db, "project", job["project_id"])
                            result["bundle"] = bundle(self.store, project, entity, self.used_assets(db, entity),
                                self.shots(db, entity["id"]), self.store.list(db, "job", episode_id=entity["id"]),
                                self.store.list(db, "review", episode_id=entity["id"]), result)
                            entity["delivery"] = result
                            self.store.put(db, "episode", entity)
                        else:
                            entity["outputs"][job["op"]] = result
                            self.store.put(db, "shot", entity)
                self.store.put(db, "job", job)
        except asyncio.CancelledError:
            raise  # startup recovery owns interrupted submissions
        except Exception as error:
            with self.store.transaction() as db:
                job = self.store.get(db, "job", job["id"])
                job["error"] = str(error)[:1500]
                if isinstance(error, RemoteFailed):
                    job.update(status="failed", spent=job["spent"] + job["reserved"], reserved=0)
                elif isinstance(error, RateLimited) and (job.get("remote") or job["attempts"] <= 2):
                    job["submission_started"] = False
                    job.update(status="submitted" if job.get("remote") else "queued", next_at=time.time() + 2 ** (job["attempts"] + 1))
                elif job.get("remote"):
                    # A polling/download failure must never resubmit a generation request.
                    job["poll_errors"] = job.get("poll_errors", 0) + 1
                    job.update(status="reconcile" if job["poll_errors"] >= 5 else "submitted", next_at=time.time() + 30)
                elif self.provider.mode == "live" and job.get("submission_started") and not isinstance(error, (Rejected, RateLimited)):
                    job["status"] = "reconcile"
                    job["error"] = "提交状态未知，请核对服务端，未自动重投。" + job["error"]
                else:
                    paid = job.get("submission_started") and not isinstance(error, (Rejected, RateLimited))
                    job.update(status="failed", spent=job["spent"] + (job["reserved"] if paid else 0), reserved=0)
                self.store.put(db, "job", job)

    async def worker(self):
        self.recover()
        tasks = set()
        try:
            while True:
                done = {t for t in tasks if t.done()}
                for task in done:
                    try:
                        task.result()
                    except Exception:
                        logging.exception("Unexpected production worker error; other tasks will continue")
                tasks -= done
                while len(tasks) < 2:
                    job = self.claim()
                    if not job:
                        break
                    self.running.add(job["id"])
                    async def run_one(j):
                        try:
                            await self.execute(j)
                        finally:
                            self.running.discard(j["id"])
                    tasks.add(asyncio.create_task(run_one(job)))
                await asyncio.sleep(0.3)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
