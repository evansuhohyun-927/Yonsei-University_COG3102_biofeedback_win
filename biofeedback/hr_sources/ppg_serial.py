import threading
import time
from collections import deque

import numpy as np
import serial
from scipy.signal import find_peaks

from .base import HRSource
from ..core.bus import EventBus
from ..core.types import BPMSample


class PPGSerialSource(HRSource):
    """Reads raw PPG from serial and computes BPM via peak detection.

    Assumes one floating-point sample per line (newline-delimited ASCII).
    Override `parse_line` for other formats (e.g. CSV with timestamp, binary).
    """

    def __init__(
        self,
        bus: EventBus,
        port: str,
        baudrate: int = 115200,
        sample_rate_hz: float = 200.0,
        window_seconds: float = 8.0,
        bpm_update_hz: float = 1.0,
        min_peak_distance_ms: float = 300.0,
        peak_threshold_factor: float = 0.30,
    ):
        super().__init__(bus)
        self.port = port
        self.baudrate = baudrate
        self.sample_rate = sample_rate_hz
        self.window_size = int(window_seconds * sample_rate_hz)
        self.bpm_update_period = 1.0 / bpm_update_hz

        self._lock = threading.Lock()
        # Calibration parameters (mutable via set_calibration / auto_calibrate)
        self.min_peak_distance_samples = int((min_peak_distance_ms / 1000.0) * sample_rate_hz)
        self.peak_threshold_factor = peak_threshold_factor

        self._buffer: deque[float] = deque(maxlen=self.window_size)
        self._last_peaks: np.ndarray = np.array([], dtype=int)
        self._last_bpm: float | None = None
        self._serial: serial.Serial | None = None
        self._connected = False
        self._running = False
        self._sample_count = 0  # total samples received (for sample-rate estimate)
        self._connect_time: float | None = None

    # --- public API ---------------------------------------------------------

    def parse_line(self, line: bytes) -> float | None:
        try:
            return float(line.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            return None

    def start(self) -> None:
        try:
            self._serial = serial.Serial(self.port, self.baudrate, timeout=1.0)
        except (serial.SerialException, OSError) as e:
            self._connected = False
            raise RuntimeError(f"Failed to open {self.port}: {e}") from e
        self._connected = True
        self._connect_time = time.time()
        self._running = True
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._bpm_loop, daemon=True).start()
        print(f"[ppg] reading from {self.port}@{self.baudrate}")

    def stop(self) -> None:
        self._running = False
        self._connected = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def is_connected(self) -> bool:
        return self._connected

    def get_recent_signal(self) -> np.ndarray:
        """Return a copy of the current signal buffer (oldest -> newest)."""
        with self._lock:
            return np.array(self._buffer, dtype=float)

    def get_recent_peaks(self) -> np.ndarray:
        with self._lock:
            return self._last_peaks.copy()

    def get_status(self) -> dict:
        with self._lock:
            n = len(self._buffer)
            bpm = self._last_bpm
            count = self._sample_count
        elapsed = (time.time() - self._connect_time) if self._connect_time else 0.0
        observed_sr = (count / elapsed) if elapsed > 1.0 else 0.0
        return {
            "connected": self._connected,
            "buffer_samples": n,
            "buffer_seconds": n / self.sample_rate,
            "bpm": bpm,
            "observed_sample_rate": observed_sr,
        }

    def set_calibration(self, threshold_factor: float | None = None,
                        min_interval_ms: float | None = None) -> None:
        with self._lock:
            if threshold_factor is not None:
                self.peak_threshold_factor = float(threshold_factor)
            if min_interval_ms is not None:
                self.min_peak_distance_samples = int(
                    (float(min_interval_ms) / 1000.0) * self.sample_rate
                )

    def auto_calibrate(self) -> dict:
        """Try several thresholds, pick the one yielding the most stable
        BPM in physiological range (40-180). Returns a status dict."""
        signal = self.get_recent_signal()
        if len(signal) < self.window_size // 2:
            return {"success": False, "reason": "Not enough signal yet (wait a few seconds)"}

        signal = signal - np.mean(signal)
        if np.max(np.abs(signal)) < 1e-9:
            return {"success": False, "reason": "Signal is flat (no input?)"}

        best = None
        for factor in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
            height = factor * np.max(np.abs(signal))
            peaks, _ = find_peaks(signal, distance=self.min_peak_distance_samples,
                                  height=height)
            if len(peaks) < 3:
                continue
            intervals = np.diff(peaks) / self.sample_rate
            mean_int = float(np.mean(intervals))
            if mean_int <= 0:
                continue
            bpm = 60.0 / mean_int
            cv = float(np.std(intervals) / mean_int)
            if not (40.0 <= bpm <= 180.0):
                continue
            score = -cv  # lower variability is better
            if best is None or score > best["_score"]:
                best = {"_score": score, "threshold_factor": factor,
                        "bpm": bpm, "cv": cv, "n_peaks": int(len(peaks))}

        if best is None:
            return {"success": False, "reason": "No threshold gave a stable BPM in 40-180"}

        self.set_calibration(threshold_factor=best["threshold_factor"])
        return {
            "success": True,
            "threshold_factor": best["threshold_factor"],
            "bpm": best["bpm"],
            "cv": best["cv"],
            "n_peaks": best["n_peaks"],
        }

    # --- internal -----------------------------------------------------------

    def _read_loop(self) -> None:
        while self._running and self._serial is not None:
            try:
                line = self._serial.readline()
                if not line:
                    continue
                v = self.parse_line(line)
                if v is None:
                    continue
                with self._lock:
                    self._buffer.append(v)
                    self._sample_count += 1
            except Exception as e:
                print(f"[ppg] read error: {e}")
                self._connected = False
                time.sleep(0.1)

    def _bpm_loop(self) -> None:
        while self._running:
            time.sleep(self.bpm_update_period)
            with self._lock:
                if len(self._buffer) < self.window_size // 2:
                    continue
                signal = np.array(self._buffer, dtype=float)
                threshold_factor = self.peak_threshold_factor
                min_dist = self.min_peak_distance_samples

            signal = signal - np.mean(signal)
            max_abs = float(np.max(np.abs(signal)))
            if max_abs < 1e-9:
                continue
            height = threshold_factor * max_abs
            peaks, _ = find_peaks(signal, distance=min_dist, height=height)
            with self._lock:
                self._last_peaks = peaks
            if len(peaks) < 2:
                continue
            intervals_s = np.diff(peaks) / self.sample_rate
            mean_interval = float(np.mean(intervals_s))
            if mean_interval <= 0:
                continue
            bpm = 60.0 / mean_interval
            with self._lock:
                self._last_bpm = bpm
            self.bus.publish("bpm_real", BPMSample(time.time(), bpm))


def list_serial_ports() -> list[str]:
    """List available serial port device paths."""
    from serial.tools import list_ports
    return [p.device for p in list_ports.comports()]
