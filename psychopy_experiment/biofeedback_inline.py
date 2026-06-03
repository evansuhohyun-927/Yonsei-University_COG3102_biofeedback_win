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

import csv
import datetime
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
from biofeedback.core.types import FakeFeedbackParams, BPMSample
from biofeedback.hr_sources.mock import MockHRSource

# Phase 타이밍 (PsychoPy와 일치)
RAMP_UP_S = 180.0    # Phase2 = 9 × 20s
HOLD_S = 45.0        # Phase3
RAMP_DOWN_S = 60.0   # Phase4
TARGET_PCT = 25.0

# ── 마커 코드 표 (fNIRS SNIRF aux1 삽입용 숫자 코드) ──────────────────────────
# PsychoPy가 push하는 마커 문자열 → 숫자 코드. 이벤트 CSV의 'code' 열로 저장되어
# snirf_marker_editor 의 code_column 으로 그대로 사용된다.
# 표에 없는 라벨은 200번부터 자동 배정된다(_code_for).
MARKER_CODES = {
    'experiment_start': 1,   # 로깅 시작 앵커 (onset 0)
    'stabilization': 2,      # 안정화 휴식
    'baseline': 3,           # 베이스라인
    'rest': 4,               # 블록 간 휴식
    'rest_between_blocks': 4,
    # 블록 유형 (Phase1_Sync 시작 시 P1_sync보다 먼저 push됨)
    'accel': 11,
    'decel': 12,
    'neutral': 13,
    # 페이즈
    'P1_sync': 21,
    'P2_ramp': 22,           # 미니 epoch마다(9회) push → 20s 간격 마커
    'P3_plateau': 23,
    'P4_recovery': 24,
    # Likert (블록 내)
    'likert_on': 31,
    'likert_off': 32,
    # 사후 설문
    'postexp_bpm': 41,
    'postexp_trust': 42,
    'maia_start': 43,
    # ── False Cardiac Feedback (고정 BPM) 설계 전용 라벨 ──────────────────
    'practice': 5,            # 연습 시행(70 BPM)
    # 5개 고정 조건의 자극 onset (블록 epoch 앵커 마커)
    'C1_53': 61,              # -25%
    'C2_60': 62,              # -15%
    'C3_70': 63,              #   0% (baseline 표준)
    'C4_81': 64,              # +15%
    'C5_88': 65,              # +25%
    'stim_off': 71,           # 자극 종료
    'assess': 80,             # 평가 구간 진입
    'assess_off': 81,         # 평가 구간 종료
    'q1': 82,                 # Q1 유사도 응답 (value=점수)
    'q2': 83,                 # Q2 편안함 응답
    'q3': 84,                 # Q3 불편함 응답
    'credibility': 90,        # 사후 신뢰도(조작 점검) 응답
    # 종료
    'experiment_end': 99,
    'logging_end': 100,
}

# 마커 라벨 중 '현재 페이즈' 컨텍스트를 갱신하는 것들
_PHASE_LABELS = {
    'stabilization', 'baseline', 'P1_sync', 'P2_ramp', 'P3_plateau',
    'P4_recovery', 'rest', 'rest_between_blocks', 'experiment_end',
    # FCF 고정 BPM 설계
    'practice', 'assess', 'assess_off', 'stim_off',
}

# 로깅 서브시스템 상태 (start_logging/stop_logging가 관리)
_log_lock = threading.Lock()
_log: dict = {
    'active': False,
    't0_perf': None,
    't0_unix': None,
    'events_file': None,
    'events_writer': None,
    'bpm_file': None,
    'bpm_writer': None,
    'bpm_thread': None,
    'bpm_stop': None,
    'events_path': None,
    'bpm_path': None,
    'period': 1.0,
    'auto_codes': {},
    'next_auto_code': 200,
}

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
    'audio_device_index': None,
    'output_bpm': 70.0,
    'real_bpm': 70.0,
    'fixed_mode': False,
    'baseline_bpm': None,
    'calibration_running': False,
    'calibration_failed': False,
    'current_block_type': 'neutral',
    'current_phase': '',
    'ppg_port': '',
    'ppg_baud': 115200,
}


# PPG 보드 식별용 VID (랩 자체 PPG = SEGGER J-Link 기반 보드)
_KNOWN_PPG_VIDS = {0x1366}


def _looks_like_ppg(port: str, baud: int = 115200, sniff_s: float = 0.8) -> bool:
    """포트를 잠깐 열어 숫자 ASCII 라인이 흐르는지 확인 (PPG raw 스트림 판별)."""
    try:
        import serial
        s = serial.Serial(port, baud, timeout=0.5)
    except Exception:
        return False
    try:
        time.sleep(0.2)
        try:
            s.reset_input_buffer()
        except Exception:
            pass
        t0 = time.time()
        good = total = 0
        buf = b''
        while time.time() - t0 < sniff_s:
            chunk = s.read(128)
            if not chunk:
                continue
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                total += 1
                try:
                    float(line.decode('utf-8', 'ignore').strip())
                    good += 1
                except Exception:
                    pass
        return total >= 3 and good >= max(3, int(0.6 * total))
    finally:
        try:
            s.close()
        except Exception:
            pass


def _autodetect_ppg_port(baud: int = 115200) -> str | None:
    """연결된 PPG 시리얼 포트를 자동 탐지.
    1) 알려진 PPG 보드 VID(SEGGER 0x1366)가 단 하나면 즉시 사용(보드 리셋 최소화).
    2) 그 외에는 숫자 ASCII 스트림이 흐르는 포트를 sniff로 찾음.
    """
    try:
        from serial.tools import list_ports
    except Exception:
        return None
    ports = list(list_ports.comports())
    if not ports:
        return None
    known = [p for p in ports if getattr(p, 'vid', None) in _KNOWN_PPG_VIDS]
    if len(known) == 1:
        return known[0].device  # 단일 매칭 → sniff 생략(연결 시 보드 리셋 방지)
    for p in (known or ports):
        try:
            if _looks_like_ppg(p.device, baud):
                return p.device
        except Exception:
            continue
    return known[0].device if known else None


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

    # HR source 선택 — source='mock' 명시가 아니면 PPG 자동 탐지/연결 시도
    want_ppg = (source != 'mock')
    detected_port = None
    if want_ppg:
        p = str(ppg_port or '').strip()
        if p and p.lower() != 'auto':
            detected_port = p  # 실험자가 명시한 포트 그대로
        else:
            detected_port = _autodetect_ppg_port(ppg_baud)
            if detected_port:
                print(f'[bf_inline] PPG 자동 탐지: {detected_port}')
            else:
                print('[bf_inline] PPG 자동 탐지 실패 — 연결된 PPG 포트 없음')

    if want_ppg and detected_port:
        try:
            from biofeedback.hr_sources.ppg_serial import PPGSerialSource
            src = PPGSerialSource(bus, port=detected_port, baudrate=ppg_baud)
            source_manager.set_source(src, 'ppg')
            _state['ppg_port'] = detected_port
            print(f'[bf_inline] PPG source on {detected_port}@{ppg_baud}')
        except Exception as e:
            print(f'[bf_inline] PPG init failed ({e}) — fallback mock')
            source_manager.set_source(MockHRSource(bus), 'mock')
            _state['ppg_port'] = ''
    else:
        source_manager.set_source(MockHRSource(bus), 'mock')
        _state['ppg_port'] = ''
        print('[bf_inline] mock HR source (70 BPM sine)')

    # 오디오 — 스트림은 항상 열어두고 음소거로 on/off 제어
    # (start/stop 반복은 네이티브 크래시 위험이라 mute 방식 사용)
    try:
        from biofeedback.feedback.audio import AudioFeedback
        # 실제 심박 녹음 파일 사용 (없으면 합성음으로 자동 폴백)
        _beat_path = os.path.join(_project, 'biofeedback', 'assets', 'heartbeat.mp3')
        if not os.path.exists(_beat_path):
            _beat_path = None
        audio = AudioFeedback(bus, mode='heartbeat', thump_gain=1.0,  # 최대 볼륨
                              beat_sound_path=_beat_path)
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


# ── 고정 BPM 모드 (False Cardiac Feedback 설계) ──────────────────────────────
# PPG/Manipulator/소스 없이, 각 블록마다 '절대 고정 BPM'(53/60/70/81/88 등)으로
# 심박음(오디오) 또는 시각 박동을 제시하기 위한 경량 시작 경로.
#   - 오디오: BeatScheduler가 bpm_output 을 따라 'beat' 를 내고 AudioFeedback 재생.
#     set_fixed_bpm(b) 이 bpm_output 을 직접 publish 하므로 Manipulator 불필요.
#   - 시각: ecg_renderer.update(t, b) 로 PsychoPy 쪽에서 직접 박동(버스 무관).
#   - 로깅: 기존 start_logging/log_marker 그대로 사용. output_bpm 열 = 제시 BPM.

def start_fixed(audio_on: bool = True) -> None:
    """고정 BPM 모드 1회 시작. bus + BeatScheduler + AudioFeedback 만 구성.

    audio_on=True  → 심박음 재생(청각 모드)
    audio_on=False → 오디오 스트림은 열되 음소거(시각 모드)
    """
    if _state['started']:
        return

    bus = EventBus()
    _state['bus'] = bus
    _state['fixed_mode'] = True

    beat_scheduler = BeatScheduler(bus)
    _state['beat_scheduler'] = beat_scheduler

    # 오디오 — 스트림은 항상 열고 mute 로 on/off (stream churn 방지)
    try:
        from biofeedback.feedback.audio import AudioFeedback
        _beat_path = os.path.join(_project, 'biofeedback', 'assets', 'heartbeat.mp3')
        if not os.path.exists(_beat_path):
            _beat_path = None
        audio = AudioFeedback(bus, mode='heartbeat', thump_gain=1.0,
                              beat_sound_path=_beat_path)
        audio.start()
        audio.set_muted(not audio_on)
        _state['audio'] = audio
        _state['audio_on'] = bool(audio_on)
        print(f'[bf_inline] audio stream up (fixed mode, on={audio_on})')
    except Exception as e:
        _state['audio'] = None
        _state['audio_on'] = False
        print(f'[bf_inline] audio init failed: {e}')

    _state['started'] = True
    print(f'[bf_inline] started (fixed BPM mode, audio_on={audio_on})')


def set_fixed_bpm(bpm: float) -> None:
    """현재 제시할 고정 BPM 설정.

    BeatScheduler(오디오 박자)와 로깅(output_bpm/real_bpm)을 함께 갱신한다.
    시각 모드에서는 ecg_renderer.update(t, bpm) 에 같은 값을 넘기면 된다.
    """
    b = float(bpm)
    _state['output_bpm'] = b
    _state['real_bpm'] = b  # 고정 모드: 제시 BPM = 로그값(실측 PPG 없음)
    bus = _state.get('bus')
    if bus is not None:
        try:
            bus.publish('bpm_output', BPMSample(time.time(), b))
        except Exception as e:
            print(f'[bf_inline] set_fixed_bpm publish err: {e}')


def set_phase(name: str) -> None:
    """로깅용 현재 페이즈 라벨 설정('stim'/'assess'/'rest'/'baseline' 등)."""
    _state['current_phase'] = str(name)


def set_block_label(label: str) -> None:
    """로깅용 현재 블록/조건 라벨 설정(예: 'C3_70'). bpm/events CSV 의
    block_type 열에 기록된다(고정 모드에서는 조건 식별자로 사용)."""
    _state['current_block_type'] = str(label)


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


# --- 데이터 로깅 (PPG BPM 1Hz 시계열 + 이벤트 마커 CSV) ----------------------
#
# start_logging(base_path) 호출 시 두 개의 CSV가 생성된다.
#   {base}_ppg_bpm.csv  : 1초마다 실측/조작 BPM, 조작량, 페이즈/블록을 기록
#   {base}_events.csv    : 키 입력·페이즈 전환 등 이벤트 마커(onset, code, ...)
#                          → snirf_marker_editor 로 .snirf aux1 에 삽입 가능
#
# onset(초)은 start_logging 시점(=onset 0)을 기준으로 한다. fNIRS(NIRSIT)를
# 먼저 켰다면 그 시작 차이만큼 snirf_marker_editor 의 onset_offset 으로 보정한다.


def _code_for(base_label: str) -> int:
    """마커 라벨 → 숫자 코드. 표에 없으면 200번부터 자동 배정."""
    if base_label in MARKER_CODES:
        return int(MARKER_CODES[base_label])
    ac = _log['auto_codes']
    if base_label not in ac:
        ac[base_label] = _log['next_auto_code']
        _log['next_auto_code'] += 1
    return int(ac[base_label])


def start_logging(base_path=None, bpm_period_s: float = 1.0) -> dict:
    """본 실험 시작 시 1회 호출. 두 CSV를 열고 1Hz BPM 기록 스레드를 가동.

    base_path : PsychoPy의 thisExp.dataFileName(확장자 없는 경로)을 주면
                {base}_ppg_bpm.csv / {base}_events.csv 로 저장된다.
                None이면 현재 폴더에 타임스탬프 이름으로 생성.
    """
    if _log['active']:
        return get_log_paths()

    if base_path:
        base = str(base_path)
    else:
        base = os.path.join(
            os.getcwd(),
            'bf_log_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))

    events_path = base + '_events.csv'
    bpm_path = base + '_ppg_bpm.csv'
    d = os.path.dirname(events_path)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass

    t0_perf = time.perf_counter()
    t0_unix = time.time()

    # utf-8-sig(BOM) → Excel에서 한글 깨짐 방지
    ev_file = open(events_path, 'w', newline='', encoding='utf-8-sig')
    ev_writer = csv.writer(ev_file)
    ev_writer.writerow(['onset', 'code', 'label', 'value',
                        'block_type', 'phase', 'unix_time', 'iso_time'])
    ev_file.flush()

    bpm_file = open(bpm_path, 'w', newline='', encoding='utf-8-sig')
    bpm_writer = csv.writer(bpm_file)
    bpm_writer.writerow(['t_sec', 'unix_time', 'iso_time',
                         'real_bpm', 'output_bpm', 'manip_pct',
                         'manip_state', 'block_type', 'phase'])
    bpm_file.flush()

    _log.update({
        't0_perf': t0_perf,
        't0_unix': t0_unix,
        'events_file': ev_file,
        'events_writer': ev_writer,
        'bpm_file': bpm_file,
        'bpm_writer': bpm_writer,
        'events_path': events_path,
        'bpm_path': bpm_path,
        'period': max(0.05, float(bpm_period_s)),
        'active': True,
    })

    iso0 = datetime.datetime.fromtimestamp(t0_unix).isoformat(timespec='milliseconds')
    print(f'[bf_inline] logging 시작: onset 0 = {iso0} (unix={t0_unix:.3f})')
    print(f'[bf_inline]   events: {events_path}')
    print(f'[bf_inline]   bpm   : {bpm_path}')

    # onset 0 앵커 마커
    log_marker('experiment_start')

    stop_evt = threading.Event()
    th = threading.Thread(target=_bpm_log_loop, args=(stop_evt,), daemon=True)
    _log['bpm_stop'] = stop_evt
    _log['bpm_thread'] = th
    th.start()
    return get_log_paths()


def log_marker(label, value=None, code=None) -> None:
    """이벤트 마커 1건을 events CSV에 기록.

    label : 마커 문자열. 'likert_on:질문…' 처럼 ':'가 있으면 앞부분이 라벨,
            뒷부분이 value로 분리 저장된다.
    value : 부가 정보(예: Likert 응답값). 생략 가능.
    code  : 강제 코드. None이면 MARKER_CODES/자동배정으로 결정.
    """
    if not _log['active']:
        return
    raw = str(label)
    base = raw
    if ':' in raw:
        base, _, rest = raw.partition(':')
        if value is None:
            value = rest
    base = base.strip()

    c = int(code) if code is not None else _code_for(base)
    onset = time.perf_counter() - _log['t0_perf']
    unix = time.time()
    iso = datetime.datetime.fromtimestamp(unix).isoformat(timespec='milliseconds')

    # 페이즈/블록 컨텍스트 갱신
    if base in _PHASE_LABELS:
        _state['current_phase'] = base
    if base in ('accel', 'decel', 'neutral'):
        _state['current_block_type'] = base
    bt = _state.get('current_block_type', '')
    ph = _state.get('current_phase', '')

    with _log_lock:
        w = _log['events_writer']
        f = _log['events_file']
        if w is not None and f is not None:
            try:
                w.writerow([f'{onset:.3f}', c, base,
                            ('' if value is None else value), bt, ph,
                            f'{unix:.3f}', iso])
                f.flush()
            except Exception as e:
                print(f'[bf_inline] log_marker write err: {e!r}')


def _bpm_log_loop(stop_evt: threading.Event) -> None:
    """1초마다 BPM/조작량을 bpm CSV에 기록하는 데몬 스레드."""
    period = _log['period']
    while not stop_evt.wait(period):
        try:
            onset = time.perf_counter() - _log['t0_perf']
            unix = time.time()
            iso = datetime.datetime.fromtimestamp(unix).isoformat(
                timespec='milliseconds')
            rb = get_real_bpm()
            ob = get_output_bpm()
            mp = get_manipulation_pct()
            ms = get_manipulator_state()
            bt = _state.get('current_block_type', '')
            ph = _state.get('current_phase', '')
            with _log_lock:
                w = _log['bpm_writer']
                f = _log['bpm_file']
                if w is not None and f is not None:
                    w.writerow([f'{onset:.3f}', f'{unix:.3f}', iso,
                                f'{rb:.2f}', f'{ob:.2f}', f'{mp:.2f}',
                                ms, bt, ph])
                    f.flush()
        except Exception as e:
            print(f'[bf_inline] bpm log err: {e!r}')


def stop_logging() -> None:
    """로깅 종료 — 스레드 정지 + 파일 닫기. stop()에서 자동 호출됨."""
    if not _log['active']:
        return
    try:
        log_marker('logging_end')
    except Exception:
        pass
    se = _log.get('bpm_stop')
    if se is not None:
        se.set()
    th = _log.get('bpm_thread')
    if th is not None:
        try:
            th.join(timeout=2.0)
        except Exception:
            pass
    with _log_lock:
        for k in ('events_file', 'bpm_file'):
            fobj = _log.get(k)
            if fobj is not None:
                try:
                    fobj.flush()
                    fobj.close()
                except Exception:
                    pass
        _log['events_writer'] = None
        _log['bpm_writer'] = None
        _log['events_file'] = None
        _log['bpm_file'] = None
    _log['active'] = False
    print('[bf_inline] logging stopped')


def is_logging() -> bool:
    return bool(_log.get('active', False))


def get_log_paths() -> dict:
    return {
        'events': _log.get('events_path'),
        'bpm': _log.get('bpm_path'),
        'active': bool(_log.get('active', False)),
    }


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


# --- 오디오 출력 장치 선택 (실험자 설정 화면 [D]) ----------------------------

def list_audio_devices() -> list:
    """이름 기준으로 중복 제거된 출력 장치 목록."""
    audio = _state.get('audio')
    if audio is None:
        return []
    try:
        return audio.list_output_devices()
    except Exception as e:
        print(f'[bf_inline] list_audio_devices failed: {e}')
        return []


def get_audio_device_name() -> str:
    """현재 소리가 나가는 출력 장치 이름."""
    audio = _state.get('audio')
    if audio is None:
        return '없음'
    try:
        return audio.current_device_name()
    except Exception:
        return '알 수 없음'


def set_audio_device(index) -> bool:
    """출력 장치를 index로 전환(스트림 재오픈). 성공 여부 반환."""
    audio = _state.get('audio')
    if audio is None:
        return False
    try:
        ok = bool(audio.set_device(index))
        if ok:
            _state['audio_device_index'] = index
        return ok
    except Exception as e:
        print(f'[bf_inline] set_audio_device failed: {e}')
        return False


def cycle_audio_device() -> str:
    """다음 출력 장치로 전환하고 새 장치 이름 반환 (실험자 [D]).
    이어폰으로 소리를 보내려면 이어폰 장치가 나올 때까지 [D]를 반복.
    열기 실패하는 장치(다른 앱이 점유한 배타 모드 등)는 건너뛴다."""
    audio = _state.get('audio')
    if audio is None:
        return '없음'
    devs = list_audio_devices()
    if not devs:
        return get_audio_device_name()
    indices = [d['index'] for d in devs]
    cur = _state.get('audio_device_index', None)
    start = indices.index(cur) + 1 if cur in indices else 0
    n = len(indices)
    for off in range(n):
        cand = indices[(start + off) % n]
        if set_audio_device(cand):
            return get_audio_device_name()
    # 어느 장치도 열리지 않으면 현재 상태 유지
    return get_audio_device_name()


# --- 포트 연결 새로고침/확인 (실험자 설정 화면 [R]) -------------------------

def list_ports() -> list:
    """사용 가능한 시리얼(COM) 포트 목록."""
    try:
        from biofeedback.hr_sources.ppg_serial import list_serial_ports
        return list_serial_ports()
    except Exception:
        return []


def get_active_port() -> str:
    """실제 연결된 PPG 포트명. mock이면 빈 문자열."""
    sm = _state.get('source_manager')
    if sm is not None and getattr(sm, 'kind', None) == 'ppg':
        return str(_state.get('ppg_port', '') or '')
    return ''


def is_ppg_active() -> bool:
    """현재 실측 소스가 PPG면 True, mock이면 False."""
    sm = _state.get('source_manager')
    return sm is not None and getattr(sm, 'kind', None) == 'ppg'


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
        # 현재 mock — PPG 자동 탐지 후 연결 시도 (실행 중 PPG를 꽂은 경우 대응)
        baud = int(_state.get('ppg_baud', 115200))
        detected = _autodetect_ppg_port(baud)
        if detected:
            try:
                from biofeedback.hr_sources.ppg_serial import PPGSerialSource
                new_src = PPGSerialSource(bus, port=detected, baudrate=baud)
                sm.set_source(new_src, 'ppg')
                _state['ppg_port'] = detected
                return {'connected': True, 'kind': 'ppg', 'port': detected,
                        'detail': f'{detected} 자동 연결 성공'}
            except Exception as e:
                return {'connected': False, 'kind': 'mock', 'port': detected,
                        'detail': f'{detected} 연결 실패: {e}'}
        ports = list_ports()
        detail = ('감지된 포트: ' + ', '.join(ports) + ' (PPG 데이터 없음)') if ports else '감지된 시리얼 포트 없음'
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
    try:
        stop_logging()
    except Exception:
        pass
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
