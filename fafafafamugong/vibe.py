"""Terminal UI: reading input and showing output; no harness logic here."""
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import Lexer
from rich.console import Console
from rich.errors import MarkupError, StyleSyntaxError
from rich.live import Live
from rich.markdown import Markdown
from rich.segment import Segment
from rich.spinner import Spinner
from rich.style import Style
from rich.table import Table
from rich.text import Text

from fafafafamugong import __version__
from fafafafamugong.schema import SLASH_NAME, Tech
from fafafafamugong.session import Session, get_context_tokens, get_session_id
from fafafafamugong.settings import COMPRESS_AT, Settings
from fafafafamugong.tags import PromptTag, is_marked

console = Console()
PROMPT = '\n> '  # the plain prompt, used without a terminal
CODE_THEME = 'monokai'
SLASH_STYLE = 'bold dim'  # a /name that takes effect, in the input box and when the message is shown again
CONTEXT_STYLES = [  # the context share on the status line: (share it starts at, style), highest first
    (COMPRESS_AT, '#e06c75'),  # coral: fa compresses before sending the next message
    (0.5, '#d19a66'),  # amber: filling up
    (0, 'dim'),
]
IN_USE_STYLE = 'yellow'  # a session another fa holds, in fa --list
MARKERS = {  # marker per command kind in the completion menu and /help: (symbol, style)
    'builtin': ('●', ''),  # runs inside fa
    'shortcut': ('○', ''),  # gets inserted into the message
    'skill': ('◇', ''),  # loaded by the model; only in /help, since it cannot be typed
}
HELP_SECTIONS = {  # kind: (title, note)
    'builtin': ('commands', 'at the start of a message'),
    'shortcut': ('shortcuts', 'anywhere in a message'),
    'skill': ('skills', 'used by the model when it fits'),
}
KEYS = [('esc+enter', 'new line'), ('ctrl+c', 'clear the line'), ('ctrl+d', 'quit')]
LEVELS = {  # notice level: (symbol, colour)
    'info': ('›', 'blue'),
    'ok': ('✓', 'green'),
    'warn': ('!', 'yellow'),
    'error': ('✗', 'red'),
}
COMPRESSING_STYLE = '#d19a66'  # the spinner while compressing; the amber of a filling context
PRERELEASE_STYLE = '#d19a66'  # the same amber: not final yet
PRERELEASES = {'a': 'alpha', 'b': 'beta', 'rc': 'rc'}  # PEP 440 pre-release letters
TEAM_BANNER = '[bold white on #c678dd] TEAM MODE [/]'  # above the banner in team mode, unless king.toml sets one
STATES = {  # reply state: (label, style)
    'sent': ('sent', 'dim'),  # request out, nothing back yet
    'thinking': ('thinking', 'magenta'),  # reasoning arriving before the reply, e.g. from a local model
    'writing': ('wololo', 'cyan'),  # the reply is streaming
}


# Input

def make_reader(home: Path, commands: dict, session: Session, settings: Settings) -> Callable[[str], str]:
    """Return read(draft), which reads one message; it raises EOFError or KeyboardInterrupt to leave."""
    if not sys.stdin.isatty():  # piped input: plain input(), no draft
        return lambda draft='': input(PROMPT)
    menu = {}  # name -> (kind, description)
    for name, command in sorted(commands.items(), key=lambda item: isinstance(item[1], Tech)):  # built-ins first
        if isinstance(command, Tech):
            menu[name] = ('shortcut', command.description)
        elif name not in command.aliases:  # aliases stay out of the menu; /help lists them
            menu[name] = ('builtin', command.description)
    history = home / 'input_history'
    history.touch(mode=0o600, exist_ok=True)  # every line typed ends up here
    prompt = PromptSession(
        history=FileHistory(history),
        completer=SlashCompleter(menu),
        complete_while_typing=True,  # open the menu as soon as / is typed
        lexer=SlashLexer(commands),  # mark the /names that take effect while typing
        key_bindings=_key_bindings(),
        prompt_continuation=lambda width, line_number, wrap_count: ' ' * width,  # indent extra lines under the >
        erase_when_done=True,  # the status line and the raw input go away; show_user() reprints the message
        placeholder=[('dim', 'Type a message')],  # shown while the box is empty
    )

    def read(draft: str = '') -> str:
        text = prompt.prompt([('', '\n'), *_status(session, settings), ('', '\n'), ('bold', '> ')], default=draft)
        if text.strip():
            show_user(text, commands=commands)
        return text

    return read


def _status(session: Session, settings: Settings) -> list[tuple[str, str]]:
    """Status line above the input: session, title, model and context usage."""
    parts = [get_session_id(session.dir) if session.dir else 'new session', session.meta.get('title'), settings.wololo_model]
    fragments = [('dim', '  '.join(part for part in parts if part))]
    if session.usage:
        context, style = _context(session, settings)
        fragments += [('dim', '  '), (style, context)]
    if count := session.meta.get('compressions'):
        fragments.append(('dim', f'  compressed ×{count}'))
    return fragments


def _context(session: Session, settings: Settings, limit: bool = False) -> tuple[str, str]:
    """The context share as the status line shows it: (text, style); '~' marks an estimate."""
    tokens = get_context_tokens(session.usage)
    share = tokens / settings.context_limit  # floored below to match the style thresholds
    estimate = '~' if session.usage.get('estimated') else ''
    of = f' / {_format_tokens(settings.context_limit)}' if limit else ''
    style = next(style for start, style in CONTEXT_STYLES if share >= start)
    return f'{estimate}{_format_tokens(tokens)}{of} tokens ({int(share * 100)}%)', style


def _format_tokens(count: int) -> str:
    """A token count for people: 950, 12.3k, 128k."""
    if count < 1000:
        return str(count)
    return f'{count / 1000:.1f}'.removesuffix('.0') + 'k'


def _mark_slashes(text: str, commands: dict, first_line: bool = True) -> list[tuple[str, str]]:
    """Style the /names that take effect: shortcuts anywhere, built-ins at the start."""
    fragments, last = [], 0
    for match in SLASH_NAME.finditer(text):
        command = commands.get(match[1])
        at_start = first_line and not text[:match.start()].strip()
        if isinstance(command, Tech) or (command is not None and at_start):
            fragments += [('', text[last:match.start()]), (SLASH_STYLE, match[0])]
            last = match.end()
    fragments.append(('', text[last:]))
    return fragments


class SlashLexer(Lexer):
    """Highlight /names while typing."""

    def __init__(self, commands: dict):
        self.commands = commands

    def lex_document(self, document):
        lines = document.lines
        return lambda number: _mark_slashes(lines[number], self.commands, first_line=number == 0)


class SlashCompleter(Completer):
    """Complete /names: shortcuts anywhere, built-ins at the start."""

    def __init__(self, menu: dict[str, tuple[str, str]]):
        self.menu = menu  # name -> (kind, description)

    def get_completions(self, document, complete_event):
        word = document.get_word_before_cursor(WORD=True)  # the run of non-spaces right before the cursor
        if not word.startswith('/'):
            return
        at_start = document.text_before_cursor.lstrip() == word
        typed = word[1:]
        for name, (kind, description) in self.menu.items():
            if kind == 'builtin' and not at_start:  # built-ins only run from the start of a message
                continue
            if name.startswith(typed):
                symbol, style = MARKERS[kind]
                yield Completion(
                    name,
                    start_position=-len(typed),
                    display=[(style, f'{symbol} '), ('', f'/{name}')],  # styled fragments: (style, text)
                    display_meta=description,
                )


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add('escape', 'enter')  # Esc then Enter, or Option+Enter when the terminal sends Option as Meta
    def _newline(event):
        event.current_buffer.insert_text('\n')

    @bindings.add('c-c')
    def _clear_or_quit(event):
        buffer = event.current_buffer
        if buffer.text:
            buffer.reset()  # drop what was typed, stay in the prompt
        else:
            event.app.exit(exception=KeyboardInterrupt)  # empty line: the caller quits

    return bindings


# Output

def show_banner(age: str, team_banner: str | None = None):
    """The two lines shown when fa starts, under the team banner in team mode."""
    if not console.is_terminal:  # keep piped output clean
        return
    if team_banner is not None:
        try:
            text = parse_markup(team_banner)
        except (MarkupError, StyleSyntaxError):
            text = Text(team_banner)  # broken markup: show it as written rather than not at all
        console.print(text, no_wrap=True, overflow='crop')  # wrapping would break ASCII art
    stage = _prerelease(__version__)
    console.print(Text.assemble(
        ('fafafa famugong', 'bold'), f' {__version__}' if __version__ else '', '  ', (f'{age.title()} Age', 'italic'),
        (f'  {stage}', PRERELEASE_STYLE) if stage else '',
    ))
    console.print(Text('/help for commands  esc+enter for a new line  ctrl+d to quit', style='dim'))


def parse_markup(markup: str) -> Text:
    """Text with its rich markup applied; raises MarkupError or StyleSyntaxError when it is broken."""
    text = Text.from_markup(markup)
    for span in text.spans:
        Style.parse(str(span.style))  # a bad colour only fails when the style is parsed
    return text


def _prerelease(version: str) -> str | None:
    match = re.search(r'\d(a|b|rc)\d*$', version)  # e.g. 0.1.0b1 -> beta; none for 0.1.0
    return PRERELEASES[match[1]] if match else None


def notice(level: str, tag: str, text: str = ''):
    """A one-line message from fa; level is info, ok, warn or error."""
    symbol, colour = LEVELS[level]
    console.print(Text.assemble((f'{symbol} {tag}', f'bold {colour}'), (f'  {text}' if text else '', 'dim')))


def confirm(question: str) -> bool:
    """Ask a yes-or-no question; anything but y is no."""
    symbol, colour = LEVELS['warn']
    try:
        answer = PromptSession().prompt([(f'bold ansi{colour}', f'{symbol} {question}'), ('', ' [y/N] ')])
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ('y', 'yes')


def show_status(session: Session, settings: Settings, totals: dict | None):
    """The session in detail; a new one shows only the model and the age."""
    rows = []
    if session.dir:
        rows.append(('session', Text.assemble(get_session_id(session.dir), f'  {session.meta.get("title") or ""}')))
        if runs := session.meta.get('runs'):
            started = datetime.fromisoformat(runs[0]['at']).strftime('%Y-%m-%d %H:%M')
            resumed = len(runs) - 1  # each run after the first is a resume
            times = f'  resumed {resumed} time{"s" * (resumed > 1)}' if resumed else ''
            rows.append(('started', Text.assemble(started, (times, 'dim'))))
    rows.append(('model', Text(settings.wololo_model)))
    rows.append(('age', Text(f'{settings.age.title()} Age', 'italic')))
    if session.usage:
        context, style = _context(session, settings, limit=True)
        compressions = session.meta.get('compressions')
        rows.append(('context', Text.assemble((context, style), (f'  compressed ×{compressions}' if compressions else '', 'dim'))))
    if totals:
        rows.append(('turns', Text(str(totals['turns']))))
        tokens = f'{_format_tokens(totals["prompt_tokens"])} tokens in, {_format_tokens(totals["completion_tokens"])} out'
        cost = f'${totals["cost"]:.4f}  ' if totals['cost'] is not None else ''  # only APIs such as LiteLLM report it
        rows.append(('spent', Text.assemble(cost, (tokens, 'dim'))))
    grid = Table.grid(padding=(0, 2))
    for label, value in rows:
        grid.add_row(Text(label, 'dim'), value)
    console.print(Indent(grid))


def show_help(commands: dict, skills: dict[str, Tech]):
    """List commands, shortcuts, skills and keys."""
    rows = {kind: [] for kind in HELP_SECTIONS}  # kind -> [(name, aliases, description, usage)]
    for name, command in commands.items():
        if isinstance(command, Tech):
            rows['shortcut'].append((f'/{name}', '', command.description, ''))
        elif name not in command.aliases:
            aliases = '  '.join(f'/{alias}' for alias in command.aliases)
            rows['builtin'].append((f'/{name}', aliases, command.description, command.usage))
    for name, skill in skills.items():
        rows['skill'].append((name, '', skill.description, ''))

    every = [row for kind_rows in rows.values() for row in kind_rows]
    name_width = max((len(row[0]) for row in every), default=0) + 2  # room for the marker
    alias_width = max((len(row[1]) for row in every), default=0)
    for kind, (title, note) in HELP_SECTIONS.items():
        if not rows[kind]:
            continue
        console.print()
        console.print(Text.assemble((title, 'bold'), (f'  {note}', 'dim')))
        symbol, style = MARKERS[kind]
        grid = Table.grid(padding=(0, 2))
        grid.add_column(min_width=name_width, no_wrap=True)
        if alias_width:
            grid.add_column(min_width=alias_width, no_wrap=True)
        grid.add_column()  # the description wraps within its own column
        for name, aliases, description, usage in sorted(rows[kind]):
            cells = [Text.assemble((f'{symbol} ', style), (name, 'bold'))]
            if alias_width:
                cells.append(Text(aliases, style='dim'))
            cells.append(Text.assemble(description, (f'  {usage}' if usage else '', 'dim')))
            grid.add_row(*cells)
        console.print(Indent(grid))
    console.print()
    keys = Text('   ').join(Text.assemble((key, 'bold'), (f' {action}', 'dim')) for key, action in KEYS)
    console.print(Text.assemble(('keys', 'bold'), '  ', keys))


def show_models(models: list[str], current: str | None = None, numbered: bool = False):
    width = len(str(len(models)))
    for number, name in enumerate(models, 1):
        line = Text(f'{number:>{width}}  ' if numbered else '', style='dim')
        line.append(name, style='bold' if name == current else '')
        if name == current:
            line.append('  (current)', style='dim')
        console.print(line)


def render_sessions(rows: list[tuple[str, str, str, str, bool]]) -> str:
    """The session list for a pager; plain text when piped."""
    header = '  '.join(['id'.ljust(6), 'last active'.ljust(16), 'context'.rjust(7), 'title'])
    lines = [Text(header, style='dim')]
    for session_id, when, share, preview, busy in rows:
        line = Text(f'{session_id}  {when}  {share:>7}  {preview}')
        if busy:
            line.append('  (in use)', style=IN_USE_STYLE)
        lines.append(line)
    with console.capture() as capture:
        console.print(Text('\n').join(lines), soft_wrap=True)  # the pager wraps long lines, not rich
    return capture.get().rstrip('\n')


def show_user(text: str, clock: bool = True, commands: dict | None = None):
    """Echo the user's message with its /names highlighted."""
    _header('you', 'green', time.strftime('%H:%M') if clock else '')
    body = Text.assemble(*[(part, style) for style, part in _mark_slashes(text, commands or {})])
    console.print(Indent(body))


def show_resumed(session: Session, commands: dict | None = None):
    """Announce the resumed session and show its last turn."""
    console.print()
    notice('info', 'resumed', '  '.join(part for part in [get_session_id(session.dir), session.meta.get('title')] if part))
    show_last_turn(session, commands)


def show_last_turn(session: Session, commands: dict | None = None):
    for message in session.messages[-2:]:
        if message['role'] == 'user' and not is_marked(message['content'], PromptTag.COMPRESSED):
            show_user(message['content'], clock=False, commands=commands)
        elif message['role'] == 'assistant':
            _header('fa', 'blue')
            console.print(Indent(Markdown(message['content'], code_theme=CODE_THEME)))


class Flare:
    """Show one streamed reply; use it as a context manager and feed it with think() and write()."""

    def __init__(self, model: str):
        self.model = model
        self.text = ''  # the whole reply so far
        self._pending = ''  # the block still arriving
        self._first = True
        self._state = 'sent'
        self._spinner = Spinner('dots')

    def __enter__(self):
        _header('fa', 'blue', time.strftime('%H:%M'), self.model)
        self._start = time.monotonic()
        self._live = Live(self, console=console, refresh_per_second=12, transient=True)
        self._live.start()
        return self

    def __exit__(self, *exc):
        self._live.stop()
        if self._pending.strip():
            console.print(self._block(self._pending))
        return False  # let Ctrl+C and errors reach the caller

    def think(self, text: str):
        if text and not self.text:
            self._state = 'thinking'

    def write(self, text: str):
        if not text:
            return
        self._state = 'writing'
        self.text += text
        self._pending += text
        while (cut := _block_end(self._pending)) is not None:
            block, self._pending = self._pending[:cut], self._pending[cut:]
            renderable = self._block(block)
            self._first = False
            console.print(renderable)  # lands above the live area

    def _block(self, markdown: str):
        return Indent(Markdown(markdown, code_theme=CODE_THEME), gap=not self._first)

    def __rich_console__(self, console, options):  # what the live area shows, redrawn about 12 times a second
        if self._pending.strip():
            yield self._block(self._pending)
        label, style = STATES[self._state]
        elapsed = time.monotonic() - self._start
        self._spinner.update(text=Text.assemble((label, style), (f'  {elapsed:.1f}s  ctrl+c to stop', 'dim')), style=style)
        yield Indent(self._spinner)


class Busy:
    """Spinner line for work other than a reply, e.g. Busy('compressing')."""

    def __init__(self, label: str, style: str = COMPRESSING_STYLE):
        self.label = label
        self.style = style
        self._spinner = Spinner('dots')

    def __enter__(self):
        self._start = time.monotonic()
        self._live = Live(self, console=console, refresh_per_second=12, transient=True)
        self._live.start()
        return self

    def __exit__(self, *exc):
        self._live.stop()
        return False  # let Ctrl+C and errors reach the caller

    def __rich_console__(self, console, options):
        elapsed = time.monotonic() - self._start
        text = Text.assemble((self.label, self.style), (f'  {elapsed:.1f}s  ctrl+c to stop', 'dim'))
        self._spinner.update(text=text, style=self.style)
        yield Indent(self._spinner)


def show_compressed(before: int, after: int, low: bool = False):
    """Show how much compression saved; when low, suggest a new session."""
    text = f'{1 - after / before:.0%} smaller  ~{_format_tokens(before)} → ~{_format_tokens(after)} tokens'
    if low:
        notice('warn', 'compressed', f'{text}; consider a new session')
    else:
        notice('ok', 'compressed', text)


def _header(name: str, colour: str, *details: str):
    console.print()
    console.print(Text.assemble((name, f'bold {colour}'), *[(f'  {detail}', 'dim') for detail in details if detail]))


def _block_end(text: str) -> int | None:
    """Index after the first finished block: a blank line outside a code fence."""
    in_fence, pos = False, 0
    for line in text.splitlines(keepends=True):
        pos += len(line)
        if not line.endswith('\n'):
            break  # this line is still arriving
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
        elif not line.strip() and not in_fence and pos > len(line):
            return pos
    return None


class Indent:
    """Indent by two spaces without trailing padding, so copied text stays clean."""

    def __init__(self, renderable, gap: bool = False):
        self.renderable = renderable
        self.gap = gap  # start with a blank line, unless the renderable already does

    def __rich_console__(self, console, options):
        lines = console.render_lines(self.renderable, options.update_width(options.max_width - 2), pad=False)
        if self.gap and lines and not _is_blank(lines[0]):
            yield Segment.line()
        for line in lines:
            line = _rstrip(line)
            if line:
                yield Segment('  ')
                yield from line
            yield Segment.line()


def _is_blank(line: list[Segment]) -> bool:
    return not _rstrip(line)


def _rstrip(line: list[Segment]) -> list[Segment]:
    """Drop trailing spaces that have no background; code blocks keep theirs."""
    line = list(line)
    while line:
        segment = line[-1]
        if segment.control or (segment.style and segment.style.bgcolor):
            break
        text = segment.text.rstrip(' ')
        if text:
            line[-1] = Segment(text, segment.style)
            break
        line.pop()
    return line
