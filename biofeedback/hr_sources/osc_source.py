import threading
import time

from pythonosc import dispatcher, osc_server

from .base import HRSource
from ..core.bus import EventBus
from ..core.types import BPMSample


class OSCHRSource(HRSource):
    """Receives BPM via OSC. Compatible with apps like HRV Logger that
    broadcast Apple Watch HR.

    Default OSC address: /HR (single float = BPM).
    Adjust `osc_address` to match your sender app.
    """

    def __init__(
        self,
        bus: EventBus,
        ip: str = "0.0.0.0",
        port: int = 9000,
        osc_address: str = "/HR",
    ):
        super().__init__(bus)
        self.ip = ip
        self.port = port
        self.osc_address = osc_address
        self._server: osc_server.ThreadingOSCUDPServer | None = None
        self._thread: threading.Thread | None = None

    def _on_hr(self, address: str, *args) -> None:
        if not args:
            return
        try:
            bpm = float(args[0])
        except (ValueError, TypeError):
            return
        self.bus.publish("bpm_real", BPMSample(time.time(), bpm))

    def start(self) -> None:
        disp = dispatcher.Dispatcher()
        disp.map(self.osc_address, self._on_hr)
        self._server = osc_server.ThreadingOSCUDPServer((self.ip, self.port), disp)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[osc] listening on {self.ip}:{self.port} address={self.osc_address}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
