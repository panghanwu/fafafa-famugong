import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

AGES = Path(__file__).parent / 'ages.toml'
BLACKSMITH = Path(__file__).parent / 'blacksmith.toml'


class Age(BaseModel):
    model_config = ConfigDict(extra='forbid')

    identity: str

    @classmethod
    def load(cls, name: str) -> Self:
        ages = tomllib.loads(AGES.read_text())
        return cls.model_validate(ages[name])


class Tech(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['shortcut', 'skill']
    description: str
    prompt: str

    @classmethod
    def load(cls, path: Path) -> dict[str, Self]:
        if not path.exists():
            return {}
        techs = tomllib.loads(path.read_text())
        return {name: cls.model_validate(tech) for name, tech in techs.items()}
