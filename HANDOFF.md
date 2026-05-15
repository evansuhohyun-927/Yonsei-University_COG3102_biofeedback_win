# Biofeedback 프로젝트 — Handoff 문서

> 이 문서는 macOS에서 시작한 프로젝트를 Windows 머신에서 이어가기 위한
> 컨텍스트 인계서입니다. Windows의 새 Claude Code 세션이 이 문서를 먼저
> 읽으면 지금까지의 결정 / 시행착오 / 남은 작업을 한 번에 파악할 수 있습니다.

---

## 1. 프로젝트 목적

인지과학 / 심리학 실험을 위한 실시간 시·청각 바이오피드백 프로그램.

핵심 요구사항:
1. **실시간 HR 데이터 수집** — Apple Watch (OSC 브릿지 앱 경유) 또는 연구실 자체 제작 DIY PPG (Serial)
2. **시·청각 피드백** — 박동하는 ECG 파형(빨간 네온), 박동하는 하트 도형, 심장박동 소리 / 톤
3. **가짜 피드백(Fake Feedback) 조작** — 실험자가 실시간으로 표시되는 BPM을 실제값 ± n%까지 끌어올리거나 낮춤. ramp-up → hold → ramp-down 의 상태머신
4. **PsychoPy 연동** — 추후 작업 예정 (아직 미구현)
5. **배포 가능한 실행 파일** — macOS `.app` (완료), Windows `.exe` (이 폴더의 인프라로 빌드)

---

## 2. 아키텍처

```
[HR Source]  →  EventBus("bpm_real")  →  [Manipulator]  →  EventBus("bpm_output")
                                                                    ↓
                                                          [BeatScheduler]
                                                                    ↓
                                                          EventBus("beat")
                                                                    ↓
                                              ┌─────────────────┴─────────────────┐
                                              ↓                                   ↓
                                  [VisualFeedback (ECG + heart)]      [AudioFeedback]
```

핵심 컴포넌트:
- **EventBus** (`core/bus.py`): 스레드 안전 pub-sub. 이벤트: `bpm_real`, `bpm_output`, `beat`, `manipulator_state`
- **Manipulator** (`core/manipulator.py`): 상태머신 (`IDLE → RAMP_UP → HOLD → RAMP_DOWN → IDLE`). `output_bpm = real_bpm × (1 + factor(t))`, factor는 0 ↔ target_pct/100 사이를 linear 또는 ease-in-out 곡선으로 보간
- **BeatScheduler** (`core/beat_scheduler.py`): 현재 `output_bpm`에 맞춰 60/bpm 초 간격으로 `beat` 이벤트 발행
- **SourceManager** (`core/source_manager.py`): 런타임에 HR 소스 교체 (Mock ↔ PPG 등)
- **ExperimenterWindow** (`gui/experimenter.py`): 컨트롤 패널 + 실시간 BPM 그래프 + PPG 캘리브레이션 UI
- **ParticipantWindow** (`feedback/participant_window.py`): 검정 배경, 가운데 빨간 네온 ECG 스크롤, 우측 하단 박동 하트
- **AudioFeedback** (`feedback/audio.py`): 합성 heartbeat thump 또는 BPM-tied tone

---

## 3. 폴더 구조

```
biofeedback_win/
├── HANDOFF.md                  ← 이 문서
├── .gitignore
├── app_entry.py                ← PyInstaller 엔트리 포인트 (frozen에서 Qt plugin path 자동 설정)
├── requirements.txt
├── setup.bat                   ← Windows venv 생성 + 의존성 설치
├── run.bat                     ← 일반 실행
├── build.bat                   ← PyInstaller로 .exe 빌드
├── biofeedback/
│   ├── core/
│   │   ├── bus.py              ← EventBus
│   │   ├── types.py            ← BPMSample, FakeFeedbackParams, ManipulatorState
│   │   ├── manipulator.py      ← 상태머신
│   │   ├── beat_scheduler.py
│   │   └── source_manager.py
│   ├── hr_sources/
│   │   ├── base.py             ← HRSource ABC
│   │   ├── mock.py             ← 개발용 시뮬레이션 (사인파 + 노이즈)
│   │   ├── osc_source.py       ← Apple Watch (OSC 수신)
│   │   └── ppg_serial.py       ← DIY PPG (Serial → peak detection → BPM)
│   ├── feedback/
│   │   ├── participant_window.py  ← 빨간 네온 ECG + 박동 하트
│   │   └── audio.py            ← heartbeat thump / tone / both
│   ├── gui/
│   │   └── experimenter.py     ← 컨트롤 패널 + PPG 캘리브레이션
│   └── main.py                 ← QApplication 진입점 (CLI args 처리)
└── resources/
    ├── make_icon.py            ← .ico 생성 스크립트
    └── icon.ico                ← 빨간 하트 + 흰 ECG 아이콘 (사전 생성됨, 다중 해상도)
```

---

## 4. 구현된 기능

### HR 소스 (`biofeedback/hr_sources/`)
- **MockHRSource**: 기본값 70 BPM 사인파(±8) + 가우시안 노이즈. 하드웨어 없이 개발 가능
- **OSCHRSource**: UDP/OSC로 BPM 수신. 기본 주소 `/HR`, 포트 9000. Apple Watch는 HRV Logger 같은 브릿지 앱 필요
- **PPGSerialSource**: 시리얼 한 줄 = float 한 개. scipy `find_peaks`로 peak 검출 → 평균 RR 간격 → BPM. **`parse_line()` 메서드를 실제 PPG 출력 형식에 맞게 오버라이드 필요**

### Manipulator (가짜 피드백)
- 파라미터: `target_pct` (-50 ~ +50), `ramp_up_duration`, `hold_duration`, `ramp_down_duration`, `curve` (`linear` / `ease`)
- API: `start_fake(params)`, `stop_fake(immediate=False)`. immediate=True면 ramp 없이 즉시 IDLE
- 출력: 20Hz 업데이트로 `bpm_output` publish

### 실험자 GUI
- 상단: real BPM / output BPM / state 라이브 표시
- 라이브 그래프: 최근 60초의 real vs output BPM (pyqtgraph)
- Fake Feedback 패널: target %, curve, ramp/hold 시간 입력 + Start/Stop/EMERGENCY STOP 버튼
- Participant Feedback 패널: **"피험자 인터페이스 실행"** 버튼, Audio 토글, audio mode 드롭다운 (heartbeat/tone/both)
- **PPG Connection & Calibration 패널**:
  - 시리얼 포트 자동 검색 (Refresh 버튼)
  - Connect/Disconnect 버튼 (런타임에 소스 교체)
  - Peak threshold (max amplitude 대비 비율) + Min interval 슬라이더 (실시간 반영)
  - **Auto-Calibrate** 버튼 — 0.15~0.50 사이 8개 threshold 시도 후 40-180 BPM + 가장 안정적인 RR 변동성 가진 값 자동 선택
  - 실시간 raw PPG 그래프 + 검출된 peak 빨간 점 오버레이

### 피험자 창
- 검정 배경, 풀스크린 가능 (`F` 키 토글, `Esc`로 해제)
- 가운데: 빨간 네온 ECG 파형 (PQRST 합성, 5초 윈도우, 좌→우 스크롤). 3-pass 스트로킹으로 글로우 효과 (외곽 halo → 중간 글로우 → 밝은 코어)
- 우측 하단: parametric heart curve로 그린 빨간 하트, beat마다 1.45배 확대 후 18%씩 감쇠
- **BPM 숫자 표시는 의도적으로 제거됨** (실험 디자인상 피험자가 정확한 BPM 알면 안 됨)

### 오디오
- 모드: `heartbeat` (beat마다 합성 thump 재생) / `tone` (BPM → 200~600Hz 매핑한 연속 사인) / `both`
- thump 파형: 6ms raised-cosine attack + 200ms 지수 감쇠 + 20ms 선형 fade-out → **시작/끝이 정확히 0** (클릭 노이즈 방지)
- 단일 75Hz 사인파 사용 (이전 dual-sine은 클리핑 문제로 폐기)
- blocksize=0 (PortAudio 자동), latency="high" (안정성 우선)

---

## 5. 아직 안 한 / 미해결

- [ ] **PsychoPy 연동** — 향후 작업. 권장 방식은 UDP/OSC로 PsychoPy 프로세스와 통신 (시각자극 frame timing 보호 위해)
- [ ] **PPG `parse_line` 튜닝** — 현재 stub. 실제 DIY PPG의 출력 형식 확인 후 조정 필요
- [ ] **Apple Watch 브릿지 앱 결정** — HRV Logger ($5) 또는 직접 WatchOS 앱 제작. 대안은 Polar H10 같은 BLE 스트랩 (정확도가 오히려 더 좋음)
- [ ] **Windows에서 실제 검증** — 이 폴더의 코드/스크립트는 macOS에서 작성됨. Windows에서 한 번도 실행 안 해봄 (아래 6번 항목 참조)

---

## 6. Windows에서 첫 실행 시 검증 체크리스트

```cmd
:: 1. clone 후 setup
setup.bat

:: 2. 일반 실행 - Mock 소스로 GUI / 그래프 / 피험자창 동작 확인
run.bat

:: 3. 빌드 - 독립 .exe 생성
build.bat
:: → dist\Biofeedback\Biofeedback.exe
```

각 단계에서 확인할 사항:
- [ ] `setup.bat` — venv 생성되고 PyQt6 / sounddevice / scipy 설치되는지
- [ ] `run.bat` — Qt 플랫폼 플러그인 에러 없이 GUI 뜨는지 (Windows 기본 plugin은 `qwindows.dll`, 경로 자동 설정 로직 검증 필요)
- [ ] Mock 모드에서 실시간 그래프가 그려지는지
- [ ] "피험자 인터페이스 실행" 버튼 클릭 시 검정 창 + 빨간 ECG 파형이 뜨는지
- [ ] Audio 토글 → 심장박동 소리가 깨끗하게 나는지 (지지직 노이즈 없어야 함)
- [ ] Fake Feedback Start → 라이브 그래프에서 output(빨강)이 real(파랑) 위로 ramp up 되는지
- [ ] PPG 패널의 "Refresh ports" 클릭 → Windows의 COM 포트들이 나오는지
- [ ] (PPG 하드웨어 있으면) Connect → raw 신호가 그려지는지
- [ ] `build.bat` → `.exe` 생성 + 다른 Windows에서도 동작하는지 (PyInstaller `--onedir` 출력)

---

## 7. macOS에서 겪은 큰 시행착오 (Windows에서 반복하지 말 것)

### A. PyQt6 6.11 wheel 버그 → 6.7.x로 다운그레이드
macOS에서 6.11은 cocoa 플랫폼 플러그인이 로드 실패. requirements.txt에 `PyQt6==6.7.*` 핀.
Windows에서도 동일 핀을 유지함 (안정성 검증 완료된 버전).

### B. macOS Sequoia + PyQt6 6.7: darwin permission 정적 링크 segfault
QtCore.abi3.so에 macOS 위치/블루투스/카메라/마이크 권한 초기화 코드가 정적 링크되어 있어,
Info.plist에 `NSLocationUsageDescription` 등의 키 없으면 앱 시작 시 segfault.
→ `build.sh`(mac 폴더)에서 PlistBuddy로 더미 usage description 추가 후 재서명.
**Windows에서는 해당 없음** — `build.bat`에 해당 로직 없음 (필요 없음).

### C. iCloud Drive가 Desktop의 venv 심볼릭 링크를 망가뜨림
`.venv/bin/python` 등이 ` 2` 접미사 붙은 중복 파일들로 변형됨.
→ 프로젝트를 `~/biofeedback`으로 이동.
**Windows에서는 OneDrive에 Desktop이 동기화되어 있으면 비슷한 문제 가능** — `.venv` 폴더를 OneDrive 제외 설정 권장.

### D. conda 환경이 PyInstaller 빌드 오염 (anaconda의 PyQt5/PySide6 충돌)
→ `build.bat`에서 명시적으로 `.venv\Scripts\python.exe`로 PyInstaller 실행,
`PYTHONPATH` / `PYTHONHOME` 비움, `--exclude-module PyQt5 PySide6 PySide2`.
**Windows에 conda가 있으면 동일 문제 가능**.

### E. 오디오 "지지직" 노이즈 (해결 완료)
heartbeat thump 파형의 끝 진폭이 0이 아니라 ~0.016 → 0으로 떨어지는 step discontinuity가 클릭 음 발생.
→ envelope에 6ms attack + 20ms fade-out 추가, 단일 75Hz 사인파로 단순화.
시작과 끝이 모두 정확히 0 (검증: `t[0] == 0.0`, `t[-1] == 0.0`).

---

## 8. 기술적 의사결정 (왜 이렇게 만들었는가)

- **PyQt6 + pyqtgraph (vs Tkinter/matplotlib)** — 실시간 그래프 성능, Qt 통합, 풀스크린 / 멀티 모니터 지원
- **EventBus 패턴 (vs 직접 콜백)** — HR 소스 / Manipulator / Feedback 디커플링, 새 modality 추가 용이
- **Manipulator는 20Hz 업데이트, BeatScheduler는 60/bpm Hz** — output_bpm 변화는 부드럽게, beat 트리거는 정확한 박동 간격
- **sounddevice (PortAudio) 사용** — 크로스플랫폼, 저지연. Windows에서 WASAPI 기본 사용
- **체크박스 → 버튼으로 변경** — 사용자가 "피험자 창 켜기"를 명시적 액션으로 만들고 싶어 함
- **PPG raw 신호 미리보기 + peak 오버레이** — 자동 캘리브레이션이 잘못된 경우 시각적으로 즉시 인지 가능
- **합성 ECG 파형 (vs 실제 PPG 시각화)** — 피험자에게 보여줄 파형은 "이상화된" 의료 ECG 모양이어야 함. 가우시안 P/Q/R/S/T 복합파

---

## 9. 사용자 선호 (이전 대화 기반)

- 한국어로 응답, 기술 용어는 영어 혼용 OK
- **간결한 응답** 선호 — 불필요한 설명 / 트레일링 요약 자제
- 인지과학 / 심리학 연구자 배경. PsychoPy 사용
- conda를 main 환경으로 사용 중 (`(base)` prompt). 자체 venv와 충돌한 적 있으니 주의
- macOS Apple Silicon (Mac15,7, macOS Sequoia 15.3)
- 코드 변경 시 **이유 + 검증 결과까지** 함께 보고하는 것 선호
- "실행 안 됨" 같은 짧은 오류 보고를 자주 함 → 크래시 로그 / 시스템 상태 먼저 확인하는 것이 도움됨

---

## 10. 다음 세션이 첫 작업으로 할 만한 일

우선순위 순:

1. **Windows에서 `setup.bat` → `run.bat` 동작 검증**
2. **`build.bat`으로 `.exe` 생성 + 다른 Windows 머신 (또는 깨끗한 사용자 계정)에서 실행 테스트**
3. **PPG 하드웨어가 있으면** `parse_line()` 형식 조정 + 실제 데이터로 Auto-Calibrate 동작 검증
4. **PsychoPy 연동 prototype** — UDP/OSC 메시지 프로토콜 정의 (예: `{"action": "start_fake", "target_pct": 20, "ramp_s": 120}`)
5. **로깅 기능 추가** — 실험 세션 동안 real BPM / output BPM / state 변화 / fake feedback 이벤트를 CSV로 저장 (현재 미구현이지만 실험 데이터 분석에 필수)

---

## 11. 핵심 파일 빠른 참조

| 파일 | 무엇이 들어 있는지 |
|------|-------------------|
| `biofeedback/main.py` | QApplication 진입점, CLI args 처리, 소스 초기화 |
| `biofeedback/core/manipulator.py` | 가짜 피드백 상태머신 (factor 계산, 상태 전이) |
| `biofeedback/feedback/audio.py` | thump 합성 (`_make_thump`), 오디오 콜백 (`_callback`) |
| `biofeedback/feedback/participant_window.py` | ECG 위젯 (3-pass 글로우), 하트 위젯 |
| `biofeedback/gui/experimenter.py` | 모든 컨트롤 UI. `_build_ppg_controls`에 캘리브레이션 UI |
| `biofeedback/hr_sources/ppg_serial.py` | peak 검출 + `auto_calibrate` 알고리즘 |
| `app_entry.py` | frozen .exe에서 Qt plugin path 자동 설정 (Windows에서도 적용됨) |
| `build.bat` | PyInstaller 옵션 (PyQt5/PySide6 명시적 제외 포함) |
