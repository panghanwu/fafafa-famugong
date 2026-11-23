import argparse
import os
import pydoc
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from fafafafamugong.agent import chat
from fafafafamugong.session import find_sessions, get_last_active, get_preview, get_session_id, is_in_use
from fafafafamugong.settings import REPO_ENV, Settings


def main():
    parser = argparse.ArgumentParser(prog='fa')
    parser.add_argument('-H', '--home', type=Path, help='where fa keeps its data (default: $FA_HOME or ~/.famugong)')  # -h is --help
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-l', '--list', action='store_true', help='list sessions, latest first')
    group.add_argument('-r', '--resume', nargs='?', const='', metavar='ID', help='resume the latest session, or one by ID')
    args = parser.parse_args()

    home = args.home or Path(os.environ.get('FA_HOME') or Path.home() / '.famugong')
    home = home.expanduser()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)

    if args.list:
        folders = find_sessions(home)
        if not folders:
            sys.exit('no sessions yet')
        os.environ.setdefault('LESS', 'FRX')  # like git: no pager if it fits on one screen
        pydoc.pager(format_sessions(folders) + '\n')
        return

    folder = None
    if args.resume is not None:
        folders = find_sessions(home, args.resume)
        if not folders:
            sys.exit('no matching session')
        if args.resume and len(folders) > 1:  # bare --resume just takes the latest
            sys.exit(f'several sessions match {args.resume}:\n{format_sessions(folders)}')
        folder = folders[0]

    try:
        settings = Settings()
    except ValidationError as e:
        sys.exit(f'{e}\n\nsettings file: {REPO_ENV}')
    chat(settings, home, folder)


def format_sessions(folders: list[Path]) -> str:
    lines = []
    for folder in folders:
        when = datetime.fromtimestamp(get_last_active(folder)).strftime('%Y-%m-%d %H:%M')
        busy = '  (in use)' if is_in_use(folder) else ''
        lines.append(f'{get_session_id(folder)}  {when}  {shorten(get_preview(folder))}{busy}')
    return '\n'.join(lines)


def shorten(text: str, width: int = 50) -> str:
    """Fit text on one line of width columns; CJK characters take two."""
    text = ' '.join(text.split())
    cols = [2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text]
    if sum(cols) <= width:
        return text
    used = 0
    for i, n in enumerate(cols):
        used += n
        if used > width - 3:  # leave room for the dots
            return text[:i].rstrip() + '...'
