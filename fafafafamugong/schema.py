import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict

AGES = Path(__file__).parent / 'ages.toml'


class Age(BaseModel):
    model_config = ConfigDict(extra='forbid')

    identity: str

    @classmethod
    def load(cls, name: str) -> Self:
        ages = tomllib.loads(AGES.read_text())
        return cls.model_validate(ages[name])
