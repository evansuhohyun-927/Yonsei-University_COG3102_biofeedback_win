# fNIRS HeartFeedback × PPG 통합 업데이트 종합 보고서

**작성일**: 2026-05-24
**작업자**: 연세대 COG3102 / 연구실
**대상**: 팀원 공유용 (실험자 + 분석자)

---

## 1. 개요

연세대 COG3102 연구실의 자체 제작 PPG 바이오피드백 프로그램과 PsychoPy 실험 파일을
**하나의 통합 시스템**으로 연결했습니다.

### 통합 목적

- 실험자가 두 프로그램을 따로 실행하는 번거로움 해소
- 가짜 피드백 (manipulated BPM) 패러다임을 PsychoPy 안에서 시각화
- fNIRS(OBELAB)와 LSL 마커로 외부 동기 가능

### 주요 결과

- **단일 진입점**: PsychoPy ▶ 한 번이면 바이오피드백 자동 실행 + 실험 시작
- **참가자 화면**: PsychoPy 검정 창에 빨간 네온 ECG 라인 + 박동 하트
- **실험자 제어**: ExperimenterWindow에 큰 "실험 시작" 버튼 + 60s calibration 카운트다운
- **데이터**: PsychoPy CSV (routine 단위) + 바이오피드백 raw PPG (시계열) + LSL 마커 stream

---

## 2. 시스템 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│ 실험자 컴퓨터 (단일)                                              │
│                                                                  │
│  ┌────────────────────────┐   subprocess.Popen                    │
│  │ PsychoPy (참가자 화면)  │ ──────────────────┐                   │
│  │ - 검정 배경            │                   ▼                   │
│  │ - 네온 ECG + 박동 하트  │   ┌────────────────────────────────┐  │
│  │ - 텍스트/Likert/MAIA   │   │ biofeedback (실험자 GUI)        │  │
│  │ - 데이터 CSV 저장      │   │ - PPG Connect/Auto-Calibrate    │  │
│  └───────────┬────────────┘   │ - "실험 시작" 버튼 (60s 카운트다운)│  │
│              │                │ - Real/Output BPM 그래프         │  │
│              │ LSL Markers    │ - PPG 신호 라이브뷰              │  │
│              │  outlet/inlet  └──────────────┬─────────────────┘  │
│              │                               │                    │
│              ▼                               ▼                    │
│  ┌──────────────────────────────────────────────────┐             │
│  │ LSL 스트림 5종                                     │             │
│  │ - PsychoPyMarkers   (PsychoPy → biofeedback)      │             │
│  │ - BiofeedbackControl (biofeedback → PsychoPy)     │             │
│  │ - Calibration_Result (biofeedback → PsychoPy)     │             │
│  │ - BPM_processed     (biofeedback → PsychoPy)      │             │
│  │ - BPM_output        (biofeedback → 외부 모니터링)  │             │
│  │ - PPG_raw           (biofeedback → 후분석)         │             │
│  └─────────────────────┬────────────────────────────┘             │
└────────────────────────┼──────────────────────────────────────────┘
                         │
                         ▼
              ┌────────────────────────┐
              │ fNIRS (OBELAB NIRSIT)   │
              │ - PsychoPyMarkers 수신  │
              │ - phase별 데이터 동기   │
              └────────────────────────┘
```

---

## 3. 실험 흐름 상세

| 단계 | 시간 | 내용 | 시각자극 |
|---|---|---|---|
| Welcome | 변동 | 실험자가 "실험 시작" 클릭 대기 | 없음 ("실험 준비중...") |
| (calibration) | 60s | 바이오피드백에서 baseline BPM 측정 | ExperimenterWindow 카운트다운 |
| Daily_Screening | 변동 | 컨디션 확인 (Y/N) | 텍스트 |
| Experiment_Instruction | 변동 | 실험 안내 + 카운터밸런싱 결정 | 텍스트 |
| TestRun_Instruction_ | 변동 | 연습 안내 | 텍스트 |
| **TestRun_Phase1** | 15s | 연습 sync | **ECG + 하트** |
| TestRun_Likert | 변동 | 연습 Likert | 텍스트 |
| TestRun_End | 변동 | 연습 종료 | 텍스트 |
| **Stabilization_Rest_** | 30s | 안정 휴식 | **ECG + 하트** + 카운트다운 |
| **Baseline** | 60s | baseline 측정 | **ECG + 하트** |
| **block_loop ×3** | ~485s/블록 | accel/decel/neutral 순서 | |
| ├ Phase1_Sync | 60s | base BPM 유지 (조작 없음) | **ECG + 하트** |
| ├ ramp_loop (Phase2_Mini_ ×9) | 180s | mismatch 0% → 25% 점진 | **ECG + 하트 (점진 변화)** |
| ├ Likert_InBlock_ | 변동 | "심박 일치/속도감" 자기보고 | 텍스트 (ECG 잠시 숨김) |
| ├ Phase3_Plateau | 45s | 25% 유지 | **ECG + 하트** |
| ├ Likert_InBlock_ | 변동 | 자기보고 | 텍스트 |
| ├ Phase4_Recovery | 60s | base 복귀 | **ECG + 하트** |
| └ Rest_Between_Blocks | 90s | 블록 간 휴식 (마지막 후 스킵) | 텍스트 |
| PostExp_Likert_BPM | 변동 | 사후 BPM Likert | 텍스트 |
| PostExp_Likert_Trust | 변동 | 사후 신뢰 Likert | 텍스트 |
| MAIA_Survey_ | 변동 | MAIA 문항 루프 | 텍스트 |
| Debrief | 변동 | 디브리핑 | 텍스트 |

**총 소요**: 약 30–40분 (calibration + 3 blocks + post-exp + MAIA 포함)

---

## 4. 데이터 출력

### PsychoPy CSV (`data/<참가자>_fNIRS_HeartFeedback_<날짜>.csv`)

주요 컬럼:
- `participant`, `session`, `expName`, `date`
- `assigned_order` (라틴스퀘어 순서)
- `block_idx` (0/1/2), `block_type` (accel/decel/neutral), `direction`
- `phase` (baseline / P1_sync / P2_ramp / P3_plateau / P4_recovery)
- `phase_onset` (PsychoPy core.getTime())
- `epoch_num` (Phase2 내 1~9)
- `mismatch_pct` (0 ~ 25)
- `current_bpm` (조작된 표시 BPM)
- `actual_bpm` (실측 BPM, 1초당 1회)
- `baseline_bpm`
- Likert 응답: `likert_bpm_inblock`, `likert_phase`, `likert_time`, `bpm_likert`, `trust_likert`
- MAIA: `maia_response` + `maia_item` (1행씩)

### 바이오피드백 출력

- **`biofeedback_console.log`** — 자동 생성. 디버깅용 stdout/stderr 통합 로그
- **(향후 추가 예정)** `biofeedback/data/<...>.csv` — 30s epoch별 real/output BPM, manipulator 상태 등

### LSL 동기 데이터 (OBELAB이 수신)

- `PsychoPyMarkers` 스트림 자체가 fNIRS 분석에 phase 정렬 기준으로 활용됨

---

## 5. 가짜 피드백 (manipulated BPM) 패러다임

```
실측 BPM (PPG에서) ──> BPMSmoother ──> bpm_real_smooth
                                            ↓
                                      Manipulator
                                            ↓ (block_type에 따라)
                                      bpm_output (조작됨)
                                            ↓
                                      BeatScheduler → "beat" 이벤트
                                            ↓
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                  PsychoPy ECG 시각자극        biofeedback 오디오 thump
```

### 조작 규칙

| block_type | Phase2 | Phase3 | Phase4 |
|---|---|---|---|
| `accel` | base × (1 + 0~25%) | base × 1.25 | base × 1.0 |
| `decel` | base × (1 − 0~25%) | base × 0.75 | base × 1.0 |
| `neutral` | base | base | base |

**중요**: 시각자극(ECG, 하트)에 표시되는 BPM은 **조작된 값**.
실측 BPM은 `actual_bpm` 컬럼에 별도 기록 (분석용).

---

## 6. 트러블슈팅 요약 (자세한 내용은 [TROUBLESHOOTING.md](TROUBLESHOOTING.md))

### 자주 발생할 수 있는 이슈

| 증상 | 원인 | 해결 |
|---|---|---|
| `NameError: expInfo not defined` | Before Experiment에서 expInfo 접근 | Begin Experiment로 이동 |
| PsychoPy "Not Responding" | LSL resolve가 블로킹 | lazy resolve로 변경 |
| 검은 콘솔창 가림 | `CREATE_NEW_CONSOLE` | `CREATE_NO_WINDOW` + log file |
| "ECG=None" 표시 | `globals()` 체크 (로컬 변수 못 봄) | 직접 `if ecg_renderer is not None` |
| ECG 라인 튕김 | routine별 `t` 리셋 + bpm 변화 시 과거 위치 점프 | 절대 시각(`core.getTime`) + beat 리스트 누적 |
| Calibration 60초 막힘 | pylsl 미설치 | `pip install pylsl` |
| ECG 안 보임 (Stabilization/Baseline) | 해당 routine에 ECG 코드 없었음 | 추가 |
| 첫 phase에서 70 BPM만 유지 | **정상** (Phase1_Sync는 sync phase) | block_type=neutral일 수도 있음 — 라틴스퀘어 확인 |

### 실험자가 알아야 할 동작

1. **PsychoPy Builder를 먼저 실행** → File > Open → `.psyexp` 열기 (더블클릭 X)
2. 참가자 ID 입력 → OK → 두 창 동시에 뜸
3. ExperimenterWindow에서 PPG 연결 + "실험 시작" 클릭 → 60s 자동 calibration
4. ExperimenterWindow가 우측 상단으로 축소되며 PsychoPy 진행
5. 실험 중 ExperimenterWindow에서 BPM 모니터링 가능 (작은 창)
6. ESC 키 = 실험 중단 (필요 시)

### 분석자가 알아야 할 동작

1. **시각자극 BPM = 조작된 값** (`current_bpm` 컬럼)
2. **실측 BPM = 분석용** (`actual_bpm` 컬럼, 1Hz 샘플링)
3. **mismatch_pct = 조작 강도**
4. **block_type** = 그 블록의 조건 (accel/decel/neutral)
5. **assigned_order** = 카운터밸런싱 순서 (참가자 번호 % 6 결정)
6. fNIRS 데이터와 동기는 LSL `PsychoPyMarkers` 스트림 timestamp 활용

---

## 7. 알려진 제한사항 / TODO

### 단기 (다음 세션 전에 해결 권장)

- [ ] **PPG 시리얼 데이터 포맷 확정**: 현재 `parse_line()`은 라인당 단일 float ASCII 가정. 자체 PPG가 CSV/바이너리 포맷이면 `biofeedback/hr_sources/ppg_serial.py:parse_line()` 오버라이드 필요. 연구실에서 PuTTY 등으로 시리얼 한 줄 샘플 확인 → 형식 알려주면 즉시 대응 가능.
- [ ] **첫 실제 참가자 데이터 수집 전 dry run**: mock 모드로 전체 흐름 1회 검증 (~30분)
- [ ] **MAIA xlsx 준비**: `conditions/maia_items.xlsx` 없으면 maia_loop 빈 채로 진행

### 중기 (추가 개선)

- [ ] 바이오피드백 자체 데이터 저장 모듈 (`SessionLogger`) 완성 — 현재 30s epoch CSV 미저장
- [ ] block_type=neutral 시 status_text에 "조작 없음 (대조군)" 명시
- [ ] ECG 라인 jitter 추가 검증 (현재 60fps 보장 확인됨)
- [ ] Likert 응답 시 ECG가 부드럽게 페이드 인/아웃되도록 (현재는 즉시 숨김/표시)
- [ ] PostExp/MAIA 동안 ECG 표시 여부 결정 (현재 안 표시)

### 장기

- [ ] 실험자용 별도 모니터에 ParticipantWindow (PyQt6) 띄울 옵션 (dual-monitor 셋업)
- [ ] 카운터밸런싱 순서 수동 지정 옵션 (참가자 dropouts 보정용)

---

## 8. 환경 설정 체크리스트

### 새 컴퓨터에서 실행하려면

1. **PsychoPy 설치**: 2026.x (또는 호환 버전)
   - 기본 경로: `C:\Program Files\PsychoPy\`
   - `python.exe`에 `pylsl`, `pyserial`, `sounddevice`, `numpy`, `scipy` 포함되어 있는지 확인
2. **바이오피드백 .venv 준비**:
   ```powershell
   cd <project-dir>
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install pylsl
   ```
3. **OBELAB NIRSIT-LITE 소프트웨어**: LSL 송수신 활성화 (외부 동기용)
4. **`conditions/maia_items.xlsx`**: MAIA 문항 데이터 준비
5. **PPG 하드웨어 연결 확인**: 시리얼 포트(COM3 등) + 신호 출력 형식
6. **Dry run**: mock 소스로 전체 흐름 30분 테스트

---

## 9. 변경된 파일 (상세)

자세한 파일별 변경 내역은 [CHANGES.md](CHANGES.md) 참조.

핵심 신규 파일:
- `psychopy_experiment/fNIRS_HeartFeedback.psyexp` — 통합 PsychoPy 실험
- `psychopy_experiment/ecg_renderer.py` — 네온 ECG 렌더러
- `biofeedback/core/lsl_outlets.py` — LSL outlet 4종
- `biofeedback/core/calibration_runner.py` — 60s baseline 측정
- `biofeedback/core/lsl_controller.py` — PsychoPy 마커 수신

핵심 수정 파일:
- `biofeedback/main.py` — wire-up
- `biofeedback/gui/experimenter.py` — "실험 시작" 버튼 + 카운트다운

---

## 10. 문의 / 다음 단계

- 실행 중 에러 발생 시 **`biofeedback_console.log`** 마지막 부분 + **PsychoPy Runner 콘솔 출력** 함께 공유
- 추가 routine/시각자극 디자인 변경 필요 시 `.psyexp`와 `ecg_renderer.py` 수정 (Builder UI 또는 코드 직접)
- LSL 마커 추가/변경 시 `biofeedback/core/lsl_controller.py:_handle_marker`와 PsychoPy Each Frame 동시 업데이트
