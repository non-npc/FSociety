from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QMimeData, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QTextBrowser

from fsociety_client.database import ClientDatabase
from fsociety_client.identity import IdentityVault, RecoveryDialog
from fsociety_client.models import Message
from fsociety_client.theme import APP_STYLESHEET
from fsociety_client.window import (
    GROUP_CONTROL_PREFIX,
    MainWindow,
    MessageComposer,
    SettingsDialog,
)
from fsociety_client.widgets import MessageBubble, MessageRow
from fixtures import seed_conversation_fixtures


class ClientInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = ClientDatabase(Path(self.temporary_directory.name, "ui.sqlite3"))
        seed_conversation_fixtures(self.database)
        self.window = MainWindow(self.database)

    def tearDown(self) -> None:
        self.window.close()
        self.temporary_directory.cleanup()

    def test_navigation_changes_sidebar_content(self) -> None:
        self.window._section_selected("communities")
        self.assertEqual(self.window.sidebar.mode, "groups")
        self.assertEqual(self.window.sidebar.list_widget.count(), 2)
        self.window._section_selected("network")
        self.assertTrue(self.window.sidebar.isHidden())
        self.assertIs(
            self.window.content_stack.currentWidget(), self.window.network_dashboard
        )

    def test_remove_selected_contact_button_keeps_message_history(self) -> None:
        peer = "01" * 32
        self.window._section_selected("contacts")
        self.window.sidebar.select_conversation("zero")
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window._remove_selected_contact()

        self.assertFalse(self.database.is_contact(peer))
        self.assertEqual(len(self.database.list_messages("zero")), 3)
        self.assertNotIn(
            "zero",
            [item.id for item in self.database.list_conversations(mode="contacts")],
        )
        self.assertIn(
            "zero", [item.id for item in self.database.list_conversations(mode="all")]
        )

    def test_delete_direct_conversation_removes_it_from_local_view(self) -> None:
        conversation = next(
            item for item in self.database.list_conversations() if item.id == "zero"
        )
        queued = self.database.queue_direct_message("01" * 32, "wrong recipient")
        self.assertEqual(queued.conversation_id, "zero")
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window._delete_direct_conversation(conversation)

        self.assertNotIn(
            "zero", [item.id for item in self.database.list_conversations(mode="all")]
        )
        self.assertEqual(self.database.pending_outbox(), [])
        self.assertNotEqual(
            getattr(self.window.chat.conversation, "id", None), "zero"
        )

    def test_selected_contact_can_be_blocked_and_unblocked(self) -> None:
        peer = "01" * 32
        self.window._section_selected("contacts")
        self.window.sidebar.select_conversation("zero")
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window._toggle_selected_contact_block()
        self.assertTrue(self.database.is_user_blocked(peer))
        self.assertEqual(self.database.list_messages("zero"), [])

        self.window.sidebar.select_conversation("zero")
        self.window._toggle_selected_contact_block()
        self.assertFalse(self.database.is_user_blocked(peer))
        self.assertEqual(len(self.database.list_messages("zero")), 3)

    def test_blocked_group_control_cannot_modify_group(self) -> None:
        creator = "d1" * 32
        own = "d2" * 32
        self.database.create_group(
            "group:blocked-control",
            "Protected group",
            [creator, own],
            creator_pubkey=creator,
        )
        self.database.set_user_blocked(creator, True)
        self.window._direct_message_received(
            {
                "recipients": [creator, own],
                "group_id": "group:blocked-control",
                "subject": "Protected group",
                "sender": creator,
                "content": GROUP_CONTROL_PREFIX
                + '{"action":"delete","actor":"' + creator + '","name":"creator"}',
                "event_id": "d3" * 32,
                "sent_at": 1700000000,
                "sender_name": "creator",
            }
        )
        self.assertIn(
            "group:blocked-control",
            [item.id for item in self.database.list_conversations(mode="groups")],
        )

    def test_send_button_persists_composed_message(self) -> None:
        self.window.sidebar.select_conversation("zero")
        self.window.chat.input.setPlainText("sent from the UI")
        self.window.chat.send.click()
        self.assertEqual(self.database.list_messages("zero")[-1].content, "sent from the UI")

    def test_selecting_chat_reenables_composer_after_it_was_cleared(self) -> None:
        conversation = next(
            item for item in self.database.list_conversations() if item.id == "zero"
        )
        self.window.chat.clear_conversation()
        self.assertFalse(self.window.chat.input.isEnabled())
        self.assertFalse(self.window.chat.send.isEnabled())

        self.window._conversation_selected(conversation)
        self.assertTrue(self.window.chat.input.isEnabled())
        self.assertTrue(self.window.chat.send.isEnabled())
        self.window.chat.input.setPlainText("composer restored")
        self.window.chat.send.click()
        self.assertEqual(
            self.database.list_messages("zero")[-1].content, "composer restored"
        )

    def test_selecting_conversation_clears_visible_unread_counter(self) -> None:
        self.window.sidebar.select_conversation("cipher")
        self.application.processEvents()

        current = self.window.sidebar.list_widget.currentItem()
        self.assertIsNotNone(current)
        self.assertEqual(current.data(Qt.ItemDataRole.UserRole + 1).unread_count, 0)
        self.assertNotIn(
            "cipher",
            [item.id for item in self.database.list_conversations(mode="unread")],
        )

    def test_message_received_in_open_chat_does_not_create_unread_counter(self) -> None:
        self.window.sidebar.select_conversation("zero")
        self.window._direct_message_received(
            {
                "sender": "01" * 32,
                "content": "currently visible",
                "event_id": "ad" * 32,
                "sent_at": 1700000010,
            }
        )
        self.application.processEvents()

        conversation = next(
            item for item in self.database.list_conversations() if item.id == "zero"
        )
        self.assertEqual(conversation.unread_count, 0)
        current = self.window.sidebar.list_widget.currentItem()
        self.assertEqual(current.data(Qt.ItemDataRole.UserRole + 1).unread_count, 0)

    def test_sender_group_recovery_copy_restores_own_message(self) -> None:
        session, _ = IdentityVault(self.database.connection).generate(
            "Recovery identity", "alice", "correct horse battery"
        )
        self.window.identity = session
        own = session.keys.public_key().to_hex()
        peer = "ab" * 32

        self.window._direct_message_received(
            {
                "sender": own,
                "sender_name": "alice",
                "recipients": [own, peer],
                "group_id": "group:sender-recovery",
                "subject": "Recovered conversation",
                "content": "my earlier reply",
                "event_id": "ac" * 32,
                "sent_at": 1700000011,
                "self_copy": True,
            }
        )

        messages = self.database.list_messages("group:sender-recovery")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].direction, "outgoing")
        self.assertEqual(messages[0].author_pubkey, own)
        conversation = next(
            item
            for item in self.database.list_conversations(mode="groups")
            if item.id == "group:sender-recovery"
        )
        self.assertEqual(conversation.unread_count, 0)

    def test_settings_copies_full_public_key(self) -> None:
        session, _ = IdentityVault(self.database.connection).generate(
            "Test identity", "alice", "correct horse battery"
        )
        dialog = SettingsDialog(self.database, session)
        dialog.copy_npub.click()
        self.application.processEvents()
        self.assertEqual(
            QApplication.clipboard().text(), session.record.npub
        )
        self.assertIn("COPIED", dialog.copy_npub.text())
        dialog.close()

    def test_group_message_bubble_displays_sender_name(self) -> None:
        members = ["11" * 32, "22" * 32]
        self.database.create_group("group:sender", "Sender test", members)
        self.database.add_group_message(
            "group:sender",
            "Sender test",
            members,
            "11" * 32,
            "hello group",
            "33" * 32,
            1700000000,
            "alice",
        )
        message = self.database.list_messages("group:sender")[0]
        bubble = MessageBubble(message, False, True)
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("GROUP //", labels)
        self.assertIn("alice", labels)
        sender = bubble.findChild(QLabel, "messageSender")
        self.assertIsNotNone(sender)
        self.assertEqual(sender.text(), "alice")
        bubble.close()

    def test_message_composer_emits_pasted_clipboard_image(self) -> None:
        composer = MessageComposer()
        pasted: list[QImage] = []
        composer.image_pasted.connect(pasted.append)
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(0xFF4DEBF3)
        mime = QMimeData()
        mime.setImageData(image)
        composer.insertFromMimeData(mime)
        self.assertEqual(len(pasted), 1)
        self.assertEqual(pasted[0].size(), image.size())
        self.assertEqual(composer.toPlainText(), "")
        composer.close()

    def test_emote_is_inserted_at_the_current_cursor_position(self) -> None:
        self.window.chat.input.setPlainText("hello world")
        cursor = self.window.chat.input.textCursor()
        cursor.setPosition(6)
        self.window.chat.input.setTextCursor(cursor)
        self.window.chat._insert_emote("😎")
        self.assertEqual(self.window.chat.input.toPlainText(), "hello 😎world")

    def test_public_feed_is_not_exposed_by_navigation_or_settings(self) -> None:
        navigation_tips = {
            button.toolTip() for button in self.window.nav.findChildren(QPushButton)
        }
        self.assertNotIn("Feed", navigation_tips)
        dialog = SettingsDialog(self.database)
        self.assertNotIn("Public feed", " ".join(label.text() for label in dialog.findChildren(QLabel)))
        dialog.close()

    def test_image_attachment_is_rendered_inside_message_bubble(self) -> None:
        path = Path(self.temporary_directory.name, "inline.png")
        image = QImage(20, 10, QImage.Format.Format_ARGB32)
        image.fill(0xFF4DEBF3)
        self.assertTrue(image.save(str(path), "PNG"))
        self.database.queue_attachment("zero", str(path), "shared image")
        message = self.database.list_messages("zero")[-1]
        bubble = MessageBubble(message)
        rendered = [
            label.pixmap()
            for label in bubble.findChildren(QLabel)
            if label.pixmap() is not None and not label.pixmap().isNull()
        ]
        self.assertEqual(len(rendered), 1)
        bubble.close()

    def test_video_attachment_does_not_create_player_inside_message_bubble(self) -> None:
        path = Path(self.temporary_directory.name, "clip.mp4")
        path.write_bytes(b"video fixture")
        self.database.queue_attachment("zero", str(path), "shared video")
        message = self.database.list_messages("zero")[-1]
        bubble = MessageBubble(message)

        self.assertEqual(bubble.findChildren(QMediaPlayer), [])
        self.assertEqual(bubble.findChildren(QVideoWidget), [])
        buttons = [button.text() for button in bubble.findChildren(QPushButton)]
        self.assertIn("▶  OPEN VIDEO", buttons)
        bubble.close()

    def test_message_bubble_uses_eighty_percent_of_row_width(self) -> None:
        message = Message(1, "zero", "outgoing", "hello", 1, "received", "NIP-17")
        row = MessageRow(message)
        row.resize(1000, 160)
        row.show()
        self.application.processEvents()

        bubble = row.findChild(MessageBubble)
        self.assertIsNotNone(bubble)
        self.assertAlmostEqual(bubble.width() / row.width(), 0.8, delta=0.02)
        row.close()

    def test_archive_attachment_has_save_control(self) -> None:
        path = Path(self.temporary_directory.name, "backup.zip")
        path.write_bytes(b"archive")
        self.database.queue_attachment(
            "zero",
            str(path),
            "📎 backup.zip\nDownloaded, decrypted, and SHA-256 verified",
        )
        message = self.database.list_messages("zero")[-1]
        bubble = MessageBubble(message)
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        buttons = [button.text() for button in bubble.findChildren(QPushButton)]
        body = bubble.findChild(QTextBrowser, "messageBody")
        self.assertTrue(any("application/zip" in label for label in labels))
        self.assertIn("SAVE FILE AS…", buttons)
        self.assertIsNotNone(body)
        self.assertNotIn("href=", body.toHtml())
        bubble.close()

    def test_regular_chat_links_remain_clickable(self) -> None:
        message = self.database.add_outgoing_message(
            "zero", "Visit https://www.yandex.com or yandex.com"
        )
        bubble = MessageBubble(message)
        body = bubble.findChild(QTextBrowser, "messageBody")
        self.assertIsNotNone(body)
        self.assertEqual(body.toHtml().count("href="), 2)
        bubble.close()

    def test_long_unbroken_message_wraps_without_changing_copied_text(self) -> None:
        invite = "fsociety-group1:" + "A" * 240
        message = Message(1, "zero", "outgoing", invite, 1, "received", "NIP-17")
        row = MessageRow(message)
        row.resize(1000, 300)
        row.show()
        self.application.processEvents()

        bubble = row.findChild(MessageBubble)
        body = row.findChild(QTextBrowser, "messageBody")
        self.assertIsNotNone(bubble)
        self.assertIsNotNone(body)
        self.assertAlmostEqual(bubble.width() / row.width(), 0.8, delta=0.02)
        self.assertEqual(body.toPlainText(), invite)
        self.assertGreater(body.document().size().height(), body.fontMetrics().height())
        row.close()

    def test_large_history_keeps_a_bounded_message_widget_window(self) -> None:
        base = 1_800_000_000
        self.database.connection.executemany(
            """INSERT INTO messages
               (conversation_id, direction, content, sent_at, delivery_state, protocol)
               VALUES ('zero', 'incoming', ?, ?, 'received', 'NIP-17')""",
            ((f"large history {index}", base + index) for index in range(320)),
        )
        self.database.connection.commit()
        conversation = next(
            item for item in self.database.list_conversations() if item.id == "zero"
        )
        self.window.chat.show_conversation(conversation, force_reload=True)
        self.assertEqual(len(self.window.chat.loaded_messages), 100)
        self.assertEqual(len(self.window.chat.message_rows), 100)
        for _ in range(4):
            self.window.chat._load_older_messages()
            QApplication.processEvents()
        self.assertEqual(len(self.window.chat.loaded_messages), 250)
        self.assertEqual(len(self.window.chat.message_rows), 250)
        self.assertTrue(self.window.chat.has_newer_messages)
        self.assertFalse(self.window.chat.new_messages.isHidden())
        self.window.chat._return_to_latest()
        self.assertEqual(len(self.window.chat.loaded_messages), 100)
        self.assertTrue(self.window.chat.new_messages.isHidden())

        self.window.chat.bottom_scroll_pending = False
        self.window.chat.scroll.verticalScrollBar().setValue(0)
        self.database.connection.execute(
            """INSERT INTO messages
               (conversation_id, direction, content, sent_at, delivery_state, protocol)
               VALUES ('zero', 'incoming', 'new while reading', ?, 'received', 'NIP-17')""",
            (base + 500,),
        )
        self.database.connection.commit()
        with patch.object(self.window.chat, "is_near_bottom", return_value=False):
            self.window.chat.show_conversation(conversation, scroll_to_latest=False)
        self.assertEqual(self.window.chat.pending_new_messages, 1)
        self.assertFalse(self.window.chat.new_messages.isHidden())
        self.window.chat._return_to_latest()
        self.assertEqual(self.window.chat.loaded_messages[-1].content, "new while reading")
        self.assertTrue(self.window.chat.new_messages.isHidden())

    def test_recovery_screen_copies_public_and_private_keys(self) -> None:
        session, nsec = IdentityVault(self.database.connection).generate(
            "Backup test", "backup-user", "correct horse battery"
        )
        dialog = RecoveryDialog(session.record.npub, nsec)
        dialog.copy_npub.click()
        self.assertEqual(QApplication.clipboard().text(), session.record.npub)
        with patch.object(
            QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok
        ):
            dialog.copy_nsec.click()
        self.assertEqual(QApplication.clipboard().text(), nsec)
        self.assertIn("TIMER ACTIVE", dialog.copy_nsec.text())
        dialog.accept()

    def test_recovery_clipboard_timer_survives_destroyed_dialog(self) -> None:
        session, nsec = IdentityVault(self.database.connection).generate(
            "Timer test", "timer-user", "correct horse battery"
        )
        callbacks = []
        dialog = RecoveryDialog(session.record.npub, nsec)
        with (
            patch.object(
                QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok
            ),
            patch(
                "fsociety_client.identity.QTimer.singleShot",
                side_effect=lambda _delay, callback: callbacks.append(callback),
            ),
        ):
            dialog.copy_nsec.click()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(QApplication.clipboard().text(), nsec)
        dialog.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        callbacks[0]()
        self.assertEqual(QApplication.clipboard().text(), "")

    def test_checkbox_theme_has_visible_unchecked_and_checked_states(self) -> None:
        self.assertIn("QCheckBox::indicator", APP_STYLESHEET)
        self.assertIn("border: 2px solid #4debf3", APP_STYLESHEET)
        self.assertIn("QCheckBox::indicator:checked", APP_STYLESHEET)

    def test_delivery_status_is_scoped_to_selected_conversation(self) -> None:
        first = self.database.add_outgoing_message("zero", "first status")
        second = self.database.add_outgoing_message("cipher", "second status")
        zero = next(item for item in self.database.list_conversations() if item.id == "zero")
        cipher = next(item for item in self.database.list_conversations() if item.id == "cipher")
        self.window._conversation_selected(zero)
        self.window._set_message_status(first.id, "FIRST GROUP ERROR")
        self.window._set_message_status(second.id, "SECOND GROUP ERROR")
        self.assertIn("FIRST GROUP ERROR", self.window.network_status.text())
        self.assertNotIn("SECOND GROUP ERROR", self.window.network_status.text())
        self.window._conversation_selected(cipher)
        self.assertIn("SECOND GROUP ERROR", self.window.network_status.text())

    def test_signed_creator_control_removes_group_from_recipient(self) -> None:
        creator = "d1" * 32
        member = "d2" * 32
        self.database.create_group(
            "group:close", "Close me", [creator, member], creator_pubkey=creator
        )
        payload = {
            "group_id": "group:close",
            "subject": "Close me",
            "recipients": [creator, member],
            "sender": creator,
            "content": GROUP_CONTROL_PREFIX
            + '{"action":"delete","actor":"' + creator + '","name":"creator"}',
            "event_id": "ef" * 32,
            "sent_at": 1700000000,
            "sender_name": "creator",
        }
        self.window._direct_message_received(payload)
        self.assertNotIn(
            "group:close", [item.id for item in self.database.list_conversations(mode="groups")]
        )

    def test_non_creator_delete_control_is_not_honored(self) -> None:
        creator = "e1" * 32
        member = "e2" * 32
        self.database.create_group(
            "group:protected", "Protected", [creator, member], creator_pubkey=creator
        )
        payload = {
            "group_id": "group:protected",
            "subject": "Protected",
            "recipients": [creator, member],
            "sender": member,
            "content": GROUP_CONTROL_PREFIX
            + '{"action":"delete","actor":"' + member + '","name":"member"}',
            "event_id": "fe" * 32,
            "sent_at": 1700000000,
            "sender_name": "member",
        }
        self.window._direct_message_received(payload)
        self.assertIn(
            "group:protected", [item.id for item in self.database.list_conversations(mode="groups")]
        )


if __name__ == "__main__":
    unittest.main()
