import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from fafafafamugong.agent import chat
from fafafafamugong.settings import REPO_ENV, Settings


def main():
    parser = argparse.ArgumentParser(prog='fa')
    parser.add_argument('--home', type=Path)
    args = parser.parse_args()

    home = args.home or Path(os.environ.get('FA_HOME') or Path.home() / '.famugong')
    home = home.expanduser()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)

    try:
        settings = Settings()
    except ValidationError as e:
        sys.exit(f'{e}\n\nsettings file: {REPO_ENV}')
    chat(settings)