from dataclasses import dataclass
from enum import Enum


@dataclass
class BPMSample:
    timestamp: float
    bpm: float


class ManipulatorState(Enum):
    IDLE = "idle"
    RAMP_UP = "ramp_up"
    HOLD = "hold"
    RAMP_DOWN = "ramp_down"


@dataclass
class FakeFeedbackParams:
    target_pct: float          # ±%, e.g. +20 means real * 1.20
    ramp_up_duration: float    # seconds to reach target from 0
    hold_duration: float       # seconds at target
    ramp_down_duration: float  # seconds to return from target to 0
    curve: str = "linear"      # "linear" or "ease"
