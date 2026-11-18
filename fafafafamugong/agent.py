from openai import OpenAI

from fafafafamugong.schema import Age
from fafafafamugong.settings import Settings


def chat(settings: Settings):
    age = Age.load(settings.age)
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    messages = [{'role': 'system', 'content': age.identity}]

    while True:
        try:
            user = input('> ')
        except (EOFError, KeyboardInterrupt):
            break
        if not user.strip():
            continue

        messages.append({'role': 'user', 'content': user})
        stream = client.chat.completions.create(model=settings.model, messages=messages, stream=True)
        parts = []
        for chunk in stream:
            if not chunk.choices:  # some chunks carry only metadata
                continue
            text = chunk.choices[0].delta.content or ''  # content can be None
            print(text, end='', flush=True)
            parts.append(text)
        print()
        messages.append({'role': 'assistant', 'content': ''.join(parts)})