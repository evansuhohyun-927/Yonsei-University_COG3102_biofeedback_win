import threading
import time

from .bus import EventBus
from .types import BPMSample


class BeatScheduler:
    """Emits 'beat' events at intervals of 60/bpm seconds, where bpm tracks bpm_output."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._current_bpm = 70.0
        self._lock = threading.Lock()
        bus.subscribe("bpm_output", self._on_bpm)

        self._next_beat_time = time.time() + 60.0 / self._current_bpm
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _on_bpm(self, sample: BPMSample) -> None:
        with self._lock:
            self._current_bpm = max(30.0, min(220.0, sample.bpm))

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            if now >= self._next_beat_time:
                self.bus.publish("beat", now)
                with self._lock:
                    interval = 60.0 / self._current_bpm
                self._next_beat_time = now + interval
            time.sleep(0.003)

    def stop(self) -> None:
        self._running = False
