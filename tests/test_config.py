from app.core.config import Settings


def test_settings_use_default_llm_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_provider == "fake"
    assert settings.llm_model == "fake-model"
    assert settings.llm_api_key is None


def test_settings_can_be_loaded_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "test-provider")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "test-provider"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_key == "test-key"