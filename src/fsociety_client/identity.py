from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from nostr_sdk import EncryptedSecretKey, Keys
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QTimer, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    id: int
    label: str
    username: str
    pubkey_hex: str
    npub: str
    encrypted_secret: str
    avatar_png: bytes | None
    created_at: int
    last_used_at: int | None


@dataclass(slots=True)
class UnlockedIdentity:
    record: IdentityRecord
    keys: Keys


def set_button_text_if_alive(button: QPushButton, text: str) -> None:
    """Ignore a delayed UI update after Qt has destroyed its dialog controls."""
    try:
        button.setText(text)
    except RuntimeError:
        # QTimer.singleShot callbacks can outlive a closed modal dialog. The
        # sensitive clipboard cleanup must still run, but its former button no
        # longer exists and therefore needs no visual reset.
        pass


class IdentityVault:
    """NIP-49 encrypted Nostr identities backed by the client SQLite database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_identities(self) -> list[IdentityRecord]:
        rows = self.connection.execute(
            "SELECT * FROM identities ORDER BY COALESCE(last_used_at, created_at) DESC, id"
        ).fetchall()
        return [IdentityRecord(**dict(row)) for row in rows]

    def generate(
        self,
        label: str,
        username: str,
        password: str,
        avatar_png: bytes | None = None,
    ) -> tuple[UnlockedIdentity, str]:
        self._validate_password(password)
        keys = Keys.generate()
        return self._store(keys, label, username, password, avatar_png)

    def import_secret(
        self,
        secret: str,
        label: str,
        username: str,
        password: str,
        avatar_png: bytes | None = None,
    ) -> UnlockedIdentity:
        self._validate_password(password)
        try:
            keys = Keys.parse(secret.strip())
        except Exception as error:
            raise ValueError("The secret must be a valid nsec or 64-character private key.") from error
        session, _ = self._store(keys, label, username, password, avatar_png)
        return session

    def unlock(self, identity_id: int, password: str) -> UnlockedIdentity:
        row = self.connection.execute(
            "SELECT * FROM identities WHERE id = ?", (identity_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Identity not found.")
        record = IdentityRecord(**dict(row))
        try:
            secret = EncryptedSecretKey.from_bech32(record.encrypted_secret).decrypt(password)
        except Exception as error:
            raise ValueError("Incorrect password or damaged identity vault.") from error
        now = int(time.time())
        self.connection.execute(
            "UPDATE identities SET last_used_at = ? WHERE id = ?", (now, identity_id)
        )
        self.connection.commit()
        refreshed = IdentityRecord(
            record.id,
            record.label,
            record.username,
            record.pubkey_hex,
            record.npub,
            record.encrypted_secret,
            record.avatar_png,
            record.created_at,
            now,
        )
        return UnlockedIdentity(refreshed, Keys(secret))

    def update_profile(
        self, session: UnlockedIdentity, username: str, avatar_png: bytes | None
    ) -> UnlockedIdentity:
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Choose a public username.")
        if len(clean_username) > 64:
            raise ValueError("The public username must be 64 characters or fewer.")
        self.connection.execute(
            "UPDATE identities SET username = ?, avatar_png = ? WHERE id = ?",
            (clean_username, avatar_png, session.record.id),
        )
        self.connection.commit()
        record = IdentityRecord(
            session.record.id,
            session.record.label,
            clean_username,
            session.record.pubkey_hex,
            session.record.npub,
            session.record.encrypted_secret,
            avatar_png,
            session.record.created_at,
            session.record.last_used_at,
        )
        return UnlockedIdentity(record, session.keys)

    def _store(
        self,
        keys: Keys,
        label: str,
        username: str,
        password: str,
        avatar_png: bytes | None,
    ) -> tuple[UnlockedIdentity, str]:
        clean_label = label.strip() or "Nostr identity"
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Choose a public username.")
        if len(clean_username) > 64:
            raise ValueError("The public username must be 64 characters or fewer.")
        secret = keys.secret_key()
        public = keys.public_key()
        recovery_nsec = secret.to_bech32()
        encrypted = secret.encrypt(password).to_bech32()
        now = int(time.time())
        try:
            cursor = self.connection.execute(
                """INSERT INTO identities
                   (label, username, pubkey_hex, npub, encrypted_secret, avatar_png,
                    created_at, last_used_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    clean_label,
                    clean_username,
                    public.to_hex(),
                    public.to_bech32(),
                    encrypted,
                    avatar_png,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("That identity is already stored on this device.") from error
        self.connection.commit()
        record = IdentityRecord(
            int(cursor.lastrowid),
            clean_label,
            clean_username,
            public.to_hex(),
            public.to_bech32(),
            encrypted,
            avatar_png,
            now,
            now,
        )
        return UnlockedIdentity(record, keys), recovery_nsec

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("Use a vault password of at least 8 characters.")


class RecoveryDialog(QDialog):
    def __init__(self, npub: str, nsec: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Back up your Nostr identity")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "Save this recovery secret now. fsociety cannot reset or recover it. "
            "Anyone who obtains it controls this identity."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addWidget(QLabel(f"Public identity:\n{npub}"))
        secret = QTextEdit()
        secret.setReadOnly(True)
        secret.setPlainText(nsec)
        secret.setMaximumHeight(80)
        layout.addWidget(secret)
        copy_row = QHBoxLayout()
        self.copy_npub = QPushButton("COPY PUBLIC KEY (NPUB)")
        self.copy_nsec = QPushButton("COPY PRIVATE RECOVERY KEY (NSEC)")
        self.copy_npub.clicked.connect(
            lambda: self._copy_public_key(npub, self.copy_npub)
        )
        self.copy_nsec.clicked.connect(
            lambda: self._copy_private_key(nsec, self.copy_nsec)
        )
        copy_row.addWidget(self.copy_npub)
        copy_row.addWidget(self.copy_nsec)
        layout.addLayout(copy_row)
        confirmed = QCheckBox("I saved the recovery secret somewhere secure")
        layout.addWidget(confirmed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(False)
        confirmed.toggled.connect(ok.setEnabled)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def reject(self) -> None:
        """Require explicit backup acknowledgement instead of closing past it."""
        return

    def _copy_public_key(self, npub: str, button: QPushButton) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(npub)
        button.setText("PUBLIC KEY COPIED")
        QTimer.singleShot(
            1800,
            lambda: set_button_text_if_alive(button, "COPY PUBLIC KEY (NPUB)"),
        )

    def _copy_private_key(self, nsec: str, button: QPushButton) -> None:
        from PyQt6.QtWidgets import QApplication

        answer = QMessageBox.warning(
            self,
            "Sensitive private key",
            "Anyone with this nsec controls your identity. Copy it only to a secure backup. "
            "The clipboard will be cleared after 60 seconds if it is unchanged.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(nsec)
        button.setText("PRIVATE KEY COPIED — CLIPBOARD TIMER ACTIVE")

        def clear_sensitive_clipboard() -> None:
            if clipboard.text() == nsec:
                clipboard.clear()
            set_button_text_if_alive(button, "COPY PRIVATE RECOVERY KEY (NSEC)")

        QTimer.singleShot(60_000, clear_sensitive_clipboard)


class IdentityDialog(QDialog):
    def __init__(self, vault: IdentityVault, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vault = vault
        self.session: UnlockedIdentity | None = None
        self.setWindowTitle("fsociety identity")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        heading = QLabel("IDENTITY ACCESS  //  LOCAL ENCRYPTED VAULT")
        heading.setObjectName("sectionCode")
        layout.addWidget(heading)
        explanation = QLabel(
            "There is no fsociety account server. Create a Nostr identity, import an "
            "existing secret, or unlock one stored on this device."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.profile = QComboBox()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Local vault password")
        form = QFormLayout()
        form.addRow("Stored identity", self.profile)
        form.addRow("Password", self.password)
        layout.addLayout(form)

        actions = QHBoxLayout()
        unlock = QPushButton("UNLOCK")
        unlock.clicked.connect(self._unlock)
        create = QPushButton("CREATE IDENTITY")
        create.clicked.connect(self._create)
        import_button = QPushButton("IMPORT NSEC")
        import_button.clicked.connect(self._import)
        actions.addWidget(unlock)
        actions.addWidget(create)
        actions.addWidget(import_button)
        layout.addLayout(actions)
        cancel = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)
        self._refresh()

    def _refresh(self) -> None:
        self.profile.clear()
        for record in self.vault.list_identities():
            self.profile.addItem(f"{record.label}  ·  {record.npub[:20]}…", record.id)
        self.password.setEnabled(self.profile.count() > 0)

    def _unlock(self) -> None:
        if self.profile.currentData() is None:
            QMessageBox.information(self, "No stored identity", "Create or import an identity first.")
            return
        try:
            self.session = self.vault.unlock(int(self.profile.currentData()), self.password.text())
        except ValueError as error:
            QMessageBox.warning(self, "Unable to unlock", str(error))
            return
        self.accept()

    def _create(self) -> None:
        values = self._credentials_dialog("Create Nostr identity", include_secret=False)
        if values is None:
            return
        label, username, password, _, avatar_png = values
        try:
            session, nsec = self.vault.generate(label, username, password, avatar_png)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to create identity", str(error))
            return
        RecoveryDialog(session.record.npub, nsec, self).exec()
        self.session = session
        self.accept()

    def _import(self) -> None:
        values = self._credentials_dialog("Import Nostr identity", include_secret=True)
        if values is None:
            return
        label, username, password, secret, avatar_png = values
        try:
            self.session = self.vault.import_secret(
                secret, label, username, password, avatar_png
            )
        except ValueError as error:
            QMessageBox.warning(self, "Unable to import identity", str(error))
            return
        self.accept()

    def _credentials_dialog(
        self, title: str, *, include_secret: bool
    ) -> tuple[str, str, str, str, bytes | None] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        form = QFormLayout(dialog)
        label = QLineEdit("My identity")
        username = QLineEdit()
        username.setPlaceholderText("Public Nostr username")
        secret = QLineEdit()
        secret.setEchoMode(QLineEdit.EchoMode.Password)
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        confirm = QLineEdit()
        confirm.setEchoMode(QLineEdit.EchoMode.Password)
        avatar_path = QLineEdit()
        avatar_path.setReadOnly(True)
        avatar_button = QPushButton("SELECT IMAGE")
        avatar_row = QHBoxLayout()
        avatar_row.addWidget(avatar_path, 1)
        avatar_row.addWidget(avatar_button)

        def select_avatar() -> None:
            filename, _ = QFileDialog.getOpenFileName(
                dialog,
                "Select profile image",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if filename:
                avatar_path.setText(filename)

        avatar_button.clicked.connect(select_avatar)
        form.addRow("Local label", label)
        form.addRow("Public username", username)
        form.addRow("Profile image (optional)", avatar_row)
        if include_secret:
            form.addRow("Nostr secret", secret)
        form.addRow("New vault password", password)
        form.addRow("Confirm password", confirm)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if password.text() != confirm.text():
            QMessageBox.warning(self, "Passwords differ", "The vault passwords do not match.")
            return None
        try:
            avatar_png = normalize_avatar(avatar_path.text()) if avatar_path.text() else None
        except ValueError as error:
            QMessageBox.warning(self, "Invalid profile image", str(error))
            return None
        return label.text(), username.text(), password.text(), secret.text(), avatar_png


def normalize_avatar(path: str | Path) -> bytes:
    """Center-crop an image and normalize it to an exact 128x128 PNG."""
    image = QImage(str(path))
    if image.isNull():
        raise ValueError("The selected file is not a supported image.")
    side = min(image.width(), image.height())
    left = (image.width() - side) // 2
    top = (image.height() - side) // 2
    square = image.copy(left, top, side, side)
    normalized = square.scaled(
        128,
        128,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not normalized.save(buffer, "PNG"):
        raise ValueError("The profile image could not be converted to PNG.")
    buffer.close()
    return bytes(data)
