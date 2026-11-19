import json
import secrets
from datetime import datetime
from pathlib import Path


class Session:
    def __init__(self, home: Path, meta: dict):
        self.home = home
        self.meta = meta
        self.dir = None    # created on the first user message
        self.pending = []  # records waiting to be written

    def append(self, message: dict):
        record = {'ts': datetime.now().astimezone().isoformat(), 'message': message}
        if self.dir is None:  # before the first user message
            self.pending.append(record)
            if message['role'] != 'user':
                return
            self._start()
            for r in self.pending:
                self._write(r)
            self.pending = []
            return
        self._write(record)

    def _write(self, record: dict):
        self._append_jsonl(self.full_path, record)
        self._append_jsonl(self.current_path, record['message'])

    def _start(self):
        now = datetime.now().astimezone()
        self.dir = self.home / 'sessions' / f'{now:%Y-%m-%dT%H-%M-%S}-{secrets.token_hex(2)}'
        self.meta_path = self.dir / 'meta.json'
        self.full_path = self.dir / 'full.jsonl'
        self.current_path = self.dir / 'current.jsonl'
        self.dir.mkdir(parents=True)
        meta = {'started_at': now.isoformat(timespec='seconds'), **self.meta}
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')

    @staticmethod
    def _append_jsonl(path: Path, record: dict):
        with path.open('a') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
