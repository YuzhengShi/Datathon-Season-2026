"""Settings of the application layer: read model, statistics and AI search.

``DATA_MODE``, ``DATA_DIR`` and ``CORS_ALLOW_ORIGINS`` are the SAME settings the core resolves in
``navigator.config``, so one ``.env`` drives both layers and they can never disagree about the data mode.
Only the AI settings and the optional read-model overrides belong to this layer.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore", case_sensitive=False)

    data_mode: Literal["live", "demo"] = "live"  # same default as the core (navigator.config.DEFAULTS)
    data_dir: str = "./data"
    # Optional overrides. Default: <DATA_DIR>/read_model.db (live) and <DATA_DIR>/demo/read_model.db (demo).
    read_model_url: str = ""
    demo_read_model_url: str = ""
    llm_enabled: bool = False
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    openai_base_url: str = ""  # empty = the official OpenAI endpoint; e.g. https://api.deepseek.com/v1
    llm_timeout_seconds: int = Field(default=20, ge=5, le=30)
    llm_max_rounds: int = Field(default=4, ge=1, le=4)
    llm_max_tool_calls: int = Field(default=6, ge=1, le=6)
    llm_max_output_tokens: int = Field(default=1800, ge=400, le=1800)
    cors_allow_origins: str = ""

    @property
    def selected_url(self) -> str:
        """The read model of the selected mode; demo and live never share a file."""
        demo = self.data_mode == "demo"
        explicit = (self.demo_read_model_url if demo else self.read_model_url).strip()
        if explicit:
            if explicit.startswith("sqlite:///./"):
                return "sqlite:///" + (REPO_ROOT / explicit.removeprefix("sqlite:///./")).as_posix()
            return explicit
        folder = Path(self.data_dir)
        if not folder.is_absolute():
            folder = REPO_ROOT / folder
        if demo:
            folder = folder / "demo"
        return "sqlite:///" + (folder / "read_model.db").as_posix()

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_enabled and self.openai_model and self.openai_api_key.get_secret_value())
