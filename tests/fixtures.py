from __future__ import annotations

import time

from fsociety_client.database import ClientDatabase


def seed_conversation_fixtures(database: ClientDatabase) -> None:
    """Create deterministic records used only by the automated test suite."""
    now = int(time.time())
    conversations = (
        ("zero", "01" * 32, "zero_cool", "Z3", "direct", "encrypted", "cyan", 0, now - 60),
        ("cipher", "02" * 32, "cipherpunk", "C9", "direct", "encrypted", "coral", 2, now - 1560),
        ("ops", None, "# night-ops", "OP", "group", "private group", "violet", 6, now - 6180),
        ("elliot", "03" * 32, "elliot.r", "ER", "direct", "offline", "cyan", 0, now - 86400),
        ("mesh", None, "# relay-mesh", "RM", "group", "relay group", "cyan", 0, now - 172800),
        ("saved", None, "Test local record", "TR", "direct", "local", "coral", 0, now - 259200),
    )
    database.connection.executemany(
        """INSERT INTO conversations
           (id, peer_pubkey, display_name, initials, kind, status, accent,
            unread_count, last_message_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        conversations,
    )
    database.connection.executemany(
        "INSERT INTO contacts(pubkey, nickname, added_at) VALUES (?, '', ?)",
        ((pubkey, now) for pubkey in ("01" * 32, "02" * 32, "03" * 32)),
    )
    messages = (
        ("zero", "incoming", "Relay connection established.", now - 420, "received", "NIP-17"),
        ("zero", "outgoing", "Send the configuration.", now - 260, "relay-accepted", "NIP-17"),
        ("zero", "incoming", "SHA-256 verified.", now - 60, "received", "NIP-17"),
        ("cipher", "incoming", "The image reached Blossom.", now - 1680, "received", "NIP-17"),
        ("cipher", "incoming", "The attachment is mirrored.", now - 1560, "received", "NIP-17"),
        ("ops", "incoming", "A group message.", now - 6300, "received", "NIP-17"),
        ("ops", "outgoing", "Acknowledged.", now - 6180, "relay-accepted", "NIP-17"),
        ("elliot", "incoming", "Attachment received.", now - 86520, "received", "NIP-17"),
        ("elliot", "outgoing", "Verified.", now - 86400, "relay-accepted", "NIP-17"),
        ("mesh", "system", "Health check completed.", now - 172800, "local", "LOCAL"),
    )
    database.connection.executemany(
        """INSERT INTO messages
           (conversation_id, direction, content, sent_at, delivery_state, protocol)
           VALUES (?, ?, ?, ?, ?, ?)""",
        messages,
    )
    database.connection.commit()
