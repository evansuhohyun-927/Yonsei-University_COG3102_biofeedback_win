import threading
from collections import defaultdict
from typing import Callable


class EventBus:
    """Simple thread-safe pub-sub. Subscribers are called synchronously on the
    publisher's thread; for cross-thread Qt updates, bridge via QObject signals.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        with self._lock:
            self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, data=None) -> None:
        with self._lock:
            subs = list(self._subscribers[event_type])
        for cb in subs:
            try:
                cb(data)
            except Exception as e:
                print(f"[bus] subscriber error on '{event_type}': {e}")
