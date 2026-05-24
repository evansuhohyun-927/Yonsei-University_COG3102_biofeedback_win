import argparse
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from .core.bus import EventBus
from .core.manipulator import Manipulator
from .core.beat_scheduler import BeatScheduler
from .core.source_manager import SourceManager
from .feedback.audio import AudioFeedback
from .gui.experimenter import ExperimenterWindow
from .hr_sources.base import HRSource
from .hr_sources.mock import MockHRSource
from .core.session_logger import SessionLogger
from .core.bpm_smoother import BPMSmoother
from .core.bpm_lsl_outlet import BPMLSLOutlet
from .core.lsl_outlets import (
    PPGRawOutlet,
    BPMProcessedOutlet,
    CalibrationResultOutlet,
    BiofeedbackControlOutlet,
)
from .core.calibration_runner import CalibrationRunner
from .core.lsl_controller import LSLController


def make_source(name: str, bus: EventBus, args: argparse.Namespace) -> tuple[HRSource, str]:
    if name == "mock":
        return MockHRSource(bus), "mock"
    if name == "osc":
        from .hr_sources.osc_source import OSCHRSource
        return OSCHRSource(bus, port=args.osc_port, osc_address=args.osc_address), "osc"
    if name == "ppg":
        if not args.ppg_port:
            raise SystemExit("--ppg-port is required when --source=ppg")
        from .hr_sources.ppg_serial import PPGSerialSource
        return PPGSerialSource(bus, port=args.ppg_port, baudrate=args.ppg_baud), "ppg"
    raise ValueError(f"Unknown source: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Biofeedback experimenter app")
    parser.add_argument("--source", default="mock", choices=["mock", "osc", "ppg"],
                        help="Initial HR source (PPG can also be connected from the GUI)")
    parser.add_argument("--osc-port", type=int, default=9000)
    parser.add_argument("--osc-address", default="/HR")
    parser.add_argument("--ppg-port", default=None,
                        help="Serial port for DIY PPG (e.g. COM3)")
    parser.add_argument("--ppg-baud", type=int, default=115200)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    bus = EventBus()

    # ── LSL outlets ──────────────────────────────────────────────────────
    # BPM_output (manipulated, 20Hz) — 시각자극·기존 호환
    lsl_outlet = BPMLSLOutlet(bus)
    lsl_outlet.start()
    # BPM_processed (smoothed real, ~10Hz) — PsychoPy가 actual_bpm 로깅
    bpm_proc_outlet = BPMProcessedOutlet(bus)
    bpm_proc_outlet.start()
    # PPG_raw (200Hz) — 후분석용 풀 데이터
    ppg_raw_outlet = PPGRawOutlet(bus)
    ppg_raw_outlet.start()
    # Calibration_Result (1회) — baseline BPM 측정 결과
    cal_outlet = CalibrationResultOutlet(bus)
    cal_outlet.start()
    # BiofeedbackControl (Markers) — 실험자 '실험 시작' 버튼 → PsychoPy 진행 신호
    control_outlet = BiofeedbackControlOutlet(bus)
    control_outlet.start()

    # ── Processing pipeline ──────────────────────────────────────────────
    smoother = BPMSmoother(bus)
    smoother.start()

    logger = SessionLogger(participant_id="TEST", save_dir="data")
    logger.start(bus)

    manipulator = Manipulator(bus)
    beat_scheduler = BeatScheduler(bus)
    audio = AudioFeedback(bus, mode="heartbeat", thump_gain=0.9)
    source_manager = SourceManager(bus)

    # PPG_Setup routine에서 호출됨 (calibration_request → 60s 측정)
    calibration_runner = CalibrationRunner(bus, source_manager=source_manager)
    calibration_runner.start()

    try:
        src, kind = make_source(args.source, bus, args)
        source_manager.set_source(src, kind)
    except Exception as e:
        QMessageBox.warning(None, "Source startup failed",
                            f"Could not start '{args.source}' source:\n{e}\n\nFalling back to Mock.")
        source_manager.set_source(MockHRSource(bus), "mock")

    win = ExperimenterWindow(bus, manipulator, audio, source_manager)
    lsl_ctrl = LSLController(bus, manipulator, win)
    lsl_ctrl.start()
    win.show()

    try:
        exit_code = app.exec()
    finally:
        source_manager.stop()
        manipulator.stop()
        beat_scheduler.stop()
        audio.stop()
        logger.stop()
        lsl_outlet.stop()
        bpm_proc_outlet.stop()
        ppg_raw_outlet.stop()
        cal_outlet.stop()
        control_outlet.stop()
        calibration_runner.stop()
        lsl_ctrl.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
