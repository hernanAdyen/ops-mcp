"""Configuration from environment variables.

Links, model settings and flags are never hard-coded, so we can point at test copies
before going live. Secrets are never returned: `describe_config` only says whether a
value is set.
"""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class _Base(BaseSettings):
    # Empty values in .env (e.g. `MODEL_API_KEY=`) count as "not set".
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")


class AppSettings(_Base):
    # Database: separate parts (preferred; passwords may contain any characters),
    # or a full DATABASE_URL as an override.
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_USER: str | None = None
    DB_PASSWORD: SecretStr | None = None
    DB_NAME: str | None = None
    DATABASE_URL: SecretStr | None = None

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8787

    # Links (point at copies while testing)
    QUESTION_BANK_URL: AnyHttpUrl | None = None
    PROPOSAL_MASTER_URL: AnyHttpUrl | None = None
    PROPOSALS_DRIVE_FOLDER_URL: AnyHttpUrl | None = None
    FEEDBACK_FORM_URL: AnyHttpUrl | None = None

    # Model (OpenAI-compatible)
    MODEL_BASE_URL: AnyHttpUrl | None = None
    MODEL_NAME: str | None = None
    MODEL_API_KEY: str | None = None
    EMBEDDING_MODEL: str | None = None

    # Feature flags
    FLAG_RECOMMENDER: Literal["curated", "graph", "both"] = "curated"
    FLAG_SANITIZE: bool = True
    # Send new questions (generic wording, no answers or material) to our review queue
    FLAG_CANDIDATE_QUEUE: bool = False

    @model_validator(mode="after")
    def _database_configured(self) -> "AppSettings":
        if self.DATABASE_URL is None and not (self.DB_USER and self.DB_PASSWORD and self.DB_NAME):
            raise ValueError("set DB_USER, DB_PASSWORD and DB_NAME (or DATABASE_URL)")
        return self

    def database_url(self) -> URL:
        """SQLAlchemy URL for psycopg 3. Built from parts, so special characters are safe."""
        if self.DATABASE_URL is not None:
            url = make_url(self.DATABASE_URL.get_secret_value())
            if url.drivername in ("postgres", "postgresql"):
                url = url.set(drivername="postgresql+psycopg")
            return url
        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD.get_secret_value() if self.DB_PASSWORD else None,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )


class McpSettings(_Base):
    APP_SERVER_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:8787")
    FEEDBACK_FORM_URL: AnyHttpUrl | None = None
    # Folder the bank-load tool may read CSVs from. Default: the repo's data/ folder (git-ignored).
    IMCP_DATA_DIR: Path | None = None
    # Folder /source-scope-answers may read merchant material from. Default: the repo's inputs/ (git-ignored).
    IMCP_INPUTS_DIR: Path | None = None


def describe_config(s: AppSettings) -> dict:
    """Which settings are present, without revealing any values."""
    is_set = lambda v: v is not None and v != ""  # noqa: E731
    return {
        "links": {
            "questionBank": is_set(s.QUESTION_BANK_URL),
            "proposalMaster": is_set(s.PROPOSAL_MASTER_URL),
            "proposalsDriveFolder": is_set(s.PROPOSALS_DRIVE_FOLDER_URL),
            "feedbackForm": is_set(s.FEEDBACK_FORM_URL),
        },
        "model": {
            "baseUrl": is_set(s.MODEL_BASE_URL),
            "name": is_set(s.MODEL_NAME),
            "apiKey": is_set(s.MODEL_API_KEY),
            "embeddingModel": is_set(s.EMBEDDING_MODEL),
        },
        "flags": {
            "recommender": s.FLAG_RECOMMENDER,
            "sanitize": s.FLAG_SANITIZE,
            "candidateQueue": s.FLAG_CANDIDATE_QUEUE,
        },
    }
