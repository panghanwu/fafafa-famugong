"""The access key, the first-run setup and the age a key gets in team mode."""
import getpass
import sys
import tomllib
from pathlib import Path

import openai
from openai import OpenAI
from pydantic import ValidationError

from fafafafamugong import log, vibe
from fafafafamugong.schema import KING, URL, Age, Kingdom, hint
from fafafafamugong.settings import CONFIG_NAME, PLAYABLE_AGES, Settings, make_config, set_config
from fafafafamugong.wololo import explain

KEY_NAME = 'key'
BROKEN = 'team config (king.toml) is broken; please reach out to your admin'


def read_key(home: Path) -> str | None:
    path = home / KEY_NAME
    return path.read_text().strip() if path.exists() else None


def save_key(home: Path, key: str):
    path = home / KEY_NAME
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)  # a file left from before may be readable by others
    path.write_text(key + '\n')


def setup(home: Path, kingdom: Kingdom | None = None):
    """First run: ask for the proxy URL (not in team mode) and a key, then write config.toml."""
    _require_terminal('set fa up')
    if kingdom is None:
        vibe.notice('info', 'setup', 'first run: enter the proxy URL')
        base_url, key, models = _ask_proxy()
    else:
        base_url = None  # the admin's URL stays out of sight and out of config.toml
        vibe.notice('info', 'setup', 'first run')
        vibe.notice('info', 'key', 'paste your access key; it stays hidden as you type')
        answer = _ask_key(kingdom.llm_base_url)
        if answer is None:
            sys.exit(1)
        key, models = answer
        find_age(kingdom, key)  # exits on an unregistered key, before anything is saved
    if kingdom and kingdom.default_wololo_model:
        model = None  # left out of config.toml, so the admin's default keeps applying
        vibe.notice('info', 'model', f'{kingdom.default_wololo_model}; fa -m picks another')
    else:
        model = _ask_model(models, Settings.model_fields['wololo_model'].default)
    save_key(home, key)  # only now: a cancelled setup leaves nothing behind
    vibe.notice('ok', 'logged in', f'key saved to {home / KEY_NAME}')
    path = home / CONFIG_NAME
    path.write_text(make_config({'llm_base_url': base_url, 'wololo_model': model}))
    vibe.notice('ok', 'created', str(path))
    vibe.notice('info', 'next', 'run fa to start')


def login(base_url: str, home: Path, kingdom: Kingdom | None = None) -> str:
    """Ask for a key until the proxy accepts it, then save it."""
    _require_terminal('enter one')
    where = '' if kingdom else f' for {base_url}'
    vibe.notice('info', 'login', f'paste your access key{where}; it stays hidden as you type')
    answer = _ask_key(base_url)
    if answer is None:
        sys.exit(1)
    key, _ = answer
    if kingdom is not None:
        find_age(kingdom, key)  # exits on an unregistered key, before it is saved
    save_key(home, key)
    vibe.notice('ok', 'logged in', f'key saved to {home / KEY_NAME}')
    return key


def read_kingdom() -> Kingdom | None:
    """king.toml, or None in personal mode; exits when it is broken."""
    try:
        return Kingdom.read()
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as e:
        log.record('king', e, file=str(KING))
        sys.exit(BROKEN)


def find_age(kingdom: Kingdom, key: str) -> str:
    """The key's age, capped at the playable ones; exits if the key is not registered."""
    entry = kingdom.find(key)
    if entry is None:
        sys.exit(f'key {hint(key)} is not registered; please reach out to your admin')
    ages = Age.load_all()
    return max((name for name in PLAYABLE_AGES if ages[name].level <= entry.age), key=lambda name: ages[name].level)


def _ask_proxy() -> tuple[str, str, list[str]]:
    """Ask for a proxy URL and a key it accepts."""
    default_url = Settings.model_fields['llm_base_url'].default
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
            return base_url, *answer


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
            models = fetch_models(base_url, key)
        except openai.APIError as e:
            if is_rejected(e):
                vibe.notice('error', 'not accepted', 'check the key and try again')
                continue
            log.record('login', e, url=base_url)
            vibe.notice(*explain(e))
            return None
        return key, models


def _ask_model(models: list[str], default: str) -> str:
    """Pick a model by its number or name."""
    if not models:
        vibe.notice('warn', 'no models', f'the proxy lists none for this key; using {default}, change it in config.toml')
        return default
    default = default if default in models else models[0]
    vibe.notice('info', 'model', 'pick the model to work with')
    vibe.show_models(models, numbered=True)
    while True:
        try:
            answer = input(f'model [{default}]: ').strip() or default
        except (EOFError, KeyboardInterrupt):
            sys.exit('\nsetup cancelled')
        if answer.isdigit() and 1 <= int(answer) <= len(models):
            return models[int(answer) - 1]
        if answer in models:
            return answer
        vibe.notice('warn', 'not on the list', 'type a number or a name from the list')


def fetch_models(base_url: str, key: str) -> list[str]:
    response = OpenAI(base_url=base_url, api_key=key, timeout=10).models.list()  # free: no model is called
    return sorted(model.id for model in response)


def list_models(settings: Settings):
    vibe.show_models(_models_or_exit(settings), current=settings.wololo_model)


def switch_model(home: Path, settings: Settings, name: str):
    """Save the model to config.toml once the proxy lists it."""
    models = _models_or_exit(settings)
    if name not in models:
        vibe.notice('error', 'unknown model', f'{name} is not on the proxy; pick one of these')
        vibe.show_models(models, current=settings.wololo_model)
        sys.exit(1)
    set_config(home, 'wololo_model', name)
    settings.wololo_model = name
    vibe.notice('ok', 'model', f'{name} saved to config.toml')


def _models_or_exit(settings: Settings) -> list[str]:
    try:
        return fetch_models(settings.llm_base_url, settings.llm_api_key)
    except openai.APIError as e:
        log.record('models', e, url=settings.llm_base_url)
        vibe.notice(*explain(e))
        sys.exit(1)


def is_rejected(error: openai.APIError) -> bool:
    """True if the proxy refused the key; a LiteLLM without a database answers 400."""
    return isinstance(error, openai.AuthenticationError) or getattr(error, 'type', None) == 'no_db_connection'


def _require_terminal(goal: str):
    if not sys.stdin.isatty():
        sys.exit(f'no terminal: run fa in one to {goal}')
