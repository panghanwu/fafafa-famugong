import re
from dataclasses import dataclass
from typing import Callable

from fafafafamugong import vibe
from fafafafamugong.schema import BLACKSMITH, SLASH_NAME, Tech
from fafafafamugong.session import Session
from fafafafamugong.tags import PromptTag, mark_text


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
    match = SLASH_NAME.match(text)
    if match is None:
        return None
    return match[1], text[match.end():].strip()


def merge(techs: dict[str, Tech]) -> dict[str, BuiltinCommand | Tech]:
    """Build one namespace from built-ins and shortcuts; skills are not callable."""
    shortcuts = {name: t for name, t in techs.items() if t.type == 'shortcut'}
    return {**shortcuts, **BUILTINS}  # built-ins win over shortcuts


def dispatch(text: str, commands: dict[str, BuiltinCommand | Tech], session: Session) -> str | None:
    """Run a built-in command. Return the text to keep in the session, or None when fa handled it."""
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
    return text


def expand_shortcuts(messages: list[dict], commands: dict[str, BuiltinCommand | Tech]) -> list[dict]:
    """A copy of messages for the model: every /shortcut in user messages becomes its prompt, tagged."""
    def replace(match: re.Match) -> str:
        command = commands.get(match[1])
        return mark_text(command.prompt.strip(), PromptTag.SHORTCUT) if isinstance(command, Tech) else match[0]
    return [{**m, 'content': SLASH_NAME.sub(replace, m['content'])} if m['role'] == 'user' else m for m in messages]
