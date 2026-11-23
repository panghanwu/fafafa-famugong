"""Terminal UI: how fa reads input and shows output. Harness logic stays out of this module."""
import sys
import time
from pathlib import Path
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.segment import Segment
from rich.spinner import Spinner
from rich.text import Text

from fafafafamugong.schema import Tech
from fafafafamugong.session import Session, get_session_id

console = Console()
PROMPT = '\n> '  # the plain prompt, used without a terminal
CODE_THEME = 'monokai'
MARKERS = {  # completion menu marker per command kind: (symbol, style); the menu's own colours keep them readable
    'builtin': ('●', ''),  # runs inside fa
    'shortcut': ('○', ''),  # gets inserted into the message
}
LEVELS = {  # notice level: (symbol, colour)
    'info': ('›', 'blue'),
    'ok': ('✓', 'green'),
    'warn': ('!', 'yellow'),
    'error': ('✗', 'red'),
}
STATES = {  # reply state: (label, style)
    'sent': ('sent', 'dim'),  # request out, nothing back yet
    'thinking': ('thinking', 'magenta'),  # reasoning arriving before the reply, e.g. from a local model
    'writing': ('writing', 'cyan'),  # the reply is streaming
}


# Input

def make_reader(home: Path, commands: dict, session: Session, model: str) -> Callable[[], str]:
    """
    Return a function that reads one message from the user.

    commands maps names to built-ins and shortcuts, as slash.merge() builds it. The function raises EOFError (Ctrl+D)
    or KeyboardInterrupt (Ctrl+C on an empty line) when the user wants to leave.
    Without a terminal, e.g. piped input, it falls back to plain input().
    """
    if not sys.stdin.isatty():
        return lambda: input(PROMPT)
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
        key_bindings=_key_bindings(),
        prompt_continuation=lambda width, line_number, wrap_count: ' ' * width,  # indent extra lines under the >
        erase_when_done=True,  # the status line and the raw input go away; show_user() reprints the message
    )

    def read() -> str:
        text = prompt.prompt([('dim', f'\n{_status(session, model)}\n'), ('bold', '> ')])
        if text.strip():
            show_user(text)
        return text

    return read


def _status(session: Session, model: str) -> str:
    """The line above the input: session, title, model and context length."""
    parts = [get_session_id(session.dir) if session.dir else 'new session', session.meta.get('title'), model]
    if session.usage:
        tokens = session.usage['prompt_tokens'] + session.usage['completion_tokens']
        parts.append(f'context {tokens / 1000:.1f}k tokens' if tokens >= 1000 else f'context {tokens} tokens')
    return '  '.join(part for part in parts if part)


class SlashCompleter(Completer):
    """Suggest names while the word being typed is '/' plus part of a name: shortcuts anywhere, built-ins at the start."""

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

def notice(level: str, tag: str, text: str = ''):
    """A line from fa itself, e.g. notice('ok', 'renamed', 'JSONL reader'); level is info, ok, warn or error."""
    symbol, colour = LEVELS[level]
    console.print(Text.assemble((f'{symbol} {tag}', f'bold {colour}'), (f'  {text}' if text else '', 'dim')))


def show_user(text: str, clock: bool = True):
    _header('you', 'green', time.strftime('%H:%M') if clock else '')
    console.print(Indent(Text(text)))


def show_resumed(session: Session):
    """Say which session is back and show where it left off."""
    notice('info', 'resumed', '  '.join(part for part in [get_session_id(session.dir), session.meta.get('title')] if part))
    for message in session.messages[-2:]:
        if message['role'] == 'user':
            show_user(message['content'], clock=False)
        elif message['role'] == 'assistant':
            _header('fa', 'blue')
            console.print(Indent(Markdown(message['content'], code_theme=CODE_THEME)))


class Flare:
    """
    Show one streamed reply: a waiting line, then markdown block by block.

    Named after the flare in Age of Empires II, the signal a player sends to show up on an ally's screen.
    Use it as a context manager around the request, then feed it with think() and write().
    Finished blocks are printed for good; only the block still arriving is redrawn, so long replies are fine.
    """

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


def _header(name: str, colour: str, *details: str):
    console.print()
    console.print(Text.assemble((name, f'bold {colour}'), *[(f'  {detail}', 'dim') for detail in details if detail]))


def _block_end(text: str) -> int | None:
    """Index just past the first finished markdown block: a blank line outside a code fence."""
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
    """Indent a renderable by two spaces and drop trailing padding, so copied text stays clean."""

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
