from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from fsociety_client.database import ClientDatabase
from fsociety_client.idle_visualization import IdleVisualizationController
from fsociety_client.window import SettingsDialog


class IdleVisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = ClientDatabase(
            Path(self.temporary_directory.name, "idle-screen.sqlite3")
        )
        self.window = QWidget()
        self.window.resize(800, 450)
        self.window.show()
        self.application.processEvents()
        self.controller = IdleVisualizationController(
            self.window, self.database, timeout_seconds=1
        )

    def tearDown(self) -> None:
        self.controller.shutdown()
        self.window.close()
        self.database.close()
        self.temporary_directory.cleanup()

    def test_idle_screen_is_enabled_by_default_and_resumes_on_input(self) -> None:
        self.assertTrue(self.controller.enabled)
        self.controller.last_activity = time.monotonic() - 2
        self.controller.check_idle()
        self.application.processEvents()
        self.assertTrue(self.controller.overlay.isVisible())

        image = QImage(self.window.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        self.window.render(painter)
        painter.end()
        self.assertGreater(image.pixelColor(400, 100).value(), 0)

        consumed = self.controller.eventFilter(
            self.window, QEvent(QEvent.Type.MouseButtonPress)
        )
        self.assertTrue(consumed)
        self.assertFalse(self.controller.overlay.isVisible())

    def test_disabled_setting_prevents_idle_screen(self) -> None:
        self.database.set_setting("ui.idle_visualization", "false")
        self.controller.refresh_settings()
        self.controller.last_activity = time.monotonic() - 2
        self.controller.check_idle()
        self.application.processEvents()
        self.assertFalse(self.controller.enabled)
        self.assertFalse(self.controller.overlay.isVisible())

    def test_settings_exposes_and_persists_idle_screen_toggle(self) -> None:
        dialog = SettingsDialog(self.database)
        self.assertTrue(dialog.idle_screen.isChecked())
        dialog.idle_screen.setChecked(False)
        dialog._save()
        self.assertEqual(
            self.database.get_setting("ui.idle_visualization", "true"), "false"
        )


if __name__ == "__main__":
    unittest.main()
