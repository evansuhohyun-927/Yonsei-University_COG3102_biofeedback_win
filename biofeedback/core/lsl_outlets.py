"""lsl_outlets.py
PsychoPy 통합용 LSL outlet들.

- PPG_raw: PPG 원신호를 그대로 송신 (로깅·후분석용)
- BPM_processed: 필터/평활된 실측 BPM (PsychoPy가 actual_bpm으로 기록)
- Calibration_Result: PPG_Setup routine에서 측정된 baseline BPM (1회)

기존 BPMLSLOutlet(BPM_output, 조작된 BPM)과는 별도 스트림이다.
PsychoPy는 name으로 disambiguation한다.
"""

from .bus import EventBus
from .types import BPMSample


class PPGRawOutlet:
    """ppg_sample 이벤트를 구독해 raw PPG를 LSL로 송신."""

    def __init__(self, bus: EventBus, sample_rate_hz: float = 200.0):
        self.bus = bus
        self.sample_rate = sample_rate_hz
        self._outlet = None

    def start(self) -> None:
        try:
            from pylsl import StreamInfo, StreamOutlet
            info = StreamInfo(
                name="PPG_raw",
                type="PPG",
                channel_count=1,
                nominal_srate=self.sample_rate,
                channel_format="float32",
                source_id="biofeedback_ppg_raw",
            )
            self._outlet = StreamOutlet(info)
            self.bus.subscribe("ppg_sample", self._on_sample)
            print(f"[lsl_outlet] streaming 'PPG_raw' (type=PPG, {self.sample_rate} Hz)")
        except ImportError:
            print("[lsl_outlet] pylsl not installed — PPG_raw 송신 비활성화")
        except Exception as e:
            print(f"[lsl_outlet] PPG_raw start failed: {e}")

    def stop(self) -> None:
        self._outlet = None

    def _on_sample(self, value: float) -> None:
        if self._outlet is not None:
            self._outlet.push_sample([float(value)])


class BPMProcessedOutlet:
    """bpm_real_smooth 이벤트를 구독해 평활된 실측 BPM을 송신."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._outlet = None

    def start(self) -> None:
        try:
            from pylsl import StreamInfo, StreamOutlet
            info = StreamInfo(
                name="BPM_processed",
                type="BPM",
                channel_count=1,
                nominal_srate=10,
                channel_format="float32",
                source_id="biofeedback_bpm_processed",
            )
            self._outlet = StreamOutlet(info)
            self.bus.subscribe("bpm_real_smooth", self._on_bpm)
            print("[lsl_outlet] streaming 'BPM_processed' (type=BPM, smoothed real)")
        except ImportError:
            print("[lsl_outlet] pylsl not installed — BPM_processed 송신 비활성화")
        except Exception as e:
            print(f"[lsl_outlet] BPM_processed start failed: {e}")

    def stop(self) -> None:
        self._outlet = None

    def _on_bpm(self, sample: BPMSample) -> None:
        if self._outlet is not None:
            self._outlet.push_sample([float(sample.bpm)])


class BiofeedbackControlOutlet:
    """바이오피드백 → PsychoPy 제어 마커.

    'experiment_start_request' 이벤트를 구독해 PsychoPy가 기다리는
    'experiment_start' 마커를 송신한다. ExperimenterWindow의 '실험 시작'
    버튼이 이 이벤트를 발행한다.
    """

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._outlet = None

    def start(self) -> None:
        try:
            from pylsl import StreamInfo, StreamOutlet
            info = StreamInfo(
                name="BiofeedbackControl",
                type="Markers",
                channel_count=1,
                nominal_srate=0,
                channel_format="string",
                source_id="biofeedback_control",
            )
            self._outlet = StreamOutlet(info)
            self.bus.subscribe("experiment_start_request", self._on_start)
            print("[lsl_outlet] streaming 'BiofeedbackControl' (type=Markers, control)")
        except ImportError:
            print("[lsl_outlet] pylsl not installed — BiofeedbackControl 송신 비활성화")
        except Exception as e:
            print(f"[lsl_outlet] BiofeedbackControl start failed: {e}")

    def stop(self) -> None:
        self._outlet = None

    def _on_start(self, _data) -> None:
        if self._outlet is not None:
            self._outlet.push_sample(["experiment_start"])
            print("[lsl_outlet] BiofeedbackControl pushed: experiment_start")


class CalibrationResultOutlet:
    """calibration_complete 이벤트를 구독해 baseline BPM을 1회 송신."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._outlet = None

    def start(self) -> None:
        try:
            from pylsl import StreamInfo, StreamOutlet
            info = StreamInfo(
                name="Calibration_Result",
                type="Calibration",
                channel_count=1,
                nominal_srate=0,
                channel_format="float32",
                source_id="biofeedback_calibration_result",
            )
            self._outlet = StreamOutlet(info)
            self.bus.subscribe("calibration_complete", self._on_complete)
            print("[lsl_outlet] streaming 'Calibration_Result' (type=Calibration, 1회)")
        except ImportError:
            print("[lsl_outlet] pylsl not installed — Calibration_Result 송신 비활성화")
        except Exception as e:
            print(f"[lsl_outlet] Calibration_Result start failed: {e}")

    def stop(self) -> None:
        self._outlet = None

    def _on_complete(self, baseline_bpm: float) -> None:
        if self._outlet is not None:
            self._outlet.push_sample([float(baseline_bpm)])
            print(f"[lsl_outlet] Calibration_Result pushed: {baseline_bpm:.1f} BPM")
