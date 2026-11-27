"""The team mode console: sudo fa king."""
import getpass
import os
import stat
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Callable

import openai
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from pydantic import ValidationError
from rich.errors import MarkupError, StyleSyntaxError
from rich.table import Table
from rich.text import Text

from fafafafamugong import __version__, vibe
from fafafafamugong.access import fetch_models, is_rejected
from fafafafamugong.schema import KING, URL, Age, KeyEntry, Kingdom, digest, hint, to_age
from fafafafamugong.settings import Settings
from fafafafamugong.wololo import explain

NEW_KEY_LEVEL = 1  # the age a new key gets when the admin just presses Enter


@dataclass
class Command:
    fn: Callable[[Kingdom, str], None]
    description: str
    usage: str = ''  # what goes after the name, e.g. '[url]'


COMMANDS: dict[str, Command] = {}


def command(name: str, description: str, usage: str = ''):
    def register(fn):
        COMMANDS[name] = Command(fn, description, usage)
        return fn
    return register


def run(args: list[str]):
    """Open the console; set king.toml up first if there is none."""
    if args:
        sys.exit('fa king takes no arguments; run sudo fa king and type help')
    if os.geteuid() != 0:
        sys.exit('run it with sudo')
    if not sys.stdin.isatty():
        sys.exit('no terminal: run sudo fa king in one')
    kingdom = _read() or _found()
    _show_banner(kingdom)
    prompt = PromptSession(completer=_CommandCompleter(), complete_while_typing=True, key_bindings=_key_bindings())  # history stays in memory, not in root's home
    while True:
        try:
            line = prompt.prompt([('bold', 'king> ')])
        except EOFError:
            return
        name, _, args = line.strip().partition(' ')
        if not name:
            continue
        if name not in COMMANDS:
            vibe.notice('error', 'unknown command', f'{name}; type help for the list')
            continue
        if args and not COMMANDS[name].usage:
            vibe.notice('error', 'unknown args', f'{name} takes none')
            continue
        try:
            COMMANDS[name].fn(kingdom, args.strip())
        except (KeyboardInterrupt, EOFError):  # commands save last, so nothing was written
            vibe.notice('warn', 'cancelled')


def _read() -> Kingdom | None:
    """king.toml or None; exits with the details when it is broken."""
    try:
        return Kingdom.read()
    except OSError as e:
        problems = [e.strerror]
    except tomllib.TOMLDecodeError as e:
        problems = [str(e)]
    except ValidationError as e:
        problems = [f'{_where(error['loc'])}{error['msg']}' for error in e.errors()]
    lines = '\n'.join(f'  {problem}' for problem in problems)
    sys.exit(f'{KING} is broken:\n{lines}\nfix it with: sudoedit {KING}')


def _where(loc: tuple) -> str:
    """Where a problem is, counting [[keys]] blocks from 1."""
    parts = [f'#{part + 1}' if isinstance(part, int) else part for part in loc]
    return ' '.join(parts) + ': ' if parts else ''


def _found() -> Kingdom:
    """Set king.toml up: the proxy URL and the default model."""
    vibe.notice('info', 'team mode', f"no {KING} yet; let's set it up")
    default_url = Settings.model_fields['llm_base_url'].default
    try:
        while not _check_url(url := input(f'proxy URL [{default_url}]: ').strip() or default_url):
            pass
        model = input('default model [Enter to let users pick]: ').strip() or None
    except (EOFError, KeyboardInterrupt):
        sys.exit('\nsetup cancelled')
    kingdom = Kingdom(llm_base_url=url, default_wololo_model=model)
    kingdom.save()
    vibe.notice('ok', 'created', str(KING))
    return kingdom


def _show_banner(kingdom: Kingdom):
    count = len(kingdom.keys)
    keys = f'{count} key' if count == 1 else f'{count} keys'
    vibe.console.print(Text.assemble(
        ('fa king', 'bold'), f' {__version__}' if __version__ else '', (f'  {KING}  {keys}', 'dim'),
    ))
    vibe.console.print(Text('help for commands  ctrl+d to quit', style='dim'))


def _newline_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add('escape', 'enter')
    def _newline(event):
        event.current_buffer.insert_text('\n')

    return bindings


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add('c-c')
    def _clear_or_quit(event):  # as in the chat: clear the line, or leave when it is empty
        buffer = event.current_buffer
        if buffer.text:
            buffer.reset()
        else:
            event.app.exit(exception=EOFError)

    return bindings


class _CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        typed = document.text_before_cursor.lstrip()
        if ' ' in typed:  # only the command name completes
            return
        for name, entry in COMMANDS.items():
            if name.startswith(typed):
                yield Completion(name, start_position=-len(typed), display_meta=entry.description)


# Commands; help lists them in this order

@command('status', 'Check king.toml, the proxy and the keys')
def _status(kingdom: Kingdom, args: str):
    info = KING.stat()
    owner, mode = info.st_uid, stat.S_IMODE(info.st_mode)
    readable = owner == 0 and mode == 0o644
    file_state = ('root 644 ✓', 'green') if readable else (f'owner uid {owner}, mode {mode:o} ✗ needs root and 644', 'red')
    reachable = _reachable(kingdom.llm_base_url)
    proxy_state = ('reachable ✓', 'green') if reachable else ('no answer ✗', 'red')
    counts = Counter(entry.age for entry in kingdom.keys)
    names = {age.level: name for name, age in Age.load_all().items()}
    by_age = ', '.join(f'{counts[level]} {names[level]}' for level in sorted(counts))
    grid = Table.grid(padding=(0, 2))
    grid.add_row(Text('file', 'dim'), Text.assemble(str(KING), '  ', file_state))
    grid.add_row(Text('proxy', 'dim'), Text.assemble(kingdom.llm_base_url, '  ', proxy_state))
    grid.add_row(Text('model', 'dim'), kingdom.default_wololo_model or 'users pick their own')
    lines = len(kingdom.banner.splitlines()) if kingdom.banner else 0
    grid.add_row(Text('banner', 'dim'), f'custom, {lines} line{"s" * (lines > 1)}' if lines else 'default')
    grid.add_row(Text('keys', 'dim'), Text.assemble(str(len(kingdom.keys)), (f'  {by_age}' if by_age else '', 'dim')))
    vibe.console.print(vibe.Indent(grid))


@command('list', 'List the registered keys')
def _list(kingdom: Kingdom, args: str):
    if not kingdom.keys:
        vibe.notice('info', 'no keys yet', 'register one with set')
        return
    width = max(len(_label(entry.age)) for entry in kingdom.keys)
    for entry in kingdom.keys:
        added = str(entry.added or '').ljust(10)
        line = Text.assemble('  ', (entry.hint, 'bold'), '  ', _label(entry.age).ljust(width), '  ', (added, 'dim'), '  ', entry.note)
        line.rstrip()
        vibe.console.print(line)
        vibe.console.print(Text.assemble(' ' * (4 + len(entry.hint)), (entry.sha256, 'dim')))  # under the age, easy to copy


@command('set', 'Register a key, or change its age and note')
def _set(kingdom: Kingdom, args: str):
    answer = _ask_key()
    entry = _find(kingdom, answer)
    if entry is None and not _accepted(kingdom, answer):
        return
    level = _ask_age(entry.age if entry else NEW_KEY_LEVEL)
    note = _ask_note(entry.note if entry else '')
    if entry is None:
        entry = KeyEntry(hint=hint(answer), sha256=digest(answer), age=level, note=note, added=date.today())
        kingdom.keys.append(entry)
        done = 'registered'
    else:
        entry.age, entry.note = level, note
        done = 'updated'
    kingdom.save()
    vibe.notice('ok', done, f'{entry.hint} as {_label(level)}')


@command('remove', 'Unregister a key')
def _remove(kingdom: Kingdom, args: str):
    entry = _find(kingdom, _ask_key())
    if entry is None:
        vibe.notice('warn', 'not registered', 'list shows the registered keys')
        return
    if not vibe.confirm(f'remove {entry.hint} ({_label(entry.age)})?'):
        return
    kingdom.keys.remove(entry)
    kingdom.save()
    vibe.notice('ok', 'removed', f'{entry.hint}; disable it on the proxy to stop it')


@command('model', 'Show or change the default model', '[name]')
def _model(kingdom: Kingdom, args: str):
    if args:
        kingdom.default_wololo_model = args
        kingdom.save()
    vibe.notice('ok' if args else 'info', 'model', kingdom.default_wololo_model or 'none; users pick their own')


@command('url', 'Show or change the proxy URL', '[url]')
def _url(kingdom: Kingdom, args: str):
    if args:
        if not _check_url(args):
            return
        kingdom.llm_base_url = args
        kingdom.save()
    vibe.notice('ok' if args else 'info', 'proxy', kingdom.llm_base_url)


@command('banner', 'Edit the banner at the top of fa; rich markup sets colours')
def _banner(kingdom: Kingdom, args: str):
    vibe.notice('info', 'banner', 'esc+enter for a new line; empty for the default')
    text = PromptSession(key_bindings=_newline_bindings()).prompt('', default=kingdom.banner or vibe.TEAM_BANNER)
    text = ''.join(c for c in text if c.isprintable() or c == '\n')  # control characters would break the TOML
    text = '\n'.join(line.rstrip() for line in text.split('\n')).strip('\n')  # leading spaces stay, for ASCII art
    try:
        preview, broken = vibe.parse_markup(text or vibe.TEAM_BANNER), None
    except (MarkupError, StyleSyntaxError) as e:
        preview, broken = Text(text), e  # saved anyway: fa shows broken markup as plain text
    kingdom.banner = text if text and text != vibe.TEAM_BANNER else None
    kingdom.save()
    vibe.console.print(preview, no_wrap=True, overflow='crop')
    if broken:
        vibe.notice('warn', 'saved as plain text', f'the markup is broken: {broken}')
    else:
        vibe.notice('ok', 'banner', 'saved')


@command('help', 'List these commands')
def _help(kingdom: Kingdom, args: str):
    grid = Table.grid(padding=(0, 2))
    for name, entry in COMMANDS.items():
        grid.add_row(Text.assemble((name, 'bold'), (f' {entry.usage}' if entry.usage else '', 'dim')), entry.description)
    vibe.console.print(vibe.Indent(grid))


@command('exit', 'Leave; ctrl+d works too')
def _exit(kingdom: Kingdom, args: str):
    raise SystemExit


# Helpers

def _ask_key() -> str:
    while not (answer := getpass.getpass('key or sha256: ').strip()):  # never echoed, never in any history
        pass
    return answer


def _find(kingdom: Kingdom, answer: str) -> KeyEntry | None:
    """The entry for a key or its sha256; only the admin may look up by sha256, since everyone can read them."""
    return kingdom.find(answer) or next((entry for entry in kingdom.keys if entry.sha256 == answer), None)


def _accepted(kingdom: Kingdom, key: str) -> bool:
    """True if the proxy knows the key, so a typo or a pasted sha256 is not registered."""
    try:
        fetch_models(kingdom.llm_base_url, key)
    except openai.APIError as e:
        if is_rejected(e):
            vibe.notice('error', 'not accepted', 'the proxy does not know this key')
        else:
            vibe.notice(*explain(e))
        return False
    return True


def _ask_age(current: int) -> int:
    while True:
        answer = input(f'age [{_label(current)}]: ').strip()
        if not answer:
            return current
        if (level := _parse_age(answer)) is not None:
            return level


def _ask_note(current: str) -> str:
    note = PromptSession().prompt('note: ', default=current)
    return ''.join(c for c in note if c.isprintable()).strip()  # control characters would break the TOML


def _parse_age(text: str) -> int | None:
    """The level of an age given by name or level; None after a notice."""
    ages = Age.load_all()
    name = to_age(text.lower())
    if name in ages:
        return ages[name].level
    choices = '  '.join(_label(age.level) for age in ages.values())
    vibe.notice('error', 'unknown age', choices)
    return None


def _label(level: int) -> str:
    name = next(name for name, age in Age.load_all().items() if age.level == level)
    return f'{name} ({level})'


def _check_url(url: str) -> bool:
    """True if it is a URL and something answers there; otherwise a notice says why."""
    if not URL.fullmatch(url):
        vibe.notice('warn', 'not a URL', 'it starts with http:// or https://')
        return False
    if not _reachable(url):
        vibe.notice('error', 'connection failed', f'nothing answers at {url}')
        return False
    return True


def _reachable(url: str) -> bool:
    try:
        OpenAI(base_url=url, api_key='-', timeout=5, max_retries=0).models.list()
    except openai.APIStatusError:  # it answered, if only to refuse the fake key
        return True
    except openai.APIConnectionError:  # timeouts too
        return False
    return True
