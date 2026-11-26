# Trees

## `~/.famugong`

```text
~/.famugong/                      fa's data; FA_HOME or -H moves it
├── config.toml                   proxy URL, model, ...
├── key                           access key, from fa --login
├── input_history                 past inputs
├── error.log                     errors and crashes
└── sessions/
    └── 2026-11-24T10-00-3f2a1b/  one conversation; its ID is 3f2a1b
        ├── meta.json             title and runs
        ├── full.jsonl            every message, append only
        ├── current.jsonl         the context sent to the model
        └── lock                  held while the session is open
```

## The repo

```text
fafafa-famugong/
├── fafafafamugong/          the fa package
│   ├── cli.py               arguments and startup
│   ├── access.py            first run, login and models
│   ├── wololo.py            the chat loop
│   ├── slash.py             commands and shortcuts
│   ├── context.py           compression
│   ├── session.py           sessions on disk
│   ├── log.py               error.log
│   ├── settings.py          config.toml
│   ├── schema.py            reads ages.toml and blacksmith.toml
│   ├── tags.py              prompt tags
│   ├── vibe.py              terminal UI
│   ├── ages.toml            the four ages
│   ├── blacksmith.toml      shortcuts, skills and command prompts
│   ├── towncenter.md        the system prompt every age shares
│   ├── __init__.py          the version
│   └── __main__.py          python -m fafafafamugong
├── docs/                    architecture and file trees
├── pyproject.toml
├── README.md
└── LICENSE
```
