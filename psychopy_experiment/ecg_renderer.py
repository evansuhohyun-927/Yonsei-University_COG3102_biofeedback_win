"""Neon ECG line + parametric heart renderer for PsychoPy.

내부에서 core.getTime() 기반 절대 시각 사용 (PsychoPy routine별 t 리셋 영향 없음).
beat 발생 시각을 리스트로 누적 → bpm 변화해도 과거 beats 위치 고정 (튕김 없음).
N_VERTICES=1250 (250Hz)로 R파 aliasing 방지.

사용법:
    # Welcome Begin Experiment:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ecg_renderer
    ecg_renderer.init(win)

    # Phase Each Frame (t 파라미터는 무시됨 — 내부 클럭 사용):
    ecg_renderer.update(t, bpm)
    ecg_renderer.draw()
"""

import math

import numpy as np
from psychopy import core as _core

_state: dict = {}

# 표시 윈도우 시간
DISPLAY_WINDOW_S = 5.0
# vertices 수 — 100Hz 해상도 (성능과 R파 표현의 균형)
N_VERTICES = 500
# PQRST 사이클 지속 (biofeedback ECGWidget과 동일)
CYCLE_DURATION_S = 0.50

# 모듈 로드 시점을 0으로 잡는 절대 시각 기준
_T0 = _core.getTime()


def _now() -> float:
    return _core.getTime() - _T0


def init(
    win,
    ecg_width: float = 1.6,
    ecg_height: float = 0.35,
    ecg_pos=(0.0, 0.05),
    heart_pos=(0.55, -0.30),
    heart_size: float = 0.22,
) -> None:
    """창이 만들어진 후 1회 호출."""
    from psychopy import visual

    _state.clear()
    _state.update(
        win=win,
        ecg_width=ecg_width,
        ecg_height=ecg_height,
        ecg_pos=ecg_pos,
        heart_size=heart_size,
        heart_pos=heart_pos,
        heart_scale=1.0,
        beats=[],            # beat이 발생한 절대 시각 (오름차순)
        last_beat_t=-1e9,    # 마지막 beat 절대 시각
        bpm=70.0,
    )

    base_verts = [(-ecg_width / 2, 0), (ecg_width / 2, 0)]

    try:
        _state['ecg_halo'] = visual.ShapeStim(
            win, name='ecg_halo', closeShape=False,
            lineWidth=16, lineColor='red',
            opacity=0.22,
            pos=ecg_pos, units='height',
            vertices=base_verts, autoDraw=False,
        )
        print('[ecg_renderer] halo OK')
        _state['ecg_glow'] = visual.ShapeStim(
            win, name='ecg_glow', closeShape=False,
            lineWidth=8, lineColor='red',
            opacity=0.55,
            pos=ecg_pos, units='height',
            vertices=base_verts, autoDraw=False,
        )
        print('[ecg_renderer] glow OK')
        _state['ecg_core'] = visual.ShapeStim(
            win, name='ecg_core', closeShape=False,
            lineWidth=2.5, lineColor='white',
            opacity=1.0,
            pos=ecg_pos, units='height',
            vertices=base_verts, autoDraw=False,
        )
        print('[ecg_renderer] core OK')
        _state['heart_shape'] = visual.ShapeStim(
            win, name='heart_shape', closeShape=True,
            fillColor='red', lineColor='red',
            lineWidth=1.0,
            pos=heart_pos, units='height',
            vertices=_heart_vertices(heart_size),
            autoDraw=False,
        )
        print('[ecg_renderer] heart OK')
    except Exception as e:
        print(f'[ecg_renderer] stim creation failed: {e!r}')
        raise

    print(f'[ecg_renderer] initialized (N_VERTICES={N_VERTICES}, '
          f'window={DISPLAY_WINDOW_S}s, time-based)')


def _heart_vertices(size: float, n: int = 96) -> list:
    """파라메트릭 하트 — PyQt 원본 식, PsychoPy y-up이라 부호 조정."""
    scale = size / 34.0
    verts = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = (13 * math.cos(t)
             - 5 * math.cos(2 * t)
             - 2 * math.cos(3 * t)
             - math.cos(4 * t))
        verts.append((x * scale, y * scale))
    return verts


def _pqrst(x: float) -> float:
    """0~1 진행도에서 PQRST 진폭 (스칼라용, 테스트 호환)."""
    if x < 0.0 or x > 1.0:
        return 0.0

    def g(xx: float, mu: float, sigma: float) -> float:
        return math.exp(-((xx - mu) ** 2) / (2 * sigma * sigma))
    return (
        0.10 * g(x, 0.18, 0.030)
        - 0.12 * g(x, 0.40, 0.013)
        + 1.00 * g(x, 0.46, 0.012)
        - 0.20 * g(x, 0.52, 0.014)
        + 0.32 * g(x, 0.74, 0.045)
    )


def _pqrst_vec(x: np.ndarray) -> np.ndarray:
    """벡터화 PQRST — x: 0~1 진행도 배열."""
    def g(xx, mu, sigma):
        return np.exp(-((xx - mu) ** 2) / (2 * sigma * sigma))
    y = (
        0.10 * g(x, 0.18, 0.030)
        - 0.12 * g(x, 0.40, 0.013)
        + 1.00 * g(x, 0.46, 0.012)
        - 0.20 * g(x, 0.52, 0.014)
        + 0.32 * g(x, 0.74, 0.045)
    )
    # x가 [0,1] 밖이면 0
    y = np.where((x >= 0.0) & (x <= 1.0), y, 0.0)
    return y


def update(t_unused: float = 0.0, bpm: float = 70.0) -> None:
    """매 프레임 호출. t 파라미터는 무시되고 내부 절대 시각 사용 (routine 전환에 강함)."""
    if 'win' not in _state:
        return
    s = _state
    now = _now()
    bpm_safe = max(40.0, float(bpm))
    interval = 60.0 / bpm_safe
    s['bpm'] = bpm_safe

    # 첫 호출: 과거 5초 backfill (display 즉시 가득)
    if not s['beats']:
        t_bf = now
        while t_bf > now - DISPLAY_WINDOW_S - 0.1:
            s['beats'].append(t_bf)
            t_bf -= interval
        s['beats'].sort()
        s['last_beat_t'] = max(s['beats'])
        s['heart_scale'] = 1.45
    elif (now - s['last_beat_t']) >= interval:
        # 정상 진행 + 갭 catch-up (이전 beats 보존, 누락분만 채움)
        next_beat = s['last_beat_t'] + interval
        while next_beat <= now:
            s['beats'].append(next_beat)
            s['last_beat_t'] = next_beat
            next_beat += interval
        s['heart_scale'] = 1.45

    # 디스플레이 윈도우 밖의 오래된 beats 정리
    cutoff = now - DISPLAY_WINDOW_S - 2.0
    if len(s['beats']) > 1 and s['beats'][0] < cutoff:
        s['beats'] = [b for b in s['beats'] if b >= cutoff]

    # 하트 크기 감쇠 (per-frame, 18%씩)
    s['heart_scale'] += (1.0 - s['heart_scale']) * 0.18
    sz = s['heart_size'] * s['heart_scale']
    s['heart_shape'].size = (sz, sz)

    s['now'] = now


def draw() -> None:
    """매 프레임 update() 직후 호출. vertices 갱신 + 3-layer + 하트 그리기."""
    if 'win' not in _state:
        return
    s = _state
    now = s.get('now', _now())
    beats = s.get('beats', [])
    w = s['ecg_width']
    h = s['ecg_height']
    window = DISPLAY_WINDOW_S

    # numpy로 한 번에 계산 → 3 layers에 같은 array 재사용
    verts = np.empty((N_VERTICES, 2), dtype=np.float32)
    xn_arr = np.linspace(0.0, 1.0, N_VERTICES, dtype=np.float32)
    verts[:, 0] = -w / 2 + xn_arr * w
    sample_ts = now - window * (1.0 - xn_arr)

    # beat 기반 PQRST 완전 벡터화
    n_beats = len(beats)
    if n_beats == 0:
        verts[:, 1] = 0.0
    else:
        beats_arr = np.asarray(beats, dtype=np.float64)
        # 각 sample_t에 대해 그 이하인 가장 큰 beat 인덱스
        idxs = np.searchsorted(beats_arr, sample_ts, side='right') - 1
        # 안전한 인덱스 (음수는 0으로 잡고 마스크로 제외)
        safe_idxs = np.clip(idxs, 0, n_beats - 1)
        deltas = sample_ts - beats_arr[safe_idxs]
        # 유효: idx>=0 이고 0 <= delta < CYCLE_DURATION_S
        valid_mask = (idxs >= 0) & (deltas >= 0.0) & (deltas < CYCLE_DURATION_S)
        progress = np.where(valid_mask, deltas / CYCLE_DURATION_S, -1.0)
        ys = _pqrst_vec(progress)
        verts[:, 1] = (ys * h).astype(np.float32)

    s['ecg_halo'].vertices = verts
    s['ecg_glow'].vertices = verts
    s['ecg_core'].vertices = verts

    s['ecg_halo'].draw()
    s['ecg_glow'].draw()
    s['ecg_core'].draw()
    s['heart_shape'].draw()


def reset_buffer() -> None:
    """beat history 초기화 (필요 시)."""
    if 'beats' in _state:
        _state['beats'] = []
        _state['last_beat_t'] = -1e9
        _state['heart_scale'] = 1.0
