import json
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Self

from filelock import FileLock, Timeout


class Session:
    def __init__(self, home: Path, system_prompt: str):
        self.home = home
        self.meta = {}  # a title or run can arrive before _start()
        self.messages = [{'role': 'system', 'content': system_prompt}]
        self.usage = None  # token usage of the last reply
        self.dir = None  # created on the first user message

    @classmethod
    def load(cls, folder: Path, system_prompt: str) -> Self:
        """Reopen a saved session, swapping in the current system prompt."""
        session = cls(folder.parent.parent, system_prompt)
        session._set_paths(folder)
        session._lock()
        session.meta = json.loads(session.meta_path.read_text())
        with session.current_path.open() as f:
            old = [json.loads(line) for line in f]
        session.messages += [m for m in old if m['role'] != 'system']
        session.usage = get_last_usage(folder)

        # update full.jsonl
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': session.messages[0], 'resumed': True}
        session._append_jsonl(session.full_path, record)

        # update current.jsonl
        session._rewrite_current()
        return session

    def append(self, message: dict, interrupted: bool = False, usage: dict | None = None):
        if self.dir is None:  # before the first user message
            self._start()
        self.messages.append(message)
        if usage is not None:
            self.usage = usage
        self._append_record(message, interrupted=interrupted, usage=usage)

    def rename(self, title: str):
        self.meta['title'] = title
        if self.dir is not None:  # otherwise _start() writes it later
            self._write_meta()

    def add_run(self, run: dict):
        """Record this run's cwd, model and age in meta.json."""
        now = datetime.now().astimezone().isoformat(timespec='seconds')
        self.meta.setdefault('runs', []).append({'at': now, **run})
        if self.dir is not None:  # otherwise _start() writes it later
            self._write_meta()

    def estimate_tokens(self) -> int | None:
        """Estimate current tokens from the last usage, scaled by text length; None before any reply."""
        if self.usage is None:
            return None
        return round(self._tokens_per_char() * count_chars(self.messages))

    def compress(self, cut: int, summary: str):
        """Replace messages[1:cut] with the summary; full.jsonl keeps the originals."""
        rate = self._tokens_per_char() if self.usage is not None else None
        message = {'role': 'user', 'content': summary}
        replaced = cut - 1
        self.messages[1:cut] = [message]
        if rate is not None:
            tokens = round(rate * count_chars(self.messages[:_last_reply(self.messages) + 1]))
            self.usage = {'prompt_tokens': tokens, 'completion_tokens': 0, 'estimated': True}
        self.meta['compressions'] = self.meta.get('compressions', 0) + 1
        self._write_meta()
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': message, 'compressed': replaced}
        if self.usage is not None:
            record['usage'] = self.usage
        self._append_jsonl(self.full_path, record)
        self._rewrite_current()

    def retract(self):
        """Take back the last message, e.g. one that never got a reply; full.jsonl keeps a record of it."""
        message = self.messages.pop()
        if not any(m['role'] == 'user' for m in self.messages):  # a failed first message leaves no session behind
            self._discard()
            return
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': message, 'retracted': True}
        self._append_jsonl(self.full_path, record)
        self._rewrite_current()

    def _start(self):
        now = datetime.now().astimezone()
        self._set_paths(self.home / 'sessions' / f'{now:%Y-%m-%dT%H-%M}-{secrets.token_hex(3)}')
        self.dir.mkdir(parents=True)
        self._lock()
        self._write_meta()
        self._append_record(self.messages[0])  # the system prompt

    def _discard(self):
        """Delete the session folder; the next message starts a new one."""
        self.lock.release()  # before deleting, so the lock file is not held open
        shutil.rmtree(self.dir)
        self.dir = None

    def _tokens_per_char(self) -> float:
        """Tokens per character, from the last reply's usage."""
        replied = self.messages[:_last_reply(self.messages) + 1]
        return get_context_tokens(self.usage) / count_chars(replied)

    def _set_paths(self, folder: Path):
        self.dir = folder
        self.meta_path = folder / 'meta.json'
        self.full_path = folder / 'full.jsonl'
        self.current_path = folder / 'current.jsonl'

    def _lock(self):
        self.lock = FileLock(self.dir / 'lock')  # keep a reference: garbage collection releases it
        try:
            self.lock.acquire(blocking=False)
        except Timeout:
            sys.exit(f'session {get_session_id(self.dir)} is open in another terminal (see fa --list)')

    def _write_meta(self):
        self._write_atomic(self.meta_path, json.dumps(self.meta, ensure_ascii=False, indent=2) + '\n')

    def _rewrite_current(self):
        """Make current.jsonl match messages again, after a change other than an append."""
        text = ''.join(json.dumps(m, ensure_ascii=False) + '\n' for m in self.messages)
        self._write_atomic(self.current_path, text)

    def _append_record(self, message: dict, interrupted: bool = False, usage: dict | None = None):
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': message}
        if interrupted:
            record['interrupted'] = True
        if usage is not None:
            record['usage'] = usage
        self._append_jsonl(self.full_path, record)
        self._append_jsonl(self.current_path, message)

    @staticmethod
    def _write_atomic(path: Path, text: str):
        tmp = path.with_suffix('.tmp')  # same folder, so replace stays atomic
        tmp.write_text(text)
        tmp.replace(path)

    @staticmethod
    def _append_jsonl(path: Path, record: dict):
        with path.open('a') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')


def find_sessions(home: Path, prefix: str = '') -> list[Path]:
    """Sessions whose ID starts with prefix, most recently active first."""
    root = home / 'sessions'
    if not root.exists():
        return []
    folders = [
        f for f in root.iterdir()
        if (f / 'full.jsonl').exists() and get_session_id(f).startswith(prefix)
    ]
    return sorted(folders, key=get_last_active, reverse=True)


def get_session_id(folder: Path) -> str:
    """The hex suffix of the folder name, e.g. sessions/2026-11-21T15-49-039f90 -> 039f90."""
    return folder.name.rsplit('-', 1)[-1]


def get_last_active(folder: Path) -> float:
    return (folder / 'full.jsonl').stat().st_mtime


def get_last_usage(folder: Path) -> dict | None:
    """Token usage of the last reply that reported one, from full.jsonl."""
    with (folder / 'full.jsonl').open() as f:
        records = [json.loads(line) for line in f]
    return next((r['usage'] for r in reversed(records) if 'usage' in r), None)


def count_chars(messages: list[dict]) -> int:
    return sum(len(m['content']) for m in messages)


def _last_reply(messages: list[dict]) -> int:
    """Index of the last assistant message, or the last message if none."""
    return next((i for i in range(len(messages) - 1, -1, -1) if messages[i]['role'] == 'assistant'), len(messages) - 1)


def get_context_tokens(usage: dict) -> int:
    """Tokens held after a reply: prompt plus completion."""
    return usage['prompt_tokens'] + usage['completion_tokens']


def is_in_use(folder: Path) -> bool:
    """True if another fa process holds this session's lock."""
    lock = FileLock(folder / 'lock')
    try:
        lock.acquire(blocking=False)
    except Timeout:
        return True
    lock.release()
    return False


def get_preview(folder: Path) -> str:
    """Title, or the first message the user typed."""
    meta = json.loads((folder / 'meta.json').read_text())
    if 'title' in meta:
        return meta['title']
    with (folder / 'full.jsonl').open() as f:  # current.jsonl may open with a summary instead
        records = (json.loads(line) for line in f)
        typed = (r['message']['content'] for r in records if r['message']['role'] == 'user' and 'compressed' not in r)
        return next(typed, '(empty)')
