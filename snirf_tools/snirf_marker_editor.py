"""
snirf_marker_editor.py
======================
SNIRF (.snirf) 파일의 stimulus / event / marker 정보를 일괄적으로
편집·삽입하기 위한 범용 스크립트.

두 가지 메인 entry point 가 동일한 패턴으로 제공됩니다.

  [A] edit_snirf(input_path, mapping, ...)
        - 기존 마커를 매핑 규칙으로 일괄 변경
        - mapping: dict 또는 JSON 경로
            예) {"TrialStart": "Trial_Start", "2001": 5001}

  [B] insert_snirf(input_path, spec, ...)
        - 새 마커를 SNIRF 에 일괄 삽입
        - spec: dict/list 또는 JSON 경로
            예) {
                  "defaults": {"method": "aux", "unit": "seconds"},
                  "markers": [
                    {"code": 2001, "onsets": [5.0, 15.0, 30.0]},
                    {"code": 5001, "csv": "events.csv",
                     "onset_column": "D", "row_start": 5, "row_end": 10,
                     "code_column": "E"}
                  ]
                }

두 가지 마커 저장 방식 모두 지원:
    (A) /nirs*/stim* 그룹  — 표준 SNIRF, name + [onset, duration, amplitude]
    (B) /nirs*/aux*  채널  — NIRSIT QUEST 등이 사용하는 숫자 코드 펄스

NIRSIT QUEST 호환 팁:
    NIRSIT 은 보통 /nirs/aux1 채널에서만 마커를 읽으므로,
    insert 시 새 aux 채널을 만들지 말고 기존 aux1 에 직접 박아야 함:
        "defaults": {"method": "aux", "aux_target": "aux1"}

마커는 기본적으로 "시점 이벤트"(duration=0)로 저장됩니다.
구간 마커가 필요하면 spec 에서 명시적으로 duration 을 지정하세요.

필수 의존성:
    pip install h5py numpy pandas
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import h5py
import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ===========================================================================
# 공통 자료구조
# ===========================================================================
StrMapping = Dict[str, str]
NumMapping = Dict[float, float]


@dataclass
class EditReport:
    """단일 파일 처리 결과 요약."""
    file_path: str
    output_path: str
    name_changes: Dict[str, int] = field(default_factory=dict)
    code_changes: Dict[str, int] = field(default_factory=dict)
    stim_groups_scanned: int = 0
    aux_channels_scanned: int = 0
    skipped_reason: Optional[str] = None

    @property
    def total_changes(self) -> int:
        return sum(self.name_changes.values()) + sum(self.code_changes.values())


# ===========================================================================
# 공통 헬퍼
# ===========================================================================
def _try_float(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _decode_bytes(val) -> str:
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, np.ndarray):
        if val.size == 0:
            return ""
        item = val.flat[0]
        if isinstance(item, bytes):
            return item.decode("utf-8", errors="replace")
        return str(item)
    return str(val)


def _format_marker_name(name) -> str:
    """숫자(int/float)도 '2001' 처럼 깔끔한 문자열로."""
    if isinstance(name, bool):
        return str(name)
    if isinstance(name, (int, np.integer)):
        return str(int(name))
    if isinstance(name, (float, np.floating)):
        f = float(name)
        return str(int(f)) if f.is_integer() else f"{f:g}"
    return str(name)


def _excel_col_to_index(col) -> int:
    """엑셀 알파벳 열을 0-based 인덱스로. 'A'->0, 'D'->3, 'AA'->26."""
    if isinstance(col, int):
        return col
    if not isinstance(col, str):
        raise TypeError(f"Column must be str or int, got {type(col).__name__}")
    s = col.strip().upper()
    if not s.isalpha():
        raise ValueError(f"Excel-style column must be alphabetic; got {col!r}")
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def collect_snirf_files(input_path: str, recursive: bool = False) -> List[str]:
    """입력이 파일이면 [경로], 폴더면 .snirf 파일 목록 반환."""
    if os.path.isfile(input_path):
        if not input_path.lower().endswith(".snirf"):
            raise ValueError(f"Not a .snirf file: {input_path}")
        return [input_path]
    if os.path.isdir(input_path):
        results: List[str] = []
        if recursive:
            for root, _, files in os.walk(input_path):
                for fn in files:
                    if fn.lower().endswith(".snirf"):
                        results.append(os.path.join(root, fn))
        else:
            for fn in os.listdir(input_path):
                full = os.path.join(input_path, fn)
                if os.path.isfile(full) and fn.lower().endswith(".snirf"):
                    results.append(full)
        return sorted(results)
    raise FileNotFoundError(f"Input path not found: {input_path}")


def resolve_output_path(
    src_path: str, in_place: bool,
    output_dir: Optional[str], suffix: str,
) -> str:
    if in_place:
        return src_path
    base_dir = output_dir or os.path.dirname(src_path)
    os.makedirs(base_dir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src_path))
    return os.path.join(base_dir, f"{stem}{suffix}{ext}")


def _find_target_nirs_group(h5: h5py.File, nirs_key: str = "nirs") -> Tuple[str, h5py.Group]:
    if nirs_key in h5 and isinstance(h5[nirs_key], h5py.Group):
        return nirs_key, h5[nirs_key]
    for k in h5.keys():
        if k.lower().startswith("nirs") and isinstance(h5[k], h5py.Group):
            return k, h5[k]
    raise RuntimeError("No /nirs* group found in this SNIRF file.")


def _get_sampling_rate(h5: h5py.File) -> Optional[float]:
    for top_key in list(h5.keys()):
        if not top_key.lower().startswith("nirs"):
            continue
        nirs_grp = h5[top_key]
        if not isinstance(nirs_grp, h5py.Group):
            continue
        for sub_key in list(nirs_grp.keys()):
            if not sub_key.lower().startswith("data"):
                continue
            data_grp = nirs_grp[sub_key]
            if not isinstance(data_grp, h5py.Group):
                continue
            if "time" not in data_grp:
                continue
            t = np.asarray(data_grp["time"][()]).astype(np.float64).ravel()
            if t.size >= 2:
                dt = float(t[1] - t[0])
                if dt > 0:
                    return 1.0 / dt
    return None


def _get_nirs_time_array(nirs_grp: h5py.Group) -> Optional[np.ndarray]:
    for sub_key in list(nirs_grp.keys()):
        if not sub_key.lower().startswith("data"):
            continue
        data_grp = nirs_grp[sub_key]
        if not isinstance(data_grp, h5py.Group):
            continue
        if "time" in data_grp:
            return np.asarray(data_grp["time"][()]).astype(np.float64).ravel()
    return None


def _convert_to_seconds(
    onsets: np.ndarray, unit: str, sampling_rate: Optional[float],
) -> np.ndarray:
    unit = unit.lower()
    if unit in ("s", "sec", "second", "seconds"):
        return onsets.astype(np.float64)
    if unit in ("ms", "millisecond", "milliseconds"):
        return onsets.astype(np.float64) / 1000.0
    if unit in ("sample", "samples", "idx", "index"):
        if sampling_rate is None or sampling_rate <= 0:
            raise ValueError(
                "Sampling rate is required to convert sample indices to seconds, "
                "but it could not be determined from the SNIRF file. "
                "Please pass sampling_rate explicitly via spec."
            )
        return onsets.astype(np.float64) / float(sampling_rate)
    raise ValueError(f"Unknown time unit: {unit!r}")


def _onsets_to_indices(onsets_sec: np.ndarray, time_arr: np.ndarray) -> np.ndarray:
    idxs = np.empty(onsets_sec.size, dtype=np.int64)
    for i, t in enumerate(onsets_sec):
        idxs[i] = int(np.argmin(np.abs(time_arr - t)))
    return idxs


def _load_json_or_dict(obj: Union[str, Dict, List, None], kind: str) -> Any:
    """JSON 경로면 파일을 읽고, dict/list 면 그대로 반환."""
    if obj is None:
        return None
    if isinstance(obj, str):
        if not os.path.isfile(obj):
            raise FileNotFoundError(f"{kind} JSON not found: {obj}")
        with open(obj, "r", encoding="utf-8") as f:
            return json.load(f)
    if isinstance(obj, (dict, list)):
        return obj
    raise TypeError(
        f"{kind} must be dict/list or path to a JSON file (got {type(obj).__name__})"
    )


# ===========================================================================
# [A] edit_snirf : 기존 마커 변경
# ===========================================================================
def load_mapping(
    mapping: Union[str, Dict, None],
) -> Tuple[StrMapping, NumMapping]:
    if mapping is None:
        return {}, {}
    mapping = _load_json_or_dict(mapping, "mapping")
    if not isinstance(mapping, dict):
        raise TypeError("mapping must be a dict")

    str_map: StrMapping = {}
    num_map: NumMapping = {}
    for k, v in mapping.items():
        k_num = _try_float(k)
        v_num = _try_float(v)
        if k_num is not None and v_num is not None:
            num_map[k_num] = v_num
        else:
            str_map[str(k)] = "" if v is None else str(v)
    return str_map, num_map


def _apply_str_mapping_to_stim(h5, str_map, report):
    if not str_map:
        return
    for top_key in list(h5.keys()):
        if not top_key.lower().startswith("nirs"):
            continue
        nirs_grp = h5[top_key]
        if not isinstance(nirs_grp, h5py.Group):
            continue
        for sub_key in list(nirs_grp.keys()):
            if not sub_key.lower().startswith("stim"):
                continue
            stim_grp = nirs_grp[sub_key]
            if not isinstance(stim_grp, h5py.Group):
                continue
            report.stim_groups_scanned += 1
            if "name" not in stim_grp:
                continue
            current = _decode_bytes(stim_grp["name"][()])
            if current not in str_map:
                continue
            new_name = str_map[current]
            del stim_grp["name"]
            stim_grp.create_dataset(
                "name",
                data=np.array(new_name, dtype=h5py.string_dtype(encoding="utf-8")),
            )
            key = f"{current!r} -> {new_name!r}"
            report.name_changes[key] = report.name_changes.get(key, 0) + 1


def _apply_num_mapping_to_aux(h5, num_map, report):
    if not num_map:
        return
    for top_key in list(h5.keys()):
        if not top_key.lower().startswith("nirs"):
            continue
        nirs_grp = h5[top_key]
        if not isinstance(nirs_grp, h5py.Group):
            continue
        for sub_key in list(nirs_grp.keys()):
            if not sub_key.lower().startswith("aux"):
                continue
            aux_grp = nirs_grp[sub_key]
            if not isinstance(aux_grp, h5py.Group):
                continue
            if "dataTimeSeries" not in aux_grp:
                continue
            report.aux_channels_scanned += 1
            ds = aux_grp["dataTimeSeries"]
            arr = np.asarray(ds[()]).astype(np.float64).copy()

            changed_total = 0
            for old_v, new_v in num_map.items():
                mask = np.isclose(arr, old_v, rtol=0, atol=1e-6)
                count = int(mask.sum())
                if count == 0:
                    continue
                arr[mask] = new_v
                changed_total += count
                key = f"{old_v:g} -> {new_v:g} (in /{top_key}/{sub_key})"
                report.code_changes[key] = report.code_changes.get(key, 0) + count

            if changed_total > 0:
                ds[...] = arr.astype(ds.dtype)


def edit_one_snirf(
    src_path: str,
    str_map: StrMapping,
    num_map: NumMapping,
    in_place: bool = False,
    output_dir: Optional[str] = None,
    suffix: str = "_edited",
) -> EditReport:
    output_path = resolve_output_path(src_path, in_place, output_dir, suffix)
    report = EditReport(file_path=src_path, output_path=output_path)

    if not in_place and os.path.abspath(src_path) != os.path.abspath(output_path):
        shutil.copy2(src_path, output_path)

    try:
        with h5py.File(output_path, "r+") as h5:
            _apply_str_mapping_to_stim(h5, str_map, report)
            _apply_num_mapping_to_aux(h5, num_map, report)
    except Exception as e:
        report.skipped_reason = f"{type(e).__name__}: {e}"
    return report


def edit_snirf(
    input_path: str,
    mapping: Union[str, Dict, None],
    in_place: bool = False,
    output_dir: Optional[str] = None,
    suffix: str = "_edited",
    recursive: bool = False,
    verbose: bool = True,
) -> List[EditReport]:
    """파일/폴더 경로를 받아 매핑 규칙으로 마커를 일괄 변경."""
    str_map, num_map = load_mapping(mapping)
    files = collect_snirf_files(input_path, recursive=recursive)

    if verbose:
        print(f"[edit_snirf] target: {input_path}")
        print(f"[edit_snirf] found {len(files)} .snirf file(s)")
        print(f"[edit_snirf] str-mapping: {len(str_map)}, num-mapping: {len(num_map)}")
        print("-" * 70)

    reports = []
    for i, f in enumerate(files, 1):
        if verbose:
            print(f"[{i}/{len(files)}] {f}")
        r = edit_one_snirf(f, str_map, num_map, in_place, output_dir, suffix)
        reports.append(r)
        if verbose:
            _print_report(r, indent="    ")

    if verbose:
        _print_summary(reports, label="edit_snirf")
    return reports


# ===========================================================================
# [B] insert_snirf : 새 마커 삽입 (스펙 기반)
# ---------------------------------------------------------------------------
# spec 구조 (둘 다 허용):
#
#   (1) list 형태  -- 마커 묶음만 적을 때
#       [ {marker_spec}, {marker_spec}, ... ]
#
#   (2) dict 형태  -- 글로벌 기본값과 함께
#       {
#         "defaults": {                  # 선택. 각 marker 에 기본값으로 적용.
#             "method": "aux",            # "aux" | "stim"  (기본 "aux")
#             "unit":   "seconds",        # "seconds"|"milliseconds"|"samples"
#             "mode":   "append",         # "append"|"replace"
#             "nirs_key": "nirs",
#             "sampling_rate": null
#         },
#         "markers": [ {marker_spec}, ... ]
#       }
#
# marker_spec 의 필드 (모두 선택, defaults 로 보강됨):
#
#   공통:
#     "method"   : "aux" 또는 "stim"
#                  생략 시 "code" 키가 있으면 "aux", "name" 이 있으면 "stim".
#     "unit"     : "seconds" / "milliseconds" / "samples"
#
#   onset 출처 - 둘 중 하나:
#     "onsets"   : [수치, 수치, ...]                ← 직접 적어 넣기
#     "csv"      : "path/to/events.csv"             ← CSV 에서 읽기
#       (csv 사용 시 같이 적는 필드)
#       "onset_column"   : "D"  또는  "onset"  또는  3
#       "row_start"      : 5    (엑셀 1-based, 헤더 포함 행 번호)
#       "row_end"        : 10   (포함)
#       "code_column"    : "E"   ← method=aux 일 때, 행별 코드값을 읽기
#       "name_column"    : "F"   ← method=stim 일 때, 행별 이름을 읽기
#       "duration_column": "G"   ← method=stim 일 때, 행별 duration 을 읽기
#       "has_header"     : true
#
#   onset_offset : 모든 onset 에 더할 값. unit 과 같은 단위로 해석.
#                  예) NIRSIT 이 자극 프로그램보다 30초 일찍 시작했다면
#                      unit="seconds", onset_offset=30
#                      자극 프로그램의 onset=5.0 → SNIRF 시간축에서 35.0 초
#                  음수도 가능. CSV / onsets 둘 다에 동일하게 적용됨.
#
#   method="aux" 일 때:
#     "code"      : 박을 숫자 코드 (스칼라 또는 onsets 길이의 리스트)
#     "aux_target": "new" (기본) 또는 기존 aux 이름("aux1")
#     "aux_name"  : "new" 일 때 부여할 이름
#
#   method="stim" 일 때:
#     "name"      : 마커 이름 (숫자도 가능 → "2001" 로 저장)
#     "duration"  : 시점 마커면 0 (기본). 구간이면 양수.
#     "amplitude" : 기본 1.0
# ===========================================================================
DEFAULT_INSERT_DEFAULTS: Dict[str, Any] = {
    "method": "aux",
    "unit": "seconds",
    "mode": "append",
    "nirs_key": "nirs",
    "sampling_rate": None,
}


def load_spec(
    spec: Union[str, Dict, List, None],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """spec 을 (defaults, markers) 튜플로 정규화."""
    if spec is None:
        return dict(DEFAULT_INSERT_DEFAULTS), []
    spec = _load_json_or_dict(spec, "spec")

    if isinstance(spec, list):
        defaults = dict(DEFAULT_INSERT_DEFAULTS)
        markers = spec
    elif isinstance(spec, dict):
        defaults = dict(DEFAULT_INSERT_DEFAULTS)
        defaults.update(spec.get("defaults", {}) or {})
        markers = spec.get("markers", [])
        if not isinstance(markers, list):
            raise TypeError("'markers' must be a list")
    else:
        raise TypeError(f"spec must be dict or list (got {type(spec).__name__})")

    return defaults, markers


def _resolve_method(marker: Dict[str, Any], default_method: str) -> str:
    """method 결정. 명시되어 있으면 그대로, 없으면 키 존재로 추론."""
    if "method" in marker:
        m = str(marker["method"]).lower()
        if m not in ("aux", "stim"):
            raise ValueError(f"Unknown method: {m!r}")
        return m
    if "code" in marker and "name" not in marker:
        return "aux"
    if "name" in marker and "code" not in marker:
        return "stim"
    return str(default_method).lower()


def _read_onsets_from_csv(
    marker: Dict[str, Any], method: str,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    """CSV 에서 onset (+ 선택적으로 code/name/duration) 추출."""
    if pd is None:
        raise ImportError(
            "pandas is required for CSV-based markers. pip install pandas"
        )

    csv_path = marker["csv"]
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    has_header = marker.get("has_header", True)
    df = pd.read_csv(csv_path, header=0 if has_header else None)

    row_start = int(marker["row_start"])
    row_end = int(marker["row_end"])
    offset = 1 if has_header else 0
    py_start = (row_start - 1) - offset
    py_end = (row_end - 1) - offset

    if py_start < 0 or py_end < py_start:
        raise ValueError(
            f"Invalid row range: row_start={row_start}, row_end={row_end} "
            f"(has_header={has_header})"
        )
    py_end = min(py_end, len(df) - 1)
    sub = df.iloc[py_start:py_end + 1]

    def _resolve_col(col):
        if isinstance(col, int):
            return df.columns[col]
        if isinstance(col, str):
            if col in df.columns:
                return col
            try:
                return df.columns[_excel_col_to_index(col)]
            except Exception:
                pass
        raise KeyError(f"Cannot resolve column: {col!r}")

    onset_col = _resolve_col(marker["onset_column"])
    onsets = pd.to_numeric(sub[onset_col], errors="coerce").to_numpy()
    valid = ~np.isnan(onsets)
    onsets = onsets[valid]

    codes = names = durations = None
    if method == "aux" and "code_column" in marker:
        codes = pd.to_numeric(
            sub[_resolve_col(marker["code_column"])], errors="coerce"
        ).to_numpy()[valid]
    if method == "stim" and "name_column" in marker:
        names = np.array([
            _format_marker_name(v)
            for v in sub[_resolve_col(marker["name_column"])].to_numpy()[valid]
        ])
    if method == "stim" and "duration_column" in marker:
        durations = pd.to_numeric(
            sub[_resolve_col(marker["duration_column"])], errors="coerce"
        ).fillna(0.0).to_numpy()[valid]

    return onsets, codes, names, durations


# ---- stim 그룹 작성 헬퍼 -------------------------------------------------
def _next_stim_index(nirs_grp: h5py.Group) -> int:
    used = set()
    for k in nirs_grp.keys():
        if k.lower().startswith("stim") and k[4:].isdigit():
            used.add(int(k[4:]))
    n = 1
    while n in used:
        n += 1
    return n


def _find_stim_group_by_name(nirs_grp: h5py.Group, name: str) -> Optional[str]:
    for k in nirs_grp.keys():
        if not k.lower().startswith("stim"):
            continue
        g = nirs_grp[k]
        if not isinstance(g, h5py.Group) or "name" not in g:
            continue
        if _decode_bytes(g["name"][()]) == name:
            return k
    return None


def _delete_all_stim_groups(nirs_grp: h5py.Group) -> int:
    n = 0
    for k in list(nirs_grp.keys()):
        if k.lower().startswith("stim"):
            del nirs_grp[k]
            n += 1
    return n


def _write_stim_group(
    nirs_grp: h5py.Group, name: str,
    onsets_sec: np.ndarray, durations: np.ndarray, amplitudes: np.ndarray,
    merge_same_name: bool,
) -> Tuple[str, int]:
    new_block = np.column_stack([
        onsets_sec.astype(np.float64),
        durations.astype(np.float64),
        amplitudes.astype(np.float64),
    ])

    existing = _find_stim_group_by_name(nirs_grp, name) if merge_same_name else None
    if existing is not None:
        stim_grp = nirs_grp[existing]
        if "data" in stim_grp:
            old = np.asarray(stim_grp["data"][()]).reshape(-1, 3)
            combined = np.vstack([old, new_block])
            del stim_grp["data"]
        else:
            combined = new_block
        combined = combined[np.argsort(combined[:, 0], kind="stable")]
        stim_grp.create_dataset("data", data=combined.astype(np.float64))
        return existing, new_block.shape[0]

    key = f"stim{_next_stim_index(nirs_grp)}"
    g = nirs_grp.create_group(key)
    g.create_dataset(
        "name",
        data=np.array(name, dtype=h5py.string_dtype(encoding="utf-8")),
    )
    g.create_dataset("data", data=new_block.astype(np.float64))
    g.create_dataset(
        "dataLabels",
        data=np.array(["onset", "duration", "amplitude"],
                      dtype=h5py.string_dtype(encoding="utf-8")),
    )
    return key, new_block.shape[0]


# ---- aux 채널 작성 헬퍼 --------------------------------------------------
def _next_aux_index(nirs_grp: h5py.Group) -> int:
    used = set()
    for k in nirs_grp.keys():
        if k.lower().startswith("aux") and k[3:].isdigit():
            used.add(int(k[3:]))
    n = 1
    while n in used:
        n += 1
    return n


def _write_aux_markers(
    nirs_grp: h5py.Group,
    time_arr: np.ndarray,
    onsets_sec: np.ndarray,
    codes: np.ndarray,
    aux_target: str,
    aux_name: Optional[str],
) -> Tuple[str, int, int]:
    """aux 채널에 시점 마커(펄스) 박기. 반환: (aux_key, n_inserted, n_dropped)."""
    in_range = (onsets_sec >= time_arr.min()) & (onsets_sec <= time_arr.max())
    n_dropped = int((~in_range).sum())
    onsets_sec = onsets_sec[in_range]
    codes = codes[in_range]

    if aux_target == "new":
        aux_idx = _next_aux_index(nirs_grp)
        aux_key = f"aux{aux_idx}"
        aux_grp = nirs_grp.create_group(aux_key)
        series = np.zeros(time_arr.size, dtype=np.float64)
        aux_grp.create_dataset("dataTimeSeries", data=series)
        aux_grp.create_dataset("time", data=time_arr.astype(np.float64))
        final_name = aux_name or f"marker_{aux_idx}"
        aux_grp.create_dataset(
            "name",
            data=np.array(final_name, dtype=h5py.string_dtype(encoding="utf-8")),
        )
        aux_grp.create_dataset(
            "dataUnit",
            data=np.array("marker", dtype=h5py.string_dtype(encoding="utf-8")),
        )
    else:
        if aux_target not in nirs_grp:
            raise KeyError(f"aux group not found: {aux_target}")
        aux_grp = nirs_grp[aux_target]
        aux_key = aux_target
        if "dataTimeSeries" not in aux_grp:
            raise RuntimeError(f"{aux_target} has no dataTimeSeries")

    if onsets_sec.size == 0:
        return aux_key, 0, n_dropped

    ds = aux_grp["dataTimeSeries"]
    arr = np.asarray(ds[()]).astype(np.float64).copy()
    arr_view = arr[:, 0] if (arr.ndim == 2 and arr.shape[1] == 1) else arr

    idxs = _onsets_to_indices(onsets_sec, time_arr)
    for i, c in zip(idxs, codes):
        if 0 <= i < arr_view.size:
            arr_view[i] = c

    if arr.ndim == 2:
        arr[:, 0] = arr_view
    ds[...] = arr.astype(ds.dtype if ds.dtype.kind == "f" else np.float64)
    return aux_key, int(onsets_sec.size), n_dropped


# ---- 단일 marker_spec 적용 ----------------------------------------------
def _apply_one_marker_spec(
    h5: h5py.File,
    marker: Dict[str, Any],
    defaults: Dict[str, Any],
    report: EditReport,
    spec_index: int,
) -> None:
    """marker_spec 1개를 받아서 SNIRF 에 적용. 실패 시 report 에 사유 기록."""

    def _get(key, fallback=None):
        return marker[key] if key in marker else defaults.get(key, fallback)

    try:
        method = _resolve_method(marker, defaults.get("method", "aux"))
        unit = _get("unit", "seconds")
        mode = _get("mode", "append")
        nirs_key = _get("nirs_key", "nirs")
        sampling_rate = _get("sampling_rate", None)

        # --- onset 추출 ---
        if "csv" in marker:
            onsets_arr, csv_codes, csv_names, csv_durations = \
                _read_onsets_from_csv(marker, method)
        elif "onsets" in marker:
            onsets_arr = np.asarray(list(marker["onsets"]),
                                    dtype=np.float64).ravel()
            csv_codes = csv_names = csv_durations = None
        else:
            raise ValueError("marker spec must have either 'onsets' or 'csv'")

        # --- onset_offset 적용 (단위 변환 전, 같은 단위에서 더하기) ---
        # 예) NIRSIT 이 자극 프로그램보다 30초 먼저 시작했다면 onset_offset=30
        #     (unit="seconds" 일 때). unit 이 ms 면 offset 도 ms 로 줘야 함.
        onset_offset = _get("onset_offset", 0)
        if onset_offset:
            onsets_arr = onsets_arr + float(onset_offset)

        if onsets_arr.size == 0:
            report.code_changes[f"[spec#{spec_index}] no valid onsets"] = 0
            return

        target_key, nirs_grp = _find_target_nirs_group(h5, nirs_key)

        fs = sampling_rate
        if str(unit).lower() in ("sample", "samples", "idx", "index") and fs is None:
            fs = _get_sampling_rate(h5)
        onsets_sec = _convert_to_seconds(onsets_arr, unit, fs)

        # ============================================================
        # method = "aux"  (NIRSIT 등에 적합, 시점 펄스로 박힘)
        # ============================================================
        if method == "aux":
            time_arr = _get_nirs_time_array(nirs_grp)
            if time_arr is None:
                raise RuntimeError("Cannot find /nirs*/data*/time to build axis.")

            if csv_codes is not None:
                codes = csv_codes.astype(np.float64)
                if np.isnan(codes).any() and "code" in marker:
                    codes[np.isnan(codes)] = float(marker["code"])
                codes = np.nan_to_num(codes, nan=0.0)
            else:
                code_val = marker.get("code")
                if code_val is None:
                    raise ValueError(
                        "method='aux' requires 'code' (or 'code_column' in CSV)."
                    )
                if hasattr(code_val, "__len__") and not isinstance(code_val, str):
                    codes = np.asarray(list(code_val), dtype=np.float64).ravel()
                    if codes.size != onsets_arr.size:
                        raise ValueError(
                            f"code list length {codes.size} != onsets length "
                            f"{onsets_arr.size}"
                        )
                else:
                    codes = np.full(onsets_arr.size, float(code_val))

            aux_target = marker.get("aux_target", defaults.get("aux_target", "new"))
            aux_name = marker.get("aux_name", defaults.get("aux_name"))

            aux_key, n_inserted, n_dropped = _write_aux_markers(
                nirs_grp, time_arr, onsets_sec, codes, aux_target, aux_name,
            )
            label = (
                f"[spec#{spec_index}] aux: {n_inserted} marker(s) into "
                f"/{target_key}/{aux_key}"
            )
            report.code_changes[label] = n_inserted
            if n_dropped:
                report.code_changes[
                    f"[spec#{spec_index}] dropped {n_dropped} onset(s) outside range"
                ] = n_dropped
            report.aux_channels_scanned += 1

        # ============================================================
        # method = "stim"  (표준 SNIRF, 기본은 시점 마커: duration=0)
        # ============================================================
        else:
            if csv_names is not None:
                names_arr = csv_names
            else:
                name_val = marker.get("name", marker.get("code"))
                if name_val is None:
                    raise ValueError("method='stim' requires 'name' (or 'code').")
                names_arr = np.array(
                    [_format_marker_name(name_val)] * onsets_arr.size
                )

            # duration 기본 0  ── 시점 마커
            if csv_durations is not None:
                durations = csv_durations.astype(np.float64)
            else:
                d = marker.get("duration", 0.0)
                if hasattr(d, "__len__") and not isinstance(d, str):
                    durations = np.asarray(list(d), dtype=np.float64).ravel()
                    if durations.size != onsets_arr.size:
                        raise ValueError("duration list length mismatch")
                else:
                    durations = np.full(onsets_arr.size, float(d))

            a = marker.get("amplitude", 1.0)
            if hasattr(a, "__len__") and not isinstance(a, str):
                amplitudes = np.asarray(list(a), dtype=np.float64).ravel()
                if amplitudes.size != onsets_arr.size:
                    raise ValueError("amplitude list length mismatch")
            else:
                amplitudes = np.full(onsets_arr.size, float(a))

            if mode == "replace":
                removed = _delete_all_stim_groups(nirs_grp)
                if removed:
                    report.name_changes[
                        f"[spec#{spec_index}] removed {removed} existing stim group(s)"
                    ] = removed

            unique_names = np.unique(names_arr)
            for nm in unique_names:
                sel = names_arr == nm
                grp_key, n_inserted = _write_stim_group(
                    nirs_grp, str(nm),
                    onsets_sec[sel], durations[sel], amplitudes[sel],
                    merge_same_name=(mode == "append"),
                )
                label = (
                    f"[spec#{spec_index}] stim '{nm}': {n_inserted} marker(s) "
                    f"into /{target_key}/{grp_key} (duration default=0)"
                )
                report.name_changes[label] = n_inserted
            report.stim_groups_scanned += len(unique_names)

    except Exception as e:
        msg = f"[spec#{spec_index}] FAILED: {type(e).__name__}: {e}"
        report.code_changes[msg] = 0


def insert_one_snirf(
    src_path: str,
    defaults: Dict[str, Any],
    markers: List[Dict[str, Any]],
    in_place: bool = False,
    output_dir: Optional[str] = None,
    suffix: str = "_with_markers",
) -> EditReport:
    """단일 .snirf 파일에 spec 의 모든 마커를 삽입."""
    output_path = resolve_output_path(src_path, in_place, output_dir, suffix)
    report = EditReport(file_path=src_path, output_path=output_path)

    if not in_place and os.path.abspath(src_path) != os.path.abspath(output_path):
        shutil.copy2(src_path, output_path)

    try:
        with h5py.File(output_path, "r+") as h5:
            for i, marker in enumerate(markers, start=1):
                if not isinstance(marker, dict):
                    raise TypeError(f"marker #{i} is not a dict")
                _apply_one_marker_spec(h5, marker, defaults, report, spec_index=i)
    except Exception as e:
        report.skipped_reason = f"{type(e).__name__}: {e}"

    return report


def insert_snirf(
    input_path: str,
    spec: Union[str, Dict, List, None],
    in_place: bool = False,
    output_dir: Optional[str] = None,
    suffix: str = "_with_markers",
    recursive: bool = False,
    verbose: bool = True,
) -> List[EditReport]:
    """
    파일/폴더 경로를 받아 spec 에 정의된 마커들을 일괄 삽입.

    edit_snirf 와 시그니처가 동일하며 'mapping' 대신 'spec' 을 받습니다.

    Parameters
    ----------
    spec : dict | list | str(JSON 경로) | None
        - list 면 그대로 markers 로 사용
        - dict 면 'defaults' + 'markers' 구조
        - str 이면 JSON 파일에서 로드
        자세한 형식은 파일 상단의 docstring 참조.
    """
    defaults, markers = load_spec(spec)
    files = collect_snirf_files(input_path, recursive=recursive)

    if verbose:
        print(f"[insert_snirf] target: {input_path}")
        print(f"[insert_snirf] found {len(files)} .snirf file(s)")
        print(f"[insert_snirf] {len(markers)} marker spec(s) to apply per file")
        print(f"[insert_snirf] defaults: {defaults}")
        print("-" * 70)

    reports = []
    for i, f in enumerate(files, 1):
        if verbose:
            print(f"[{i}/{len(files)}] {f}")
        r = insert_one_snirf(f, defaults, markers, in_place, output_dir, suffix)
        reports.append(r)
        if verbose:
            _print_report(r, indent="    ")

    if verbose:
        _print_summary(reports, label="insert_snirf")
    return reports


# ===========================================================================
# 로그 출력
# ===========================================================================
def _print_report(report: EditReport, indent: str = "") -> None:
    if report.skipped_reason:
        print(f"{indent}SKIPPED: {report.skipped_reason}")
        return
    print(f"{indent}-> saved to: {report.output_path}")
    if report.stim_groups_scanned or report.aux_channels_scanned:
        print(f"{indent}   stim groups touched : {report.stim_groups_scanned}")
        print(f"{indent}   aux channels touched: {report.aux_channels_scanned}")
    print(f"{indent}   total operations    : {report.total_changes}")

    for k, v in report.name_changes.items():
        print(f"{indent}     {k}: {v}")
    for k, v in report.code_changes.items():
        print(f"{indent}     {k}: {v}")

    if not report.name_changes and not report.code_changes:
        print(f"{indent}   (no changes — file unchanged)")


def _print_summary(reports: List[EditReport], label: str = "snirf") -> None:
    n_ok = sum(1 for r in reports if r.skipped_reason is None)
    n_fail = len(reports) - n_ok
    total = sum(r.total_changes for r in reports)
    print("=" * 70)
    print(f"[{label}] processed: {n_ok}/{len(reports)} files OK"
          + (f", {n_fail} failed" if n_fail else ""))
    print(f"[{label}] total operations across all files: {total}")


# ===========================================================================
# CLI
# ---------------------------------------------------------------------------
#   -m / --mapping : 마커 변경 (edit_snirf)
#   -s / --spec    : 마커 삽입 (insert_snirf)
# 둘을 동시에 주면 edit → insert 순으로 적용.
# ===========================================================================
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="snirf_marker_editor",
        description="SNIRF 마커를 일괄 변경(edit) 또는 삽입(insert)합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python snirf_marker_editor.py -i ./data -m mapping.json --recursive\n"
            "  python snirf_marker_editor.py -i ./data -s spec.json --recursive\n"
            "  python snirf_marker_editor.py -i ./data -m mapping.json -s spec.json\n"
        ),
    )
    p.add_argument("-i", "--input", required=True,
                   help="입력 .snirf 파일 또는 폴더 경로.")
    p.add_argument("-m", "--mapping",
                   help="마커 변경용 JSON 파일 경로.")
    p.add_argument("--mapping-str",
                   help="마커 변경용 인라인 JSON 문자열.")
    p.add_argument("-s", "--spec",
                   help="마커 삽입용 JSON 파일 경로.")
    p.add_argument("--spec-str",
                   help="마커 삽입용 인라인 JSON 문자열.")
    p.add_argument("--in-place", action="store_true",
                   help="원본 파일을 직접 수정. 기본은 복사본 생성.")
    p.add_argument("-o", "--output-dir", default=None,
                   help="결과 폴더(--in-place 가 아닐 때).")
    p.add_argument("--edit-suffix", default="_edited",
                   help="edit 결과 접미사 (기본: _edited).")
    p.add_argument("--insert-suffix", default="_with_markers",
                   help="insert 결과 접미사 (기본: _with_markers).")
    p.add_argument("--recursive", action="store_true",
                   help="폴더 입력 시 하위 폴더까지 탐색.")
    p.add_argument("--quiet", action="store_true",
                   help="진행 로그 끄기.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    verbose = not args.quiet

    mapping = None
    if args.mapping_str is not None:
        try:
            mapping = json.loads(args.mapping_str)
        except json.JSONDecodeError as e:
            print(f"--mapping-str invalid JSON: {e}", file=sys.stderr)
            return 2
    elif args.mapping is not None:
        mapping = args.mapping

    spec = None
    if args.spec_str is not None:
        try:
            spec = json.loads(args.spec_str)
        except json.JSONDecodeError as e:
            print(f"--spec-str invalid JSON: {e}", file=sys.stderr)
            return 2
    elif args.spec is not None:
        spec = args.spec

    if mapping is None and spec is None:
        print("ERROR: provide at least one of --mapping/-m or --spec/-s",
              file=sys.stderr)
        return 2

    all_reports: List[EditReport] = []

    if mapping is not None:
        reports = edit_snirf(
            input_path=args.input,
            mapping=mapping,
            in_place=args.in_place,
            output_dir=args.output_dir,
            suffix=args.edit_suffix,
            recursive=args.recursive,
            verbose=verbose,
        )
        all_reports.extend(reports)

    if spec is not None:
        reports = insert_snirf(
            input_path=args.input,
            spec=spec,
            in_place=args.in_place,
            output_dir=args.output_dir,
            suffix=args.insert_suffix,
            recursive=args.recursive,
            verbose=verbose,
        )
        all_reports.extend(reports)

    if any(r.skipped_reason for r in all_reports):
        return 1
    return 0


# ===========================================================================
# 사용 예시
# ===========================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main())

    print(__doc__)
    print()
    print("아래는 함수 형태로 호출하는 데모 코드입니다 (실행되지는 않습니다).")
    print()
    demo = r'''
# =====================================================================
# [A] 마커 변경 - edit_snirf
# =====================================================================
from snirf_marker_editor import edit_snirf

# 기존 마커의 코드/이름 변경. 0 으로 매핑하면 사실상 마커 삭제.
edit_snirf(
    input_path = r"C:\data\snirf_folder",
    mapping    = {
        "TrialStart": "Trial_Start",   # stim 의 name 변경
        "2001": 5001,                   # aux 의 숫자 코드 변경
        "2002": 0,                      # aux 마커 삭제
    },
    suffix     = "_remapped",
    recursive  = True,
)


# =====================================================================
# [B] 마커 삽입 - insert_snirf
# =====================================================================
from snirf_marker_editor import insert_snirf

# ---------------------------------------------------------------------
# 중요: NIRSIT QUEST 같은 도구는 보통 /nirs/aux1 채널에서만 마커를 읽음.
# 새 aux 채널을 만들면(기본값) NIRSIT 이 인식하지 못하므로,
# "aux_target": "aux1" 을 지정해 기존 마커 채널에 직접 박아야 함.
#
# ⚠ 주의: aux1 에 기존 마커가 있는 경우, 같은 시점에 새 코드를 박으면
#         기존 마커가 덮어쓰임. 필요시 edit_snirf 로 먼저 비우세요.
# ---------------------------------------------------------------------


# ---------------------------------------------------------------------
# (예시 1) ★ 기본 사용: NIRSIT 호환 - aux1 에 직접 박기
# ---------------------------------------------------------------------
insert_snirf(
    input_path = r"C:\data\subject01.snirf",
    spec = {
        "defaults": {
            "method": "aux",
            "aux_target": "aux1",   # ← NIRSIT 이 보는 채널
            "unit": "seconds",
        },
        "markers": [
            {"code": 1, "onsets": [5.0, 15.0, 30.0]},
            {"code": 2, "onsets": [45.0, 60.0]},
        ],
    },
)


# ---------------------------------------------------------------------
# (예시 2) 기존 마커 다 지우고 새로 박는 워크플로우 (2단계)
# ---------------------------------------------------------------------
src = r"C:\data\subject01.snirf"

# 1단계: aux1 의 기존 마커 코드를 모두 0 으로 (사실상 비우기).
edit_snirf(
    input_path = src,
    mapping    = {"2001": 0, "2002": 0},   # 실제 파일에 있는 코드들로
    suffix     = "_cleared",
)

# 2단계: 깨끗해진 파일의 aux1 에 새 마커 박기.
insert_snirf(
    input_path = src.replace(".snirf", "_cleared.snirf"),
    spec = {
        "defaults": {"method": "aux", "aux_target": "aux1"},
        "markers": [
            {"code": 1, "onsets": [5.0, 15.0, 30.0]},
            {"code": 2, "onsets": [45.0, 60.0]},
        ],
    },
)


# ---------------------------------------------------------------------
# (예시 3) CSV 의 D열(onset) + E열(code) 5~10행에서 읽기
# ---------------------------------------------------------------------
insert_snirf(
    input_path = r"C:\data\subject01.snirf",
    spec = {
        "defaults": {"method": "aux", "aux_target": "aux1"},
        "markers": [
            {
                "csv": r"C:\data\events.csv",
                "onset_column": "D",   # 엑셀 알파벳 또는 "onset" 또는 3
                "code_column":  "E",
                "row_start": 5,         # 엑셀 1-based, 헤더 포함 행 번호
                "row_end":   10,
                "code": 0,             # E열에 NaN 있을 때의 기본 코드
            },
        ],
    },
)


# ---------------------------------------------------------------------
# (예시 4) ★ 시간 offset - NIRSIT 을 자극 프로그램보다 먼저 켰을 때
# ---------------------------------------------------------------------
# 실험 흐름:
#   1. NIRSIT 녹화 시작 (t=0)
#   2. 30초 후, 자극 프로그램 시작
#   3. 자극 프로그램이 기록한 onset 은 "자극 시작 기준" 시간임
#      예) CSV 의 onset = [0, 5, 10, ...]  ← 자극 프로그램 기준
#      실제 SNIRF 시간축에서는 [30, 35, 40, ...] 위치
#
# onset_offset 으로 그 시간 차이를 한 번에 더해줄 수 있음:
insert_snirf(
    input_path = r"C:\data\subject01.snirf",
    spec = {
        "defaults": {
            "method": "aux",
            "aux_target": "aux1",
            "unit": "seconds",
            "onset_offset": 30,     # ← NIRSIT 이 30초 먼저 시작했다는 의미
        },
        "markers": [
            # 아래 onset 들은 자극 프로그램 기준. +30 되어 SNIRF 에 박힘.
            {"code": 1, "onsets": [0.0, 10.0, 20.0]},   # 실제로는 30, 40, 50초에 박힘
            {"code": 2, "csv": r"C:\data\events.csv",
             "onset_column": "D", "code": "11", # code는 지정하고자 하는 마커 번호
             "row_start": 5, "row_end": 10},
        ],
    },
)
# 시간축 밖으로 나가는 onset 은 자동으로 제외되고 로그에 표시됩니다.
# 음수 offset 도 가능 (자극 프로그램이 NIRSIT 보다 먼저 시작한 경우).


# ---------------------------------------------------------------------
# (예시 5) 폴더 일괄 처리 + JSON 으로 spec 분리해 관리
# ---------------------------------------------------------------------
# spec.json 예시:
# {
#   "defaults": {
#     "method": "aux", "aux_target": "aux1",
#     "unit": "seconds", "onset_offset": 30
#   },
#   "markers": [
#     {"code": 1, "onsets": [0.0, 10.0, 20.0]},
#     {"code": 2, "csv": "events.csv",
#      "onset_column": "D", "row_start": 5, "row_end": 10, "code_column": "E"}
#   ]
# }
insert_snirf(
    input_path = r"C:\data\snirf_folder",
    spec       = r"C:\data\spec.json",
    recursive  = True,
)


# ---------------------------------------------------------------------
# (예시 6) 새 aux 채널에 박기 (NIRSIT 외 도구용 / 기존 마커와 분리)
# ---------------------------------------------------------------------
insert_snirf(
    input_path = r"C:\data\subject01.snirf",
    spec = [
        # aux_target 생략 시 새 aux 채널(aux<다음번호>)이 자동 생성됨.
        {"code": 1, "onsets": [5.0, 15.0, 30.0], "aux_name": "task_start"},
        {"code": 2, "onsets": [45.0, 60.0],      "aux_name": "task_end"},
    ],
)


# ---------------------------------------------------------------------
# (예시 7) stim 그룹에 시점 마커 (표준 SNIRF 분석 도구용)
# ---------------------------------------------------------------------
insert_snirf(
    input_path = r"C:\data\subject01.snirf",
    spec = [
        {"method": "stim", "name": "Cue",   "onsets": [5.0, 15.0]},
        {"method": "stim", "name": 2001,    "onsets": [25.0, 35.0]},   # 숫자 name 도 OK
        # duration 기본 0 = 시점 마커. 구간 마커가 필요할 때만 명시.
        {"method": "stim", "name": "Block", "onsets": [40.0], "duration": 10.0},
    ],
)


# =====================================================================
# CLI 실행 (스크립트 직접 실행)
# =====================================================================
#   python snirf_marker_editor.py -i ./data -m mapping.json --recursive
#   python snirf_marker_editor.py -i ./data -s spec.json --recursive
#   python snirf_marker_editor.py -i ./data -m mapping.json -s spec.json
'''
    print(demo)