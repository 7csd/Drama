"""Single source of model configuration; never read model settings from the environment."""
import math
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "drama.local.yaml"


def load_config():
    if not CONFIG_PATH.exists():
        return {"mode": "mock"}
    try:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        # Parser errors can contain source lines with credentials.
        raise ValueError("drama.local.yaml 格式错误，请检查 YAML 缩进和语法") from None
    allowed = {"mode", "chat_model", "fal_key", "dashscope_api_key", "image_model",
               "image_edit_model", "video_model", "voice_model", "cosyvoice_endpoint",
               "lipsync_models", "cost_ceiling_cny"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("drama.local.yaml 必须是配置映射，且不能包含未知字段")
    if config.get("mode", "mock") not in ("mock", "live"):
        raise ValueError("mode 必须是 mock 或 live")
    for key in allowed - {"chat_model", "lipsync_models", "cost_ceiling_cny"}:
        if key in config and not isinstance(config[key], str):
            raise ValueError(f"{key} 必须是字符串")
    for key in ("chat_model", "lipsync_models", "cost_ceiling_cny"):
        if not isinstance(config.get(key, {}), dict):
            raise ValueError(f"{key} 必须是映射")
    args = config.get("chat_model", {}).get("init_args", {})
    if not isinstance(args, dict):
        raise ValueError("chat_model.init_args 必须是映射")
    for key in ("model", "model_provider", "base_url", "api_key"):
        if key in args and not isinstance(args[key], str):
            raise ValueError(f"chat_model.init_args.{key} 必须是字符串")
    if any(not isinstance(v, str) for v in config.get("lipsync_models", {}).values()):
        raise ValueError("lipsync_models 必须是字符串映射")
    for value in config.get("cost_ceiling_cny", {}).values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("费用上限必须是正数；未配置时请保留空映射")
    return config
