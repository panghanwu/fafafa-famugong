import argparse
import os
import pydoc
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import get_args

from fafafafamugong import log, vibe
from fafafafamugong.access import list_models, login, read_key, setup, switch_model
from fafafafamugong.schema import to_age
from fafafafamugong.session import (SessionError, find_sessions, get_context_tokens, get_last_active, get_last_usage,
                                    get_preview, get_session_id, is_in_use)
from fafafafamugong.settings import CONFIG_NAME, Settings, load_settings
from fafafafamugong.wololo import chat


def main():
    parser = argparse.ArgumentParser(prog='fa')
    parser.add_argument('-H', '--home', type=Path, help='where fa keeps its data (default: $FA_HOME or ~/.famugong)')  # -h is --help
    ages = get_args(Settings.model_fields['age'].annotation)  # the Literal in Settings is the one list of playable ages
    parser.add_argument('-a', '--age', type=to_age, choices=ages, default='dark', metavar='AGE',
                        help='the age to play in, by name or level, e.g. dark or 1 (default: dark)')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-l', '--list', action='store_true', help='list sessions, latest first')
    group.add_argument('-r', '--resume', nargs='?', const='', metavar='ID', help='resume the latest session, or one by ID')
    group.add_argument('--login', action='store_true', help='enter a new access key')
    parser.add_argument('-m', '--model', nargs='?', const='', metavar='NAME',
                        help='switch to this model and save it; without a name, list the models on the proxy')
    args = parser.parse_args()

    os.umask(0o077)  # everything fa writes is for this user only
    home = args.home or Path(os.environ.get('FA_HOME') or Path.home() / '.famugong')
    home = home.expanduser()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    log.start(home)

    if args.list:
        folders = find_sessions(home)
        if not folders:
            sys.exit('no sessions yet')
        os.environ.setdefault('LESS', r'FRX -Ps?e(END) :\: .(q to quit)$')  # like git: no pager if it fits; the prompt says how to leave
        pydoc.pager(format_sessions(folders, load_settings(home).context_limit) + '\n')
        return

    folder = None
    if args.resume is not None:
        folders = find_sessions(home, args.resume)
        if not folders:
            sys.exit('no matching session')
        if args.resume and len(folders) > 1:  # bare --resume just takes the latest
            listing = format_sessions(folders, load_settings(home).context_limit)
            sys.exit(f'several sessions match {args.resume}:\n{listing}')
        folder = folders[0]

    if not (home / CONFIG_NAME).exists():  # first run
        setup(home)
        return
    settings = load_settings(home, llm_api_key=read_key(home), age=args.age)
    if args.login or settings.llm_api_key is None:
        settings.llm_api_key = login(settings.llm_base_url, home)
        if args.login:
            return
    if args.model == '':  # -m without a name
        list_models(settings)
        return
    if args.model:
        switch_model(home, settings, args.model)
    chat(settings, home, folder)


def format_sessions(folders: list[Path], context_limit: int) -> str:
    """Render the session list."""
    rows = []
    for folder in folders:
        when = datetime.fromtimestamp(get_last_active(folder)).strftime('%Y-%m-%d %H:%M')
        try:
            usage = get_last_usage(folder)
            preview = shorten(get_preview(folder))
        except SessionError as e:
            usage, preview = None, f'(damaged: {e})'
        share = f'{int(get_context_tokens(usage) / context_limit * 100)}%' if usage else ''  # floored like the status line
        rows.append((get_session_id(folder), when, share, preview, is_in_use(folder)))
    return vibe.render_sessions(rows)


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
