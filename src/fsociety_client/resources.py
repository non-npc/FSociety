from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QSplashScreen


DOS_FONT_FAMILY = "Perfect DOS VGA 437 Win"


def resource_path(filename: str) -> Path:
    """Resolve a client asset in source checkouts and PyInstaller bundles."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        return Path(bundle_root, "assets", filename)
    return Path(__file__).resolve().parents[2] / "assets" / filename


def load_application_font() -> str:
    """Register the bundled DOS font and return its actual embedded family."""
    font_id = QFontDatabase.addApplicationFont(str(resource_path("dos.ttf")))
    if font_id < 0:
        return "Cascadia Mono"
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else DOS_FONT_FAMILY


def create_hud_icon(kind: str, size: int = 20, color: str = "#4debf3") -> QIcon:
    """Draw dependable UI glyphs without relying on a system icon font."""
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(1.5, size / 11))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    if kind == "search":
        painter.drawEllipse(QRectF(size * 0.18, size * 0.15, size * 0.48, size * 0.48))
        painter.drawLine(
            QPointF(size * 0.61, size * 0.60), QPointF(size * 0.84, size * 0.84)
        )
    elif kind == "info":
        painter.drawEllipse(QRectF(size * 0.12, size * 0.12, size * 0.76, size * 0.76))
        painter.drawPoint(QPointF(size * 0.50, size * 0.34))
        painter.drawLine(
            QPointF(size * 0.50, size * 0.48), QPointF(size * 0.50, size * 0.70)
        )
    elif kind == "more":
        brush = painter.brush()
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = max(1.5, size * 0.09)
        for x in (0.24, 0.50, 0.76):
            painter.drawEllipse(QPointF(size * x, size * 0.50), radius, radius)
        painter.setBrush(brush)
    painter.end()
    return QIcon(canvas)


def create_splash() -> QSplashScreen:
    artwork = QPixmap(str(resource_path("fsociety.png")))
    if artwork.isNull():
        artwork = QPixmap(320, 320)
        artwork.fill(QColor("black"))
    artwork = artwork.scaled(
        320,
        320,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(380, 390)
    canvas.fill(QColor("black"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap((canvas.width() - artwork.width()) // 2, 22, artwork)
    painter.setPen(QColor("white"))
    painter.setFont(QFont(DOS_FONT_FAMILY, 12, QFont.Weight.DemiBold))
    painter.drawText(
        QRect(0, 350, canvas.width(), 28),
        Qt.AlignmentFlag.AlignCenter,
        "loading...",
    )
    painter.end()
    return QSplashScreen(canvas, Qt.WindowType.WindowStaysOnTopHint)
