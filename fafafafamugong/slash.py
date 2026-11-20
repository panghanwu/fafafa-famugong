from dataclasses import dataclass
from typing import Callable

from fafafafamugong.schema import Tech


@dataclass
class BuiltinCommand:
    description: str
    fn: Callable[[str], None]


BUILTINS: dict[str, BuiltinCommand] = {}


def builtin(name: str, description: str):
    """Register a function as a built-in slash command."""
    def register(fn):
        BUILTINS[name] = BuiltinCommand(description, fn)
        return fn
    return register


@builtin('exit', 'Leave the chat')
def _exit(args: str):
    raise SystemExit


def parse(text: str) -> tuple[str, str] | None:
    """Split '/name args' into (name, args); None if text is not a command."""
    if not text.startswith('/'):
        return None

    name, _, args = text[1:].partition(' ')
    if not name or '/' in name:  # a bare '/' or a path like /usr/bin
        return None
    return name, args.strip()


def merge(techs: dict[str, Tech]) -> dict[str, BuiltinCommand | Tech]:
    """Build one namespace from built-ins and shortcuts; skills are not callable."""
    shortcuts = {name: t for name, t in techs.items() if t.type == 'shortcut'}
    return {**shortcuts, **BUILTINS}  # built-ins win over shortcuts


def dispatch(name: str, args: str, commands: dict[str, BuiltinCommand | Tech]) -> str | None:
    """Run a command. Return text to send to the model, or None."""
    command = commands.get(name)
    if command is None:
        print(f'unknown command: /{name}')
        return None
    if isinstance(command, BuiltinCommand):
        command.fn(args)
        return None
    text = command.prompt.strip()
    if args:
        text += f'\n\nARGUMENTS: {args}'  # same format as Claude Code skills
    return text
