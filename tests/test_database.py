from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fsociety_client.database import ClientDatabase
from fixtures import seed_conversation_fixtures


class ClientDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = ClientDatabase(Path(self.temporary_directory.name, "client.sqlite3"))
        seed_conversation_fixtures(self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def test_filters_and_search(self) -> None:
        self.assertEqual(len(self.database.list_conversations(mode="unread")), 2)
        self.assertEqual(len(self.database.list_conversations(mode="groups")), 2)
        self.assertEqual(len(self.database.list_conversations(mode="contacts")), 3)
        self.assertEqual(self.database.list_conversations(mode="saved")[0].id, "saved")
        self.assertEqual(self.database.list_conversations(query="Blossom")[0].id, "cipher")

    def test_upgrade_removes_legacy_placeholder_conversations(self) -> None:
        self.database.connection.execute(
            "DELETE FROM schema_migrations WHERE version = 9"
        )
        self.database.connection.commit()
        database_path = self.database.path
        self.database.close()
        self.database = ClientDatabase(database_path)

        ids = {item.id for item in self.database.list_conversations()}
        self.assertTrue(
            ids.isdisjoint({"zero", "cipher", "ops", "elliot", "mesh", "saved"})
        )

    def test_outgoing_message_is_persisted(self) -> None:
        created = self.database.add_outgoing_message("zero", "A new message")
        self.assertEqual(created.delivery_state, "local")
        self.assertEqual(self.database.list_messages("zero")[-1].content, "A new message")

    def test_empty_message_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.database.add_outgoing_message("zero", "   ")

    def test_settings_are_persisted(self) -> None:
        self.database.set_setting("network.relay", "wss://relay.test")
        self.assertEqual(self.database.get_setting("network.relay"), "wss://relay.test")

    def test_attachment_protocol_is_recorded(self) -> None:
        self.database.add_outgoing_message("zero", "file.txt", protocol="BLOSSOM")
        self.assertEqual(self.database.list_messages("zero")[-1].protocol, "BLOSSOM")
        self.database.queue_attachment("zero", "photo.png", "shared photo")
        attachment = self.database.list_messages("zero")[-1]
        self.assertEqual(attachment.attachment_path, "photo.png")
        self.assertEqual(attachment.attachment_mime, "image/png")
        conversation = next(item for item in self.database.list_conversations() if item.id == "zero")
        self.assertEqual(conversation.last_message, "You shared an image")

    def test_archive_attachments_use_portable_mime_types(self) -> None:
        zip_message = self.database.queue_attachment("zero", "backup.ZIP", "shared zip")
        rar_message = self.database.queue_attachment("zero", "backup.rar", "shared rar")
        messages = {message.id: message for message in self.database.list_messages("zero")}
        self.assertEqual(messages[zip_message.id].attachment_mime, "application/zip")
        self.assertEqual(messages[rar_message.id].attachment_mime, "application/vnd.rar")

    def test_message_history_uses_keyset_pages_and_bounded_search(self) -> None:
        base = 1_800_000_000
        self.database.connection.executemany(
            """INSERT INTO messages
               (conversation_id, direction, content, sent_at, delivery_state, protocol)
               VALUES ('zero', 'incoming', ?, ?, 'received', 'NIP-17')""",
            (
                (f"history {index}" + (" needle" if index % 2 == 0 else ""), base + index)
                for index in range(320)
            ),
        )
        self.database.connection.commit()
        recent = self.database.list_recent_messages("zero", 100)
        self.assertEqual(len(recent), 100)
        self.assertEqual(recent[0].content.split()[1], "220")
        self.assertEqual(recent[-1].content.split()[1], "319")
        older = self.database.list_messages_before(
            "zero", recent[0].sent_at, recent[0].id, 50
        )
        self.assertEqual(len(older), 50)
        self.assertEqual(older[0].content.split()[1], "170")
        self.assertEqual(older[-1].content.split()[1], "219")
        after = self.database.list_messages_after(
            "zero", recent[-1].sent_at, recent[-1].id
        )
        self.assertEqual(after, [])
        results = self.database.search_messages("zero", "needle", 25)
        self.assertEqual(len(results), 25)
        self.assertTrue(all("needle" in message.content for message in results))


    def test_signed_moderation_targets_are_filtered_from_local_views(self) -> None:
        user = "11" * 32
        post = "22" * 32
        self.database.connection.execute(
            "UPDATE conversations SET peer_pubkey = ? WHERE id = 'zero'", (user,)
        )
        self.database.connection.execute(
            "UPDATE messages SET event_id = ? WHERE id = "
            "(SELECT MIN(id) FROM messages WHERE conversation_id = 'zero')",
            (post,),
        )
        self.database.connection.commit()
        self.database.replace_moderation_blocks([user], [], "aa" * 32)
        self.assertNotIn("zero", [item.id for item in self.database.list_conversations()])
        self.database.replace_moderation_blocks([], [post], "bb" * 32)
        self.assertIn("zero", [item.id for item in self.database.list_conversations()])
        self.assertEqual(len(self.database.list_messages("zero")), 2)

    def test_direct_message_outbox_and_delivery_state(self) -> None:
        peer = "33" * 32
        message = self.database.queue_direct_message(peer, "encrypted hello")
        self.assertEqual(len(self.database.pending_outbox()), 1)
        self.database.mark_message_published(message.id, "44" * 32)
        self.assertEqual(self.database.pending_outbox(), [])
        saved = self.database.list_messages(peer)[0]
        self.assertEqual(saved.delivery_state, "relay-accepted")

    def test_incoming_gift_wrap_is_deduplicated(self) -> None:
        sender = "55" * 32
        event_id = "66" * 32
        self.assertTrue(
            self.database.add_incoming_message(sender, "hello", event_id, 1700000000)
        )
        self.assertFalse(
            self.database.add_incoming_message(sender, "hello", event_id, 1700000000)
        )
        self.assertEqual(len(self.database.list_messages(sender)), 1)

    def test_sender_inbox_copy_restores_outgoing_direct_message(self) -> None:
        own = "54" * 32
        peer = "55" * 32
        event_id = "56" * 32
        self.assertTrue(
            self.database.add_recovered_outgoing_message(
                peer, own, "my recovered reply", event_id, 1700000000
            )
        )
        message = self.database.list_messages(peer)[0]
        self.assertEqual(message.direction, "outgoing")
        self.assertEqual(message.author_pubkey, own)
        self.assertEqual(message.delivery_state, "relay-accepted")
        conversation = next(
            item for item in self.database.list_conversations() if item.id == peer
        )
        self.assertEqual(conversation.unread_count, 0)

    def test_sender_inbox_copy_restores_outgoing_group_message(self) -> None:
        own = "57" * 32
        peer = "58" * 32
        self.assertTrue(
            self.database.add_group_message(
                "group:recovered",
                "Recovered group",
                [own, peer],
                own,
                "my recovered group reply",
                "59" * 32,
                1700000000,
                "alice",
                recovered_outgoing=True,
            )
        )
        message = self.database.list_messages("group:recovered")[0]
        self.assertEqual(message.direction, "outgoing")
        self.assertEqual(message.author_pubkey, own)
        self.assertEqual(message.delivery_state, "relay-accepted")
        conversation = next(
            item
            for item in self.database.list_conversations(mode="groups")
            if item.id == "group:recovered"
        )
        self.assertEqual(conversation.unread_count, 0)

    def test_sender_group_attachment_copy_does_not_duplicate_local_upload(self) -> None:
        own = "60" * 32
        peer = "61" * 32
        group_id = "group:attachment-recovery"
        self.database.create_group(group_id, "Files", [own, peer], own)
        local = self.database.queue_group_attachment(
            group_id,
            "coldharbor.zip",
            "coldharbor.zip\nEncrypted Blossom attachment",
            [peer],
            own,
            "alice",
        )
        inserted = self.database.add_group_message(
            group_id,
            "Files",
            [own, peer],
            own,
            "coldharbor.zip\nDownloaded, decrypted, and SHA-256 verified",
            "62" * 32,
            local.sent_at,
            "alice",
            "attachments/8c145beb-coldharbor.zip",
            "application/x-zip-compressed",
            recovered_outgoing=True,
        )
        self.assertFalse(inserted)
        self.assertEqual(len(self.database.list_messages(group_id)), 1)

    def test_upgrade_hides_preexisting_sender_attachment_duplicate(self) -> None:
        own = "67" * 32
        peer = "68" * 32
        group_id = "group:legacy-attachment-copy"
        self.database.create_group(group_id, "Legacy Files", [own, peer], own)
        local = self.database.queue_group_attachment(
            group_id, "bundle.zip", "Shared bundle.zip", [peer], own, "alice"
        )
        self.database.connection.execute(
            """INSERT INTO messages
               (conversation_id, event_id, author_pubkey, author_name,
                attachment_path, attachment_mime, direction, content, sent_at,
                delivery_state, protocol)
               VALUES (?, ?, ?, 'alice', ?, 'application/x-zip-compressed',
                       'outgoing', 'Downloaded and verified', ?, 'relay-accepted',
                       'NIP-17 GROUP')""",
            (
                group_id,
                "69" * 32,
                own,
                "attachments/abcdef123456-bundle.zip",
                local.sent_at,
            ),
        )
        self.database.connection.commit()
        path = self.database.path
        self.database.close()
        self.database = ClientDatabase(path)
        self.assertEqual(len(self.database.list_messages(group_id)), 1)

    def test_sender_direct_attachment_copy_does_not_duplicate_local_upload(self) -> None:
        own = "63" * 32
        peer = "64" * 32
        local = self.database.queue_attachment(
            peer,
            "archive.rar",
            "archive.rar\nEncrypted Blossom attachment",
        )
        inserted = self.database.add_recovered_outgoing_message(
            peer,
            own,
            "archive.rar\nDownloaded, decrypted, and SHA-256 verified",
            "65" * 32,
            local.sent_at,
            "attachments/0123456789ab-archive.rar",
            "application/vnd.rar",
        )
        self.assertFalse(inserted)
        self.assertEqual(len(self.database.list_messages(peer)), 1)

    def test_hidden_relay_message_stays_hidden_after_duplicate_sync(self) -> None:
        sender = "5a" * 32
        event_id = "5b" * 32
        self.assertTrue(
            self.database.add_incoming_message(
                sender, "hide this locally", event_id, 1700000000
            )
        )
        message = self.database.list_messages(sender)[0]
        self.assertTrue(self.database.hide_message_locally(message.id))
        self.assertEqual(self.database.list_messages(sender), [])
        self.assertFalse(
            self.database.add_incoming_message(
                sender, "hide this locally", event_id, 1700000000
            )
        )
        self.assertEqual(self.database.list_messages(sender), [])

    def test_hiding_unsent_message_cancels_outbox_retry(self) -> None:
        peer = "5c" * 32
        message = self.database.queue_direct_message(peer, "do not send this")
        self.assertEqual(len(self.database.pending_outbox()), 1)
        self.assertTrue(self.database.hide_message_locally(message.id))
        self.assertEqual(self.database.pending_outbox(), [])
        self.assertEqual(self.database.list_messages(peer), [])

    def test_hiding_direct_conversation_cancels_outbox_and_new_message_reopens_it(self) -> None:
        peer = "5f" * 32
        self.database.queue_direct_message(peer, "wrong recipient")
        self.assertTrue(self.database.hide_direct_conversation_locally(peer))
        self.assertEqual(self.database.pending_outbox(), [])
        self.assertEqual(self.database.list_messages(peer), [])
        self.assertNotIn(peer, [item.id for item in self.database.list_conversations()])

        self.assertTrue(
            self.database.add_incoming_message(
                peer, "old relay copy", "6e" * 32, 1700000000
            )
        )
        self.assertNotIn(peer, [item.id for item in self.database.list_conversations()])

        self.assertTrue(
            self.database.add_incoming_message(
                peer, "new message", "6f" * 32, int(time.time()) + 1
            )
        )
        self.assertIn(peer, [item.id for item in self.database.list_conversations()])
        self.assertEqual([item.content for item in self.database.list_messages(peer)], ["new message"])

    def test_removing_contact_keeps_conversation_outside_contact_roster(self) -> None:
        peer = "5d" * 32
        self.database.add_incoming_message(
            peer, "conversation remains", "5e" * 32, 1700000000
        )
        self.assertIn(peer, [item.id for item in self.database.list_conversations(mode="contacts")])
        self.database.remove_contact(peer)
        self.assertNotIn(
            peer, [item.id for item in self.database.list_conversations(mode="contacts")]
        )
        self.assertIn(peer, [item.id for item in self.database.list_conversations(mode="all")])
        self.assertEqual(len(self.database.list_messages(peer)), 1)

    def test_group_membership_and_outbox_are_persistent(self) -> None:
        members = ["77" * 32, "88" * 32]
        self.database.create_group("group:test", "Test group", members)
        sender = "99" * 32
        message = self.database.queue_group_message(
            "group:test", "hello group", members, sender, "alice"
        )
        self.assertEqual(self.database.group_members("group:test"), members)
        queued = self.database.pending_outbox()[0]
        self.assertEqual(queued["message_id"], message.id)
        self.assertEqual(queued["message_type"], "group")
        stored = self.database.list_messages("group:test")[0]
        self.assertEqual(stored.author_pubkey, sender)
        self.assertEqual(stored.author_name, "alice")

        incoming_sender = "aa" * 32
        self.database.add_group_message(
            "group:test",
            "Test group",
            members,
            incoming_sender,
            "hello from bob",
            "bb" * 32,
            1700000000,
            "bob",
        )
        incoming = self.database.list_messages("group:test")[0]
        self.assertEqual(incoming.author_pubkey, incoming_sender)
        self.assertEqual(incoming.author_name, "bob")

        attachment = self.database.queue_group_attachment(
            "group:test",
            "pasted.png",
            "pasted image",
            members,
            sender,
            "alice",
        )
        attachment_outbox = next(
            row for row in self.database.pending_outbox() if row["message_id"] == attachment.id
        )
        self.assertEqual(attachment_outbox["message_type"], "group_attachment")
        self.assertEqual(attachment_outbox["attachment_path"], "pasted.png")

    def test_public_posts_reactions_and_follows(self) -> None:
        author = "99" * 32
        post = "aa" * 32
        self.database.upsert_post(post, author, "public post", 1700000000)
        self.database.upsert_reaction("bb" * 32, post, "cc" * 32, "+", 1700000001)
        self.database.set_following(author, True)
        rows = self.database.list_posts(followed_only=True)
        self.assertEqual(rows[0]["event_id"], post)
        self.assertEqual(rows[0]["reaction_count"], 1)

    def test_contacts_profiles_and_profile_targets_are_persistent(self) -> None:
        peer = "ab" * 32
        conversation_id = self.database.ensure_direct_conversation(peer)
        self.database.add_contact(peer, "local friend")
        self.database.upsert_profile(
            peer,
            "alice",
            "Alice Nostr",
            "https://example.test/alice.png",
            1700000000,
            "Nostr profile text",
            "alice@example.test",
            b"avatar-png",
        )
        profile = self.database.get_profile(peer)
        self.assertEqual(profile["nickname"], "local friend")
        self.assertEqual(profile["about"], "Nostr profile text")
        self.assertEqual(profile["picture_blob"], b"avatar-png")
        self.assertIn(peer, self.database.profile_targets())
        contacts = self.database.list_conversations(mode="contacts")
        self.assertIn(conversation_id, [item.id for item in contacts])
        self.assertEqual(
            next(item for item in contacts if item.id == conversation_id).display_name,
            "local friend",
        )
        self.database.remove_contact(peer)
        self.assertNotIn(conversation_id, [item.id for item in self.database.list_conversations(mode="contacts")])

    def test_new_direct_conversation_automatically_becomes_a_contact(self) -> None:
        peer = "d1" * 32
        conversation_id = self.database.ensure_direct_conversation(peer, "New peer")

        self.assertTrue(self.database.is_contact(peer))
        self.assertIn(
            conversation_id,
            [item.id for item in self.database.list_conversations(mode="contacts")],
        )

    def test_duplicate_contact_names_include_public_key_fingerprints(self) -> None:
        first = "a1" * 32
        second = "b2" * 32
        self.database.ensure_direct_conversation(first, "same-name")
        self.database.ensure_direct_conversation(second, "same-name")

        names = {
            item.peer_pubkey: item.display_name
            for item in self.database.list_conversations(mode="contacts")
            if item.peer_pubkey in {first, second}
        }
        self.assertEqual(names[first], f"same-name - {first[:8]}")
        self.assertEqual(names[second], f"same-name - {second[:8]}")

    def test_local_user_block_hides_messages_but_remains_manageable_in_contacts(self) -> None:
        peer = "e3" * 32
        conversation_id = self.database.ensure_direct_conversation(peer, "blocked peer")
        self.database.set_user_blocked(peer, True)

        self.assertTrue(self.database.is_user_blocked(peer))
        self.assertNotIn(
            conversation_id,
            [item.id for item in self.database.list_conversations()],
        )
        contact = next(
            item
            for item in self.database.list_conversations(mode="contacts")
            if item.id == conversation_id
        )
        self.assertIn("[BLOCKED]", contact.display_name)
        self.assertFalse(
            self.database.add_incoming_message(
                peer, "spam", "f4" * 32, 1700000000
            )
        )

        self.database.set_user_blocked(peer, False)
        self.assertFalse(self.database.is_user_blocked(peer))
        self.assertIn(
            conversation_id,
            [item.id for item in self.database.list_conversations()],
        )

    def test_blocked_group_sender_is_not_persisted(self) -> None:
        own = "e4" * 32
        blocked = "e5" * 32
        self.database.create_group(
            "group:block-test", "Block test", [own, blocked], creator_pubkey=own
        )
        self.database.set_user_blocked(blocked, True)

        self.assertFalse(
            self.database.add_group_message(
                "group:block-test",
                "Block test",
                [own, blocked],
                blocked,
                "group spam",
                "e6" * 32,
                1700000000,
                "spammer",
            )
        )
        self.assertEqual(self.database.list_messages("group:block-test"), [])

    def test_readding_blocked_npub_unblocks_contact(self) -> None:
        peer = "e7" * 32
        self.database.ensure_direct_conversation(peer, "returning contact")
        self.database.set_user_blocked(peer, True)
        self.assertTrue(self.database.is_user_blocked(peer))

        self.database.add_contact(peer, "welcome back")

        self.assertFalse(self.database.is_user_blocked(peer))
        self.assertTrue(self.database.is_contact(peer))

    def test_message_can_be_mapped_back_to_its_conversation(self) -> None:
        message = self.database.add_outgoing_message("zero", "status scope")
        self.assertEqual(self.database.conversation_id_for_message(message.id), "zero")

    def test_group_creator_membership_and_deletion_are_persistent(self) -> None:
        creator = "c1" * 32
        member = "c2" * 32
        self.database.create_group(
            "group:owned", "Owned group", [creator, member], creator_pubkey=creator
        )
        self.assertEqual(self.database.group_creator("group:owned"), creator)
        self.database.remove_group_member("group:owned", member)
        self.assertEqual(self.database.group_members("group:owned"), [creator])
        self.database.delete_group("group:owned")
        self.assertNotIn(
            "group:owned", [item.id for item in self.database.list_conversations(mode="groups")]
        )


if __name__ == "__main__":
    unittest.main()
