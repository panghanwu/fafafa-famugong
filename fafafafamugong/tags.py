from enum import StrEnum


class PromptTag(StrEnum):
    """Unified tag names for prompts"""
    SHORTCUT = 'SHORTCUT'
    COMPRESSED = 'COMPRESSED'


MEANINGS = {  # listed in the system prompt
    PromptTag.SHORTCUT: 'an instruction the user inserted with a shortcut; follow it as part of their message without mentioning the tag',
    PromptTag.COMPRESSED: (
        'a summary of the earlier part of this conversation, written to save space. Details and exact wording may be lost; '
        'if asked for them, say that part was compressed instead of guessing. Do not copy its style'
    ),
}
assert set(MEANINGS) == set(PromptTag), 'every tag needs a meaning'


def mark_text(text: str, tag: str) -> str:
    tag = tag.upper()
    return f'<{tag}>\n{text}\n</{tag}>'


def is_marked(text: str, tag: str) -> bool:
    return text.startswith(f'<{tag.upper()}>\n')


def describe_tags() -> str:
    """Tag list for the system prompt."""
    return 'What each tag means:\n' + '\n'.join(f'- <{tag}>: {meaning}' for tag, meaning in MEANINGS.items())
