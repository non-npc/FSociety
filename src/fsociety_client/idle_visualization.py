from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication, QWidget


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class NeonSunsetDrive(QWidget):
    """Native Qt port of RetroStudio's Neon Sunset Drive / Rolling Hills preset."""

    HORIZON_Y = 0.44
    VANISHING_X = 0.5
    CAMERA_HEIGHT = 1.2
    ROAD_WIDTH = 2.3
    ROAD_LANES = 4
    GRID_SPACING = 1.35
    DEPTH_LINES = 28
    TERRAIN_WIDTH = 6.5
    TERRAIN_HEIGHT = 1.7
    TERRAIN_ROUGHNESS = 0.75
    TERRAIN_COLUMNS = 11
    TERRAIN_SAMPLES = 48
    LOOP_DURATION = 6.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        rng = random.Random(1986)
        self.phases = [rng.uniform(0.0, math.tau) for _ in range(6)]
        self.started_at = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

    def start(self) -> None:
        self.started_at = time.monotonic()
        self.setGeometry(self.parentWidget().rect() if self.parentWidget() else self.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.timer.start()
        self.update()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def _project(
        self,
        x: float,
        elevation: float,
        depth: float,
        horizon: float,
        vanishing: float,
        focal: float,
    ) -> QPointF:
        safe_depth = max(0.001, depth)
        return QPointF(
            vanishing + x * focal / safe_depth,
            horizon + (self.CAMERA_HEIGHT - elevation) * focal / safe_depth,
        )

    def _terrain_height(self, x: float, world_depth: float, loop_length: float) -> float:
        road_half = self.ROAD_WIDTH / 2.0
        distance = max(0.0, abs(x) - road_half)
        span = max(0.001, self.TERRAIN_WIDTH - road_half)
        edge = _clamp(distance / span, 0.0, 1.0)
        edge = edge * edge * (3.0 - 2.0 * edge)
        if edge <= 0.0:
            return 0.0
        side_phase = (-1.0 if x < 0 else 1.0) * self.phases[4]
        depth_angle = world_depth / loop_length * math.tau
        cross_angle = distance / span * math.pi
        first = math.sin(
            depth_angle * 2.0 + cross_angle * 1.25 + self.phases[0] + side_phase
        )
        second = math.sin(
            depth_angle * 5.0 - cross_angle * 2.1 + self.phases[1] - side_phase * 0.7
        )
        third = math.sin(
            depth_angle * 9.0 + cross_angle * 3.7 + self.phases[2] + side_phase * 1.3
        )
        broad = math.sin(depth_angle - cross_angle * 0.6 + self.phases[3])
        value = (
            0.48
            + first * 0.24
            + second * 0.16 * self.TERRAIN_ROUGHNESS
            + third * 0.09 * self.TERRAIN_ROUGHNESS
            + broad * 0.18
        )
        shaped = _clamp(value, 0.0, 1.0) ** 1.45
        return self.TERRAIN_HEIGHT * edge**0.55 * shaped

    def _depth_color(self, color: QColor, depth: float, far_depth: float) -> QColor:
        fade = 1.0 - _clamp((depth - 1.0) / max(0.001, far_depth - 1.0), 0.0, 1.0)
        strength = 0.2 + fade * 0.8
        return QColor(color.red(), color.green(), color.blue(), round(255 * strength))

    def _near_fade(self, depth: float) -> float:
        amount = _clamp((depth - 1.0) / (self.GRID_SPACING * 2.75), 0.0, 1.0)
        return amount * amount * (3.0 - 2.0 * amount)

    def _draw_sun(self, painter: QPainter, width: int, height: int, horizon: float) -> None:
        center = QPointF(width * 0.5, height * 0.28)
        radius = max(2.0, min(width, height) * 0.14)
        ellipse = QPainterPath()
        ellipse.addEllipse(center, radius, radius)
        painter.save()
        painter.setClipPath(ellipse)
        painter.setClipRect(QRectF(0, 0, width, horizon), Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 58, 174, 50))
        painter.drawEllipse(center, radius * 1.22, radius * 1.22)
        gradient = QLinearGradient(0, center.y() - radius, 0, center.y() + radius)
        gradient.setColorAt(0.0, QColor("#fff36b"))
        gradient.setColorAt(1.0, QColor("#ff3aae"))
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)
        stripe_height = radius * 0.92 / 6.0
        striped_start = center.y() - radius * 0.02
        painter.setBrush(QColor("#17052f"))
        for stripe in range(7):
            y = striped_start + stripe * stripe_height
            painter.drawRect(
                QRectF(center.x() - radius, y, radius * 2.0, stripe_height * 0.38)
            )
        painter.restore()

    @staticmethod
    def _draw_glowing_polyline(
        painter: QPainter, points: list[QPointF], color: QColor, width: int = 1
    ) -> None:
        if len(points) < 2:
            return
        polygon = QPolygonF(points)
        glow = QColor(color)
        glow.setAlpha(65)
        painter.setPen(QPen(glow, width + 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPolyline(polygon)
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPolyline(polygon)

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        width = max(1, self.width())
        height = max(1, self.height())
        horizon = height * self.HORIZON_Y
        vanishing = width * self.VANISHING_X
        focal = max(1.0, height - horizon) / self.CAMERA_HEIGHT
        road_half = self.ROAD_WIDTH / 2.0
        far_depth = self.GRID_SPACING * self.DEPTH_LINES
        elapsed = time.monotonic() - self.started_at
        phase = (elapsed % self.LOOP_DURATION) / self.LOOP_DURATION
        camera_depth = phase * far_depth

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sky = QLinearGradient(0, 0, 0, horizon)
        sky.setColorAt(0.0, QColor("#05000f"))
        sky.setColorAt(1.0, QColor("#351068"))
        painter.fillRect(QRectF(0, 0, width, horizon), sky)
        painter.fillRect(QRectF(0, horizon, width, height - horizon), QColor("#07000f"))
        self._draw_sun(painter, width, height, horizon)

        left_near = self._project(-road_half, 0.0, 1.0, horizon, vanishing, focal)
        right_near = self._project(road_half, 0.0, 1.0, horizon, vanishing, focal)
        road = QPolygonF(
            [
                QPointF(vanishing, horizon),
                left_near,
                QPointF(left_near.x(), height),
                QPointF(right_near.x(), height),
                right_near,
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#09000f"))
        painter.drawPolygon(road)
        reflection = QLinearGradient(vanishing, horizon, vanishing, height)
        reflection.setColorAt(0.0, QColor(255, 58, 174, 65))
        reflection.setColorAt(1.0, QColor(255, 58, 174, 0))
        painter.setBrush(reflection)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(vanishing - width * 0.01, horizon),
                    QPointF(vanishing + width * 0.01, horizon),
                    QPointF(vanishing + width * 0.12, height),
                    QPointF(vanishing - width * 0.12, height),
                ]
            )
        )

        road_color = QColor("#ff43d1")
        terrain_color = QColor("#ff4fd8")
        for lane in range(self.ROAD_LANES + 1):
            x = -road_half + lane / self.ROAD_LANES * road_half * 2.0
            near = self._project(x, 0.0, 1.0, horizon, vanishing, focal)
            self._draw_glowing_polyline(
                painter, [near, QPointF(vanishing, horizon)], road_color, 2
            )

        first_grid = math.floor((camera_depth + 1.0) / self.GRID_SPACING) * self.GRID_SPACING
        depths: list[float] = []
        world_grid = first_grid
        while world_grid <= camera_depth + far_depth + self.GRID_SPACING:
            depth = world_grid - camera_depth
            if 1.0 <= depth <= far_depth:
                depths.append(depth)
            world_grid += self.GRID_SPACING
        depths.sort(reverse=True)
        for depth in depths:
            color = self._depth_color(road_color, depth, far_depth)
            left = self._project(-road_half, 0.0, depth, horizon, vanishing, focal)
            right = self._project(road_half, 0.0, depth, horizon, vanishing, focal)
            self._draw_glowing_polyline(painter, [left, right], color, 2)

        groups = (
            [
                -self.TERRAIN_WIDTH
                + index / (self.TERRAIN_COLUMNS - 1) * (self.TERRAIN_WIDTH - road_half)
                for index in range(self.TERRAIN_COLUMNS)
            ],
            [
                road_half
                + index / (self.TERRAIN_COLUMNS - 1) * (self.TERRAIN_WIDTH - road_half)
                for index in range(self.TERRAIN_COLUMNS)
            ],
        )
        for depth in depths:
            world_depth = (camera_depth + depth) % far_depth
            color = self._depth_color(terrain_color, depth, far_depth)
            for x_values in groups:
                points = []
                for x in x_values:
                    elevation = self._terrain_height(x, world_depth, far_depth)
                    elevation *= self._near_fade(depth)
                    points.append(
                        self._project(x, elevation, depth, horizon, vanishing, focal)
                    )
                self._draw_glowing_polyline(painter, points, color, 1)

        sample_depths = [
            math.exp(
                math.log(1.0)
                + index / (self.TERRAIN_SAMPLES - 1) * math.log(far_depth)
            )
            for index in range(self.TERRAIN_SAMPLES)
        ]
        for x_values in groups:
            for x in x_values:
                points = []
                for depth in reversed(sample_depths):
                    world_depth = (camera_depth + depth) % far_depth
                    elevation = self._terrain_height(x, world_depth, far_depth)
                    elevation *= self._near_fade(depth)
                    points.append(
                        self._project(x, elevation, depth, horizon, vanishing, focal)
                    )
                self._draw_glowing_polyline(painter, points, terrain_color, 1)

        painter.setPen(QColor(77, 235, 243, 190))
        painter.setFont(QFont("Perfect DOS VGA 437 Win", 10, QFont.Weight.Bold))
        painter.drawText(
            QRectF(0, height - 58, width, 22),
            Qt.AlignmentFlag.AlignCenter,
            "FSOCIETY  //  IDLE NETWORK MODE",
        )
        painter.setPen(QColor(255, 255, 255, 165))
        painter.drawText(
            QRectF(0, height - 34, width, 18),
            Qt.AlignmentFlag.AlignCenter,
            "MOVE MOUSE OR PRESS ANY KEY TO RESUME",
        )
        painter.end()


class IdleVisualizationController(QObject):
    ACTIVITY_EVENTS = {
        QEvent.Type.KeyPress,
        QEvent.Type.KeyRelease,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseMove,
        QEvent.Type.Wheel,
        QEvent.Type.TouchBegin,
        QEvent.Type.TouchUpdate,
        QEvent.Type.TouchEnd,
        QEvent.Type.TabletPress,
        QEvent.Type.TabletMove,
        QEvent.Type.TabletRelease,
    }

    def __init__(self, window: QWidget, database, timeout_seconds: int = 300) -> None:
        super().__init__(window)
        self.window = window
        self.database = database
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.enabled = True
        self.last_activity = time.monotonic()
        self.overlay = NeonSunsetDrive(window)
        self.check_timer = QTimer(self)
        self.check_timer.setInterval(1000)
        self.check_timer.timeout.connect(self.check_idle)
        QApplication.instance().installEventFilter(self)
        self.refresh_settings()
        self.check_timer.start()

    def refresh_settings(self) -> None:
        self.enabled = self.database.get_setting(
            "ui.idle_visualization", "true"
        ) == "true"
        self.last_activity = time.monotonic()
        if not self.enabled:
            self.overlay.stop()

    def check_idle(self) -> None:
        if (
            not self.enabled
            or self.overlay.isVisible()
            or not self.window.isVisible()
            or self.window.isMinimized()
            or QApplication.activeModalWidget() is not None
        ):
            return
        if time.monotonic() - self.last_activity >= self.timeout_seconds:
            self.overlay.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window and event.type() == QEvent.Type.Resize:
            self.overlay.setGeometry(self.window.rect())
        if event.type() in self.ACTIVITY_EVENTS:
            self.last_activity = time.monotonic()
            if self.overlay.isVisible():
                self.overlay.stop()
                return True
        return False

    def shutdown(self) -> None:
        self.check_timer.stop()
        self.overlay.stop()
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

