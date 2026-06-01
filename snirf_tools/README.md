# SNIRF 마커 연동 (snirf_tools)

PsychoPy 실험(`fNIRS_HeartFeedback`)이 남긴 이벤트 로그를 NIRSIT(`.snirf`)
파일에 **사후(post-hoc)** 로 마커로 박아 넣기 위한 도구 모음.

NIRSIT 녹화 자체에는 자극 마커가 없으므로, 실험이 끝난 뒤 PsychoPy가 기록한
이벤트 타임라인을 `.snirf`의 `/nirs/aux1` 채널에 삽입해 NIRSIT QUEST에서
구간 분석을 할 수 있게 한다.

## 구성

| 파일 | 역할 |
|---|---|
| `snirf_marker_editor.py` | 범용 SNIRF 마커 편집/삽입 엔진 (`edit_snirf`, `insert_snirf`). |
| `insert_markers_from_events.py` | 실험이 만든 `*_events.csv` → `aux1` 삽입 래퍼 (보통 이것만 쓰면 됨). |

## 의존성

`h5py`가 필요하다. PsychoPy 번들 파이썬에는 없을 수 있으니, 그 경우 한 번만
설치하거나 h5py가 있는 별도 환경에서 실행한다.

```
pip install h5py numpy pandas
```

## 실험이 만드는 로그 파일

본 실험이 **시작(안정화 루틴 진입)** 되는 순간 `biofeedback_inline`이 두 개의
CSV를 PsychoPy 데이터 폴더에 만든다. (PsychoPy 데이터 파일명 base 기준)

- `<base>_events.csv` — 이산 이벤트(페이즈 전환, 설문/키 입력 마킹)
  - 열: `onset, code, label, value, block_type, phase, unix_time, iso_time`
  - `onset` = 실험 시작(=`experiment_start`, onset 0)으로부터의 **초**
  - `code` = 아래 표의 숫자 마커
- `<base>_ppg_bpm.csv` — 1초마다 PPG 심박/조작량 스냅샷
  - 열: `t_sec, unix_time, iso_time, real_bpm, output_bpm, manip_pct, manip_state, block_type, phase`

> SNIRF 삽입에는 `_events.csv`만 쓴다. `_ppg_bpm.csv`는 분석용 시계열.

## 마커 코드 표

| code | label | 의미 |
|---|---|---|
| 1 | experiment_start | 로깅 시작 앵커 (onset 0) |
| 2 | stabilization | 안정화 휴식 진입 |
| 3 | baseline | 베이스라인 진입 |
| 4 | rest / rest_between_blocks | 블록 간 휴식 |
| 11 | accel | 블록 유형: 가속 조작 |
| 12 | decel | 블록 유형: 감속 조작 |
| 13 | neutral | 블록 유형: 중립(조작 없음) |
| 21 | P1_sync | Phase1 동기화 진입 |
| 22 | P2_ramp | Phase2 미니 epoch (20s 간격, 블록당 9회) |
| 23 | P3_plateau | Phase3 고원 진입 |
| 24 | P4_recovery | Phase4 회복 진입 |
| 31 | likert_on | 블록 내 Likert 표시 시작 (`value`에 질문문) |
| 32 | likert_off | 블록 내 Likert 종료 |
| 41 | postexp_bpm | 사후 설문: BPM 일치도 |
| 42 | postexp_trust | 사후 설문: 신뢰도 |
| 43 | maia_start | MAIA 설문 시작 |
| 99 | experiment_end | 실험 종료 마커 |
| 100 | logging_end | 로깅 종료 (파일 닫기 직전) |

> 표에 없는 라벨이 push되면 200번부터 자동 배정되고 콘솔에 매핑이 출력된다.

## 시간 정렬 (`--offset`) — 가장 중요

`_events.csv`의 `onset 0`은 PsychoPy `experiment_start` 마커가 찍힌 순간이다.
NIRSIT 시간축의 0은 NIRSIT **녹화 시작** 순간이다. 둘은 보통 다르다.

```
SNIRF에 박히는 시각 = events.onset + offset
offset = (NIRSIT 녹화 시작 → experiment_start) 사이의 초
```

- NIRSIT을 실험(안정화 루틴) 시작보다 **30초 먼저** 켰다면 → `--offset 30`
- 동시에 시작했다면 → `--offset 0`
- (드물게) PsychoPy가 NIRSIT보다 먼저라면 음수 offset도 가능

가장 정확한 offset을 얻는 방법: 두 시스템의 벽시계(wall-clock)를 비교한다.
`_events.csv`의 `experiment_start` 행 `iso_time`(또는 `unix_time`)과 NIRSIT 녹화
시작 시각의 차이가 곧 offset이다. 시간축 밖으로 나가는 onset은 자동으로
드롭되고 로그에 표시되므로, 잘 모르면 몇 개 값으로 시도해 보며 맞춘다.

### 마커 시간 해상도 주의

aux1 마커는 fNIRS 샘플 1개(보통 NIRSIT ~8Hz → 약 0.12초) 단위로 박힌다.
**같은 샘플 안에 들어오는 두 마커는 한 칸에 겹쳐 나중 것이 앞 것을 덮어쓴다.**
본 실험의 페이즈/설문 마커는 모두 초~분 단위로 떨어져 있어 문제가 없지만,
혹시 0.1초 이내로 붙는 마커(예: 같은 순간의 likert_on/off)가 있다면 둘 중
하나만 남을 수 있다. 정밀한 다중 마커가 필요하면 `_events.csv` 원본(밀리초
onset 보존)을 분석에 직접 쓰는 편이 낫다.

## 사용법

### 단일 파일

```
"C:\Program Files\PsychoPy\python.exe" insert_markers_from_events.py ^
    --events ..\psychopy_experiment\data\P01_events.csv ^
    --snirf  C:\NIRSIT\P01.snirf ^
    --offset 30
```

→ 원본은 그대로 두고 `C:\NIRSIT\P01_with_markers.snirf` 를 만든다.
NIRSIT QUEST로 `_with_markers.snirf`를 열면 aux1에 마커가 보인다.

### 폴더 일괄

`--snirf`에 폴더를 주면 그 안의 모든 `.snirf`에 같은 events/offset을 적용한다
(참가자별로 다르면 폴더 일괄은 피하고 파일 단위로 돌릴 것).

### 원본 직접 수정

```
... --in-place
```

## 검증

삽입 후 마커가 잘 박혔는지 빠르게 확인:

```python
import h5py, numpy as np
with h5py.File(r"C:\NIRSIT\P01_with_markers.snirf", "r") as f:
    aux = f["/nirs/aux1/dataTimeSeries"][()].ravel()
    nz = np.nonzero(aux)[0]
    print("마커 개수:", nz.size)
    print("코드들:", np.unique(aux[nz]))
```

## 고급: 엔진 직접 사용

행 범위·열 지정·기존 마커 정리 등 세밀한 제어가 필요하면
`snirf_marker_editor.py` 상단 docstring과 하단 데모(예시 1~7)를 참고.
요지:

- NIRSIT QUEST는 **aux1만** 읽으므로 항상 `"aux_target": "aux1"`.
- 기존 마커를 비우고 새로 박으려면 `edit_snirf(mapping={"<old>": 0})`로 먼저 0 처리.
- CLI: `python snirf_marker_editor.py -i ./data -s spec.json --recursive`
