import sys
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONFIG_NAME = 'config.toml'
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


def read_config(home: Path) -> dict:
    """The settings in <home>/config.toml, which setup() writes on the first run."""
    path = home / CONFIG_NAME
    try:
        config = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        sys.exit(f'{path}: {e}')
    for name, hint in NOT_IN_CONFIG.items():
        if name in config:
            sys.exit(f'{path}: {name} does not belong here; {hint}')
    return config


def make_config(values: dict[str, str]) -> str:
    """config.toml with every setting it may hold: the given values, defaults for the rest."""
    lines = ['# fa settings. The access key is not kept here: run fa --login to enter a new one.']
    for name, field in Settings.model_fields.items():
        if name in NOT_IN_CONFIG:
            continue
        lines += ['', f'# {field.description}', f"{name} = '{values.get(name, field.default)}'"]  # every setting is a string so far
    return '\n'.join(lines) + '\n'
