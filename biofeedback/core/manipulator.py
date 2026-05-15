import math
import threading
import time

from .bus import EventBus
from .types import BPMSample, ManipulatorState, FakeFeedbackParams


def _ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _linear(t: float) -> float:
    return t


class Manipulator:
    """Produces output_bpm from real_bpm with optional fake-feedback manipulation.

    State machine: IDLE -> RAMP_UP -> HOLD -> RAMP_DOWN -> IDLE.
    During non-IDLE states, output_bpm = real_bpm * (1 + factor), where factor
    smoothly interpolates between 0 and target_pct/100 according to the curve.
    """

    def __init__(self, bus: EventBus, update_rate_hz: float = 20.0):
        self.bus = bus
        self._update_period = 1.0 / update_rate_hz

        self._lock = threading.RLock()
        self._latest_real_bpm = 70.0
        self.state = ManipulatorState.IDLE
        self.params: FakeFeedbackParams | None = None
        self._state_start_time = 0.0
        self._ramp_down_start_factor = 0.0

        bus.subscribe("bpm_real", self._on_real_bpm)

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _on_real_bpm(self, sample: BPMSample) -> None:
        with self._lock:
            self._latest_real_bpm = sample.bpm

    def start_fake(self, params: FakeFeedbackParams) -> None:
        with self._lock:
            self.params = params
            self._state_start_time = time.time()
            self.state = ManipulatorState.RAMP_UP
        self.bus.publish("manipulator_state", self.state.value)

    def stop_fake(self, immediate: bool = False) -> None:
        """Stop manipulation. immediate=True snaps back instantly; otherwise
        run the ramp_down phase from the current factor."""
        with self._lock:
            if immediate:
                self.state = ManipulatorState.IDLE
                self.params = None
                self._ramp_down_start_factor = 0.0
            elif self.state in (ManipulatorState.RAMP_UP, ManipulatorState.HOLD):
                self._ramp_down_start_factor = self._compute_factor_unsafe(time.time())
                self._state_start_time = time.time()
                self.state = ManipulatorState.RAMP_DOWN
        self.bus.publish("manipulator_state", self.state.value)

    def _curve_fn(self):
        if self.params and self.params.curve == "ease":
            return _ease_in_out
        return _linear

    def _compute_factor_unsafe(self, now: float) -> float:
        if self.state == ManipulatorState.IDLE or self.params is None:
            return 0.0

        target = self.params.target_pct / 100.0
        elapsed = now - self._state_start_time
        curve = self._curve_fn()

        if self.state == ManipulatorState.RAMP_UP:
            d = max(self.params.ramp_up_duration, 1e-6)
            t = min(elapsed / d, 1.0)
            return curve(t) * target

        if self.state == ManipulatorState.HOLD:
            return target

        if self.state == ManipulatorState.RAMP_DOWN:
            d = max(self.params.ramp_down_duration, 1e-6)
            t = min(elapsed / d, 1.0)
            return self._ramp_down_start_factor * (1.0 - curve(t))

        return 0.0

    def _advance_state_unsafe(self, now: float) -> str | None:
        if self.state == ManipulatorState.IDLE or self.params is None:
            return None

        elapsed = now - self._state_start_time

        if self.state == ManipulatorState.RAMP_UP and elapsed >= self.params.ramp_up_duration:
            self.state = ManipulatorState.HOLD
            self._state_start_time = now
            return self.state.value

        if self.state == ManipulatorState.HOLD and elapsed >= self.params.hold_duration:
            self._ramp_down_start_factor = self.params.target_pct / 100.0
            self.state = ManipulatorState.RAMP_DOWN
            self._state_start_time = now
            return self.state.value

        if self.state == ManipulatorState.RAMP_DOWN and elapsed >= self.params.ramp_down_duration:
            self.state = ManipulatorState.IDLE
            self.params = None
            self._ramp_down_start_factor = 0.0
            return self.state.value

        return None

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            with self._lock:
                state_change = self._advance_state_unsafe(now)
                factor = self._compute_factor_unsafe(now)
                output_bpm = self._latest_real_bpm * (1.0 + factor)
            self.bus.publish("bpm_output", BPMSample(now, output_bpm))
            if state_change is not None:
                self.bus.publish("manipulator_state", state_change)
            time.sleep(self._update_period)

    def stop(self) -> None:
        self._running = False
