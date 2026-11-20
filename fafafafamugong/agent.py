from pathlib import Path

from openai import OpenAI

from fafafafamugong import slash
from fafafafamugong.schema import BLACKSMITH, Age, Tech
from fafafafamugong.session import Session
from fafafafamugong.settings import Settings


def cook_system_prompt(age: Age, techs: dict[str, Tech]) -> str:
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
    session = Session(home, session_meta, cook_system_prompt(age, techs))

    while True:
        try:
            user = input('> ')
        except (EOFError, KeyboardInterrupt):
            break
        if not user.strip():
            continue

        command = slash.parse(user)
        if command is not None:
            user = slash.dispatch(*command, commands, session)
            if user is None:  # handled locally, nothing to send
                continue

        session.append({'role': 'user', 'content': user})
        parts = []
        interrupted = False
        try:
            with client.chat.completions.create(model=settings.model, messages=session.messages, stream=True) as stream:
                for chunk in stream:
                    if not chunk.choices:  # some chunks carry only metadata
                        continue
                    text = chunk.choices[0].delta.content or ''  # content can be None
                    print(text, end='', flush=True)
                    parts.append(text)
        except KeyboardInterrupt:
            interrupted = True

        if interrupted:
            hint = ' use /continue to finish the reply' if parts else ''
            print(f'\n[interrupted]{hint}')
        else:
            print()

        if parts:
            session.append({'role': 'assistant', 'content': ''.join(parts)}, interrupted)
