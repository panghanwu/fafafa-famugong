"""Log errors and crashes to <home>/error.log, without message content or keys."""
import logging
import platform
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import openai

from fafafafamugong import __version__
from fafafafamugong.session import Session, get_session_id
from fafafafamugong.settings import Settings

LOG_NAME = 'error.log'
MAX_BYTES = 1_000_000  # then it moves to error.log.1, replacing the older one
KEY = re.compile(r'sk-[\w-]+')  # LiteLLM keys; a proxy may quote one in an error

logger = logging.getLogger('fafafafamugong')
_session: Session | None = None
_settings: Settings | None = None


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.session = get_session_id(_session.dir) if _session and _session.dir else '-'
        return KEY.sub('sk-***', super().format(record))


def start(home: Path):
    """Set up error.log and catch crashes."""
    path = home / LOG_NAME
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=1, encoding='utf-8', delay=True)
    version = __version__ or 'source'
    handler.setFormatter(_Formatter(f'%(asctime)s  %(levelname)s  fa {version}  session %(session)s\n%(message)s\n'))
    logger.addHandler(handler)
    logger.propagate = False

    def on_crash(kind, error, tb):
        if issubclass(kind, KeyboardInterrupt):
            return sys.__excepthook__(kind, error, tb)
        details = {'python': platform.python_version(), 'os': platform.platform()}
        logger.critical(_describe('crash', error, details), exc_info=(kind, error, tb))
        print(f'fa crashed ({kind.__name__}); details in {path}', file=sys.stderr)

    sys.excepthook = on_crash


def watch(session: Session, settings: Settings):
    """Add this session and its settings to later entries."""
    global _session, _settings
    _session, _settings = session, settings


def record(event: str, error: BaseException, **details):
    logger.error(_describe(event, error, details))


def _describe(event: str, error: BaseException, details: dict) -> str:
    found = {}
    if error.__cause__ is not None:  # e.g. what lies under openai's 'Connection error.'
        found['cause'] = _one_line(error.__cause__)
    if isinstance(error, openai.APIStatusError):
        found['request'] = error.response.headers.get('x-litellm-call-id')  # to find it in LiteLLM's logs
    if _settings is not None:
        found['model'] = _settings.wololo_model
        found['url'] = _settings.llm_base_url
        if (tokens := _session.estimate_tokens()) is not None:
            found['context'] = f'~{tokens} tokens ({int(tokens / _settings.context_limit * 100)}%)'
    lines = [f'{event}  {_one_line(error)}']
    lines += [f'  {key}: {value}' for key, value in (found | details).items() if value is not None]
    return '\n'.join(lines)


def _one_line(error: BaseException) -> str:
    return ' '.join(f'{type(error).__name__}: {error}'.split())  # proxy messages can span lines
