import re
import sys
import tomllib
from pathlib import Path
from typing import Literal, get_args

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

    # Per run: from --age, or king.toml in team mode
    age: Literal['dark'] = 'dark'

    # From config.toml (king.toml sets llm_base_url in team mode); descriptions go into config.toml
    llm_base_url: str = Field('http://localhost:4000', description='The proxy URL every request goes to')
    wololo_model: str = Field('gpt-oss-120b', description='The main model')
    guard_model: str = Field('', description='The model for guard; empty uses wololo_model')
    context_limit: int = Field(128000, gt=0, description='How many tokens the model can hold, the prompt and the reply together')


PLAYABLE_AGES = get_args(Settings.model_fields['age'].annotation)  # the Literal in Settings is the one list of playable ages


def load_settings(home: Path, defaults: dict | None = None, **values) -> Settings:
    """Settings from defaults, then config.toml, then values; exits on a bad config.toml."""
    try:
        return Settings(**((defaults or {}) | read_config(home) | values))
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


def make_config(values: dict[str, str | int | None]) -> str:
    """The text of a config.toml: the given values, defaults for the rest; None leaves a setting out."""
    lines = ['# fa settings. The access key is not kept here: run fa --login to enter a new one.']
    for name, field in Settings.model_fields.items():
        value = values.get(name, field.default)
        if name in NOT_IN_CONFIG or value is None:
            continue
        lines += ['', f'# {field.description}', f'{name} = {value!r}']  # repr gives valid TOML for str and int
    return '\n'.join(lines) + '\n'


def set_config(home: Path, name: str, value: str | int):
    """Change one setting in config.toml and leave the rest of the file as it is."""
    path = home / CONFIG_NAME
    text = path.read_text()
    line = f'{name} = {value!r}'
    pattern = re.compile(rf'^{name}\s*=.*$', re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(lambda match: line, text, count=1)  # a function, so backslashes in the value stay as they are
    else:
        text = text.rstrip('\n') + f'\n\n# {Settings.model_fields[name].description}\n{line}\n'
    path.write_text(text)
