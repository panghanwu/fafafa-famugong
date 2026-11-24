"""The access key and the first-run setup."""
import getpass
import re
import sys
from pathlib import Path

import openai
from openai import OpenAI

from fafafafamugong import log, vibe
from fafafafamugong.settings import CONFIG_NAME, Settings, make_config
from fafafafamugong.wololo import explain

KEY_NAME = 'key'
URL = re.compile(r'https?://[^\s\'"]+')  # no spaces or quotes, so it fits in config.toml as is


def read_key(home: Path) -> str | None:
    path = home / KEY_NAME
    return path.read_text().strip() if path.exists() else None


def save_key(home: Path, key: str):
    path = home / KEY_NAME
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)  # a file left from before may be readable by others
    path.write_text(key + '\n')


def setup(home: Path):
    """First run: ask for the proxy URL and a key, then write config.toml."""
    _require_terminal('set fa up')
    default_url = Settings.model_fields['llm_base_url'].default
    default_model = Settings.model_fields['model'].default
    vibe.notice('info', 'setup', 'first run: where is your LiteLLM proxy?')
    while True:
        try:
            base_url = input(f'proxy URL [{default_url}]: ').strip() or default_url
        except (EOFError, KeyboardInterrupt):
            sys.exit('\nsetup cancelled')
        if not URL.fullmatch(base_url):
            vibe.notice('warn', 'not a URL', 'it starts with http:// or https://')
            continue
        vibe.notice('info', 'key', 'paste your access key; it stays hidden as you type')
        answer = _ask_key(base_url)
        if answer is not None:
            break
    key, models = answer
    save_key(home, key)
    vibe.notice('ok', 'logged in', f'key saved to {home / KEY_NAME}')
    path = home / CONFIG_NAME
    path.write_text(make_config({'llm_base_url': base_url}))
    vibe.notice('ok', 'created', str(path))
    if models and default_model not in models:
        vibe.notice('warn', 'model', f'{default_model} is not on this proxy; pick one in config.toml')
    vibe.notice('info', 'next', 'check the model in config.toml, then run fa again')


def login(base_url: str, home: Path) -> str:
    """Ask for a key until the proxy accepts it, then save it."""
    _require_terminal('enter one')
    vibe.notice('info', 'login', f'paste your access key for {base_url}; it stays hidden as you type')
    answer = _ask_key(base_url)
    if answer is None:
        sys.exit(1)
    key, _ = answer
    save_key(home, key)
    vibe.notice('ok', 'logged in', f'key saved to {home / KEY_NAME}')
    return key


def _ask_key(base_url: str) -> tuple[str, list[str]] | None:
    """Return a key the proxy accepts and the models it may use; None if the proxy failed."""
    while True:
        try:
            key = getpass.getpass('key: ').strip()  # never echoed, never in any history
        except (EOFError, KeyboardInterrupt):
            sys.exit('\ncancelled')
        if not key:
            continue
        try:
            models = OpenAI(base_url=base_url, api_key=key, timeout=10).models.list()  # free: no model is called
        except openai.APIError as e:
            if _is_rejected(e):
                vibe.notice('error', 'not accepted', 'check the key and try again')
                continue
            log.record('login', e, url=base_url)
            vibe.notice(*explain(e, base_url))
            return None
        return key, [model.id for model in models]


def _is_rejected(error: openai.APIError) -> bool:
    """True if the proxy refused the key; a LiteLLM without a database answers 400."""
    return isinstance(error, openai.AuthenticationError) or getattr(error, 'type', None) == 'no_db_connection'


def _require_terminal(goal: str):
    if not sys.stdin.isatty():
        sys.exit(f'no terminal: run fa in one to {goal}')
