# -*- coding: utf-8 -*-
"""Generator for MAIA_Survey.psyexp (한국어 24문항 MAIA 설문).

Run with the bundled PsychoPy interpreter:
    "C:\\Program Files\\PsychoPy\\python.exe" _build_maia.py

Builds a Builder-compatible .psyexp via PsychoPy's own Experiment API,
then compiles it to _lastrun.py for verification.

설계:
  문항은 conditions/maia_items.xlsx 를 런타임에 로딩한다(하드코딩 X).
    컬럼: item_num, item_text(한국어), subscale, reverse(0/1)
    24문항 / 8 하위척도(각 3문항):
      Noticing, Not-Distracting, Not-Worrying, Attention-Regulation,
      Emotional-Awareness, Self-Regulation, Body-Listening, Trusting
    역채점 문항: 5, 6, 9  (scored = 5 - raw)
  척도: 0(전혀 그렇지 않다) ~ 5(항상 그렇다)  → 숫자 키 0–5
  Flow: Intro → [loop maia_loop: Item] → End(하위척도 점수 계산/저장)
  출력: PsychoPy wide CSV(문항별) + {participant}_MAIA_{date}_subscales.csv(요약)
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
OUT = os.path.join(HERE, "MAIA_Survey.psyexp")
COND_FILE = 'conditions/maia_items.xlsx'

exp = experiment.Experiment()
S = exp.settings.params
S['expName'].val = 'MAIA_Survey'
S['Experiment info'].val = (
    "{'participant': '000', 'session': '001', "
    "'age': '', 'sex': ['F', 'M', 'other']}"
)
S['Data filename'].val = (
    "u'data/%s_MAIA_%s' % (expInfo['participant'], expInfo['date'])"
)
S['Full-screen window'].val = False
S['Screen'].val = 1
S['Units'].val = 'height'
S['Window size (pixels)'].val = '(1280, 720)'
S['Save wide csv file'].val = True
S['Save psydat file'].val = True
S['Show info dlg'].val = True
S['Show mouse'].val = False
S['Enable Escape'].val = True
S['color'].val = '$[-1,-1,-1]'
S['keyboardBackend'].val = 'PsychToolbox'
S['End Message'].val = '설문에 참여해 주셔서 감사합니다.'


def add_code(routine, name, **blocks):
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
    """code-only 루틴이 한 프레임 만에 끝나지 않도록 보이지 않는 앵커 추가."""
    tc = TextComponent(exp=exp, parentName=routine.name, name=name)
    tc.params['text'].val = ' '
    tc.params['startType'].val = 'time (s)'
    tc.params['startVal'].val = '0'
    tc.params['stopType'].val = 'duration (s)'
    tc.params['stopVal'].val = ''
    tc.params['opacity'].val = '0'
    tc.params['saveStartStop'].val = False
    routine.addComponent(tc)
    return tc


# ────────────────────────────────────────────────────────────────────────────
# Routine: Intro
# ────────────────────────────────────────────────────────────────────────────
intro = make_routine('MAIA_Intro')

BEFORE_EXP = r'''import os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
print('[maia] === Before Experiment ===')
from psychopy import event
'''

BEGIN_EXP = r'''print('[maia] === Begin Experiment ===')

# 공용 자극
prog_stim = visual.TextStim(win, name='prog_stim', text='', height=0.030,
                            color=(0.2, 0.2, 0.2), pos=(0, 0.43),
                            alignText='center')
item_stim = visual.TextStim(win, name='item_stim', text='', height=0.052,
                            color='white', pos=(0, 0.14), wrapWidth=1.5,
                            alignText='center')
scale_stim = visual.TextStim(win, name='scale_stim', text='', height=0.038,
                             color='white', pos=(0, -0.18), wrapWidth=1.6,
                             alignText='center')
msg_stim = visual.TextStim(win, name='msg_stim', text='', height=0.045,
                           color='white', pos=(0, 0), wrapWidth=1.5,
                           alignText='center')

# 척도 안내 텍스트 (0–5)
SCALE_TEXT = ('0  전혀 그렇지 않다      …      5  항상 그렇다\n\n'
              '0      1      2      3      4      5\n\n'
              '해당하는 숫자 키(0–5)를 누르세요')

# 하위척도 점수 누적 (역채점 반영 후)
_subscale_scores = {}
_resp_count = 0

thisExp.addData('age', expInfo.get('age', ''))
thisExp.addData('sex', expInfo.get('sex', ''))
'''

INTRO_FRAME = r'''msg_stim.text = ('신체 감각 자각 설문 (MAIA)\n\n'
                 '아래 문항들이 평소 자신에게 얼마나 해당하는지\n'
                 '0(전혀 그렇지 않다)부터 5(항상 그렇다)까지로 응답하세요.\n\n'
                 '정답은 없으며, 떠오르는 대로 솔직하게 답하시면 됩니다.\n\n'
                 '총 24문항 · 약 5–10분 소요\n\n'
                 '준비되면 스페이스바를 누르세요.')
msg_stim.draw()
_k = event.getKeys(keyList=['space', 'escape'])
if 'escape' in _k:
    core.quit()
if 'space' in _k:
    continueRoutine = False
'''

add_code(intro, 'code_maia_intro',
         **{'Before Experiment': BEFORE_EXP,
            'Begin Experiment': BEGIN_EXP,
            'Each Frame': INTRO_FRAME})

# ────────────────────────────────────────────────────────────────────────────
# Routine: Item  (loop body — 한 문항 제시 + 0–5 응답)
#   loop 변수: item_num, item_text, subscale, reverse  (maia_items.xlsx)
# ────────────────────────────────────────────────────────────────────────────
item = make_routine('MAIA_Item')

ITEM_BEGIN = r'''_resp = None
_item_onset = core.getTime()
event.clearEvents()
'''

ITEM_FRAME = r'''prog_stim.text = f'{maia_loop.thisN + 1} / {maia_loop.nTotal}'
item_stim.text = str(item_text)
scale_stim.text = SCALE_TEXT
prog_stim.draw()
item_stim.draw()
scale_stim.draw()
_k = event.getKeys(keyList=['0', '1', '2', '3', '4', '5', 'escape'])
if 'escape' in _k:
    core.quit()
if _k:
    _resp = int(_k[0])
    continueRoutine = False
'''

ITEM_END = r'''try:
    _rev = int(float(reverse))
except Exception:
    _rev = 0
_scored = (5 - _resp) if (_rev == 1 and _resp is not None) else _resp
thisExp.addData('item_num', item_num)
thisExp.addData('subscale', subscale)
thisExp.addData('reverse', _rev)
thisExp.addData('response_raw', _resp)
thisExp.addData('response_scored', _scored)
thisExp.addData('rt', round(core.getTime() - _item_onset, 4))
if _scored is not None:
    _subscale_scores.setdefault(str(subscale), []).append(_scored)
    _resp_count += 1
'''

add_code(item, 'code_maia_item',
         **{'Begin Routine': ITEM_BEGIN, 'Each Frame': ITEM_FRAME,
            'End Routine': ITEM_END})

# ────────────────────────────────────────────────────────────────────────────
# Routine: End  (하위척도 평균 계산 + 저장)
# ────────────────────────────────────────────────────────────────────────────
end = make_routine('MAIA_End')

END_BEGIN = r'''# 8개 하위척도 평균(역채점 반영) 계산
_SUBSCALE_ORDER = ['Noticing', 'Not-Distracting', 'Not-Worrying',
                   'Attention-Regulation', 'Emotional-Awareness',
                   'Self-Regulation', 'Body-Listening', 'Trusting']
_summary = {}
_all_vals = []
for _sub in _SUBSCALE_ORDER:
    _vals = _subscale_scores.get(_sub, [])
    if _vals:
        _m = sum(_vals) / len(_vals)
        _all_vals += _vals
    else:
        _m = float('nan')
    _summary[_sub] = _m
    thisExp.addData('MAIA_' + _sub.replace('-', '_'), round(_m, 4))
_overall = (sum(_all_vals) / len(_all_vals)) if _all_vals else float('nan')
thisExp.addData('MAIA_overall_mean', round(_overall, 4))
thisExp.addData('MAIA_n_answered', _resp_count)
print('[maia] subscale means:')
for _sub in _SUBSCALE_ORDER:
    print(f'   {_sub:22s} {_summary[_sub]:.3f}')
print(f'   {"OVERALL":22s} {_overall:.3f}  (n={_resp_count}/24)')

# 분석 편의용 별도 요약 CSV 저장
try:
    import csv as _csv
    _base = thisExp.dataFileName  # 확장자 없는 경로
    _sum_path = _base + '_subscales.csv'
    _d = os.path.dirname(_sum_path)
    if _d and not os.path.isdir(_d):
        os.makedirs(_d, exist_ok=True)
    with open(_sum_path, 'w', newline='', encoding='utf-8-sig') as _f:
        _w = _csv.writer(_f)
        _w.writerow(['participant', 'session', 'age', 'sex',
                     'subscale', 'mean_score', 'n_items'])
        _pid = expInfo.get('participant', '')
        _ses = expInfo.get('session', '')
        _age = expInfo.get('age', '')
        _sex = expInfo.get('sex', '')
        for _sub in _SUBSCALE_ORDER:
            _vals = _subscale_scores.get(_sub, [])
            _mean = (sum(_vals) / len(_vals)) if _vals else ''
            _w.writerow([_pid, _ses, _age, _sex, _sub,
                         (round(_mean, 4) if _vals else ''), len(_vals)])
        _w.writerow([_pid, _ses, _age, _sex, 'OVERALL',
                     (round(_overall, 4) if _all_vals else ''), _resp_count])
    print('[maia] 요약 저장:', _sum_path)
except Exception as _e:
    print('[maia] 요약 CSV 저장 실패:', repr(_e))
'''

END_FRAME = r'''msg_stim.text = ('설문이 끝났습니다.\n\n참여해 주셔서 감사합니다.\n\n'
                 '스페이스바를 누르면 종료됩니다.')
msg_stim.draw()
if 'space' in event.getKeys(keyList=['space']):
    continueRoutine = False
'''

add_code(end, 'code_maia_end',
         **{'Begin Routine': END_BEGIN, 'Each Frame': END_FRAME})

# ────────────────────────────────────────────────────────────────────────────
# 앵커 (code-only 루틴 유지)
# ────────────────────────────────────────────────────────────────────────────
for _rt in (intro, item, end):
    add_anchor(_rt)

# ────────────────────────────────────────────────────────────────────────────
# Flow: MAIA_Intro → [loop maia_loop: MAIA_Item] → MAIA_End
# ────────────────────────────────────────────────────────────────────────────
exp.flow.addRoutine(intro, 0)
exp.flow.addRoutine(item, 1)
exp.flow.addRoutine(end, 2)

# 문항 조건 파일 로딩(빌드 시 nTotal 계산용)
try:
    from psychopy import data as _pdata
    _conds = _pdata.importConditions(os.path.join(HERE, COND_FILE))
    print(f'[maia] loaded {len(_conds)} items from {COND_FILE}')
except Exception as _e:
    print(f'[maia] importConditions failed: {_e!r}')
    _conds = []

maia_loop = TrialHandler(exp, name='maia_loop', loopType='sequential',
                         nReps=1, conditions=_conds, conditionsFile=COND_FILE)
# wrap flow[1] = MAIA_Item  → initiator@1, terminator@2
exp.flow.addLoop(maia_loop, 1, 2)

exp.saveToXML(OUT)
print('SAVED', OUT)

# 즉시 컴파일 검증 → _lastrun.py
script = exp.writeScript(expPath=OUT)
lastrun = os.path.join(HERE, 'MAIA_Survey_lastrun.py')
with open(lastrun, 'w', encoding='utf-8') as f:
    f.write(script)
print('WROTE', lastrun, len(script), 'chars')

print('FLOW:')
for itm in exp.flow:
    nm = getattr(itm, 'name', None) or type(itm).__name__
    print('  ', type(itm).__name__, nm)
