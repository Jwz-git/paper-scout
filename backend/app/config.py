from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")
    app_name: str = "Paper Scout"
    app_version: str = "0.1.0"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = ROOT / "data"
    llm_protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"] = "openai_chat"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    arxiv_user_agent: str = "PaperScout/0.1"
    arxiv_rate_limit_seconds: float = Field(default=3.0, ge=3.0)


# 导入模块不读取本地凭据文件；应用 lifespan 才显式加载本地配置。
settings = Settings(_env_file=None)
