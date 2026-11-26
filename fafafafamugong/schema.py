import re
import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

AGES = Path(__file__).parent / 'ages.toml'
BLACKSMITH = Path(__file__).parent / 'blacksmith.toml'
TOWN_CENTER = Path(__file__).parent / 'towncenter.md'  # shared by every age
SLASH_NAME = re.compile(r'(?<!\S)/([\w-]+)(?![\w/-])')  # a /name standing alone, not part of a path like /usr/bin


class Age(BaseModel):
    model_config = ConfigDict(extra='forbid')

    level: int
    identity: str

    @classmethod
    def load_all(cls) -> dict[str, Self]:
        return {name: cls.model_validate(age) for name, age in tomllib.loads(AGES.read_text()).items()}

    @classmethod
    def load(cls, name: str) -> Self:
        return cls.load_all()[name]


def to_age(value: str) -> str:
    return next((name for name, age in Age.load_all().items() if str(age.level) == value), value)


class Tech(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['shortcut', 'skill', 'command']
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
