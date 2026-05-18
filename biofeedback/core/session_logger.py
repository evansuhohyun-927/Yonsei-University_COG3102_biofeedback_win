"""session_logger.py
실험 세션 동안 real BPM / output BPM / mismatch % / manipulator state 를
30초 epoch 단위 + 이벤트 단위로 CSV에 저장한다.

사용법 (experimenter.py 에서):
    from ..core.session_logger import SessionLogger
    self.logger = SessionLogger(participant_id="P01")
    self.logger.start(bus)   # 실험 시작 시
    self.logger.stop()       # 실험 종료 시
"""

import csv
import os
import threading
import time
from datetime import datetime

from .bus import EventBus
from .types import BPMSample


class SessionLogger:
    """두 종류의 CSV를 기록한다.

    1. <id>_<ts>_epoch.csv   — 30초마다 real/output BPM 평균 + mismatch
    2. <id>_<ts>_events.csv  — phase 전환 / fake feedback 시작·종료 등 이벤트
    """

    EPOCH_SECONDS = 30

    def __init__(
        self,
        participant_id: str = "TEST",
        save_dir: str = "data",
    ):
        self.participant_id = participant_id
        self.save_dir = save_dir

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(save_dir, exist_ok=True)

        self._epoch_path = os.path.join(
            save_dir, f"{participant_id}_{ts}_epoch.csv"
        )
        self._event_path = os.path.join(
            save_dir, f"{participant_id}_{ts}_events.csv"
        )

        # 내부 상태
        self._real_bpm_buf: list[float] = []
        self._output_bpm_buf: list[float] = []
        self._current_state: str = "idle"
        self._epoch_index: int = 0
        self._running = False
        self._bus: EventBus | None = None
        self._epoch_thread: threading.Thread | None = None

        # CSV 파일 핸들 (start() 에서 열림)
        self._epoch_file = None
        self._epoch_writer = None
        self._event_file = None
        self._event_writer = None

    # ------------------------------------------------------------------ public

    def start(self, bus: EventBus) -> None:
        """EventBus 구독 시작 + epoch 타이머 시작."""
        self._bus = bus
        self._running = True

        # CSV 헤더 작성
        self._epoch_file = open(self._epoch_path, "w", newline="", encoding="utf-8")
        self._epoch_writer = csv.writer(self._epoch_file)
        self._epoch_writer.writerow([
            "epoch_index", "epoch_start_time", "epoch_end_time",
            "real_bpm_mean", "real_bpm_std",
            "output_bpm_mean", "output_bpm_std",
            "mismatch_pct_mean", "manipulator_state",
        ])
        self._epoch_file.flush()

        self._event_file = open(self._event_path, "w", newline="", encoding="utf-8")
        self._event_writer = csv.writer(self._event_file)
        self._event_writer.writerow(["timestamp", "event", "value"])
        self._event_file.flush()

        # BPM 구독
        bus.subscribe("bpm_real", self._on_bpm_real)
        bus.subscribe("bpm_output", self._on_bpm_output)
        bus.subscribe("manipulator_state", self._on_state)

        # epoch 타이머 스레드
        self._epoch_thread = threading.Thread(
            target=self._epoch_loop, daemon=True
        )
        self._epoch_thread.start()

        self._log_event("session_start", self.participant_id)
        print(f"[logger] epoch → {self._epoch_path}")
        print(f"[logger] events → {self._event_path}")

    def stop(self) -> None:
        self._running = False
        self._log_event("session_stop", "")
        if self._epoch_file:
            self._epoch_file.close()
        if self._event_file:
            self._event_file.close()
        print("[logger] stopped.")

    def log_phase(self, phase_name: str) -> None:
        """실험자가 phase 전환 시점에 수동으로 호출."""
        self._log_event("phase", phase_name)

    def set_participant_id(self, pid: str) -> None:
        self.participant_id = pid

    # ----------------------------------------------------------------- private

    def _on_bpm_real(self, sample: BPMSample) -> None:
        self._real_bpm_buf.append(sample.bpm)

    def _on_bpm_output(self, sample: BPMSample) -> None:
        self._output_bpm_buf.append(sample.bpm)

    def _on_state(self, state: str) -> None:
        if state != self._current_state:
            self._log_event("manipulator_state", state)
            self._current_state = state

    def _epoch_loop(self) -> None:
        import numpy as np

        epoch_start = time.time()
        while self._running:
            time.sleep(0.5)
            now = time.time()
            if now - epoch_start < self.EPOCH_SECONDS:
                continue

            # epoch 종료 → 집계
            real_buf = self._real_bpm_buf[:]
            out_buf = self._output_bpm_buf[:]
            self._real_bpm_buf.clear()
            self._output_bpm_buf.clear()

            if real_buf and out_buf:
                real_arr = np.array(real_buf)
                out_arr = np.array(out_buf)
                real_mean = float(np.mean(real_arr))
                real_std = float(np.std(real_arr))
                out_mean = float(np.mean(out_arr))
                out_std = float(np.std(out_arr))
                mismatch = (
                    float(np.mean((out_arr - real_arr[:len(out_arr)]) /
                                  real_arr[:len(out_arr)] * 100))
                    if len(real_arr) >= len(out_arr) > 0
                    else 0.0
                )
            else:
                real_mean = real_std = out_mean = out_std = mismatch = 0.0

            self._epoch_writer.writerow([
                self._epoch_index,
                f"{epoch_start:.3f}",
                f"{now:.3f}",
                f"{real_mean:.2f}", f"{real_std:.2f}",
                f"{out_mean:.2f}", f"{out_std:.2f}",
                f"{mismatch:.2f}",
                self._current_state,
            ])
            self._epoch_file.flush()
            self._epoch_index += 1
            epoch_start = now

    def _log_event(self, event: str, value: str) -> None:
        if self._event_writer is None:
            return
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._event_writer.writerow([ts, event, value])
        self._event_file.flush()
