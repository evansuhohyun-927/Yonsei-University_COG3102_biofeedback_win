import threading

import numpy as np
import sounddevice as sd

from ..core.bus import EventBus
from ..core.types import BPMSample


class AudioFeedback:
    """Audio output with selectable modes:
       - 'heartbeat': plays a synthesized thump on each beat event
       - 'tone': continuous sine whose frequency tracks output BPM
       - 'both': overlays heartbeat thumps on top of the tone
    """

    def __init__(
        self,
        bus: EventBus,
        sample_rate: int = 44100,
        mode: str = "heartbeat",
        tone_freq_min: float = 200.0,
        tone_freq_max: float = 600.0,
        bpm_range: tuple[float, float] = (50.0, 120.0),
        tone_gain: float = 0.12,
        thump_gain: float = 0.45,
    ):
        self.bus = bus
        self.sr = sample_rate
        self.mode = mode
        self.tone_freq_min = tone_freq_min
        self.tone_freq_max = tone_freq_max
        self.bpm_min, self.bpm_max = bpm_range
        self.tone_gain = tone_gain

        self._beat_sample = self._make_thump(gain=thump_gain)

        self._lock = threading.Lock()
        self._current_bpm = 70.0
        self._tone_phase = 0.0
        # Each active thump tracks how many samples of the waveform we've already emitted.
        self._active_thumps: list[int] = []
        self._stream: sd.OutputStream | None = None

        bus.subscribe("beat", self._on_beat)
        bus.subscribe("bpm_output", self._on_bpm)

    def _make_thump(self, gain: float) -> np.ndarray:
        """Synthesize a soft heartbeat thump. The envelope guarantees the
        waveform starts AND ends at exactly zero so there are no step
        discontinuities (which would otherwise produce audible clicks /
        crackling at the start or end of each beat)."""
        dur = 0.20
        n = int(dur * self.sr)
        t = np.arange(n, dtype=np.float32) / self.sr

        # Exponential decay (slightly slower than before so the tail is quieter
        # by the time we hard-fade it)
        envelope = np.exp(-t * 16.0)

        # Raised-cosine attack to avoid a click at the start
        attack_n = max(4, int(0.006 * self.sr))  # 6 ms
        attack_ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(attack_n, dtype=np.float32) / attack_n)
        envelope[:attack_n] *= attack_ramp

        # Linear fade-out at the end -> guaranteed zero termination
        fadeout_n = max(4, int(0.020 * self.sr))  # 20 ms
        fadeout = np.linspace(1.0, 0.0, fadeout_n, dtype=np.float32)
        envelope[-fadeout_n:] *= fadeout

        # Single low-frequency sine — peaks at ±1.0 instead of ±1.5 (the old
        # dual-sine could clip when overlaid with the tone in 'both' mode)
        wave = np.sin(2 * np.pi * 75.0 * t).astype(np.float32)

        return (envelope * wave * gain).astype(np.float32)

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.mode = mode
            if mode == "tone":
                self._active_thumps = []

    def _on_beat(self, _ts) -> None:
        with self._lock:
            if self.mode in ("heartbeat", "both"):
                self._active_thumps.append(0)

    def _on_bpm(self, sample: BPMSample) -> None:
        with self._lock:
            self._current_bpm = sample.bpm

    def _bpm_to_freq(self, bpm: float) -> float:
        clamped = max(self.bpm_min, min(self.bpm_max, bpm))
        ratio = (clamped - self.bpm_min) / (self.bpm_max - self.bpm_min)
        return self.tone_freq_min + ratio * (self.tone_freq_max - self.tone_freq_min)

    def _callback(self, outdata, frames, _time_info, _status) -> None:
        # Snapshot all shared state in a single lock acquisition. Holding the
        # lock briefly avoids audio glitches from priority inversion.
        with self._lock:
            mode = self.mode
            bpm = self._current_bpm
            thumps_to_play = self._active_thumps
            self._active_thumps = []  # we will repopulate with leftovers below

        out = np.zeros(frames, dtype=np.float32)

        if mode in ("tone", "both"):
            freq = self._bpm_to_freq(bpm)
            phase_inc = 2 * np.pi * freq / self.sr
            phases = self._tone_phase + phase_inc * np.arange(frames, dtype=np.float32)
            out += (self.tone_gain * np.sin(phases)).astype(np.float32)
            self._tone_phase = float((phases[-1] + phase_inc) % (2 * np.pi))

        still_active: list[int] = []
        if mode in ("heartbeat", "both"):
            sample_len = len(self._beat_sample)
            for idx in thumps_to_play:
                remaining = sample_len - idx
                n = min(remaining, frames)
                if n > 0:
                    out[:n] += self._beat_sample[idx:idx + n]
                if remaining > frames:
                    still_active.append(idx + frames)

        np.clip(out, -1.0, 1.0, out=out)
        outdata[:, 0] = out

        # Repopulate the active-thump list (and merge any beats that arrived
        # during this callback). Single short lock.
        if still_active or mode in ("heartbeat", "both"):
            with self._lock:
                self._active_thumps = still_active + self._active_thumps

    def start(self) -> None:
        if self._stream is not None:
            return
        # blocksize=0 lets PortAudio pick the device's preferred buffer size,
        # which is more reliable than forcing 512 frames (could under-run).
        self._stream = sd.OutputStream(
            samplerate=self.sr,
            channels=1,
            callback=self._callback,
            blocksize=0,
            latency="high",
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
