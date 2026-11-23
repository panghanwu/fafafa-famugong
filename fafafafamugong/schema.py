import re
import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

AGES = Path(__file__).parent / 'ages.toml'
BLACKSMITH = Path(__file__).parent / 'blacksmith.toml'
TOWN_CENTER = Path(__file__).parent / 'town_center.md'  # shared by every age
SLASH_NAME = re.compile(r'(?<!\S)/([\w-]+)(?![\w/-])')  # a /name standing alone, not part of a path like /usr/bin


class Age(BaseModel):
    model_config = ConfigDict(extra='forbid')

    identity: str

    @classmethod
    def load(cls, name: str) -> Self:
        ages = tomllib.loads(AGES.read_text())
        return cls.model_validate(ages[name])


class Tech(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['shortcut', 'skill', 'catzor']
    description: str
    prompt: str

    @classmethod
    def load(cls, path: Path) -> dict[str, Self]:
        if not path.exists():
            return {}
        techs = tomllib.loads(path.read_text())
        for name in techs:
            if len(name) == 1:  # kept for built-in aliases such as /q
                raise ValueError(f'{path}: [{name}] single-letter names are reserved for built-in aliases')
        return {name: cls.model_validate(tech) for name, tech in techs.items()}
