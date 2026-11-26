"""Compress the context by summarizing its earlier part."""
from openai import OpenAI

from fafafafamugong.schema import BLACKSMITH, Tech
from fafafafamugong.tags import PromptTag, is_marked, mark_text

COMPRESS = 'compress'  # its name in blacksmith.toml
COMPRESS_SHARE = 0.8  # share of the conversation, by length, to summarize
MIN_SAVING = 0.2  # a compression that saves less suggests a new session
MIN_RAW_TURNS = 3  # latest turns kept word for word


class CompressError(Exception):
    """The summary came back empty."""


def find_cut(messages: list[dict]) -> int | None:
    """
    Find the cut point for compression.

    1. Cut only at a reply, so roles keep alternating.
    2. Keep the latest MIN_RAW_TURNS turns.
    3. Skip a cut that would only summarize the earlier summary again.
    4. Pick the cut closest to COMPRESS_SHARE, or None if there is none.
    """
    starts = [
        i for i in range(1, len(messages) - 1)
        if messages[i]['role'] == 'user' and messages[i + 1]['role'] == 'assistant'
    ]  # where each replied turn starts
    cuts = [i + 1 for i in starts[:-MIN_RAW_TURNS]]
    if cuts and is_marked(messages[1]['content'], PromptTag.COMPRESSED):
        cuts = [c for c in cuts if c != 2]
    sizes = [len(m['content']) for m in messages]
    target = COMPRESS_SHARE * sum(sizes[1:])
    return min(cuts, key=lambda c: abs(sum(sizes[1:c]) - target), default=None)


def dump(messages: list[dict]) -> str:
    return '\n\n'.join(f'[{m['role']}]\n{m['content']}' for m in messages)


def summarize(client: OpenAI, model: str, messages: list[dict], cut: int) -> str:
    """Load the compress tech and prompt it with the part to summarize and the part to keep."""
    text = (
        f'## Earlier part (summarize this)\n\n{dump(messages[1:cut])}\n\n'
        f'## Recent part (stays word for word; for context only)\n\n{dump(messages[cut:])}'
    )
    tech = Tech.load(BLACKSMITH)[COMPRESS]
    response = client.chat.completions.create(
        model=model,
        messages=[{'role': 'system', 'content': tech.prompt.strip()}, {'role': 'user', 'content': text}],
    )
    summary = (response.choices[0].message.content or '').strip()
    if not summary:
        raise CompressError('the summary came back empty')
    return mark_text(summary, PromptTag.COMPRESSED)
