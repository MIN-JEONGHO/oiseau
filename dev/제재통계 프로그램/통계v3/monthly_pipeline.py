# -*- coding: utf-8 -*-
"""
제재정보 raw data -> 월별통계 9종 (처분연도 기준)

'월별통계 제재통계 자동 분석.xlsx' 의 수식 로직을 pandas 로 구현한 모듈.
같은 NTIS 제재정보 rawdata 를 쓰지만 기준연도가 **처분연도**이고, 과제 단위로
묶지 않고 **제재 레코드 단위**로 센다는 점이 '제재처분 원인과제 집계'와 다르다.

  [입력]  NTIS 제재정보 rawdata (헤더 행 자동 탐지 — sanction_pipeline 재사용)
     |
  [1] 전처리  : 원본 워크북 '원자료(전처리)' 시트의 11열을 그대로 재현
     |
  [2] 집계    : 제재유형(3) x 분류축(3) = 9개 통계
                  참여제한   -> 건수
                  환수금     -> 부과액/납부액/미납액/미납률/건수
                  제재부가금 -> 부과액/납부액/미납액/미납률/건수
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sanction_pipeline import (
    MINISTRY_RENAME,
    UNASSIGNED,
    PipelineConfig,
    _clean_text,
    _norm_key,
    detect_header_row,
    extract_year_series,
    resolve_rename_chains,
)

TOTAL_LABEL = "합 계"

# ---------------------------------------------------------------------------
# 컬럼 사전 — '원자료' 시트의 11열
# ---------------------------------------------------------------------------

M_REQUIRED = {
    "처분연도": ["처분연도", "처분년도", "제재처분연도"],
    "제재유형구분": ["제재유형구분", "제재유형", "제재구분"],
    "제재ID": ["제재ID", "제재아이디", "제재정보ID"],
}
M_OPTIONAL = {
    "연구수행주체": ["연구수행주체"],
    "연구수행주체(정제)": ["연구수행주체(정제)", "연구수행주체정제"],
    "제재사유(기본법)": ["제재사유(기본법)", "제재사유기본법"],
    "제재사유(혁신법)": ["제재사유(혁신법)", "제재사유혁신법"],
    "미납금액": ["미납금액"],
    "대상금액(원)": ["대상금액(원)", "대상금액"],
    "납부금액(원)": ["납부금액(원)", "납부금액"],
    "소관부처": ["소관부처", "소관 부처"],
    "부처명": ["부처명", "부처", "중앙행정기관"],
    "처분일": ["처분일", "제재처분일"],
}
M_ALL = {**M_REQUIRED, **M_OPTIONAL}
_M_ALIAS = {_norm_key(a): std for std, al in M_ALL.items() for a in al}

#: 억원 환산 단위
EOK = 100_000_000

# ---------------------------------------------------------------------------
# 표준 분류 목록 (엑셀 결과부의 고정 목록)
# ---------------------------------------------------------------------------

#: 제재사유 9분류 -> (기본법 원문값, 혁신법 원문값)
REASON_GROUPS: list[tuple[str, list[str], list[str]]] = [
    ("연구결과 불량", ["01. 연구결과불량"], ["12. 연구과정 및 결과 불량"]),
    ("연구개발결과 누설‧유출", ["02. 연구개발 내용 누설 및 유출"], []),
    ("연구개발과제 수행포기", ["03. 연구개발과제 수행포기"], ["27. 연구개발과제 수행포기"]),
    ("기술료 미납", ["04. 기술료 미납"], ["28. 기술료 미납"]),
    ("환수금 미납", ["05. 환수금 미납"], ["29. 회수금 미납"]),
    (
        "연구비 부정사용",
        ["06. 연구개발비 용도외 사용", "07. 학생인건비부당회수", "071. 연구개발비 용도외 사용"],
        ["15. 연구개발비 용도외 사용", "16. 학생인건비부당회수"],
    ),
    (
        "연구개발 성과의 소유 위반",
        ["08. 지식재산권의 개인 명의 출원 및 등록"],
        ["17. 연구개발 성과의 소유 위반"],
    ),
    (
        "연구 부정행위",
        ["09. 부정한 방법으로 연구 수행", "10. 위조·변조·표절", "101. 부정한 방법으로 연구 수행"],
        [
            "14. 위조·변조·표절",
            "21. 부정한 방법으로 연구 신청",
            "22. 부정한 방법으로 연구 수행",
            "24. 연구비 사용 건전성 저해 행위",
        ],
    ),
    (
        "그 외 법령 및 협약 위반",
        ["11. 그 외 법령 및 협약 위반"],
        ["13. 협약불이행에 따른 과제 변경‧중단"],
    ),
]
REASON_LABELS = [g[0] for g in REASON_GROUPS]

#: 표기용 라벨 — 여러 원문값을 묶은 분류는 세부 사유를 괄호에 적는다.
#: 양식 각주 "통합 시 세부 제재사유를 괄호 안에 표기"를 따르며, 양식에서는 표마다
#: 괄호 내용이 달랐던 것(데이터에 나온 것만 적힘)을 전 표에 같은 형태로 통일했다.
REASON_DISPLAY = {
    "연구비 부정사용": "연구비 부정사용(연구개발비 용도외 사용, 학생인건비 부당회수)",
    "연구개발 성과의 소유 위반": "연구개발 성과의 소유 위반(지식재산권의 개인 명의 출원 및 등록)",
    "연구 부정행위": (
        "연구 부정행위(부정한 방법으로 연구 신청‧수행, 위조‧변조‧표절, "
        "연구비 사용 건전성 저해 행위)"
    ),
    "그 외 법령 및 협약 위반": "그 외 법령 및 협약 위반(협약불이행에 따른 과제 변경‧중단)",
}


def display_label(label: str) -> str:
    """표·문서에 쓸 분류명."""
    return REASON_DISPLAY.get(label, label)

#: 기관유형 표준 목록
ORG_LABELS = ["대학", "대기업", "중견기업", "중소기업", "출연연", "국공립연구소", "기타"]

#: 기관유형 표기 별칭 (구칭·유사표기 -> 표준). 적용되면 화면에 알린다.
ORG_ALIAS = {
    "출연연구소": "출연연",
    "정부출연연구소": "출연연",
    "출연(연)": "출연연",
    "국공립연": "국공립연구소",
    "국공립": "국공립연구소",
    "국·공립연구소": "국공립연구소",
    "정부부처": "국공립연구소",
    "대학교": "대학",
    "산학협력단": "대학",
}

#: 표준 목록에 없는 기관유형은 '기타'로 편입한다. 공란도 마찬가지.
#: 다른 분류축과 달리 별도 행을 만들지 않는다 — 양식의 기관유형은 7개로 고정이고,
#: 목록 밖 값을 남기면 기관유형별 표만 합계가 갈라진다.
ORG_FALLBACK = "기타"

#: 부처 표준 목록 (엑셀 결과부 순서).
#: 구칭이 섞여 있으므로 실제 사용 시에는 ministry_rename 을 적용해 정규화한다.
#: 이 처리를 빼면 rawdata 쪽만 새 이름(예: 산업통상부)이 되어 표준 목록의 구칭 행은
#: 0 으로 남고 새 이름이 '미등록 값'으로 맨 아래 따로 붙는다 — 같은 부처가 두 줄로 갈라진다.
MINISTRY_LABELS = [
    "경찰청", "과학기술정보통신부", "교육부", "국토교통부", "기상청",
    "농림축산식품부", "농촌진흥청", "다부처", "문화체육관광부",
    "방송미디어통신위원회", "방위사업청", "보건복지부", "산림청",
    "산업통상자원부", "소방청", "식품의약품안전처", "원자력안전위원회",
    "중소벤처기업부", "특허청", "해양경찰청", "해양수산부", "행정안전부",
    "기후에너지환경부",
]

#: 제재유형 3종 -> (통계 성격)
SANCTION_LIMIT = "참여제한"
SANCTION_RECOVER = "환수금"
SANCTION_FEE = "제재부가금"

#: 9개 통계 정의 (번호, 제목, 제재유형, 분류축)
AXIS_REASON, AXIS_ORG, AXIS_MINISTRY = "제재사유", "기관유형", "부처"
TABLES: list[tuple[int, str, str, str]] = [
    (1, "국가R&D사업 참여제한 현황(제재사유별)", SANCTION_LIMIT, AXIS_REASON),
    (2, "국가R&D사업 참여제한 현황(기관유형별)", SANCTION_LIMIT, AXIS_ORG),
    (3, "국가R&D사업 참여제한 현황(부처별)", SANCTION_LIMIT, AXIS_MINISTRY),
    (4, "국가R&D사업 환수금 현황(제재사유별)", SANCTION_RECOVER, AXIS_REASON),
    (5, "국가R&D사업 환수금 현황(기관유형별)", SANCTION_RECOVER, AXIS_ORG),
    (6, "국가R&D사업 환수금 현황(부처별)", SANCTION_RECOVER, AXIS_MINISTRY),
    (7, "국가R&D사업 제재부가금 현황(제재사유별)", SANCTION_FEE, AXIS_REASON),
    (8, "국가R&D사업 제재부가금 현황(기관유형별)", SANCTION_FEE, AXIS_ORG),
    (9, "국가R&D사업 제재부가금 현황(부처별)", SANCTION_FEE, AXIS_MINISTRY),
]

#: 금액 통계의 항목 순서
MONEY_ITEMS = ["부과액", "납부액", "미납액", "미납률", "건수"]
COUNT_ITEMS = ["건수"]


@dataclass
class MonthlyConfig:
    """월별통계 실행 옵션."""

    sheet_name: str | int = "제재정보"
    header_row: int | None = None
    data_start_row: int | None = None
    year_start: int | None = 2017     # None -> 데이터 최소 처분연도
    year_end: int | None = None       # None -> 올해
    ministry_column: str = "소관부처"
    ministry_rename: dict = field(default_factory=lambda: dict(MINISTRY_RENAME))
    org_alias: dict = field(default_factory=lambda: dict(ORG_ALIAS))
    #: 전 연도가 0인 행을 빼는 분류축. 부처는 23개 중 대부분이 0이라 표가 길어진다.
    #: 제재사유·기관유형은 목록이 짧아 0이어도 남긴다(양식과 대조하기 쉽도록).
    drop_empty_axes: tuple = (AXIS_MINISTRY,)
    verbose: bool = True
    resolved: dict = field(default_factory=dict)

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg)


# ---------------------------------------------------------------------------
# [0] 입력
# ---------------------------------------------------------------------------

def load_raw(path: str, cfg: MonthlyConfig) -> pd.DataFrame:
    """rawdata 에서 월별통계에 필요한 열만 읽는다."""
    from sanction_pipeline import PipelineConfig as _PC
    from sanction_pipeline import _read_excel

    probe = _PC(sheet_name=cfg.sheet_name, verbose=cfg.verbose)
    probe.log = cfg.log
    if cfg.header_row is None:
        cfg.header_row = detect_header_row(path, cfg.sheet_name, probe)
    if cfg.data_start_row is None:
        cfg.data_start_row = cfg.header_row + 1
    header_idx = cfg.header_row - 1
    cfg.resolved["header_row"] = cfg.header_row

    def wanted(name) -> bool:
        return _norm_key(name) in _M_ALIAS

    lower = str(path).lower()
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
    cfg.resolved["sheet"] = cfg.sheet_name
    cfg.log(f"[입력] {len(df):,}행 (필요 컬럼 {len(df.columns)}개, 헤더 {cfg.header_row}행)")
    return df


# ---------------------------------------------------------------------------
# [1] 전처리 — '원자료(전처리)' 시트 재현
# ---------------------------------------------------------------------------

#: 전각 숫자·기호 -> 반각
_WIDE = str.maketrans("０１２３４５６７８９．－（），", "0123456789.-(),")
#: 금액 문자열에서 걷어낼 것 (쉼표, 각종 공백, 통화 표기)
_MONEY_STRIP = re.compile(r"[,\s 　]|원$|₩|KRW", re.I)


def parse_money(s: pd.Series) -> tuple[pd.Series, int, list[str]]:
    """금액 열을 숫자로. (값, 변환 실패 건수, 실패 예시)

    NTIS 내보내기에 따라 금액이 **텍스트로 저장**되어 오는 경우가 있다.
    `18,873,603` 처럼 쉼표가 있으면 pandas 의 to_numeric 이 그대로 NaN 을 내고,
    그러면 그 금액이 조용히 0 으로 집계된다. 원본 워크북에서 '텍스트 나누기'로
    속성을 바꿔야 했던 것이 이 문제이므로 여기서 직접 걷어낸다.

    0 은 결측으로 둔다 (엑셀 IF(VALUE(..)=0,"") 재현).
    """
    if pd.api.types.is_numeric_dtype(s):
        v = pd.to_numeric(s, errors="coerce")
        return v.where(v.ne(0)), 0, []

    txt = s.astype("string").fillna("").str.strip()
    cleaned = (
        txt.str.translate(_WIDE)
        .str.replace(_MONEY_STRIP, "", regex=True)
        # (1,234) 형태의 음수
        .str.replace(r"^\((.+)\)$", r"-\1", regex=True)
    )
    v = pd.to_numeric(cleaned, errors="coerce")

    bad = txt.ne("") & v.isna()
    samples = [str(x) for x in txt[bad].unique()[:4]]
    return v.where(v.ne(0)), int(bad.sum()), samples


def _money(s: pd.Series) -> pd.Series:
    return parse_money(s)[0]


def preprocess(df: pd.DataFrame, cfg: MonthlyConfig) -> pd.DataFrame:
    """11열 전처리 결과를 만든다."""
    lookup: dict[str, str] = {}
    for c in df.columns:
        std = _M_ALIAS.get(_norm_key(c))
        if std and std not in lookup:
            lookup[std] = c
    missing = [k for k in M_REQUIRED if k not in lookup]
    if missing:
        raise KeyError(
            "raw data 에서 다음 필수 컬럼을 찾을 수 없습니다: " + ", ".join(missing)
            + f"\n  읽어온 컬럼: {list(df.columns)}\n  헤더 행 번호를 확인해 주세요."
        )
    if "소관부처" not in lookup and "부처명" not in lookup:
        raise KeyError("raw data 에서 '소관부처' 또는 '부처명' 컬럼을 찾을 수 없습니다.")

    def col(name) -> pd.Series:
        if name in lookup:
            return df[lookup[name]]
        return pd.Series([pd.NA] * len(df), index=df.index)

    out = pd.DataFrame(index=df.index)

    # 처분연도 — 없으면 처분일에서 추출
    yr = extract_year_series(col("처분연도"))
    if yr.isna().all() and "처분일" in lookup:
        yr = extract_year_series(col("처분일"))
    out["처분연도"] = yr

    out["제재유형구분"] = _clean_text(col("제재유형구분"))

    # 연구수행주체 — 두 열의 출처가 다르다.
    #   연구수행주체(L열)      : 문제과제정보 (조사·분석 데이터)
    #   연구수행주체(정제)(AG열): 제재정보 (전문기관 입력)
    # 규칙 = IF(제재정보="", 문제과제, 제재정보)
    #   1) 정제가 비면 L열 값을 쓴다
    #   2) 둘 다 있고 다르면 정제(AG열)를 쓴다
    raw_org = _clean_text(col("연구수행주체"))
    fine_org = _clean_text(col("연구수행주체(정제)"))
    org = fine_org.where(fine_org.ne(""), raw_org)

    n_from_raw = int((fine_org.eq("") & raw_org.ne("")).sum())
    diff = (fine_org.ne("") & raw_org.ne("") & fine_org.ne(raw_org))
    n_diff = int(diff.sum())
    if n_from_raw:
        cfg.log(f"  ! 연구수행주체(정제)가 빈 행 {n_from_raw:,}건은 연구수행주체 값을 썼습니다")
    if n_diff:
        pairs = sorted({f"{a}→{b}" for a, b in zip(raw_org[diff], fine_org[diff])})
        cfg.log(
            f"  ! 두 열이 달라 연구수행주체(정제) 값을 쓴 행 {n_diff:,}건: "
            + ", ".join(pairs[:5]) + (" …" if len(pairs) > 5 else "")
        )
    n_both_blank = int((fine_org.eq("") & raw_org.eq("")).sum())
    cfg.resolved["org_source"] = {
        "정제사용": int((fine_org.ne("")).sum()),
        "L열보완": n_from_raw,
        "불일치": n_diff,
        "둘다공란": n_both_blank,
    }

    # 기관유형 별칭 적용 (정부부처 → 국공립연구소 등)
    alias = resolve_rename_chains(cfg.org_alias)
    hits = org[org.isin(alias)].value_counts()
    for old, n in hits.items():
        cfg.log(f"  ! 기관유형 치환: {old} → {alias[old]} ({n:,}건)")
    cfg.resolved["org_alias_hits"] = {str(k): [alias[k], int(v)] for k, v in hits.items()}
    org = org.replace(alias)

    # 표준 7개에 없는 값과 공란은 '기타'로 편입한다.
    # 양식의 기관유형은 7개로 고정이고, 목록 밖 값을 남기면 기관유형별 표만 합계가 갈라진다.
    unlisted = org.ne("") & ~org.isin(ORG_LABELS)
    n_blank_org = int(org.eq("").sum())
    if unlisted.any():
        cnt = org[unlisted].value_counts()
        cfg.log(
            f"  ! 표준 목록에 없는 기관유형 {int(unlisted.sum()):,}건을 '{ORG_FALLBACK}'로 편입: "
            + ", ".join(f"{k} {v:,}건" for k, v in cnt.items())
        )
        cfg.resolved["org_to_other"] = {str(k): int(v) for k, v in cnt.items()}
    if n_blank_org:
        cfg.log(
            f"  ! 연구수행주체가 두 열 모두 빈 행 {n_blank_org:,}건도 '{ORG_FALLBACK}'로 편입"
        )
    cfg.resolved["org_blank_to_other"] = n_blank_org
    out["연구수행주체(정제)"] = org.where(org.isin(ORG_LABELS), ORG_FALLBACK)

    out["제재사유(기본법)"] = _clean_text(col("제재사유(기본법)"))
    out["제재사유(혁신법)"] = _clean_text(col("제재사유(혁신법)"))
    # 금액 3열 — 텍스트로 저장돼 온 경우 쉼표·공백을 걷어내고 숫자로 바꾼다.
    # 변환하지 못한 값은 집계에서 0 이 되므로 반드시 알린다.
    money_bad: dict = {}
    for name in ("미납금액", "대상금액(원)", "납부금액(원)"):
        v, n_bad, samples = parse_money(col(name))
        out[name] = v
        if n_bad:
            money_bad[name] = n_bad
            cfg.log(
                f"  ! '{name}' 을 숫자로 바꾸지 못한 값 {n_bad:,}건 (집계에서 0 처리): "
                + ", ".join(repr(x) for x in samples)
            )
    cfg.resolved["money_unparsed"] = money_bad
    if money_bad:
        cfg.log(
            "  ! 금액이 텍스트로 저장된 파일일 수 있습니다. "
            "합계가 실제보다 작게 나오니 원자료를 확인해 주세요"
        )

    # 부처 — 선택 열을 쓰고 비면 다른 열로 보완, 구칭 통일
    primary = cfg.ministry_column if cfg.ministry_column in ("소관부처", "부처명") else "소관부처"
    backup = "부처명" if primary == "소관부처" else "소관부처"
    a, b = _clean_text(col(primary)), _clean_text(col(backup))
    m = a.where(a.ne(""), b)
    rn = resolve_rename_chains(cfg.ministry_rename)
    mhits = m[m.isin(rn)].value_counts()
    for old, n in mhits.items():
        cfg.log(f"  ! 부처명 치환: {old} → {rn[old]} ({n:,}건)")
    cfg.resolved["ministry_renames"] = {str(k): [rn[k], int(v)] for k, v in mhits.items()}
    cfg.resolved["ministry_column"] = primary
    out["소관부처"] = m.replace(rn).replace("", UNASSIGNED)

    out["제재ID"] = _clean_text(col("제재ID"))
    out["건수"] = np.where(out["제재ID"].ne(""), 1, 0)

    before = len(out)
    out = out[out["처분연도"].notna()]
    if before - len(out):
        cfg.log(f"  ! 처분연도가 없어 제외한 행 {before - len(out):,}건")
    if out.empty:
        raise ValueError("처분연도가 있는 행이 없습니다. 헤더 행 설정을 확인해 주세요.")
    out["처분연도"] = out["처분연도"].astype(int)

    cfg.log(f"[전처리] {len(out):,}행 (제재 레코드 단위)")
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# [2] 집계
# ---------------------------------------------------------------------------

def _reason_label(pre: pd.DataFrame) -> pd.Series:
    """기본법·혁신법 원문값 -> 9분류 라벨. 어느 쪽에도 없으면 빈 문자열."""
    base = pre["제재사유(기본법)"]
    new = pre["제재사유(혁신법)"]
    out = pd.Series("", index=pre.index, dtype=object)
    for label, base_keys, new_keys in REASON_GROUPS:
        hit = base.isin(base_keys) | new.isin(new_keys)
        out = out.mask(hit & out.eq(""), label)
    return out


@dataclass
class MonthlyTable:
    """통계 한 개."""

    no: int
    title: str
    sanction: str
    axis: str
    labels: list[str]              # 분류 행 순서 (표준 목록 + 추가분)
    extra_labels: list[str]        # 표준 목록에 없어 덧붙인 분류
    items: list[str]               # 항목 순서
    #: values[분류][항목][연도 | "합계"] = 값 (None 이면 공란)
    values: dict
    unit: str
    #: 이 제재유형의 모집단 건수 (연도축 내). 세 분류축 표가 모두 같아야 한다.
    base_count: int = 0
    #: 분류축 값이 비어 이 표에서만 빠진 건수
    dropped_count: int = 0

    def get(self, label: str, item: str, col) -> float | None:
        return self.values.get(label, {}).get(item, {}).get(col)


@dataclass
class MonthlyResult:
    years: list[int]
    tables: list[MonthlyTable]
    pre: pd.DataFrame
    dropped: dict = field(default_factory=dict)
    #: 전처리 요약 (연구수행주체 출처 내역, 금액 변환 실패 등)
    prep: dict = field(default_factory=dict)

    def table(self, no: int) -> MonthlyTable:
        return next(t for t in self.tables if t.no == no)


def _axis_series(pre: pd.DataFrame, axis: str) -> pd.Series:
    if axis == AXIS_REASON:
        return pre["_제재사유"]
    if axis == AXIS_ORG:
        return pre["연구수행주체(정제)"]
    return pre["소관부처"]


def _std_labels(axis: str, cfg: MonthlyConfig) -> list[str]:
    """표준 분류 목록. 부처는 치환 규칙을 적용해 정규화한다."""
    if axis == AXIS_REASON:
        return list(REASON_LABELS)
    if axis == AXIS_ORG:
        return list(dict.fromkeys(
            resolve_rename_chains(cfg.org_alias).get(x, x) for x in ORG_LABELS
        ))
    rn = resolve_rename_chains(cfg.ministry_rename)
    # 치환으로 두 부처가 한 이름이 되면 순서를 지키며 하나로 합친다
    return list(dict.fromkeys(rn.get(x, x) for x in MINISTRY_LABELS))


def _build_table(
    pre: pd.DataFrame, years: list[int], no: int, title: str, sanction: str, axis: str,
    cfg: MonthlyConfig,
) -> MonthlyTable:
    sub = pre[pre["제재유형구분"].eq(sanction) & pre["처분연도"].isin(years)]
    ax = _axis_series(sub, axis)

    #: 이 제재유형의 모집단 — 세 분류축 표가 모두 이 값과 같아야 한다
    base = int(sub["건수"].sum())
    #: 분류축 값이 비어 이 표에서만 빠지는 건수 (표 간 합계가 갈라지는 원인)
    dropped = int(sub.loc[ax.eq(""), "건수"].sum())

    std = _std_labels(axis, cfg)
    present = [v for v in sorted(ax[ax.ne("")].unique().tolist()) if v not in std]
    labels = std + present
    if present:
        cfg.log(
            f"  ! [{no}] 표준 목록에 없는 {axis} 값 {len(present)}개를 행으로 추가했습니다: "
            + ", ".join(present[:6]) + (" …" if len(present) > 6 else "")
        )
    if dropped:
        why = "9분류에 없어" if axis == AXIS_REASON else "값이 비어"
        cfg.log(f"  ! [{no}] {axis}가 {why} 이 표에서 빠진 건수 {dropped:,}건 (모집단 {base:,}건)")

    is_money = sanction in (SANCTION_RECOVER, SANCTION_FEE)
    items = MONEY_ITEMS if is_money else COUNT_ITEMS
    keys = [*years, "합계"]

    work = pd.DataFrame(
        {
            "_ax": ax,
            "_yr": sub["처분연도"],
            "건수": sub["건수"],
            "부과액": sub["대상금액(원)"].fillna(0) / EOK,
            "납부액": sub["납부금액(원)"].fillna(0) / EOK,
        }
    )
    work = work[work["_ax"].ne("") & work["_yr"].isin(years)]

    agg = (
        work.groupby(["_ax", "_yr"], sort=False)[["건수", "부과액", "납부액"]].sum()
        if len(work) else None
    )

    values: dict = {}
    for lab in [*labels, TOTAL_LABEL]:
        values[lab] = {it: dict.fromkeys(keys) for it in items}
    n_overpaid = [0]   # 납부액 > 부과액 인 칸 수 (완납 처리)

    def put(lab, it, col, v) -> None:
        values[lab][it][col] = v

    for lab in labels:
        row = {it: {} for it in ("건수", "부과액", "납부액")}
        for y in years:
            try:
                r = agg.loc[(lab, y)] if agg is not None else None
            except KeyError:
                r = None
            row["건수"][y] = float(r["건수"]) if r is not None else 0.0
            row["부과액"][y] = float(r["부과액"]) if r is not None else 0.0
            row["납부액"][y] = float(r["납부액"]) if r is not None else 0.0
        for k in ("건수", "부과액", "납부액"):
            row[k]["합계"] = sum(row[k][y] for y in years)
        for col in keys:
            put(lab, "건수", col, row["건수"][col])
            if is_money:
                imp, paid = row["부과액"][col], row["납부액"][col]
                # 양식 각주: "미납액이 0원 이하일 경우 완납으로 간주" -> 음수는 0 으로
                unpaid = imp - paid
                if unpaid < -1e-9:
                    n_overpaid[0] += 1
                unpaid = max(unpaid, 0.0)
                put(lab, "부과액", col, imp)
                put(lab, "납부액", col, paid)
                put(lab, "미납액", col, unpaid)
                # 미납률 = 미납액/부과액. 부과액이 0(당해 연도 미발생)이면 산출하지 않는다.
                # 0% 는 '전액 납부'라는 뜻이므로 값으로 남긴다.
                put(lab, "미납률", col, unpaid / imp * 100 if imp else None)

    # 합 계 행 — 미납액은 완납 처리된 행 값을 더해 행 합과 어긋나지 않게 한다
    for col in keys:
        put(TOTAL_LABEL, "건수", col, sum(values[l]["건수"][col] for l in labels))
        if is_money:
            imp = sum(values[l]["부과액"][col] for l in labels)
            paid = sum(values[l]["납부액"][col] for l in labels)
            unpaid = sum(values[l]["미납액"][col] for l in labels)
            put(TOTAL_LABEL, "부과액", col, imp)
            put(TOTAL_LABEL, "납부액", col, paid)
            put(TOTAL_LABEL, "미납액", col, unpaid)
            put(TOTAL_LABEL, "미납률", col, unpaid / imp * 100 if imp else None)

    if n_overpaid[0]:
        cfg.log(
            f"  ! [{no}] 납부액이 부과액보다 큰 칸 {n_overpaid[0]:,}개를 "
            "'완납'(미납액 0, 미납률 0%)으로 처리했습니다"
        )

    # 전 연도가 0인 행 제거 (부처 축 기본). 표준 목록이 길어 대부분 0인 축에만 적용한다.
    if axis in cfg.drop_empty_axes:
        keep = [
            l for l in labels
            if any((values[l]["건수"][c] or 0) or (values[l].get("부과액", {}).get(c) or 0)
                   for c in keys)
        ]
        n_cut = len(labels) - len(keep)
        if n_cut:
            cfg.log(f"  ! [{no}] 전 연도가 0인 {axis} {n_cut}개 행을 뺐습니다")
        for l in set(labels) - set(keep):
            values.pop(l, None)
        labels = keep
        present = [p for p in present if p in keep]

    unit = "건" if not is_money else "건, 억원, %"
    return MonthlyTable(
        no=no, title=title, sanction=sanction, axis=axis,
        labels=labels, extra_labels=present, items=items, values=values, unit=unit,
        base_count=base, dropped_count=dropped,
    )


def aggregate(pre: pd.DataFrame, cfg: MonthlyConfig) -> MonthlyResult:
    pre = pre.copy()
    pre["_제재사유"] = _reason_label(pre)

    y0 = cfg.year_start or int(pre["처분연도"].min())
    y1 = cfg.year_end or _dt.date.today().year
    if y1 < y0:
        y1 = y0
    years = list(range(y0, y1 + 1))
    cfg.resolved["years"] = years

    out_of_range = int((~pre["처분연도"].isin(years)).sum())
    if out_of_range:
        cfg.log(f"  ! 처분연도가 {y0}~{y1} 밖이라 제외한 행 {out_of_range:,}건")

    unknown_types = sorted(
        set(pre.loc[pre["제재유형구분"].ne(""), "제재유형구분"])
        - {SANCTION_LIMIT, SANCTION_RECOVER, SANCTION_FEE}
    )
    if unknown_types:
        cfg.log(f"  ! 집계 대상이 아닌 제재유형: {', '.join(unknown_types)}")

    tables = [
        _build_table(pre, years, no, title, sanction, axis, cfg)
        for no, title, sanction, axis in TABLES
    ]
    cfg.log(f"[집계] 통계 {len(tables)}개 / 연도축 {years[0]}~{years[-1]}")
    return MonthlyResult(
        years=years, tables=tables, pre=pre,
        dropped={"연도밖": out_of_range, "제재유형외": unknown_types},
        prep=dict(cfg.resolved),
    )


# ---------------------------------------------------------------------------
# 검산
# ---------------------------------------------------------------------------

def integrity(res: MonthlyResult) -> list[dict]:
    """표 안쪽 정합성 + 같은 제재유형 세 표의 합계 일치를 확인."""
    checks = []
    for t in res.tables:
        ok = True
        for it in ("건수", "부과액", "납부액"):
            if it not in t.items:
                continue
            for col in [*res.years, "합계"]:
                s = sum(t.get(l, it, col) or 0 for l in t.labels)
                tot = t.get(TOTAL_LABEL, it, col) or 0
                if abs(s - tot) > 1e-6:
                    ok = False
            row = sum(t.get(TOTAL_LABEL, it, y) or 0 for y in res.years)
            if abs(row - (t.get(TOTAL_LABEL, it, "합계") or 0)) > 1e-6:
                ok = False
        checks.append({"label": f"{t.no}. {t.axis}별 {t.sanction}", "ok": ok})
    return checks


def cross_checks(res: MonthlyResult) -> list[dict]:
    """같은 제재유형의 세 표(분류축만 다름)는 모집단이 같으므로 합계가 같아야 한다.

    어긋나면 그 표에서만 빠진 건수를 함께 알려 준다. 실제로 갈라지는 경우는 두 가지다.
      - 제재사유가 9분류 어디에도 없는 행 -> 제재사유별 표에서만 빠짐
      - 연구수행주체가 비어 있는 행       -> 기관유형별 표에서만 빠짐
    부처는 비면 '(부처 미지정)' 으로 남으므로 빠지지 않는다.
    """
    out = []
    for sanction in (SANCTION_LIMIT, SANCTION_RECOVER, SANCTION_FEE):
        group = [t for t in res.tables if t.sanction == sanction]
        if len(group) < 2:
            continue
        base = max(t.base_count for t in group)
        sums = {t.axis: int(round(t.get(TOTAL_LABEL, "건수", "합계") or 0)) for t in group}
        ok = len(set(sums.values())) == 1 and next(iter(sums.values())) == base
        detail = " · ".join(f"{ax} {n:,}" for ax, n in sums.items())
        miss = [
            f"{t.axis} −{t.dropped_count:,}" for t in group if t.dropped_count
        ]
        out.append({
            "label": f"{sanction} 세 표 건수 합계 일치",
            "ok": ok,
            "detail": f"모집단 {base:,} / {detail}" + (f"  (빠진 건수: {' · '.join(miss)})" if miss else ""),
            "sums": sums,
            "base": base,
        })
    return out


def all_checks(res: MonthlyResult) -> list[dict]:
    return cross_checks(res) + integrity(res)


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------

def run_monthly(raw_path: str, cfg: MonthlyConfig | None = None) -> MonthlyResult:
    cfg = cfg or MonthlyConfig()
    raw = load_raw(raw_path, cfg)
    pre = preprocess(raw, cfg)
    return aggregate(pre, cfg)
