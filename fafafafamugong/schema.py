import hashlib
import json
import os
import re
import shutil
import tomllib
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

AGES = Path(__file__).parent / 'ages.toml'
BLACKSMITH = Path(__file__).parent / 'blacksmith.toml'
TOWN_CENTER = Path(__file__).parent / 'towncenter.md'  # shared by every age
KING = Path('/etc/famugong/king.toml')  # fixed: a path users could set would let them leave team mode
SLASH_NAME = re.compile(r'(?<!\S)/([\w-]+)(?![\w/-])')  # a /name standing alone, not part of a path like /usr/bin
URL = re.compile(r'https?://[^\s\'"]+')  # no spaces or quotes, so it fits in a TOML string as is


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


def _known_level(level: int) -> int:
    levels = sorted(age.level for age in Age.load_all().values())
    if level not in levels:
        raise ValueError(f'no age has level {level}; levels go from {levels[0]} to {levels[-1]}')
    return level


Level = Annotated[int, AfterValidator(_known_level)]


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def hint(key: str) -> str:
    return f'{key[:3]}...{key[-4:]}'


class KeyEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')

    hint: str = ''
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    age: Level
    note: str = ''
    added: date | None = None


class Kingdom(BaseModel):
    """king.toml: team mode's proxy and the age of each key."""
    model_config = ConfigDict(extra='forbid')

    llm_base_url: str = Field(pattern=rf'^{URL.pattern}$')
    default_wololo_model: str | None = None  # for users who have not picked one
    banner: str | None = None  # rich markup shown at the top of fa; None shows the default
    keys: list[KeyEntry] = []

    @model_validator(mode='after')
    def _no_twins(self) -> Self:
        digests = [entry.sha256 for entry in self.keys]
        if len(set(digests)) < len(digests):
            raise ValueError('a key is registered twice')
        return self

    @classmethod
    def read(cls) -> Self | None:
        """None without king.toml; raises when it is broken."""
        try:
            text = KING.read_text()
        except FileNotFoundError:
            return None
        return cls.model_validate(tomllib.loads(text))

    def find(self, key: str) -> KeyEntry | None:
        return next((entry for entry in self.keys if entry.sha256 == digest(key)), None)

    def save(self):
        """Write king.toml for all users to read; the old one becomes king.toml.bak."""
        text = self.dump()
        type(self).model_validate(tomllib.loads(text))  # never write a file fa cannot read back
        if not KING.parent.exists():
            KING.parent.mkdir(parents=True)
            KING.parent.chmod(0o755)
        if KING.exists():
            shutil.copy2(KING, KING.with_name(f'{KING.name}.bak'))
        temp = KING.with_name(f'.{KING.name}.tmp')
        temp.write_text(text)
        temp.chmod(0o644)  # every user's fa reads it, whatever the umask
        os.replace(temp, KING)  # a crash never leaves half a file behind

    def dump(self) -> str:
        lines = ['# fa team mode; manage it with sudo fa king', '', f'llm_base_url = {_toml(self.llm_base_url)}']
        if self.default_wololo_model:
            lines.append(f'default_wololo_model = {_toml(self.default_wololo_model)}')
        if self.banner:
            lines.append(f'banner = {_toml(self.banner)}')
        for entry in self.keys:
            lines += ['', '[[keys]]']
            lines += [f'{name} = {_toml(value)}' for name, value in entry.model_dump(exclude_none=True).items()]
        return '\n'.join(lines) + '\n'


def _toml(value: str | int | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if '\n' in value and "'''" not in value:
        return f"'''\n{value}'''"  # a multi-line literal string keeps backslashes and spaces as typed
    return f"'{value}'" if "'" not in value else json.dumps(value, ensure_ascii=False)  # JSON strings are valid TOML
