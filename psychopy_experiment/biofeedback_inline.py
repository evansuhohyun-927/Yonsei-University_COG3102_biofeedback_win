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
    'audio_on': False,
    'output_bpm': 70.0,
    'real_bpm': 70.0,
    'baseline_bpm': None,
    'calibration_running': False,
    'calibration_failed': False,
    'current_block_type': 'neutral',
    'ppg_port': '',
    'ppg_baud': 115200,
}


def start(source: str = 'mock', ppg_port: str = '', ppg_baud: int = 115200,
          audio_on: bool = True) -> None:
    """Before Experiment에서 1회 호출."""
    if _state['started']:
        return

    _state['ppg_port'] = ppg_port
    _state['ppg_baud'] = ppg_baud

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

    # 오디오 — 스트림은 항상 열어두고 음소거로 on/off 제어
    # (start/stop 반복은 네이티브 크래시 위험이라 mute 방식 사용)
    try:
        from biofeedback.feedback.audio import AudioFeedback
        audio = AudioFeedback(bus, mode='heartbeat', thump_gain=0.9)
        audio.start()
        audio.set_muted(not audio_on)
        _state['audio'] = audio
        _state['audio_on'] = bool(audio_on)
        print(f'[bf_inline] audio stream up (on={audio_on})')
    except Exception as e:
        _state['audio'] = None
        _state['audio_on'] = False
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


# --- 조작량 로깅 (블록별 증가/감소 정도 기록용) --------------------------------

def get_target_pct() -> float:
    """현재 블록의 '목표' 조작 비율(%). 부호 포함: accel=+25, decel=-25, neutral=0.

    매 블록 시작(set_block_type) 이후의 설계상 목표값. 실제 ramp 진행 중의
    순간 적용량은 get_manipulation_pct()를 사용."""
    bt = _state.get('current_block_type', 'neutral')
    if bt == 'accel':
        return float(TARGET_PCT)
    if bt == 'decel':
        return -float(TARGET_PCT)
    return 0.0


def get_manipulation_pct() -> float:
    """현재 '실제로' 적용 중인 조작 비율(%). 부호 포함 (+증가 / -감소).

    Manipulator factor 기준 — ramp_up 동안 0→target, hold에서 target,
    ramp_down 동안 target→0으로 변함. idle이면 0."""
    m = _state.get('manipulator')
    if m is None:
        return 0.0
    try:
        return float(m.get_status().get('manip_pct', 0.0))
    except Exception:
        return 0.0


def get_manipulator_state() -> str:
    """Manipulator 상태 문자열: 'idle' / 'ramp_up' / 'hold' / 'ramp_down'."""
    m = _state.get('manipulator')
    if m is None:
        return 'idle'
    try:
        return str(m.get_status().get('state', 'idle'))
    except Exception:
        return 'idle'


def get_manip_status() -> dict:
    """조작 상태 전체 dict: {state, manip_pct(실측 적용%), target_pct(목표%),
    block_type, direction}. 한 번에 로깅하기 편하도록 제공."""
    bt = _state.get('current_block_type', 'neutral')
    direction = {'accel': 'increase', 'decel': 'decrease'}.get(bt, 'none')
    m = _state.get('manipulator')
    base = {'state': 'idle', 'manip_pct': 0.0, 'target_pct': get_target_pct()}
    if m is not None:
        try:
            st = m.get_status()
            base['state'] = st.get('state', 'idle')
            base['manip_pct'] = float(st.get('manip_pct', 0.0))
            base['target_pct'] = float(st.get('target_pct', get_target_pct()))
        except Exception:
            pass
    base['block_type'] = bt
    base['direction'] = direction
    return base


# --- 소리 ON/OFF (실험자 설정 화면 [S]) --------------------------------------

def is_audio_on() -> bool:
    return bool(_state.get('audio_on', False)) and _state.get('audio') is not None


def set_audio(on: bool) -> None:
    """오디오 스트림은 유지한 채 음소거만 토글 (스트림 churn 방지)."""
    audio = _state.get('audio')
    if audio is None:
        _state['audio_on'] = False
        return
    try:
        audio.set_muted(not on)
        _state['audio_on'] = bool(on)
    except Exception as e:
        print(f'[bf_inline] set_audio failed: {e}')


def toggle_audio() -> bool:
    """소리 ON/OFF 토글. 현재 상태(bool) 반환."""
    set_audio(not is_audio_on())
    return is_audio_on()


# --- 포트 연결 새로고침/확인 (실험자 설정 화면 [R]) -------------------------

def list_ports() -> list:
    """사용 가능한 시리얼(COM) 포트 목록."""
    try:
        from biofeedback.hr_sources.ppg_serial import list_serial_ports
        return list_serial_ports()
    except Exception:
        return []


def get_source_status() -> dict:
    """현재 HR 소스 연결 상태 dict."""
    sm = _state.get('source_manager')
    if sm is None or getattr(sm, 'current', None) is None:
        return {'kind': None, 'connected': False, 'detail': '소스 없음'}
    src = sm.current
    kind = getattr(sm, 'kind', None)
    if hasattr(src, 'get_status'):
        try:
            st = src.get_status()
            st['kind'] = kind
            return st
        except Exception as e:
            return {'kind': kind, 'connected': False, 'detail': f'상태 조회 실패: {e}'}
    return {'kind': kind, 'connected': True, 'detail': 'mock (70 BPM)'}


def refresh_source() -> dict:
    """포트 연결 재확인/재시도.

    - PPG 모드: 연결 안 돼 있으면 재연결 시도, 결과 dict 반환
    - mock 모드: 사용 가능한 COM 포트 스캔 결과 반환
    """
    sm = _state.get('source_manager')
    bus = _state.get('bus')
    if sm is None:
        return {'connected': False, 'detail': '아직 시작 안 됨'}

    port = str(_state.get('ppg_port', '') or '').strip()
    if not port:
        ports = list_ports()
        detail = ('감지된 포트: ' + ', '.join(ports)) if ports else '감지된 시리얼 포트 없음'
        return {'connected': True, 'kind': 'mock', 'ports': ports, 'detail': detail}

    # PPG 모드
    src = getattr(sm, 'current', None)
    connected = False
    try:
        if src is not None and hasattr(src, 'is_connected'):
            connected = bool(src.is_connected())
    except Exception:
        connected = False

    if connected:
        st = get_source_status()
        sr = st.get('observed_sample_rate', 0.0) or 0.0
        return {'connected': True, 'kind': 'ppg', 'port': port,
                'detail': f'{port} 연결됨 (~{sr:.0f} Hz)'}

    # 재연결 시도
    try:
        from biofeedback.hr_sources.ppg_serial import PPGSerialSource
        new_src = PPGSerialSource(bus, port=port,
                                  baudrate=int(_state.get('ppg_baud', 115200)))
        sm.set_source(new_src, 'ppg')  # start() 내부에서 실패 시 예외
        return {'connected': True, 'kind': 'ppg', 'port': port,
                'detail': f'{port} 연결 성공'}
    except Exception as e:
        return {'connected': False, 'kind': 'ppg', 'port': port,
                'detail': f'{port} 연결 실패: {e}'}


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
