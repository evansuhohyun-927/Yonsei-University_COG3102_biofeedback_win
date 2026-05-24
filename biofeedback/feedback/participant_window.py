import math
import time

import numpy as np
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QPointF
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QPolygonF, QPainterPath, QFont
from PyQt6.QtWidgets import QWidget, QLabel

from ..core.bus import EventBus


class _ParticipantBridge(QObject):
    beat = pyqtSignal()
    likert_show = pyqtSignal(str)
    likert_hide = pyqtSignal()

    def __init__(self, bus: EventBus):
        super().__init__()
        bus.subscribe("beat", lambda _ts: self.beat.emit())
        bus.subscribe("likert_show", lambda text: self.likert_show.emit(text or ""))
        bus.subscribe("likert_hide", lambda _: self.likert_hide.emit())


class ECGWidget(QWidget):
    """Continuously scrolling ECG trace with red neon glow effect.
    Stamps a synthesized PQRST complex on each 'beat' event."""

    def __init__(
        self,
        sample_rate: int = 250,
        duration_seconds: float = 5.0,
        cycle_duration: float = 0.50,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.sr = sample_rate
        self.duration = duration_seconds
        self.cycle_duration = cycle_duration

        self.buffer_size = int(sample_rate * duration_seconds)
        self.buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.write_pos = 0
        self.cycle_progress = -1.0
        self._last_tick = time.time()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60 fps

    def trigger_beat(self) -> None:
        self.cycle_progress = 0.0

    @staticmethod
    def _pqrst(t: float) -> float:
        def g(x: float, mu: float, sigma: float) -> float:
            return math.exp(-((x - mu) ** 2) / (2 * sigma * sigma))

        p = 0.10 * g(t, 0.18, 0.030)
        q = -0.12 * g(t, 0.40, 0.013)
        r = 1.00 * g(t, 0.46, 0.012)
        s = -0.20 * g(t, 0.52, 0.014)
        tw = 0.32 * g(t, 0.74, 0.045)
        return p + q + r + s + tw

    def _tick(self) -> None:
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        n_samples = max(1, int(dt * self.sr))
        n_samples = min(n_samples, self.buffer_size)
        for _ in range(n_samples):
            if self.cycle_progress >= 0.0:
                self.buffer[self.write_pos] = self._pqrst(self.cycle_progress)
                self.cycle_progress += 1.0 / (self.sr * self.cycle_duration)
                if self.cycle_progress >= 1.0:
                    self.cycle_progress = -1.0
            else:
                self.buffer[self.write_pos] = 0.0
            self.write_pos = (self.write_pos + 1) % self.buffer_size
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0))

        w = self.width()
        h = self.height()
        if w < 2 or h < 2:
            return
        cy = h * 0.5
        amp = h * 0.42

        # Build path once, stroke multiple times for neon glow
        n = self.buffer_size
        path = QPainterPath()
        for i in range(n):
            idx = (self.write_pos + i) % n
            x = i / (n - 1) * w
            y = cy - self.buffer[idx] * amp
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        # Outer halo: wide, very faint pure red
        p.setPen(QPen(QColor(255, 0, 30, 35), 14.0,
                      Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        # Mid glow: medium width, brighter red
        p.setPen(QPen(QColor(255, 30, 60, 110), 7.0,
                      Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        # Bright core: thin, near-white pinkish
        p.setPen(QPen(QColor(255, 160, 170, 255), 2.2,
                      Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)


class HeartWidget(QWidget):
    """Heart shape that scales up briefly on each 'beat' event."""

    def __init__(
        self,
        color: tuple[int, int, int] = (220, 60, 90),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._scale = 1.0
        self._color = QColor(*color)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)

    def trigger_beat(self) -> None:
        self._scale = 1.45

    def _animate(self) -> None:
        self._scale += (1.0 - self._scale) * 0.18
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2
        size = min(w, h) * 0.42 * self._scale

        n = 96
        poly = QPolygonF()
        for i in range(n + 1):
            t = 2 * math.pi * i / n
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t)
                  - 2 * math.cos(3 * t) - math.cos(4 * t))
            poly.append(QPointF(cx + x * size / 17.0, cy + y * size / 17.0))

        p.setBrush(QBrush(self._color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(poly)


class LikertOverlay(QLabel):
    """Centered white text shown during Likert prompts.
    Transparent background; ECG underneath is hidden separately.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("color: white; background: transparent;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        font = QFont("Arial", 24)
        font.setBold(True)
        self.setFont(font)
        self.hide()


class ParticipantWindow(QWidget):
    """Participant-facing display: black background, scrolling neon-red ECG
    in the middle, pulsing heart in the bottom-right corner.

    During Likert prompts, the ECG is hidden and a centered text overlay
    appears; the heart keeps beating. Key input (1-7) is forwarded to the
    next focusable widget (PsychoPy) — this window does NOT capture them.

    Press F to toggle fullscreen, Esc to exit fullscreen."""

    def __init__(self, bus: EventBus):
        super().__init__()
        self.setWindowTitle("Biofeedback - Participant View")
        self.resize(1100, 700)
        self.setStyleSheet("background-color: black;")
        # Prevent stealing keyboard focus from PsychoPy.
        # Likert keys (1-7) and space should reach PsychoPy's window.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # NOTE: WindowStaysOnTopHint는 제거 — PsychoPy ecg_renderer가 시각자극을
        # 직접 그리므로 이 창은 실험자 모니터링용. PsychoPy 위에 떠 있으면 안 됨.

        self.ecg = ECGWidget(parent=self)
        self.heart = HeartWidget(parent=self)
        self.likert = LikertOverlay(parent=self)
        # Make sure overlay is above ECG
        self.likert.raise_()

        self._bridge = _ParticipantBridge(bus)
        self._bridge.beat.connect(self.ecg.trigger_beat)
        self._bridge.beat.connect(self.heart.trigger_beat)
        self._bridge.likert_show.connect(self._show_likert)
        self._bridge.likert_hide.connect(self._hide_likert)

    def _show_likert(self, text: str) -> None:
        self.likert.setText(text)
        self.ecg.setVisible(False)
        self.likert.show()
        self.likert.raise_()

    def _hide_likert(self) -> None:
        self.likert.hide()
        self.ecg.setVisible(True)

    def resizeEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        w, h = self.width(), self.height()
        ecg_h = int(h * 0.5)
        self.ecg.setGeometry(0, (h - ecg_h) // 2, w, ecg_h)
        heart_size = max(140, min(w, h) // 5)
        margin = 30
        self.heart.setGeometry(
            w - heart_size - margin,
            h - heart_size - margin,
            heart_size,
            heart_size,
        )
        # Likert overlay: centered, 80% width
        overlay_w = int(w * 0.8)
        overlay_h = int(h * 0.4)
        self.likert.setGeometry((w - overlay_w) // 2, (h - overlay_h) // 2,
                                overlay_w, overlay_h)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        # Only handle local fullscreen toggle; forward everything else.
        if event.key() == Qt.Key.Key_F:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            event.accept()
            return
        # Forward to OS so the focused window (PsychoPy) can capture it.
        event.ignore()
