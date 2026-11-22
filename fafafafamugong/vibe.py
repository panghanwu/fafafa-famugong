"""Terminal UI: how fa reads input and shows output. Harness logic stays out of this module."""
import sys
from pathlib import Path
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from fafafafamugong.schema import Tech
from fafafafamugong.slash import BuiltinCommand

PROMPT = '\n> '
MARKERS = {  # menu marker per command kind: (symbol, style)
    'builtin': ('!', 'fg:ansiyellow'),  # runs inside fa
    'shortcut': ('>', 'fg:ansicyan'),  # becomes a message to the model
}


def make_reader(home: Path, commands: dict[str, BuiltinCommand | Tech]) -> Callable[[], str]:
    """
    Return a function that reads one message from the user.

    It raises EOFError (Ctrl+D) or KeyboardInterrupt (Ctrl+C on an empty line) when the user wants to leave.
    Without a terminal, e.g. piped input, it falls back to plain input().
    """
    if not sys.stdin.isatty():
        return lambda: input(PROMPT)
    menu = {}  # name -> (kind, description); built-ins first, aliases left out since /help lists them
    for name, command in sorted(commands.items(), key=lambda item: not isinstance(item[1], BuiltinCommand)):
        if isinstance(command, BuiltinCommand):
            if name not in command.aliases:
                menu[name] = ('builtin', command.description)
        else:
            menu[name] = ('shortcut', command.description)
    history = home / 'input_history'
    history.touch(mode=0o600, exist_ok=True)  # every line typed ends up here
    session = PromptSession(
        history=FileHistory(history),
        completer=SlashCompleter(menu),
        complete_while_typing=True,  # open the menu as soon as / is typed
        key_bindings=_key_bindings(),
        prompt_continuation=lambda width, line_number, wrap_count: ' ' * width,  # indent extra lines under the >
    )
    return lambda: session.prompt(PROMPT)


class SlashCompleter(Completer):
    """Suggest command names while the input is '/' plus part of a name."""

    def __init__(self, menu: dict[str, tuple[str, str]]):
        self.menu = menu  # name -> (kind, description)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith('/') or ' ' in text:  # plain chat, or already typing arguments
            return
        typed = text[1:]
        for name, (kind, description) in self.menu.items():
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
