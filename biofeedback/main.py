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
                        help="Serial port for DIY PPG (e.g. /dev/tty.usbmodem...)")
    parser.add_argument("--ppg-baud", type=int, default=115200)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    bus = EventBus()

    manipulator = Manipulator(bus)
    beat_scheduler = BeatScheduler(bus)
    audio = AudioFeedback(bus, mode="heartbeat")
    source_manager = SourceManager(bus)

    try:
        src, kind = make_source(args.source, bus, args)
        source_manager.set_source(src, kind)
    except Exception as e:
        # Fall back to Mock and let the user know
        QMessageBox.warning(None, "Source startup failed",
                            f"Could not start '{args.source}' source:\n{e}\n\nFalling back to Mock.")
        source_manager.set_source(MockHRSource(bus), "mock")

    win = ExperimenterWindow(bus, manipulator, audio, source_manager)
    win.show()

    try:
        exit_code = app.exec()
    finally:
        source_manager.stop()
        manipulator.stop()
        beat_scheduler.stop()
        audio.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
