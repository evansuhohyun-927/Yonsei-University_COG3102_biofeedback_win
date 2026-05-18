"""bpm_smoother.py
PPG peak detection 결과로 나온 raw BPM의 튀는 값을 제거하고
이동평균으로 안정화한다.

EventBus의 "bpm_real" 이벤트를 구독해서
정제된 값을 "bpm_real_smooth" 이벤트로 재발행한다.

사용법 (main.py 또는 experimenter.py 에서):
    from ..core.bpm_smoother import BPMSmoother
    smoother = BPMSmoother(bus)
    smoother.start()
"""

import time
from collections import deque

from .bus import EventBus
from .types import BPMSample

# 생리적으로 불가능한 BPM은 버린다
BPM_MIN = 40.0
BPM_MAX = 160.0

# 이전 값 대비 이 %를 초과하면 이상값으로 처리
SPIKE_THRESHOLD_PCT = 30.0

# 이동평균 윈도우 크기 (샘플 수)
MOVING_AVG_WINDOW = 5


class BPMSmoother:
    """raw bpm_real 이벤트를 받아 정제 후 bpm_real_smooth 로 재발행."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._window: deque[float] = deque(maxlen=MOVING_AVG_WINDOW)
        self._last_valid: float | None = None

    def start(self) -> None:
        self.bus.subscribe("bpm_real", self._on_bpm)
        print("[smoother] started — subscribing to bpm_real")

    def stop(self) -> None:
        pass  # EventBus에 unsubscribe가 없으면 그냥 두면 됨

    # ----------------------------------------------------------------- private

    def _on_bpm(self, sample: BPMSample) -> None:
        bpm = sample.bpm

        # 1. 생리적 범위 벗어나면 버림
        if not (BPM_MIN <= bpm <= BPM_MAX):
            return

        # 2. 직전 유효값 대비 spike 체크
        if self._last_valid is not None:
            change_pct = abs(bpm - self._last_valid) / self._last_valid * 100
            if change_pct > SPIKE_THRESHOLD_PCT:
                # spike → 버리고 직전 값 재사용
                bpm = self._last_valid

        self._last_valid = bpm
        self._window.append(bpm)

        # 3. 이동평균
        smoothed = sum(self._window) / len(self._window)

        # 4. 정제된 값을 새 이벤트로 발행
        self.bus.publish(
            "bpm_real_smooth",
            BPMSample(timestamp=time.time(), bpm=smoothed),
        )
