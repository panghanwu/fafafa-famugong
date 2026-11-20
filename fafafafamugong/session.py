import json
import secrets
from datetime import datetime
from pathlib import Path


class Session:
    def __init__(self, home: Path, meta: dict, system_prompt: str):
        self.home = home
        self.meta = meta
        self.messages = [{'role': 'system', 'content': system_prompt}]
        self.dir = None  # created on the first user message

    def append(self, message: dict, interrupted: bool = False):
        if self.dir is None:  # before the first user message
            self._start()
        self.messages.append(message)
        self._append_record(message, interrupted)

    def rename(self, title: str):
        self.meta['title'] = title
        if self.dir is not None:  # otherwise _start() writes it later
            self._write_meta()

    def _start(self):
        now = datetime.now().astimezone()
        self.dir = self.home / 'sessions' / f'{now:%Y-%m-%dT%H-%M}-{secrets.token_hex(3)}'
        self.meta_path = self.dir / 'meta.json'
        self.full_path = self.dir / 'full.jsonl'
        self.current_path = self.dir / 'current.jsonl'
        self.dir.mkdir(parents=True)
        self.meta = {'started_at': now.isoformat(timespec='seconds'), **self.meta}
        self._write_meta()
        self._append_record(self.messages[0])  # the system prompt

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
