from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QIcon,
    QImage,
    QKeyEvent,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .attachment_types import guess_attachment_mime
from . import __release_label__
from .database import ClientDatabase
from .group_invite import create_group_invite, parse_group_invite
from .identity import UnlockedIdentity, normalize_avatar
from .idle_visualization import IdleVisualizationController
from .moderation import ModerationSyncWorker
from .models import Conversation
from .reactions import MESSAGE_REACTION_EMOJIS, REACTION_PREFIX, decode_reaction
from .resources import create_hud_icon
from .transport import NostrTransport
from .theme import CORAL, CYAN, LINE, MUTED, PANEL, TEXT, UI_SMALL_FONT_PX, VOID
from .widgets import (
    AvatarLabel,
    BrandMark,
    ConversationRow,
    CornerFrame,
    HudTelemetry,
    MessageBubble,
    MessageRow,
    RelayMeshView,
    clear_layout,
)

GROUP_CONTROL_PREFIX = "fsociety-group-control:"

CREATE_ACTION_STYLE = """
QPushButton {
    color: #4debf3;
    background-color: #101718;
    border: 1px solid #4debf3;
    font: 900 17px "Perfect DOS VGA 437 Win";
    padding: 0px;
}
QPushButton:hover {
    color: #d9fdff;
    background-color: #18343a;
    border: 2px solid #76f4fa;
}
QPushButton:pressed {
    color: #ffffff;
    background-color: #20515a;
    border: 2px solid #bdfbff;
}
"""


class NavRail(QFrame):
    section_selected = pyqtSignal(str)
    settings_requested = pyqtSignal()
    profile_requested = pyqtSignal()

    def __init__(
        self, username: str = "", avatar_png: bytes | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.expanded = False
        self.username = username
        self.avatar_png = avatar_png
        self.setFixedWidth(68)
        self.nav_layout = QVBoxLayout(self)
        self.nav_layout.setContentsMargins(11, 27, 11, 13)
        self.nav_layout.setSpacing(8)
        self.brand = BrandMark()
        self.brand.clicked.connect(self.toggle_expanded)
        self.nav_layout.addWidget(self.brand, alignment=Qt.AlignmentFlag.AlignHCenter)

        group = QButtonGroup(self)
        group.setExclusive(True)
        self.section_buttons: list[tuple[QPushButton, str, str]] = []
        for label, glyph, section, checked in (
            ("Messages", "▰", "messages", True),
            ("Contacts", "◎", "contacts", False),
            ("Communities", "⌁", "communities", False),
            ("Network", "◇", "network", False),
        ):
            button = QPushButton(glyph)
            button.setToolTip(label)
            button.setCheckable(True)
            button.setChecked(checked)
            button.setFixedSize(44, 42)
            button.setStyleSheet("font:600 16px 'Perfect DOS VGA 437 Win';")
            button.clicked.connect(
                lambda checked, selected_section=section: self.section_selected.emit(selected_section)
            )
            group.addButton(button)
            self.section_buttons.append((button, label, glyph))
            self.nav_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.nav_layout.addStretch(1)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setToolTip("Settings")
        self.settings_button.setFixedSize(44, 42)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.nav_layout.addWidget(self.settings_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.profile_button = QPushButton()
        self.profile_button.setToolTip("View and edit my profile")
        self.profile_button.setFixedSize(38, 38)
        self.profile_button.clicked.connect(self.profile_requested.emit)
        self.set_profile(username, avatar_png)
        self.nav_layout.addWidget(self.profile_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def toggle_expanded(self) -> None:
        self.expanded = not self.expanded
        width = 190 if self.expanded else 68
        button_width = 166 if self.expanded else 44
        self.setFixedWidth(width)
        self.nav_layout.setContentsMargins(
            11 if not self.expanded else 12, 27, 11 if not self.expanded else 12, 13
        )
        for button, label, glyph in self.section_buttons:
            button.setText(f"{glyph}   {label.upper()}" if self.expanded else glyph)
            button.setFixedSize(button_width, 42)
            button.setStyleSheet(
                "font:600 12px 'Perfect DOS VGA 437 Win';text-align:left;padding-left:14px;"
                if self.expanded
                else "font:600 16px 'Perfect DOS VGA 437 Win';"
            )
        self.settings_button.setText("⚙   SETTINGS" if self.expanded else "⚙")
        self.settings_button.setFixedSize(button_width, 42)
        self.settings_button.setStyleSheet(
            "font:600 12px 'Perfect DOS VGA 437 Win';text-align:left;padding-left:14px;"
            if self.expanded
            else "font:600 16px 'Perfect DOS VGA 437 Win';"
        )
        self._render_profile()

    def set_profile(self, username: str, avatar_png: bytes | None) -> None:
        self.username = username
        self.avatar_png = avatar_png
        self._render_profile()

    def _render_profile(self) -> None:
        self.profile_button.setFixedSize(166 if self.expanded else 38, 42 if self.expanded else 38)
        self.profile_button.setText(
            "PROFILE"
            if self.expanded
            else (self.username[:2] or "ME").upper()
        )
        self.profile_button.setIcon(QIcon())
        if self.avatar_png:
            pixmap = QPixmap()
            if pixmap.loadFromData(self.avatar_png):
                if not self.expanded:
                    self.profile_button.setText("")
                self.profile_button.setIcon(QIcon(pixmap))
                self.profile_button.setIconSize(
                    QSize(34, 34) if self.expanded else self.profile_button.size() - QSize(4, 4)
                )
        self.profile_button.setStyleSheet(
            f"font:600 {UI_SMALL_FONT_PX}px 'Perfect DOS VGA 437 Win';text-align:left;padding-left:8px;"
            if self.expanded
            else f"font:600 {UI_SMALL_FONT_PX}px 'Perfect DOS VGA 437 Win';"
        )


class ConversationSidebar(QFrame):
    conversation_selected = None

    def __init__(
        self,
        database: ClientDatabase,
        on_selected,
        on_new_chat=None,
        on_new_group=None,
        on_create_invite=None,
        on_join_invite=None,
        on_add_contact=None,
        on_view_profile=None,
        on_group_exit=None,
        on_remove_contact=None,
        on_toggle_contact_block=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.on_selected = on_selected
        self.on_view_profile = on_view_profile
        self.mode = "all"
        self.setObjectName("sidebar")
        self.setFixedWidth(390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(17, 28, 17, 12)
        brand_row = QHBoxLayout()
        brand = QLabel("fsociety")
        brand.setObjectName("brand")
        live = QLabel("NOSTR://LIVE")
        live.setObjectName("protocolLive")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        new_chat = QPushButton("+")
        new_chat.setObjectName("createAction")
        new_chat.setStyleSheet(CREATE_ACTION_STYLE)
        new_chat.setToolTip("Start encrypted chat by npub")
        new_chat.setFixedSize(34, 32)
        if on_new_chat is not None:
            new_chat.clicked.connect(on_new_chat)
        brand_row.addWidget(new_chat)
        new_group = QPushButton("G")
        new_group.setObjectName("createAction")
        new_group.setStyleSheet(CREATE_ACTION_STYLE)
        new_group.setToolTip("Create encrypted group/community")
        new_group.setFixedSize(34, 32)
        if on_new_group is not None:
            new_group.clicked.connect(on_new_group)
        brand_row.addWidget(new_group)
        brand_row.addWidget(live)
        header_layout.addLayout(brand_row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search encrypted chats")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        header_layout.addWidget(self.search)
        layout.addWidget(header)

        self.filter_row = QWidget()
        filter_layout = QHBoxLayout(self.filter_row)
        filter_layout.setContentsMargins(16, 0, 16, 10)
        filter_layout.setSpacing(4)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for label, mode in (("ALL", "all"), ("UNREAD", "unread"), ("GROUPS", "groups")):
            button = QPushButton(label)
            button.setObjectName("filter")
            button.setCheckable(True)
            button.setChecked(mode == "all")
            button.clicked.connect(lambda checked, selected_mode=mode: self.set_mode(selected_mode))
            self.filter_group.addButton(button)
            self.filter_buttons[mode] = button
            filter_layout.addWidget(button)
        filter_layout.addStretch(1)
        layout.addWidget(self.filter_row)

        self.group_actions = QFrame()
        self.group_actions.setObjectName("composerFrame")
        group_actions_layout = QVBoxLayout(self.group_actions)
        group_actions_layout.setContentsMargins(12, 10, 12, 10)
        group_title = QLabel("PRIVATE NIP-17 COMMUNITIES")
        group_title.setObjectName("sectionCode")
        group_help = QLabel(
            "Create a group with member npubs. Recipients see it after the first encrypted message."
        )
        group_help.setWordWrap(True)
        group_help.setObjectName("muted")
        create_group = QPushButton("CREATE ENCRYPTED GROUP")
        create_group.setObjectName("groupAction")
        create_group.setFixedHeight(38)
        if on_new_group is not None:
            create_group.clicked.connect(on_new_group)
        group_actions_layout.addWidget(group_title)
        group_actions_layout.addWidget(group_help)
        group_actions_layout.addWidget(create_group)
        create_invite = QPushButton("CREATE INVITE")
        join_invite = QPushButton("JOIN WITH INVITE")
        create_invite.setObjectName("groupAction")
        join_invite.setObjectName("groupAction")
        create_invite.setFixedHeight(38)
        join_invite.setFixedHeight(38)
        if on_create_invite is not None:
            create_invite.clicked.connect(on_create_invite)
        if on_join_invite is not None:
            join_invite.clicked.connect(on_join_invite)
        group_actions_layout.addWidget(create_invite)
        group_actions_layout.addWidget(join_invite)
        leave_group = QPushButton("LEAVE / DELETE GROUP")
        leave_group.setObjectName("groupAction")
        leave_group.setFixedHeight(38)
        leave_group.setToolTip("Creators can delete; other members can leave")
        if on_group_exit is not None:
            leave_group.clicked.connect(on_group_exit)
        group_actions_layout.addWidget(leave_group)
        layout.addWidget(self.group_actions)
        self.group_actions.hide()

        self.contact_actions = QFrame()
        self.contact_actions.setObjectName("composerFrame")
        contact_layout = QVBoxLayout(self.contact_actions)
        contact_layout.setContentsMargins(12, 10, 12, 10)
        contact_title = QLabel("ENCRYPTED CONTACTS")
        contact_title.setObjectName("sectionCode")
        contact_help = QLabel("Save an npub, resolve its Nostr profile, or start a private chat.")
        contact_help.setWordWrap(True)
        contact_help.setObjectName("muted")
        add_contact = QPushButton("ADD CONTACT BY NPUB")
        add_contact.setObjectName("send")
        if on_add_contact is not None:
            add_contact.clicked.connect(on_add_contact)
        remove_contact = QPushButton("REMOVE SELECTED CONTACT")
        remove_contact.setObjectName("groupAction")
        remove_contact.setFixedHeight(38)
        remove_contact.setToolTip(
            "Remove the selected user from Contacts; message history remains local"
        )
        if on_remove_contact is not None:
            remove_contact.clicked.connect(on_remove_contact)
        block_contact = QPushButton("BLOCK / UNBLOCK SELECTED USER")
        block_contact.setObjectName("danger")
        block_contact.setFixedHeight(38)
        block_contact.setToolTip(
            "Blocked users are discarded locally and remain available here for unblocking"
        )
        if on_toggle_contact_block is not None:
            block_contact.clicked.connect(on_toggle_contact_block)
        contact_layout.addWidget(contact_title)
        contact_layout.addWidget(contact_help)
        contact_layout.addWidget(add_contact)
        contact_layout.addWidget(remove_contact)
        contact_layout.addWidget(block_contact)
        layout.addWidget(self.contact_actions)
        self.contact_actions.hide()

        self.telemetry = HudTelemetry()
        self.telemetry.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.telemetry)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._item_double_clicked)
        layout.addWidget(self.list_widget, 1)
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.refresh()

    def show_section(self, section: str) -> None:
        if section == "messages":
            self.group_actions.hide()
            self.contact_actions.hide()
            self.filter_row.show()
            self.filter_buttons["all"].setChecked(True)
            self.search.setPlaceholderText("Search encrypted chats")
            self.set_mode("all")
        elif section == "contacts":
            self.group_actions.hide()
            self.contact_actions.show()
            self.filter_row.hide()
            self.search.setPlaceholderText("Search contacts")
            self.set_mode("contacts")
        elif section == "communities":
            self.contact_actions.hide()
            self.filter_row.hide()
            self.group_actions.show()
            self.search.setPlaceholderText("Search communities")
            self.set_mode("groups")
    def refresh(self, *, select_first: bool = True) -> None:
        selected_id = None
        current = self.list_widget.currentItem()
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)
        conversations = self.database.list_conversations(query=self.search.text(), mode=self.mode)
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        selected_item = None
        for conversation in conversations:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, conversation)
            item.setSizeHint(ConversationRow(conversation).sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, ConversationRow(conversation))
            if conversation.id == selected_id:
                selected_item = item
        if selected_item is not None:
            # Restoring the same logical selection is bookkeeping, not a user
            # navigation event. Keep signals blocked so profile/relay refreshes
            # do not tear down and recreate the entire chat/media widget tree.
            self.list_widget.setCurrentItem(selected_item)
            self.list_widget.blockSignals(False)
        else:
            self.list_widget.blockSignals(False)
        if select_first and selected_item is None and self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def select_conversation(self, conversation_id: str) -> None:
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == conversation_id:
                self.list_widget.setCurrentItem(item)
                return

    def _selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        conversation = current.data(Qt.ItemDataRole.UserRole + 1)
        self.on_selected(conversation)

    def _item_double_clicked(self, item: QListWidgetItem) -> None:
        conversation = item.data(Qt.ItemDataRole.UserRole + 1)
        if (
            self.mode == "contacts"
            and conversation.peer_pubkey
            and self.on_view_profile is not None
        ):
            self.on_view_profile(conversation.peer_pubkey)


class MessageComposer(QTextEdit):
    image_pasted = pyqtSignal(object)
    files_dropped = pyqtSignal(object)
    submit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def local_files(source: QMimeData) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        if not source.hasUrls():
            return paths
        for url in source.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            key = str(path.absolute()).casefold()
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            paths.append(path)
        return paths

    def _set_drop_active(self, active: bool) -> None:
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.isEnabled() and self.local_files(event.mimeData()):
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_active(False)
        paths = self.local_files(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.submit_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasImage():
            image = source.imageData()
            self.image_pasted.emit(image if isinstance(image, QImage) else QImage(image))
            return
        super().insertFromMimeData(source)


class AttachmentDropDialog(QDialog):
    def __init__(self, paths: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm attachment drop")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        heading = QLabel(f"QUEUE {len(paths)} ENCRYPTED ATTACHMENT(S)")
        heading.setObjectName("sectionCode")
        layout.addWidget(heading)
        files = QListWidget()
        for path in paths:
            try:
                size = path.stat().st_size / 1024
                files.addItem(f"{path.name}  ·  {size:.1f} KB")
            except OSError:
                files.addItem(f"{path.name}  ·  inaccessible")
        files.setMaximumHeight(180)
        layout.addWidget(files)
        layout.addWidget(QLabel("Optional caption (applies to every dropped file)"))
        self.caption = QLineEdit()
        self.caption.setMaxLength(1000)
        self.caption.setPlaceholderText("Add a caption")
        layout.addWidget(self.caption)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Queue attachments")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ProfileDialog(QDialog):
    def __init__(
        self,
        database: ClientDatabase,
        pubkey: str,
        own_identity: UnlockedIdentity | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.pubkey = pubkey
        self.own_identity = own_identity
        self.is_own = own_identity is not None and own_identity.record.pubkey_hex == pubkey
        self.avatar_png = own_identity.record.avatar_png if self.is_own else None
        self.start_message = False
        self.contact_changed = False
        self.block_changed = False
        profile = database.get_profile(pubkey) or {}
        if not self.avatar_png:
            self.avatar_png = profile.get("picture_blob") or None
        try:
            from nostr_sdk import PublicKey

            self.npub = PublicKey.parse(pubkey).to_bech32()
        except Exception:
            self.npub = pubkey

        self.setWindowTitle("My fsociety profile" if self.is_own else "Nostr profile")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        heading = QLabel("MY PUBLIC PROFILE" if self.is_own else "CONTACT PROFILE")
        heading.setObjectName("sectionCode")
        layout.addWidget(heading)
        self.avatar_layout = QHBoxLayout()
        layout.addLayout(self.avatar_layout)
        self._render_avatar()

        form = QFormLayout()
        if self.is_own:
            self.username = QLineEdit(own_identity.record.username)
            form.addRow("Public username", self.username)
        else:
            display = str(
                profile.get("nickname")
                or profile.get("display_name")
                or profile.get("name")
                or f"npub:{pubkey[:16]}…"
            )
            form.addRow("Display name", QLabel(display))
            self.nickname = QLineEdit(str(profile.get("nickname") or ""))
            self.nickname.setPlaceholderText("Optional local nickname")
            form.addRow("Local nickname", self.nickname)
            about = QLabel(str(profile.get("about") or "No profile description published."))
            about.setWordWrap(True)
            form.addRow("About", about)
            form.addRow("NIP-05", QLabel(str(profile.get("nip05") or "Not published")))
        npub_label = QLabel(self.npub)
        npub_label.setWordWrap(True)
        npub_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Public key", npub_label)
        layout.addLayout(form)

        copy = QPushButton("COPY PUBLIC KEY (NPUB)")
        copy.setObjectName("createAction")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.npub))
        layout.addWidget(copy)

        actions = QHBoxLayout()
        if self.is_own:
            choose = QPushButton("CHANGE PROFILE IMAGE")
            remove = QPushButton("REMOVE IMAGE")
            choose.clicked.connect(self._choose_avatar)
            remove.clicked.connect(self._remove_avatar)
            actions.addWidget(choose)
            actions.addWidget(remove)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            actions.addWidget(buttons)
        else:
            locally_blocked = database.is_user_blocked(pubkey)
            contact = QPushButton(
                "REMOVE CONTACT" if database.is_contact(pubkey) else "ADD CONTACT"
            )
            contact.clicked.connect(self._toggle_contact)
            contact.setEnabled(not locally_blocked)
            if locally_blocked:
                contact.setToolTip("Unblock this user before changing contact membership")
            block = QPushButton(
                "UNBLOCK USER" if locally_blocked else "BLOCK USER"
            )
            block.setObjectName("danger")
            block.clicked.connect(self._toggle_block)
            message = QPushButton("MESSAGE")
            message.setObjectName("send")
            message.clicked.connect(self._message)
            message.setEnabled(not locally_blocked)
            close = QPushButton("CLOSE")
            close.clicked.connect(self.accept)
            actions.addWidget(contact)
            actions.addWidget(block)
            actions.addWidget(message)
            actions.addWidget(close)
        layout.addLayout(actions)

    def _render_avatar(self) -> None:
        clear_layout(self.avatar_layout)
        name = (
            self.own_identity.record.username
            if self.is_own and self.own_identity is not None
            else self.npub[:2]
        )
        self.avatar_layout.addWidget(
            AvatarLabel(name[:2].upper(), "cyan", 96, self.avatar_png),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

    def _choose_avatar(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select profile image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not filename:
            return
        try:
            self.avatar_png = normalize_avatar(filename)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid profile image", str(error))
            return
        self._render_avatar()

    def _remove_avatar(self) -> None:
        self.avatar_png = None
        self._render_avatar()

    def _toggle_contact(self) -> None:
        if self.database.is_contact(self.pubkey):
            self.database.remove_contact(self.pubkey)
        else:
            self.database.add_contact(self.pubkey, self.nickname.text())
        self.contact_changed = True
        self.accept()

    def _message(self) -> None:
        if self.database.is_contact(self.pubkey):
            self.database.set_contact_nickname(self.pubkey, self.nickname.text())
        self.start_message = True
        self.accept()

    def _toggle_block(self) -> None:
        blocked = self.database.is_user_blocked(self.pubkey)
        if not blocked:
            answer = QMessageBox.question(
                self,
                "Block user",
                "Block this user locally? Their messages and posts will be hidden, "
                "and new direct messages from this key will be ignored.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.database.set_user_blocked(self.pubkey, not blocked)
        self.block_changed = True
        self.accept()


class GroupSettingsDialog(QDialog):
    def __init__(
        self,
        database: ClientDatabase,
        conversation: Conversation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.conversation = conversation
        self.setWindowTitle(f"{conversation.display_name} — group settings")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        heading = QLabel("GROUP DISPLAY SETTINGS  //  LOCAL")
        heading.setObjectName("sectionCode")
        layout.addWidget(heading)
        name = QLabel(conversation.display_name)
        name.setStyleSheet("font-weight:700;")
        layout.addWidget(name)
        self.show_images = QCheckBox("Show images inline in this group")
        self.show_images.setChecked(
            database.get_setting(f"group.inline_images:{conversation.id}", "true")
            == "true"
        )
        self.show_videos = QCheckBox("Show video launchers in this group")
        self.show_videos.setChecked(
            database.get_setting(f"group.inline_videos:{conversation.id}", "true")
            == "true"
        )
        layout.addWidget(self.show_images)
        layout.addWidget(self.show_videos)
        notice = QLabel(
            "These preferences affect only this local fsociety identity. Hidden media remains "
            "an encrypted attachment and its filename and verification details stay visible."
        )
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        layout.addWidget(notice)
        release = QLabel(f"FSOCIETY CLIENT  //  {__release_label__.upper()}")
        release.setObjectName("sectionCode")
        layout.addWidget(release)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        group_id = self.conversation.id
        self.database.set_setting(
            f"group.inline_images:{group_id}",
            "true" if self.show_images.isChecked() else "false",
        )
        self.database.set_setting(
            f"group.inline_videos:{group_id}",
            "true" if self.show_videos.isChecked() else "false",
        )
        self.accept()


class ChatPane(QWidget):
    INITIAL_MESSAGE_LIMIT = 100
    MESSAGE_PAGE_SIZE = 50
    MAX_RENDERED_MESSAGES = 250

    def __init__(
        self,
        database: ClientDatabase,
        on_message_sent,
        send_direct=None,
        send_attachment=None,
        send_group=None,
        send_group_attachment=None,
        send_reaction=None,
        view_profile=None,
        group_exit=None,
        delete_conversation=None,
        own_pubkey: str = "",
        own_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.on_message_sent = on_message_sent
        self.send_direct = send_direct
        self.send_attachment = send_attachment
        self.send_group = send_group
        self.send_group_attachment = send_group_attachment
        self.send_reaction = send_reaction
        self.view_profile = view_profile
        self.group_exit = group_exit
        self.delete_conversation = delete_conversation
        self.own_pubkey = own_pubkey
        self.own_name = own_name
        self.loaded_messages = []
        self.message_rows: dict[int, MessageRow] = {}
        self.has_older_messages = False
        self.has_newer_messages = False
        self.pending_new_messages = 0
        self.loading_older_messages = False
        self.search_active = False
        self.message_font_size = max(
            11,
            min(
                20,
                int(
                    database.get_setting(
                        "messages.font_size",
                        database.get_setting("ui.font_size", "18"),
                    )
                ),
            ),
        )
        self.conversation: Conversation | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("chatHeader")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 10)
        self.avatar_holder = QVBoxLayout()
        header_layout.addLayout(self.avatar_holder)
        identity = QVBoxLayout()
        identity.setSpacing(3)
        self.name = QLabel("Select a conversation")
        self.name.setStyleSheet("font-weight:600;")
        self.presence = QLabel("OFFLINE-FIRST")
        self.presence.setObjectName("presence")
        identity.addWidget(self.name)
        identity.addWidget(self.presence)
        header_layout.addLayout(identity)
        header_layout.addStretch(1)
        cipher = QLabel("CIPHER  NIP-44")
        cipher.setStyleSheet(
            f"color:{CYAN};border:1px solid {LINE};padding:6px 8px;"
            f"font:{UI_SMALL_FONT_PX}px 'Perfect DOS VGA 437 Win';"
        )
        header_layout.addWidget(cipher)
        for icon_name, tip, handler in (
            ("search", "Search conversation", self._search_conversation),
            ("info", "Conversation details", self._show_details),
            ("more", "More actions", self._show_actions),
        ):
            button = QPushButton()
            button.setIcon(create_hud_icon(icon_name))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(tip)
            button.setFixedSize(36, 36)
            button.clicked.connect(handler)
            header_layout.addWidget(button)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_host = QWidget()
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(38, 24, 38, 20)
        self.message_layout.setSpacing(5)
        self.scroll.setWidget(self.message_host)
        self.bottom_scroll_generation = 0
        self.bottom_scroll_pending = False
        self.scroll.verticalScrollBar().rangeChanged.connect(self._scroll_range_changed)
        self.scroll.verticalScrollBar().valueChanged.connect(self._scroll_value_changed)
        layout.addWidget(self.scroll, 1)

        self.new_messages = QPushButton("↓ RETURN TO LATEST")
        self.new_messages.setObjectName("createAction")
        self.new_messages.setFixedHeight(32)
        self.new_messages.clicked.connect(self._return_to_latest)
        self.new_messages.hide()
        layout.addWidget(self.new_messages)

        compose_outer = QWidget()
        compose_outer_layout = QVBoxLayout(compose_outer)
        compose_outer_layout.setContentsMargins(18, 11, 18, 18)
        composer = QFrame()
        composer.setObjectName("composerFrame")
        compose_layout = QHBoxLayout(composer)
        compose_layout.setContentsMargins(6, 5, 6, 5)
        attach = QPushButton("＋")
        attach.setToolTip("Attach via Blossom")
        attach.setFixedSize(38, 38)
        attach.clicked.connect(self._attach_file)
        emotes = QPushButton("😎")
        emotes.setToolTip("Insert an emote")
        emotes.setFixedSize(38, 38)
        emotes.clicked.connect(self._show_emotes)
        self.input = MessageComposer()
        self.input.image_pasted.connect(self._paste_image)
        self.input.files_dropped.connect(self._drop_files)
        self.input.submit_requested.connect(self._send)
        self.input.setPlaceholderText("Select a conversation")
        self.input.setFixedHeight(42)
        self.input.setFrameStyle(QFrame.Shape.NoFrame)
        self._style_composer()
        self.send = QPushButton("↑")
        self.send.setObjectName("send")
        self.send.setToolTip("Publish message")
        self.send.setFixedSize(42, 38)
        self.send.clicked.connect(self._send)
        compose_layout.addWidget(attach)
        compose_layout.addWidget(emotes)
        compose_layout.addWidget(self.input, 1)
        compose_layout.addWidget(self.send)
        compose_outer_layout.addWidget(composer)
        layout.addWidget(compose_outer)

    def _style_composer(self) -> None:
        self.input.setStyleSheet(
            "QTextEdit{border:0;background:transparent;padding:9px 5px;"
            f"font-size:{self.message_font_size}px;"
            "}QTextEdit[dropActive=\"true\"]{border:1px dashed #4debf3;"
            "background:#102326;}"
        )

    def apply_message_font_size(self) -> None:
        self.message_font_size = max(
            11,
            min(20, int(self.database.get_setting("messages.font_size", "18"))),
        )
        self._style_composer()
        if self.conversation is not None:
            stay_at_bottom = self.is_near_bottom()
            self.show_conversation(
                self.conversation,
                scroll_to_latest=stay_at_bottom,
                force_reload=True,
            )

    def show_conversation(
        self,
        conversation: Conversation,
        scroll_to_latest: bool = True,
        force_reload: bool = False,
    ) -> None:
        changed = self.conversation is None or self.conversation.id != conversation.id
        self.conversation = conversation
        self.name.setText(conversation.display_name)
        self.presence.setText(f"● {conversation.status.upper()}")
        self.input.setPlaceholderText(f"Message {conversation.display_name}")
        self.input.setEnabled(True)
        self.send.setEnabled(True)
        clear_layout(self.avatar_holder)
        self.avatar_holder.addWidget(AvatarLabel(conversation.initials, conversation.accent, 42))
        if changed or force_reload or self.search_active:
            self._load_latest_messages(scroll_to_latest=scroll_to_latest)
        else:
            self._sync_visible_messages(scroll_to_latest=scroll_to_latest)

    def _load_latest_messages(self, scroll_to_latest: bool = True) -> None:
        if self.conversation is None:
            return
        self.search_active = False
        self.loaded_messages = self.database.list_recent_messages(
            self.conversation.id, self.INITIAL_MESSAGE_LIMIT
        )
        self.has_older_messages = len(self.loaded_messages) >= self.INITIAL_MESSAGE_LIMIT
        self.has_newer_messages = False
        self.pending_new_messages = 0
        self._update_new_messages_button()
        self._render_messages(self.loaded_messages, scroll_to_latest=scroll_to_latest)

    def _sync_visible_messages(self, scroll_to_latest: bool) -> None:
        if self.conversation is None:
            return
        if self.has_newer_messages and scroll_to_latest:
            self._load_latest_messages(scroll_to_latest=True)
            return
        if not self.loaded_messages:
            self._load_latest_messages(scroll_to_latest=scroll_to_latest)
            return
        recent = self.database.list_recent_messages(
            self.conversation.id, self.INITIAL_MESSAGE_LIMIT
        )
        loaded_ids = {message.id for message in self.loaded_messages}
        new_messages = [message for message in recent if message.id not in loaded_ids]
        if not new_messages:
            if scroll_to_latest:
                self._arm_bottom_scroll()
            return
        if not scroll_to_latest and not self.is_near_bottom():
            self.has_newer_messages = True
            self.pending_new_messages += len(new_messages)
            self._update_new_messages_button()
            return
        newest_key = (
            self.loaded_messages[-1].sent_at,
            self.loaded_messages[-1].id,
        )
        if all((message.sent_at, message.id) > newest_key for message in new_messages):
            self._append_messages(new_messages)
        else:
            merged = {message.id: message for message in self.loaded_messages}
            merged.update({message.id: message for message in new_messages})
            self.loaded_messages = sorted(
                merged.values(), key=lambda message: (message.sent_at, message.id)
            )[-self.MAX_RENDERED_MESSAGES :]
            self.has_older_messages = True
            self._render_messages(self.loaded_messages, scroll_to_latest=True)
            return
        self._arm_bottom_scroll()

    def update_message_delivery_state(self, message_id: int, state: str) -> bool:
        for bubble in self.message_host.findChildren(MessageBubble):
            if bubble.message_id == message_id:
                bubble.set_delivery_state(state)
                return True
        return False

    def refresh_message_reactions(self, message_id: int) -> bool:
        row = self.message_rows.get(message_id)
        if row is None:
            return False
        bubble = row.findChild(MessageBubble)
        if bubble is None:
            return False
        stay_at_bottom = self.is_near_bottom()
        scroll_value = self.scroll.verticalScrollBar().value()
        bubble.set_reactions(
            self.database.list_message_reactions(message_id), self.own_pubkey
        )
        bubble.updateGeometry()
        row.updateGeometry()
        if stay_at_bottom:
            self._arm_bottom_scroll()
        else:
            QTimer.singleShot(
                0, lambda: self.scroll.verticalScrollBar().setValue(scroll_value)
            )
        return True

    def _render_messages(
        self,
        messages,
        banner: str = "TODAY  ·  END-TO-END ENCRYPTED",
        scroll_to_latest: bool = True,
    ) -> None:
        clear_layout(self.message_layout)
        self.message_rows.clear()
        date = QLabel(banner)
        date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date.setObjectName("sectionCode")
        self.message_layout.addWidget(date)
        self.message_layout.addSpacing(8)
        show_images = True
        show_videos = True
        if self.conversation is not None and self.conversation.kind == "group":
            show_images = (
                self.database.get_setting(
                    f"group.inline_images:{self.conversation.id}", "true"
                )
                == "true"
            )
            show_videos = (
                self.database.get_setting(
                    f"group.inline_videos:{self.conversation.id}", "true"
                )
                == "true"
            )
        for message in messages:
            row = self._create_message_row(message, show_images, show_videos)
            self.message_layout.addWidget(row)
        if not messages:
            empty = QLabel("NO MATCHING MESSAGES")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("muted")
            self.message_layout.addWidget(empty)
        self.message_layout.addStretch(1)
        if scroll_to_latest:
            self._arm_bottom_scroll()

    def _media_preferences(self) -> tuple[bool, bool]:
        show_images = True
        show_videos = True
        if self.conversation is not None and self.conversation.kind == "group":
            show_images = (
                self.database.get_setting(
                    f"group.inline_images:{self.conversation.id}", "true"
                )
                == "true"
            )
            show_videos = (
                self.database.get_setting(
                    f"group.inline_videos:{self.conversation.id}", "true"
                )
                == "true"
            )
        return show_images, show_videos

    def _create_message_row(
        self, message, show_images: bool | None = None, show_videos: bool | None = None
    ) -> MessageRow:
        if show_images is None or show_videos is None:
            show_images, show_videos = self._media_preferences()
        row = MessageRow(
            message,
            self.conversation is not None and self.conversation.kind == "group",
            self.own_pubkey,
            self.own_name,
            bool(show_images),
            bool(show_videos),
            self.message_font_size,
            self.database.list_message_reactions(message.id),
        )
        row.setToolTip("Right-click for message actions")
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda position, selected=message, widget=row: self._show_message_actions(
                selected, widget.mapToGlobal(position)
            )
        )
        self.message_rows[message.id] = row
        return row

    def _remove_rendered_message(self, message) -> None:
        row = self.message_rows.pop(message.id, None)
        if row is not None:
            self.message_layout.removeWidget(row)
            row.deleteLater()

    def _append_messages(self, messages) -> None:
        if not messages:
            return
        for message in messages:
            self.loaded_messages.append(message)
            self.message_layout.insertWidget(
                max(0, self.message_layout.count() - 1),
                self._create_message_row(message),
            )
        overflow = len(self.loaded_messages) - self.MAX_RENDERED_MESSAGES
        if overflow > 0:
            removed = self.loaded_messages[:overflow]
            self.loaded_messages = self.loaded_messages[overflow:]
            for message in removed:
                self._remove_rendered_message(message)
            self.has_older_messages = True

    def _load_older_messages(self) -> None:
        if (
            self.loading_older_messages
            or self.search_active
            or not self.has_older_messages
            or not self.loaded_messages
            or self.conversation is None
        ):
            return
        self.loading_older_messages = True
        oldest = self.loaded_messages[0]
        anchor = self.message_rows.get(oldest.id)
        bar = self.scroll.verticalScrollBar()
        old_value = bar.value()
        old_anchor_y = anchor.mapTo(self.message_host, QPoint(0, 0)).y() if anchor else 0
        page = self.database.list_messages_before(
            self.conversation.id,
            oldest.sent_at,
            oldest.id,
            self.MESSAGE_PAGE_SIZE,
        )
        if not page:
            self.has_older_messages = False
            self.loading_older_messages = False
            return
        overflow = max(
            0, len(self.loaded_messages) + len(page) - self.MAX_RENDERED_MESSAGES
        )
        if overflow:
            removed = self.loaded_messages[-overflow:]
            self.loaded_messages = self.loaded_messages[:-overflow]
            for message in removed:
                self._remove_rendered_message(message)
            self.has_newer_messages = True
            self._update_new_messages_button()
        for message in reversed(page):
            self.message_layout.insertWidget(2, self._create_message_row(message))
        self.loaded_messages = page + self.loaded_messages
        self.has_older_messages = len(page) >= self.MESSAGE_PAGE_SIZE
        self.message_layout.activate()

        def preserve_anchor() -> None:
            current_anchor = self.message_rows.get(oldest.id)
            if current_anchor is not None:
                new_y = current_anchor.mapTo(self.message_host, QPoint(0, 0)).y()
                bar.setValue(old_value + max(0, new_y - old_anchor_y))
            self.loading_older_messages = False

        QTimer.singleShot(0, preserve_anchor)

    def _scroll_value_changed(self, value: int) -> None:
        if value <= 24 and not self.bottom_scroll_pending:
            self._load_older_messages()

    def _update_new_messages_button(self) -> None:
        if not self.has_newer_messages:
            self.new_messages.hide()
            return
        self.new_messages.setText(
            f"↓ {self.pending_new_messages} NEW MESSAGES"
            if self.pending_new_messages
            else "↓ RETURN TO LATEST"
        )
        self.new_messages.show()

    def _return_to_latest(self) -> None:
        self._load_latest_messages(scroll_to_latest=True)

    def _show_message_actions(self, message, global_position) -> None:
        menu = QMenu(self.window())
        reaction_menu = menu.addMenu("React to message")
        message_ref = self.database.message_reference(message.id)
        picker = QWidget()
        picker.setObjectName("reactionPicker")
        picker_layout = QGridLayout(picker)
        picker_layout.setContentsMargins(7, 7, 7, 7)
        picker_layout.setHorizontalSpacing(5)
        picker_layout.setVerticalSpacing(5)

        def choose_reaction(emoji: str, active: bool) -> None:
            reaction_menu.close()
            menu.close()
            if self.send_reaction is None or self.conversation is None:
                return
            conversation = self.conversation
            QTimer.singleShot(
                0,
                lambda: self.send_reaction(
                    message.id, conversation, emoji, active
                ),
            )

        for index, emoji in enumerate(MESSAGE_REACTION_EMOJIS):
            selected = self.database.has_message_reaction(
                message.id, self.own_pubkey, emoji
            )
            button = QPushButton(emoji)
            button.setFixedSize(42, 38)
            button.setToolTip(
                f"{'Remove' if selected else 'Add'} {emoji} reaction"
            )
            button.setEnabled(bool(message_ref) and message.direction != "system")
            button.setStyleSheet(
                "QPushButton{font-family:'Segoe UI Emoji';font-size:20px;"
                f"color:{TEXT};background:"
                + ("#392126" if selected else "#101b1e")
                + ";border:1px solid "
                + (CORAL if selected else LINE)
                + ";padding:0;}QPushButton:hover{border:1px solid "
                + CYAN
                + ";background:#183035;}"
            )
            button.clicked.connect(
                lambda checked=False, value=emoji, active=not selected: choose_reaction(
                    value, active
                )
            )
            picker_layout.addWidget(button, index // 4, index % 4)
        picker_action = QWidgetAction(reaction_menu)
        picker_action.setDefaultWidget(picker)
        reaction_menu.addAction(picker_action)
        if not message_ref:
            reaction_menu.setToolTipsVisible(True)
            reaction_menu.setToolTip(
                "Reactions are available after a message has a stable relay reference."
            )
        menu.addSeparator()
        copy_action = menu.addAction("Copy message text")
        hide_action = menu.addAction("Hide message locally")
        selected = menu.exec(global_position)
        if selected == copy_action:
            QApplication.clipboard().setText(message.content)
            return
        if selected != hide_action:
            return
        answer = QMessageBox.question(
            self.window(),
            "Hide message locally",
            "Hide this message on this device? This does not delete an event "
            "already published to Nostr or an attachment stored by Blossom. "
            "The message will remain hidden after relay synchronization.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.database.hide_message_locally(message.id) and self.conversation is not None:
            self.on_message_sent(self.conversation.id)
            self.show_conversation(
                self.conversation,
                scroll_to_latest=self.is_near_bottom(),
                force_reload=True,
            )

    def _search_conversation(self) -> None:
        if self.conversation is None:
            return
        query, accepted = QInputDialog.getText(
            self.window(),
            "Search conversation",
            f"Search messages in {self.conversation.display_name}:",
        )
        if not accepted:
            return
        if query.strip():
            messages = self.database.search_messages(
                self.conversation.id, query, self.MAX_RENDERED_MESSAGES
            )
            self.search_active = True
            self.loaded_messages = messages
            self.has_older_messages = False
            self.has_newer_messages = False
            self.pending_new_messages = 0
            self._update_new_messages_button()
            self._render_messages(
                messages,
                f"SEARCH RESULTS  ·  NEWEST {self.MAX_RENDERED_MESSAGES} MAX  ·  {query.upper()}",
                scroll_to_latest=False,
            )
        else:
            self._load_latest_messages(scroll_to_latest=True)

    def _show_emotes(self) -> None:
        menu = QMenu(self.window())
        panel = QWidget(menu)
        grid = QGridLayout(panel)
        grid.setContentsMargins(7, 7, 7, 7)
        grid.setSpacing(2)
        emotes = (
            "😀", "😃", "😄", "😁", "😆", "😂", "🤣", "😊",
            "😎", "🤩", "🥳", "😉", "😍", "🥰", "😘", "😋",
            "🤔", "🤨", "😐", "😑", "🙄", "😬", "🤐", "🤫",
            "😢", "😭", "😤", "😡", "🤯", "😱", "😨", "💀",
            "👍", "👎", "👏", "🙌", "🤝", "💪", "✌️", "🤘",
            "❤️", "💔", "🔥", "✨", "🎉", "💥", "💯", "👀",
            "👻", "🤖", "👽", "💩", "✅", "❌", "⚠️", "🔒",
        )
        for index, emote in enumerate(emotes):
            button = QPushButton(emote)
            button.setFixedSize(34, 32)
            button.setStyleSheet("font-size:18px;padding:2px;")
            button.clicked.connect(
                lambda checked=False, value=emote: self._insert_emote(value, menu)
            )
            grid.addWidget(button, index // 8, index % 8)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        menu.exec(QCursor.pos())

    def _insert_emote(self, emote: str, menu: QMenu | None = None) -> None:
        cursor = self.input.textCursor()
        cursor.insertText(emote)
        self.input.setTextCursor(cursor)
        self.input.setFocus()
        if menu is not None:
            menu.close()

    def _show_details(self) -> None:
        if self.conversation is None:
            return
        muted = self.database.get_setting(f"muted:{self.conversation.id}", "false") == "true"
        group_details = ""
        if self.conversation.kind == "group":
            members = self.database.group_members(self.conversation.id)
            member_lines = "\n".join(f"  {member[:24]}…" for member in members)
            group_details = f"\nMembers stored locally: {len(members) + 1}\n{member_lines}\n"
        QMessageBox.information(
            self.window(),
            "Conversation details",
            f"Name: {self.conversation.display_name}\n"
            f"Local ID: {self.conversation.id}\n"
            f"Type: {self.conversation.kind}\n"
            f"Status: {self.conversation.status}\n"
            f"Muted: {'yes' if muted else 'no'}\n\n"
            f"{group_details}"
            "Direct and group identities are Nostr public keys; fsociety blocks affect only this client.",
        )

    def _show_actions(self) -> None:
        if self.conversation is None:
            return
        menu = QMenu(self.window())
        copy_action = menu.addAction("Copy conversation ID")
        profile_action = (
            menu.addAction("View contact profile")
            if self.conversation.peer_pubkey and self.view_profile is not None
            else None
        )
        member_profile_action = (
            menu.addAction("View group member profile")
            if self.conversation.kind == "group" and self.view_profile is not None
            else None
        )
        group_settings_action = (
            menu.addAction("Group settings")
            if self.conversation.kind == "group"
            else None
        )
        group_exit_action = (
            menu.addAction("Leave or delete group")
            if self.conversation.kind == "group" and self.group_exit is not None
            else None
        )
        delete_conversation_action = (
            menu.addAction("Delete conversation locally")
            if self.conversation.kind == "direct" and self.delete_conversation is not None
            else None
        )
        mark_read_action = menu.addAction("Mark as read")
        muted_key = f"muted:{self.conversation.id}"
        is_muted = self.database.get_setting(muted_key, "false") == "true"
        mute_action = menu.addAction("Unmute conversation" if is_muted else "Mute conversation")
        selected = menu.exec(QCursor.pos())
        if selected == copy_action:
            QApplication.clipboard().setText(self.conversation.id)
        elif profile_action is not None and selected == profile_action:
            self.view_profile(self.conversation.peer_pubkey)
        elif member_profile_action is not None and selected == member_profile_action:
            members = self.database.group_members(self.conversation.id)
            if members:
                labels: list[str] = []
                pubkeys: list[str] = []
                for pubkey in members:
                    profile = self.database.get_profile(pubkey) or {}
                    name = str(
                        profile.get("nickname")
                        or profile.get("display_name")
                        or profile.get("name")
                        or f"npub:{pubkey[:16]}…"
                    )
                    labels.append(f"{name}  ·  {pubkey[:16]}…")
                    pubkeys.append(pubkey)
                choice, accepted = QInputDialog.getItem(
                    self.window(), "Group member profile", "Member:", labels, 0, False
                )
                if accepted:
                    self.view_profile(pubkeys[labels.index(choice)])
        elif group_settings_action is not None and selected == group_settings_action:
            if GroupSettingsDialog(
                self.database, self.conversation, self.window()
            ).exec() == QDialog.DialogCode.Accepted:
                self.show_conversation(self.conversation, force_reload=True)
        elif group_exit_action is not None and selected == group_exit_action:
            self.group_exit(self.conversation)
        elif (
            delete_conversation_action is not None
            and selected == delete_conversation_action
        ):
            self.delete_conversation(self.conversation)
        elif selected == mark_read_action:
            self.database.mark_read(self.conversation.id)
            self.on_message_sent(self.conversation.id)
        elif selected == mute_action:
            self.database.set_setting(muted_key, "false" if is_muted else "true")
            self.presence.setText(
                f"● {self.conversation.status.upper()}"
                + ("  ·  MUTED" if not is_muted else "")
            )

    def _attach_file(self) -> None:
        if self.conversation is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self.window(),
            "Select an encrypted attachment",
            "",
            "Supported files (*.png *.jpg *.jpeg *.gif *.webp *.mp4 *.m4v *.mov *.webm *.zip *.rar);;"
            "Archives (*.zip *.rar);;"
            "Images (*.png *.jpg *.jpeg *.gif *.webp);;"
            "Videos (*.mp4 *.m4v *.mov *.webm);;All files (*.*)",
        )
        if not filename:
            return
        self._queue_attachment(Path(filename))

    def _drop_files(self, paths: list[Path]) -> None:
        if self.conversation is None:
            QMessageBox.information(
                self.window(), "No conversation", "Select a conversation before dropping files."
            )
            return
        clean_paths = list(dict.fromkeys(path for path in paths if path.is_file()))[:20]
        if not clean_paths:
            QMessageBox.warning(
                self.window(), "Unsupported drop", "The drop did not contain readable files."
            )
            return
        dialog = AttachmentDropDialog(clean_paths, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        caption = dialog.caption.text().strip()
        for path in clean_paths:
            self._queue_attachment(path, caption)

    def _paste_image(self, image: QImage) -> None:
        if self.conversation is None or image.isNull():
            return
        attachments = self.database.path.parent / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        filename = (
            f"pasted-image-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.png"
        )
        path = attachments / filename
        if not image.save(str(path), "PNG"):
            QMessageBox.warning(
                self.window(), "Paste failed", "The clipboard image could not be saved."
            )
            return
        self._queue_attachment(path)

    def _queue_attachment(self, path: Path, caption: str = "") -> None:
        if self.conversation is None:
            return
        try:
            if not path.is_file():
                raise OSError("The selected path is not a file.")
            size = path.stat().st_size
            if size <= 0:
                raise OSError("Empty files cannot be attached.")
            with path.open("rb"):
                pass
        except OSError as error:
            QMessageBox.warning(self.window(), "Attachment unavailable", str(error))
            return
        max_megabytes = int(self.database.get_setting("uploads.max_mb", "100"))
        mime_type = guess_attachment_mime(path.name)
        if mime_type.startswith("video/"):
            video_limit = min(
                30, int(self.database.get_setting("uploads.video_max_mb", "30"))
            )
            if size > video_limit * 1024 * 1024:
                QMessageBox.warning(
                    self.window(),
                    "Video too large",
                    f"Embedded videos are limited to {video_limit} MB. "
                    "Compress or trim this video and try again.",
                )
                return
        if size > max_megabytes * 1024 * 1024:
            QMessageBox.warning(
                self.window(),
                "Attachment too large",
                f"The configured upload limit is {max_megabytes} MB.",
            )
            return
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        attachment_details = (
            f"📎 {path.name}\n"
            f"{size / 1024:.1f} KB · SHA-256 {digest.hexdigest()[:16]}…\n"
            "Encrypted Blossom attachment"
        )
        content = f"{caption}\n{attachment_details}" if caption else attachment_details
        if self.conversation.kind == "group" and self.send_group_attachment is not None:
            self.send_group_attachment(self.conversation, str(path), content, caption)
        elif self.conversation.peer_pubkey and self.send_attachment is not None:
            self.send_attachment(self.conversation.peer_pubkey, str(path), content, caption)
        else:
            self.database.add_outgoing_message(self.conversation.id, content, protocol="BLOSSOM")
        self.on_message_sent(self.conversation.id)

    def _send(self) -> None:
        if self.conversation is None:
            return
        content = self.input.toPlainText().strip()
        if not content:
            return
        if self.conversation.kind == "group" and self.send_group is not None:
            self.send_group(self.conversation, content)
        elif self.conversation.peer_pubkey and self.send_direct is not None:
            self.send_direct(self.conversation.peer_pubkey, content)
        else:
            self.database.add_outgoing_message(self.conversation.id, content)
        self.input.clear()
        self.on_message_sent(self.conversation.id)

    def _scroll_to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _arm_bottom_scroll(self) -> None:
        self.bottom_scroll_generation += 1
        generation = self.bottom_scroll_generation
        self.bottom_scroll_pending = True
        for delay in (0, 40, 150, 400):
            QTimer.singleShot(delay, self._scroll_to_bottom)
        QTimer.singleShot(800, lambda: self._finish_bottom_scroll(generation))

    def _finish_bottom_scroll(self, generation: int) -> None:
        if generation == self.bottom_scroll_generation:
            self._scroll_to_bottom()
            self.bottom_scroll_pending = False

    def _scroll_range_changed(self, minimum: int, maximum: int) -> None:
        del minimum, maximum
        if self.bottom_scroll_pending:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def is_near_bottom(self) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar.maximum() - bar.value() <= 80

    def clear_conversation(self) -> None:
        self.bottom_scroll_generation += 1
        self.bottom_scroll_pending = False
        self.loaded_messages = []
        self.message_rows.clear()
        self.has_older_messages = False
        self.has_newer_messages = False
        self.pending_new_messages = 0
        self.search_active = False
        self.new_messages.hide()
        self.conversation = None
        self.name.setText("Select a conversation")
        self.presence.setText("OFFLINE-FIRST")
        clear_layout(self.avatar_holder)
        clear_layout(self.message_layout)
        self.input.clear()
        self.input.setPlaceholderText("Select a conversation")
        self.input.setEnabled(False)
        self.send.setEnabled(False)


class SettingsDialog(QDialog):
    def __init__(
        self,
        database: ClientDatabase,
        identity: UnlockedIdentity | None = None,
        edit_profile=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("fsociety settings")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        code = QLabel("NETWORK CONFIG  //  LOCAL PROFILE")
        code.setObjectName("sectionCode")
        layout.addWidget(code)

        identity_text = (
            f"Unlocked identity: {identity.record.username} ({identity.record.label})\n"
            f"{identity.record.npub}"
            if identity is not None
            else "No persistent identity is unlocked (smoke-test session)."
        )
        identity_label = QLabel(identity_text)
        identity_label.setWordWrap(True)
        identity_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(identity_label)
        self.copy_npub = QPushButton("COPY MY PUBLIC KEY (NPUB)")
        self.copy_npub.setObjectName("createAction")
        self.copy_npub.setEnabled(identity is not None)
        if identity is not None:
            self.copy_npub.clicked.connect(
                lambda: self._copy_public_key(identity.record.npub)
            )
        layout.addWidget(self.copy_npub)
        self.edit_profile = QPushButton("VIEW / EDIT MY PUBLIC PROFILE")
        self.edit_profile.setEnabled(identity is not None and edit_profile is not None)
        if edit_profile is not None:
            self.edit_profile.clicked.connect(edit_profile)
        layout.addWidget(self.edit_profile)

        form = QFormLayout()
        self.relay = self._endpoint_picker(
            (
                "wss://relay.damus.io",
                "wss://nos.lol",
                "wss://relay.primal.net",
                "wss://relay.nostrcheck.me",
            ),
            database.get_setting("network.relay", "wss://relay.damus.io"),
        )
        self.relay_fallback = self._endpoint_picker(
            (
                "wss://nos.lol",
                "wss://relay.damus.io",
                "wss://relay.primal.net",
                "wss://relay.nostrcheck.me",
            ),
            database.get_setting("network.relay_fallback", "wss://nos.lol"),
        )
        self.dm_relay = self._endpoint_picker(
            (
                "wss://auth.nostr1.com",
                "wss://inbox.azzamo.net",
                "wss://inbox.nostr.wine",
                "wss://relay.nostrcheck.me",
            ),
            database.get_setting("network.dm_relay", "wss://auth.nostr1.com"),
        )
        self.blossom = self._endpoint_picker(
            (
                "https://blossom.nostr.build",
                "https://blossom.primal.net",
                "https://blosstr.com",
            ),
            database.get_setting("network.blossom", "https://blossom.nostr.build"),
        )
        self.blossom_fallback = self._endpoint_picker(
            (
                "https://blossom.primal.net",
                "https://blossom.nostr.build",
                "https://blosstr.com",
            ),
            database.get_setting("network.blossom_fallback", "https://blossom.primal.net"),
        )
        self.upload_limit = QSpinBox()
        self.upload_limit.setRange(1, 2048)
        self.upload_limit.setSuffix(" MB")
        self.upload_limit.setValue(int(database.get_setting("uploads.max_mb", "100")))
        self.video_limit = QSpinBox()
        self.video_limit.setRange(1, 30)
        self.video_limit.setSuffix(" MB")
        self.video_limit.setValue(
            min(30, int(database.get_setting("uploads.video_max_mb", "30")))
        )
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 20)
        self.font_size.setSuffix(" px")
        legacy_font_size = database.get_setting("ui.font_size", "18")
        self.font_size.setValue(
            int(database.get_setting("messages.font_size", legacy_font_size))
        )
        self.font_size.setToolTip("Changes message bodies, sender names, and composer text")
        self.idle_screen = QCheckBox("Enable after 5 minutes of inactivity")
        self.idle_screen.setChecked(
            database.get_setting("ui.idle_visualization", "true") == "true"
        )
        self.idle_screen.setToolTip(
            "Shows the Neon Sunset Drive rolling-hills visualization while fsociety is idle"
        )
        self.admin_key = QLineEdit(
            database.get_setting("moderation.admin_npub", "")
        )
        self.admin_key.setPlaceholderText("Trusted fsociety admin npub")
        form.addRow("Primary Nostr relay", self.relay)
        form.addRow("Fallback Nostr relay", self.relay_fallback)
        form.addRow("NIP-17 DM inbox relay", self.dm_relay)
        form.addRow("Primary Blossom server", self.blossom)
        form.addRow("Fallback Blossom server", self.blossom_fallback)
        form.addRow("Attachment limit", self.upload_limit)
        form.addRow("Short video limit", self.video_limit)
        form.addRow("Message font size", self.font_size)
        form.addRow("Idle screen", self.idle_screen)
        form.addRow("Moderation admin key", self.admin_key)
        layout.addLayout(form)

        notice = QLabel(
            "Endpoints are stored in the local SQLite profile. The inbox relay is published "
            "as this identity's NIP-17 delivery preference and supports authenticated private "
            "message retrieval. "
            "The trusted admin key is used only to verify signed fsociety block lists."
        )
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        layout.addWidget(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        relay = self.relay.currentText().strip()
        relay_fallback = self.relay_fallback.currentText().strip()
        dm_relay = self.dm_relay.currentText().strip()
        blossom = self.blossom.currentText().strip()
        blossom_fallback = self.blossom_fallback.currentText().strip()
        admin_key = self.admin_key.text().strip()
        if any(
            not value.startswith(("ws://", "wss://"))
            for value in (relay, relay_fallback, dm_relay)
        ):
            QMessageBox.warning(
                self, "Invalid relay", "All relay URLs must begin with ws:// or wss://."
            )
            return
        if admin_key:
            try:
                from nostr_sdk import PublicKey

                admin_key = PublicKey.parse(admin_key).to_bech32()
            except Exception:
                QMessageBox.warning(
                    self, "Invalid admin key", "Enter a valid fsociety admin npub or public key."
                )
                return
        if any(
            not value.startswith(("http://", "https://"))
            for value in (blossom, blossom_fallback)
        ):
            QMessageBox.warning(
                self, "Invalid Blossom server", "Blossom URLs must begin with http:// or https://."
            )
            return
        self.database.set_setting("network.relay", relay)
        self.database.set_setting("network.relay_fallback", relay_fallback)
        self.database.set_setting("network.dm_relay", dm_relay)
        self.database.set_setting("network.blossom", blossom)
        self.database.set_setting("network.blossom_fallback", blossom_fallback)
        self.database.set_setting("uploads.max_mb", str(self.upload_limit.value()))
        self.database.set_setting("uploads.video_max_mb", str(self.video_limit.value()))
        self.database.set_setting("messages.font_size", str(self.font_size.value()))
        self.database.set_setting(
            "ui.idle_visualization", "true" if self.idle_screen.isChecked() else "false"
        )
        self.database.set_setting("moderation.admin_npub", admin_key)
        self.accept()

    def _copy_public_key(self, npub: str) -> None:
        QApplication.clipboard().setText(npub)
        self.copy_npub.setText("COPIED NPUB TO CLIPBOARD")
        QTimer.singleShot(
            1800,
            lambda: self.copy_npub.setText("COPY MY PUBLIC KEY (NPUB)"),
        )

    @staticmethod
    def _endpoint_picker(options: tuple[str, ...], current: str) -> QComboBox:
        picker = QComboBox()
        picker.setEditable(True)
        picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        picker.addItems(options)
        picker.setCurrentText(current)
        picker.setMinimumContentsLength(34)
        return picker


class NetworkDashboard(QWidget):
    def __init__(self, database: ClientDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.relay_states: dict[str, str] = {}
        self.inbox_status = "WAIT"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("NOSTR RELAY NETWORK  //  LIVE MESH")
        title.setObjectName("sectionCode")
        layout.addWidget(title)
        self.heading = QLabel("NETWORK INITIALIZING")
        self.heading.setStyleSheet(f"color:{CYAN};font-weight:700;")
        layout.addWidget(self.heading)
        self.mesh = RelayMeshView()
        layout.addWidget(self.mesh, 1)

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        self.connected_stat = self._stat_card("CONNECTED RELAYS", "0")
        self.availability_stat = self._stat_card("MESH AVAILABILITY", "0%")
        self.inbox_stat = self._stat_card("NIP-17 INBOX", "WAIT")
        self.messages_stat = self._stat_card("LOCAL MESSAGES", "0")
        self.outbox_stat = self._stat_card("PENDING OUTBOX", "0")
        self.groups_stat = self._stat_card("LOCAL GROUPS", "0")
        for index, card in enumerate(
            (
                self.connected_stat,
                self.availability_stat,
                self.inbox_stat,
                self.messages_stat,
                self.outbox_stat,
                self.groups_stat,
            )
        ):
            stats.addWidget(card, index // 3, index % 3)
        layout.addLayout(stats)

        relay_title = QLabel("CONFIGURED RELAY DETAILS")
        relay_title.setObjectName("sectionCode")
        layout.addWidget(relay_title)
        self.relay_details = QLabel("No relays configured")
        self.relay_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.relay_details.setStyleSheet(
            f"color:{TEXT};background:#0a1113;border:1px solid {LINE};padding:12px;"
        )
        layout.addWidget(self.relay_details)

    @staticmethod
    def _stat_card(label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("composerFrame")
        card.setProperty("stat_label", label)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 9, 12, 9)
        caption = QLabel(label)
        caption.setObjectName("sectionCode")
        number = QLabel(value)
        number.setObjectName("networkStatValue")
        number.setStyleSheet(f"color:{CYAN};font-weight:700;")
        card_layout.addWidget(caption)
        card_layout.addWidget(number)
        return card

    @staticmethod
    def _set_card(card: QFrame, value: str, error: bool = False) -> None:
        value_label = card.findChild(QLabel, "networkStatValue")
        if value_label is not None:
            value_label.setText(value)
            value_label.setStyleSheet(
                f"color:{CORAL if error else CYAN};font-weight:700;"
            )

    def set_relays(self, relays: list[str]) -> None:
        self.relay_states = {relay: "FOUND" for relay in relays}
        self.inbox_status = "WAIT"
        self.mesh.set_relays(relays)
        self._refresh_network_stats()

    def update_relay(self, relay: str, status: str) -> None:
        normalized = status.upper()
        if relay == "NIP-17 PRIVATE INBOX":
            self.inbox_status = normalized
        else:
            self.relay_states[relay] = normalized
        self.mesh.update_relay(relay, normalized)
        self._refresh_network_stats()

    def set_error(self, error: str) -> None:
        self.heading.setText(f"NETWORK DEGRADED  ·  {error}")
        self.heading.setStyleSheet(f"color:{CORAL};font-weight:700;")

    def refresh_local_stats(self) -> None:
        if not self.relay_states:
            self.set_relays(
                list(
                    dict.fromkeys(
                        value.strip()
                        for value in (
                            self.database.get_setting("network.relay", "wss://relay.damus.io"),
                            self.database.get_setting("network.relay_fallback", "wss://nos.lol"),
                            self.database.get_setting("network.dm_relay", "wss://auth.nostr1.com"),
                        )
                        if value.strip()
                    )
                )
            )
        message_count = int(
            self.database.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        )
        group_count = int(
            self.database.connection.execute(
                "SELECT COUNT(*) FROM conversations WHERE kind = 'group'"
            ).fetchone()[0]
        )
        self._set_card(self.messages_stat, str(message_count))
        self._set_card(
            self.outbox_stat,
            str(
                len(self.database.pending_outbox())
                + len(self.database.pending_reaction_outbox())
            ),
        )
        self._set_card(self.groups_stat, str(group_count))
        self._refresh_network_stats()

    def _refresh_network_stats(self) -> None:
        total = len(self.relay_states)
        connected = sum(state == "CONNECTED" for state in self.relay_states.values())
        unavailable = sum(state == "UNAVAILABLE" for state in self.relay_states.values())
        availability = round(connected * 100 / total) if total else 0
        self._set_card(self.connected_stat, f"{connected} / {total}", unavailable > 0)
        self._set_card(self.availability_stat, f"{availability}%", unavailable > 0)
        self._set_card(
            self.inbox_stat,
            self.inbox_status,
            self.inbox_status in {"UNAVAILABLE", "FAILED"},
        )
        self.heading.setText(
            f"{connected} OF {total} RELAYS CONNECTED"
            + (f"  ·  {unavailable} UNAVAILABLE" if unavailable else "")
        )
        self.heading.setStyleSheet(
            f"color:{CORAL if unavailable else CYAN};font-weight:700;"
        )
        lines = []
        for relay, state in self.relay_states.items():
            marker = "●" if state == "CONNECTED" else ("×" if state == "UNAVAILABLE" else "◌")
            lines.append(f"{marker}  {relay}  ·  {state}")
        lines.append(f"●  NIP-17 PRIVATE INBOX  ·  {self.inbox_status}")
        self.relay_details.setText("\n".join(lines))


class NetworkStartupDialog(QDialog):
    """Visible startup telemetry for relay and private-inbox connectivity."""

    def __init__(self, relays: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("fsociety network startup")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.relay_rows: dict[str, QLabel] = {}
        self.relay_urls = list(relays)
        self.states: dict[str, str] = {
            relay: "FOUND" for relay in [*relays, "NIP-17 PRIVATE INBOX"]
        }
        self.resolved: set[str] = set()
        self.total_steps = len(relays) + 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        heading = QLabel("NOSTR NETWORK INITIALIZATION")
        heading.setObjectName("sectionCode")
        layout.addWidget(heading)
        self.summary = QLabel(f"FOUND {len(relays)} CONFIGURED RELAYS")
        self.summary.setStyleSheet(f"color:{CYAN};font:700 13px 'Perfect DOS VGA 437 Win';")
        layout.addWidget(self.summary)

        for relay in [*relays, "NIP-17 PRIVATE INBOX"]:
            row = QLabel(f"○  {relay}  ·  FOUND")
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.setStyleSheet("padding:7px;border:1px solid #243b40;")
            self.relay_rows[relay] = row
            layout.addWidget(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, self.total_steps)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("STARTUP CHECKS  %v / %m COMPLETE")
        layout.addWidget(self.progress)
        self.detail = QLabel("Discovering relay capabilities and opening encrypted inbox…")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("muted")
        layout.addWidget(self.detail)
        self.continue_button = QPushButton("CONTINUE IN BACKGROUND")
        self.continue_button.clicked.connect(self.accept)
        layout.addWidget(self.continue_button)

    def update_relay(self, relay: str, status: str) -> None:
        row = self.relay_rows.get(relay)
        if row is None:
            row = QLabel()
            self.relay_rows[relay] = row
            self.layout().insertWidget(max(0, self.layout().count() - 3), row)
        normalized = status.upper()
        self.states[relay] = normalized
        glyph = "●" if normalized == "CONNECTED" else ("×" if normalized == "UNAVAILABLE" else "◌")
        color = CYAN if normalized == "CONNECTED" else (CORAL if normalized == "UNAVAILABLE" else TEXT)
        row.setText(f"{glyph}  {relay}  ·  {normalized}")
        row.setStyleSheet(f"color:{color};padding:7px;border:1px solid #243b40;")
        if normalized in {"CONNECTED", "UNAVAILABLE"}:
            self.resolved.add(relay)
        else:
            self.resolved.discard(relay)
        self.progress.setValue(min(len(self.resolved), self.total_steps))
        relay_connected = sum(
            self.states.get(value) == "CONNECTED" for value in self.relay_urls
        )
        relay_unavailable = sum(
            self.states.get(value) == "UNAVAILABLE" for value in self.relay_urls
        )
        self.summary.setText(
            f"RELAYS CONNECTED {relay_connected}/{len(self.relay_urls)}"
            + (f"  ·  {relay_unavailable} UNAVAILABLE" if relay_unavailable else "")
        )
        self.detail.setText(f"{relay}: {normalized.lower()}")

    def connected(self, count: int) -> None:
        self.progress.setValue(self.total_steps)
        self.progress.setFormat("NETWORK READY")
        self.summary.setText(
            f"NOSTR ONLINE  ·  {count}/{len(self.relay_urls)} RELAYS CONNECTED"
            "  ·  PRIVATE INBOX READY"
        )
        self.detail.setText("Private messaging synchronization is active.")
        self.continue_button.setText("OPEN FSOCIETY")
        QTimer.singleShot(1400, self.accept)

    def failed(self, error: str) -> None:
        self.summary.setText("NETWORK CONNECTION INCOMPLETE")
        self.summary.setStyleSheet(f"color:{CORAL};font:700 13px 'Perfect DOS VGA 437 Win';")
        self.detail.setText(error)
        self.continue_button.setText("CONTINUE OFFLINE / RETRY IN BACKGROUND")


class MainWindow(QMainWindow):
    def __init__(
        self,
        database: ClientDatabase,
        identity: UnlockedIdentity | None = None,
        profile_updater=None,
    ) -> None:
        super().__init__()
        self.database = database
        self.identity = identity
        if identity is not None:
            self.database.ensure_legacy_message_references(
                identity.keys.public_key().to_hex()
            )
        self.closing = False
        self.database_closed = False
        self.profile_updater = profile_updater
        self.moderation_worker: ModerationSyncWorker | None = None
        self.transport: NostrTransport | None = None
        self.startup_dialog: NetworkStartupDialog | None = None
        self.startup_dialog_shown = False
        self.transport_connected = False
        self.conversation_statuses: dict[str, str] = {}
        self.pending_group_control = ""
        self.global_status = "NOSTR CONNECTING"
        self.setWindowTitle(f"fsociety - secure messenger - {__release_label__}")
        self.setMinimumSize(900, 620)
        self.resize(1180, 760)

        root = CornerFrame()
        root.setStyleSheet(f"background:{VOID};")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        top_plate = QLabel(
            f"SECURE INTERFACE  //  FSOCIETY  //  {__release_label__.upper()}"
        )
        top_plate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_plate.setFixedHeight(25)
        top_plate.setStyleSheet(
            f"background:#14252a;color:{TEXT};border-top:2px solid {CYAN};"
            f"font:600 {UI_SMALL_FONT_PX}px 'Perfect DOS VGA 437 Win';letter-spacing:2px;"
        )
        outer.addWidget(top_plate)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.nav = NavRail(
            identity.record.username if identity is not None else "",
            identity.record.avatar_png if identity is not None else None,
        )
        self.nav.section_selected.connect(self._section_selected)
        self.nav.settings_requested.connect(self._open_settings)
        self.nav.profile_requested.connect(self._open_my_profile)
        self.chat = ChatPane(
            database=database,
            on_message_sent=self._message_sent,
            send_direct=self._send_direct_message,
            send_attachment=self._send_attachment,
            send_group=self._send_group_message,
            send_group_attachment=self._send_group_attachment,
            send_reaction=self._send_message_reaction,
            view_profile=self._view_profile,
            group_exit=self._leave_or_delete_group,
            delete_conversation=self._delete_direct_conversation,
            own_pubkey=identity.keys.public_key().to_hex() if identity is not None else "",
            own_name=identity.record.username if identity is not None else "",
        )
        self.sidebar = ConversationSidebar(
            database,
            self._conversation_selected,
            self._new_direct_chat,
            self._new_group,
            self._create_group_invite,
            self._join_group_invite,
            self._add_contact,
            self._view_profile,
            self._leave_or_delete_group,
            self._remove_selected_contact,
            self._toggle_selected_contact_block,
        )
        self.network_dashboard = NetworkDashboard(database)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.chat)
        self.content_stack.addWidget(self.network_dashboard)
        body_layout.addWidget(self.nav)
        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.content_stack, 1)
        outer.addWidget(body, 1)

        identity_status = (
            f"IDENTITY {identity.record.npub[:18]}…  ·  " if identity is not None else ""
        )
        self.network_status = QLabel(
            f"{identity_status}LOCAL CACHE READY  ·  "
            + ("CONNECTING TO NOSTR…" if identity is not None else "NETWORK DISABLED")
        )
        self.network_status.setObjectName("networkStatus")
        self.network_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.network_status.setContentsMargins(0, 2, 12, 3)
        self.network_status.setFixedHeight(18)
        outer.addWidget(self.network_status)
        self.setCentralWidget(root)
        self.idle_visualization = IdleVisualizationController(self, database)
        QTimer.singleShot(1000, self._sync_moderation)
        QTimer.singleShot(0, self._start_transport)

    def _section_selected(self, section: str) -> None:
        if section == "network":
            self.sidebar.hide()
            self.content_stack.setCurrentWidget(self.network_dashboard)
            self.network_dashboard.refresh_local_stats()
            return
        self.sidebar.show()
        self.content_stack.setCurrentWidget(self.chat)
        self.sidebar.show_section(section)

    def _open_settings(self) -> None:
        if SettingsDialog(
            self.database, self.identity, self._open_my_profile, self
        ).exec() == QDialog.DialogCode.Accepted:
            self.chat.apply_message_font_size()
            self.idle_visualization.refresh_settings()
            self._sync_moderation()
            self._restart_transport()

    def _open_my_profile(self) -> None:
        if self.identity is None or self.profile_updater is None:
            return
        previous_username = self.identity.record.username
        dialog = ProfileDialog(
            self.database,
            self.identity.keys.public_key().to_hex(),
            self.identity,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        username = dialog.username.text().strip()
        try:
            self.identity = self.profile_updater(self.identity, username, dialog.avatar_png)
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Profile not saved", str(error))
            return
        self.nav.set_profile(self.identity.record.username, self.identity.record.avatar_png)
        self.chat.own_name = self.identity.record.username
        self.database.set_setting("profile.published_fingerprint", "")
        self.database.set_setting("profile.picture_url", "")
        if self.identity.record.username != previous_username:
            self._queue_group_username_changes(
                previous_username, self.identity.record.username
            )
        self._restart_transport()

    def _queue_group_username_changes(self, previous: str, current: str) -> None:
        if self.identity is None:
            return
        own = self.identity.keys.public_key().to_hex()
        control = GROUP_CONTROL_PREFIX + json.dumps(
            {
                "action": "rename",
                "actor": own,
                "previous": previous,
                "name": current,
            },
            separators=(",", ":"),
        )
        for conversation in self.database.list_conversations(mode="groups"):
            members = [
                member
                for member in self.database.group_members(conversation.id)
                if member != own
            ]
            self.database.queue_group_system_message(
                conversation.id,
                f"✎ {previous} changed their username to {current}.",
                control,
                members,
                own,
                current,
            )
        self.sidebar.refresh()
        if self.chat.conversation is not None:
            self._refresh_current_conversation()

    def _add_contact(self) -> None:
        if self.identity is None:
            return
        value, accepted = QInputDialog.getText(
            self, "Add contact", "Contact npub or public key:"
        )
        if not accepted or not value.strip():
            return
        try:
            from nostr_sdk import PublicKey

            pubkey = PublicKey.parse(value.strip()).to_hex()
        except Exception:
            QMessageBox.warning(self, "Invalid identity", "Enter a valid npub or public key.")
            return
        if pubkey == self.identity.keys.public_key().to_hex():
            QMessageBox.warning(self, "Your identity", "Your own profile is available in the navigation rail.")
            return
        nickname, accepted = QInputDialog.getText(
            self, "Contact nickname", "Optional local nickname:"
        )
        if not accepted:
            return
        self.database.add_contact(pubkey, nickname.strip())
        conversation_id = self.database.ensure_direct_conversation(pubkey)
        self.sidebar.show_section("contacts")
        self.sidebar.refresh()
        self.sidebar.select_conversation(conversation_id)
        if self.transport is not None:
            self.transport.refresh_profiles([pubkey])

    def _remove_selected_contact(self) -> None:
        item = self.sidebar.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "Remove contact", "Select a contact first.")
            return
        conversation = item.data(Qt.ItemDataRole.UserRole + 1)
        if not conversation.peer_pubkey or not self.database.is_contact(
            conversation.peer_pubkey
        ):
            QMessageBox.information(self, "Remove contact", "Select a contact first.")
            return
        answer = QMessageBox.question(
            self,
            "Remove contact",
            f"Remove {conversation.display_name} from Contacts? The local conversation "
            "and its visible message history will remain available under Messages.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.database.remove_contact(conversation.peer_pubkey)
        self.sidebar.refresh()

    def _delete_direct_conversation(self, conversation: Conversation) -> None:
        if conversation.kind != "direct":
            return
        answer = QMessageBox.question(
            self,
            "Delete conversation locally",
            f"Remove {conversation.display_name} and all of its messages from this "
            "identity's local view?\n\nPending retries will be cancelled. Events already "
            "accepted by Nostr relays cannot be erased. A genuinely new incoming message "
            "or deliberately adding this npub again can reopen the conversation.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.database.hide_direct_conversation_locally(conversation.id):
            return
        self.conversation_statuses.pop(conversation.id, None)
        self.chat.clear_conversation()
        self.sidebar.refresh()
        if self.sidebar.list_widget.count() == 0:
            self.network_status.setText("CONVERSATION REMOVED FROM LOCAL VIEW")

    def _toggle_selected_contact_block(self) -> None:
        item = self.sidebar.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "Block user", "Select a contact first.")
            return
        conversation = item.data(Qt.ItemDataRole.UserRole + 1)
        pubkey = conversation.peer_pubkey
        if not pubkey:
            QMessageBox.information(self, "Block user", "Select a contact first.")
            return
        blocked = self.database.is_user_blocked(pubkey)
        if not blocked:
            answer = QMessageBox.question(
                self,
                "Block user",
                f"Block {conversation.display_name} locally? Existing messages will be "
                "hidden and future direct or group messages from this key will be discarded.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.database.set_user_blocked(pubkey, not blocked)
        if (
            not blocked
            and self.chat.conversation is not None
            and self.chat.conversation.peer_pubkey == pubkey
        ):
            self.chat.clear_conversation()
        self.sidebar.refresh()

    def _view_profile(self, pubkey: str) -> None:
        if self.identity is not None and pubkey == self.identity.keys.public_key().to_hex():
            self._open_my_profile()
            return
        dialog = ProfileDialog(self.database, pubkey, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.block_changed and self.chat.conversation is not None:
            if (
                self.database.is_user_blocked(pubkey)
                and self.chat.conversation.peer_pubkey == pubkey
            ):
                self.chat.clear_conversation()
            elif self.chat.conversation.kind == "group":
                self._refresh_current_conversation()
        if dialog.nickname.text().strip() and self.database.is_contact(pubkey):
            self.database.set_contact_nickname(pubkey, dialog.nickname.text().strip())
        self.sidebar.refresh()
        if dialog.start_message:
            conversation_id = self.database.ensure_direct_conversation(pubkey)
            self.sidebar.show_section("messages")
            self.sidebar.refresh()
            self.sidebar.select_conversation(conversation_id)

    def _new_direct_chat(self) -> None:
        if self.identity is None:
            return
        value, accepted = QInputDialog.getText(
            self, "Start encrypted chat", "Recipient npub or public key:"
        )
        if not accepted or not value.strip():
            return
        try:
            from nostr_sdk import PublicKey

            peer = PublicKey.parse(value.strip()).to_hex()
        except Exception:
            QMessageBox.warning(self, "Invalid identity", "Enter a valid npub or public key.")
            return
        if peer == self.identity.keys.public_key().to_hex():
            QMessageBox.warning(self, "Invalid recipient", "You cannot start a direct chat with yourself.")
            return
        conversation_id = self.database.ensure_direct_conversation(peer)
        self.sidebar.refresh()
        self.sidebar.select_conversation(conversation_id)

    def _start_transport(self) -> None:
        if self.identity is None or self.transport is not None:
            return
        relays = [
            self.database.get_setting("network.relay", "wss://relay.damus.io"),
            self.database.get_setting("network.relay_fallback", "wss://nos.lol"),
            self.database.get_setting("network.dm_relay", "wss://auth.nostr1.com"),
        ]
        relays = list(dict.fromkeys(value.strip() for value in relays if value.strip()))
        self.sidebar.telemetry.set_relays(relays)
        self.network_dashboard.set_relays(relays)
        if not self.startup_dialog_shown:
            self.startup_dialog_shown = True
            self.startup_dialog = NetworkStartupDialog(relays, self)
            self.startup_dialog.show()
        inbox_relays = [
            self.database.get_setting("network.dm_relay", "wss://auth.nostr1.com"),
            self.database.get_setting("network.relay", "wss://relay.damus.io"),
            self.database.get_setting("network.relay_fallback", "wss://nos.lol"),
        ]
        profile_material = self.identity.record.username.encode("utf-8") + (
            self.identity.record.avatar_png or b""
        )
        profile_fingerprint = hashlib.sha256(profile_material).hexdigest()
        published_fingerprint = self.database.get_setting("profile.published_fingerprint", "")
        self.transport_connected = False
        self.network_status.setText("CONNECTING TO NOSTR RELAYS…")
        self.transport = NostrTransport(
            self.identity,
            relays,
            self.database.get_setting("network.blossom", "https://blossom.nostr.build"),
            profile_fingerprint,
            profile_fingerprint != published_fingerprint,
            self.database.get_setting("profile.picture_url", ""),
            str(self.database.path.parent / "attachments"),
            int(self.database.get_setting("uploads.max_mb", "100")) * 1024 * 1024,
            self.database.get_setting(
                "network.blossom_fallback", "https://blossom.primal.net"
            ),
            inbox_relay_urls=inbox_relays,
            max_video_bytes=min(
                30, int(self.database.get_setting("uploads.video_max_mb", "30"))
            )
            * 1024
            * 1024,
        )
        self.transport.connected.connect(self._transport_connected)
        self.transport.connection_failed.connect(self._transport_failed)
        self.transport.relay_status.connect(self._relay_status_changed)
        self.transport.direct_message.connect(self._direct_message_received)
        self.transport.message_published.connect(self._message_published)
        self.transport.message_failed.connect(self._message_publish_failed)
        self.transport.profile_published.connect(self._profile_published)
        self.transport.profile_failed.connect(self._profile_failed)
        self.transport.attachment_status.connect(self._attachment_status)
        self.transport.public_profile.connect(self._public_profile_received)
        self.transport.reaction_published.connect(self._reaction_published)
        self.transport.reaction_failed.connect(self._reaction_failed)
        self.transport.finished.connect(self._transport_finished)
        self.transport.start()

    def _restart_transport(self) -> None:
        if self.transport is not None and self.transport.isRunning():
            self.transport.requestInterruption()
            if not self.transport.wait(7000):
                self.network_status.setText("WAITING FOR NOSTR TRANSPORT TO RESTART…")
                return
        self.transport = None
        self._start_transport()

    def _transport_connected(self, count: int) -> None:
        if self.closing:
            return
        newly_connected = not self.transport_connected
        self.transport_connected = True
        self.global_status = (
            f"NOSTR LIVE  ·  {count} RELAYS CONNECTED  ·  "
            "AUTHENTICATED NIP-17 INBOX ACTIVE"
        )
        self.network_status.setText(self.global_status)
        self.network_dashboard.refresh_local_stats()
        if self.startup_dialog is not None and self.startup_dialog.isVisible():
            self.startup_dialog.connected(count)
        if not newly_connected:
            return
        if self.transport is not None:
            self.transport.refresh_profiles(self.database.profile_targets())
        for item in self.database.pending_outbox():
            if self.transport is not None:
                self.database.mark_message_sending(int(item["message_id"]))
                if item["message_type"] == "group_attachment" and item["attachment_path"]:
                    import json

                    group_id = str(item["group_id"])
                    conversation = next(
                        (row for row in self.database.list_conversations() if row.id == group_id),
                        None,
                    )
                    self.transport.send_group_attachment(
                        int(item["message_id"]),
                        group_id,
                        conversation.display_name if conversation else "Encrypted group",
                        json.loads(str(item["recipients_json"])),
                        str(item["attachment_path"]),
                        str(item["attachment_caption"] or ""),
                    )
                elif item["message_type"] == "attachment" and item["attachment_path"]:
                    self.transport.send_attachment(
                        int(item["message_id"]),
                        str(item["recipient_pubkey"]),
                        str(item["attachment_path"]),
                        str(item["attachment_caption"] or ""),
                    )
                elif item["message_type"] == "group" and item["recipients_json"]:
                    import json

                    group_id = str(item["group_id"])
                    conversation = next(
                        (item for item in self.database.list_conversations() if item.id == group_id),
                        None,
                    )
                    self.transport.send_group(
                        int(item["message_id"]),
                        group_id,
                        conversation.display_name if conversation else "Encrypted group",
                        json.loads(str(item["recipients_json"])),
                        str(item["content"]),
                    )
                else:
                    self.transport.send_direct_message(
                        int(item["message_id"]),
                        str(item["recipient_pubkey"]),
                        str(item["content"]),
                    )
        for item in self.database.pending_reaction_outbox():
            self._publish_queued_reaction(item)

    def _publish_queued_reaction(self, item: dict[str, object]) -> None:
        if self.transport is None or not self.transport_connected:
            return
        group_id = str(item["group_id"] or "")
        conversation = next(
            (
                row
                for row in self.database.list_conversations()
                if row.id == str(item["conversation_id"])
            ),
            None,
        )
        self.database.mark_reaction_sending(int(item["id"]))
        self.transport.send_reaction(
            int(item["id"]),
            str(item["target_ref"]),
            str(item["emoji"]),
            bool(item["active"]),
            int(item["created_at"]),
            json.loads(str(item["recipients_json"])),
            group_id,
            conversation.display_name if conversation is not None else "Encrypted group",
        )

    def _transport_failed(self, error: str) -> None:
        if self.closing:
            return
        if "warning:" in error.casefold() or error.startswith("Relay synchronization failed:"):
            self.network_status.setText(f"NOSTR LIVE  ·  {error}")
            return
        self.transport_connected = False
        self.network_status.setText(f"NOSTR OFFLINE  ·  {error}")
        self.network_dashboard.set_error(error)
        if self.startup_dialog is not None and self.startup_dialog.isVisible():
            self.startup_dialog.failed(error)

    def _relay_status_changed(self, relay: str, status: str) -> None:
        if self.closing:
            return
        self.sidebar.telemetry.update_relay(relay, status)
        self.network_dashboard.update_relay(relay, status)
        if self.startup_dialog is not None and self.startup_dialog.isVisible():
            self.startup_dialog.update_relay(relay, status)

    def _transport_finished(self) -> None:
        self.transport_connected = False

    def _profile_published(self, fingerprint: str, picture_url: str, relays: str) -> None:
        if self.closing:
            return
        self.database.set_setting("profile.published_fingerprint", fingerprint)
        self.database.set_setting("profile.picture_url", picture_url)
        self.network_status.setText(f"NOSTR LIVE  ·  PROFILE PUBLISHED TO {relays}")

    def _profile_failed(self, error: str) -> None:
        if self.closing:
            return
        self.network_status.setText(f"NOSTR LIVE  ·  PROFILE PUBLISH FAILED: {error}")

    def _public_profile_received(self, payload: dict[str, object]) -> None:
        if self.closing or self.database_closed:
            return
        self.database.upsert_profile(
            str(payload["pubkey"]),
            str(payload["name"]),
            str(payload["display_name"]),
            str(payload["picture"]),
            int(payload["updated_at"]),
            str(payload.get("about") or ""),
            str(payload.get("nip05") or ""),
            payload.get("picture_blob") if isinstance(payload.get("picture_blob"), bytes) else None,
        )
        self.sidebar.refresh()

    def _send_direct_message(self, peer_pubkey: str, content: str) -> None:
        if self.database.is_user_blocked(peer_pubkey):
            QMessageBox.warning(
                self, "User blocked", "Unblock this user from Contacts before messaging them."
            )
            return
        message = self.database.queue_direct_message(peer_pubkey, content)
        if self.transport_connected and self.transport is not None:
            self.database.mark_message_sending(message.id)
            self.transport.send_direct_message(message.id, peer_pubkey, content)

    def _send_attachment(
        self, peer_pubkey: str, path: str, display_text: str, caption: str = ""
    ) -> None:
        if self.database.is_user_blocked(peer_pubkey):
            QMessageBox.warning(
                self, "User blocked", "Unblock this user from Contacts before sharing files."
            )
            return
        message = self.database.queue_attachment(peer_pubkey, path, display_text, caption)
        if self.transport_connected and self.transport is not None:
            self.database.mark_message_sending(message.id)
            self.transport.send_attachment(message.id, peer_pubkey, path, caption)

    def _send_group_attachment(
        self,
        conversation: Conversation,
        path: str,
        display_text: str,
        caption: str = "",
    ) -> None:
        if self.identity is None:
            return
        own = self.identity.keys.public_key().to_hex()
        members = [
            member
            for member in self.database.group_members(conversation.id)
            if member != own
        ]
        message = self.database.queue_group_attachment(
            conversation.id,
            path,
            display_text,
            members,
            own,
            self.identity.record.username,
            caption,
        )
        if self.transport_connected and self.transport is not None:
            self.database.mark_message_sending(message.id)
            self.transport.send_group_attachment(
                message.id,
                conversation.id,
                conversation.display_name,
                members,
                path,
                caption,
            )

    def _send_message_reaction(
        self, message_id: int, conversation: Conversation, emoji: str, active: bool
    ) -> None:
        if self.identity is None:
            return
        own = self.identity.keys.public_key().to_hex()
        if conversation.kind == "group":
            recipients = [
                member
                for member in self.database.group_members(conversation.id)
                if member != own
            ]
            group_id = conversation.id
        else:
            recipients = [conversation.peer_pubkey] if conversation.peer_pubkey else []
            group_id = ""
        if not recipients:
            QMessageBox.warning(self, "Reaction unavailable", "This chat has no recipient.")
            return
        try:
            outbox_id = self.database.queue_message_reaction(
                message_id,
                conversation.id,
                own,
                emoji,
                active,
                [str(value) for value in recipients],
                group_id,
            )
        except ValueError as error:
            QMessageBox.information(self, "Reaction unavailable", str(error))
            return
        self.chat.refresh_message_reactions(message_id)
        item = next(
            (
                row
                for row in self.database.pending_reaction_outbox()
                if int(row["id"]) == outbox_id
            ),
            None,
        )
        if item is not None:
            self._publish_queued_reaction(item)

    def _new_group(self) -> None:
        if self.identity is None:
            return
        name, accepted = QInputDialog.getText(self, "Create encrypted group", "Group name:")
        if not accepted or not name.strip():
            return
        values, accepted = QInputDialog.getMultiLineText(
            self,
            "Optional initial members",
            "Enter one member npub per line, or leave blank and create invites later:",
        )
        if not accepted:
            return
        try:
            from nostr_sdk import PublicKey

            members = [
                PublicKey.parse(value.strip()).to_hex()
                for value in values.splitlines()
                if value.strip()
            ]
        except Exception:
            QMessageBox.warning(self, "Invalid member", "Every group member must be a valid npub.")
            return
        own = self.identity.keys.public_key().to_hex()
        members = list(dict.fromkeys(member for member in members if member != own))
        material = "|".join(sorted([own, *members])) + "|" + name.strip()
        group_id = "group:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        self.database.create_group(
            group_id, name.strip(), [own, *members], creator_pubkey=own
        )
        self.sidebar.show_section("communities")
        self.sidebar.refresh()
        self.sidebar.select_conversation(group_id)
        QMessageBox.information(
            self,
            "Encrypted group created",
            "You are automatically the first member. Use Create Invite to add people, then "
            "send a message to deliver the encrypted community to its members.",
        )

    def _selected_group(self) -> Conversation | None:
        item = self.sidebar.list_widget.currentItem()
        if item is not None:
            conversation = item.data(Qt.ItemDataRole.UserRole + 1)
            if conversation is not None and conversation.kind == "group":
                return conversation
        if self.chat.conversation is not None and self.chat.conversation.kind == "group":
            return self.chat.conversation
        QMessageBox.information(
            self, "Select a group", "Open Communities and select a group first."
        )
        return None

    def _leave_or_delete_group(self, conversation=None) -> None:
        if self.identity is None:
            return
        if not isinstance(conversation, Conversation):
            conversation = self._selected_group()
        if conversation is None or conversation.kind != "group":
            return
        own = self.identity.keys.public_key().to_hex()
        creator = self.database.group_creator(conversation.id)
        is_creator = bool(creator) and creator == own
        action = "delete" if is_creator else "leave"
        if is_creator:
            title = "Delete encrypted group"
            prompt = (
                f"Delete {conversation.display_name}?\n\n"
                "A signed encrypted closure notice will be sent to members when connected. "
                "Official fsociety clients will remove the group, but already-published Nostr "
                "events cannot be erased from relays. Local messages will be removed from this PC."
            )
        else:
            title = "Leave encrypted group"
            prompt = (
                f"Leave {conversation.display_name}?\n\n"
                "A signed encrypted leave notice will be sent when connected, and this group's "
                "local messages will be removed from this PC."
            )
        if (
            QMessageBox.question(
                self,
                title,
                prompt,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        members = [
            member for member in self.database.group_members(conversation.id) if member != own
        ]
        if members and (not self.transport_connected or self.transport is None):
            QMessageBox.warning(
                self,
                "Connect before leaving",
                "fsociety must be connected before this membership change so the signed "
                "group system event can be delivered to the remaining members.",
            )
            return
        control = GROUP_CONTROL_PREFIX + json.dumps(
            {
                "action": action,
                "actor": own,
                "name": self.identity.record.username,
            },
            separators=(",", ":"),
        )
        notice_sent = False
        if self.transport_connected and self.transport is not None and members:
            self.pending_group_control = "GROUP CLOSURE" if is_creator else "GROUP LEAVE"
            self.transport.send_group(
                0,
                conversation.id,
                conversation.display_name,
                members,
                control,
            )
            notice_sent = True
        self.database.delete_group(conversation.id)
        self.conversation_statuses.pop(conversation.id, None)
        self.sidebar.show_section("communities")
        self.sidebar.refresh()
        if self.sidebar.list_widget.count() == 0:
            self.chat.clear_conversation()
        self.network_status.setText(
            ("GROUP DELETED" if is_creator else "GROUP LEFT")
            + (
                "  ·  ENCRYPTED NOTICE QUEUED"
                if notice_sent
                else (
                    "  ·  NO REMOTE RECIPIENTS"
                    if self.transport_connected
                    else "  ·  LOCAL ONLY (OFFLINE)"
                )
            )
        )

    def _create_group_invite(self) -> None:
        if self.identity is None:
            return
        conversation = self._selected_group()
        if conversation is None:
            return
        value, accepted = QInputDialog.getText(
            self, "Create signed group invite", "Invitee npub or public key:"
        )
        if not accepted or not value.strip():
            return
        try:
            from nostr_sdk import PublicKey

            invited = PublicKey.parse(value.strip()).to_hex()
            members = self.database.group_members(conversation.id)
            code = create_group_invite(
                self.identity.keys,
                conversation.id,
                conversation.display_name,
                invited,
                members,
                creator_pubkey=self.database.group_creator(conversation.id),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Unable to create invite", str(error))
            return
        self.database.add_group_member(conversation.id, invited)
        QApplication.clipboard().setText(code)
        QMessageBox.information(
            self,
            "Signed invite copied",
            "A 24-hour invite targeted to that npub was copied to the clipboard. "
            "Send it privately to the invitee, who should use Communities > Join With Invite.",
        )
        self.sidebar.refresh()
        self.sidebar.select_conversation(conversation.id)

    def _join_group_invite(self) -> None:
        if self.identity is None:
            return
        code, accepted = QInputDialog.getMultiLineText(
            self, "Join encrypted group", "Paste the signed fsociety invite code:"
        )
        if not accepted or not code.strip():
            return
        try:
            invite = parse_group_invite(
                code, self.identity.keys.public_key().to_hex()
            )
        except ValueError as error:
            QMessageBox.warning(self, "Invite rejected", str(error))
            return
        self.database.create_group(
            invite.group_id,
            invite.name,
            list(invite.members),
            creator_pubkey=invite.creator,
        )
        self.sidebar.show_section("communities")
        self.sidebar.refresh()
        self.sidebar.select_conversation(invite.group_id)
        conversation = self._selected_group()
        if conversation is not None:
            own = self.identity.keys.public_key().to_hex()
            self.database.add_group_member(conversation.id, own)
            members = [member for member in self.database.group_members(conversation.id) if member != own]
            display_text = f"🔐 {self.identity.record.username} joined the group."
            control = GROUP_CONTROL_PREFIX + json.dumps(
                {"action": "join", "actor": own, "name": self.identity.record.username},
                separators=(",", ":"),
            )
            message = self.database.queue_group_system_message(
                conversation.id,
                display_text,
                control,
                members,
                own,
                self.identity.record.username,
            )
            if self.transport_connected and self.transport is not None:
                self.database.mark_message_sending(message.id)
                self.transport.send_group(
                    message.id,
                    conversation.id,
                    conversation.display_name,
                    members,
                    control,
                )
            self._refresh_current_conversation()
        QMessageBox.information(
            self,
            "Group joined",
            f"Joined {invite.name}. A signed encrypted membership message was queued for the group.",
        )

    def _send_group_message(self, conversation: Conversation, content: str) -> None:
        members = self.database.group_members(conversation.id)
        if self.identity is not None:
            own = self.identity.keys.public_key().to_hex()
            members = [member for member in members if member != own]
        message = self.database.queue_group_message(
            conversation.id,
            content,
            members,
            self.identity.keys.public_key().to_hex() if self.identity is not None else "",
            self.identity.record.username if self.identity is not None else "",
        )
        if self.transport_connected and self.transport is not None:
            self.database.mark_message_sending(message.id)
            self.transport.send_group(
                message.id, conversation.id, conversation.display_name, members, content
            )

    def _message_published(
        self, message_id: int, event_id: str, relays: str, message_ref: str
    ) -> None:
        if self.closing:
            return
        if message_id == 0:
            label = self.pending_group_control or "GROUP CONTROL"
            self.pending_group_control = ""
            self.network_status.setText(f"{label} ACCEPTED BY {relays}")
            return
        self.database.mark_message_published(message_id, event_id)
        self.database.set_message_reference(message_id, message_ref)
        self._set_message_status(message_id, f"MESSAGE ACCEPTED BY {relays}")
        self.sidebar.refresh()
        if not self.chat.update_message_delivery_state(message_id, "relay-accepted"):
            self._refresh_current_conversation()

    def _reaction_published(self, outbox_id: int, event_id: str, relays: str) -> None:
        if self.closing or self.database_closed:
            return
        self.database.mark_reaction_published(outbox_id, event_id)
        self.network_status.setText(f"REACTION ACCEPTED BY {relays}")

    def _reaction_failed(self, outbox_id: int, error: str) -> None:
        if self.closing or self.database_closed:
            return
        self.database.mark_reaction_failed(outbox_id, error)
        self.network_status.setText(f"REACTION QUEUED FOR RETRY  ·  {error}")

    def _message_publish_failed(self, message_id: int, error: str) -> None:
        if self.closing:
            return
        if message_id == 0:
            label = self.pending_group_control or "GROUP CONTROL"
            self.pending_group_control = ""
            self.network_status.setText(f"{label} DELIVERY FAILED  ·  {error}")
            return
        self.database.mark_message_failed(message_id, error)
        self._set_message_status(message_id, f"MESSAGE QUEUED FOR RETRY  ·  {error}")
        self.sidebar.refresh()
        if not self.chat.update_message_delivery_state(message_id, "failed"):
            self._refresh_current_conversation()

    def _attachment_status(self, message_id: int, status: str) -> None:
        if self.closing or self.database_closed:
            return
        self._set_message_status(message_id, status)

    def _set_message_status(self, message_id: int, status: str) -> None:
        if self.closing or self.database_closed:
            return
        conversation_id = self.database.conversation_id_for_message(message_id)
        if conversation_id is None:
            return
        self.conversation_statuses[conversation_id] = status
        if self.chat.conversation is not None and self.chat.conversation.id == conversation_id:
            self.network_status.setText(f"THIS CHAT  ·  {status}")

    def _direct_message_received(self, payload: dict[str, object]) -> None:
        if self.closing or self.database_closed:
            return
        sender = str(payload["sender"])
        own_pubkey = (
            self.identity.keys.public_key().to_hex() if self.identity is not None else ""
        )
        self_copy = bool(payload.get("self_copy")) and sender == own_pubkey
        # NIP-59 hides the real sender from the relay, so blocking must happen
        # after local decryption but before content or group controls are stored.
        if not self_copy and self.database.is_user_blocked(sender):
            return
        raw_content = str(payload.get("content") or "")
        reaction = decode_reaction(raw_content)
        if reaction is not None or raw_content.startswith(REACTION_PREFIX):
            if reaction is None:
                return
            if payload.get("group_id"):
                reaction_conversation_id = str(payload["group_id"])
            elif self_copy:
                peers = [
                    str(value)
                    for value in list(payload.get("recipients") or [])
                    if str(value) and str(value) != own_pubkey
                ]
                if not peers:
                    return
                reaction_conversation_id = self.database.direct_conversation_id(peers[0]) or ""
            else:
                reaction_conversation_id = self.database.direct_conversation_id(sender) or ""
            if not reaction_conversation_id:
                return
            changed_message_id = self.database.apply_message_reaction(
                str(payload["message_ref"]),
                str(reaction["target"]),
                sender,
                str(reaction["emoji"]),
                bool(reaction["active"]),
                int(payload["sent_at"]),
                reaction_conversation_id,
                own_pubkey,
            )
            if (
                changed_message_id is not None
                and self.chat.conversation is not None
                and self.chat.conversation.id == reaction_conversation_id
            ):
                self.chat.refresh_message_reactions(changed_message_id)
            return
        affected_conversation_id = ""
        if payload.get("group_id"):
            group_id = str(payload["group_id"])
            affected_conversation_id = group_id
            content = str(payload["content"])
            control: dict[str, str] | None = None
            if content.startswith(GROUP_CONTROL_PREFIX):
                try:
                    parsed = json.loads(content.removeprefix(GROUP_CONTROL_PREFIX))
                    if (
                        isinstance(parsed, dict)
                        and str(parsed.get("actor") or "") == sender
                        and str(parsed.get("action") or "")
                        in {"join", "leave", "delete", "rename"}
                    ):
                        control = {key: str(value) for key, value in parsed.items()}
                except (TypeError, ValueError, json.JSONDecodeError):
                    control = None
            if control and control["action"] == "delete":
                if self.database.group_creator(group_id) == sender:
                    self.database.delete_group(group_id)
                    self.conversation_statuses.pop(group_id, None)
                    self.sidebar.refresh()
                    if self.chat.conversation is not None and self.chat.conversation.id == group_id:
                        self.chat.clear_conversation()
                    self.network_status.setText(
                        f"GROUP CLOSED BY CREATOR  ·  {control.get('name') or sender[:12]}"
                    )
                    return
                control = None
            if control and control["action"] == "leave":
                content = f"👋 {control.get('name') or sender[:12]} left the group."
            elif control and control["action"] == "join":
                content = f"🔐 {control.get('name') or sender[:12]} joined the group."
            elif control and control["action"] == "rename":
                previous = control.get("previous") or sender[:12]
                current = control.get("name") or sender[:12]
                content = f"✎ {previous} changed their username to {current}."
            inserted = self.database.add_group_message(
                group_id,
                str(payload.get("subject") or "Encrypted group"),
                list(payload.get("recipients") or []),
                sender,
                content,
                str(payload["event_id"]),
                int(payload["sent_at"]),
                str(payload.get("sender_name") or ""),
                str(payload.get("attachment_path") or ""),
                str(payload.get("attachment_mime") or ""),
                str(payload.get("message_ref") or ""),
                system=bool(control),
                recovered_outgoing=self_copy,
            )
            if inserted and control and control["action"] == "leave":
                self.database.remove_group_member(group_id, sender)
            elif inserted and control and control["action"] == "join":
                self.database.add_group_member(group_id, sender)
        else:
            if self_copy:
                recipients = [
                    str(value)
                    for value in list(payload.get("recipients") or [])
                    if str(value) and str(value) != own_pubkey
                ]
                if not recipients:
                    return
                affected_conversation_id = self.database.ensure_direct_conversation(
                    recipients[0], reveal=False
                )
                inserted = self.database.add_recovered_outgoing_message(
                    recipients[0],
                    own_pubkey,
                    str(payload["content"]),
                    str(payload["event_id"]),
                    int(payload["sent_at"]),
                    str(payload.get("attachment_path") or ""),
                    str(payload.get("attachment_mime") or ""),
                    str(payload.get("message_ref") or ""),
                )
            else:
                affected_conversation_id = self.database.ensure_direct_conversation(
                    sender, reveal=False
                )
                inserted = self.database.add_incoming_message(
                    sender,
                    str(payload["content"]),
                    str(payload["event_id"]),
                    int(payload["sent_at"]),
                    str(payload.get("attachment_path") or ""),
                    str(payload.get("attachment_mime") or ""),
                    str(payload.get("message_ref") or ""),
                )
        if inserted:
            is_current_conversation = (
                self.chat.conversation is not None
                and self.chat.conversation.id == affected_conversation_id
            )
            if is_current_conversation:
                self.database.mark_read(self.chat.conversation.id)
                self._refresh_current_conversation()
            else:
                self.sidebar.refresh()

    def _refresh_current_conversation(self) -> None:
        if self.chat.conversation is None:
            return
        keep_at_latest = self.chat.is_near_bottom()
        conversation_id = self.chat.conversation.id
        self.sidebar.refresh()
        self.sidebar.select_conversation(conversation_id)
        item = self.sidebar.list_widget.currentItem()
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == conversation_id:
            self.chat.show_conversation(
                item.data(Qt.ItemDataRole.UserRole + 1),
                scroll_to_latest=keep_at_latest,
            )

    def _sync_moderation(self) -> None:
        admin_key = self.database.get_setting("moderation.admin_npub", "").strip()
        if not admin_key:
            return
        if self.moderation_worker is not None and self.moderation_worker.isRunning():
            return
        relays = [
            self.database.get_setting("network.relay", "wss://relay.damus.io"),
            self.database.get_setting("network.relay_fallback", "wss://nos.lol"),
        ]
        relays = list(dict.fromkeys(value.strip() for value in relays if value.strip()))
        self.network_status.setText("SYNCING SIGNED FSOCIETY MODERATION LIST…")
        self.moderation_worker = ModerationSyncWorker(admin_key, relays)
        self.moderation_worker.synced.connect(self._moderation_synced)
        self.moderation_worker.failed.connect(self._moderation_failed)
        self.moderation_worker.finished.connect(self._moderation_finished)
        self.moderation_worker.start()

    def _moderation_synced(self, users: list[str], posts: list[str], event_id: str) -> None:
        if self.closing or self.database_closed:
            return
        self.database.replace_moderation_blocks(users, posts, event_id)
        self.network_status.setText(
            f"MODERATION VERIFIED  ·  {len(users)} USERS  ·  {len(posts)} POSTS"
        )
        self.sidebar.refresh()
        if self.chat.conversation is not None:
            self.chat.show_conversation(self.chat.conversation, force_reload=True)

    def _moderation_failed(self, error: str) -> None:
        if self.closing:
            return
        self.network_status.setText(f"MODERATION SYNC FAILED  ·  {error}")

    def _moderation_finished(self) -> None:
        if self.moderation_worker is not None:
            self.moderation_worker.deleteLater()
        self.moderation_worker = None

    def _conversation_selected(self, conversation: Conversation) -> None:
        self.database.mark_read(conversation.id)
        self.chat.show_conversation(replace(conversation, unread_count=0))
        QTimer.singleShot(0, self._refresh_sidebar_read_state)
        status = self.conversation_statuses.get(conversation.id)
        if status:
            self.network_status.setText(f"THIS CHAT  ·  {status}")
        elif self.transport_connected:
            self.network_status.setText(self.global_status)

    def _refresh_sidebar_read_state(self) -> None:
        if self.closing or self.database_closed:
            return
        self.sidebar.refresh(select_first=False)

    def _message_sent(self, conversation_id: str) -> None:
        self.sidebar.refresh()
        self.sidebar.select_conversation(conversation_id)
        item = self.sidebar.list_widget.currentItem()
        if item is not None:
            self.chat.show_conversation(item.data(Qt.ItemDataRole.UserRole + 1))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.database_closed:
            super().closeEvent(event)
            return
        if self.moderation_worker is not None and self.moderation_worker.isRunning():
            self.network_status.setText("WAITING FOR MODERATION SYNC TO FINISH BEFORE CLOSING…")
            event.ignore()
            return
        self.closing = True
        if self.transport is not None and self.transport.isRunning():
            self.transport.requestInterruption()
            if not self.transport.wait(7000):
                self.network_status.setText("WAITING FOR NOSTR TRANSPORT TO CLOSE…")
                self.closing = False
                event.ignore()
                return
        self.idle_visualization.shutdown()
        # Deliver already-queued transport signals while the database is still
        # open. Their slots see ``closing`` and return without touching state.
        QApplication.processEvents()
        self.database.close()
        self.database_closed = True
        super().closeEvent(event)
