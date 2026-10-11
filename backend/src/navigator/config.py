from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    data_mode: Literal["live", "demo"] = "demo"
    database_url: str = "sqlite:///./data/live.db"
    demo_database_url: str = "sqlite:///./data/demo.db"
    llm_enabled: bool = False
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    openai_base_url: str = (
        ""  # empty = the official OpenAI endpoint; e.g. https://api.deepseek.com/v1
    )
    llm_timeout_seconds: int = Field(default=20, ge=5, le=30)
    llm_max_rounds: int = Field(default=4, ge=1, le=4)
    llm_max_tool_calls: int = Field(default=6, ge=1, le=6)
    llm_max_output_tokens: int = Field(default=1800, ge=400, le=1800)
    cors_origins: str = ""

    @property
    def selected_url(self) -> str:
        url = self.demo_database_url if self.data_mode == "demo" else self.database_url
        if url.startswith("sqlite:///./"):
            return "sqlite:///" + str(ROOT / url.removeprefix("sqlite:///./"))
        return url

    @property
    def llm_ready(self) -> bool:
        return bool(
            self.llm_enabled and self.openai_model and self.openai_api_key.get_secret_value()
        )
