from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # GCP / Vertex (GCP_* preferred; VERTEX_* kept for compatibility)
    gcp_project_id: str = ""
    gcp_location: str = ""
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    gemini_model: str = "gemini-2.5-flash"
    google_application_credentials: str = ""
    mock_llm: bool = False

    max_concurrent_jobs: int = 2
    rate_limit_per_hour: int = 5
    quick_minutes_default: int = 10
    quick_minutes_min: int = 5
    quick_minutes_max: int = 20
    full_max_video_seconds: int = 3600
    results_ttl_hours: int = 72

    pressplay_demo_secret: str = ""
    data_dir: str = "data"
    graphify_bin: str = ""
    pressplay_use_mock: str = ""

    # Postgres + guest sessions
    database_url: str = ""
    session_secret: str = ""
    guest_session_ttl_days: int = 30

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def data_path(self) -> Path:
        return self.project_root / self.data_dir

    @property
    def jobs_path(self) -> Path:
        return self.data_path / "jobs"

    @property
    def results_path(self) -> Path:
        return self.data_path / "results"

    @property
    def effective_gcp_project(self) -> str:
        return (self.gcp_project_id or self.vertex_project).strip()

    @property
    def effective_gcp_location(self) -> str:
        loc = (self.gcp_location or self.vertex_location).strip()
        return loc or "us-central1"

    @property
    def gcp_credentials_path(self) -> Path | None:
        creds = self.google_application_credentials.strip()
        return Path(creds) if creds else None

    @property
    def gcp_credentials_mode(self) -> str:
        """Pattern C: ``adc`` (local), ``service_account`` (Docker/VM), or ``mock``."""
        if self.should_mock_llm():
            return "mock"
        if self.gcp_credentials_path is not None:
            return "service_account"
        return "adc"

    def should_mock_llm(self) -> bool:
        """Stub Watcher/Writer (GeminiAdapter) when ``MOCK_LLM`` or GCP project unset.

        Does **not** skip ingest — use ``PRESSPLAY_USE_MOCK=1`` for full fast mock.
        With Pattern C, unset ``GOOGLE_APPLICATION_CREDENTIALS`` uses ADC locally.
        """
        if self.mock_llm:
            return True
        return not self.effective_gcp_project

    @property
    def use_database(self) -> bool:
        return bool(self.database_url.strip())

    @property
    def session_cookie_secure(self) -> bool:
        return not self.debug

    def gcp_credential_warnings(self) -> list[str]:
        """Non-fatal misconfig hints (e.g. Docker mount missing)."""
        path = self.gcp_credentials_path
        if path is None:
            return []
        if path.is_file():
            return []
        return [
            "GOOGLE_APPLICATION_CREDENTIALS is set but the file is missing: "
            f"{path}. For local dev, unset it and use ADC; for Docker, mount "
            "./secrets/gcp-sa.json:/secrets/gcp.json:ro"
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
