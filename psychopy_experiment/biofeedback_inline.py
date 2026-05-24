"""Single-process biofeedback integration for PsychoPy.

PsychoPy가 직접 biofeedback 코어를 import해서 사용하는 모듈.
별도 subprocess, LSL inlets 불필요 — 모두 in-process EventBus로 통신.

사용법 (PsychoPy CodeComponent):
    # Welcome Before Experiment:
    import biofeedback_inline as bf
    bf.start(source='mock')  # 또는 source='ppg', ppg_port='COM3'

    # PPG_Setup Begin Routine:
    bf.start_calibration()
    # PPG_Setup Each Frame:
    if bf.is_calibration_done():
        baseline = bf.get_baseline_bpm()
        continueRoutine = False

    # Phase1_Sync Begin Routine:
    bf.set_block_type(block_type)  # 'accel' / 'decel' / 'neutral'

    # Phase2_Mini_ Begin Routine (또는 첫 epoch에서):
    bf.start_ramp()

    # Phase4_Recovery Begin Routine:
    bf.stop_ramp()

    # 모든 Phase Each Frame:
    bpm = bf.get_output_bpm()  # 조작된 BPM (manipulator output)
    ecg_renderer.update(t, bpm); ecg_renderer.draw()

    # Debrief End Routine:
    bf.stop()
"""

import os
import sys
import threading
import time

# biofeedback 패키지를 sys.path에 추가
_here = os.path.dirname(os.path.abspath(__file__))
_project = os.path.dirname(_here)
if _project not in sys.path:
    sys.path.insert(0, _project)

from biofeedback.core.bus import EventBus
from biofeedback.core.manipulator import Manipulator
from biofeedback.core.beat_scheduler import BeatScheduler
from biofeedback.core.bpm_smoother import BPMSmoother
from biofeedback.core.source_manager import SourceManager
from biofeedback.core.calibration_runner import CalibrationRunner
from biofeedback.core.types import FakeFeedbackParams
from biofeedback.hr_sources.mock import MockHRSource

# Phase 타이밍 (PsychoPy와 일치)
RAMP_UP_S = 180.0    # Phase2 = 9 × 20s
HOLD_S = 45.0        # Phase3
RAMP_DOWN_S = 60.0   # Phase4
TARGET_PCT = 25.0

_state: dict = {
    'started': False,
    'bus': None,
    'manipulator': None,
    'beat_scheduler': None,
    'smoother': None,
    'source_manager': None,
    'calibration_runner': None,
    'audio': None,
    'output_bpm': 70.0,
    'real_bpm': 70.0,
    'baseline_bpm': None,
    'calibration_running': False,
    'calibration_failed': False,
    'current_block_type': 'neutral',
}


def start(source: str = 'mock', ppg_port: str = '', ppg_baud: int = 115200,
          audio_on: bool = True) -> None:
    """Before Experiment에서 1회 호출."""
    if _state['started']:
        return

    bus = EventBus()
    _state['bus'] = bus

    smoother = BPMSmoother(bus); smoother.start()
    _state['smoother'] = smoother

    manipulator = Manipulator(bus)
    _state['manipulator'] = manipulator

    beat_scheduler = BeatScheduler(bus)
    _state['beat_scheduler'] = beat_scheduler

    source_manager = SourceManager(bus)
    _state['source_manager'] = source_manager

    calibration_runner = CalibrationRunner(bus, source_manager=source_manager)
    calibration_runner.start()
    _state['calibration_runner'] = calibration_runner

    # bus 이벤트 → _state 동기화
    bus.subscribe('bpm_output', lambda s: _state.__setitem__('output_bpm', float(s.bpm)))
    bus.subscribe('bpm_real_smooth', lambda s: _state.__setitem__('real_bpm', float(s.bpm)))
    bus.subscribe('calibration_complete', _on_calibration_complete)
    bus.subscribe('calibration_failed', _on_calibration_failed)

    # HR source 선택
    if source == 'ppg' and ppg_port:
        try:
            from biofeedback.hr_sources.ppg_serial import PPGSerialSource
            src = PPGSerialSource(bus, port=ppg_port, baudrate=ppg_baud)
            source_manager.set_source(src, 'ppg')
            print(f'[bf_inline] PPG source on {ppg_port}@{ppg_baud}')
        except Exception as e:
            print(f'[bf_inline] PPG init failed ({e}) — fallback mock')
            source_manager.set_source(MockHRSource(bus), 'mock')
    else:
        source_manager.set_source(MockHRSource(bus), 'mock')
        print('[bf_inline] mock HR source (70 BPM sine)')

    # 오디오 (실패해도 진행)
    if audio_on:
        try:
            from biofeedback.feedback.audio import AudioFeedback
            audio = AudioFeedback(bus, mode='heartbeat', thump_gain=0.9)
            audio.start()
            _state['audio'] = audio
            print('[bf_inline] audio ON')
        except Exception as e:
            print(f'[bf_inline] audio init failed: {e}')

    _state['started'] = True
    print('[bf_inline] started')


def start_calibration() -> None:
    """60초 baseline 측정 시작."""
    bus = _state.get('bus')
    if bus is None:
        return
    _state['baseline_bpm'] = None
    _state['calibration_running'] = True
    _state['calibration_failed'] = False
    bus.publish('calibration_request', None)


def is_calibration_done() -> bool:
    """True면 calibration 완료 또는 실패. get_baseline_bpm()으로 결과 확인."""
    return not _state.get('calibration_running', False)


def get_baseline_bpm() -> float | None:
    return _state.get('baseline_bpm')


def calibration_failed() -> bool:
    return _state.get('calibration_failed', False)


def set_block_type(block_type: str) -> None:
    """'accel' / 'decel' / 'neutral' — 다음 ramp에 적용."""
    _state['current_block_type'] = block_type


def start_ramp() -> None:
    """Phase2 시작 시 호출. block_type에 따라 manipulator RAMP_UP."""
    bt = _state.get('current_block_type', 'neutral')
    if bt == 'neutral':
        return
    manipulator = _state.get('manipulator')
    if manipulator is None or manipulator.state.value != 'idle':
        return
    target = TARGET_PCT if bt == 'accel' else -TARGET_PCT
    params = FakeFeedbackParams(
        target_pct=target,
        ramp_up_duration=RAMP_UP_S,
        hold_duration=HOLD_S,
        ramp_down_duration=RAMP_DOWN_S,
        curve='linear',
    )
    manipulator.start_fake(params)
    print(f'[bf_inline] ramp started: {bt} {target:+.0f}%')


def stop_ramp() -> None:
    """Phase4 시작 시 호출. Manipulator RAMP_DOWN."""
    manipulator = _state.get('manipulator')
    if manipulator is not None:
        manipulator.stop_fake(immediate=False)
        print('[bf_inline] ramp stop (ramp_down)')


def get_output_bpm() -> float:
    """현재 조작된 BPM (ECG 시각자극용)."""
    return float(_state.get('output_bpm', 70.0))


def get_real_bpm() -> float:
    """현재 실측 BPM (로깅용)."""
    return float(_state.get('real_bpm', 70.0))


def stop() -> None:
    """실험 종료 시 cleanup."""
    for key in ('source_manager', 'manipulator', 'beat_scheduler', 'audio'):
        obj = _state.get(key)
        if obj is not None and hasattr(obj, 'stop'):
            try:
                obj.stop()
            except Exception:
                pass
    _state['started'] = False
    print('[bf_inline] stopped')


# --- 내부 핸들러 -------------------------------------------------------------

def _on_calibration_complete(bpm: float) -> None:
    _state['baseline_bpm'] = float(bpm)
    _state['calibration_running'] = False
    _state['calibration_failed'] = False
    print(f'[bf_inline] calibration complete: {bpm:.1f} BPM')


def _on_calibration_failed(_data) -> None:
    _state['calibration_running'] = False
    _state['calibration_failed'] = True
    _state['baseline_bpm'] = 70.0  # fallback
    print('[bf_inline] calibration failed — using fallback 70 BPM')
