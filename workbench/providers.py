"""Cloud adapters. Local simulation never imports SDKs or sends network requests."""
import asyncio
import base64
import json
import math
import os
import re
import shutil
import wave
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from .media import dimensions, ffmpeg, wav_duration
from .store import digest


class RateLimited(Exception):
    pass


class Rejected(Exception):
    """A definite rejection before a provider accepted a paid request."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class RemoteFailed(Exception):
    pass


class Provider:
    mode = "mock"

    def __init__(self, store, config=None):
        self.store = store
        self.config = config or {}

    @property
    def signature(self):
        plan_config = Path(self.config.get("vimax_config", "configs/agent.local.yaml"))
        config_hash = digest(plan_config.read_text(encoding="utf-8")) if plan_config.is_file() else None
        return digest({"mode": self.mode, "config": self.public_config(), "planning_config_hash": config_hash})

    def public_config(self):
        allowed = ("cost_ceiling_cny", "vimax_config", "image_model", "image_edit_model", "video_model",
                   "voice_model", "cosyvoice_endpoint", "lipsync_models")
        return {k: v for k, v in self.config.items() if k in allowed}

    def estimate(self, op, payload):
        return 0.0

    def validate(self, op, payload):
        pass

    async def submit(self, job, payload):
        folder = self.store.media_path(job["id"])
        folder.mkdir(exist_ok=True)
        op = job["op"]
        width, height = dimensions(payload.get("aspect", "9:16"))
        result = {"simulated": True, "provider": "local-simulation", "actual_cost": 0}
        if op in ("asset_image", "keyframe"):
            image = Image.new("RGB", (width, height), "#142638" if payload.get("style") == "realistic" else "#24433b")
            draw = ImageDraw.Draw(image)
            font_path = next((p for p in ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if Path(p).exists()), None)
            font = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
            draw.rounded_rectangle((48, 70, width - 48, height - 70), radius=24, outline="#a5d7bb", width=2)
            draw.text((75, 115), "流程模拟 / SIMULATION", font=font, fill="#c9f8d9")
            text = payload.get("prompt", "")
            lines = [text[i:i + 18] for i in range(0, min(len(text), 240), 18)]
            draw.multiline_text((75, 210), "\n".join(lines), font=font, fill="white", spacing=18)
            draw.text((75, height - 150), "占位素材 · 非模型生成画面", font=font, fill="#a5d7bb")
            image.save(folder / "image.png")
            result["path"] = f"{job['id']}/image.png"
        elif op == "tts":
            duration = max(1, len(payload.get("dialogue", "")) / 4.5) if payload.get("dialogue") else payload["duration"]
            with wave.open(str(folder / "voice.wav"), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * round(duration * 24000))
            result.update(path=f"{job['id']}/voice.wav", duration=duration, warning="静音占位，不验证声音或口型")
        elif op == "video":
            await ffmpeg(["-loop", "1", "-i", self.store.media_path(payload["image"]), "-t", payload["duration"],
                          "-r", "24", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", folder / "video.mp4"])
            result.update(path=f"{job['id']}/video.mp4", duration=payload["duration"])
        elif op == "lipsync":
            shutil.copyfile(self.store.media_path(payload["video"]), folder / "lipsync.mp4")
            result.update(path=f"{job['id']}/lipsync.mp4", duration=payload["duration"], warning="未执行真实口型同步")
        return {"done": True, "result": result}


class CloudProvider(Provider):
    mode = "live"

    def estimate(self, op, payload):
        if op in ("qc", "compose") or (op == "tts" and not payload.get("dialogue")):
            return 0
        value = self.config.get("cost_ceiling_cny", {}).get(op)
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"请为 {op} 配置单次调用人民币费用上限 cost_ceiling_cny（含模型最大时长）")
        return float(value)

    def validate(self, op, payload):
        if op == "plan":
            import importlib.util
            if importlib.util.find_spec("langchain") is None:
                raise ValueError("尚未安装 ViMax 生成依赖，请按 README_WORKBENCH.md 安装")
            if not Path(self.config.get("vimax_config", "configs/agent.local.yaml")).is_file():
                raise ValueError("缺少 ViMax 本地配置文件（chat_model.init_args）")
        if op in ("asset_image", "keyframe", "video", "lipsync"):
            if not os.environ.get("FAL_KEY"):
                raise ValueError("缺少 FAL_KEY 环境变量")
        if op == "tts" and payload.get("dialogue"):
            if not os.environ.get("DASHSCOPE_API_KEY") or not self.config.get("cosyvoice_endpoint"):
                raise ValueError("请配置 DASHSCOPE_API_KEY 和 cosyvoice_endpoint")
        if op == "video" and payload.get("duration", 0) > 15:
            raise ValueError("当前 Seedance 适配器单镜最长 15 秒，请拆分对白／镜头")

    async def request(self, method, url, **kwargs):
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.request(method, url, **kwargs)
        if response.status_code == 429:
            raise RateLimited("服务限流，稍后重试")
        if 400 <= response.status_code < 500:
            raise Rejected(f"服务拒绝请求（HTTP {response.status_code}）", response.status_code)
        response.raise_for_status()
        return response

    async def download(self, job, url, name):
        from urllib.parse import urlsplit
        if urlsplit(url).scheme not in ("https", "http"):
            raise ValueError("模型未返回有效素材 URL")
        response = await self.request("GET", url)
        folder = self.store.media_path(job["id"])
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(response.content)
        return f"{job['id']}/{name}"

    def data_uri(self, path):
        mime = "audio/wav" if str(path).endswith(".wav") else "video/mp4" if str(path).endswith(".mp4") else "image/png"
        return f"data:{mime};base64," + base64.b64encode(self.store.media_path(path).read_bytes()).decode()

    async def submit(self, job, payload):
        op = job["op"]
        if op == "tts":
            if not payload.get("dialogue"):
                result = await super().submit(job, payload)
                result["result"]["simulated"] = False
                return result
            response = await self.request("POST", self.config["cosyvoice_endpoint"],
                headers={"Authorization": "Bearer " + os.environ["DASHSCOPE_API_KEY"]},
                json={"model": self.config.get("voice_model", "cosyvoice-v3-plus"), "input": {
                    "text": payload["dialogue"], "voice": payload["voice"], "format": "wav", "sample_rate": 24000}})
            body = response.json()
            # Return the remote URL before downloading: a restart can fetch the same result without resynthesis.
            return {"done": False, "remote": {"kind": "download", "url": body["output"]["audio"]["url"],
                    "request_id": body["request_id"], "name": "voice.wav", "model": self.config.get("voice_model", "cosyvoice-v3-plus")}}
        headers = {"Authorization": "Key " + os.environ["FAL_KEY"]}
        if op in ("asset_image", "keyframe"):
            refs = payload.get("references", [])
            model = self.config.get("image_edit_model", "fal-ai/nano-banana/edit") if refs else self.config.get("image_model", "fal-ai/nano-banana")
            arguments = {"prompt": payload["prompt"], "aspect_ratio": payload["aspect"], "num_images": 1, "output_format": "png"}
            if refs:
                arguments["image_urls"] = [self.data_uri(path) for path in refs]
        elif op == "video":
            model = self.config.get("video_model", "bytedance/seedance-2.0/fast/image-to-video")
            arguments = {"prompt": payload["prompt"], "image_url": self.data_uri(payload["image"]),
                         "duration": str(max(4, math.ceil(payload["duration"]))), "aspect_ratio": payload["aspect"],
                         "resolution": "720p", "generate_audio": False}
        else:
            model = self.config.get("lipsync_models", {}).get(payload["style"], "fal-ai/latentsync")
            arguments = {"video_url": self.data_uri(payload["video"]), "audio_url": self.data_uri(payload["audio"])}
        response = await self.request("POST", "https://queue.fal.run/" + model, headers=headers, json=arguments)
        body = response.json()
        return {"done": False, "remote": {"kind": "fal", "model": model, "request_id": body["request_id"],
                "status_url": body["status_url"], "response_url": body["response_url"]}}

    async def poll(self, job, payload):
        remote = job["remote"]
        if remote["kind"] == "download":
            path = await self.download(job, remote["url"], remote["name"])
            return {"done": True, "result": {"path": path, "duration": wav_duration(self.store.media_path(path)),
                    "simulated": False, "provider": "cosyvoice", "model": remote.get("model"), "request_id": remote["request_id"]}}
        # Never send an API key to a URL outside the queue service, including during reconciliation.
        from urllib.parse import urlsplit
        for key in ("status_url", "response_url"):
            url = urlsplit(remote[key])
            if url.scheme != "https" or url.hostname != "queue.fal.run":
                raise ValueError("非法的 fal 任务 URL")
        headers = {"Authorization": "Key " + os.environ["FAL_KEY"]}
        status = (await self.request("GET", remote["status_url"], headers=headers)).json()
        if status.get("status") in ("FAILED", "CANCELLED"):
            raise RemoteFailed("模型服务端任务失败；未重新提交")
        if status.get("status") != "COMPLETED":
            return {"done": False, "remote": remote}
        try:
            result = (await self.request("GET", remote["response_url"], headers=headers)).json()
        except Rejected as error:
            if error.status_code == 422:
                raise RemoteFailed("供应商已结束任务并返回生成失败；保留任务 ID，未重新提交") from error
            raise
        image = job["op"] in ("asset_image", "keyframe")
        url = result["images"][0]["url"] if image else result["video"]["url"]
        path = await self.download(job, url, "image.png" if image else "video.mp4")
        return {"done": True, "result": {"path": path, "simulated": False, "provider": "fal",
                "model": remote["model"], "request_id": remote["request_id"], "duration": payload.get("duration"),
                "seed": result.get("seed")}}


def load_provider(store):
    config_path = store.root / "providers.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    if os.environ.get("DRAMA_ENABLE_LIVE") == "1":
        return CloudProvider(store, config)
    return Provider(store, config)
