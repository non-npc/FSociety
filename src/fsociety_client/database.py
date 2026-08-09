from __future__ import annotations

import sqlite3
import time
import json
from pathlib import Path

from .attachment_types import guess_attachment_mime
from .models import Conversation, Message


SCHEMA_VERSION = 11


class ClientDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                peer_pubkey TEXT,
                creator_pubkey TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL,
                initials TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('direct', 'group')),
                status TEXT NOT NULL,
                accent TEXT NOT NULL DEFAULT 'cyan',
                unread_count INTEGER NOT NULL DEFAULT 0 CHECK (unread_count >= 0),
                last_message_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                event_id TEXT,
                author_pubkey TEXT,
                author_name TEXT NOT NULL DEFAULT '',
                attachment_path TEXT NOT NULL DEFAULT '',
                attachment_mime TEXT NOT NULL DEFAULT '',
                hidden_local INTEGER NOT NULL DEFAULT 0 CHECK (hidden_local IN (0, 1)),
                direction TEXT NOT NULL CHECK (direction IN ('incoming', 'outgoing', 'system')),
                content TEXT NOT NULL,
                sent_at INTEGER NOT NULL,
                delivery_state TEXT NOT NULL DEFAULT 'local',
                protocol TEXT NOT NULL DEFAULT 'NIP-17'
            );

            CREATE INDEX IF NOT EXISTS messages_conversation_time
                ON messages(conversation_id, sent_at, id);
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
                recipient_pubkey TEXT NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'text',
                attachment_path TEXT,
                recipients_json TEXT,
                group_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued'
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                pubkey_hex TEXT NOT NULL UNIQUE,
                npub TEXT NOT NULL UNIQUE,
                encrypted_secret TEXT NOT NULL,
                avatar_png BLOB,
                created_at INTEGER NOT NULL,
                last_used_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS moderation_blocks (
                target_type TEXT NOT NULL CHECK (target_type IN ('user', 'post')),
                target TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                synced_at INTEGER NOT NULL,
                PRIMARY KEY(target_type, target)
            );

            CREATE TABLE IF NOT EXISTS posts (
                event_id TEXT PRIMARY KEY,
                author_pubkey TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                reply_to TEXT
            );
            CREATE TABLE IF NOT EXISTS profiles (
                pubkey TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                picture TEXT NOT NULL DEFAULT '',
                about TEXT NOT NULL DEFAULT '',
                nip05 TEXT NOT NULL DEFAULT '',
                picture_blob BLOB,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contacts (
                pubkey TEXT PRIMARY KEY,
                nickname TEXT NOT NULL DEFAULT '',
                added_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_user_blocks (
                pubkey TEXT PRIMARY KEY,
                blocked_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_hidden_conversations (
                conversation_id TEXT PRIMARY KEY
                    REFERENCES conversations(id) ON DELETE CASCADE,
                hidden_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reactions (
                event_id TEXT PRIMARY KEY,
                target_event_id TEXT NOT NULL,
                author_pubkey TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS follows (
                pubkey TEXT PRIMARY KEY,
                followed_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_members (
                group_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                pubkey TEXT NOT NULL,
                PRIMARY KEY(group_id, pubkey)
            );
            """
        )
        identity_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(identities)").fetchall()
        }
        if "username" not in identity_columns:
            self.connection.execute(
                "ALTER TABLE identities ADD COLUMN username TEXT NOT NULL DEFAULT ''"
            )
        if "avatar_png" not in identity_columns:
            self.connection.execute("ALTER TABLE identities ADD COLUMN avatar_png BLOB")
        conversation_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "peer_pubkey" not in conversation_columns:
            self.connection.execute("ALTER TABLE conversations ADD COLUMN peer_pubkey TEXT")
        if "creator_pubkey" not in conversation_columns:
            self.connection.execute(
                "ALTER TABLE conversations ADD COLUMN creator_pubkey TEXT NOT NULL DEFAULT ''"
            )
        message_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "event_id" not in message_columns:
            self.connection.execute("ALTER TABLE messages ADD COLUMN event_id TEXT")
        if "author_pubkey" not in message_columns:
            self.connection.execute("ALTER TABLE messages ADD COLUMN author_pubkey TEXT")
        if "author_name" not in message_columns:
            self.connection.execute(
                "ALTER TABLE messages ADD COLUMN author_name TEXT NOT NULL DEFAULT ''"
            )
        if "attachment_path" not in message_columns:
            self.connection.execute(
                "ALTER TABLE messages ADD COLUMN attachment_path TEXT NOT NULL DEFAULT ''"
            )
        if "attachment_mime" not in message_columns:
            self.connection.execute(
                "ALTER TABLE messages ADD COLUMN attachment_mime TEXT NOT NULL DEFAULT ''"
            )
        if "hidden_local" not in message_columns:
            self.connection.execute(
                "ALTER TABLE messages ADD COLUMN hidden_local INTEGER NOT NULL DEFAULT 0"
            )
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS messages_event_id
               ON messages(event_id) WHERE event_id IS NOT NULL"""
        )
        outbox_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(outbox)").fetchall()
        }
        if "message_type" not in outbox_columns:
            self.connection.execute(
                "ALTER TABLE outbox ADD COLUMN message_type TEXT NOT NULL DEFAULT 'text'"
            )
        if "attachment_path" not in outbox_columns:
            self.connection.execute("ALTER TABLE outbox ADD COLUMN attachment_path TEXT")
        if "recipients_json" not in outbox_columns:
            self.connection.execute("ALTER TABLE outbox ADD COLUMN recipients_json TEXT")
        if "group_id" not in outbox_columns:
            self.connection.execute("ALTER TABLE outbox ADD COLUMN group_id TEXT")
        profile_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(profiles)").fetchall()
        }
        if "about" not in profile_columns:
            self.connection.execute(
                "ALTER TABLE profiles ADD COLUMN about TEXT NOT NULL DEFAULT ''"
            )
        if "nip05" not in profile_columns:
            self.connection.execute(
                "ALTER TABLE profiles ADD COLUMN nip05 TEXT NOT NULL DEFAULT ''"
            )
        if "picture_blob" not in profile_columns:
            self.connection.execute("ALTER TABLE profiles ADD COLUMN picture_blob BLOB")
        contact_sync_applied = self.connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 7"
        ).fetchone() is not None
        if not contact_sync_applied:
            # A direct-message peer is part of the user's contact roster as soon
            # as a conversation exists. Backfill peers created by older builds,
            # which only showed manually-added keys on the Contacts page.
            self.connection.execute(
                """INSERT OR IGNORE INTO contacts(pubkey, nickname, added_at)
                   SELECT peer_pubkey, '', last_message_at
                   FROM conversations
                   WHERE kind = 'direct' AND peer_pubkey IS NOT NULL
                         AND peer_pubkey != ''"""
            )
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (7, ?)",
                (int(time.time()),),
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (8, ?)",
            (int(time.time()),),
        )
        placeholder_cleanup_applied = self.connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 9"
        ).fetchone() is not None
        if not placeholder_cleanup_applied:
            # Releases before Open Beta v0.3.2 could explicitly seed six fixed
            # placeholder conversations. Their IDs cannot be real Nostr public
            # keys or fsociety group IDs, so remove them during the upgrade.
            self.connection.execute(
                "DELETE FROM conversations WHERE id IN "
                "('zero', 'cipher', 'ops', 'elliot', 'mesh', 'saved')"
            )
            self.connection.execute(
                """DELETE FROM contacts
                   WHERE pubkey IN (?, ?, ?)
                   AND NOT EXISTS (
                       SELECT 1 FROM conversations c
                       WHERE c.peer_pubkey = contacts.pubkey
                   )""",
                ("01" * 32, "02" * 32, "03" * 32),
            )
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (9, ?)",
                (int(time.time()),),
            )
        self.connection.execute(
            "UPDATE settings SET value = 'wss://relay.damus.io' "
            "WHERE key = 'network.relay' AND value = 'wss://relay.example'"
        )
        self.connection.execute(
            "UPDATE settings SET value = 'https://blossom.nostr.build' "
            "WHERE key = 'network.blossom' AND value = 'https://blossom.example'"
        )
        self.connection.execute(
            "UPDATE outbox SET status = 'queued' WHERE status = 'sending'"
        )
        self._hide_legacy_sender_attachment_duplicates()
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (10, ?)",
            (int(time.time()),),
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (11, ?)",
            (int(time.time()),),
        )
        self.connection.commit()

    def _hide_legacy_sender_attachment_duplicates(self) -> None:
        """Repair attachment self-copies stored by builds before schema v11."""
        local_rows = self.connection.execute(
            """SELECT m.id, m.conversation_id, m.sent_at, m.attachment_path
               FROM messages m JOIN outbox o ON o.message_id = m.id
               WHERE o.message_type IN ('attachment', 'group_attachment')
                 AND m.attachment_path <> ''"""
        ).fetchall()
        for local in local_rows:
            local_name = Path(str(local["attachment_path"])).name
            candidates = self.connection.execute(
                """SELECT m.id, m.attachment_path FROM messages m
                   WHERE m.conversation_id = ? AND m.id != ?
                     AND m.direction = 'outgoing' AND m.hidden_local = 0
                     AND m.attachment_path <> '' AND ABS(m.sent_at - ?) <= 30
                     AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.message_id = m.id)""",
                (local["conversation_id"], local["id"], local["sent_at"]),
            ).fetchall()
            for candidate in candidates:
                recovered_name = Path(str(candidate["attachment_path"])).name
                if recovered_name == local_name or recovered_name.endswith(f"-{local_name}"):
                    self.connection.execute(
                        "UPDATE messages SET hidden_local = 1 WHERE id = ?",
                        (candidate["id"],),
                    )

    def list_conversations(self, *, query: str = "", mode: str = "all") -> list[Conversation]:
        clauses: list[str] = [
            "NOT EXISTS (SELECT 1 FROM moderation_blocks mb "
            "WHERE mb.target_type = 'user' AND mb.target = c.peer_pubkey)",
            "NOT EXISTS (SELECT 1 FROM local_hidden_conversations hc "
            "WHERE hc.conversation_id = c.id)",
        ]
        if mode != "contacts":
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM local_user_blocks lb "
                "WHERE lb.pubkey = c.peer_pubkey)"
            )
        values: list[object] = []
        if query:
            clauses.append("(c.display_name LIKE ? OR EXISTS (SELECT 1 FROM messages sm WHERE sm.conversation_id = c.id AND sm.hidden_local = 0 AND sm.content LIKE ?))")
            wildcard = f"%{query}%"
            values.extend((wildcard, wildcard))
        if mode == "unread":
            clauses.append("c.unread_count > 0")
        elif mode == "groups":
            clauses.append("c.kind = 'group'")
        elif mode == "contacts":
            clauses.append(
                "c.kind = 'direct' AND c.id != 'saved' "
                "AND EXISTS (SELECT 1 FROM contacts ct2 WHERE ct2.pubkey = c.peer_pubkey)"
            )
        elif mode == "saved":
            clauses.append("c.id = 'saved'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"""
            SELECT c.*,
                COALESCE(NULLIF(ct.nickname, ''), NULLIF(pr.display_name, ''),
                         NULLIF(pr.name, ''), c.display_name) AS resolved_name,
                pr.picture_blob AS profile_picture_png,
                COALESCE((SELECT CASE
                            WHEN m.attachment_path <> '' THEN
                                COALESCE(NULLIF(m.author_name, ''),
                                    CASE WHEN m.direction = 'outgoing' THEN 'You' ELSE 'User' END)
                                || ' shared ' ||
                                CASE
                                    WHEN m.attachment_mime LIKE 'image/%' THEN 'an image'
                                    WHEN m.attachment_mime LIKE 'video/%' THEN 'a video'
                                    WHEN m.attachment_mime LIKE 'audio/%' THEN 'audio'
                                    ELSE 'a file'
                                END
                            ELSE m.content
                          END FROM messages m
                          WHERE m.conversation_id = c.id AND m.hidden_local = 0
                            AND NOT EXISTS (
                                SELECT 1 FROM local_user_blocks lb
                                WHERE lb.pubkey = CASE
                                    WHEN c.kind = 'direct' THEN c.peer_pubkey
                                    ELSE m.author_pubkey
                                END
                            )
                          ORDER BY m.sent_at DESC, m.id DESC LIMIT 1), '') AS last_message
            FROM conversations c
            LEFT JOIN contacts ct ON ct.pubkey = c.peer_pubkey
            LEFT JOIN profiles pr ON pr.pubkey = c.peer_pubkey
            {where}
            ORDER BY c.last_message_at DESC
            """,
            values,
        ).fetchall()
        conversations = []
        for row in rows:
            values = dict(row)
            values["display_name"] = values.pop("resolved_name")
            conversations.append(Conversation(**values))
        if mode == "contacts":
            # Nostr display names are neither unique nor authoritative. If two
            # public keys choose the same name, expose a short fingerprint so
            # the UI never makes one identity appear to be a duplicate row.
            name_counts: dict[str, int] = {}
            for conversation in conversations:
                key = conversation.display_name.strip().casefold()
                name_counts[key] = name_counts.get(key, 0) + 1
            conversations = [
                Conversation(
                    **{
                        **{
                            field: getattr(conversation, field)
                            for field in conversation.__dataclass_fields__
                        },
                        "display_name": (
                            (
                                f"{conversation.display_name} - {conversation.peer_pubkey[:8]}"
                                if conversation.peer_pubkey
                                and name_counts.get(
                                    conversation.display_name.strip().casefold(), 0
                                ) > 1
                                else conversation.display_name
                            )
                            + (
                                " [BLOCKED]"
                                if conversation.peer_pubkey
                                and self.is_user_blocked(conversation.peer_pubkey)
                                else ""
                            )
                        ),
                    }
                )
                for conversation in conversations
            ]
        return conversations

    def list_messages(self, conversation_id: str) -> list[Message]:
        rows = self.connection.execute(
            """SELECT m.id, m.conversation_id, m.direction, m.content, m.sent_at,
                      m.delivery_state, m.protocol, m.author_pubkey,
                      COALESCE(NULLIF(m.author_name, ''), NULLIF(p.display_name, ''),
                               NULLIF(p.name, ''), '') AS author_name,
                      m.attachment_path, m.attachment_mime
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN profiles p ON p.pubkey = m.author_pubkey
               WHERE m.conversation_id = ? AND m.hidden_local = 0
               AND NOT EXISTS (SELECT 1 FROM moderation_blocks mb
                   WHERE (mb.target_type = 'post' AND mb.target = m.event_id)
                      OR (mb.target_type = 'user' AND mb.target = m.author_pubkey))
               AND NOT EXISTS (SELECT 1 FROM local_user_blocks lb
                   WHERE lb.pubkey = CASE
                       WHEN c.kind = 'direct' THEN c.peer_pubkey
                       ELSE m.author_pubkey
                   END)
               ORDER BY m.sent_at, m.id""",
            (conversation_id,),
        ).fetchall()
        return [Message(**dict(row)) for row in rows]

    def list_recent_messages(self, conversation_id: str, limit: int = 100) -> list[Message]:
        """Return the newest visible messages in chronological display order."""
        rows = self.connection.execute(
            """SELECT m.id, m.conversation_id, m.direction, m.content, m.sent_at,
                      m.delivery_state, m.protocol, m.author_pubkey,
                      COALESCE(NULLIF(m.author_name, ''), NULLIF(p.display_name, ''),
                               NULLIF(p.name, ''), '') AS author_name,
                      m.attachment_path, m.attachment_mime
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN profiles p ON p.pubkey = m.author_pubkey
               WHERE m.conversation_id = ? AND m.hidden_local = 0
               AND NOT EXISTS (SELECT 1 FROM moderation_blocks mb
                   WHERE (mb.target_type = 'post' AND mb.target = m.event_id)
                      OR (mb.target_type = 'user' AND mb.target = m.author_pubkey))
               AND NOT EXISTS (SELECT 1 FROM local_user_blocks lb
                   WHERE lb.pubkey = CASE
                       WHEN c.kind = 'direct' THEN c.peer_pubkey
                       ELSE m.author_pubkey
                   END)
               ORDER BY m.sent_at DESC, m.id DESC
               LIMIT ?""",
            (conversation_id, max(1, int(limit))),
        ).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def list_messages_before(
        self,
        conversation_id: str,
        before_sent_at: int,
        before_id: int,
        limit: int = 50,
    ) -> list[Message]:
        """Page backward without OFFSET so large histories remain fast."""
        rows = self.connection.execute(
            """SELECT m.id, m.conversation_id, m.direction, m.content, m.sent_at,
                      m.delivery_state, m.protocol, m.author_pubkey,
                      COALESCE(NULLIF(m.author_name, ''), NULLIF(p.display_name, ''),
                               NULLIF(p.name, ''), '') AS author_name,
                      m.attachment_path, m.attachment_mime
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN profiles p ON p.pubkey = m.author_pubkey
               WHERE m.conversation_id = ? AND m.hidden_local = 0
               AND (m.sent_at < ? OR (m.sent_at = ? AND m.id < ?))
               AND NOT EXISTS (SELECT 1 FROM moderation_blocks mb
                   WHERE (mb.target_type = 'post' AND mb.target = m.event_id)
                      OR (mb.target_type = 'user' AND mb.target = m.author_pubkey))
               AND NOT EXISTS (SELECT 1 FROM local_user_blocks lb
                   WHERE lb.pubkey = CASE
                       WHEN c.kind = 'direct' THEN c.peer_pubkey
                       ELSE m.author_pubkey
                   END)
               ORDER BY m.sent_at DESC, m.id DESC
               LIMIT ?""",
            (
                conversation_id,
                int(before_sent_at),
                int(before_sent_at),
                int(before_id),
                max(1, int(limit)),
            ),
        ).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def list_messages_after(
        self,
        conversation_id: str,
        after_sent_at: int,
        after_id: int,
        limit: int = 251,
    ) -> list[Message]:
        """Return visible messages newer than a rendered keyset cursor."""
        rows = self.connection.execute(
            """SELECT m.id, m.conversation_id, m.direction, m.content, m.sent_at,
                      m.delivery_state, m.protocol, m.author_pubkey,
                      COALESCE(NULLIF(m.author_name, ''), NULLIF(p.display_name, ''),
                               NULLIF(p.name, ''), '') AS author_name,
                      m.attachment_path, m.attachment_mime
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN profiles p ON p.pubkey = m.author_pubkey
               WHERE m.conversation_id = ? AND m.hidden_local = 0
               AND (m.sent_at > ? OR (m.sent_at = ? AND m.id > ?))
               AND NOT EXISTS (SELECT 1 FROM moderation_blocks mb
                   WHERE (mb.target_type = 'post' AND mb.target = m.event_id)
                      OR (mb.target_type = 'user' AND mb.target = m.author_pubkey))
               AND NOT EXISTS (SELECT 1 FROM local_user_blocks lb
                   WHERE lb.pubkey = CASE
                       WHEN c.kind = 'direct' THEN c.peer_pubkey
                       ELSE m.author_pubkey
                   END)
               ORDER BY m.sent_at, m.id
               LIMIT ?""",
            (
                conversation_id,
                int(after_sent_at),
                int(after_sent_at),
                int(after_id),
                max(1, int(limit)),
            ),
        ).fetchall()
        return [Message(**dict(row)) for row in rows]

    def search_messages(
        self, conversation_id: str, query: str, limit: int = 250
    ) -> list[Message]:
        """Search the complete SQLite history while bounding rendered results."""
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if not escaped:
            return []
        rows = self.connection.execute(
            """SELECT m.id, m.conversation_id, m.direction, m.content, m.sent_at,
                      m.delivery_state, m.protocol, m.author_pubkey,
                      COALESCE(NULLIF(m.author_name, ''), NULLIF(p.display_name, ''),
                               NULLIF(p.name, ''), '') AS author_name,
                      m.attachment_path, m.attachment_mime
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               LEFT JOIN profiles p ON p.pubkey = m.author_pubkey
               WHERE m.conversation_id = ? AND m.hidden_local = 0
                 AND m.content LIKE ? ESCAPE '\\' COLLATE NOCASE
               AND NOT EXISTS (SELECT 1 FROM moderation_blocks mb
                   WHERE (mb.target_type = 'post' AND mb.target = m.event_id)
                      OR (mb.target_type = 'user' AND mb.target = m.author_pubkey))
               AND NOT EXISTS (SELECT 1 FROM local_user_blocks lb
                   WHERE lb.pubkey = CASE
                       WHEN c.kind = 'direct' THEN c.peer_pubkey
                       ELSE m.author_pubkey
                   END)
               ORDER BY m.sent_at DESC, m.id DESC
               LIMIT ?""",
            (conversation_id, f"%{escaped}%", max(1, int(limit))),
        ).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def hide_message_locally(self, message_id: int) -> bool:
        """Keep a relay event tombstoned locally and cancel any pending send."""
        row = self.connection.execute(
            "SELECT conversation_id FROM messages WHERE id = ? AND hidden_local = 0",
            (message_id,),
        ).fetchone()
        if row is None:
            return False
        conversation_id = str(row["conversation_id"])
        with self.connection:
            self.connection.execute("DELETE FROM outbox WHERE message_id = ?", (message_id,))
            self.connection.execute(
                "UPDATE messages SET hidden_local = 1 WHERE id = ?", (message_id,)
            )
            newest = self.connection.execute(
                """SELECT MAX(sent_at) FROM messages
                   WHERE conversation_id = ? AND hidden_local = 0""",
                (conversation_id,),
            ).fetchone()[0]
            if newest is not None:
                self.connection.execute(
                    "UPDATE conversations SET last_message_at = ? WHERE id = ?",
                    (int(newest), conversation_id),
                )
        return True

    def add_outgoing_message(
        self, conversation_id: str, content: str, *, protocol: str = "NIP-17"
    ) -> Message:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("message content cannot be empty")
        sent_at = int(time.time())
        cursor = self.connection.execute(
            """INSERT INTO messages
               (conversation_id, direction, content, sent_at, delivery_state, protocol)
               VALUES (?, 'outgoing', ?, ?, 'local', ?)""",
            (conversation_id, clean_content, sent_at, protocol),
        )
        self.connection.execute(
            "UPDATE conversations SET last_message_at = ? WHERE id = ?",
            (sent_at, conversation_id),
        )
        self.connection.commit()
        return Message(cursor.lastrowid, conversation_id, "outgoing", clean_content, sent_at, "local", protocol)

    def ensure_direct_conversation(
        self, peer_pubkey: str, display_name: str = "", *, reveal: bool = True
    ) -> str:
        existing = self.connection.execute(
            "SELECT id FROM conversations WHERE peer_pubkey = ? AND kind = 'direct' LIMIT 1",
            (peer_pubkey,),
        ).fetchone()
        if existing is not None:
            conversation_id = str(existing["id"])
            if reveal:
                self.connection.execute(
                    "DELETE FROM local_hidden_conversations WHERE conversation_id = ?",
                    (conversation_id,),
                )
                self.connection.commit()
            return conversation_id
        clean_name = display_name.strip() or f"npub:{peer_pubkey[:16]}…"
        now = int(time.time())
        initials = clean_name[:2].upper()
        self.connection.execute(
            """INSERT INTO conversations
               (id, peer_pubkey, display_name, initials, kind, status, accent,
                unread_count, last_message_at)
               VALUES (?, ?, ?, ?, 'direct', 'Nostr direct message', 'cyan', 0, ?)
               ON CONFLICT(id) DO UPDATE SET
                   peer_pubkey = excluded.peer_pubkey,
                   display_name = CASE
                       WHEN conversations.display_name LIKE 'npub:%' THEN excluded.display_name
                       ELSE conversations.display_name END""",
            (peer_pubkey, peer_pubkey, clean_name, initials, now),
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO contacts(pubkey, nickname, added_at) VALUES (?, '', ?)",
            (peer_pubkey, now),
        )
        self.connection.commit()
        return peer_pubkey

    def hide_direct_conversation_locally(self, conversation_id: str) -> bool:
        """Hide a direct chat and its history while retaining relay tombstones."""
        row = self.connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND kind = 'direct'",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return False
        hidden_at = int(time.time())
        with self.connection:
            self.connection.execute(
                "DELETE FROM outbox WHERE message_id IN "
                "(SELECT id FROM messages WHERE conversation_id = ?)",
                (conversation_id,),
            )
            self.connection.execute(
                "UPDATE messages SET hidden_local = 1 WHERE conversation_id = ?",
                (conversation_id,),
            )
            self.connection.execute(
                """INSERT INTO local_hidden_conversations(conversation_id, hidden_at)
                   VALUES (?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET hidden_at = excluded.hidden_at""",
                (conversation_id, hidden_at),
            )
            self.connection.execute(
                "UPDATE conversations SET unread_count = 0 WHERE id = ?",
                (conversation_id,),
            )
        return True

    def add_contact(self, pubkey: str, nickname: str = "") -> str:
        conversation_id = self.ensure_direct_conversation(pubkey)
        with self.connection:
            # Explicitly re-adding an npub is also an explicit decision to
            # resume contact with that identity.
            self.connection.execute(
                "DELETE FROM local_user_blocks WHERE pubkey = ?", (pubkey,)
            )
            self.connection.execute(
                """INSERT INTO contacts(pubkey, nickname, added_at) VALUES (?, ?, ?)
                   ON CONFLICT(pubkey) DO UPDATE SET nickname = excluded.nickname""",
                (pubkey, nickname.strip(), int(time.time())),
            )
        return conversation_id

    def remove_contact(self, pubkey: str) -> None:
        self.connection.execute("DELETE FROM contacts WHERE pubkey = ?", (pubkey,))
        self.connection.commit()

    def is_contact(self, pubkey: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM contacts WHERE pubkey = ?", (pubkey,)
        ).fetchone() is not None

    def set_user_blocked(self, pubkey: str, blocked: bool) -> None:
        if blocked:
            self.connection.execute(
                "INSERT OR REPLACE INTO local_user_blocks(pubkey, blocked_at) VALUES (?, ?)",
                (pubkey, int(time.time())),
            )
        else:
            self.connection.execute(
                "DELETE FROM local_user_blocks WHERE pubkey = ?", (pubkey,)
            )
        self.connection.commit()

    def is_user_blocked(self, pubkey: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM local_user_blocks WHERE pubkey = ?", (pubkey,)
        ).fetchone() is not None

    def set_contact_nickname(self, pubkey: str, nickname: str) -> None:
        self.connection.execute(
            "UPDATE contacts SET nickname = ? WHERE pubkey = ?",
            (nickname.strip(), pubkey),
        )
        self.connection.commit()

    def profile_targets(self) -> list[str]:
        rows = self.connection.execute(
            """SELECT pubkey FROM contacts
               UNION SELECT pubkey FROM group_members
               UNION SELECT peer_pubkey FROM conversations
                     WHERE peer_pubkey IS NOT NULL AND id != 'saved'"""
        ).fetchall()
        return [str(row[0]) for row in rows if row[0]]

    def queue_direct_message(self, peer_pubkey: str, content: str) -> Message:
        conversation_id = self.ensure_direct_conversation(peer_pubkey)
        message = self.add_outgoing_message(conversation_id, content)
        self.connection.execute(
            """INSERT INTO outbox(message_id, recipient_pubkey, content)
               VALUES (?, ?, ?)""",
            (message.id, peer_pubkey, message.content),
        )
        self.connection.commit()
        return message

    def pending_outbox(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """SELECT id, message_id, recipient_pubkey, content, attempts,
                      message_type, attachment_path, recipients_json, group_id
               FROM outbox WHERE status IN ('queued', 'failed') ORDER BY id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def queue_attachment(self, peer_pubkey: str, path: str, display_text: str) -> Message:
        conversation_id = self.ensure_direct_conversation(peer_pubkey)
        message = self.add_outgoing_message(
            conversation_id, display_text, protocol="BLOSSOM+NIP-17"
        )
        mime_type = guess_attachment_mime(path)
        self.connection.execute(
            "UPDATE messages SET attachment_path = ?, attachment_mime = ? WHERE id = ?",
            (path, mime_type, message.id),
        )
        self.connection.execute(
            """INSERT INTO outbox
               (message_id, recipient_pubkey, content, message_type, attachment_path)
               VALUES (?, ?, ?, 'attachment', ?)""",
            (message.id, peer_pubkey, display_text, path),
        )
        self.connection.commit()
        return message

    def create_group(
        self,
        group_id: str,
        name: str,
        members: list[str],
        creator_pubkey: str = "",
    ) -> str:
        now = int(time.time())
        clean_name = name.strip() or "Encrypted group"
        self.connection.execute(
            """INSERT INTO conversations
               (id, creator_pubkey, display_name, initials, kind, status, accent,
                unread_count, last_message_at)
               VALUES (?, ?, ?, ?, 'group', ?, 'violet', 0, ?)
               ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name,
                   status = excluded.status,
                   creator_pubkey = CASE WHEN conversations.creator_pubkey = ''
                       THEN excluded.creator_pubkey ELSE conversations.creator_pubkey END""",
            (
                group_id,
                creator_pubkey,
                clean_name,
                clean_name[:2].upper(),
                f"{len(members)} members · NIP-17 encrypted",
                now,
            ),
        )
        self.connection.executemany(
            "INSERT OR IGNORE INTO group_members(group_id, pubkey) VALUES (?, ?)",
            ((group_id, member) for member in members),
        )
        self.connection.commit()
        return group_id

    def group_creator(self, group_id: str) -> str:
        row = self.connection.execute(
            "SELECT creator_pubkey FROM conversations WHERE id = ? AND kind = 'group'",
            (group_id,),
        ).fetchone()
        return str(row["creator_pubkey"]) if row is not None else ""

    def remove_group_member(self, group_id: str, pubkey: str) -> None:
        self.connection.execute(
            "DELETE FROM group_members WHERE group_id = ? AND pubkey = ?",
            (group_id, pubkey),
        )
        count = self.connection.execute(
            "SELECT COUNT(*) FROM group_members WHERE group_id = ?", (group_id,)
        ).fetchone()[0]
        self.connection.execute(
            "UPDATE conversations SET status = ? WHERE id = ?",
            (f"{count} members · NIP-17 encrypted", group_id),
        )
        self.connection.commit()

    def delete_group(self, group_id: str) -> None:
        self.connection.execute(
            "DELETE FROM conversations WHERE id = ? AND kind = 'group'", (group_id,)
        )
        self.connection.commit()

    def add_group_member(self, group_id: str, pubkey: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO group_members(group_id, pubkey) VALUES (?, ?)",
            (group_id, pubkey),
        )
        count = self.connection.execute(
            "SELECT COUNT(*) FROM group_members WHERE group_id = ?", (group_id,)
        ).fetchone()[0]
        self.connection.execute(
            "UPDATE conversations SET status = ? WHERE id = ?",
            (f"{count} members · NIP-17 encrypted", group_id),
        )
        self.connection.commit()

    def group_members(self, group_id: str) -> list[str]:
        return [
            row[0]
            for row in self.connection.execute(
                "SELECT pubkey FROM group_members WHERE group_id = ? ORDER BY pubkey",
                (group_id,),
            )
        ]

    def queue_group_message(
        self,
        group_id: str,
        content: str,
        members: list[str],
        sender_pubkey: str = "",
        sender_name: str = "",
    ) -> Message:
        message = self.add_outgoing_message(group_id, content)
        self.connection.execute(
            "UPDATE messages SET author_pubkey = ?, author_name = ? WHERE id = ?",
            (sender_pubkey or None, sender_name.strip(), message.id),
        )
        self.connection.execute(
            """INSERT INTO outbox
               (message_id, recipient_pubkey, content, message_type, recipients_json, group_id)
               VALUES (?, '', ?, 'group', ?, ?)""",
            (message.id, message.content, json.dumps(members), group_id),
        )
        self.connection.commit()
        return message

    def queue_group_attachment(
        self,
        group_id: str,
        path: str,
        display_text: str,
        members: list[str],
        sender_pubkey: str,
        sender_name: str,
    ) -> Message:
        message = self.add_outgoing_message(
            group_id, display_text, protocol="BLOSSOM+NIP-17 GROUP"
        )
        mime_type = guess_attachment_mime(path)
        self.connection.execute(
            """UPDATE messages SET author_pubkey = ?, author_name = ?,
                      attachment_path = ?, attachment_mime = ? WHERE id = ?""",
            (sender_pubkey, sender_name.strip(), path, mime_type, message.id),
        )
        self.connection.execute(
            """INSERT INTO outbox
               (message_id, recipient_pubkey, content, message_type, attachment_path,
                recipients_json, group_id)
               VALUES (?, '', ?, 'group_attachment', ?, ?, ?)""",
            (message.id, display_text, path, json.dumps(members), group_id),
        )
        self.connection.commit()
        return message

    def add_group_message(
        self,
        group_id: str,
        name: str,
        members: list[str],
        sender: str,
        content: str,
        event_id: str,
        sent_at: int,
        sender_name: str = "",
        attachment_path: str = "",
        attachment_mime: str = "",
        system: bool = False,
        recovered_outgoing: bool = False,
    ) -> bool:
        if not recovered_outgoing and self.is_user_blocked(sender):
            return False
        existing_group = self.connection.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (group_id,)
        ).fetchone()
        self.create_group(
            group_id,
            name,
            list(dict.fromkeys([sender, *members])),
            creator_pubkey=sender if existing_group is None else "",
        )
        direction = "system" if system else ("outgoing" if recovered_outgoing else "incoming")
        delivery_state = "relay-accepted" if recovered_outgoing else "received"
        unread_increment = 0 if recovered_outgoing else 1
        if recovered_outgoing:
            if self._has_local_recovery_copy(
                group_id, content, sent_at, attachment_path, attachment_mime
            ):
                return False
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO messages
                       (conversation_id, event_id, author_pubkey, author_name,
                        attachment_path, attachment_mime, direction, content,
                       sent_at, delivery_state, protocol)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NIP-17 GROUP')""",
                    (
                        group_id,
                        event_id,
                        sender,
                        sender_name.strip(),
                        attachment_path,
                        attachment_mime,
                        direction,
                        content,
                        sent_at,
                        delivery_state,
                    ),
                )
                self.connection.execute(
                    """UPDATE conversations
                       SET last_message_at = MAX(last_message_at, ?),
                           unread_count = unread_count + ?
                       WHERE id = ?""",
                    (sent_at, unread_increment, group_id),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def queue_group_system_message(
        self,
        group_id: str,
        display_text: str,
        transport_content: str,
        members: list[str],
        sender_pubkey: str,
        sender_name: str,
    ) -> Message:
        message = self.add_outgoing_message(group_id, display_text, protocol="NIP-17 GROUP CONTROL")
        with self.connection:
            self.connection.execute(
                """UPDATE messages SET direction = 'system', author_pubkey = ?, author_name = ?
                   WHERE id = ?""",
                (sender_pubkey, sender_name.strip(), message.id),
            )
            self.connection.execute(
                """INSERT INTO outbox
                   (message_id, recipient_pubkey, content, message_type, recipients_json, group_id)
                   VALUES (?, '', ?, 'group', ?, ?)""",
                (message.id, transport_content, json.dumps(members), group_id),
            )
        return message

    def mark_message_sending(self, message_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE messages SET delivery_state = 'sending' WHERE id = ?", (message_id,)
            )
            self.connection.execute(
                "UPDATE outbox SET status = 'sending' WHERE message_id = ?", (message_id,)
            )

    def mark_message_published(self, message_id: int, event_id: str) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE messages SET delivery_state = 'relay-accepted', event_id = ?
                   WHERE id = ?""",
                (event_id, message_id),
            )
            self.connection.execute(
                "UPDATE outbox SET status = 'published', last_error = '' WHERE message_id = ?",
                (message_id,),
            )

    def mark_message_failed(self, message_id: int, error: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE messages SET delivery_state = 'failed' WHERE id = ?", (message_id,)
            )
            self.connection.execute(
                """UPDATE outbox SET status = 'failed', attempts = attempts + 1,
                   last_error = ? WHERE message_id = ?""",
                (error, message_id),
            )

    def conversation_id_for_message(self, message_id: int) -> str | None:
        row = self.connection.execute(
            "SELECT conversation_id FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return str(row["conversation_id"]) if row is not None else None

    def add_incoming_message(
        self,
        sender_pubkey: str,
        content: str,
        event_id: str,
        sent_at: int,
        attachment_path: str = "",
        attachment_mime: str = "",
    ) -> bool:
        if self.is_user_blocked(sender_pubkey):
            return False
        conversation_id = self.ensure_direct_conversation(sender_pubkey, reveal=False)
        hidden = self.connection.execute(
            "SELECT hidden_at FROM local_hidden_conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        keep_hidden = hidden is not None and sent_at <= int(hidden["hidden_at"])
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO messages
                       (conversation_id, event_id, author_pubkey, attachment_path,
                        attachment_mime, hidden_local, direction, content, sent_at,
                        delivery_state, protocol)
                       VALUES (?, ?, ?, ?, ?, ?, 'incoming', ?, ?, 'received', 'NIP-17')""",
                    (
                        conversation_id,
                        event_id,
                        sender_pubkey,
                        attachment_path,
                        attachment_mime,
                        1 if keep_hidden else 0,
                        content,
                        sent_at,
                    ),
                )
                self.connection.execute(
                    """UPDATE conversations SET last_message_at = MAX(last_message_at, ?),
                       unread_count = unread_count + ? WHERE id = ?""",
                    (sent_at, 0 if keep_hidden else 1, conversation_id),
                )
                if hidden is not None and not keep_hidden:
                    self.connection.execute(
                        "DELETE FROM local_hidden_conversations WHERE conversation_id = ?",
                        (conversation_id,),
                    )
        except sqlite3.IntegrityError:
            return False
        return True

    def add_recovered_outgoing_message(
        self,
        peer_pubkey: str,
        sender_pubkey: str,
        content: str,
        event_id: str,
        sent_at: int,
        attachment_path: str = "",
        attachment_mime: str = "",
    ) -> bool:
        """Restore a sender inbox copy without duplicating a live local send."""
        conversation_id = self.ensure_direct_conversation(peer_pubkey, reveal=False)
        if self._has_local_recovery_copy(
            conversation_id, content, sent_at, attachment_path, attachment_mime
        ):
            return False
        protocol = "BLOSSOM+NIP-17" if attachment_path else "NIP-17"
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO messages
                       (conversation_id, event_id, author_pubkey, attachment_path,
                        attachment_mime, direction, content, sent_at,
                        delivery_state, protocol)
                       VALUES (?, ?, ?, ?, ?, 'outgoing', ?, ?,
                               'relay-accepted', ?)""",
                    (
                        conversation_id,
                        event_id,
                        sender_pubkey,
                        attachment_path,
                        attachment_mime,
                        content,
                        sent_at,
                        protocol,
                    ),
                )
                self.connection.execute(
                    """UPDATE conversations
                       SET last_message_at = MAX(last_message_at, ?)
                       WHERE id = ?""",
                    (sent_at, conversation_id),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def _has_local_recovery_copy(
        self,
        conversation_id: str,
        content: str,
        sent_at: int,
        attachment_path: str = "",
        attachment_mime: str = "",
    ) -> bool:
        """Match a NIP-17 sender copy to the local message that produced it."""
        rows = self.connection.execute(
            """SELECT m.content, m.attachment_path, m.attachment_mime
               FROM messages m
               JOIN outbox o ON o.message_id = m.id
               WHERE m.conversation_id = ?
                 AND m.direction IN ('outgoing', 'system')
                 AND ABS(m.sent_at - ?) <= 30""",
            (conversation_id, sent_at),
        ).fetchall()
        if not attachment_path:
            return any(str(row["content"]) == content for row in rows)
        recovered_name = Path(attachment_path).name
        for row in rows:
            local_path = str(row["attachment_path"] or "")
            if not local_path:
                continue
            local_name = Path(local_path).name
            same_name = recovered_name == local_name or recovered_name.endswith(
                f"-{local_name}"
            )
            # MIME spelling is not a stable identity for archives: Windows
            # commonly reports application/x-zip-compressed while other
            # platforms use application/zip. The sender copy's cached filename
            # carries a hash prefix, so match its original basename instead.
            if same_name:
                return True
        return False

    def mark_read(self, conversation_id: str) -> None:
        self.connection.execute(
            "UPDATE conversations SET unread_count = 0 WHERE id = ?", (conversation_id,)
        )
        self.connection.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            """INSERT INTO settings(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
        self.connection.commit()

    def replace_moderation_blocks(
        self, users: list[str], posts: list[str], source_event_id: str
    ) -> None:
        now = int(time.time())
        with self.connection:
            self.connection.execute("DELETE FROM moderation_blocks")
            self.connection.executemany(
                """INSERT INTO moderation_blocks
                   (target_type, target, source_event_id, synced_at)
                   VALUES ('user', ?, ?, ?)""",
                ((target, source_event_id, now) for target in users),
            )
            self.connection.executemany(
                """INSERT INTO moderation_blocks
                   (target_type, target, source_event_id, synced_at)
                   VALUES ('post', ?, ?, ?)""",
                ((target, source_event_id, now) for target in posts),
            )
            self.connection.execute(
                """INSERT INTO settings(key, value) VALUES ('moderation.last_event_id', ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (source_event_id,),
            )

    def upsert_post(
        self,
        event_id: str,
        author_pubkey: str,
        content: str,
        created_at: int,
        reply_to: str | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO posts(event_id, author_pubkey, content, created_at, reply_to)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(event_id) DO NOTHING""",
            (event_id, author_pubkey, content, created_at, reply_to),
        )
        self.connection.commit()

    def upsert_reaction(
        self, event_id: str, target_event_id: str, author: str, content: str, created_at: int
    ) -> None:
        self.connection.execute(
            """INSERT INTO reactions
               (event_id, target_event_id, author_pubkey, content, created_at)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_id) DO NOTHING""",
            (event_id, target_event_id, author, content, created_at),
        )
        self.connection.commit()

    def list_posts(self, *, followed_only: bool = False, limit: int = 200) -> list[dict[str, object]]:
        followed = "AND EXISTS (SELECT 1 FROM follows f WHERE f.pubkey = p.author_pubkey)" if followed_only else ""
        rows = self.connection.execute(
            f"""SELECT p.*, COALESCE(NULLIF(pr.display_name, ''), NULLIF(pr.name, ''), '')
                           AS profile_name,
                       COALESCE(pr.picture, '') AS profile_picture,
                       (SELECT COUNT(*) FROM reactions r WHERE r.target_event_id = p.event_id)
                           AS reaction_count
                FROM posts p
                LEFT JOIN profiles pr ON pr.pubkey = p.author_pubkey
                WHERE NOT EXISTS (SELECT 1 FROM moderation_blocks mb
                    WHERE (mb.target_type = 'post' AND mb.target = p.event_id)
                       OR (mb.target_type = 'user' AND mb.target = p.author_pubkey))
                AND NOT EXISTS (SELECT 1 FROM local_user_blocks lb
                    WHERE lb.pubkey = p.author_pubkey)
                {followed}
                ORDER BY p.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_profile(
        self,
        pubkey: str,
        name: str,
        display_name: str,
        picture: str,
        updated_at: int,
        about: str = "",
        nip05: str = "",
        picture_blob: bytes | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO profiles
               (pubkey, name, display_name, picture, about, nip05, picture_blob, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(pubkey) DO UPDATE SET
                   name = excluded.name,
                   display_name = excluded.display_name,
                   picture = excluded.picture,
                   about = excluded.about,
                   nip05 = excluded.nip05,
                   picture_blob = COALESCE(excluded.picture_blob, profiles.picture_blob),
                   updated_at = excluded.updated_at
               WHERE excluded.updated_at >= profiles.updated_at""",
            (pubkey, name, display_name, picture, about, nip05, picture_blob, updated_at),
        )
        self.connection.execute(
            """UPDATE conversations SET display_name = ?, initials = ?
               WHERE peer_pubkey = ? AND display_name LIKE 'npub:%' AND ? != ''""",
            (display_name or name, (display_name or name)[:2].upper(), pubkey, display_name or name),
        )
        self.connection.commit()

    def get_profile(self, pubkey: str) -> dict[str, object] | None:
        row = self.connection.execute(
            """SELECT p.*, COALESCE(c.nickname, '') AS nickname
               FROM profiles p LEFT JOIN contacts c ON c.pubkey = p.pubkey
               WHERE p.pubkey = ?""",
            (pubkey,),
        ).fetchone()
        if row is not None:
            return dict(row)
        contact = self.connection.execute(
            "SELECT pubkey, nickname FROM contacts WHERE pubkey = ?", (pubkey,)
        ).fetchone()
        if contact is None:
            return None
        return {
            "pubkey": pubkey,
            "name": "",
            "display_name": "",
            "picture": "",
            "about": "",
            "nip05": "",
            "picture_blob": None,
            "updated_at": 0,
            "nickname": str(contact["nickname"]),
        }

    def set_following(self, pubkey: str, following: bool) -> None:
        if following:
            self.connection.execute(
                "INSERT OR IGNORE INTO follows(pubkey, followed_at) VALUES (?, ?)",
                (pubkey, int(time.time())),
            )
        else:
            self.connection.execute("DELETE FROM follows WHERE pubkey = ?", (pubkey,))
        self.connection.commit()

    def is_following(self, pubkey: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM follows WHERE pubkey = ?", (pubkey,)
        ).fetchone() is not None

    def followed_pubkeys(self) -> list[str]:
        return [row[0] for row in self.connection.execute("SELECT pubkey FROM follows ORDER BY pubkey")]
