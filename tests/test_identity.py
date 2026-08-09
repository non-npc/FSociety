from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtGui import QColor, QImage

from fsociety_client.database import ClientDatabase
from fsociety_client.identity import IdentityVault, normalize_avatar


class IdentityVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = ClientDatabase(Path(self.temporary.name, "client.sqlite3"))
        self.vault = IdentityVault(self.database.connection)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary.cleanup()

    def test_generated_identity_is_encrypted_and_unlocks(self) -> None:
        session, nsec = self.vault.generate("Laptop", "alice", "correct horse battery")
        record = self.vault.list_identities()[0]
        self.assertEqual(record.username, "alice")
        self.assertTrue(record.encrypted_secret.startswith("ncryptsec1"))
        self.assertNotIn(nsec, record.encrypted_secret)
        unlocked = self.vault.unlock(record.id, "correct horse battery")
        self.assertEqual(unlocked.keys.public_key().to_bech32(), session.record.npub)

    def test_wrong_password_is_rejected(self) -> None:
        session, _ = self.vault.generate("Laptop", "alice", "correct horse battery")
        with self.assertRaisesRegex(ValueError, "Incorrect password"):
            self.vault.unlock(session.record.id, "wrong password")

    def test_avatar_is_exact_128_png(self) -> None:
        source = Path(self.temporary.name, "small.png")
        image = QImage(32, 64, QImage.Format.Format_ARGB32)
        image.fill(QColor("#46e6e1"))
        self.assertTrue(image.save(str(source), "PNG"))
        normalized = normalize_avatar(source)
        result = QImage.fromData(normalized, "PNG")
        self.assertEqual((result.width(), result.height()), (128, 128))

    def test_profile_name_and_avatar_can_be_updated_without_replacing_keys(self) -> None:
        session, _ = self.vault.generate("Laptop", "alice", "correct horse battery")
        updated = self.vault.update_profile(session, "alice-updated", b"new-avatar")
        self.assertEqual(updated.record.username, "alice-updated")
        self.assertEqual(updated.record.avatar_png, b"new-avatar")
        self.assertEqual(updated.record.pubkey_hex, session.record.pubkey_hex)
        stored = self.vault.list_identities()[0]
        self.assertEqual(stored.username, "alice-updated")
        self.assertEqual(stored.avatar_png, b"new-avatar")


if __name__ == "__main__":
    unittest.main()
