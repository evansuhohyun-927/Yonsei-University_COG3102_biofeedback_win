"""
insert_markers_from_events.py
=============================
PsychoPy 실험이 남긴 ``*_events.csv`` 를 읽어, 그 안의
``onset`` (초) / ``code`` (숫자 마커) 열을 그대로 NIRSIT(.snirf) 파일의
``/nirs/aux1`` 채널에 박아 넣는 얇은 래퍼.

핵심 아이디어
------------
biofeedback_inline 의 로깅이 만든 events CSV 는 이미
``onset_column='onset'`` + ``code_column='code'`` 형식이라,
snirf_marker_editor.insert_snirf 가 추가 가공 없이 바로 소비할 수 있다.

이 스크립트는 단지
  1. events CSV 의 데이터 행 수를 세고 (row_start/row_end 계산),
  2. NIRSIT 호환 spec(method=aux, aux_target=aux1)을 만들어,
  3. insert_snirf 를 호출
하는 일만 한다.

시간 정렬 (--offset)
-------------------
events CSV 의 onset 0 = PsychoPy ``experiment_start`` 마커가 찍힌 순간이다.
NIRSIT 녹화를 그보다 먼저 시작했다면, 그 선행 시간(초)을 ``--offset`` 으로
준다. 예) NIRSIT 을 자극 시작 30초 전에 켰으면 ``--offset 30``.
  SNIRF 시간축 onset = events.onset + offset

사용 예
-------
  # PsychoPy 인터프리터로 (h5py 가 깔린 환경에서) 실행
  "C:\\Program Files\\PsychoPy\\python.exe" insert_markers_from_events.py ^
      --events ..\\psychopy_experiment\\data\\P01_events.csv ^
      --snirf  C:\\NIRSIT\\P01.snirf ^
      --offset 30

  # 폴더 단위로도 가능 (--snirf 에 폴더 경로)
  python insert_markers_from_events.py --events P01_events.csv --snirf .\\snirf_in --offset 0

결과물은 원본을 건드리지 않고 ``<원본>_with_markers.snirf`` 로 저장된다.
``--in-place`` 를 주면 원본을 직접 수정한다.

의존성: pip install h5py numpy pandas
"""

from __future__ import annotations

import argparse
import os
import sys

# 같은 폴더의 snirf_marker_editor 를 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snirf_marker_editor import insert_snirf  # noqa: E402


def _count_data_rows(events_csv: str) -> int:
    """events CSV 의 (헤더 제외) 데이터 행 수. pandas 없으면 순수 파이썬으로."""
    try:
        import pandas as pd
        df = pd.read_csv(events_csv)
        return int(len(df))
    except ImportError:
        with open(events_csv, "r", encoding="utf-8-sig", newline="") as f:
            n = sum(1 for _ in f)
        return max(0, n - 1)  # 헤더 1줄 제외


def build_spec(events_csv: str, offset: float, aux_target: str) -> dict:
    """events CSV → insert_snirf 용 spec(dict)."""
    n_rows = _count_data_rows(events_csv)
    if n_rows <= 0:
        raise ValueError(f"events CSV 에 데이터 행이 없습니다: {events_csv}")

    # 엑셀 1-based(헤더 포함): 데이터는 2행부터 n_rows+1행까지
    row_start = 2
    row_end = n_rows + 1

    return {
        "defaults": {
            "method": "aux",
            "aux_target": aux_target,   # NIRSIT QUEST 는 aux1 만 읽음
            "unit": "seconds",
            "onset_offset": float(offset),
        },
        "markers": [
            {
                "csv": events_csv,
                "onset_column": "onset",
                "code_column": "code",
                "row_start": row_start,
                "row_end": row_end,
                "has_header": True,
                "code": 0,  # code 열이 비었을 때의 기본값
            }
        ],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="insert_markers_from_events",
        description="PsychoPy events CSV → NIRSIT(.snirf) aux1 마커 삽입",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--events", required=True,
                   help="PsychoPy 가 만든 *_events.csv 경로.")
    p.add_argument("--snirf", required=True,
                   help="대상 .snirf 파일 또는 폴더 경로.")
    p.add_argument("--offset", type=float, default=0.0,
                   help="onset 에 더할 초. NIRSIT 을 자극보다 N초 먼저 켰으면 N. "
                        "(기본 0)")
    p.add_argument("--aux-target", default="aux1",
                   help="마커를 박을 aux 채널. NIRSIT 호환은 aux1 (기본).")
    p.add_argument("--in-place", action="store_true",
                   help="원본 .snirf 를 직접 수정. 기본은 복사본(_with_markers) 생성.")
    p.add_argument("--output-dir", default=None,
                   help="결과 폴더(--in-place 가 아닐 때).")
    p.add_argument("--recursive", action="store_true",
                   help="--snirf 가 폴더일 때 하위 폴더까지 탐색.")
    args = p.parse_args(argv)

    if not os.path.isfile(args.events):
        print(f"ERROR: events CSV 를 찾을 수 없습니다: {args.events}",
              file=sys.stderr)
        return 2
    if not os.path.exists(args.snirf):
        print(f"ERROR: snirf 경로를 찾을 수 없습니다: {args.snirf}",
              file=sys.stderr)
        return 2

    spec = build_spec(args.events, args.offset, args.aux_target)

    print("=" * 70)
    print(f"[insert_markers] events : {args.events}")
    print(f"[insert_markers] snirf  : {args.snirf}")
    print(f"[insert_markers] offset : {args.offset} s")
    print(f"[insert_markers] aux    : {args.aux_target}")
    print(f"[insert_markers] rows   : {spec['markers'][0]['row_start']}"
          f"~{spec['markers'][0]['row_end']} (엑셀 1-based)")
    print("=" * 70)

    reports = insert_snirf(
        input_path=args.snirf,
        spec=spec,
        in_place=args.in_place,
        output_dir=args.output_dir,
        recursive=args.recursive,
        verbose=True,
    )

    if any(r.skipped_reason for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
