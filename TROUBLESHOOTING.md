# 트러블슈팅

PsychoPy ↔ biofeedback 통합 작업 중 마주친 이슈들과 해결 방법.

---

## 1. `expInfo` NameError on PsychoPy 실행

### 증상
```
NameError: name 'expInfo' is not defined
```
PsychoPy 실행 직후 (참가자 ID 입력 후) 즉시 종료.

### 원인
PsychoPy Builder의 **Before Experiment** 코드는 `expInfo` 다이얼로그 표시 **이전**에 실행됨.
`expInfo.get(...)` 호출하면 NameError 발생.

### 해결
`expInfo` 사용하는 코드는 **Begin Experiment**로 이동 (다이얼로그 후 실행).
`Begin Experiment`는 win 생성 후 첫 routine 시작 전에 실행됨.

---

## 2. PsychoPy 창이 "Not Responding" / freeze

### 증상
참가자 ID 입력 후 PsychoPy 창이 응답 없음. 10초 이상 멈춤.

### 원인
Before Experiment에서 `resolve_byprop(..., timeout=5.0)` 같은 LSL 검색을 5번 반복 = 최대 60초 블로킹.
Windows가 이 시간 동안 PsychoPy를 "Not Responding"으로 표시.

### 해결
1. Before Experiment는 비차단(non-blocking) 처리만 수행
2. LSL inlets는 `None`으로 두고 **Welcome Each Frame**에서 **lazy resolution** (0.5초마다 timeout=0.0으로 재시도)
3. 바이오피드백이 늦게 부팅돼도 자동 연결

---

## 3. 바이오피드백 콘솔창이 PsychoPy를 가림

### 증상
PsychoPy 창이 안 보임. 검은 콘솔창만 보임.

### 원인
`subprocess.Popen(..., creationflags=CREATE_NEW_CONSOLE)` = 0x00000010 → 별도 콘솔 창 생성.

### 해결
`creationflags=CREATE_NO_WINDOW` = 0x08000000 로 변경.
stdout/stderr는 `biofeedback_console.log` 파일로 리다이렉트 (디버깅용 보존).

```python
subprocess.Popen(
    [python_exe, '-m', 'biofeedback.main'],
    cwd=project_dir,
    stdout=open(log_path, 'w', encoding='utf-8'),
    stderr=subprocess.STDOUT,
    creationflags=0x08000000,  # CREATE_NO_WINDOW
)
```

---

## 4. `BiofeedbackControl` LSL 스트림 못 찾음 → 영영 대기

### 증상
바이오피드백은 실행되는데, PsychoPy가 `experiment_start` 마커를 영영 못 받음.

### 원인
**바이오피드백 .venv에 `pylsl`이 설치되지 않음.** 모든 LSL outlet 생성 실패 (console log에 `pylsl not installed` 경고).

### 해결
```powershell
.venv\Scripts\python.exe -m pip install pylsl
```

PsychoPy 환경에는 이미 `pylsl 1.18.1` 있음. 둘 다 같은 버전이어야 호환.

---

## 5. `UnicodeDecodeError 'utf-8' 0xc0` in PsychoPy Runner

### 증상
```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0 in position 186
File "...psychopy/app/jobs.py", line 135, in run
```

### 원인
Windows 한국어 콘솔의 기본 encoding은 cp949. PsychoPy의 print 출력 (한국어 포함)이 cp949로 인코딩되어 Runner의 utf-8 디코딩과 충돌.

### 해결
Before Experiment 시작에 stdout/stderr를 utf-8로 강제:
```python
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
```

---

## 6. `wxAssertionError: how did we lose focus?`

### 증상
PsychoPy 실행 중 wx assertion 에러 메시지.

### 원인
PsychoPy wx GUI의 알려진 경고. 창 포커스 전환 시 발생.

### 해결
무해. 무시 가능. 실험 동작에 영향 없음.

---

## 7. PsychoPy Builder 시작 시 .psyexp 직접 열면 안 됨

### 증상
.psyexp 더블클릭 → PsychoPy Builder UI 안 뜨거나 Run 버튼 보이지 않음.

### 해결
**PsychoPy Builder를 먼저 실행 → File > Open으로 .psyexp 열기.** Builder 정상 동작.

또는 백업: `run_experiment.bat` 더블클릭 → Builder UI 없이 직접 실행.

---

## 8. PsychoPy ECG 안 보임 ("ECG=None init_err=None")

### 증상
화면 하단 status_text에 "ECG=None init_err=None" 표시.

### 원인
PsychoPy 생성 코드는 모든 변수를 `def run()` 함수 안에 둠. `ecg_renderer`는 함수 **로컬**.
`if 'ecg_renderer' in globals()` 체크는 모듈 globals만 보므로 **항상 False**.

### 해결
`globals()` 체크 제거하고 직접 사용:
```python
if ecg_renderer is not None:
    ecg_renderer.update(t, bpm)
    ecg_renderer.draw()
```

---

## 9. ECG 라인이 routine 전환 시 튕김

### 증상
TestRun_Phase1 → Stabilization → Baseline → Phase1_Sync 전환 시 ECG가 갑자기 점프.

### 원인 1: routine별 `t` 리셋
PsychoPy의 `t`는 각 routine 시작 시 0으로 리셋. ecg_renderer가 시간이 거꾸로 가는 것으로 인식.

### 원인 2: bpm 변화 시 과거 샘플 위치 점프
`cycle_pos = sample_t % interval` 공식은 interval(=60/bpm)이 바뀌면 과거 sample의 cycle_pos도 모두 변경 → 화면 전체 점프.

### 해결
ecg_renderer 재설계:
1. 내부에서 **`core.getTime()` 기반 절대 시각** 사용 (routine 무관)
2. **beat 발생 시각을 리스트로 누적**. 과거 beats는 고정. bpm 변하면 미래 beats만 새 interval로 추가
3. 장기 갭(>2s, routine 전환) 시 누락분만 EXTEND (이전 beats 보존)

```python
# 첫 호출: 과거 5초 backfill (화면 즉시 가득)
if not s['beats']:
    t_bf = now
    while t_bf > now - DISPLAY_WINDOW_S:
        s['beats'].append(t_bf)
        t_bf -= interval

# 정상 + 갭 catch-up
elif (now - s['last_beat_t']) >= interval:
    next_beat = s['last_beat_t'] + interval
    while next_beat <= now:
        s['beats'].append(next_beat)
        s['last_beat_t'] = next_beat
        next_beat += interval
```

---

## 10. ECG 라인 R파(spike)가 들쭉날쭉

### 증상
ECG의 R wave(가장 높은 spike)가 사이클마다 다른 높이로 보임.

### 원인
**Aliasing.** R wave Gaussian 폭 = 12ms. 250 vertices를 5초 window에 펼치면 샘플링 50Hz (20ms/sample). R wave를 가끔 놓침.

### 해결
N_VERTICES 500 (100Hz)으로 증가 + numpy 벡터화로 성능 부담 해결.

---

## 11. PsychoPy 창이 닫혀버림

### 증상
실험 진행 중 PsychoPy 창이 갑자기 닫힘.

### 원인 후보
- ESC 키 입력 (PsychoPy 기본: 실험 중단)
- 예외 발생 → run() 함수 중단 → win 자동 close
- 사용자가 X 버튼 클릭

### 해결
1. Each Frame 코드를 `try/except`로 보호하여 예외로 인한 종료 방지
2. status_text에 진단 정보 표시 → 어디서 문제 발생하는지 즉시 확인
3. ESC 키 비활성화 옵션: `.psyexp` Settings → Enable Escape = False (단, 실험자 abort 기능 잃음)

---

## 12. 첫 Phase에서 BPM 변화 없음 (70 유지)

### 증상
"실험 시작 후 첫 phase에서 ramp up 없이 70 BPM만 유지됨"

### 원인 — **정상 동작**
1. **Phase1_Sync는 의도된 sync 단계**: 60초간 baseline BPM (조작 없음)
2. **Phase2_Mini_부터 ramping**: 9 epoch × 20s = 180s 동안 0% → 25% mismatch
3. **block_type = neutral**이면 Phase2~3도 조작 없음 (대조군)

### 확인 방법
status_text에 `block=accel/decel/neutral` 표시됨.
- accel/decel → Phase2부터 BPM 변화 시작
- neutral → 전체 블록 동안 baseline 유지 (정상)

라틴스퀘어 카운터밸런싱이라 참가자 번호에 따라 첫 블록이 다름.

---

## 13. ECG가 본격 실험에서 안 보임

### 증상
TestRun에서는 보이는데 실험 시작 후 안 보임.

### 원인
TestRun_End → **Stabilization_Rest_(30s) + Baseline(60s)** 동안 ECG 코드 없음 → 90초간 빈 검정 화면. 사용자가 이 시점을 "실험 시작 직후"로 인식.

### 해결
Stabilization_Rest_와 Baseline routine의 Each Frame에도 `ecg_renderer.update + draw` 추가.

---

## 14. 단일 모니터에서 두 창 동시 표시

### 증상
ExperimenterWindow가 PsychoPy를 가림. PsychoPy 창 안 보임.

### 해결
"실험 시작" 클릭 시 ExperimenterWindow를 자동으로:
- 480×360으로 축소
- 화면 우측 상단으로 이동

PsychoPy 창이 화면 중앙에 노출되어 참가자가 ECG 확인 가능.
실험자는 작은 ExperimenterWindow로 BPM 모니터링 가능.

---

## 15. 폴더 구조 / Python 환경 분리

### 주의
- **PsychoPy 환경**: `C:\Program Files\PsychoPy\python.exe` (PsychoPy 2026.1.3 번들)
  - pylsl, numpy, scipy, pyserial, sounddevice 모두 있음
- **바이오피드백 .venv**: 프로젝트 폴더의 `.venv/Scripts/python.exe`
  - 위 패키지들 + PyQt6 6.7.x

PsychoPy는 자체 Python으로 `psychopy_experiment/ecg_renderer.py` import.
바이오피드백 subprocess는 .venv Python으로 `biofeedback.main` 실행.
두 환경에 모두 `pylsl` 있어야 LSL 통신 가능.
