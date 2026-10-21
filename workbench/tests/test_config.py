import pytest
from fastapi.testclient import TestClient

from workbench import config
from workbench.api import create_app
from workbench.providers import CloudProvider, load_provider
from workbench.store import Store


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "drama.local.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def test_yaml_is_only_source_and_health_never_exposes_keys(tmp_path, config_path, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "environment-secret")
    monkeypatch.setenv("DRAMA_ENABLE_LIVE", "1")
    assert load_provider(Store(tmp_path)).mode == "mock"
    config_path.write_text("mode: live\nfal_key: yaml-secret\ndashscope_api_key: voice-secret\nchat_model:\n  init_args:\n    api_key: planner-secret\n", encoding="utf-8")
    provider = load_provider(Store(tmp_path))
    assert isinstance(provider, CloudProvider)
    assert provider.config["fal_key"] == "yaml-secret"
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        health = client.get("/api/drama/health")
        assert health.json()["fal_configured"]
        assert "secret" not in health.text
        config_path.write_text("mode: mock\n", encoding="utf-8")
        assert client.put("/api/drama/config", json={}).json()["mode"] == "mock"
        config_path.write_text("mode: invalid\n", encoding="utf-8")
        assert client.put("/api/drama/config", json={}).status_code == 400
        assert client.get("/api/drama/health").json()["mode"] == "mock"
    assert not (tmp_path / "providers.local.json").exists()


@pytest.mark.parametrize("text", ["mode: invalid", "fal_key: 123", "cost_ceiling_cny: {video: -1}", "chat_model: []", "lipsync_models: {comic: 123}", "[secret-token: "])
def test_invalid_yaml_rejected_without_source_leak(config_path, text):
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        config.load_config()
    assert "secret-token" not in str(error.value)
