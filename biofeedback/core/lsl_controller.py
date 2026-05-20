"""lsl_controller.py
PsychoPy가 LSL로 보내는 Phase 마커를 수신해서
biofeedback을 자동으로 제어한다.

마커 → 동작:
    baseline   → 피험자 창 열기 + 오디오 ON
    P1_sync    → 대기 (피험자 창 유지)
    P2_ramp    → block_type에 따라 Fake Feedback 자동 Start
                 (accel: +25%, decel: -25%, neutral: 아무것도 안 함)
    P3_plateau → 대기 (Fake Feedback이 Hold 상태로 자동 유지됨)
    P4_recovery→ Fake Feedback Stop (ramp down)

사용법 (main.py 에서):
    from .core.lsl_controller import LSLController
    lsl_ctrl = LSLController(bus, manipulator, experimenter_window)
    lsl_ctrl.start()
"""

import threading
import time

from .bus import EventBus
from .manipulator import Manipulator
from .types import FakeFeedbackParams

# 프로토콜 파라미터 (PsychoPy 타이밍과 맞춤)
RAMP_UP_S = 120.0   # Phase2: 20초 × 6회
HOLD_S = 45.0       # Phase3
RAMP_DOWN_S = 60.0  # Phase4
TARGET_PCT = 25.0   # ±25%


class LSLController:
    """LSL 마커 수신 → biofeedback 자동 제어."""

    def __init__(self, bus: EventBus, manipulator: Manipulator, win):
        """
        win: ExperimenterWindow 인스턴스
             (open_participant_window, set_audio 메서드 호출용)
        """
        self.bus = bus
        self.manipulator = manipulator
        self.win = win
        self._running = False
        self._thread: threading.Thread | None = None
        self._current_block_type: str = "neutral"

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[lsl_ctrl] started — waiting for PsychoPy markers")

    def stop(self) -> None:
        self._running = False

    # ----------------------------------------------------------------- private

    def _loop(self) -> None:
        try:
            from pylsl import StreamInlet, resolve_byprop
        except ImportError:
            print("[lsl_ctrl] pylsl not installed — auto control disabled")
            return

        print("[lsl_ctrl] searching for PsychoPy marker stream...")
        inlet = None

        while self._running:
            if inlet is None:
                try:
                    streams = resolve_byprop("type", "Markers", 1, 2.0)
                    if streams:
                        inlet = StreamInlet(streams[0])
                        print("[lsl_ctrl] connected to PsychoPy marker stream")
                    else:
                        time.sleep(2.0)
                        continue
                except Exception as e:
                    print(f"[lsl_ctrl] stream search error: {e}")
                    time.sleep(2.0)
                    continue

            try:
                sample, _ = inlet.pull_sample(timeout=1.0)
                if sample:
                    marker = sample[0].strip()
                    print(f"[lsl_ctrl] marker received: {marker}")
                    self._handle_marker(marker)
            except Exception as e:
                print(f"[lsl_ctrl] inlet error: {e}")
                inlet = None
                time.sleep(1.0)

    def _handle_marker(self, marker: str) -> None:
        if marker == "baseline":
            self._auto_open_participant()
            self._auto_audio_on()

        elif marker == "P1_sync":
            # block_type 정보가 아직 없는 단계 — 대기
            pass

        elif marker.startswith("P2_ramp"):
            # marker 예: "P2_ramp" — block_type은 별도 마커로 오거나
            # PsychoPy 코드에서 block_type을 LSL로 같이 보내야 함
            # 현재는 이전 P1_sync에서 받은 block_type 사용
            self._auto_start_fake()

        elif marker == "P3_plateau":
            # Manipulator가 자동으로 HOLD 상태로 전환됨 — 개입 불필요
            pass

        elif marker == "P4_recovery":
            self._auto_stop_fake()

        elif marker in ("accel", "decel", "neutral"):
            # block_type 마커 (PsychoPy에서 별도로 보내는 경우)
            self._current_block_type = marker
            print(f"[lsl_ctrl] block_type set to: {marker}")

    def _auto_open_participant(self) -> None:
        """Qt 메인 스레드에서 피험자 창 열기."""
        try:
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(
                self.win, "open_participant_window_auto",
                Qt.ConnectionType.QueuedConnection,
            )
        except Exception as e:
            print(f"[lsl_ctrl] open participant window error: {e}")

    def _auto_audio_on(self) -> None:
        """Qt 메인 스레드에서 오디오 ON."""
        try:
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(
                self.win, "set_audio_on",
                Qt.ConnectionType.QueuedConnection,
            )
        except Exception as e:
            print(f"[lsl_ctrl] audio on error: {e}")

    def _auto_start_fake(self) -> None:
    	if self._current_block_type == "neutral":
        	print("[lsl_ctrl] neutral block — skipping fake feedback")
        	return
    	if self.manipulator.state.value != "idle":
        	return
    	target = TARGET_PCT if self._current_block_type == "accel" else -TARGET_PCT
    	params = FakeFeedbackParams(
        	target_pct=target,
        	ramp_up_duration=RAMP_UP_S,
        	hold_duration=HOLD_S,
        	ramp_down_duration=RAMP_DOWN_S,
        	curve="linear",
    	)

    self.manipulator.start_fake(params)
    print(f"[lsl_ctrl] fake feedback started: {target:+.0f}%")

    def _auto_stop_fake(self) -> None:
        self.manipulator.stop_fake(immediate=False)
        print("[lsl_ctrl] fake feedback stopped (ramp down)")
