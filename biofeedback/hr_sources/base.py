from abc import ABC, abstractmethod

from ..core.bus import EventBus


class HRSource(ABC):
    """Abstract base for all HR data sources. Publishes 'bpm_real' events."""

    def __init__(self, bus: EventBus):
        self.bus = bus

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
