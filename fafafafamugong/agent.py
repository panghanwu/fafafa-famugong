from pathlib import Path

from openai import OpenAI

from fafafafamugong import slash, vibe
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


def chat(settings: Settings, home: Path, folder: Path | None = None):
    age = Age.load(settings.age)
    techs = Tech.load(BLACKSMITH)
    commands = slash.merge(techs)
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    run = {
        'cwd': str(Path.cwd()),
        'model': settings.model,
        'age': settings.age
    }
    system_prompt = cook_system_prompt(age, techs)

    # create/load session
    if folder is None:
        session = Session(home, system_prompt)
    else:
        session = Session.load(folder, system_prompt)
        vibe.show_resumed(session)
    session.add_run(run)
    read_input = vibe.make_reader(home, commands, session, settings.model)

    while True:
        try:
            user = read_input()
        except (EOFError, KeyboardInterrupt):
            break
        if not user.strip():
            continue

        user = slash.dispatch(user, commands, session)
        if user is None:  # handled locally, nothing to send
            continue

        session.append({'role': 'user', 'content': user})
        flare = vibe.Flare(settings.model)
        usage = None
        interrupted = False
        try:
            with (
                flare,
                client.chat.completions.create(
                    model=settings.model,
                    messages=session.messages,
                    stream=True,
                    stream_options={'include_usage': True},
                ) as stream,
            ):
                for chunk in stream:
                    if chunk.usage:
                        usage = {'prompt_tokens': chunk.usage.prompt_tokens, 'completion_tokens': chunk.usage.completion_tokens}
                    if not chunk.choices:  # some chunks carry only metadata
                        continue
                    delta = chunk.choices[0].delta
                    flare.think(getattr(delta, 'reasoning_content', None) or '')  # local models may stream reasoning first
                    flare.write(delta.content or '')  # content can be None
        except KeyboardInterrupt:
            interrupted = True

        if interrupted:
            vibe.notice('warn', 'interrupted', 'use /continue to finish the reply' if flare.text else '')

        if flare.text:
            session.append({'role': 'assistant', 'content': flare.text}, interrupted, usage=usage)
