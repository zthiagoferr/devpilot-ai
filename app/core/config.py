from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _ComparableSecretStr(SecretStr):
    """Secret string that remains masked while supporting string comparisons."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return self.get_secret_value() == other.get_secret_value()
        if isinstance(other, str):
            return self.get_secret_value() == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.get_secret_value())


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    environment: str = "development"
    llm_provider: str = "fake"
    llm_model: str = "fake-model"
    llm_api_key: _ComparableSecretStr | None = None
    github_token: _ComparableSecretStr | None = None
    github_api_base_url: str = "https://api.github.com"
    database_url: _ComparableSecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @property
    def is_production(self) -> bool:
        """Return whether the application is configured for production."""
        return self.environment.strip().lower() == "production"

    def get_database_url(self) -> str | None:
        """Return the database URL for internal database initialization only.

        The configured value remains secret-like everywhere it is represented;
        this accessor is the explicit boundary at which database code may obtain
        the underlying URL without placing it in settings output or logs.
        """
        if self.database_url is None:
            return None
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
