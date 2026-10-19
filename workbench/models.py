from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=80)
    budget: float = Field(default=50, ge=0, le=1_000_000)


class EpisodeInput(Input):
    title: str = Field(min_length=1, max_length=100)
    style: Literal["comic", "realistic"] = "comic"
    script: str = Field(min_length=1, max_length=50000)
    target_duration: int = Field(default=75, ge=60, le=90)
    aspect: Literal["9:16", "16:9"] = "9:16"


class ScriptInput(Input):
    script: str = Field(min_length=1, max_length=50000)


class VersionInput(Input):
    version: int = Field(ge=1)


class ShotInput(VersionInput):
    visual: str = Field(min_length=1, max_length=5000)
    dialogue: str = Field(default="", max_length=1000)
    speaker_id: str | None = None
    asset_ids: list[str]
    duration: float = Field(ge=1, le=30)
    framing: Literal["closeup", "two_shot", "profile", "action", "transition"]
    sample: bool = False


class AssetInput(VersionInput):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)
    costume: str = Field(default="", max_length=1000)
    voice: str = Field(default="longxiaochun", max_length=100)


class NewAssetInput(Input):
    kind: Literal["character", "scene", "prop"]
    style: Literal["comic", "realistic"]
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)
    costume: str = Field(default="", max_length=1000)
    voice: str = Field(default="longxiaochun", max_length=100)


class ReviewInput(Input):
    identity: bool
    continuity: bool
    voice: bool
    dialogue: bool
    lip_sync: bool
    note: str = Field(default="", max_length=2000)


class RunInput(Input):
    phase: Literal["assets", "sample", "full", "compose"]


class ResolveInput(Input):
    request_id: str = Field(min_length=1, max_length=200)


class CostInput(Input):
    actual_cost: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)


DEMO_SCRIPT = """【场景：旧书店，傍晚】
林夏：你把那封信藏了三年？
顾言：我每天都想交给你，可你一直没有回来。
动作：林夏翻开旧书，泛黄的信封滑落在桌面。顾言侧身望向窗外。
林夏：信上的日期，是我离开的前一天。
顾言：那天，我在车站等到了最后一班车。
【场景：车站，夜晚】
动作：两人走进空旷的候车厅，电子钟闪过九点。
林夏：如果我现在回来，还来得及吗？
顾言：这一次，我陪你一起走。
动作：林夏握住信封，两人走向灯光，车站广播响起。
"""
