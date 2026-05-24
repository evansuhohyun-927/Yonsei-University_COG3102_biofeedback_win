from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, pyqtSlot
import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox, QGridLayout, QStatusBar,
    QScrollArea, QMessageBox,
)

from ..core.bus import EventBus
from ..core.types import BPMSample, FakeFeedbackParams
from ..core.manipulator import Manipulator
from ..core.source_manager import SourceManager
from ..feedback.participant_window import ParticipantWindow
from ..feedback.audio import AudioFeedback
from ..hr_sources.mock import MockHRSource
from ..hr_sources.ppg_serial import PPGSerialSource, list_serial_ports


class _BusBridge(QObject):
    bpm_real = pyqtSignal(object)
    bpm_output = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    calibration_complete = pyqtSignal(float)
    calibration_failed = pyqtSignal()

    def __init__(self, bus: EventBus):
        super().__init__()
        bus.subscribe("bpm_real", lambda s: self.bpm_real.emit(s))
        bus.subscribe("bpm_output", lambda s: self.bpm_output.emit(s))
        bus.subscribe("manipulator_state", lambda s: self.state_changed.emit(s))
        bus.subscribe("calibration_complete", lambda bpm: self.calibration_complete.emit(float(bpm)))
        bus.subscribe("calibration_failed", lambda _: self.calibration_failed.emit())


class ExperimenterWindow(QMainWindow):
    def __init__(
        self,
        bus: EventBus,
        manipulator: Manipulator,
        audio: AudioFeedback,
        source_manager: SourceManager,
    ):
        super().__init__()
        self.setWindowTitle("Biofeedback - Experimenter Control")
        self.resize(1150, 900)

        self.bus = bus
        self.manipulator = manipulator
        self.audio = audio
        self.source_manager = source_manager
        self.participant_window: ParticipantWindow | None = None

        self._bridge = _BusBridge(bus)
        self._bridge.bpm_real.connect(self._on_bpm_real)
        self._bridge.bpm_output.connect(self._on_bpm_output)
        self._bridge.state_changed.connect(self._on_state)
        self._bridge.calibration_complete.connect(self._on_calibration_complete)
        self._bridge.calibration_failed.connect(self._on_calibration_failed)

        # PsychoPy 통합용 상태
        self._baseline_bpm: float | None = None
        self._experiment_started = False
        self._calib_remaining = 0
        self._calib_timer = QTimer(self)
        self._calib_timer.timeout.connect(self._tick_calib_countdown)

        self._t0 = time.time()
        self._real_t: deque[float] = deque(maxlen=4000)
        self._real_y: deque[float] = deque(maxlen=4000)
        self._out_t: deque[float] = deque(maxlen=4000)
        self._out_y: deque[float] = deque(maxlen=4000)

        self._build_ui()

        self._plot_timer = QTimer(self)
        self._plot_timer.timeout.connect(self._refresh_plot)
        self._plot_timer.start(33)

        # PPG status/preview poll
        self._ppg_timer = QTimer(self)
        self._ppg_timer.timeout.connect(self._refresh_ppg_status)
        self._ppg_timer.start(250)

    # --- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # --- 최상단: PsychoPy 통합 패널 (실험 시작 버튼) ---
        outer.addWidget(self._build_start_panel())

        # --- top: status row + main BPM plot are always visible ---
        status_row = QHBoxLayout()
        self.real_bpm_label = QLabel("Real BPM: --")
        self.output_bpm_label = QLabel("Output BPM: --")
        self.state_label = QLabel("State: idle")
        for w in (self.real_bpm_label, self.output_bpm_label, self.state_label):
            w.setStyleSheet("font-size: 14pt; padding: 4px 12px;")
            status_row.addWidget(w)
        status_row.addStretch()
        outer.addLayout(status_row)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.setLabel("left", "BPM")
        self.plot_widget.setLabel("bottom", "Time (s)")
        self.plot_widget.addLegend()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(220)
        self.real_curve = self.plot_widget.plot([], [], pen=pg.mkPen("#1f77b4", width=2),
                                                 name="Real BPM")
        self.output_curve = self.plot_widget.plot([], [], pen=pg.mkPen("#d62728", width=2),
                                                   name="Output BPM")
        outer.addWidget(self.plot_widget, stretch=1)

        # --- scrollable area for the rest of the controls ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(self._build_fake_controls())
        inner_layout.addWidget(self._build_feedback_controls())
        inner_layout.addWidget(self._build_ppg_controls())
        inner_layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _build_start_panel(self) -> QGroupBox:
        """PsychoPy 통합 패널: Baseline 측정 → 실험 시작 (가장 눈에 띄게)."""
        box = QGroupBox("PsychoPy 통합 — 실험 진행")
        box.setStyleSheet(
            "QGroupBox { font-size: 13pt; font-weight: 600; "
            "border: 2px solid #2e7d32; border-radius: 6px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { padding: 0 8px; }"
        )
        v = QVBoxLayout(box)

        row1 = QHBoxLayout()
        self.start_exp_btn = QPushButton("실험 시작 →")
        self.start_exp_btn.setMinimumHeight(60)
        self.start_exp_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; "
            "font-size: 16pt; font-weight: bold; padding: 8px 24px;"
        )
        self.start_exp_btn.setToolTip(
            "1. 오디오 ON\n"
            "2. Baseline 60초 측정\n"
            "3. PsychoPy에 'experiment_start' 마커 송신\n"
            "(참가자 시각자극은 PsychoPy 창에서 직접 표시됨)"
        )
        self.start_exp_btn.clicked.connect(self._on_start_exp_clicked)
        row1.addWidget(self.start_exp_btn, stretch=2)

        self.calib_status_label = QLabel("Baseline: 미측정")
        self.calib_status_label.setStyleSheet("font-size: 12pt; padding: 0 16px;")
        row1.addWidget(self.calib_status_label, stretch=1)
        v.addLayout(row1)

        self.start_help_label = QLabel(
            "준비 순서: PPG 연결 → 신호 품질 확인 → 위 버튼 클릭 "
            "(60초 calibration → PsychoPy 진행). 참가자 시각자극은 PsychoPy 창."
        )
        self.start_help_label.setStyleSheet("color: #555; font-size: 9pt; padding: 0 4px;")
        self.start_help_label.setWordWrap(True)
        v.addWidget(self.start_help_label)

        return box

    def _on_start_exp_clicked(self) -> None:
        if self._experiment_started:
            return
        # 오디오 ON (시각자극은 PsychoPy ecg_renderer가 직접 그림)
        # ParticipantWindow는 자동으로 안 열림 — 필요하면 '피험자 인터페이스 실행' 버튼 클릭
        if not self.audio_btn.isChecked():
            self.audio_btn.setChecked(True)
        # 이미 calibration 완료된 경우 즉시 송신
        if self._baseline_bpm is not None:
            self._fire_experiment_start()
            return
        # 아직 calibration 안 됐으면 calibration_request 발행
        # → CalibrationRunner가 30초 측정 후 calibration_complete 이벤트 발행
        # → _on_calibration_complete 핸들러가 자동으로 _fire_experiment_start 호출
        self.start_exp_btn.setEnabled(False)
        self.start_exp_btn.setText("Calibrating... (60s)")
        self.calib_status_label.setText("측정 중... 60s")
        # 1초마다 카운트다운 갱신
        self._calib_remaining = 60
        self._calib_timer.start(1000)
        self.bus.publish("calibration_request", None)

    def _tick_calib_countdown(self) -> None:
        self._calib_remaining -= 1
        if self._calib_remaining <= 0:
            self._calib_timer.stop()
            self.start_exp_btn.setText("Calibrating... (마무리 중)")
            self.calib_status_label.setText("측정 마무리 중...")
            return
        self.start_exp_btn.setText(f"Calibrating... ({self._calib_remaining}s)")
        self.calib_status_label.setText(f"측정 중... {self._calib_remaining}s")

    def _on_calibration_complete(self, baseline_bpm: float) -> None:
        self._calib_timer.stop()
        self._baseline_bpm = baseline_bpm
        self.calib_status_label.setText(f"Baseline: {baseline_bpm:.1f} BPM")
        # Calibration_Result outlet은 이미 자동 송신됨 (lsl_outlets.py)
        # 이제 experiment_start 마커 송신
        if not self._experiment_started:
            self._fire_experiment_start()

    def _on_calibration_failed(self) -> None:
        self._calib_timer.stop()
        QMessageBox.warning(
            self, "Calibration 실패",
            "60초 동안 안정적인 BPM을 측정하지 못했습니다.\n"
            "PPG 신호를 확인하고 다시 시도하세요.",
        )
        self.start_exp_btn.setEnabled(True)
        self.start_exp_btn.setText("실험 시작 →")
        self.calib_status_label.setText("Baseline: 측정 실패")

    def _fire_experiment_start(self) -> None:
        """PsychoPy에 experiment_start 마커 송신 → PsychoPy가 다음 routine으로 진행."""
        self._experiment_started = True
        self.bus.publish("experiment_start_request", None)
        self.start_exp_btn.setEnabled(False)
        self.start_exp_btn.setStyleSheet(
            "background-color: #888; color: white; font-size: 16pt; "
            "font-weight: bold; padding: 8px 24px;"
        )
        self.start_exp_btn.setText("실험 진행 중 ✓")
        self.statusBar().showMessage("PsychoPy 창에서 실험 진행 중 — 이 창은 모니터링용")
        # 두 창 모두 유지하되, 이 창을 작게 + 우측 상단으로 이동해서
        # PsychoPy 참가자 창이 잘 보이게 함
        QTimer.singleShot(300, self._shrink_to_corner)

    def _shrink_to_corner(self) -> None:
        """ExperimenterWindow를 작게 만들고 우측 상단으로 이동."""
        try:
            from PyQt6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen().availableGeometry()
            new_w, new_h = 480, 360
            self.resize(new_w, new_h)
            self.move(screen.width() - new_w - 20, 20)
        except Exception as _e:
            print(f'[experimenter] shrink_to_corner error: {_e}')

    def _build_fake_controls(self) -> QGroupBox:
        box = QGroupBox("Fake Feedback")
        g = QGridLayout(box)

        g.addWidget(QLabel("Target % (±):"), 0, 0)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-50.0, 50.0)
        self.target_spin.setValue(20.0)
        self.target_spin.setSuffix(" %")
        self.target_spin.setSingleStep(1.0)
        g.addWidget(self.target_spin, 0, 1)

        g.addWidget(QLabel("Curve:"), 0, 2)
        self.curve_combo = QComboBox()
        self.curve_combo.addItems(["linear", "ease"])
        g.addWidget(self.curve_combo, 0, 3)

        g.addWidget(QLabel("Ramp up (s):"), 1, 0)
        self.ramp_up_spin = QDoubleSpinBox()
        self.ramp_up_spin.setRange(0.1, 600.0)
        self.ramp_up_spin.setValue(120.0)
        g.addWidget(self.ramp_up_spin, 1, 1)

        g.addWidget(QLabel("Hold (s):"), 1, 2)
        self.hold_spin = QDoubleSpinBox()
        self.hold_spin.setRange(0.0, 3600.0)
        self.hold_spin.setValue(60.0)
        g.addWidget(self.hold_spin, 1, 3)

        g.addWidget(QLabel("Ramp down (s):"), 2, 0)
        self.ramp_down_spin = QDoubleSpinBox()
        self.ramp_down_spin.setRange(0.1, 600.0)
        self.ramp_down_spin.setValue(60.0)
        g.addWidget(self.ramp_down_spin, 2, 1)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start_fake)
        self.stop_btn = QPushButton("Stop (ramp down)")
        self.stop_btn.clicked.connect(self._stop_fake)
        self.estop_btn = QPushButton("EMERGENCY STOP")
        self.estop_btn.setStyleSheet(
            "background-color: #c62828; color: white; font-weight: bold;"
        )
        self.estop_btn.clicked.connect(self._emergency_stop)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.estop_btn)
        g.addLayout(btns, 3, 0, 1, 4)

        return box

    def _build_feedback_controls(self) -> QGroupBox:
        box = QGroupBox("Participant Feedback")
        h = QHBoxLayout(box)

        self.participant_btn = QPushButton("피험자 인터페이스 실행")
        self.participant_btn.setStyleSheet(
            "padding: 8px 16px; font-weight: 600;"
        )
        self.participant_btn.clicked.connect(self._open_participant_window)
        h.addWidget(self.participant_btn)

        h.addSpacing(20)

        self.audio_btn = QPushButton("Audio: OFF")
        self.audio_btn.setCheckable(True)
        self.audio_btn.toggled.connect(self._toggle_audio)
        h.addWidget(self.audio_btn)

        h.addWidget(QLabel("Mode:"))
        self.audio_mode_combo = QComboBox()
        self.audio_mode_combo.addItems(["heartbeat", "tone", "both"])
        self.audio_mode_combo.currentTextChanged.connect(self.audio.set_mode)
        h.addWidget(self.audio_mode_combo)

        h.addStretch()
        return box

    def _build_ppg_controls(self) -> QGroupBox:
        box = QGroupBox("PPG Connection & Calibration")
        g = QGridLayout(box)

        # Row 0: port + baud + connect
        g.addWidget(QLabel("Port:"), 0, 0)
        self.ppg_port_combo = QComboBox()
        self.ppg_port_combo.setEditable(True)
        self.ppg_port_combo.setMinimumWidth(260)
        g.addWidget(self.ppg_port_combo, 0, 1, 1, 2)

        self.ppg_refresh_btn = QPushButton("Refresh ports")
        self.ppg_refresh_btn.clicked.connect(self._refresh_ppg_ports)
        g.addWidget(self.ppg_refresh_btn, 0, 3)

        g.addWidget(QLabel("Baud:"), 0, 4)
        self.ppg_baud_spin = QSpinBox()
        self.ppg_baud_spin.setRange(9600, 1000000)
        self.ppg_baud_spin.setValue(115200)
        g.addWidget(self.ppg_baud_spin, 0, 5)

        self.ppg_connect_btn = QPushButton("Connect PPG")
        self.ppg_connect_btn.setStyleSheet("font-weight: 600;")
        self.ppg_connect_btn.clicked.connect(self._toggle_ppg_connection)
        g.addWidget(self.ppg_connect_btn, 0, 6)

        # Row 1: status + sample rate label
        self.ppg_status_label = QLabel(
            "Status: not connected (active source: " + (self.source_manager.kind or "—") + ")"
        )
        g.addWidget(self.ppg_status_label, 1, 0, 1, 7)

        # Row 2: live raw signal preview
        self.ppg_preview = pg.PlotWidget()
        self.ppg_preview.setBackground("#111")
        self.ppg_preview.setLabel("left", "PPG raw")
        self.ppg_preview.setLabel("bottom", "Sample")
        self.ppg_preview.showGrid(x=False, y=True, alpha=0.2)
        self.ppg_preview.setMinimumHeight(160)
        self.ppg_preview_curve = self.ppg_preview.plot(
            [], [], pen=pg.mkPen("#3cd070", width=1)
        )
        self.ppg_peak_scatter = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen(None), brush=pg.mkBrush("#ff4060")
        )
        self.ppg_preview.addItem(self.ppg_peak_scatter)
        g.addWidget(self.ppg_preview, 2, 0, 1, 7)

        # Row 3: calibration controls
        g.addWidget(QLabel("Peak threshold (× max amp):"), 3, 0)
        self.ppg_threshold_spin = QDoubleSpinBox()
        self.ppg_threshold_spin.setRange(0.05, 0.95)
        self.ppg_threshold_spin.setValue(0.30)
        self.ppg_threshold_spin.setSingleStep(0.05)
        self.ppg_threshold_spin.valueChanged.connect(self._apply_ppg_calibration)
        g.addWidget(self.ppg_threshold_spin, 3, 1)

        g.addWidget(QLabel("Min interval (ms):"), 3, 2)
        self.ppg_min_interval_spin = QSpinBox()
        self.ppg_min_interval_spin.setRange(200, 1500)
        self.ppg_min_interval_spin.setValue(300)
        self.ppg_min_interval_spin.setSingleStep(20)
        self.ppg_min_interval_spin.valueChanged.connect(self._apply_ppg_calibration)
        g.addWidget(self.ppg_min_interval_spin, 3, 3)

        self.ppg_autocal_btn = QPushButton("Auto-Calibrate")
        self.ppg_autocal_btn.clicked.connect(self._auto_calibrate_ppg)
        g.addWidget(self.ppg_autocal_btn, 3, 4, 1, 3)

        self._refresh_ppg_ports()
        return box

    # --- bus event handlers ------------------------------------------------

    def _on_bpm_real(self, sample: BPMSample) -> None:
        t = sample.timestamp - self._t0
        self._real_t.append(t)
        self._real_y.append(sample.bpm)
        self.real_bpm_label.setText(f"Real BPM: {sample.bpm:.1f}")

    def _on_bpm_output(self, sample: BPMSample) -> None:
        t = sample.timestamp - self._t0
        self._out_t.append(t)
        self._out_y.append(sample.bpm)
        self.output_bpm_label.setText(f"Output BPM: {sample.bpm:.1f}")

    def _on_state(self, state: str) -> None:
        self.state_label.setText(f"State: {state}")

    def _refresh_plot(self) -> None:
        now_t = time.time() - self._t0
        x_min = now_t - 60.0
        if self._real_t:
            self.real_curve.setData(list(self._real_t), list(self._real_y))
        if self._out_t:
            self.output_curve.setData(list(self._out_t), list(self._out_y))
        self.plot_widget.setXRange(x_min, now_t, padding=0)

    # --- fake feedback -----------------------------------------------------

    def _start_fake(self) -> None:
        params = FakeFeedbackParams(
            target_pct=self.target_spin.value(),
            ramp_up_duration=self.ramp_up_spin.value(),
            hold_duration=self.hold_spin.value(),
            ramp_down_duration=self.ramp_down_spin.value(),
            curve=self.curve_combo.currentText(),
        )
        self.manipulator.start_fake(params)
        self.statusBar().showMessage(
            f"Fake feedback started: {params.target_pct:+.1f}% "
            f"(ramp {params.ramp_up_duration:.0f}s, hold {params.hold_duration:.0f}s, "
            f"down {params.ramp_down_duration:.0f}s, {params.curve})"
        )

    def _stop_fake(self) -> None:
        self.manipulator.stop_fake(immediate=False)
        self.statusBar().showMessage("Stopping fake feedback (ramp down)")

    def _emergency_stop(self) -> None:
        self.manipulator.stop_fake(immediate=True)
        self.statusBar().showMessage("EMERGENCY STOP - reverted to real BPM")

    # --- participant window + audio ---------------------------------------

    def _open_participant_window(self) -> None:
        if self.participant_window is None:
            self.participant_window = ParticipantWindow(self.bus)
        self.participant_window.show()
        self.participant_window.raise_()
        self.participant_window.activateWindow()
        self.statusBar().showMessage("Participant window opened")

    def _toggle_audio(self, on: bool) -> None:
        if on:
            self.audio.start()
            self.audio_btn.setText("Audio: ON")
        else:
            self.audio.stop()
            self.audio_btn.setText("Audio: OFF")

    # --- PPG controls ------------------------------------------------------

    def _refresh_ppg_ports(self) -> None:
        current = self.ppg_port_combo.currentText()
        self.ppg_port_combo.clear()
        ports = list_serial_ports()
        if ports:
            self.ppg_port_combo.addItems(ports)
            if current and current in ports:
                self.ppg_port_combo.setCurrentText(current)
        else:
            self.ppg_port_combo.addItem("(no ports detected)")

    def _toggle_ppg_connection(self) -> None:
        # If a PPG source is currently active, this button disconnects it.
        if isinstance(self.source_manager.current, PPGSerialSource):
            self._disconnect_ppg()
        else:
            self._connect_ppg()

    def _connect_ppg(self) -> None:
        port = self.ppg_port_combo.currentText().strip()
        if not port or port.startswith("("):
            QMessageBox.warning(self, "PPG", "Select a serial port first.")
            return
        baud = self.ppg_baud_spin.value()
        try:
            ppg = PPGSerialSource(
                self.bus, port=port, baudrate=baud,
                peak_threshold_factor=self.ppg_threshold_spin.value(),
                min_peak_distance_ms=self.ppg_min_interval_spin.value(),
            )
            self.source_manager.set_source(ppg, "ppg")
        except Exception as e:
            QMessageBox.critical(self, "PPG connection failed", str(e))
            return
        self.ppg_connect_btn.setText("Disconnect PPG")
        self.statusBar().showMessage(f"Connected to PPG on {port}@{baud}")

    def _disconnect_ppg(self) -> None:
        # Replace PPG with a Mock source so the rest of the system keeps running
        mock = MockHRSource(self.bus)
        self.source_manager.set_source(mock, "mock")
        self.ppg_connect_btn.setText("Connect PPG")
        self.statusBar().showMessage("PPG disconnected (reverted to Mock)")

    def _apply_ppg_calibration(self) -> None:
        src = self.source_manager.current
        if not isinstance(src, PPGSerialSource):
            return
        src.set_calibration(
            threshold_factor=self.ppg_threshold_spin.value(),
            min_interval_ms=self.ppg_min_interval_spin.value(),
        )

    def _auto_calibrate_ppg(self) -> None:
        src = self.source_manager.current
        if not isinstance(src, PPGSerialSource):
            QMessageBox.information(self, "Auto-Calibrate", "Connect to PPG first.")
            return
        result = src.auto_calibrate()
        if not result.get("success"):
            QMessageBox.warning(self, "Auto-Calibrate failed",
                                result.get("reason", "Unknown error"))
            return
        # Reflect back into UI (block signals to avoid re-triggering set_calibration)
        self.ppg_threshold_spin.blockSignals(True)
        self.ppg_threshold_spin.setValue(result["threshold_factor"])
        self.ppg_threshold_spin.blockSignals(False)
        QMessageBox.information(
            self, "Auto-Calibrate",
            f"Threshold set to {result['threshold_factor']:.2f}\n"
            f"Detected BPM: {result['bpm']:.1f}\n"
            f"Interval CV: {result['cv']:.3f}\n"
            f"Peaks in window: {result['n_peaks']}",
        )

    def _refresh_ppg_status(self) -> None:
        src = self.source_manager.current
        kind = self.source_manager.kind or "—"
        if isinstance(src, PPGSerialSource):
            st = src.get_status()
            bpm_txt = f"{st['bpm']:.1f}" if st["bpm"] else "—"
            self.ppg_status_label.setText(
                f"Status: connected | source={kind} | "
                f"buffer={st['buffer_seconds']:.1f}s | "
                f"obs sample rate≈{st['observed_sample_rate']:.0f} Hz | BPM={bpm_txt}"
            )
            signal = src.get_recent_signal()
            peaks = src.get_recent_peaks()
            if len(signal) > 0:
                xs = np.arange(len(signal))
                self.ppg_preview_curve.setData(xs, signal)
                if len(peaks) > 0 and peaks.max() < len(signal):
                    self.ppg_peak_scatter.setData(peaks.astype(float), signal[peaks])
                else:
                    self.ppg_peak_scatter.setData([], [])
        else:
            self.ppg_status_label.setText(
                f"Status: not connected (active source: {kind})"
            )
            self.ppg_preview_curve.setData([], [])
            self.ppg_peak_scatter.setData([], [])

# --- LSLController에서 호출하는 자동 제어 메서드 (Qt slot) ---------------
    @pyqtSlot()
    def open_participant_window_auto(self) -> None:
        self._open_participant_window()
        if self.participant_window:
            self.participant_window.setWindowState(Qt.WindowState.WindowActive)
            self.participant_window.raise_()
            self.participant_window.activateWindow()

    @pyqtSlot()
    def set_audio_on(self) -> None:
        """LSLController가 baseline 마커 받으면 자동으로 오디오 ON."""
        if not self.audio_btn.isChecked():
            self.audio_btn.setChecked(True)