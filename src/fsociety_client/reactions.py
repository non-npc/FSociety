from __future__ import annotations

import json


REACTION_PREFIX = "fsociety-reaction:"
MESSAGE_REACTION_EMOJIS = ("👍", "❤️", "😂", "😮", "😢", "🔥", "✍️")
REACTION_EMOJI_BY_BASE = {
    emoji.replace("\ufe0e", "").replace("\ufe0f", ""): emoji
    for emoji in MESSAGE_REACTION_EMOJIS
}


def normalize_reaction_emoji(value: str) -> str:
    base = value.strip().replace("\ufe0e", "").replace("\ufe0f", "")
    return REACTION_EMOJI_BY_BASE.get(base, "")


def encode_reaction(target_ref: str, emoji: str, active: bool) -> str:
    if len(target_ref) != 64 or any(
        character not in "0123456789abcdef" for character in target_ref
    ):
        raise ValueError("Reaction target is not a valid message reference.")
    emoji = normalize_reaction_emoji(emoji)
    if not emoji:
        raise ValueError("Unsupported message reaction.")
    return REACTION_PREFIX + json.dumps(
        {"v": 1, "target": target_ref, "emoji": emoji, "active": bool(active)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_reaction(content: str) -> dict[str, object] | None:
    if not content.startswith(REACTION_PREFIX):
        return None
    try:
        payload = json.loads(content.removeprefix(REACTION_PREFIX))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != 1:
        return None
    target = str(payload.get("target") or "").lower()
    emoji = normalize_reaction_emoji(str(payload.get("emoji") or ""))
    active = payload.get("active")
    if (
        len(target) != 64
        or any(character not in "0123456789abcdef" for character in target)
        or not emoji
        or not isinstance(active, bool)
    ):
        return None
    return {"target": target, "emoji": emoji, "active": active}
