import re
from dataclasses import dataclass
from typing import Callable

from fafafafamugong import vibe
from fafafafamugong.schema import BLACKSMITH, SLASH_NAME, Tech
from fafafafamugong.session import Session
from fafafafamugong.tags import PromptTag, is_marked, mark_text


@dataclass
class BuiltinCommand:
    description: str
    fn: Callable[[Session, str], None]
    aliases: tuple[str, ...] = ()
    usage: str = ''  # what goes after the name, e.g. '<title>'


BUILTINS: dict[str, BuiltinCommand] = {}  # aliases are keys too, pointing to the same command


def builtin(name: str, description: str, aliases: tuple[str, ...] = (), usage: str = ''):
    """Register a function as a built-in slash command."""
    def register(fn):
        command = BuiltinCommand(description, fn, aliases, usage)
        for key in (name, *aliases):
            BUILTINS[key] = command
        return fn
    return register


@builtin('quit', 'Leave the chat', aliases=('q',))
def _quit(session: Session, args: str):
    raise SystemExit


@builtin('rename', 'Rename the session', aliases=('r',), usage='<title>')
def _rename(session: Session, args: str):
    if not args:  # later: let catzor pick a title
        vibe.notice('warn', 'usage', '/rename <title>')
        return
    session.rename(args)
    vibe.notice('ok', 'renamed', args)


@builtin('rollback', 'Remove the last turn')
def _rollback(session: Session, args: str):
    users = [i for i, m in enumerate(session.messages) if m['role'] == 'user']
    if not users:
        vibe.notice('warn', 'nothing to roll back')
        return
    start = users[-1]
    if is_marked(session.messages[start]['content'], PromptTag.COMPRESSED):
        vibe.notice('warn', 'cannot roll back', 'earlier turns were compressed')
        return
    only = len(users) == 1
    if not vibe.confirm('roll back the only turn? the session will be deleted' if only else 'roll back the last turn?'):
        return
    session.rollback(start)
    if only:
        vibe.notice('ok', 'rolled back', 'nothing left, so the session was deleted')
        return
    vibe.notice('ok', 'rolled back', 'continuing from:')
    vibe.show_last_turn(session)


@builtin('help', 'List commands, shortcuts and skills', aliases=('h',))
def _help(session: Session, args: str):
    techs = Tech.load(BLACKSMITH)
    skills = {name: tech for name, tech in techs.items() if tech.type == 'skill'}
    vibe.show_help(merge(techs), skills)


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
    """Expand /shortcuts in user messages for the model, skipping summaries."""
    def replace(match: re.Match) -> str:
        command = commands.get(match[1])
        return mark_text(command.prompt.strip(), PromptTag.SHORTCUT) if isinstance(command, Tech) else match[0]

    def typed(m: dict) -> bool:  # a user message, not a summary
        return m['role'] == 'user' and not is_marked(m['content'], PromptTag.COMPRESSED)

    return [{**m, 'content': SLASH_NAME.sub(replace, m['content'])} if typed(m) else m for m in messages]
