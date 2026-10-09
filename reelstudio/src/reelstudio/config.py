"""Settings (env) and YAML configuration loading. Secrets only ever come from the environment."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/reelstudio.db"
    data_dir: Path = Path("./data")
    config_dir: Path = PROJECT_ROOT / "config"
    dashboard_token: str = ""
    secret_key: str = ""
    ai_provider: str = "local"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_redirect_uri: str = ""
    graph_version: str = "v21.0"
    public_base_url: str = ""

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or get_settings().config_dir) / name
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
