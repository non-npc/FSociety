from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fsociety_client.app import (
    account_database_path,
    application_directory,
    default_database_path,
)
from fsociety_client.database import ClientDatabase


class AccountIsolationTests(unittest.TestCase):
    def test_default_database_is_inside_portable_client_data_directory(self) -> None:
        self.assertEqual(
            default_database_path(),
            application_directory() / "data" / "fsociety.sqlite3",
        )

    def test_each_public_key_has_an_independent_runtime_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            vault_path = Path(temporary_directory, "fsociety.sqlite3")
            first_path = account_database_path(vault_path, "11" * 32)
            second_path = account_database_path(vault_path, "22" * 32)
            self.assertNotEqual(first_path, second_path)

            first = ClientDatabase(first_path)
            second = ClientDatabase(second_path)
            try:
                first.create_group("group:test", "First account group", ["11" * 32])
                first.queue_group_message(
                    "group:test", "owned by first", [], "11" * 32, "first-user"
                )
                first.set_setting("public_feed.enabled", "true")

                self.assertEqual(len(first.list_messages("group:test")), 1)
                self.assertEqual(second.list_conversations(), [])
                self.assertEqual(second.get_setting("public_feed.enabled", "false"), "false")
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
