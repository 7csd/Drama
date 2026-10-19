"""Reuse ViMax's text planning, with a strict short-drama interchange schema."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class NamedAsset(BaseModel):
    name: str
    description: str


class PlannedShot(BaseModel):
    visual: str
    dialogue: str = ""
    speaker: str | None = None
    characters: list[str]
    props: list[str] = Field(default_factory=list)
    scene: str
    duration: float = Field(ge=1, le=15)
    framing: Literal["closeup", "two_shot", "profile", "action", "transition"]


class DramaPlan(BaseModel):
    characters: list[NamedAsset]
    scenes: list[NamedAsset]
    props: list[NamedAsset] = Field(default_factory=list)
    shots: list[PlannedShot] = Field(min_length=1, max_length=100)


async def plan(store, job, payload, config):
    import yaml
    from langchain.chat_models import init_chat_model
    from pipelines.script2video_pipeline import Script2VideoPipeline
    from utils.provider_presets import resolve_chat_model_config

    path = Path(config.get("vimax_config", "configs/agent.local.yaml"))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    model = init_chat_model(**resolve_chat_model_config(data["chat_model"]["init_args"]))
    # The planning-only entrypoint never touches either media generator.
    pipeline = Script2VideoPipeline(model, None, None, str(store.root / "plans" / job["id"]),
                                    frame_size="720x1280" if payload["aspect"] == "9:16" else "1280x720")
    raw = await pipeline.plan_text_artifacts(script=payload["script"], style=payload["style"],
        user_requirement=f"中文短剧，{payload['aspect']}，总时长 {payload['target_duration']} 秒，保留全部对白及说话人。", quiet=True)
    serial = {key: [x.model_dump() for x in value] if isinstance(value, list) else value for key, value in raw.items()}
    (store.root / "plans" / job["id"] / "vimax_plan.json").write_text(json.dumps(serial, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    result = await model.with_structured_output(DramaPlan).ainvoke([
        ("system", "将 ViMax 影视规划规范化为短剧生产表。必须忠于原始剧本，不得改写、添加、遗漏对白；一镜仅一名说话人。角色和场景名称必须引用资产列表。双人镜头列出双方角色。每镜最长15秒，按普通中文语速安排时长，总时长尽量符合目标。覆盖近景、对话、侧脸、动作、转场。"),
        ("human", json.dumps({"original": payload, "vimax": serial}, ensure_ascii=False, default=str))])
    output = result.model_dump()
    from .engine import parse_script
    original = [(s["speaker"], s["dialogue"]) for s in parse_script(payload["script"], payload["target_duration"])["shots"] if s.get("dialogue")]
    actual = [(s["speaker"], s["dialogue"]) for s in output["shots"] if s.get("dialogue")]
    if original and original != actual:
        raise ValueError("ViMax 规范化改变了原剧本对白或说话人，请检查原始规划与剧本，未进入生成阶段")
    model_config = data["chat_model"]["init_args"]
    public_model = {k: model_config[k] for k in ("model", "model_provider", "base_url", "temperature", "max_tokens") if k in model_config}
    return {**output, "simulated": False, "planner": {"framework": "ViMax", "model": public_model}, "upstream_plan": serial}
