# 🪓 Fafafa Famugong

A lightweight, terminal-based LLM harness.

`Famugong` talks to any OpenAI-compatible API, keeps every session on disk, and compresses long conversations on its own.

> **Beta (0.1.0b2).** Chat only.

## Install

Requires Python 3.12 or newer on macOS or Linux, and an OpenAI-compatible endpoint. `Famugong` is tested with a [LiteLLM](https://docs.litellm.ai/) proxy, which is also the easiest way to reach Claude, Gemini or local models through one API.

```bash
pipx install git+https://github.com/panghanwu/fafafa-famugong.git
```

`pip install` works too, preferably in its own virtual environment.

## Quick start

To start the harness, run:

```bash
fa
```

**The first run sets up your proxy, key and model.**

`fa --help` lists the options; type `/help` inside the chatroom for commands and shortcuts.

## Team mode

Use the `king` command to manage a team:

```bash
sudo fa king
```

It creates `/etc/famugong/king.toml`, which applies to every user on the machine.
