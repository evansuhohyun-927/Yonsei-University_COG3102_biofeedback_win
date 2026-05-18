"""bpm_lsl_outlet.py
biofeedback의 output BPM을 LSL 스트림으로 송신한다.
PsychoPy 쪽에서 StreamInlet으로 받아서 박동 원 BPM에 사용.

사용법 (main.py 에서):
    from .core.bpm_lsl_outlet import BPMLSLOutlet
    lsl_outlet = BPMLSLOutlet(bus)
    lsl_outlet.start()
"""

from .bus import EventBus
from .types import BPMSample


class BPMLSLOutlet:
    """bpm_output 이벤트를 구독해서 LSL 스트림으로 송신."""

    def __init__(self, bus: EventBus, stream_name: str = "BiofeedbackBPM"):
        self.bus = bus
        self.stream_name = stream_name
        self._outlet = None

    def start(self) -> None:
        try:
            from pylsl import StreamInfo, StreamOutlet
            info = StreamInfo(
                name=self.stream_name,
                type="BPM",
                channel_count=1,
                nominal_srate=20,  # Manipulator가 20Hz로 업데이트
                channel_format="float32",
                source_id="biofeedback_bpm_outlet",
            )
            self._outlet = StreamOutlet(info)
            self.bus.subscribe("bpm_output", self._on_bpm_output)
            print(f"[lsl_outlet] streaming '{self.stream_name}' (type=BPM)")
        except ImportError:
            print("[lsl_outlet] pylsl not installed — LSL송신 비활성화. pip install pylsl 로 설치하세요.")
        except Exception as e:
            print(f"[lsl_outlet] failed to start: {e}")

    def stop(self) -> None:
        self._outlet = None

    def _on_bpm_output(self, sample: BPMSample) -> None:
        if self._outlet is not None:
            self._outlet.push_sample([float(sample.bpm)])
