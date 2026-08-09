from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    peer_pubkey: str | None
    display_name: str
    initials: str
    kind: str
    status: str
    accent: str
    unread_count: int
    last_message: str
    last_message_at: int
    profile_picture_png: bytes | None = None
    creator_pubkey: str = ""

    @property
    def time_label(self) -> str:
        message_time = datetime.fromtimestamp(self.last_message_at)
        now = datetime.now()
        if message_time.date() == now.date():
            return message_time.strftime("%H:%M")
        return message_time.strftime("%a")


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    conversation_id: str
    direction: str
    content: str
    sent_at: int
    delivery_state: str
    protocol: str
    author_pubkey: str | None = None
    author_name: str = ""
    attachment_path: str = ""
    attachment_mime: str = ""

    @property
    def time_label(self) -> str:
        return datetime.fromtimestamp(self.sent_at).strftime("%H:%M")
