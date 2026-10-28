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
    # Docker sets DB_HOST=postgres and maps APP_DB_* to DB_*; without Docker the entry points (imcp-app, alembic,
    # the bank draft) read the same .env with from_env_file(), so the APP_DB_* names work there too.
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str | None = None
    DB_PASSWORD: SecretStr | None = None
    DB_NAME: str | None = None
    DATABASE_URL: SecretStr | None = None
    APP_DB_USER: str | None = None  # the .env names docker-compose reads; used when DB_* aren't set
    APP_DB_PASSWORD: SecretStr | None = None
    APP_DB_NAME: str | None = None

    # The app server has no login of its own: without Docker it listens on the machine only. Docker's
    # compose file sets 0.0.0.0 inside the container and publishes the port on 127.0.0.1.
    APP_HOST: str = "127.0.0.1"
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
    # Embeddings (OpenAI-compatible /embeddings). The URL and key fall back to the chat model's.
    EMBEDDING_MODEL: str | None = None
    EMBEDDING_BASE_URL: AnyHttpUrl | None = None
    EMBEDDING_API_KEY: str | None = None

    # The index of the Adyen docs (llms.txt): one line per page with its title and description.
    # Read by the doc page loader, never stored.
    DOCS_INDEX_URL: AnyHttpUrl | None = None

    # Feature flags
    FLAG_RECOMMENDER: Literal["curated", "graph", "both"] = "curated"
    FLAG_SANITIZE: bool = True
    # Send new questions (generic wording, no answers or material) to our review queue
    FLAG_CANDIDATE_QUEUE: bool = False
    # Accept call transcripts (material of kind `transcript`) in /ops-answer-scope. Off: the run refuses
    # them and asks for a call summary or notes instead. Summaries, notes, emails and documents always pass.
    FLAG_TRANSCRIPTS: bool = True

    @model_validator(mode="after")
    def _database_configured(self) -> "AppSettings":
        self.DB_USER = self.DB_USER or self.APP_DB_USER or ("imcp" if self.APP_DB_PASSWORD else None)
        self.DB_PASSWORD = self.DB_PASSWORD or self.APP_DB_PASSWORD
        self.DB_NAME = self.DB_NAME or self.APP_DB_NAME or ("imcp" if self.APP_DB_PASSWORD else None)
        if self.DATABASE_URL is None and not (self.DB_USER and self.DB_PASSWORD and self.DB_NAME):
            raise ValueError("set APP_DB_PASSWORD (and APP_DB_USER, APP_DB_NAME if not the defaults) in .env, "
                             "or DB_USER, DB_PASSWORD and DB_NAME, or DATABASE_URL")
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
    # The IM's own Drive folder for scope sheets and proposals. Set per IM in their MCP config; the
    # skills copy into it without searching Drive. Unset: the skills look for a SolutionProposals folder.
    PROPOSALS_DRIVE_FOLDER_URL: AnyHttpUrl | None = None
    # Folder the bank-load tool may read CSVs from. Default: the repo's data/ folder (git-ignored).
    IMCP_DATA_DIR: Path | None = None
    # Folder /ops-answer-scope may read merchant material from. Default: the repo's inputs/ (git-ignored).
    IMCP_INPUTS_DIR: Path | None = None


def from_env_file(path: str = ".env") -> AppSettings:
    """The app settings as a program run from the repo folder sees them: the environment first, then .env.
    Only the no-Docker entry points use this; the app under Docker and the tests take the environment alone."""
    return AppSettings(_env_file=path)


def describe_config(s: AppSettings) -> dict:
    """Which settings are present, without revealing any values."""
    is_set = lambda v: v is not None and v != ""  # noqa: E731
    return {
        "links": {
            "questionBank": is_set(s.QUESTION_BANK_URL),
            "proposalMaster": is_set(s.PROPOSAL_MASTER_URL),
            "proposalsDriveFolder": is_set(s.PROPOSALS_DRIVE_FOLDER_URL),
            "feedbackForm": is_set(s.FEEDBACK_FORM_URL),
            "docsIndex": is_set(s.DOCS_INDEX_URL),
        },
        "model": {
            "baseUrl": is_set(s.MODEL_BASE_URL),
            "name": is_set(s.MODEL_NAME),
            "apiKey": is_set(s.MODEL_API_KEY),
            "embeddingModel": is_set(s.EMBEDDING_MODEL),
            "embeddingBaseUrl": is_set(s.EMBEDDING_BASE_URL) or is_set(s.MODEL_BASE_URL),
            "embeddingApiKey": is_set(s.EMBEDDING_API_KEY) or is_set(s.MODEL_API_KEY),
        },
        "flags": {
            "recommender": s.FLAG_RECOMMENDER,
            "sanitize": s.FLAG_SANITIZE,
            "candidateQueue": s.FLAG_CANDIDATE_QUEUE,
            "transcripts": s.FLAG_TRANSCRIPTS,
        },
    }
