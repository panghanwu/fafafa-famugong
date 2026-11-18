from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='FA_', env_file='.env')

    llm_base_url: str = 'http://localhost:4000'  # shared by all models
    llm_api_key: str
    model: str = 'claude-sonnet-5-5-dmc'  # the working agent
    age: Literal['dark'] = 'dark'