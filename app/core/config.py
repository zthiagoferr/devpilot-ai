from functools import lru_cache

from pydantic import SecretStr, model_validator
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
    # Firebase Authentication. The project identifier is not a secret; the
    # service account JSON is. Both are optional: without them the API runs
    # with authentication disabled (public endpoints stay public) instead of
    # refusing to start.
    firebase_project_id: str | None = None
    firebase_service_account_json: _ComparableSecretStr | None = None
    log_level: str = "INFO"
    frontend_origins: str = ""
    # Correction providers routinely take 45-100 s on medium files. Render free
    # web services are documented to spin down after idle time; the official
    # docs reviewed did not state a request timeout, so 90 s is a conservative
    # bound below the commonly reported ~100 s proxy limit.
    llm_timeout_seconds: float = 90.0
    max_source_code_bytes: int = 1_000_000
    github_max_files: int = 1_000
    github_max_file_bytes: int = 1_000_000
    github_max_total_bytes: int = 5_000_000
    # Upper bound for the number of tree paths collected as repository context.
    # When a tree has more blobs than this, the path set is truncated and the
    # reference graph reports ``tree_complete=False`` (unknown instead of missing).
    github_max_tree_paths: int = 5_000
    # Maximum size of the root ``apps.json`` metadata file read for Protheus
    # repositories. Larger files are ignored without failing the load.
    github_apps_json_max_bytes: int = 65_536
    # Deterministic relation graph edge cap per analysis.
    relations_max_edges: int = 5_000
    # Global time budget for a single ``POST /repositories/load`` call. It is
    # shared by every download of that call and is enforced on top of the
    # per-request HTTP timeout.
    github_load_total_seconds: float = 60.0
    # In-memory rate limiting for the expensive public endpoints
    # (``POST /analyses`` and ``POST /repositories/load``). The default is
    # deliberately generous so local development and the test suite are never
    # throttled; public deployments should lower ``rate_limit_requests``
    # (for example to 10). A non-positive value disables throttling.
    rate_limit_requests: int = 100
    rate_limit_window_seconds: float = 60.0
    # Trust ``X-Forwarded-For`` only when the application runs behind a known
    # reverse proxy (for example the Render/Cloudflare edge). Never enable this
    # when clients can reach the application directly, because the header can be
    # forged.
    trust_proxy_headers: bool = False
    # AI correction (Fase 6-7). The service never executes the returned code,
    # so both limits bound the prompt/response text only.
    correction_max_source_bytes: int = 200_000
    correction_max_corrected_bytes: int = 1_000_000
    # The model's explanation is short prose; a larger payload is treated as an
    # unusable response instead of being persisted.
    correction_max_explanation_bytes: int = 20_000
    # Upper bound for the "full" correction mode: one request may address at
    # most this many issues. Larger batches are rejected with 422 instead of
    # producing an unbounded prompt.
    correction_full_max_issues: int = 10
    # Batch corrections (Fase D2a). One request corrects at most
    # ``correction_batch_max_files`` files, with a total payload bound. The
    # total defaults to three times the per-file limit (3 x 200 kB) and is
    # derived when not set explicitly, so raising the per-file limit keeps the
    # batch bound proportional. The whole request shares one wall-clock budget
    # that must stay below the proxy timeout documented above (~100 s).
    correction_batch_max_files: int = 3
    correction_batch_max_total_bytes: int | None = None
    correction_batch_budget_seconds: float = 90.0
    correction_rate_limit_requests: int = 20
    correction_rate_limit_window_seconds: float = 60.0
    # The deterministic fake provider must be opted into explicitly before the
    # correction endpoint is exposed; otherwise ``LLM_PROVIDER=fake`` (the
    # development default) answers ``503`` instead of persisting fake code.
    correction_fake_provider_enabled: bool = False
    # ADVPL validation stays heuristic unless an official toolchain is
    # explicitly configured. Nothing in this repository runs a build.
    advpl_official_validation_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @model_validator(mode="after")
    def _derive_batch_total_bytes(self) -> "Settings":
        """Derive the batch total from the per-file bound when unset."""
        if self.correction_batch_max_total_bytes is None:
            self.correction_batch_max_total_bytes = (
                3 * self.correction_max_source_bytes
            )
        return self

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

    def get_frontend_origins(self) -> list[str]:
        """Return the configured CORS allowlist as exact origins.

        The setting is a comma-separated string kept for compatibility; this
        accessor normalizes it into a list, trimming whitespace and discarding
        empty entries so a blank or malformed value never becomes a wildcard.
        """
        return [
            origin.strip()
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
