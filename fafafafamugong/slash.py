from dataclasses import dataclass
from typing import Callable

from fafafafamugong.schema import BLACKSMITH, Tech
from fafafafamugong.session import Session


@dataclass
class BuiltinCommand:
    description: str
    fn: Callable[[Session, str], None]
    aliases: tuple[str, ...] = ()


BUILTINS: dict[str, BuiltinCommand] = {}  # aliases are keys too, pointing to the same command


def builtin(name: str, description: str, aliases: tuple[str, ...] = ()):
    """Register a function as a built-in slash command."""
    def register(fn):
        command = BuiltinCommand(description, fn, aliases)
        for key in (name, *aliases):
            BUILTINS[key] = command
        return fn
    return register


@builtin('exit', 'Leave the chat', aliases=('q',))
def _exit(session: Session, args: str):
    raise SystemExit


@builtin('rename', 'Rename the session: /rename <title>', aliases=('r',))
def _rename(session: Session, args: str):
    if not args:  # later: let catzor pick a title
        print('usage: /rename <title>')
        return
    session.rename(args)
    print(f'renamed: {args}')


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
    for title, rows in [('commands', commands), ('shortcuts', shortcuts), ('skills (used by the model)', skills)]:
        if rows:
            print(f'{title}:')
            for label, description in rows:
                print(f'  {label:<{width}}  {description}')


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


def dispatch(name: str, args: str, commands: dict[str, BuiltinCommand | Tech], session: Session) -> str | None:
    """Run a command. Return text to send to the model, or None."""
    command = commands.get(name)
    if command is None:
        print(f'unknown command: /{name}')
        return None
    if isinstance(command, BuiltinCommand):
        command.fn(session, args)
        return None
    text = command.prompt.strip()
    if args:
        text += f'\n\nARGUMENTS: {args}'  # same format as Claude Code skills
    return text
