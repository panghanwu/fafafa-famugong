from enum import StrEnum


class PromptTag(StrEnum):
    """Unified tag names for prompts"""
    SHORTCUT = 'SHORTCUT'


MEANINGS = {  # what each tag tells the model; listed in the system prompt
    PromptTag.SHORTCUT: 'an instruction the user inserted with a shortcut; follow it as part of their message without mentioning the tag',
}
assert set(MEANINGS) == set(PromptTag), 'every tag needs a meaning'


def mark_text(text: str, tag: str) -> str:
    tag = tag.upper()
    return f'<{tag}>\n{text}\n</{tag}>'


def describe_tags() -> str:
    """The tag list for the system prompt."""
    return 'What each tag means:\n' + '\n'.join(f'- <{tag}>: {meaning}' for tag, meaning in MEANINGS.items())
