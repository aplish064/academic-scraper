"""Configuration for the Academic CV Builder."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from a .env file without overriding the environment."""
    env_path = path
    if env_path is None:
        env_file_override = os.environ.get("CV_BUILDER_ENV_FILE")
        env_path = Path(env_file_override) if env_file_override else Path.cwd() / ".env"

    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class CvBuilderConfig:
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_database: str
    clickhouse_user: str
    clickhouse_password: str
    cv_database: str
    openalex_base_url: str
    orcid_client_id: str
    orcid_client_secret: str
    orcid_base_url: str
    orcid_token_url: str
    crossref_base_url: str
    crossref_mailto: str
    crossref_user_agent: str
    semantic_base_url: str
    semantic_api_key: str
    request_timeout: float


def _get_legacy_env(primary_key: str, legacy_key: str, default: str = "") -> str:
    return os.environ.get(primary_key) or os.environ.get(legacy_key, default)


def _get_int_env(key: str, default: int, min_value: int | None = None) -> int:
    raw_value = os.environ.get(key)
    if raw_value is None:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer, got {raw_value!r}") from exc

    if min_value is not None and value < min_value:
        raise ValueError(f"{key} must be >= {min_value}, got {value}")
    return value


def _get_float_env(key: str, default: float, min_value: float | None = None) -> float:
    raw_value = os.environ.get(key)
    if raw_value is None:
        value = default
    else:
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"{key} must be a number, got {raw_value!r}") from exc

    if min_value is not None and value <= min_value:
        raise ValueError(f"{key} must be > {min_value}, got {value}")
    return value


def get_config(load_dotenv: bool = True, env_file: Path | None = None) -> CvBuilderConfig:
    if load_dotenv:
        load_env_file(env_file)

    return CvBuilderConfig(
        clickhouse_host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        clickhouse_port=_get_int_env("CLICKHOUSE_PORT", 8123, min_value=1),
        clickhouse_database=os.environ.get("CLICKHOUSE_DATABASE", "academic_db"),
        clickhouse_user=os.environ.get("CLICKHOUSE_USER", "default"),
        clickhouse_password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        cv_database=os.environ.get("CV_DATABASE", "academic_cv"),
        openalex_base_url=os.environ.get("OPENALEX_BASE_URL", "https://api.openalex.org"),
        orcid_client_id=_get_legacy_env("ORCID_CLIENT_ID", "ORCID_Client_ID"),
        orcid_client_secret=_get_legacy_env("ORCID_CLIENT_SECRET", "ORCID_Client_secret"),
        orcid_base_url=os.environ.get("ORCID_BASE_URL", "https://pub.orcid.org/v3.0"),
        orcid_token_url=os.environ.get(
            "ORCID_OAUTH_TOKEN_URL",
            "https://orcid.org/oauth/token",
        ),
        crossref_base_url=os.environ.get("CROSSREF_BASE_URL", "https://api.crossref.org"),
        crossref_mailto=os.environ.get("CROSSREF_MAILTO", ""),
        crossref_user_agent=os.environ.get(
            "CROSSREF_USER_AGENT",
            "Top-Talent-Academic/1.0",
        ),
        semantic_base_url=os.environ.get(
            "SEMANTIC_BASE_URL",
            "https://api.semanticscholar.org/graph/v1",
        ),
        semantic_api_key=os.environ.get("SEMANTIC_API_KEY", ""),
        request_timeout=_get_float_env("CV_BUILDER_REQUEST_TIMEOUT", 30.0, min_value=0.1),
    )
