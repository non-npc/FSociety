from __future__ import annotations

import html
import math
import re
import shutil
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImageReader, QMovie, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .models import Conversation, Message
from .theme import CORAL, CYAN, LINE, MUTED, PANEL_2, TEXT, VOID


WEB_LINK_PATTERN = re.compile(
    r"\[(?P<label>[^\]\r\n]+)\]\((?P<markdown>https?://[^\s<>\"')]+)\)"
    r"|(?<![\w@])(?P<bare>"
    r"(?:https?://|www\.)[^\s<>\"'\]]+"
    r"|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?:/[^\s<>\"'\]]*)?"
    r")",
    re.IGNORECASE,
)


def linkify_message_text(value: str) -> str:
    """Escape user content and add anchors for explicitly recognized web URLs."""
    output: list[str] = []
    cursor = 0
    for match in WEB_LINK_PATTERN.finditer(value):
        output.append(html.escape(value[cursor : match.start()]))
        markdown_url = match.group("markdown")
        visible = match.group("label") if markdown_url else (match.group("bare") or "")
        target = markdown_url or visible
        trailing = ""
        if not markdown_url:
            while target and target[-1] in ".,!?;:)":
                trailing = target[-1] + trailing
                target = target[:-1]
                visible = visible[:-1]
        href = target if target.lower().startswith(("http://", "https://")) else f"https://{target}"
        output.append(
            f'<a href="{html.escape(href, quote=True)}" style="color:{CYAN};">'
            f"{html.escape(visible)}</a>{html.escape(trailing)}"
        )
        cursor = match.end()
    output.append(html.escape(value[cursor:]))
    return "".join(output).replace("\n", "<br>")


def clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)  # type: ignore[arg-type]


class BrandMark(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Expand or collapse navigation")

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(31, 0)
        path.lineTo(44, 13)
        path.lineTo(44, 44)
        path.lineTo(13, 44)
        path.lineTo(0, 31)
        path.closeSubpath()
        painter.fillPath(path, QColor(CYAN))
        painter.setPen(QColor(VOID))
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 15, QFont.Weight.DemiBold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "f_")


class HudTelemetry(QWidget):
    """Compact view of live relay connectivity reported by NostrTransport."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.relay_states: dict[str, str] = {}
        self.inbox_status = "WAIT"

    def set_relays(self, relays: list[str]) -> None:
        self.relay_states = {relay: "FOUND" for relay in relays}
        self.inbox_status = "WAIT"
        self.update()

    def update_relay(self, relay: str, status: str) -> None:
        if relay == "NIP-17 PRIVATE INBOX":
            self.inbox_status = status.upper()
        else:
            self.relay_states[relay] = status.upper()
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(bounds, QColor("#0a1113"))
        painter.setPen(QPen(QColor("#27464c"), 1))
        painter.drawRect(bounds)

        states = list(self.relay_states.values())
        total = len(states)
        connected = sum(state == "CONNECTED" for state in states)
        unavailable = sum(state == "UNAVAILABLE" for state in states)
        percentage = round(connected * 100 / total) if total else 0
        samples = np.fromiter(
            (
                1.0 if state == "CONNECTED" else 0.48 if state == "CONNECTING" else 0.18
                for state in states
            ),
            dtype=float,
        )

        ring = QRectF(12, 14, 40, 40)
        painter.setPen(QPen(QColor("#293a3e"), 6))
        painter.drawArc(ring, 0, 360 * 16)
        painter.setPen(QPen(QColor(CYAN), 6))
        painter.drawArc(ring, 90 * 16, -round(360 * 16 * percentage / 100))
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 7, QFont.Weight.DemiBold))
        painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, f"{percentage}%")

        left = 69
        available = max(40, self.width() - left - 43)
        painter.setPen(QColor(MUTED))
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 6))
        painter.drawText(left, 18, f"RELAY MESH     {connected}/{total}")
        count = max(1, len(samples))
        bar_width = max(4.0, min(12.0, (available - max(0, count - 1) * 3) / count))
        for index, sample in enumerate(samples):
            height = float(sample) * 22
            state = states[index]
            color = QColor(CYAN if state == "CONNECTED" else CORAL if state == "UNAVAILABLE" else MUTED)
            painter.fillRect(QRectF(left + index * (bar_width + 3), 52 - height, bar_width, height), color)
        painter.setPen(QColor(CYAN if self.inbox_status == "CONNECTED" else CORAL))
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 6, QFont.Weight.DemiBold))
        painter.drawText(self.width() - 30, 22, "N17")
        painter.drawText(self.width() - 30, 34, f"E{unavailable}")
        painter.drawText(
            self.width() - 30,
            46,
            "OK" if self.inbox_status == "CONNECTED" else self.inbox_status[:4],
        )


class RelayMeshView(QWidget):
    """Large live network map driven exclusively by configured relay states."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.relay_states: dict[str, str] = {}
        self.inbox_status = "WAIT"

    def set_relays(self, relays: list[str]) -> None:
        self.relay_states = {relay: "FOUND" for relay in relays}
        self.inbox_status = "WAIT"
        self.update()

    def update_relay(self, relay: str, status: str) -> None:
        if relay == "NIP-17 PRIVATE INBOX":
            self.inbox_status = status.upper()
        else:
            self.relay_states[relay] = status.upper()
        self.update()

    @staticmethod
    def _state_color(state: str) -> QColor:
        if state == "CONNECTED":
            return QColor(CYAN)
        if state == "UNAVAILABLE":
            return QColor(CORAL)
        return QColor(MUTED)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(bounds, QColor("#0a1113"))
        painter.setPen(QPen(QColor("#27464c"), 1))
        painter.drawRect(bounds)
        center = QPointF(bounds.center())
        relays = list(self.relay_states.items())
        radius = max(62.0, min(bounds.width(), bounds.height()) * 0.34)
        positions: list[QPointF] = []
        for index, _ in enumerate(relays):
            angle = -math.pi / 2 + (2 * math.pi * index / max(1, len(relays)))
            positions.append(
                QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius)
            )
        for position, (_, state) in zip(positions, relays):
            painter.setPen(QPen(self._state_color(state), 2))
            painter.drawLine(center, position)

        connected = sum(state == "CONNECTED" for state in self.relay_states.values())
        painter.setPen(QPen(QColor(CYAN), 3))
        painter.setBrush(QColor("#102024"))
        painter.drawEllipse(center, 49, 49)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 12, QFont.Weight.Bold))
        painter.drawText(
            QRectF(center.x() - 45, center.y() - 18, 90, 22),
            Qt.AlignmentFlag.AlignCenter,
            "FSOCIETY",
        )
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 9))
        painter.setPen(QColor(CYAN if self.inbox_status == "CONNECTED" else MUTED))
        painter.drawText(
            QRectF(center.x() - 45, center.y() + 5, 90, 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{connected}/{len(relays)} ONLINE",
        )
        for position, (relay, state) in zip(positions, relays):
            color = self._state_color(state)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QColor("#101718"))
            painter.drawEllipse(position, 15, 15)
            painter.setPen(color)
            painter.setFont(QFont("Perfect DOS VGA 437 Win", 8, QFont.Weight.DemiBold))
            label = relay.removeprefix("wss://").removeprefix("ws://")
            painter.drawText(
                QRectF(position.x() - 105, position.y() + 20, 210, 34),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                f"{label}\n{state}",
            )


class AvatarLabel(QLabel):
    def __init__(
        self,
        initials: str,
        accent: str = "cyan",
        size: int = 42,
        image_png: bytes | None = None,
    ) -> None:
        super().__init__(initials)
        colors = {"cyan": CYAN, "coral": CORAL, "violet": "#b595ff"}
        color = colors.get(accent, CYAN)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(size, size)
        self.setStyleSheet(
            f"background:#182326;color:{color};border:1px solid #354548;"
            "font:600 10px 'Perfect DOS VGA 437 Win';"
        )
        if image_png:
            pixmap = QPixmap()
            if pixmap.loadFromData(image_png):
                self.setText("")
                self.setPixmap(
                    pixmap.scaled(
                        size - 2,
                        size - 2,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )


class ConversationRow(QWidget):
    def __init__(self, conversation: Conversation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.conversation_id = conversation.id
        self.setMinimumHeight(66)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(
            AvatarLabel(
                conversation.initials,
                conversation.accent,
                image_png=conversation.profile_picture_png,
            )
        )

        copy = QVBoxLayout()
        copy.setSpacing(3)
        name = QLabel(conversation.display_name)
        name.setStyleSheet(f"color:{TEXT};font-weight:600;")
        preview = QLabel(conversation.last_message)
        preview.setObjectName("muted")
        preview.setMaximumWidth(150)
        copy.addWidget(name)
        copy.addWidget(preview)
        layout.addLayout(copy, 1)

        meta = QVBoxLayout()
        meta.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        timestamp = QLabel(conversation.time_label)
        timestamp.setStyleSheet(f"color:{MUTED};font:9px 'Perfect DOS VGA 437 Win';")
        meta.addWidget(timestamp, alignment=Qt.AlignmentFlag.AlignRight)
        if conversation.unread_count:
            unread = QLabel(str(conversation.unread_count))
            unread.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unread.setFixedSize(19, 19)
            unread.setStyleSheet(
                f"background:{CORAL};color:white;font:600 9px 'Perfect DOS VGA 437 Win';"
            )
            meta.addWidget(unread, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(meta)


class InlineImageAttachment(QLabel):
    """Render static images efficiently and play GIF/APNG media in place."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.animation: QMovie | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:#080d0e;border:1px solid {LINE};padding:3px;")
        reader = QImageReader(path)
        animated = reader.supportsAnimation()
        if animated:
            movie = QMovie(path, parent=self)
            if movie.isValid():
                size = reader.size()
                if size.isValid():
                    size.scale(QSize(420, 320), Qt.AspectRatioMode.KeepAspectRatio)
                    movie.setScaledSize(size)
                movie.setCacheMode(QMovie.CacheMode.CacheAll)
                self.animation = movie
                self.setMovie(movie)
                movie.start()
                return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.setPixmap(
                pixmap.scaled(
                    420,
                    320,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class VideoPlayerDialog(QDialog):
    """Play a verified local video outside the scrolling message hierarchy."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"fsociety video // {Path(path).name}")
        self.resize(760, 500)
        self.setStyleSheet("border:0;background:#080d0e;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(4)
        self.video = QVideoWidget(self)
        self.video.setMinimumSize(640, 360)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        layout.addWidget(self.video)

        controls = QHBoxLayout()
        controls.setContentsMargins(3, 0, 3, 0)
        self.play = QPushButton("▶  PLAY")
        self.play.setObjectName("createAction")
        self.play.setFixedWidth(92)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 0)
        self.time = QLabel("00:00 / 00:00")
        self.time.setStyleSheet(f"color:{MUTED};font:8px 'Perfect DOS VGA 437 Win';border:0;")
        controls.addWidget(self.play)
        controls.addWidget(self.position, 1)
        controls.addWidget(self.time)
        layout.addLayout(controls)

        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.75)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.play.clicked.connect(self._toggle)
        self.position.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.errorOccurred.connect(self._error)

    @staticmethod
    def _clock(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _duration_changed(self, duration: int) -> None:
        self.position.setRange(0, duration)
        self._position_changed(self.player.position())

    def _position_changed(self, position: int) -> None:
        if not self.position.isSliderDown():
            self.position.setValue(position)
        self.time.setText(
            f"{self._clock(position)} / {self._clock(self.player.duration())}"
        )

    def _state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play.setText("❚❚  PAUSE" if state == QMediaPlayer.PlaybackState.PlayingState else "▶  PLAY")

    def _error(self, _error, error_text: str) -> None:  # type: ignore[no-untyped-def]
        self.play.setText("UNPLAYABLE")
        self.play.setEnabled(False)
        self.setToolTip(error_text or "This system does not have a codec for the video.")

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.player.stop()
        self.player.setVideoOutput(None)
        self.player.setAudioOutput(None)
        super().closeEvent(event)


class VideoAttachment(QWidget):
    """Launch video playback without creating a native surface in the chat list."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.player_dialog: VideoPlayerDialog | None = None
        self.setStyleSheet(f"border:1px solid {LINE};background:#080d0e;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        filename = QLabel(Path(path).name)
        filename.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filename.setWordWrap(True)
        filename.setStyleSheet(f"color:{TEXT};border:0;")
        layout.addWidget(filename)

        open_video = QPushButton("▶  OPEN VIDEO")
        open_video.setObjectName("openVideo")
        open_video.setToolTip("Open this video in a dedicated player window")
        open_video.clicked.connect(self._open_player)
        layout.addWidget(open_video)

    def _open_player(self) -> None:
        if self.player_dialog is not None and self.player_dialog.isVisible():
            self.player_dialog.raise_()
            self.player_dialog.activateWindow()
            return
        self.player_dialog = VideoPlayerDialog(self.path, self.window())
        self.player_dialog.finished.connect(self._player_closed)
        self.player_dialog.show()

    def _player_closed(self) -> None:
        if self.player_dialog is not None:
            self.player_dialog.deleteLater()
        self.player_dialog = None


class FileAttachment(QWidget):
    """Offer a verified generic attachment without automatically opening it."""

    def __init__(self, path: str, mime_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.setStyleSheet(f"border:1px solid {LINE};background:#080d0e;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        details = QLabel(f"FILE  //  {self.path.name}\n{mime_type or 'application/octet-stream'}")
        details.setWordWrap(True)
        details.setStyleSheet(f"color:{TEXT};border:0;")
        save = QPushButton("SAVE FILE AS…")
        save.setObjectName("createAction")
        save.clicked.connect(self._save_as)
        layout.addWidget(details, 1)
        layout.addWidget(save)

    def _save_as(self) -> None:
        destination, _ = QFileDialog.getSaveFileName(
            self.window(), "Save decrypted attachment", self.path.name
        )
        if not destination:
            return
        try:
            source = self.path.resolve()
            target = Path(destination).resolve()
            if source != target:
                shutil.copy2(source, target)
        except OSError as error:
            QMessageBox.warning(self.window(), "Save failed", str(error))


class MessageBubble(QFrame):
    def __init__(
        self,
        message: Message,
        outgoing: bool | None = None,
        group: bool = False,
        own_name: str = "",
        show_images: bool = True,
        show_videos: bool = True,
        message_font_size: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.message_id = message.id
        outgoing = message.direction == "outgoing" if outgoing is None else outgoing
        system = message.direction == "system"
        border = CORAL if outgoing else (MUTED if system else CYAN)
        background = "#15282c" if outgoing else ("#111617" if system else PANEL_2)
        self.setMaximumWidth(500)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(f"QFrame{{background:{background};border:1px solid {border};}}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 8)
        layout.setSpacing(6)
        sender_name = ""
        if group and outgoing:
            code = "SIGNED //"
            sender_name = own_name or "YOU"
        elif group and not system:
            sender = message.author_name.strip()
            if not sender and message.author_pubkey:
                sender = f"npub:{message.author_pubkey[:16]}…"
            code = "GROUP //"
            sender_name = sender or "UNKNOWN SENDER"
        else:
            code = "SIGNED // YOU" if outgoing else (
                "SYSTEM // LOCAL" if system else f"MSG // {message.protocol}"
            )
        protocol = QLabel(code)
        protocol.setStyleSheet(f"color:{border};font:600 7px 'Perfect DOS VGA 437 Win';border:0;")
        sender_label = None
        if sender_name:
            sender_label = QLabel(sender_name)
            sender_label.setObjectName("messageSender")
            sender_label.setStyleSheet(
                f"color:{border};font-weight:600;font-size:{message_font_size}px;border:0;"
            )
        # Attachment descriptions contain filenames such as archive.zip. Since
        # .zip is also a public internet suffix, the ordinary chat URL detector
        # would incorrectly turn that local filename into a browser link. Media
        # metadata is generated by fsociety and should remain plain display text;
        # the dedicated attachment control handles the local file instead.
        rendered_content = (
            html.escape(message.content).replace("\n", "<br>")
            if message.attachment_path
            else linkify_message_text(message.content)
        )
        text = QLabel(rendered_content)
        text.setObjectName("messageBody")
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        text.setOpenExternalLinks(True)
        text.setStyleSheet(f"color:{TEXT};font-size:{message_font_size}px;border:0;")
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label.setStyleSheet(f"color:{MUTED};font:7px 'Perfect DOS VGA 437 Win';border:0;")
        self.time_text = message.time_label
        self.set_delivery_state(message.delivery_state)
        layout.addWidget(protocol)
        if sender_label is not None:
            layout.addWidget(sender_label)
        if (
            show_images
            and message.attachment_path
            and message.attachment_mime.startswith("image/")
        ):
            layout.addWidget(InlineImageAttachment(message.attachment_path, self))
        elif (
            show_videos
            and message.attachment_path
            and message.attachment_mime.startswith("video/")
        ):
            layout.addWidget(VideoAttachment(message.attachment_path, self))
        elif message.attachment_path and (
            message.attachment_mime.startswith("image/")
            or message.attachment_mime.startswith("video/")
        ):
            media_type = "IMAGE" if message.attachment_mime.startswith("image/") else "VIDEO"
            hidden = QLabel(f"{media_type} PREVIEW HIDDEN BY GROUP SETTINGS")
            hidden.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hidden.setStyleSheet(
                f"color:{MUTED};background:#080d0e;border:1px solid {LINE};padding:14px;"
            )
            layout.addWidget(hidden)
        elif message.attachment_path:
            layout.addWidget(
                FileAttachment(message.attachment_path, message.attachment_mime, self)
            )
        layout.addWidget(text)
        layout.addWidget(self.time_label)

    def set_delivery_state(self, state: str) -> None:
        labels = {
            "relay-accepted": "ACCEPTED",
            "sending": "SENDING",
            "failed": "FAILED",
            "received": "RECEIVED",
            "local": "LOCAL",
        }
        normalized = state.casefold().strip()
        display = labels.get(normalized, normalized.upper().replace("-", " "))
        self.time_label.setText(f"{self.time_text}  {display}")


class MessageRow(QWidget):
    def __init__(
        self,
        message: Message,
        group: bool = False,
        own_pubkey: str = "",
        own_name: str = "",
        show_images: bool = True,
        show_videos: bool = True,
        message_font_size: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        outgoing = message.direction == "outgoing"
        if group and message.author_pubkey and own_pubkey:
            outgoing = message.author_pubkey == own_pubkey
        bubble = MessageBubble(
            message,
            outgoing,
            group,
            own_name,
            show_images,
            show_videos,
            message_font_size,
        )
        if message.direction == "system":
            layout.addStretch(1)
            layout.addWidget(bubble)
            layout.addStretch(1)
        elif outgoing:
            layout.addStretch(1)
            layout.addWidget(bubble)
        else:
            layout.addWidget(bubble)
            layout.addStretch(1)


class CornerFrame(QFrame):
    """A restrained HUD frame with cyan structural and coral corner marks."""

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(CORAL), 2))
        length = 18
        margin = 3
        points = (
            (QPointF(margin, margin + length), QPointF(margin, margin), QPointF(margin + length, margin)),
            (QPointF(self.width() - margin - length, margin), QPointF(self.width() - margin, margin), QPointF(self.width() - margin, margin + length)),
            (QPointF(margin, self.height() - margin - length), QPointF(margin, self.height() - margin), QPointF(margin + length, self.height() - margin)),
            (QPointF(self.width() - margin - length, self.height() - margin), QPointF(self.width() - margin, self.height() - margin), QPointF(self.width() - margin, self.height() - margin - length)),
        )
        for start, corner, end in points:
            painter.drawLine(start, corner)
            painter.drawLine(corner, end)
