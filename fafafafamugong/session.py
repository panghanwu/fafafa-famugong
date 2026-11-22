import json
import secrets
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

        # update full.jsonl
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': session.messages[0], 'resumed': True}
        session._append_jsonl(session.full_path, record)

        # update current.jsonl
        text = ''.join(json.dumps(m, ensure_ascii=False) + '\n' for m in session.messages)
        session._write_atomic(session.current_path, text)
        return session

    def append(self, message: dict, interrupted: bool = False):
        if self.dir is None:  # before the first user message
            self._start()
        self.messages.append(message)
        self._append_record(message, interrupted=interrupted)

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

    def _start(self):
        now = datetime.now().astimezone()
        self._set_paths(self.home / 'sessions' / f'{now:%Y-%m-%dT%H-%M}-{secrets.token_hex(3)}')
        self.dir.mkdir(parents=True)
        self._lock()
        self._write_meta()
        self._append_record(self.messages[0])  # the system prompt

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

    def _append_record(self, message: dict, interrupted: bool = False):
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': message}
        if interrupted:
            record['interrupted'] = True
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
    """The title, or the first user message; the caller shortens it."""
    meta = json.loads((folder / 'meta.json').read_text())
    if 'title' in meta:
        return meta['title']
    with (folder / 'current.jsonl').open() as f:
        messages = (json.loads(line) for line in f)
        return next((m['content'] for m in messages if m['role'] == 'user'), '(empty)')
