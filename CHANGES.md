# 변경 사항 (이전 standalone 바이오피드백 버전 대비)

원본은 PyQt6 단독 실행되는 바이오피드백 프로그램(`biofeedback.main`)이었습니다.
이번 업데이트로 **PsychoPy 실험과 LSL로 통합**되어 단일 진입점(PsychoPy ▶)으로 운영됩니다.

---

## 신규 파일

| 파일 | 용도 |
|---|---|
| `psychopy_experiment/fNIRS_HeartFeedback.psyexp` | PsychoPy 실험 (Welcome → block_loop → Debrief) |
| `psychopy_experiment/ecg_renderer.py` | PsychoPy 창에 네온 ECG 라인 + 박동 하트 직접 그리는 모듈 |
| `psychopy_experiment/biofeedback_inline.py` | (선택) 단일 프로세스 통합 API — 현재 미사용 |
| `biofeedback/core/lsl_outlets.py` | `PPG_raw`, `BPM_processed`, `Calibration_Result`, `BiofeedbackControl` outlet들 |
| `biofeedback/core/calibration_runner.py` | 60초 baseline BPM 측정 (CalibrationRunner) |
| `biofeedback/core/lsl_controller.py` | PsychoPy 마커 수신 → 바이오피드백 자동 제어 |
| `run_experiment.bat` | Builder UI 우회 — .psyexp 직접 컴파일 + 실행 |
| `README.md` | 통합 시스템 사용 안내 |
| `CHANGES.md` | (이 파일) |
| `TROUBLESHOOTING.md` | 알려진 이슈 |
| `UPDATE_REPORT.md` | 팀 공유용 종합 보고서 |

## 수정 파일

| 파일 | 변경 요약 |
|---|---|
| `biofeedback/main.py` | 신규 outlets/runner wire-up 추가 |
| `biofeedback/core/bpm_lsl_outlet.py` | stream name `BiofeedbackBPM` → `BPM_output` (구분 명확화) |
| `biofeedback/core/bpm_smoother.py` | (변경 없음) |
| `biofeedback/hr_sources/ppg_serial.py` | raw 샘플을 EventBus `ppg_sample`로 publish 추가 |
| `biofeedback/feedback/participant_window.py` | `LikertOverlay` 추가, 키 forwarding 처리 (현재 PsychoPy 안에서 ECG 그려서 사용 안 함) |
| `biofeedback/gui/experimenter.py` | **녹색 "실험 시작" 버튼**, calibration 카운트다운 타이머, 우상단 축소 이동, calibration_complete 이벤트 처리 |
| `.gitignore` | PsychoPy 산출물 추가 (lastrun.py, console log 등) |

---

## 아키텍처 변경

### Before (원본)
```
[실험자] python -m biofeedback.main
                ↓
        ExperimenterWindow + ParticipantWindow (PyQt6)
                ↓
        시각자극, 오디오, 데이터 저장 모두 자체 처리
```

### After (이번 업데이트)
```
[실험자] PsychoPy ▶ → 참가자 ID 입력
                ↓
        PsychoPy 검정 창 ("실험 준비중...")
                ↓ (Before Experiment: subprocess.Popen)
        ExperimenterWindow 자동 실행 (PyQt6, 콘솔 숨김)
                ↓
        실험자: PPG Connect → "실험 시작" 클릭
                ↓ (60s calibration → LSL marker 'experiment_start')
        PsychoPy: Daily_Screening → ... → block_loop → Debrief
                ↓ (Phase routines: ECG/하트 직접 그림)
        PsychoPy 창에서 네온 ECG + 박동 하트 표시
        Likert/Survey/MAIA → 데이터 저장 (data/*.csv)
```

---

## LSL 통합

원본은 LSL 없음. 추가된 스트림 5개:

| 스트림 | 방향 | 용도 |
|---|---|---|
| `PsychoPyMarkers` | PsychoPy → biofeedback (& fNIRS) | phase / block_type / experiment_end 마커 |
| `BiofeedbackControl` | biofeedback → PsychoPy | "실험 시작" 버튼 누름 신호 |
| `Calibration_Result` | biofeedback → PsychoPy | 60s baseline BPM 1회 송신 |
| `BPM_processed` | biofeedback → PsychoPy | 평활된 실측 BPM (로깅용) |
| `BPM_output` | biofeedback → 외부 모니터링 | 조작된 BPM (manipulator 출력) |
| `PPG_raw` | biofeedback → 후분석 | raw PPG 200Hz |

---

## 주요 기능 추가

### 1. 단일 진입점
- 이전: 바이오피드백과 PsychoPy 각각 실행
- 현재: PsychoPy ▶ 하나로 두 프로그램 동시 시작

### 2. PsychoPy 안에서 네온 ECG 표시
- ECG 라인 (3-layer halo + glow + core)
- 박동 하트 (파라메트릭 곡선, 1.45× pop)
- 시간 기반 직접 계산 (routine 전환에 강함, 매끄러운 스크롤)

### 3. 카운트다운 calibration
- "실험 시작" 버튼이 `Calibrating... (60s)` → `(59s)` → ... 카운트다운
- 완료 시 ExperimenterWindow 우측 상단으로 축소

### 4. fNIRS 외부 동기
- `PsychoPyMarkers` LSL을 fNIRS (OBELAB)도 함께 수신해서 phase 동기 가능

### 5. 데이터 컬럼 확장
- `actual_bpm`, `baseline_bpm`, `current_bpm`, `mismatch_pct`, `block_type` 등

---

## 의존성 변경

추가:
- `pylsl >= 1.18` (LSL 통신)

PsychoPy 환경에 이미 있는 패키지:
- `pyserial`, `numpy`, `scipy`, `sounddevice` (확인됨)

---

## 알려진 변경된 동작

| 항목 | 이전 | 현재 |
|---|---|---|
| 참가자 시각자극 | biofeedback PyQt 창 | **PsychoPy 창에 직접** (네온 ECG + 하트) |
| 실험자 진행 제어 | 바이오피드백 GUI 버튼 | **PsychoPy ▶ + ExperimenterWindow "실험 시작" 버튼** |
| Calibration | 수동 (`Auto-Calibrate`) | **"실험 시작" 클릭 → 자동 60s baseline 측정** |
| 데이터 저장 | biofeedback CSV (epoch 기반) | **PsychoPy CSV (routine 단위) + biofeedback raw PPG 별도** |
| 외부 동기 | 없음 | **LSL Markers (fNIRS와 통합)** |

---

## 다음 작업 (TODO)

- [ ] PPG 시리얼 데이터 포맷 확정 — 자체 PPG가 라인당 단일 float ASCII가 아니면 `PPGSerialSource.parse_line()` 오버라이드 필요
- [ ] block_loop counterbalancing — 첫 블록이 `neutral`이면 시각자극 변화 없음을 실험자가 인지하도록 안내
- [ ] ECG 라인 jitter 추가 검증 (현재 60fps 보장, jitter 거의 없음)
- [ ] Likert_InBlock_에서 ECG가 잠시 사라지고 텍스트 표시되는 동작 검증
