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
        device: int | str | None = None,
        channels: int = 2,
        beat_sound_path: str | None = None,
    ):
        self.bus = bus
        self.sr = sample_rate
        self.mode = mode
        self.tone_freq_min = tone_freq_min
        self.tone_freq_max = tone_freq_max
        self.bpm_min, self.bpm_max = bpm_range
        self.tone_gain = tone_gain
        # None -> system default output device. Can be re-pointed at runtime via
        # set_device() (e.g. so the experimenter can route to earphones).
        self._device = device
        # Stereo by default so both earbuds receive sound (a mono stream can be
        # routed to only one channel by some Windows drivers).
        self._channels = max(1, int(channels))

        # Kept so the beat sample can be rebuilt if a device forces a different
        # sample rate (see _open_stream).
        self._thump_gain = thump_gain
        # Optional path to a real heartbeat recording (wav/mp3/flac/...). When
        # set and loadable it replaces the synthesized thump; otherwise we fall
        # back to the synth so audio never breaks.
        self._beat_sound_path = beat_sound_path
        self._beat_sample = self._build_beat_sample()

        self._lock = threading.Lock()
        self._current_bpm = 70.0
        self._tone_phase = 0.0
        # Each active thump tracks how many samples of the waveform we've already emitted.
        self._active_thumps: list[int] = []
        self._stream: sd.OutputStream | None = None
        self._muted = False

        bus.subscribe("beat", self._on_beat)
        bus.subscribe("bpm_output", self._on_bpm)

    def _make_thump(self, gain: float) -> np.ndarray:
        """Synthesize a punchy, clearly-audible heartbeat thump.

        A pure low-frequency sine (~75 Hz) is below the reproduction range of
        most laptop / monitor speakers, which roll off sharply under ~150 Hz —
        so the old single-sine thump was nearly inaudible on those devices. We
        now mix a low 'thud' body with a higher transient so the beat carries
        energy in a band small speakers can actually reproduce, then
        peak-normalize the result so ``gain`` maps directly to output amplitude
        (gain=1.0 -> full scale = maximum volume).

        The envelope still guarantees the waveform starts AND ends at exactly
        zero, so there are no step discontinuities (which would otherwise
        produce audible clicks / crackling at the start or end of each beat)."""
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

        # Low body (heartbeat thud) + higher transient so the beat is audible
        # on speakers that cannot reproduce the sub-150 Hz fundamental.
        body = np.sin(2 * np.pi * 70.0 * t).astype(np.float32)
        transient = np.sin(2 * np.pi * 150.0 * t).astype(np.float32)
        wave = body + 0.7 * transient

        raw = (envelope * wave).astype(np.float32)
        # Peak-normalize so `gain` maps to true amplitude (gain=1.0 -> ±1.0).
        peak = float(np.max(np.abs(raw)))
        if peak > 1e-9:
            raw *= (gain / peak)
        return raw.astype(np.float32)

    def _build_beat_sample(self) -> np.ndarray:
        """Return the per-beat waveform: a loaded sound file if one is
        configured and loadable, otherwise the synthesized thump."""
        if self._beat_sound_path:
            arr = self._load_beat_file(self._beat_sound_path)
            if arr is not None and len(arr) > 0:
                return arr
        return self._make_thump(gain=self._thump_gain)

    @staticmethod
    def _resample(data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        """Linear resample (dependency-free). Adequate for a short percussive
        heartbeat sample; HF loss is inaudible here."""
        if src_sr == dst_sr or len(data) == 0:
            return data.astype(np.float32)
        n_dst = max(1, int(round(len(data) * float(dst_sr) / float(src_sr))))
        x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
        return np.interp(x_new, x_old, data).astype(np.float32)

    def _load_beat_file(self, path: str) -> np.ndarray | None:
        """Load a heartbeat sound file, downmix to mono, resample to the
        current stream rate, trim surrounding silence (so the onset lines up
        with the beat event), apply tiny fades to avoid edge clicks, and
        peak-normalize to `thump_gain` (gain=1.0 -> full scale)."""
        try:
            import soundfile as sf
            data, src_sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as e:
            print(f"[AudioFeedback] could not load beat sound {path!r}: {e}")
            return None

        mono = data.mean(axis=1).astype(np.float32)
        mono = self._resample(mono, int(src_sr), int(self.sr))

        # Trim leading/trailing near-silence (< 1% of peak)
        peak = float(np.max(np.abs(mono)))
        if peak <= 1e-9:
            return None
        nz = np.where(np.abs(mono) > 0.01 * peak)[0]
        if len(nz) > 0:
            mono = mono[nz[0]:nz[-1] + 1]

        # Short fade in/out to prevent clicks at the trimmed boundaries
        fade = min(int(0.005 * self.sr), len(mono) // 2)
        if fade > 0:
            mono[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
            mono[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)

        peak = float(np.max(np.abs(mono)))
        if peak > 1e-9:
            mono = mono * (self._thump_gain / peak)
        return mono.astype(np.float32)

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.mode = mode
            if mode == "tone":
                self._active_thumps = []

    def set_muted(self, muted: bool) -> None:
        """Silence output without tearing down the PortAudio stream.
        Toggling mute (instead of stop/start) avoids repeated stream
        open/close, which is a known native-crash source."""
        with self._lock:
            self._muted = bool(muted)

    def is_muted(self) -> bool:
        with self._lock:
            return self._muted

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
            muted = self._muted

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

        if muted:
            out[:] = 0.0
        np.clip(out, -1.0, 1.0, out=out)
        # Broadcast the mono signal to every output channel (mono or stereo).
        outdata[:] = out[:, np.newaxis]

        # Repopulate the active-thump list (and merge any beats that arrived
        # during this callback). Single short lock.
        if still_active or mode in ("heartbeat", "both"):
            with self._lock:
                self._active_thumps = still_active + self._active_thumps

    def start(self) -> None:
        if self._stream is not None:
            return
        self._open_stream()

    def _open_stream(self) -> None:
        # blocksize=0 lets PortAudio pick the device's preferred buffer size,
        # which is more reliable than forcing 512 frames (could under-run).
        # Some endpoints (notably exclusive WDM-KS headphone jacks) only accept
        # their native sample rate, so fall back to the device default if the
        # configured rate is rejected. If the rate changes, regenerate the
        # thump so its pitch stays correct.
        candidate_rates = [self.sr]
        try:
            if self._device is not None:
                dev_sr = int(sd.query_devices(self._device)["default_samplerate"])
                if dev_sr and dev_sr not in candidate_rates:
                    candidate_rates.append(dev_sr)
        except Exception:
            pass

        last_err: Exception | None = None
        for rate in candidate_rates:
            try:
                stream = sd.OutputStream(
                    samplerate=rate,
                    channels=self._channels,
                    callback=self._callback,
                    blocksize=0,
                    latency="high",
                    device=self._device,
                )
                stream.start()
                if rate != self.sr:
                    self.sr = rate
                    self._beat_sample = self._build_beat_sample()
                self._stream = stream
                return
            except Exception as e:
                last_err = e
        if last_err is not None:
            raise last_err
        raise RuntimeError("no working sample rate for output device")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # --- Output-device routing (experimenter setup) ------------------------
    @staticmethod
    def list_output_devices() -> list[dict]:
        """Distinct output devices, de-duplicated by name. For each physical
        device the most compatible host API is kept (MME > DirectSound >
        WASAPI > WDM-KS) so the experimenter sees a short, meaningful list."""
        api_pref = {
            "MME": 0,
            "Windows DirectSound": 1,
            "Windows WASAPI": 2,
            "Windows WDM-KS": 3,
        }
        best: dict[str, dict] = {}
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] <= 0:
                    continue
                try:
                    ha = sd.query_hostapis(d["hostapi"])["name"]
                except Exception:
                    ha = ""
                name = str(d["name"]).strip()
                rank = api_pref.get(ha, 9)
                if name not in best or rank < best[name]["rank"]:
                    best[name] = {"index": i, "name": name, "hostapi": ha, "rank": rank}
        except Exception:
            pass
        return [
            {"index": v["index"], "name": v["name"], "hostapi": v["hostapi"]}
            for v in best.values()
        ]

    def current_device_name(self) -> str:
        try:
            dev = self._device
            if dev is None:
                dev = sd.default.device[1]
            return str(sd.query_devices(dev)["name"]).strip()
        except Exception:
            return "기본 출력 장치"

    def set_device(self, device: int | str | None) -> bool:
        """Re-open the output stream on a different device. Returns True on
        success. On failure it transparently falls back to the previous device.
        Stream reopen is a setup-time action (not during the run), so the
        open/close-churn crash concern does not apply here."""
        prev = self._device
        if self._stream is not None:
            try:
                self.stop()
            except Exception:
                pass
        self._device = device
        try:
            self.start()
            return True
        except Exception as e:
            print(f"[AudioFeedback] set_device({device!r}) failed: {e}; reverting")
            self._device = prev
            try:
                if self._stream is None:
                    self.start()
            except Exception:
                pass
            return False
