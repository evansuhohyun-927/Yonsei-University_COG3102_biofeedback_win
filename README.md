# fNIRS HeartFeedback × PPG 바이오피드백 통합 시스템

연구실 자체 제작 PPG 하드웨어 기반 바이오피드백 프로그램과 PsychoPy 실험을
**단일 진입점**(PsychoPy ▶)으로 통합한 시스템.

- PsychoPy 창에서 참가자가 **네온 ECG 라인 + 박동 하트**를 직접 봄 (가짜 피드백 패러다임)
- ExperimenterWindow에서 실험자가 **PPG 연결·calibration·실험 시작 버튼** 제어
- LSL로 두 프로그램 동기 (fNIRS OBELAB과 외부 동기도 함께)

---

## 폴더 구조

```
Yonsei-University_COG3102_biofeedback_win-main/
├── biofeedback/                          # PyQt6 바이오피드백 (실험자 GUI)
│   ├── main.py                           # 진입점 (PsychoPy가 subprocess로 자동 실행)
│   ├── core/
│   │   ├── bus.py                        # EventBus (스레드 안전 pub-sub)
│   │   ├── manipulator.py                # Fake feedback 상태머신 (RAMP_UP/HOLD/RAMP_DOWN)
│   │   ├── beat_scheduler.py             # output BPM에 맞춰 beat 이벤트 발행
│   │   ├── bpm_smoother.py               # raw → 평활 BPM
│   │   ├── bpm_lsl_outlet.py             # BPM_output (조작된 BPM, type=BPM, 20Hz)
│   │   ├── lsl_outlets.py                # PPG_raw, BPM_processed, Calibration_Result, BiofeedbackControl
│   │   ├── calibration_runner.py         # 60초 baseline BPM 측정
│   │   ├── lsl_controller.py             # PsychoPy 마커 수신 → 자동 제어
│   │   └── source_manager.py
│   ├── hr_sources/
│   │   ├── ppg_serial.py                 # 자체 제작 PPG (시리얼 ASCII)
│   │   ├── osc_source.py
│   │   └── mock.py                       # 70 BPM sine (테스트용)
│   ├── feedback/
│   │   ├── participant_window.py         # (선택적) PyQt6 ECG widget — 이제 사용 안 함
│   │   └── audio.py                      # 박동 thump 사운드
│   └── gui/
│       └── experimenter.py               # ExperimenterWindow + "실험 시작" 버튼 + 카운트다운
├── psychopy_experiment/
│   ├── fNIRS_HeartFeedback.psyexp        # PsychoPy 실험 (수정본 — Builder로 열기)
│   ├── ecg_renderer.py                   # PsychoPy 창에 ECG/하트 직접 그리는 모듈
│   └── biofeedback_inline.py             # (선택 사용) 단일 프로세스 통합용 — 현재 미사용
├── conditions/
│   └── maia_items.xlsx                   # MAIA 문항 (사용자 별도 준비)
├── data/                                 # PsychoPy 실험 데이터 저장 위치 (자동 생성)
├── biofeedback_console.log               # 자동 생성 — 바이오피드백 stdout 로그
├── README.md                             # (이 파일)
├── CHANGES.md                            # 이전 버전 대비 변경 사항
├── TROUBLESHOOTING.md                    # 알려진 이슈 + 해결책
├── UPDATE_REPORT.md                      # 종합 업데이트 보고서 (팀 공유용)
├── requirements.txt
└── run_experiment.bat                    # Builder UI 없이 .psyexp 직접 실행 (백업용)
```

---

## 실행 절차 (간단)

### 사전 준비 (1회)

1. PsychoPy 2026.x 설치 (기본 경로: `C:\Program Files\PsychoPy\`)
2. 바이오피드백 .venv 생성 + 의존성 설치:
   ```powershell
   cd C:\...\Yonsei-University_COG3102_biofeedback_win-main
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install pylsl
   ```
3. `conditions/maia_items.xlsx` 준비 (없으면 MAIA 루프 빈 채로 진행)
4. fNIRS(OBELAB) 소프트웨어 켜고 LSL 송신 활성화

### 실험 진행 (매 세션)

1. **PsychoPy Builder 먼저 실행** → `psychopy_experiment/fNIRS_HeartFeedback.psyexp` 열기 → ▶
2. 참가자 ID 다이얼로그 입력 → OK
3. PsychoPy 검정 창("실험 준비중...") + ExperimenterWindow 동시에 뜸
4. ExperimenterWindow에서:
   - **PPG Connect** → 신호 확인
   - 녹색 **"실험 시작 →"** 버튼 클릭
5. 60초 baseline calibration 자동 진행 (버튼 카운트다운 표시)
6. Calibration 완료 시 ExperimenterWindow가 우측 상단으로 축소되고 PsychoPy 진행
7. 이후 자동: Daily_Screening → Instruction → TestRun → Stabilization → Baseline → block_loop ×3 → Post-exp → Debrief

---

## LSL 스트림

| 이름 | type | 방향 | 형식 | srate |
|---|---|---|---|---|
| `PsychoPyMarkers` | Markers | PsychoPy → biofeedback (& fNIRS) | string | irregular |
| `PPG_raw` | PPG | biofeedback → 후분석 | float32 | 200 Hz |
| `BPM_processed` | BPM | biofeedback → PsychoPy | float32 | 10 Hz |
| `BPM_output` | BPM | biofeedback → (모니터링) | float32 | 20 Hz |
| `Calibration_Result` | Calibration | biofeedback → PsychoPy | float32 | 1회 |
| `BiofeedbackControl` | Markers | biofeedback → PsychoPy | string | 1회 (실험 시작) |

---

## 마커 어휘 (`PsychoPyMarkers`)

| 마커 | 송신 시점 | 수신 동작 |
|---|---|---|
| `baseline` | Baseline routine 시작 | 오디오 ON |
| `accel`/`decel`/`neutral` | Phase1_Sync 시작 | 다음 ramp의 block_type 저장 |
| `P1_sync` | Phase1_Sync | (대기) |
| `P2_ramp` | Phase2_Mini_ 각 epoch | (lsl_controller가 자동 manipulator 시작) |
| `P3_plateau` | Phase3_Plateau | (Manipulator 자동 HOLD) |
| `P4_recovery` | Phase4_Recovery | (Manipulator 자동 RAMP_DOWN) |
| `experiment_end` | Debrief 종료 | 종료 신호 |

`BiofeedbackControl` 송신:
| 마커 | 송신 시점 |
|---|---|
| `experiment_start` | 실험자가 "실험 시작" 버튼 클릭 + calibration 완료 |

---

## 실험 흐름

```
Welcome (대기) ── 실험자 "실험 시작" 클릭 ──> 60s calibration
                                                  │
                                                  ▼
Daily_Screening → Experiment_Instruction
  ↓
TestRun (Instruction → Phase1 15s + ECG → Likert → End)
  ↓
Stabilization_Rest_ (30s + ECG)
  ↓
Baseline (60s + ECG)
  ↓
block_loop ×3 (counterbalanced accel/decel/neutral):
   Phase1_Sync (60s, base BPM 유지) + ECG
   ramp_loop (Phase2_Mini_ ×9 = 180s, 0%→25%) + ECG
   Likert_InBlock_
   Phase3_Plateau (45s, 25% 유지) + ECG
   Likert_InBlock_
   Phase4_Recovery (60s, baseline 복귀) + ECG
   Rest_Between_Blocks (90s, 마지막 블록 뒤 스킵)
  ↓
PostExp_Likert_BPM → PostExp_Likert_Trust → MAIA_Survey_ → Debrief
```

---

## 참고 문서

- [CHANGES.md](CHANGES.md) — 이전 버전 대비 무엇이 달라졌는지
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 알려진 이슈와 해결책
- [UPDATE_REPORT.md](UPDATE_REPORT.md) — 통합 업데이트 종합 보고서 (팀 공유용)
- [HANDOFF.md](HANDOFF.md) — 원본 바이오피드백 프로그램 핸드오프 문서

---

## 실행 백업

PsychoPy Builder UI가 작동 안 할 때:

```cmd
run_experiment.bat
```

`.psyexp`를 자동 컴파일한 뒤 `.py`로 직접 실행합니다.
