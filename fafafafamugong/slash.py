import re
from dataclasses import dataclass
from typing import Callable

from fafafafamugong import vibe
from fafafafamugong.schema import BLACKSMITH, Tech
from fafafafamugong.session import Session


@dataclass
class BuiltinCommand:
    description: str
    fn: Callable[[Session, str], None]
    aliases: tuple[str, ...] = ()


BUILTINS: dict[str, BuiltinCommand] = {}  # aliases are keys too, pointing to the same command
NAME = re.compile(r'(?<!\S)/([\w-]+)(?![\w/-])')  # a /name standing alone, not part of a path like /usr/bin


def builtin(name: str, description: str, aliases: tuple[str, ...] = ()):
    """Register a function as a built-in slash command."""
    def register(fn):
        command = BuiltinCommand(description, fn, aliases)
        for key in (name, *aliases):
            BUILTINS[key] = command
        return fn
    return register


@builtin('quit', 'Leave the chat', aliases=('q',))
def _quit(session: Session, args: str):
    raise SystemExit


@builtin('rename', 'Rename the session: /rename <title>', aliases=('r',))
def _rename(session: Session, args: str):
    if not args:  # later: let catzor pick a title
        vibe.notice('warn', 'usage', '/rename <title>')
        return
    session.rename(args)
    vibe.notice('ok', 'renamed', args)


@builtin('help', 'List commands, shortcuts and skills', aliases=('h',))
def _help(session: Session, args: str):
    techs = Tech.load(BLACKSMITH)
    commands = [
        (', '.join(f'/{n}' for n in (name, *command.aliases)), command.description)
        for name, command in BUILTINS.items() if name not in command.aliases
    ]
    shortcuts = [(f'/{n}', t.description) for n, t in techs.items() if t.type == 'shortcut' and n not in BUILTINS]
    skills = [(n, t.description) for n, t in techs.items() if t.type == 'skill']
    width = max(len(label) for label, _ in commands + shortcuts + skills)
    for title, rows in [
        ('commands', commands),
        ('shortcuts (anywhere in a message)', shortcuts),
        ('skills (used by the model)', skills),
    ]:
        if rows:
            print(f'{title}:')
            for label, description in rows:
                print(f'  {label:<{width}}  {description}')


def parse(text: str) -> tuple[str, str] | None:
    """Split '/name args' into (name, args); None if text does not start with a /name."""
    match = NAME.match(text)
    if match is None:
        return None
    return match[1], text[match.end():].strip()


def merge(techs: dict[str, Tech]) -> dict[str, BuiltinCommand | Tech]:
    """Build one namespace from built-ins and shortcuts; skills are not callable."""
    shortcuts = {name: t for name, t in techs.items() if t.type == 'shortcut'}
    return {**shortcuts, **BUILTINS}  # built-ins win over shortcuts


def dispatch(text: str, commands: dict[str, BuiltinCommand | Tech], session: Session) -> str | None:
    """Run a built-in, or expand shortcuts. Return text to send to the model, or None."""
    command = parse(text)
    if command is not None:  # only the start of a message can be a command
        name, args = command
        target = commands.get(name)
        if target is None:
            vibe.notice('error', 'unknown command', f'/{name}')
            return None
        if isinstance(target, BuiltinCommand):
            target.fn(session, args)
            return None
    return expand(text, commands)


def expand(text: str, commands: dict[str, BuiltinCommand | Tech]) -> str:
    """Replace every /name of a shortcut with its prompt, wherever it appears; other words stay as they are."""
    def replace(match: re.Match) -> str:
        command = commands.get(match[1])
        return command.prompt.strip() if isinstance(command, Tech) else match[0]
    return NAME.sub(replace, text)
