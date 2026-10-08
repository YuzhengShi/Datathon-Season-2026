"""One configuration resolver for the API, CLI, migrations and reports.

``derive_runtime`` is pure (a mapping in, a frozen :class:`Runtime` out) and holds the rules that
matter: mode precedence, demo/live isolation, and refusing a configuration that would let demo
data share a database with live data. ``load_runtime`` feeds it from pydantic-settings
(environment + ``.env``), so every entry point resolves settings identically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

VALID_MODES = ("live", "demo")
VALID_EXTRACTION_MODES = ("deterministic", "curated", "llm")
DEFAULTS: dict[str, str] = {
    "DATA_MODE": "live",
    "DATABASE_URL": "sqlite:///./data/navigator.db",
    "DEMO_DATABASE_URL": "sqlite:///./data/demo/navigator.db",
    "DATA_DIR": "./data",
    "SOURCE_CONFIG": "./sources.yaml",
    "LOG_LEVEL": "INFO",
    "FETCH_TIMEOUT_SECONDS": "30",
    "FETCH_MAX_BYTES": "10485760",
    "FETCH_RETRIES": "3",
    "FETCH_PER_HOST_CONCURRENCY": "1",
    "FETCH_MIN_INTERVAL_SECONDS": "1",
    "FRESHNESS_DAYS": "30",
    "EXTRACTION_MODE": "deterministic",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "CORS_ALLOW_ORIGINS": "",
    "USER_AGENT": "IndigenousFundingNavigatorBot/0.1 (+contact: set USER_AGENT in .env)",
}


class ConfigError(ValueError):
    """Invalid or unsafe configuration (CLI exit code 2)."""


@dataclass(frozen=True)
class Runtime:
    mode: str
    database_url: str
    data_dir: Path
    artifact_root: Path
    sources_config: Path
    log_level: str
    fetch_timeout: float
    fetch_max_bytes: int
    fetch_retries: int
    fetch_per_host_concurrency: int
    fetch_min_interval: float
    freshness_days: int
    extraction_mode: str
    llm_configured: bool
    cors_origins: tuple[str, ...]
    user_agent: str

    @property
    def reference_dir(self) -> Path:
        return self.data_dir / "reference"

    def describe(self) -> dict:
        """Safe-to-print view (no credentials, no connection strings)."""
        return {"data_mode": self.mode, "artifact_root": self.artifact_root.as_posix(),
                "database_kind": self.database_url.split(":", 1)[0].split("+")[0],
                "extraction_mode": self.extraction_mode, "freshness_days": self.freshness_days}


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    tail = url.split(":///", 1)[1] if ":///" in url else ""
    return Path(tail).resolve() if tail and tail != ":memory:" else None


def _num(raw: Mapping[str, str], key: str, cast: type, minimum: float) -> float:
    try:
        value = cast(raw[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be a number, got {raw[key]!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def derive_runtime(raw: Mapping[str, str], mode_arg: str | None = None) -> Runtime:
    """Resolve settings. An explicit ``mode_arg`` (``--mode``) beats ``DATA_MODE``."""
    merged = {**DEFAULTS, **{k: str(v) for k, v in raw.items() if v is not None}}
    mode = (mode_arg or merged["DATA_MODE"]).strip().lower()
    if mode not in VALID_MODES:
        raise ConfigError(f"data mode must be one of {VALID_MODES}, got {mode!r}")
    extraction = merged["EXTRACTION_MODE"].strip().lower()
    if extraction not in VALID_EXTRACTION_MODES:
        raise ConfigError(f"EXTRACTION_MODE must be one of {VALID_EXTRACTION_MODES}")

    live_url, demo_url = merged["DATABASE_URL"].strip(), merged["DEMO_DATABASE_URL"].strip()
    if not live_url or not demo_url:
        raise ConfigError("DATABASE_URL and DEMO_DATABASE_URL must both be set")
    if live_url == demo_url or (_sqlite_path(live_url) and _sqlite_path(live_url) == _sqlite_path(demo_url)):
        raise ConfigError("DATABASE_URL and DEMO_DATABASE_URL must differ: demo data must never share the live database")

    data_dir = Path(merged["DATA_DIR"])
    return Runtime(
        mode=mode,
        database_url=demo_url if mode == "demo" else live_url,
        data_dir=data_dir,
        artifact_root=data_dir / "demo" if mode == "demo" else data_dir,
        sources_config=Path(merged["SOURCE_CONFIG"]),
        log_level=merged["LOG_LEVEL"].upper(),
        fetch_timeout=_num(merged, "FETCH_TIMEOUT_SECONDS", float, 1),
        fetch_max_bytes=int(_num(merged, "FETCH_MAX_BYTES", int, 1024)),
        fetch_retries=int(_num(merged, "FETCH_RETRIES", int, 0)),
        fetch_per_host_concurrency=int(_num(merged, "FETCH_PER_HOST_CONCURRENCY", int, 1)),
        fetch_min_interval=_num(merged, "FETCH_MIN_INTERVAL_SECONDS", float, 0),
        freshness_days=int(_num(merged, "FRESHNESS_DAYS", int, 1)),
        extraction_mode=extraction,
        llm_configured=bool(merged["OPENAI_API_KEY"].strip() and merged["OPENAI_MODEL"].strip()),
        cors_origins=tuple(o.strip() for o in merged["CORS_ALLOW_ORIGINS"].split(",") if o.strip()),
        user_agent=merged["USER_AGENT"],
    )


def load_runtime(mode_arg: str | None = None, env_file: str | Path = ".env") -> Runtime:
    """Load settings from the environment and ``.env`` with pydantic-settings, then derive."""
    try:
        from pydantic import field_validator
        from pydantic_settings import BaseSettings, SettingsConfigDict
    except ImportError as exc:  # pragma: no cover - exercised only without the dependency
        raise ConfigError("pydantic-settings is not installed; run `python -m pip install -r requirements.lock`") from exc

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=str(env_file), extra="ignore", case_sensitive=False)
        data_mode: str = DEFAULTS["DATA_MODE"]
        database_url: str = DEFAULTS["DATABASE_URL"]
        demo_database_url: str = DEFAULTS["DEMO_DATABASE_URL"]
        data_dir: str = DEFAULTS["DATA_DIR"]
        source_config: str = DEFAULTS["SOURCE_CONFIG"]
        log_level: str = DEFAULTS["LOG_LEVEL"]
        fetch_timeout_seconds: str = DEFAULTS["FETCH_TIMEOUT_SECONDS"]
        fetch_max_bytes: str = DEFAULTS["FETCH_MAX_BYTES"]
        fetch_retries: str = DEFAULTS["FETCH_RETRIES"]
        fetch_per_host_concurrency: str = DEFAULTS["FETCH_PER_HOST_CONCURRENCY"]
        fetch_min_interval_seconds: str = DEFAULTS["FETCH_MIN_INTERVAL_SECONDS"]
        freshness_days: str = DEFAULTS["FRESHNESS_DAYS"]
        extraction_mode: str = DEFAULTS["EXTRACTION_MODE"]
        openai_api_key: str = ""
        openai_model: str = ""
        cors_allow_origins: str = ""
        user_agent: str = DEFAULTS["USER_AGENT"]

        @field_validator("data_mode")
        @classmethod
        def _mode(cls, value: str) -> str:
            if value.strip().lower() not in VALID_MODES:
                raise ValueError(f"data_mode must be one of {VALID_MODES}")
            return value

    try:
        settings = Settings()
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(f"invalid settings: {exc.__class__.__name__}") from exc
    return derive_runtime({k.upper(): v for k, v in settings.model_dump().items()}, mode_arg)
