"""The main agent: the chat loop."""
import sys
from pathlib import Path

import openai
from openai import OpenAI

from fafafafamugong import context, log, slash, vibe
from fafafafamugong.schema import BLACKSMITH, TOWN_CENTER, Age, Tech
from fafafafamugong.session import Session, SessionError, get_session_id, read_usage
from fafafafamugong.settings import COMPRESS_AT, Settings
from fafafafamugong.tags import describe_tags


def cook_system_prompt(age: Age, techs: dict[str, Tech]) -> str:
    """Build the system prompt: identity, town center, tags and every skill."""
    parts = [age.identity.strip(), TOWN_CENTER.read_text().strip(), describe_tags()]
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
        'model': settings.wololo_model,
        'age': settings.age
    }
    system_prompt = cook_system_prompt(age, techs)

    vibe.show_banner(settings.age)

    # create/load session
    if folder is None:
        session = Session(home, system_prompt)
    else:
        try:
            session = Session.load(folder, system_prompt)
        except SessionError as e:
            log.record('resume', e, folder=folder.name)
            sys.exit(f'session {get_session_id(folder)} is damaged: {e}')
        vibe.show_resumed(session, commands)
    session.add_run(run)
    log.watch(session, settings)
    read_input = vibe.make_reader(home, commands, session, settings)
    draft = ''  # a message that got no reply, offered again in the input box

    while True:
        try:
            user = read_input(draft)
        except (EOFError, KeyboardInterrupt):
            break
        draft = ''
        if not user.strip():
            continue

        user = slash.dispatch(user, commands, session, settings)
        if user is None:  # handled locally, nothing to send
            continue

        session.append({'role': 'user', 'content': user})
        try:
            compress_if_full(session, client, settings)
        except KeyboardInterrupt:  # stopped before anything was sent: offer the message again
            session.retract()
            draft = user
            vibe.notice('warn', 'interrupted', 'your message is back in the input box')
            continue

        flare = vibe.Flare(settings.wololo_model)
        usage = None
        interrupted = False
        error = None
        try:
            with (
                flare,
                client.chat.completions.create(
                    model=settings.wololo_model,
                    messages=slash.expand_shortcuts(session.messages, commands),  # shortcuts are filled only when sending
                    stream=True,
                    stream_options={'include_usage': True},
                ) as stream,
            ):
                for chunk in stream:
                    if chunk.usage:
                        usage = read_usage(chunk.usage)
                    if not chunk.choices:  # some chunks carry only metadata
                        continue
                    delta = chunk.choices[0].delta
                    flare.think(getattr(delta, 'reasoning_content', None) or '')  # local models may stream reasoning first
                    flare.write(delta.content or '')  # content can be None
        except KeyboardInterrupt:
            interrupted = True
        except openai.APIError as e:  # every API failure, from a dead proxy to a bad token
            error = e

        stopped = interrupted or error is not None
        if error is not None:
            log.record('reply', error)
            vibe.notice(*explain(error))
        if flare.text:
            session.append({'role': 'assistant', 'content': flare.text}, stopped, usage=usage)
            if stopped:
                vibe.notice('warn', 'interrupted', 'use /continue to finish the reply')
        elif stopped:  # nothing came back: take the message back and offer it again
            session.retract()
            draft = user
            if interrupted:
                vibe.notice('warn', 'interrupted', 'your message is back in the input box')


def compress_if_full(session: Session, client: OpenAI, settings: Settings):
    """Compress the earlier part once the context reaches COMPRESS_AT; on failure, send as is."""
    before = session.estimate_tokens()
    if before is None or before < COMPRESS_AT * settings.context_limit:
        return
    cut = context.find_cut(session.messages)
    if cut is None:
        vibe.notice('warn', 'context nearly full', 'nothing to compress; consider a new session')
        return
    compress(session, client, settings, cut)


@slash.builtin('compress', 'Compress the conversation now')  # here, since slash cannot import wololo
def _compress(session: Session, settings: Settings, args: str):
    cut = context.find_cut(session.messages)
    if cut is None:
        vibe.notice('info', 'nothing to compress')
        return
    try:
        compress(session, OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key), settings, cut)
    except KeyboardInterrupt:
        vibe.notice('warn', 'interrupted', 'nothing was compressed')


def compress(session: Session, client: OpenAI, settings: Settings, cut: int):
    """Replace messages[1:cut] with a summary; on failure, keep them."""
    before = session.estimate_tokens()
    try:
        with vibe.Busy('compressing'):
            summary = context.summarize(client, settings.wololo_model, session.messages, cut)
    except openai.APIError as e:
        log.record('compress', e)
        vibe.notice('warn', 'compression failed', explain(e)[2])
        return
    except context.CompressError as e:
        log.record('compress', e)
        vibe.notice('warn', 'compression failed', str(e))
        return
    session.compress(cut, summary)
    if before is None:  # the API reports no usage
        vibe.notice('ok', 'compressed')
        return
    after = session.estimate_tokens()
    vibe.show_compressed(before, after, low=1 - after / before < context.MIN_SAVING)


def explain(error: openai.APIError) -> tuple[str, str, str]:
    """Turn an API error into a notice: (level, tag, text)."""
    match error:
        case openai.APITimeoutError():  # before APIConnectionError, which it subclasses
            return 'error', 'timed out', 'try again'
        case openai.APIConnectionError():
            return 'error', 'connection failed', 'cannot reach the proxy; please check it'
        case openai.AuthenticationError():
            return 'error', 'unauthorized', 'run fa --login to enter a new key'
        case openai.BadRequestError() if 'Invalid model name' in error.message:  # LiteLLM's words; it has no error code for this
            return 'error', 'unknown model', 'not on the proxy; check wololo_model in config.toml'
        case openai.RateLimitError():
            return 'warn', 'rate limited', 'wait a moment and try again'
        case openai.APIStatusError():
            detail = error.body.get('message') if isinstance(error.body, dict) else None  # the server's own words
            return 'error', f'error {error.status_code}', detail or error.message
    return 'error', 'request failed', str(error)
