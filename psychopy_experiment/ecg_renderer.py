"""중앙 박동 하트 렌더러 (PsychoPy용).

ECG 라인 없이 화면 중앙의 박동 하트만 표시.

설계:
- vertices는 init 시 1회만 계산 (정규화 크기 1.0 기준)
- 매 프레임 ShapeStim.size 속성만 갱신 → GL 버퍼 재구축 없음 (jitter 제거)
- 비트 스케줄링은 절대 시각(core.getTime()) 기반 — routine 전환에 강함

사용법 (PsychoPy CodeComponent):
    # Welcome Begin Experiment:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ecg_renderer
    ecg_renderer.init(win)

    # Phase Each Frame:
    ecg_renderer.update(t, bpm)   # t 무시, 내부 절대시각 사용
    ecg_renderer.draw()
"""

import math

from psychopy import core as _core

_state: dict = {}

# 모듈 로드 시점 = 절대 시각 기준 0
_T0 = _core.getTime()


def _now() -> float:
    return _core.getTime() - _T0


def _heart_vertices_normalized(n: int = 96) -> list:
    """파라메트릭 하트 (정규화 — 외접원 반지름 ~1).
    x = 16·sin³(t), y = 13·cos(t) − 5·cos(2t) − 2·cos(3t) − cos(4t).
    PsychoPy y-up 좌표계로 y 부호 적용."""
    verts = []
    # 원본 y 범위는 약 -12 ~ +5, x 범위 ±16. 17로 나눠서 ±1 근처로 정규화.
    s = 1.0 / 17.0
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = (13 * math.cos(t)
             - 5 * math.cos(2 * t)
             - 2 * math.cos(3 * t)
             - math.cos(4 * t))
        verts.append((x * s, y * s))
    return verts


def init(
    win,
    heart_pos=(0.0, 0.0),       # 화면 중앙
    heart_size: float = 0.20,   # height units 기준 (전체 화면 높이의 ~20%)
    heart_color="red",
    pop_scale: float = 1.45,    # 박동 시 확대 배율
    decay_factor: float = 0.18, # 매 프레임 (1.0으로 가까워지는) 감쇠율
) -> None:
    """창 생성 후 1회 호출. vertices는 1회 계산 후 고정, .size로 애니메이션."""
    from psychopy import visual

    _state.clear()
    _state.update(
        win=win,
        heart_pos=heart_pos,
        heart_base_size=float(heart_size),
        heart_scale=1.0,
        pop_scale=float(pop_scale),
        decay_factor=float(decay_factor),
        last_beat_t=-1e9,
        bpm=70.0,
    )

    try:
        verts = _heart_vertices_normalized()
        shape = visual.ShapeStim(
            win, name='heart_shape', closeShape=True,
            fillColor=heart_color, lineColor=heart_color,
            lineWidth=1.0,
            pos=heart_pos, units='height',
            vertices=verts,
            size=(heart_size, heart_size),  # 초기 크기 설정
            autoDraw=False,
        )
        _state['heart_shape'] = shape
        print('[ecg_renderer] heart OK (vertices fixed, .size animated)')
    except Exception as e:
        print(f'[ecg_renderer] heart creation failed: {e!r}')
        raise

    print(f'[ecg_renderer] initialized — center heart only, '
          f'pos={heart_pos}, base_size={heart_size}')


def update(t_unused: float = 0.0, bpm: float = 70.0) -> None:
    """매 프레임 호출. 내부 절대 시각 + bpm으로 박동 트리거 + 크기 감쇠."""
    if 'win' not in _state:
        return
    s = _state
    now = _now()
    bpm_safe = max(40.0, float(bpm))
    interval = 60.0 / bpm_safe
    s['bpm'] = bpm_safe

    # 박동 트리거
    if (now - s['last_beat_t']) >= interval:
        s['last_beat_t'] = now
        s['heart_scale'] = s['pop_scale']

    # 감쇠: scale → 1.0으로 매끄럽게 수렴
    s['heart_scale'] += (1.0 - s['heart_scale']) * s['decay_factor']

    # .size 속성만 갱신 (vertices는 그대로) — jitter 제거
    sz = s['heart_base_size'] * s['heart_scale']
    s['heart_shape'].size = (sz, sz)


def draw() -> None:
    """매 프레임 update() 직후 호출."""
    if 'win' not in _state:
        return
    _state['heart_shape'].draw()


def reset_buffer() -> None:
    """이전 API 호환 (no-op + 박동 상태 초기화)."""
    if 'last_beat_t' in _state:
        _state['last_beat_t'] = -1e9
        _state['heart_scale'] = 1.0
