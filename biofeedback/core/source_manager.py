from .bus import EventBus
from ..hr_sources.base import HRSource


class SourceManager:
    """Holds the currently active HRSource. Allows runtime swapping (e.g.
    switch from Mock to PPG when the user connects via the GUI)."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self.current: HRSource | None = None
        self.kind: str | None = None  # "mock" / "osc" / "ppg" for UI labeling

    def set_source(self, source: HRSource, kind: str) -> None:
        if self.current is not None:
            self.current.stop()
        self.current = source
        self.kind = kind
        self.current.start()

    def stop(self) -> None:
        if self.current is not None:
            self.current.stop()
            self.current = None
            self.kind = None
