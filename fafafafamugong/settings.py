from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ENV = Path(__file__).resolve().parent.parent / '.env'  # dev only: the repo's .env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='FA_', env_file=REPO_ENV, extra='ignore')

    llm_base_url: str = 'http://localhost:4000'  # shared by all models
    llm_api_key: str
    model: str = 'claude-sonnet-5-5-dmc'  # the working agent
    age: Literal['dark'] = 'dark'