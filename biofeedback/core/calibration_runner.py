"""calibration_runner.py
PsychoPy의 PPG_Setup routine에서 송신되는 'calibration_start' 마커를 받아
60초간 PPG 신호를 수집한 뒤 baseline BPM을 산출한다.

흐름:
    PsychoPy        bus.publish("calibration_request")
        ↓                        ↓
    PsychoPyMarkers    lsl_controller          CalibrationRunner
    ('calibration_start')    →                    →  60s 수집·peak detect
                                                    →  median BPM 산출
                                                    →  bus.publish("calibration_complete", bpm)
                                                                ↓
                                              CalibrationResultOutlet
                                                                ↓
                                              PsychoPy의 cal_inlet이 수신
"""

import threading
import time

import numpy as np
from scipy.signal import find_peaks

from .bus import EventBus

CALIBRATION_DURATION_S = 60.0
BPM_RANGE = (40.0, 180.0)


class CalibrationRunner:
    """calibration_request 이벤트를 받아 60s baseline 측정.

    PPG 소스(`PPGSerialSource` 또는 Mock)에 대한 의존성은 main.py에서
    set_source()로 주입한다. 소스 객체는 `get_recent_signal()`과
    `sample_rate` 속성만 있으면 된다.
    """

    def __init__(self, bus: EventBus, source_manager=None):
        """source_manager: 동적으로 현재 HR 소스를 조회. 명시 안 하면
        set_source()로 단일 소스 직접 지정 가능 (테스트용)."""
        self.bus = bus
        self.source_manager = source_manager
        self._source = None
        self._running = False
        self._thread: threading.Thread | None = None

    def set_source(self, source) -> None:
        """source_manager 없이 단일 소스 직접 지정 (테스트용)."""
        self._source = source

    def _resolve_source(self):
        if self.source_manager is not None and self.source_manager.current is not None:
            return self.source_manager.current
        return self._source

    def start(self) -> None:
        self.bus.subscribe("calibration_request", self._on_request)
        print("[calibration] runner subscribed — waiting for calibration_request")

    def stop(self) -> None:
        self._running = False

    # ----------------------------------------------------------------- private

    def _on_request(self, _data) -> None:
        if self._running:
            print("[calibration] already running — request ignored")
            return
        source = self._resolve_source()
        if source is None:
            print("[calibration] no HR source available — cannot calibrate")
            return
        if not hasattr(source, "get_recent_signal"):
            print("[calibration] source has no PPG access (mock?) — using bpm_real fallback")
            self._thread = threading.Thread(
                target=self._fallback_collect, args=(source,), daemon=True)
        else:
            self._thread = threading.Thread(
                target=self._collect, args=(source,), daemon=True)
        self._running = True
        self._thread.start()

    def _collect(self, source) -> None:
        """PPG raw signal에서 60s 누적 → peak detect → median BPM."""
        print(f"[calibration] starting {CALIBRATION_DURATION_S:.0f}s collection")
        sample_rate = getattr(source, "sample_rate", 200.0)
        end_time = time.time() + CALIBRATION_DURATION_S

        bpm_samples: list[float] = []
        last_check = time.time()

        while time.time() < end_time and self._running:
            time.sleep(1.0)
            now = time.time()
            elapsed = CALIBRATION_DURATION_S - (end_time - now)

            try:
                signal = source.get_recent_signal()
            except Exception as e:
                print(f"[calibration] signal read error: {e}")
                continue
            if len(signal) < int(sample_rate * 4):
                continue

            signal = signal - np.mean(signal)
            max_abs = float(np.max(np.abs(signal)))
            if max_abs < 1e-9:
                continue

            min_dist = int(0.3 * sample_rate)  # 300 ms = 200 BPM upper limit
            best_bpm: float | None = None
            best_cv = float("inf")
            for factor in (0.20, 0.30, 0.40):
                height = factor * max_abs
                peaks, _ = find_peaks(signal, distance=min_dist, height=height)
                if len(peaks) < 3:
                    continue
                intervals = np.diff(peaks) / sample_rate
                mean_int = float(np.mean(intervals))
                if mean_int <= 0:
                    continue
                bpm = 60.0 / mean_int
                cv = float(np.std(intervals) / mean_int)
                if BPM_RANGE[0] <= bpm <= BPM_RANGE[1] and cv < best_cv:
                    best_bpm = bpm
                    best_cv = cv
            if best_bpm is not None:
                bpm_samples.append(best_bpm)
                if now - last_check >= 10.0:
                    print(f"[calibration] {elapsed:.0f}s — current estimate {best_bpm:.1f} BPM")
                    last_check = now

        self._finish(bpm_samples)

    def _fallback_collect(self, _source) -> None:
        """get_recent_signal()이 없는 소스(mock 등) — bpm_real 이벤트 누적."""
        print(f"[calibration] fallback: collecting bpm_real for {CALIBRATION_DURATION_S:.0f}s")
        bpm_samples: list[float] = []

        def collect(sample):
            bpm_samples.append(float(sample.bpm))

        self.bus.subscribe("bpm_real", collect)
        time.sleep(CALIBRATION_DURATION_S)
        # EventBus has no unsubscribe; live with extra subscriber until shutdown
        self._finish(bpm_samples)

    def _finish(self, bpm_samples: list[float]) -> None:
        self._running = False
        if not bpm_samples:
            print("[calibration] FAILED — no valid BPM measurements")
            self.bus.publish("calibration_failed", None)
            return
        valid = [b for b in bpm_samples if BPM_RANGE[0] <= b <= BPM_RANGE[1]]
        if not valid:
            print("[calibration] FAILED — all measurements out of physiological range")
            self.bus.publish("calibration_failed", None)
            return
        baseline = float(np.median(valid))
        print(f"[calibration] DONE — baseline = {baseline:.1f} BPM "
              f"(median of {len(valid)} samples, range "
              f"{min(valid):.1f}-{max(valid):.1f})")
        self.bus.publish("calibration_complete", baseline)
