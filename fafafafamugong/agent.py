from pathlib import Path

from openai import OpenAI

from fafafafamugong.schema import Age
from fafafafamugong.session import Session
from fafafafamugong.settings import Settings


def chat(settings: Settings, home: Path):
    age = Age.load(settings.age)
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    session_meta = {
        'cwd': str(Path.cwd()),
        'model': settings.model,
        'age': settings.age
    }
    session = Session(home, session_meta)
    messages = []

    def add(message: dict):
        messages.append(message)
        session.append(message)

    add({'role': 'system', 'content': age.identity})

    while True:
        try:
            user = input('> ')
        except (EOFError, KeyboardInterrupt):
            break
        if not user.strip():
            continue

        add({'role': 'user', 'content': user})
        stream = client.chat.completions.create(model=settings.model, messages=messages, stream=True)
        parts = []
        for chunk in stream:
            if not chunk.choices:  # some chunks carry only metadata
                continue
            text = chunk.choices[0].delta.content or ''  # content can be None
            print(text, end='', flush=True)
            parts.append(text)
        print()
        add({'role': 'assistant', 'content': ''.join(parts)})