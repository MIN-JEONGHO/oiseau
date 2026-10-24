# -*- coding: utf-8 -*-
"""
제재정보 raw data -> 부처별/연도별 제재처분 집계 파이프라인

'제재정보분석.workflow' 의 노드 로직을 pandas 로 구현한 모듈.

  [입력]  NTIS 제재정보 rawdata (xlsx) — 헤더 행 자동 탐지
     |
  [1] 데이터 변환   : 컬럼 선택 -> 과제수행연도 필터 -> 과제명 공백제거 -> 연도 추출
  [2] 데이터 전처리 : 부처명 통일/보완 -> 과제 그룹 결측 보완 -> 시작일 결측 행 제거
  [3] 기간 분석     : 과제 단위 제재유형 판정(①②③) + 총연구기간 연도 전개
  [4] 집계          : 부처 x 항목 x 연도 교차표 (합계 열은 계속과제 1건 처리)

10만 행 규모를 전제로 모든 단계를 벡터화했고, 엑셀 읽기는 calamine(있으면) ->
openpyxl 순으로 시도합니다.
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 컬럼 사전
# ---------------------------------------------------------------------------

#: 없으면 집계가 불가능한 컬럼
REQUIRED_COLUMNS = {
    "과제수행연도": ["과제수행연도", "수행연도", "과제수행년도"],
    "과제명": ["과제명", "연구과제명", "원인과제명"],
    "총연구기간시작일": ["총연구기간시작일", "연구기간시작일", "총연구시작일"],
    "총연구기간종료일": ["총연구기간종료일", "연구기간종료일", "총연구종료일"],
    "제재유형구분": ["제재유형구분", "제재유형", "제재구분"],
}

#: 있으면 쓰고 없으면 비워두는 컬럼
OPTIONAL_COLUMNS = {
    "과제번호": ["과제번호", "과제고유번호", "세부과제번호"],
    "소관부처": ["소관부처", "소관 부처"],
    "부처명": ["부처명", "부처", "중앙행정기관", "소관기관"],
    "처분연도": ["처분연도", "처분년도", "제재처분연도"],
    "처분일": ["처분일", "제재처분일"],
    "제재ID": ["제재ID", "제재아이디", "제재정보ID"],
    "제재고유번호": ["제재고유번호"],
    "제재대상": ["제재대상", "제재대상구분"],
    "사업명": ["사업명"],
}

ALL_COLUMNS = {**REQUIRED_COLUMNS, **OPTIONAL_COLUMNS}

#: 판정 코드 -> 양식상 표기
JUDGMENT_LABELS = {
    "①": "① 참여제한 및 제재부가금",
    "②": "② 참여제한만 처분",
    "③": "③ 제재부가금만 처분",
}
JUDGMENT_ORDER = ["①", "②", "③"]

# ---------------------------------------------------------------------------
# 소관부처 표기 통일 (구칭 -> 현재 명칭)
#
# rawdata 의 '소관부처' 열은 NTIS 가 이미 현재 명칭으로 정리해 주므로 이 표는
# 대부분 '부처명'(처분 당시 명칭) 열로 넘어갈 때만 작동합니다.
# 실행 중 실제로 적용된 치환은 화면 각주와 콘솔에 건수와 함께 표시됩니다.
#
# 필요하면 이 표를 직접 고쳐 쓰십시오. 아래 두 그룹으로 나눠 두었습니다.
# ---------------------------------------------------------------------------

#: 사용자가 확인한 매핑
MINISTRY_RENAME_CONFIRMED = {
    "미래창조과학부": "과학기술정보통신부",
    "환경부": "기후에너지환경부",
    "산업통상자원부": "산업통상부",
}

#: 정부조직 개편 이력에서 유추한 매핑 (검토 후 쓰십시오)
#: 부처가 둘로 쪼개진 경우는 R&D 소관을 이어받은 쪽으로 보냈습니다.
#:   교육과학기술부 -> 교육부 / 미래창조과학부 (R&D 는 후자)
#:   국토해양부     -> 국토교통부 / 해양수산부
#:   농림수산식품부 -> 농림축산식품부 / 해양수산부
#: 실제 데이터에서 해양수산 과제가 잘못 분류되면 해당 항목을 지우거나 바꾸십시오.
MINISTRY_RENAME_INFERRED = {
    "과학기술부": "과학기술정보통신부",
    "정보통신부": "과학기술정보통신부",
    "교육과학기술부": "과학기술정보통신부",
    "교육인적자원부": "교육부",
    "산업자원부": "산업통상자원부",
    "지식경제부": "산업통상자원부",
    "농림부": "농림축산식품부",
    "농림수산식품부": "농림축산식품부",
    "건설교통부": "국토교통부",
    "국토해양부": "국토교통부",
    "보건복지가족부": "보건복지부",
    "행정자치부": "행정안전부",
    "안전행정부": "행정안전부",
    "국민안전처": "행정안전부",
    "중소기업청": "중소벤처기업부",
    "문화관광부": "문화체육관광부",
}

def resolve_rename_chains(table: dict) -> dict:
    """A→B, B→C 가 함께 있으면 A→C 까지 이어서 풀어 준다.

    pandas 의 Series.replace(dict) 는 한 번만 치환하므로 표에 연쇄가 있으면
    중간 이름에서 멈춘다. 예를 들어 '지식경제부→산업통상자원부' 와
    '산업통상자원부→산업통상부' 가 함께 있을 때 지식경제부가 산업통상자원부에
    남아 같은 부처가 두 줄로 갈라진다. 정부조직 개편은 여러 번 겹치므로
    표에는 실제 개편 단계를 그대로 적고, 최종 이름은 여기서 계산한다.
    """
    out = {}
    for src in table:
        seen = {src}
        dst = table[src]
        while dst in table and dst not in seen:   # 순환은 마지막 이름에서 멈춘다
            seen.add(dst)
            dst = table[dst]
        if dst != src:
            out[src] = dst
    return out


MINISTRY_RENAME = resolve_rename_chains(
    {**MINISTRY_RENAME_INFERRED, **MINISTRY_RENAME_CONFIRMED}
)

TOTAL_LABEL = "합 계"
UNASSIGNED = "(부처 미지정)"

#: 제재유형 판정에 쓰는 키워드
KW_LIMIT = "참여제한"
KW_FEE = "제재부가금"


@dataclass
class PipelineConfig:
    """파이프라인 실행 옵션."""

    sheet_name: str | int = "제재정보"
    header_row: int | None = None    # None -> 자동 탐지 (1-base)
    data_start_row: int | None = None
    min_task_year: int = 2017        # 과제수행연도 하한 (양식 각주 기준)
    year_start: int | None = None    # None -> 자동
    year_end: int | None = None      # None -> 자동
    year_end_cap: int | None = None  # None -> 올해로 자동 제한
    id_strategy: str = "번호우선"     # 번호우선 | 번호 | 과제명 | 번호+명
    ministry_column: str = "소관부처"  # 소관부처 | 부처명
    ministry_rename: dict = field(default_factory=lambda: dict(MINISTRY_RENAME))
    verbose: bool = True

    #: 실행 중 확정된 값 (읽기 전용 참고)
    resolved: dict = field(default_factory=dict)

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"(1[89]\d{2}|20\d{2}|21\d{2})")
_NORM_RE = re.compile(r"[\s\-_()·.]")


def _norm_key(s) -> str:
    return _NORM_RE.sub("", unicodedata.normalize("NFC", str(s)))


_ALIAS_LOOKUP = {
    _norm_key(a): std for std, aliases in ALL_COLUMNS.items() for a in aliases
}


def extract_year(value) -> float:
    """단일 값에서 4자리 연도 추출 (컬럼명·참조데이터용)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (pd.Timestamp, _dt.datetime, _dt.date)):
        return float(value.year)
    if isinstance(value, (int, np.integer)):
        v = int(value)
        if 1800 <= v <= 2200:
            return float(v)
        if 10000 <= v <= 80000:
            return float((pd.Timestamp("1899-12-30") + pd.Timedelta(days=v)).year)
        return np.nan
    if isinstance(value, (float, np.floating)):
        return extract_year(int(value))
    m = _YEAR_RE.search(str(value).strip())
    if m:
        return float(m.group(1))
    ts = pd.to_datetime(str(value), errors="coerce")
    return float(ts.year) if pd.notna(ts) else np.nan


def extract_year_series(s: pd.Series) -> pd.Series:
    """Series 전체에서 4자리 연도 추출 (벡터화)."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.year.astype("Float64").astype(float)

    if pd.api.types.is_numeric_dtype(s):
        v = pd.to_numeric(s, errors="coerce")
        out = v.where((v >= 1800) & (v <= 2200))
        serial = v.where((v >= 10000) & (v <= 80000))
        if serial.notna().any():
            conv = pd.Timestamp("1899-12-30") + pd.to_timedelta(serial, unit="D")
            out = out.fillna(conv.dt.year)
        return out.astype(float)

    txt = s.astype(str)
    got = txt.str.extract(_YEAR_RE, expand=False)
    out = pd.to_numeric(got, errors="coerce")
    miss = out.isna() & s.notna()
    if miss.any():  # 'YY/MM/DD' 등 4자리 연도가 없는 표기
        conv = pd.to_datetime(txt[miss], errors="coerce")
        out.loc[miss] = conv.dt.year
    return out.astype(float)


def strip_spaces(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", str(value)))


def _clean_text(s: pd.Series) -> pd.Series:
    return (
        s.astype("string")
        .fillna("")
        .str.strip()
        .replace({"nan": "", "None": "", "NaN": "", "-": ""})
    )


def _raw_ministry_labels(df: pd.DataFrame) -> set:
    """'소관부처' 없으면 '부처명'으로 대략 채운 부처 라벨 집합 (진단용, 정식 규칙은 preprocess 참고)."""
    a = df["소관부처"].astype("string").fillna("").str.strip() if "소관부처" in df else pd.Series([""] * len(df))
    b = df["부처명"].astype("string").fillna("").str.strip() if "부처명" in df else pd.Series([""] * len(df))
    return set(a.where(a.ne(""), b)) - {""}


def _warn_vanished_ministries(cfg: "PipelineConfig", before: set, after: set, reason: str) -> None:
    for m in sorted(before - after):
        cfg.log(f"  ! '{m}' 부처는 {reason} 결과에서 빠졌습니다")


# ---------------------------------------------------------------------------
# [0] 데이터 입력 — 헤더 행 자동 탐지
# ---------------------------------------------------------------------------

def _probe_rows(path: str, sheet, n: int = 15) -> list[tuple]:
    """파일 앞부분 n행만 싸게 읽는다 (10만 행 파일에서도 즉시).

    openpyxl 을 read_only 로 직접 열면 시트의 dimension 메타데이터를 그대로
    믿는데, 내보내기 도구에 따라 이 값이 실제 데이터 범위보다 작게(예:
    A1:A1) 잘못 기록된 xlsx 가 있다. 그런 파일은 openpyxl read_only 로는
    첫 행 이후를 전혀 못 읽어 헤더 자동 탐지가 항상 실패한다. pandas 는
    같은 파일에서도 전체 범위를 정상적으로 읽으므로 이쪽을 쓴다.
    """
    lower = str(path).lower()
    if lower.endswith((".csv", ".tsv", ".txt")):
        sep = "\t" if lower.endswith(".tsv") else ","
        df = pd.read_csv(path, sep=sep, header=None, nrows=n, dtype=object)
        return [tuple(r) for r in df.itertuples(index=False)]

    try:
        names = pd.ExcelFile(path).sheet_names
    except Exception:  # noqa: BLE001
        names = []
    name = sheet if isinstance(sheet, str) and sheet in names else (names[0] if names else 0)
    df = pd.read_excel(path, sheet_name=name, header=None, nrows=n)
    df = df.where(df.notna(), None)
    return [tuple(r) for r in df.itertuples(index=False)]


def detect_header_row(path: str, sheet, cfg: PipelineConfig) -> int:
    """알려진 컬럼명이 가장 많이 등장하는 행을 헤더로 본다. 1-base 반환."""
    rows = _probe_rows(path, sheet)
    best_i, best_score = 0, -1
    for i, row in enumerate(rows):
        score = sum(1 for c in row if c is not None and _norm_key(c) in _ALIAS_LOOKUP)
        if score > best_score:
            best_i, best_score = i, score
    if best_score < 3:
        cfg.log(f"  ! 헤더 행을 자동으로 찾지 못해 1행을 사용합니다 (일치 {best_score}개)")
        return 1
    if best_i > 0:
        cfg.log(f"  ! 헤더가 {best_i + 1}행에 있어 자동으로 맞췄습니다")
    return best_i + 1


def _read_excel_calamine_iter(path: str, sheet, header_idx: int, usecols) -> pd.DataFrame:
    """calamine 으로 행을 흘려 읽으면서 필요한 열만 담는다.

    pandas 의 read_excel 은 전체 시트를 먼저 메모리에 올린 뒤 열을 걸러내기 때문에
    94열 x 10만행에서 1.3GB 를 쓴다. 여기서는 읽는 즉시 걸러서 절반 이하로 줄인다.
    """
    from python_calamine import CalamineWorkbook

    wb = CalamineWorkbook.from_path(str(path))
    name = sheet if isinstance(sheet, str) and sheet in wb.sheet_names else wb.sheet_names[0]
    it = wb.get_sheet_by_name(name).iter_rows()

    header = None
    for i, row in enumerate(it):
        if i == header_idx:
            header = row
            break
    if header is None:
        raise ValueError("헤더 행을 읽을 수 없습니다.")

    keep = [i for i, h in enumerate(header) if h is not None and usecols(h)]
    if not keep:
        raise ValueError("필요한 컬럼을 찾을 수 없습니다.")
    names = [str(header[i]) for i in keep]
    cols: list[list] = [[] for _ in keep]

    for row in it:
        n = len(row)
        for j, i in enumerate(keep):
            cols[j].append(row[i] if i < n else None)

    return pd.DataFrame(dict(zip(names, cols)))


def _read_excel(path: str, sheet, header_idx: int, usecols) -> pd.DataFrame:
    """calamine(스트리밍) -> pandas+calamine -> openpyxl 순으로 시도."""
    errors = []
    try:
        return _read_excel_calamine_iter(path, sheet, header_idx, usecols)
    except Exception as e:  # noqa: BLE001
        errors.append(f"calamine-iter: {e}")
    for engine in ("calamine", None):
        try:
            kw = {} if engine is None else {"engine": engine}
            return pd.read_excel(
                path, sheet_name=sheet, header=header_idx, usecols=usecols, **kw
            )
        except Exception as e:  # noqa: BLE001, PERF203
            errors.append(f"{engine or 'openpyxl'}: {e}")
    raise RuntimeError("엑셀을 읽지 못했습니다.\n  " + "\n  ".join(errors))


def load_raw(path: str, cfg: PipelineConfig) -> pd.DataFrame:
    """제재정보 rawdata 를 읽어온다. 필요한 컬럼만 가져온다."""
    lower = str(path).lower()

    if cfg.header_row is None:
        cfg.header_row = detect_header_row(path, cfg.sheet_name, cfg)
    if cfg.data_start_row is None:
        cfg.data_start_row = cfg.header_row + 1
    header_idx = cfg.header_row - 1
    cfg.resolved["header_row"] = cfg.header_row

    def wanted(name) -> bool:
        return _norm_key(name) in _ALIAS_LOOKUP

    if lower.endswith((".csv", ".tsv", ".txt")):
        sep = "\t" if lower.endswith(".tsv") else ","
        df = pd.read_csv(path, sep=sep, header=header_idx, usecols=wanted, dtype=object)
    else:
        sheet = cfg.sheet_name
        try:
            names = pd.ExcelFile(path).sheet_names
            if isinstance(sheet, str) and sheet not in names:
                cfg.log(f"  ! 시트 '{sheet}' 없음 -> '{names[0]}' 사용")
                sheet = names[0]
                cfg.sheet_name = sheet
        except Exception:  # noqa: BLE001
            pass
        df = _read_excel(path, sheet, header_idx, wanted)

    skip = cfg.data_start_row - cfg.header_row - 1
    if skip > 0:
        df = df.iloc[skip:].reset_index(drop=True)

    df = df.loc[:, ~df.columns.duplicated()]
    cfg.log(f"[입력] {len(df):,}행 (필요 컬럼 {len(df.columns)}개, 헤더 {cfg.header_row}행)")
    return df


# ---------------------------------------------------------------------------
# [1] 데이터 변환
# ---------------------------------------------------------------------------

def resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """실제 컬럼명 -> 표준 컬럼명 매핑. 필수 컬럼이 없으면 예외."""
    lookup: dict[str, str] = {}
    for c in df.columns:
        std = _ALIAS_LOOKUP.get(_norm_key(c))
        if std and std not in lookup:
            lookup[std] = c

    missing = [k for k in REQUIRED_COLUMNS if k not in lookup]
    if missing:
        raise KeyError(
            "raw data 에서 다음 필수 컬럼을 찾을 수 없습니다: "
            + ", ".join(missing)
            + f"\n  읽어온 컬럼: {list(df.columns)}"
            + "\n  헤더 행 번호가 맞는지 확인해 주세요."
        )
    if "소관부처" not in lookup and "부처명" not in lookup:
        raise KeyError("raw data 에서 '소관부처' 또는 '부처명' 컬럼을 찾을 수 없습니다.")
    return lookup


def transform(df: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    """컬럼 선택 -> 과제수행연도 필터 -> 과제명 공백 제거 -> 연도 추출."""
    mapping = resolve_columns(df)
    out = pd.DataFrame(index=df.index)

    for std in ALL_COLUMNS:
        out[std] = df[mapping[std]] if std in mapping else pd.NA

    for col in ("총연구기간시작일", "총연구기간종료일", "처분연도", "과제수행연도"):
        out[col] = extract_year_series(out[col])
    if out["처분연도"].isna().all() and "처분일" in mapping:
        out["처분연도"] = extract_year_series(out["처분일"])

    before = len(out)
    before_ministries = _raw_ministry_labels(out)
    out = out[out["과제수행연도"].notna() & (out["과제수행연도"] >= cfg.min_task_year)]
    cfg.log(f"[변환] 과제수행연도 >= {cfg.min_task_year} 필터: {before:,} -> {len(out):,}행")
    if out.empty:
        raise ValueError(
            f"과제수행연도가 {cfg.min_task_year} 이상인 행이 없습니다. "
            "하한 값이나 헤더 행 설정을 확인해 주세요."
        )
    _warn_vanished_ministries(
        cfg, before_ministries, _raw_ministry_labels(out),
        f"과제수행연도가 모두 {cfg.min_task_year} 미만(또는 결측)이라",
    )

    for col in ("과제명", "과제번호"):
        out[col] = _clean_text(out[col]).str.replace(r"\s+", "", regex=True)
    for col in ("소관부처", "부처명", "제재유형구분", "제재ID", "제재고유번호", "제재대상", "사업명"):
        out[col] = _clean_text(out[col])

    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# [2] 데이터 전처리
# ---------------------------------------------------------------------------

def _build_key(out: pd.DataFrame, strategy: str) -> pd.Series:
    """과제 동일성 판정 키."""
    no, nm = out["과제번호"], out["과제명"]
    if strategy == "번호" and no.ne("").any():
        return no.where(no.ne(""), "명:" + nm)
    if strategy == "과제명":
        return nm
    if strategy == "번호+명":
        return no + "│" + nm
    # 번호우선 (기본): 과제번호가 있으면 그것, 없으면 과제명
    if no.ne("").any():
        return no.where(no.ne(""), "명:" + nm)
    return nm


def preprocess(df: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    """부처명 통일/보완 -> 과제 그룹 결측 보완 -> 시작일 결측 행 제거."""
    out = df.copy()

    # 1) 부처: 선택한 컬럼을 쓰고, 비어 있으면 다른 컬럼으로 보완
    primary = cfg.ministry_column if cfg.ministry_column in ("소관부처", "부처명") else "소관부처"
    backup = "부처명" if primary == "소관부처" else "소관부처"
    m = out[primary].where(out[primary].ne(""), out[backup])

    n_filled = int((out[primary].eq("") & m.ne("")).sum())
    if n_filled:
        cfg.log(f"  ! '{primary}'가 빈 행 {n_filled:,}건은 '{backup}'로 채웠습니다")

    # 실제로 적용된 구칭 치환만 건수와 함께 알린다
    hits = m[m.isin(cfg.ministry_rename)].value_counts()
    for old, n in hits.items():
        cfg.log(f"  ! 부처명 치환: {old} → {cfg.ministry_rename[old]} ({n:,}건)")
    cfg.resolved["ministry_renames"] = {
        str(k): [cfg.ministry_rename[k], int(v)] for k, v in hits.items()
    }

    out["_부처"] = m.replace(cfg.ministry_rename).replace("", UNASSIGNED)
    n_blank = int((m == "").sum())
    if n_blank:
        cfg.log(f"  ! 부처명이 빈 행 {n_blank:,}건은 '{UNASSIGNED}'로 분류했습니다")

    # 2) 과제 키
    out["_과제키"] = _build_key(out, cfg.id_strategy)
    cfg.resolved["id_strategy"] = cfg.id_strategy
    cfg.resolved["ministry_column"] = primary

    # 3) 과제 그룹 내 연구기간 결측 보완 (FillByGroup) — 벡터화
    for col in ("총연구기간시작일", "총연구기간종료일"):
        g = out.groupby("_과제키", sort=False)[col]
        out[col] = out[col].fillna(g.ffill()).fillna(
            out.groupby("_과제키", sort=False)[col].bfill()
        )

    # 4) 시작일이 여전히 비어 있으면 행 제거
    before = len(out)
    before_ministries = set(out["_부처"].unique()) - {UNASSIGNED}
    out = out[out["총연구기간시작일"].notna()]
    dropped = before - len(out)
    cfg.log(f"[전처리] 연구기간 시작일 결측 행 제거: {before:,} -> {len(out):,}행")
    if dropped:
        cfg.log(f"  ! 연구기간 시작일이 없어 제외한 행 {dropped:,}건")
    if out.empty:
        raise ValueError("총연구기간 시작일이 있는 행이 없습니다.")
    _warn_vanished_ministries(
        cfg, before_ministries, set(out["_부처"].unique()) - {UNASSIGNED},
        "모든 과제의 총연구기간 시작일이 결측(그룹 내 보완도 불가)이라",
    )

    out["총연구기간종료일"] = out["총연구기간종료일"].fillna(out["총연구기간시작일"])
    # 종료 < 시작 인 이상치는 시작일로 맞춘다
    bad = out["총연구기간종료일"] < out["총연구기간시작일"]
    if bad.any():
        cfg.log(f"  ! 종료연도가 시작연도보다 이른 행 {int(bad.sum()):,}건은 시작연도로 맞췄습니다")
        out.loc[bad, "총연구기간종료일"] = out.loc[bad, "총연구기간시작일"]

    for col in ("총연구기간시작일", "총연구기간종료일", "과제수행연도"):
        out[col] = out[col].astype(int)
    out["처분연도"] = out["처분연도"].astype("Int64")
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# [3] 기간 분석 + 제재유형 판정
# ---------------------------------------------------------------------------

#: 상세 시트의 제재ID 목록에 표시할 최대 개수
ID_LIST_CAP = 8


def _flag_labels(work: pd.DataFrame, key: str, col: str, labels: list[str],
                 index, contains: bool = False) -> np.ndarray:
    """값 종류가 적은 컬럼을 그룹별 불리언 max 로 모아 문자열로 조립 (벡터화)."""
    src = work[col]
    flags = pd.DataFrame(
        {
            lab: (src.str.contains(lab, na=False) if contains else src.eq(lab))
            for lab in labels
        },
        index=work.index,
    )
    flags[key] = work[key].to_numpy()
    got = flags.groupby(key, sort=False)[labels].max().reindex(index).to_numpy()
    arr = np.asarray(labels, dtype=object)
    return np.array([", ".join(arr[row.astype(bool)]) for row in got], dtype=object)


def _join_ids(work: pd.DataFrame, key: str, col: str, index) -> np.ndarray:
    """고유값이 많은 컬럼: 좁은 프레임에서 중복 제거 후 결합."""
    narrow = work.loc[work[col].ne(""), [key, col]].drop_duplicates()
    narrow = narrow.sort_values([key, col], kind="stable")
    n = narrow.groupby(key, sort=False)[col].size()
    joined = narrow.groupby(key, sort=False)[col].agg(
        lambda s: ", ".join(s.iloc[:ID_LIST_CAP])
    )
    over = n[n > ID_LIST_CAP]
    if len(over):
        joined.loc[over.index] = joined.loc[over.index] + over.map(
            lambda c: f" …(총 {c}건)"
        )
    return joined.reindex(index).fillna("").to_numpy()


def _range_text(lo: pd.Series, hi: pd.Series) -> np.ndarray:
    """연도 구간을 '2018~2020' / '2019' 로 표기."""
    a = lo.to_numpy()
    b = hi.to_numpy()
    return np.where(
        pd.isna(a), "",
        np.where(a == b, pd.Series(a).astype("Int64").astype(str),
                 pd.Series(a).astype("Int64").astype(str) + "~"
                 + pd.Series(b).astype("Int64").astype(str)),
    )


def analyze_periods(df: pd.DataFrame, cfg: PipelineConfig):
    """과제 단위 판정/연구기간 산출 + 연도 축 결정. (tasks, years, mask)"""
    work = df.assign(
        _lim=df["제재유형구분"].str.contains(KW_LIMIT, na=False),
        _fee=df["제재유형구분"].str.contains(KW_FEE, na=False),
        _m=df["_부처"].replace(UNASSIGNED, np.nan),
    )
    g = work.groupby("_과제키", sort=False)

    tasks = g.agg(
        과제번호=("과제번호", "first"),
        과제명=("과제명", "first"),
        사업명=("사업명", "first"),
        소관부처=("_m", "first"),
        총연구기간시작연도=("총연구기간시작일", "min"),
        총연구기간종료연도=("총연구기간종료일", "max"),
        _처분_최소=("처분연도", "min"),
        _처분_최대=("처분연도", "max"),
        _수행_최소=("과제수행연도", "min"),
        _수행_최대=("과제수행연도", "max"),
        레코드수=("제재유형구분", "size"),
        _lim=("_lim", "max"),
        _fee=("_fee", "max"),
    ).reset_index()
    tasks["소관부처"] = tasks["소관부처"].fillna(UNASSIGNED)

    idx = tasks["_과제키"]
    tasks["제재유형"] = _flag_labels(
        work, "_과제키", "제재유형구분", [KW_LIMIT, KW_FEE, "환수금"], idx, contains=True
    )
    tasks["제재대상"] = _flag_labels(work, "_과제키", "제재대상", ["기관", "인물"], idx)
    tasks["제재ID"] = _join_ids(work, "_과제키", "제재ID", idx)
    tasks["처분연도"] = _range_text(tasks.pop("_처분_최소"), tasks.pop("_처분_최대"))
    tasks["과제수행연도(원자료)"] = _range_text(
        tasks.pop("_수행_최소"), tasks.pop("_수행_최대")
    )

    # 판정
    code = np.where(
        tasks["_lim"] & tasks["_fee"], "①",
        np.where(tasks["_lim"], "②", np.where(tasks["_fee"], "③", None)),
    )
    tasks["_판정코드"] = pd.Series(code, index=tasks.index).replace({np.nan: None})
    tasks["판정"] = tasks["_판정코드"].map(JUDGMENT_LABELS).fillna("제외(환수금 등)")

    valid = tasks[tasks["_판정코드"].notna()]
    if valid.empty:
        raise ValueError(
            "판정 대상 과제가 없습니다. '제재유형구분' 값에 "
            f"'{KW_LIMIT}' 또는 '{KW_FEE}' 가 있는지 확인해 주세요."
        )

    # 연도 축
    y0 = cfg.year_start or max(cfg.min_task_year, int(valid["총연구기간시작연도"].min()))
    y1 = cfg.year_end or int(valid["총연구기간종료연도"].max())
    if cfg.year_end is None:
        cap = cfg.year_end_cap or _dt.date.today().year
        if y1 > cap:
            cfg.log(f"  ! 종료연도 {y1} -> {cap} 으로 제한했습니다 (아직 수행되지 않은 연도)")
            y1 = cap
    years = list(range(y0, max(y0, y1) + 1))
    cfg.resolved["years"] = years

    # 과제 x 연도 불리언 행렬 (벡터화)
    ya = np.asarray(years, dtype=np.int64)
    s = tasks["총연구기간시작연도"].to_numpy(dtype=np.int64)[:, None]
    e = tasks["총연구기간종료연도"].to_numpy(dtype=np.int64)[:, None]
    mask = (s <= ya[None, :]) & (ya[None, :] <= e)

    # 마스크는 항상 연속 구간이므로 '2018~2020' 형태로 표기 (벡터 연산)
    lo = np.clip(s[:, 0], years[0], years[-1])
    hi = np.clip(e[:, 0], years[0], years[-1])
    any_year = mask.any(axis=1)
    tasks["집계반영연도"] = np.where(
        ~any_year, "",
        np.where(lo == hi, lo.astype(str), lo.astype(str) + "~" + hi.astype(str)),
    )
    cfg.log(
        f"[기간분석] 과제 {len(tasks):,}건 (판정대상 {len(valid):,}건) / 연도축 {years[0]}~{years[-1]}"
    )
    return tasks, years, mask


# ---------------------------------------------------------------------------
# [4] 집계
# ---------------------------------------------------------------------------

@dataclass
class AggregateResult:
    years: list[int]
    ministries: list[str]
    counts: dict          # counts[부처][판정코드][연도 | "합계"] = 건수
    tasks: pd.DataFrame
    long: pd.DataFrame
    reference: dict | None = None

    def count(self, ministry: str, code: str, col) -> int:
        return int(self.counts.get(ministry, {}).get(code, {}).get(col, 0))

    def subtotal(self, ministry: str, col) -> int:
        return sum(self.count(ministry, c, col) for c in JUDGMENT_ORDER)

    def ref(self, ministry: str, item: str, col):
        if not self.reference:
            return None
        return self.reference.get((ministry, item), {}).get(col)

    def ratio(self, ministry: str, col):
        """제재처분 비율 = 소계 / 국가R&D과제수 x 100"""
        try:
            denom = float(self.ref(ministry, "국가R&D과제수", col))
        except (TypeError, ValueError):
            return None
        if not denom or denom != denom:  # 0 또는 NaN (참조데이터의 빈 셀)
            return None
        return self.subtotal(ministry, col) / denom * 100.0


def aggregate(tasks: pd.DataFrame, years: list[int], mask, cfg: PipelineConfig) -> AggregateResult:
    """부처 x 판정 x 연도 집계. 합계 열은 과제 중복 제거(계속과제 1건)."""
    keep = tasks["_판정코드"].notna().to_numpy() & mask.any(axis=1)
    if not keep.any():
        raise ValueError("연도 축 안에서 수행된 판정 대상 과제가 없습니다.")

    sub = tasks.loc[keep]
    m = mask[keep]

    all_juris = set(tasks["소관부처"].unique()) - {UNASSIGNED}
    kept_juris = set(sub["소관부처"].unique()) - {UNASSIGNED}
    for mm in sorted(all_juris - kept_juris):
        has_valid = tasks.loc[tasks["소관부처"] == mm, "_판정코드"].notna().any()
        if not has_valid:
            cfg.log(f"  ! '{mm}' 부처는 판정 대상(참여제한/제재부가금) 과제가 없어(환수금 등만 존재) 집계에서 빠졌습니다")
        else:
            cfg.log(
                f"  ! '{mm}' 부처는 총연구기간이 연도축({years[0]}~{years[-1]}) 밖이라 집계에서 빠졌습니다"
            )

    grid = pd.DataFrame(m, columns=years)
    grid["_부처"] = sub["소관부처"].to_numpy()
    grid["_판정"] = sub["_판정코드"].to_numpy()

    per_year = grid.groupby(["_부처", "_판정"], sort=True)[years].sum()
    per_total = grid.groupby(["_부처", "_판정"], sort=True).size()

    ministries = sorted(sub["소관부처"].unique().tolist())
    counts: dict = {
        mm: {c: dict.fromkeys([*years, "합계"], 0) for c in JUDGMENT_ORDER}
        for mm in [*ministries, TOTAL_LABEL]
    }
    for (mm, cc), row in per_year.iterrows():
        for y in years:
            v = int(row[y])
            counts[mm][cc][y] = v
            counts[TOTAL_LABEL][cc][y] += v
    for (mm, cc), v in per_total.items():
        counts[mm][cc]["합계"] = int(v)
        counts[TOTAL_LABEL][cc]["합계"] += int(v)

    # 과제 x 연도 long 포맷
    ti, yi = np.nonzero(m)
    long = pd.DataFrame(
        {
            "소관부처": sub["소관부처"].to_numpy()[ti],
            "과제번호": sub["과제번호"].to_numpy()[ti],
            "과제명": sub["과제명"].to_numpy()[ti],
            "판정": sub["_판정코드"].to_numpy()[ti],
            "연도": np.asarray(years)[yi],
            "건수": 1,
        }
    )

    cfg.log(f"[집계] 부처 {len(ministries)}개 / 판정대상 과제 {int(keep.sum()):,}건")
    return AggregateResult(
        years=years, ministries=ministries, counts=counts, tasks=tasks, long=long
    )


# ---------------------------------------------------------------------------
# 참조 데이터 (NTIS 조사·분석: 국가R&D연구비 / 국가R&D과제수)
# ---------------------------------------------------------------------------

REF_ITEMS = ["국가R&D연구비", "국가R&D과제수"]
_REF_ITEM_ALIASES = {
    "국가R&D연구비": ["국가R&D연구비", "연구비", "정부연구비", "국가rnd연구비"],
    "국가R&D과제수": ["국가R&D과제수", "과제수", "총괄주관과제수", "국가rnd과제수"],
}


def load_reference(path: str | None, years: list[int], cfg: PipelineConfig) -> dict | None:
    """조사·분석 참조 엑셀 -> ref[(부처, 항목)][연도] = 값

    허용 형식
      (A) wide : 부처 | 항목 | 2017 | ... | 합계
      (B) long : 부처 | 연도 | 국가R&D연구비 | 국가R&D과제수
    """
    if not path:
        return None
    df = (
        pd.read_csv(path)
        if str(path).lower().endswith(".csv")
        else pd.read_excel(path)
    )
    cols = {_norm_key(c): c for c in df.columns}

    def pick(*names):
        for n in names:
            if _norm_key(n) in cols:
                return cols[_norm_key(n)]
        return None

    mcol = pick("부처", "부처별", "소관부처", "중앙행정기관", "부처명")
    if mcol is None:
        raise KeyError(f"참조 파일에 '부처' 컬럼이 없습니다: {list(df.columns)}")

    #: 집계표와 같은 규칙으로 부처명을 통일한다. 이걸 하지 않으면 rawdata 쪽만
    #: 새 이름으로 바뀌어 참조데이터 조회가 빗나가고 연구비·과제수·비율이
    #: 통째로 공란이 된다.
    rn = resolve_rename_chains(cfg.ministry_rename)
    ref: dict = {}

    def _ministry(v) -> str:
        name = str(v).strip()
        return rn.get(name, name)

    def _put(key, col, value) -> None:
        """치환으로 두 부처가 한 이름이 되면 값을 덮지 않고 더한다."""
        d = ref.setdefault(key, {})
        if col not in d:
            d[col] = value
            return
        try:
            d[col] = float(d[col]) + float(value)
        except (TypeError, ValueError):
            pass  # 숫자가 아니면 먼저 온 값을 유지

    ycol = pick("연도", "년도")
    if ycol is not None:
        for item, aliases in _REF_ITEM_ALIASES.items():
            vcol = pick(*aliases)
            if vcol is None:
                continue
            for _, r in df.iterrows():
                y = extract_year(r[ycol])
                if pd.isna(y):
                    continue
                _put((_ministry(r[mcol]), item), int(y), r[vcol])
    else:
        icol = pick("항목", "구분")
        if icol is None:
            raise KeyError("참조 파일은 '연도' 열(long) 또는 '항목' 열(wide)이 필요합니다.")
        year_cols = {}
        for c in df.columns:
            y = extract_year(c)
            if pd.notna(y):
                year_cols[int(y)] = c
        total_col = pick("합계", "총계", "계")
        item_map = {
            _norm_key(a): std for std, al in _REF_ITEM_ALIASES.items() for a in al
        }
        for _, r in df.iterrows():
            item = item_map.get(_norm_key(r[icol]))
            if item is None:
                continue
            key = (_ministry(r[mcol]), item)
            for y, c in year_cols.items():
                _put(key, y, r[c])
            if total_col is not None:
                _put(key, "합계", r[total_col])

    # '합계' 표기 정규화 / 없으면 부처 값 합으로 보완
    for item in REF_ITEMS:
        for alias in ("합계", "총계", "계", "합 계"):
            if (alias, item) in ref and (TOTAL_LABEL, item) not in ref:
                ref[(TOTAL_LABEL, item)] = ref[(alias, item)]
        if (TOTAL_LABEL, item) in ref:
            continue
        agg: dict = {}
        for (mm, it), d in ref.items():
            if it != item or mm in (TOTAL_LABEL, "합계", "총계", "계"):
                continue
            for k, v in d.items():
                try:
                    agg[k] = agg.get(k, 0) + float(v)
                except (TypeError, ValueError):
                    pass
        if agg:
            ref[(TOTAL_LABEL, item)] = agg

    cfg.log(f"[참조] {len({m for m, _ in ref})}개 부처 결합")
    return ref


def make_reference_template(path: str, ministries: list[str], years: list[int]) -> str:
    rows = [
        {"부처": m, "항목": item, **dict.fromkeys(years), "합계": None}
        for m in [*ministries, TOTAL_LABEL]
        for item in REF_ITEMS
    ]
    pd.DataFrame(rows).to_excel(path, index=False, sheet_name="조사분석")
    return path


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------

def run_pipeline(
    raw_path: str,
    reference_path: str | None = None,
    cfg: PipelineConfig | None = None,
) -> AggregateResult:
    cfg = cfg or PipelineConfig()
    raw = load_raw(raw_path, cfg)
    tr = transform(raw, cfg)
    pp = preprocess(tr, cfg)
    tasks, years, mask = analyze_periods(pp, cfg)
    result = aggregate(tasks, years, mask, cfg)
    result.reference = load_reference(reference_path, years, cfg)
    return result
