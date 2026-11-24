import sys
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_NAME = 'config.toml'
COMPRESS_AT = 0.8  # share of context_limit where fa compresses before sending
NOT_IN_CONFIG = {  # settings that come from elsewhere: name -> where
    'llm_api_key': 'run fa --login to enter it',
    'age': 'pick it with fa --age',
}


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # Secret: from <home>/key, written by fa --login
    llm_api_key: str | None = None

    # Per run: from --age, or from the proxy in team mode
    age: Literal['dark'] = 'dark'

    # From config.toml, or admin.toml in team mode; descriptions go into config.toml
    llm_base_url: str = Field('http://localhost:4000', description='The LiteLLM proxy every request goes to')
    model: str = Field('gpt-oss-120b', description='The model that does the work, by its name on the proxy')
    context_limit: int = Field(128000, gt=0, description='How many tokens the model can hold, the prompt and the reply together')


def load_settings(home: Path, **values) -> Settings:
    """Settings from config.toml plus the given values; exits on a bad config.toml."""
    try:
        return Settings(**(read_config(home) | values))  # the given values win over config.toml
    except ValidationError as e:
        problems = '\n'.join(f'  {error['loc'][0]}: {error['msg']}' for error in e.errors())
        sys.exit(f'{home / CONFIG_NAME}:\n{problems}')


def read_config(home: Path) -> dict:
    """The settings in config.toml; empty before the first run."""
    path = home / CONFIG_NAME
    if not path.exists():
        return {}
    try:
        config = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        sys.exit(f'{path}: {e}')
    for name, hint in NOT_IN_CONFIG.items():
        if name in config:
            sys.exit(f'{path}: {name} does not belong here; {hint}')
    return config


def make_config(values: dict[str, str | int]) -> str:
    """The text of a config.toml: the given values, defaults for the rest."""
    lines = ['# fa settings. The access key is not kept here: run fa --login to enter a new one.']
    for name, field in Settings.model_fields.items():
        if name in NOT_IN_CONFIG:
            continue
        lines += ['', f'# {field.description}', f'{name} = {values.get(name, field.default)!r}']  # repr gives valid TOML for str and int
    return '\n'.join(lines) + '\n'
