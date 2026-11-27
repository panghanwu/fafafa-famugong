import argparse
import os
import pydoc
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from fafafafamugong import king, log, vibe
from fafafafamugong.access import find_age, list_models, login, read_key, read_kingdom, setup, switch_model
from fafafafamugong.schema import KING, to_age
from fafafafamugong.session import (SessionError, find_sessions, get_context_tokens, get_last_active, get_last_usage,
                                    get_preview, get_session_id, is_in_use)
from fafafafamugong.settings import CONFIG_NAME, PLAYABLE_AGES, load_settings
from fafafafamugong.wololo import chat


def main():
    if sys.argv[1:2] == ['king']:  # the admin console, before anything touches a home
        king.run(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(prog='fa', epilog=f'team mode: sudo fa king manages {KING}')
    parser.add_argument('-H', '--home', type=Path, help='where fa keeps its data (default: $FA_HOME or ~/.famugong)')  # -h is --help
    parser.add_argument('-a', '--age', type=to_age, choices=PLAYABLE_AGES, metavar='AGE',
                        help='the age to play in, by name or level, e.g. dark or 1 (default: dark; your key sets it in team mode)')
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
    kingdom = read_kingdom()  # team mode if king.toml exists
    if kingdom and args.age:
        vibe.notice('warn', '--age ignored', 'in team mode your key sets the age')

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
        setup(home, kingdom)
        return
    locked = {'llm_base_url': kingdom.llm_base_url} if kingdom else {}  # the admin's settings win over config.toml
    defaults = {'wololo_model': kingdom.default_wololo_model} if kingdom and kingdom.default_wololo_model else {}
    settings = load_settings(home, defaults, llm_api_key=read_key(home), **locked)
    if args.login or settings.llm_api_key is None:
        settings.llm_api_key = login(settings.llm_base_url, home, kingdom)
        if args.login:
            return
    if kingdom:
        settings.age = find_age(kingdom, settings.llm_api_key)  # exits on an unregistered key
    elif args.age:
        settings.age = args.age
    if args.model == '':  # -m without a name
        list_models(settings)
        return
    if args.model:
        switch_model(home, settings, args.model)
    chat(settings, home, folder, (kingdom.banner or vibe.TEAM_BANNER) if kingdom else None)


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
