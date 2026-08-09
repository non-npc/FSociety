from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

from nostr_sdk import Event, EventBuilder, Kind, PublicKey, Tag


PREFIX = "fsociety-group1:"


@dataclass(frozen=True, slots=True)
class GroupInvite:
    group_id: str
    name: str
    inviter: str
    creator: str
    invited: str
    members: tuple[str, ...]
    expires_at: int


def create_group_invite(
    keys,
    group_id: str,
    name: str,
    invited_pubkey: str,
    members: list[str],
    *,
    creator_pubkey: str = "",
    lifetime_seconds: int = 24 * 60 * 60,
) -> str:
    invited = PublicKey.parse(invited_pubkey).to_hex()
    inviter = keys.public_key().to_hex()
    creator = PublicKey.parse(creator_pubkey).to_hex() if creator_pubkey else inviter
    normalized_members = tuple(
        dict.fromkeys(
            PublicKey.parse(value).to_hex()
            for value in [*members, creator, inviter, invited]
        )
    )
    expires = int(time.time()) + lifetime_seconds
    content = json.dumps(
        {
            "name": name.strip() or "Encrypted group",
            "creator": creator,
            "invited": invited,
            "members": normalized_members,
            "expires": expires,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    event = (
        EventBuilder(Kind(30078), content)
        .tags(
            [
                Tag.custom("d", [f"fsociety-group-invite:{group_id}:{invited}"]),
                Tag.custom("h", [group_id]),
                Tag.public_key(PublicKey.parse(invited)),
                Tag.custom("expiration", [str(expires)]),
            ]
        )
        .finalize(keys)
    )
    encoded = base64.urlsafe_b64encode(event.as_json().encode("utf-8")).decode("ascii")
    return PREFIX + encoded.rstrip("=")


def parse_group_invite(code: str, current_pubkey: str) -> GroupInvite:
    clean = code.strip()
    if not clean.startswith(PREFIX):
        raise ValueError("This is not an fsociety group invite.")
    encoded = clean.removeprefix(PREFIX)
    encoded += "=" * (-len(encoded) % 4)
    try:
        event = Event.from_json(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except Exception as error:
        raise ValueError("The invite code is damaged.") from error
    if event.kind().as_u16() != 30078 or not event.verify():
        raise ValueError("The invite signature is invalid.")
    tags = [tag.to_vec() for tag in event.tags()]
    group_id = next((tag[1] for tag in tags if len(tag) >= 2 and tag[0] == "h"), "")
    if not group_id:
        raise ValueError("The invite has no group identifier.")
    try:
        payload = json.loads(event.content())
        invited = PublicKey.parse(str(payload["invited"])).to_hex()
        current = PublicKey.parse(current_pubkey).to_hex()
        members = tuple(PublicKey.parse(value).to_hex() for value in payload["members"])
        creator = PublicKey.parse(str(payload.get("creator") or event.author().to_hex())).to_hex()
        expires = int(payload["expires"])
    except Exception as error:
        raise ValueError("The invite payload is invalid.") from error
    if invited != current:
        raise ValueError("This invite was issued to a different Nostr identity.")
    if expires < int(time.time()):
        raise ValueError("This group invite has expired.")
    inviter = event.author().to_hex()
    if inviter not in members or creator not in members or invited not in members:
        raise ValueError("The signed membership list is incomplete.")
    return GroupInvite(
        group_id,
        str(payload.get("name") or "Encrypted group"),
        inviter,
        creator,
        invited,
        tuple(dict.fromkeys(members)),
        expires,
    )
