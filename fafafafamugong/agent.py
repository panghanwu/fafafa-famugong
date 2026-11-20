from pathlib import Path

from openai import OpenAI

from fafafafamugong import slash
from fafafafamugong.schema import BLACKSMITH, Age, Tech
from fafafafamugong.session import Session
from fafafafamugong.settings import Settings


def system_prompt(age: Age, techs: dict[str, Tech]) -> str:
    """Identity plus every skill; dark has no tools, so skills are always loaded."""
    parts = [age.identity.strip()]
    for name, tech in techs.items():
        if tech.type == 'skill':
            parts.append(f'# Skill: {name}\n{tech.description}\n\n{tech.prompt.strip()}')
    return '\n\n'.join(parts)


def chat(settings: Settings, home: Path):
    age = Age.load(settings.age)
    techs = Tech.load(BLACKSMITH)
    commands = slash.merge(techs)
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

    add({'role': 'system', 'content': system_prompt(age, techs)})

    while True:
        try:
            user = input('> ')
        except (EOFError, KeyboardInterrupt):
            break
        if not user.strip():
            continue

        command = slash.parse(user)
        if command is not None:
            user = slash.dispatch(*command, commands)
            if user is None:  # handled locally, nothing to send
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
