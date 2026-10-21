import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .engine import Conflict, Engine, source_hash
from .models import AssetInput, NewAssetInput, EpisodeInput, ProjectInput, ReviewInput, RunInput, ShotInput, ScriptInput, ResolveInput, CostInput
from .providers import load_provider
from .store import Store, uid

REPO = Path(__file__).resolve().parent.parent


def create_app(data_dir=None, provider=None, start_worker=True):
    store = Store(data_dir or os.environ.get("DRAMA_DATA_DIR", REPO / ".drama"))
    engine = Engine(store, provider)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(engine.worker()) if start_worker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="短剧 · AI 短剧工作台", lifespan=lifespan)
    app.state.engine = engine

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "拒绝跨站写入"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(LookupError)
    async def missing(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409 if isinstance(error, Conflict) else 400)

    @app.get("/api/drama/health")
    def health():
        import importlib.util
        return {"ok": True, "mode": engine.provider.mode, "concurrency": 2, "max_retries": 2,
                "vimax_available": importlib.util.find_spec("langchain") is not None,
                "fal_configured": bool(engine.provider.config.get("fal_key")),
                "voice_configured": bool(engine.provider.config.get("dashscope_api_key")), "config": engine.provider.public_config()}

    @app.get("/api/drama/projects")
    def projects():
        with store.transaction() as db:
            return store.list(db, "project")

    @app.post("/api/drama/projects", status_code=201)
    def create_project(data: ProjectInput):
        return engine.create_project(data.model_dump())

    @app.patch("/api/drama/projects/{id}")
    def budget(id: str, data: ProjectInput):
        with store.transaction() as db:
            project = store.get(db, "project", id)
            project.update(data.model_dump())
            return store.put(db, "project", project, bump=True)

    @app.get("/api/drama/projects/{id}")
    def project(id: str):
        return engine.snapshot(id)

    @app.post("/api/drama/projects/{id}/episodes", status_code=201)
    def episode(id: str, data: EpisodeInput):
        return engine.create_episode(id, data.model_dump())

    @app.put("/api/drama/episodes/{id}/script")
    def script(id: str, data: ScriptInput):
        with store.transaction() as db:
            ep = store.get(db, "episode", id)
            for shot in engine.shots(db, id):
                shot["archived"] = True
                store.put(db, "shot", shot, bump=True)
            ep.update(script=data.script, planned_hash=None, approvals={})
            ep.pop("delivery", None)
            return store.put(db, "episode", ep, bump=True)

    @app.post("/api/drama/episodes/{id}/plan")
    def plan(id: str):
        return engine.plan(id)

    @app.post("/api/drama/episodes/{id}/approve/{gate}")
    def approve(id: str, gate: str):
        return engine.approve(id, gate)

    @app.post("/api/drama/episodes/{id}/run")
    def run(id: str, data: RunInput):
        return engine.run(id, data.phase)

    @app.put("/api/drama/shots/{id}")
    def shot(id: str, data: ShotInput):
        return engine.update_shot(id, data.model_dump())

    @app.post("/api/drama/shots/{id}/review")
    def review(id: str, data: ReviewInput):
        return engine.review(id, data.model_dump())

    @app.put("/api/drama/assets/{id}")
    def asset(id: str, data: AssetInput):
        return engine.update_asset(id, data.model_dump())

    @app.post("/api/drama/projects/{id}/assets", status_code=201)
    def add_asset(id: str, data: NewAssetInput):
        with store.transaction() as db:
            store.get(db, "project", id)
            return store.put(db, "asset", {**data.model_dump(), "project_id": id, "image": None, "simulated": False})

    @app.post("/api/drama/assets/{id}/image")
    async def upload(id: str, file: UploadFile = File(...)):
        content = await file.read(12 * 1024 * 1024 + 1)
        if len(content) > 12 * 1024 * 1024:
            raise ValueError("参考图不能超过 12 MiB")
        import io
        try:
            image = Image.open(io.BytesIO(content))
            if image.width * image.height > 30_000_000:
                raise ValueError("参考图像素过大")
            image.load()
            image = image.convert("RGB")
        except Exception:
            raise ValueError("请选择有效的 PNG、JPEG 或 WebP 图片")
        folder = store.media_path(uid())
        folder.mkdir()
        image.save(folder / "reference.png")
        with store.transaction() as db:
            asset = store.get(db, "asset", id)
            asset.update(image=(folder / "reference.png").relative_to(store.root / "media").as_posix(), simulated=False)
            asset = store.put(db, "asset", asset, bump=True)
            engine.invalidate_asset(db, asset)
            return asset

    @app.get("/api/drama/versions/{id}")
    def versions(id: str):
        with store.transaction() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM versions WHERE id=? ORDER BY version DESC", (id,))]

    @app.post("/api/drama/jobs/{id}/retry")
    def retry(id: str):
        with store.transaction() as db:
            job = store.get(db, "job", id)
            if job["status"] != "failed" or job["attempts"] >= 3:
                raise Conflict("仅可重试已确定失败且未超过重试上限的任务；未知状态须先核对服务端")
            if not engine.is_current(db, job):
                raise Conflict("任务输入已过期，请重新排产")
            job.update(status="queued", next_at=0, error=None)
            return store.put(db, "job", job)

    @app.post("/api/drama/jobs/{id}/reconcile")
    def reconcile(id: str, data: ResolveInput):
        import re
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", data.request_id):
            raise ValueError("无效的服务端任务 ID")
        with store.transaction() as db:
            job = store.get(db, "job", id)
            if job["status"] != "reconcile" or job["op"] not in ("asset_image", "keyframe", "video", "lipsync"):
                raise Conflict("此任务不能通过 fal ID 恢复；请核对服务端记录，保留预算占用")
            cfg = engine.provider.config
            if job["op"] in ("asset_image", "keyframe"):
                model = cfg.get("image_edit_model", "fal-ai/nano-banana/edit") if job["input"].get("references") else cfg.get("image_model", "fal-ai/nano-banana")
            elif job["op"] == "video":
                model = cfg.get("video_model", "bytedance/seedance-2.0/fast/image-to-video")
            else:
                model = cfg.get("lipsync_models", {}).get(job["input"]["style"], "fal-ai/latentsync")
            # fal queue request endpoints use the base model ID, excluding subpaths.
            parts = model.split("/")
            base = "/".join(parts[:2])
            root = f"https://queue.fal.run/{base}/requests/{data.request_id}"
            job.update(status="submitted", next_at=0, remote={"kind": "fal", "model": model,
                "request_id": data.request_id, "status_url": root + "/status", "response_url": root})
            return store.put(db, "job", job)

    @app.patch("/api/drama/jobs/{id}/cost")
    def reconcile_cost(id: str, data: CostInput):
        with store.transaction() as db:
            job = store.get(db, "job", id)
            if job["status"] not in ("succeeded", "failed", "obsolete") or job["reserved"]:
                raise Conflict("仅能核对已结束任务的账单；在途任务须保留预算占用")
            job.update(actual_cost=data.actual_cost, spent=data.actual_cost, cost_source="manually_verified_invoice")
            return store.put(db, "job", job, bump=True)

    @app.put("/api/drama/config")
    async def config(request: Request):
        if await request.json() != {}:
            raise ValueError("请直接编辑 configs/drama.local.yaml；此接口仅重新加载配置")
        if engine.running:
            raise Conflict("有任务正在执行，请等待任务结束后重新加载配置")
        engine.provider = load_provider(store)
        return {"ok": True, "mode": engine.provider.mode}

    @app.get("/api/drama/demo-script")
    def demo_script():
        from .models import DEMO_SCRIPT
        return {"script": DEMO_SCRIPT}

    @app.get("/api/drama/media/{path:path}")
    def media(path: str):
        target = store.media_path(path)
        if not target.is_file():
            raise HTTPException(404, "素材不存在")
        return FileResponse(target)

    dist = REPO / "web" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def home():
        return RedirectResponse("/drama")

    @app.get("/vimax-dark.svg")
    def icon():
        return FileResponse(REPO / "web" / "public" / "drama.svg", media_type="image/svg+xml")

    @app.get("/drama")
    @app.get("/drama/{path:path}")
    def frontend(path: str = ""):
        if not (dist / "index.html").is_file():
            return JSONResponse({"detail": "请先在 web 目录执行 npm run build，或使用启动脚本"}, status_code=503)
        return FileResponse(dist / "index.html")

    return app


app = create_app()
