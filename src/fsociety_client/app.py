from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Qt's FFmpeg backend logs complete media stream metadata at info level whenever
# an inline player opens a file. Keep real warnings/errors, but do not clutter a
# normal fsociety console with decoder diagnostics. Respect an explicit logging
# configuration supplied by a developer or beta tester.
os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.multimedia.ffmpeg=false;qt.multimedia.ffmpeg.*=false",
)
# Qt checks whether QT_FFMPEG_DEBUG exists, not whether its value is truthy.
# An inherited value of "0" therefore enables the extremely verbose FFmpeg
# transform/codec dump. Remove only that mistaken value; an explicit developer
# value of "1" remains available for diagnostics.
if os.environ.get("QT_FFMPEG_DEBUG") == "0":
    os.environ.pop("QT_FFMPEG_DEBUG", None)

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from .database import ClientDatabase
from .identity import IdentityDialog, IdentityVault
from .resources import create_splash, load_application_font, resource_path
from .theme import APP_STYLESHEET
from .window import MainWindow


def application_directory() -> Path:
    """Return the portable directory containing the source app or executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_database_path() -> Path:
    """Store all persistent client state inside the portable app directory."""
    return application_directory() / "data" / "fsociety.sqlite3"


def account_database_path(vault_path: Path, pubkey_hex: str) -> Path:
    """Keep network/cache state isolated while identities share one login vault."""
    return vault_path.parent / "accounts" / pubkey_hex / "fsociety.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="fsociety Nostr messenger")
    parser.add_argument("--database", type=Path, help="override the SQLite database path")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def run(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("fsociety")
    app.setOrganizationName("fsociety")
    app.setWindowIcon(QIcon(str(resource_path("fsociety.ico"))))
    app.setStyle("Fusion")
    font_family = load_application_font()
    app.setFont(QFont(font_family, 15))
    app.setStyleSheet(APP_STYLESHEET)

    splash = create_splash()
    splash.show()
    app.processEvents()

    vault_path = arguments.database or default_database_path()
    database = ClientDatabase(vault_path)
    windows: list[MainWindow] = []

    def reveal_main_window() -> None:
        nonlocal database
        splash.close()
        identity = None
        if not arguments.smoke_test:
            identity_dialog = IdentityDialog(IdentityVault(database.connection))
            if identity_dialog.exec() != IdentityDialog.DialogCode.Accepted:
                database.close()
                app.quit()
                return
            identity = identity_dialog.session
            isolated_path = account_database_path(vault_path, identity.record.pubkey_hex)
            database.close()
            database = ClientDatabase(isolated_path)
        def update_profile(session, username: str, avatar_png: bytes | None):
            vault_database = ClientDatabase(vault_path)
            try:
                return IdentityVault(vault_database.connection).update_profile(
                    session, username, avatar_png
                )
            finally:
                vault_database.close()

        window = MainWindow(
            database,
            identity,
            update_profile if identity is not None else None,
        )
        windows.append(window)
        window.show()
        if arguments.smoke_test:
            QTimer.singleShot(300, window.close)

    QTimer.singleShot(50 if arguments.smoke_test else 2500, reveal_main_window)
    return app.exec()
