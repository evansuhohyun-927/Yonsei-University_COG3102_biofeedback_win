import math
import random
import threading
import time

from .base import HRSource
from ..core.bus import EventBus
from ..core.types import BPMSample


class MockHRSource(HRSource):
    """Slowly varying simulated BPM for development/testing.

    bpm(t) = base + amplitude * sin(2π·t/period) + N(0, noise_std)
    """

    def __init__(
        self,
        bus: EventBus,
        base_bpm: float = 70.0,
        amplitude: float = 8.0,
        period: float = 30.0,
        noise_std: float = 1.5,
        update_rate_hz: float = 1.0,
    ):
        super().__init__(bus)
        self.base_bpm = base_bpm
        self.amplitude = amplitude
        self.period = period
        self.noise_std = noise_std
        self._update_period = 1.0 / update_rate_hz
        self._running = False
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            t = now - self._t0
            bpm = self.base_bpm + self.amplitude * math.sin(2 * math.pi * t / self.period)
            bpm += random.gauss(0, self.noise_std)
            self.bus.publish("bpm_real", BPMSample(now, bpm))
            time.sleep(self._update_period)
