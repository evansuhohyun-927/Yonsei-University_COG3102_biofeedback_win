# -*- coding: utf-8 -*-
"""Generator for fNIRS_FalseCardiacFeedback.psyexp (new fixed-BPM design).

Run with the bundled PsychoPy interpreter:
    "C:\\Program Files\\PsychoPy\\python.exe" _build_fcf.py

Builds a Builder-compatible .psyexp via PsychoPy's own Experiment API
(guaranteed-valid XML), then compiles it to _lastrun.py for verification.

Design (per artifact):
  5 fixed conditions  C1=53(-25%) C2=60(-15%) C3=70(0%) C4=81(+15%) C5=88(+25%)
  10 blocks (5 x 2), Latin-square-ish per-participant order, no consecutive
  acceleration (C4/C5) blocks. Each block: Stimulus 30s -> Assessment 20s
  (Q1 similarity / Q2 comfort / Q3 discomfort, sequential keys 1-7, 20s cap)
  -> Rest 10+-2s jitter. Modality (auditory|visual) chosen at startup.
  Baseline 2min, Practice 70BPM 30s, Exit Q4 credibility. MAIA excluded;
  baseline BPM (smartwatch) entered manually as covariate.
"""
import os
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from psychopy import experiment
from psychopy.experiment.routines import Routine
from psychopy.experiment.loops import TrialHandler
from psychopy.experiment.components.code import CodeComponent
from psychopy.experiment.components.text import TextComponent

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fNIRS_FalseCardiacFeedback.psyexp")

exp = experiment.Experiment()
S = exp.settings.params
S['expName'].val = 'fNIRS_FalseCardiacFeedback'
S['Experiment info'].val = (
    "{'participant': '000', 'session': '001', "
    "'feedback_modality': ['auditory', 'visual'], "
    "'baseline_bpm': '', 'caffeine': ['no', 'yes'], "
    "'smoking': ['no', 'yes'], 'age': '', 'sex': ['F', 'M', 'other']}"
)
S['Data filename'].val = (
    "u'data/%s_%s_%s' % (expInfo['participant'], expName, expInfo['date'])"
)
S['Full-screen window'].val = False
S['Screen'].val = 1
S['Units'].val = 'height'
S['Window size (pixels)'].val = '(1280, 720)'
S['Save wide csv file'].val = True
S['Save psydat file'].val = True
S['Audio lib'].val = 'ptb'
S['Force stereo'].val = True
S['Show info dlg'].val = True
S['Show mouse'].val = False
S['Enable Escape'].val = True
S['color'].val = '$[-1,-1,-1]'
S['keyboardBackend'].val = 'PsychToolbox'
S['End Message'].val = '참여해 주셔서 감사합니다.'


def add_code(routine, name, **blocks):
    """Attach a Python CodeComponent to routine. blocks keys are param names
    like 'Before Experiment', 'Begin Experiment', 'Begin Routine',
    'Each Frame', 'End Routine', 'End Experiment'."""
    cc = CodeComponent(exp=exp, parentName=routine.name, name=name)
    cc.params['Code Type'].val = 'Py'
    for k, v in blocks.items():
        cc.params[k].val = v
    routine.addComponent(cc)
    return cc


def make_routine(name):
    rt = Routine(name=name, exp=exp)
    exp.addRoutine(name, rt)
    return rt


def add_anchor(routine, name='_keep'):
    """Append an invisible, never-finishing TextComponent so the auto-generated
    'has every Component finished?' loop keeps continueRoutine True. Without at
    least one real Builder component (CodeComponents are NOT in routine.components),
    a code-only routine would end after a single frame. start=0, no stop time =>
    status stays STARTED for the whole routine; our code sets continueRoutine=False
    to end it (which triggers the forceEnded break BEFORE the override fires)."""
    tc = TextComponent(exp=exp, parentName=routine.name, name=name)
    tc.params['text'].val = ' '
    tc.params['startType'].val = 'time (s)'
    tc.params['startVal'].val = '0'
    tc.params['stopType'].val = 'duration (s)'
    tc.params['stopVal'].val = ''          # no stop -> never FINISHED
    tc.params['opacity'].val = '0'         # fully transparent (belt + braces)
    tc.params['saveStartStop'].val = False
    routine.addComponent(tc)
    return tc


# ────────────────────────────────────────────────────────────────────────────
# Routine: Intro  (imports + backend start + shared stims + sequence)
# ────────────────────────────────────────────────────────────────────────────
intro = make_routine('Intro')

BEFORE_EXP = r'''import os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
print('[fcf] === Before Experiment ===')

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import biofeedback_inline as bf
import ecg_renderer
from psychopy import event

# fNIRS 동기 마커 outlet (LSL 있으면 사용, 없으면 더미). 모든 push는 events CSV
# 로깅(bf.log_marker)에도 기록되어 사후 SNIRF aux1 삽입 소스가 된다.
class _NullOutlet:
    def push_sample(self, *a, **k):
        pass
outlet = _NullOutlet()
try:
    from pylsl import StreamInfo, StreamOutlet
    info = StreamInfo('PsychoPyMarkers', 'Markers', 1, 0, 'string', 'psychopy_markers')
    outlet = StreamOutlet(info)
    print('[fcf] LSL outlet PsychoPyMarkers up')
except Exception as _e:
    print(f'[fcf] LSL outlet unavailable: {_e!r}')

class _LoggingOutlet:
    def __init__(self, inner):
        self._inner = inner
    def push_sample(self, x, *a, **k):
        try:
            self._inner.push_sample(x, *a, **k)
        except Exception:
            pass
        try:
            _lab = x[0] if isinstance(x, (list, tuple)) else x
            bf.log_marker(str(_lab))
        except Exception:
            pass
outlet = _LoggingOutlet(outlet)
'''

BEGIN_EXP = r'''print('[fcf] === Begin Experiment ===')

# 모달리티: auditory(심박음) / visual(박동 하트)
modality = str(expInfo.get('feedback_modality', 'auditory')).strip().lower()
audio_mode = (modality == 'auditory')
print(f'[fcf] feedback_modality = {modality}  (audio_mode={audio_mode})')

# 고정 BPM 백엔드 시작 (오디오 모드면 소리 ON, 시각 모드면 음소거)
bf.start_fixed(audio_on=audio_mode)

# 시각 박동 렌더러 (시각 모드 전용이지만 init은 항상)
try:
    ecg_renderer.init(win)
    _ecg_ok = True
except Exception as _e:
    print(f'[fcf] ecg_renderer init failed: {_e!r}')
    _ecg_ok = False

# 공용 자극 stim
fix_stim = visual.TextStim(win, name='fix_stim', text='+', height=0.10,
                           color='white', pos=(0, 0))
msg_stim = visual.TextStim(win, name='msg_stim', text='', height=0.045,
                           color='white', pos=(0, 0.36), wrapWidth=1.4,
                           alignText='center')
q_stim = visual.TextStim(win, name='q_stim', text='', height=0.052,
                         color='white', pos=(0, 0.05), wrapWidth=1.5,
                         alignText='center')
status_stim = visual.TextStim(win, name='status_stim', text='', height=0.026,
                              color=(-0.2, -0.2, -0.2), pos=(0, -0.45),
                              wrapWidth=1.6, alignText='center')

# 5개 고정 조건 (70 BPM 표준 대비 편차)
CONDITIONS = [
    {'cond': 'C1', 'bpm': 53, 'dev': -25, 'label': 'C1_53', 'accel': False},
    {'cond': 'C2', 'bpm': 60, 'dev': -15, 'label': 'C2_60', 'accel': False},
    {'cond': 'C3', 'bpm': 70, 'dev':   0, 'label': 'C3_70', 'accel': False},
    {'cond': 'C4', 'bpm': 81, 'dev':  15, 'label': 'C4_81', 'accel': True},
    {'cond': 'C5', 'bpm': 88, 'dev':  25, 'label': 'C5_88', 'accel': True},
]
N_REPS_PER_COND = 2

# 참가자 번호로 시드 (재현성) + 연속 가속(C4/C5) 금지 제약
import random as _random
try:
    _seed = int(''.join(ch for ch in str(expInfo.get('participant', '0')) if ch.isdigit()) or '0')
except Exception:
    _seed = 0
_rng = _random.Random(_seed)

def _gen_block_sequence():
    base = []
    for c in CONDITIONS:
        base += [c] * N_REPS_PER_COND
    for _ in range(5000):
        _rng.shuffle(base)
        ok = True
        for i in range(1, len(base)):
            if base[i]['accel'] and base[i - 1]['accel']:
                ok = False
                break
        if ok:
            return list(base)
    print('[fcf] WARN: 연속 가속 제약을 만족하는 순서를 못 찾음 — 무작위 순서 사용')
    return list(base)

block_sequence = _gen_block_sequence()
print('[fcf] block order:', [b['label'] for b in block_sequence])

# 공변량 저장
def _to_float(x):
    try:
        return float(str(x).strip())
    except Exception:
        return float('nan')
thisExp.addData('block_order', ','.join(b['label'] for b in block_sequence))
thisExp.addData('feedback_modality', modality)
thisExp.addData('baseline_bpm_smartwatch', _to_float(expInfo.get('baseline_bpm', '')))
thisExp.addData('caffeine', expInfo.get('caffeine', ''))
thisExp.addData('smoking', expInfo.get('smoking', ''))
thisExp.addData('age', expInfo.get('age', ''))
thisExp.addData('sex', expInfo.get('sex', ''))
'''

INTRO_FRAME = r'''q_stim.text = ('심박 지각 실험에 오신 것을 환영합니다.\n\n'
               '한 손가락을 반대쪽 손목 맥박 위에 가볍게 올려두고\n'
               '실험 내내 그 자세를 유지하세요.\n\n'
               + ('각 구간에서 들리는 심장 박동 소리와\n' if audio_mode
                  else '각 구간에서 보이는 심장 박동과\n')
               + '본인의 손목 맥박을 비교하게 됩니다.\n\n'
               '준비되면 스페이스바를 누르세요.')
q_stim.draw()
if 'space' in event.getKeys(keyList=['space']):
    continueRoutine = False
if 'escape' in event.getKeys(keyList=['escape']):
    core.quit()
'''

add_code(intro, 'code_intro',
         **{'Before Experiment': BEFORE_EXP,
            'Begin Experiment': BEGIN_EXP,
            'Each Frame': INTRO_FRAME})

# ────────────────────────────────────────────────────────────────────────────
# Routine: Baseline (120s pulse palpation + fixation, no feedback)
# ────────────────────────────────────────────────────────────────────────────
baseline = make_routine('Baseline')

BASE_BEGIN = r'''# 본 실험 로깅 시작 — onset 0 = baseline 시작 (fNIRS 동기 앵커)
try:
    _lp = bf.start_logging(thisExp.dataFileName)
    print('[fcf] logging:', _lp)
except Exception as _e:
    print('[fcf] start_logging failed:', repr(_e))
bf.set_block_label('baseline')
bf.set_phase('baseline')
if audio_mode:
    bf.set_audio(False)
outlet.push_sample(['baseline'])
thisExp.addData('phase', 'baseline')
thisExp.addData('phase_onset', core.getTime())
_BASE_DUR = 120.0
'''

BASE_FRAME = r'''secs_left = max(0, int(_BASE_DUR - t))
msg_stim.text = ('안정 구간\n\n손목 맥박에 집중하며 편안히 쉬세요.\n\n'
                 f'남은 시간: {secs_left}초    (스페이스=건너뛰기)')
msg_stim.draw()
fix_stim.draw()
_k = event.getKeys(keyList=['space', 'escape'])
if 'escape' in _k:
    core.quit()
if 'space' in _k or t >= _BASE_DUR:
    continueRoutine = False
'''

add_code(baseline, 'code_baseline',
         **{'Begin Routine': BASE_BEGIN, 'Each Frame': BASE_FRAME})

# ────────────────────────────────────────────────────────────────────────────
# Routine: Practice (single 70 BPM trial, 30s)
# ────────────────────────────────────────────────────────────────────────────
practice = make_routine('Practice')

PRAC_BEGIN = r'''bf.set_block_label('practice')
bf.set_phase('practice')
bf.set_fixed_bpm(70)
if audio_mode:
    bf.set_audio(True)
outlet.push_sample(['practice'])
thisExp.addData('phase', 'practice')
thisExp.addData('phase_onset', core.getTime())
_PRAC_DUR = 30.0
'''

PRAC_FRAME = r'''remain = max(0, int(_PRAC_DUR - t))
if audio_mode:
    fix_stim.draw()
    msg_stim.text = ('연습\n\n지금 들리는 심장 박동을 들으며\n손목 맥박과 비교해 보세요.\n\n'
                     f'{remain}초')
else:
    if _ecg_ok:
        ecg_renderer.update(t, 70)
        ecg_renderer.draw()
    msg_stim.text = ('연습\n\n지금 보이는 심장 박동을 보며\n손목 맥박과 비교해 보세요.\n\n'
                     f'{remain}초')
msg_stim.draw()
if 'escape' in event.getKeys(keyList=['escape']):
    core.quit()
if t >= _PRAC_DUR:
    continueRoutine = False
'''

PRAC_END = r'''if audio_mode:
    bf.set_audio(False)
'''

add_code(practice, 'code_practice',
         **{'Begin Routine': PRAC_BEGIN, 'Each Frame': PRAC_FRAME,
            'End Routine': PRAC_END})

# ────────────────────────────────────────────────────────────────────────────
# Loop body routines: Stimulus / Assessment / Rest
# ────────────────────────────────────────────────────────────────────────────
stimulus = make_routine('Stimulus')

STIM_BEGIN = r'''cond = block_sequence[block_loop.thisN]
_stim_bpm = cond['bpm']
bf.set_block_label(cond['label'])
bf.set_phase('stim')
bf.set_fixed_bpm(_stim_bpm)
if audio_mode:
    bf.set_audio(True)
outlet.push_sample([cond['label']])   # 조건별 자극 onset 마커 (code 61~65)
thisExp.addData('phase', 'stim')
thisExp.addData('phase_onset', core.getTime())
_STIM_DUR = 30.0
'''

STIM_FRAME = r'''cond = block_sequence[block_loop.thisN]
remain = max(0, int(_STIM_DUR - t))
if audio_mode:
    fix_stim.draw()
    msg_stim.text = f'심장 박동을 들으며 손목 맥박과 비교하세요   ({remain}s)'
else:
    if _ecg_ok:
        ecg_renderer.update(t, _stim_bpm)
        ecg_renderer.draw()
    msg_stim.text = f'심장 박동을 보며 손목 맥박과 비교하세요   ({remain}s)'
msg_stim.draw()
status_stim.text = (f'[{block_loop.thisN + 1}/10] {cond["label"]}  '
                    f'bpm={_stim_bpm}  ({"AUD" if audio_mode else "VIS"})')
status_stim.draw()
if 'escape' in event.getKeys(keyList=['escape']):
    core.quit()
if t >= _STIM_DUR:
    continueRoutine = False
'''

STIM_END = r'''outlet.push_sample(['stim_off'])
'''

add_code(stimulus, 'code_stim',
         **{'Begin Routine': STIM_BEGIN, 'Each Frame': STIM_FRAME,
            'End Routine': STIM_END})

assessment = make_routine('Assessment')

ASSESS_BEGIN = r'''if audio_mode:
    bf.set_audio(False)          # 평가 중 소리 OFF
bf.set_phase('assess')
outlet.push_sample(['assess'])
_qidx = 0
_qresp = [None, None, None]
_qrt = [None, None, None]
_ASSESS_DUR = 20.0
_q_onset = core.getTime()
_QTEXTS = [
    ('Q1.  방금 제시된 심장 박동이\n본인의 실제 맥박과 얼마나 일치했습니까?\n\n'
     '1 (전혀 일치하지 않음)   …   7 (매우 일치함)\n\n숫자 키 1–7'),
    ('Q2.  방금 자극이 얼마나 편안했습니까?\n\n'
     '1 (전혀 편안하지 않음)   …   7 (매우 편안함)\n\n숫자 키 1–7'),
    ('Q3.  방금 자극이 얼마나 불편했습니까?\n\n'
     '1 (전혀 불편하지 않음)   …   7 (매우 불편함)\n\n숫자 키 1–7'),
]
event.clearEvents()
'''

ASSESS_FRAME = r'''if _qidx < 3:
    q_stim.text = _QTEXTS[_qidx]
    q_stim.draw()
_keys = event.getKeys(keyList=['1', '2', '3', '4', '5', '6', '7', 'escape'])
if 'escape' in _keys:
    core.quit()
if _keys and _qidx < 3:
    _qresp[_qidx] = int(_keys[0])
    _qrt[_qidx] = core.getTime() - _q_onset
    outlet.push_sample([f'q{_qidx + 1}:{_qresp[_qidx]}'])
    _qidx += 1
if _qidx >= 3 or t >= _ASSESS_DUR:
    continueRoutine = False
'''

ASSESS_END = r'''cond = block_sequence[block_loop.thisN]
_labels = ['Q1_similarity', 'Q2_comfort', 'Q3_discomfort']
for _i in range(3):
    thisExp.addData(_labels[_i], _qresp[_i])
    thisExp.addData(_labels[_i] + '_rt', _qrt[_i])
thisExp.addData('block_idx', block_loop.thisN)
thisExp.addData('cond', cond['cond'])
thisExp.addData('cond_label', cond['label'])
thisExp.addData('bpm', cond['bpm'])
thisExp.addData('deviation_pct', cond['dev'])
thisExp.addData('is_accel', cond['accel'])
thisExp.addData('feedback_modality', modality)
# Q1 이분화 (IV): <=3 discord / >=5 match / ==4 excluded
_q1 = _qresp[0]
if _q1 is None:
    _iv = 'NA'
elif _q1 <= 3:
    _iv = 'discord'
elif _q1 >= 5:
    _iv = 'match'
else:
    _iv = 'excluded'
thisExp.addData('Q1_class', _iv)
outlet.push_sample(['assess_off'])
'''

add_code(assessment, 'code_assess',
         **{'Begin Routine': ASSESS_BEGIN, 'Each Frame': ASSESS_FRAME,
            'End Routine': ASSESS_END})

rest = make_routine('Rest')

REST_BEGIN = r'''bf.set_phase('rest')
outlet.push_sample(['rest'])
_REST_DUR = float(10.0 + (np.random.rand() * 4.0 - 2.0))   # 10 ± 2 s jitter
thisExp.addData('rest_dur', round(_REST_DUR, 3))
'''

REST_FRAME = r'''fix_stim.draw()
if 'escape' in event.getKeys(keyList=['escape']):
    core.quit()
if t >= _REST_DUR:
    continueRoutine = False
'''

add_code(rest, 'code_rest',
         **{'Begin Routine': REST_BEGIN, 'Each Frame': REST_FRAME})

# ────────────────────────────────────────────────────────────────────────────
# Routine: ExitSurvey (Q4 credibility / manipulation check)
# ────────────────────────────────────────────────────────────────────────────
exit_survey = make_routine('ExitSurvey')

EXIT_BEGIN = r'''if audio_mode:
    bf.set_audio(False)
bf.set_phase('postexp')
_cred = None
event.clearEvents()
'''

EXIT_FRAME = r'''q_stim.text = ('Q4.  이 실험에서 제시된 심장 박동이\n'
               '실제 본인의 심장 박동이라고\n어느 정도 믿으셨습니까?\n\n'
               '1 (전혀 믿지 않음)   …   7 (완전히 믿음)\n\n숫자 키 1–7')
q_stim.draw()
_k = event.getKeys(keyList=['1', '2', '3', '4', '5', '6', '7', 'escape'])
if 'escape' in _k:
    core.quit()
if _k:
    _cred = int(_k[0])
    outlet.push_sample([f'credibility:{_cred}'])
    thisExp.addData('Q4_credibility', _cred)
    continueRoutine = False
'''

add_code(exit_survey, 'code_exit',
         **{'Begin Routine': EXIT_BEGIN, 'Each Frame': EXIT_FRAME})

# ────────────────────────────────────────────────────────────────────────────
# Routine: Debrief
# ────────────────────────────────────────────────────────────────────────────
debrief = make_routine('Debrief')

DEBRIEF_BEGIN = r'''outlet.push_sample(['experiment_end'])
'''

DEBRIEF_FRAME = r'''q_stim.text = ('실험이 끝났습니다.\n\n참여해 주셔서 감사합니다.\n\n'
               '스페이스바를 누르면 종료됩니다.')
q_stim.draw()
if 'space' in event.getKeys(keyList=['space']):
    continueRoutine = False
'''

DEBRIEF_END = r'''try:
    bf.stop()
except Exception as _e:
    print('[fcf] bf.stop err:', repr(_e))
'''

add_code(debrief, 'code_debrief',
         **{'Begin Routine': DEBRIEF_BEGIN, 'Each Frame': DEBRIEF_FRAME,
            'End Routine': DEBRIEF_END})

# ────────────────────────────────────────────────────────────────────────────
# Each routine is code-only; add an invisible anchor so it doesn't end after
# one frame (CodeComponents are not counted in routine.components).
# ────────────────────────────────────────────────────────────────────────────
for _rt in (intro, baseline, practice, stimulus, assessment, rest,
            exit_survey, debrief):
    add_anchor(_rt)

# ────────────────────────────────────────────────────────────────────────────
# Flow: Intro, Baseline, Practice, [loop: Stimulus, Assessment, Rest],
#       ExitSurvey, Debrief
# ────────────────────────────────────────────────────────────────────────────
exp.flow.addRoutine(intro, 0)
exp.flow.addRoutine(baseline, 1)
exp.flow.addRoutine(practice, 2)
exp.flow.addRoutine(stimulus, 3)
exp.flow.addRoutine(assessment, 4)
exp.flow.addRoutine(rest, 5)
exp.flow.addRoutine(exit_survey, 6)
exp.flow.addRoutine(debrief, 7)

block_loop = TrialHandler(exp, name='block_loop', loopType='sequential',
                          nReps=10, conditions=(), conditionsFile='')
# wrap flow[3:6] = Stimulus, Assessment, Rest  → initiator@3, terminator@6
exp.flow.addLoop(block_loop, 3, 6)

exp.saveToXML(OUT)
print('SAVED', OUT)

# 즉시 컴파일 검증 → _lastrun.py
script = exp.writeScript(expPath=OUT)
lastrun = os.path.join(HERE, 'fNIRS_FalseCardiacFeedback_lastrun.py')
with open(lastrun, 'w', encoding='utf-8') as f:
    f.write(script)
print('WROTE', lastrun, len(script), 'chars')

# 플로우 순서 출력
print('FLOW:')
for item in exp.flow:
    nm = getattr(item, 'name', None) or type(item).__name__
    print('  ', type(item).__name__, nm)
