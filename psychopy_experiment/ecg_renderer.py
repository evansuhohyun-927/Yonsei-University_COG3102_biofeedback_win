"""중앙 박동 하트 렌더러 (PsychoPy용).

기존에는 네온 ECG 라인 + 우하단 박동 하트를 그렸으나,
이제는 ECG 라인을 제거하고 **화면 중앙의 박동 하트**만 표시한다.

비트 스케줄링은 절대 시각(core.getTime()) 기반으로 routine 전환에 강하며,
bpm 변화 시 미래 박동만 새 interval로 추가됨 (과거 박동 위치 고정).

사용법 (PsychoPy CodeComponent — 호출 API는 이전과 동일):
    # Welcome Begin Experiment:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ecg_renderer
    ecg_renderer.init(win)

    # Phase Each Frame:
    ecg_renderer.update(t, bpm)   # t 파라미터는 무시됨
    ecg_renderer.draw()
"""

import math

from psychopy import core as _core

_state: dict = {}

# 모듈 로드 시점을 0으로 잡는 절대 시각 기준
_T0 = _core.getTime()


def _now() -> float:
    return _core.getTime() - _T0


def init(
    win,
    heart_pos=(0.0, 0.0),       # 화면 중앙
    heart_size: float = 0.45,   # 큼직하게 (height units 기준 ~45%)
    heart_color="red",
) -> None:
    """창이 만들어진 후 1회 호출. 박동 하트만 생성."""
    from psychopy import visual

    _state.clear()
    _state.update(
        win=win,
        heart_size=heart_size,
        heart_pos=heart_pos,
        heart_scale=1.0,
        last_beat_t=-1e9,
        bpm=70.0,
    )

    try:
        _state['heart_shape'] = visual.ShapeStim(
            win, name='heart_shape', closeShape=True,
            fillColor=heart_color, lineColor=heart_color,
            lineWidth=1.0,
            pos=heart_pos, units='height',
            vertices=_heart_vertices(heart_size),
            autoDraw=False,
        )
        print('[ecg_renderer] heart OK (centered, no ECG line)')
    except Exception as e:
        print(f'[ecg_renderer] heart creation failed: {e!r}')
        raise

    print(f'[ecg_renderer] initialized — center heart only, pos={heart_pos}, size={heart_size}')


def _heart_vertices(size: float, n: int = 96) -> list:
    """파라메트릭 하트 — x=16·sin³(t), y=13·cos(t)−5·cos(2t)−2·cos(3t)−cos(4t).
    PsychoPy는 y-up 좌표계이므로 PyQt 원본의 y 부호 반전 적용."""
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


def update(t_unused: float = 0.0, bpm: float = 70.0) -> None:
    """매 프레임 호출. 내부 절대 시각 사용 (routine 전환에 강함).
    t 파라미터는 호환 위해 받지만 사용하지 않음."""
    if 'win' not in _state:
        return
    s = _state
    now = _now()
    bpm_safe = max(40.0, float(bpm))
    interval = 60.0 / bpm_safe
    s['bpm'] = bpm_safe

    # 박동 트리거 (last_beat_t와의 거리가 interval 이상이면 새 박동)
    if (now - s['last_beat_t']) >= interval:
        s['last_beat_t'] = now
        s['heart_scale'] = 1.45  # pop 1.45배

    # 하트 크기 감쇠 (1.45 → 1.0, 매 프레임 18%)
    s['heart_scale'] += (1.0 - s['heart_scale']) * 0.18

    # 새 크기에 맞춰 vertices 재계산 (size에 직접 적용)
    new_size = s['heart_size'] * s['heart_scale']
    s['heart_shape'].vertices = _heart_vertices(new_size)


def draw() -> None:
    """매 프레임 update() 직후 호출. 박동 하트만 그림."""
    if 'win' not in _state:
        return
    _state['heart_shape'].draw()


def reset_buffer() -> None:
    """이전 인터페이스 호환용 (no-op + 박동 상태 초기화)."""
    if 'last_beat_t' in _state:
        _state['last_beat_t'] = -1e9
        _state['heart_scale'] = 1.0
