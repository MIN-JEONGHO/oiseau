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
    "대학교": "대학",
    "산학협력단": "대학",
}

#: 부처 표준 목록 (엑셀 결과부 순서)
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

def _money(s: pd.Series) -> pd.Series:
    """금액: 숫자로 바꾸고 0 은 결측으로 (엑셀 IF(VALUE(..)=0,"") 재현)."""
    v = pd.to_numeric(s, errors="coerce")
    return v.where(v.ne(0))


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

    # 연구수행주체(정제)가 있으면 그것, 없으면 연구수행주체  ← 원본 C열 규칙
    raw_org = _clean_text(col("연구수행주체"))
    fine_org = _clean_text(col("연구수행주체(정제)"))
    org = fine_org.where(fine_org.ne(""), raw_org)
    n_from_raw = int((fine_org.eq("") & raw_org.ne("")).sum())
    if n_from_raw:
        cfg.log(f"  ! 연구수행주체(정제)가 빈 행 {n_from_raw:,}건은 연구수행주체 값을 썼습니다")

    # 기관유형 별칭 적용
    alias = resolve_rename_chains(cfg.org_alias)
    hits = org[org.isin(alias)].value_counts()
    for old, n in hits.items():
        cfg.log(f"  ! 기관유형 치환: {old} → {alias[old]} ({n:,}건)")
    cfg.resolved["org_alias_hits"] = {str(k): [alias[k], int(v)] for k, v in hits.items()}
    out["연구수행주체(정제)"] = org.replace(alias)

    out["제재사유(기본법)"] = _clean_text(col("제재사유(기본법)"))
    out["제재사유(혁신법)"] = _clean_text(col("제재사유(혁신법)"))
    out["미납금액"] = _money(col("미납금액"))
    out["대상금액(원)"] = _money(col("대상금액(원)"))
    out["납부금액(원)"] = _money(col("납부금액(원)"))

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

    def get(self, label: str, item: str, col) -> float | None:
        return self.values.get(label, {}).get(item, {}).get(col)


@dataclass
class MonthlyResult:
    years: list[int]
    tables: list[MonthlyTable]
    pre: pd.DataFrame
    dropped: dict = field(default_factory=dict)

    def table(self, no: int) -> MonthlyTable:
        return next(t for t in self.tables if t.no == no)


def _axis_series(pre: pd.DataFrame, axis: str) -> pd.Series:
    if axis == AXIS_REASON:
        return pre["_제재사유"]
    if axis == AXIS_ORG:
        return pre["연구수행주체(정제)"]
    return pre["소관부처"]


def _std_labels(axis: str) -> list[str]:
    if axis == AXIS_REASON:
        return list(REASON_LABELS)
    if axis == AXIS_ORG:
        return list(ORG_LABELS)
    return list(MINISTRY_LABELS)


def _build_table(
    pre: pd.DataFrame, years: list[int], no: int, title: str, sanction: str, axis: str,
    cfg: MonthlyConfig,
) -> MonthlyTable:
    sub = pre[pre["제재유형구분"].eq(sanction)]
    ax = _axis_series(sub, axis)

    std = _std_labels(axis)
    present = [v for v in sorted(ax[ax.ne("")].unique().tolist()) if v not in std]
    labels = std + present
    if present:
        cfg.log(
            f"  ! [{no}] 표준 목록에 없는 {axis} 값 {len(present)}개를 행으로 추가했습니다: "
            + ", ".join(present[:6]) + (" …" if len(present) > 6 else "")
        )
    n_blank = int(ax.eq("").sum())
    if n_blank and axis == AXIS_REASON:
        cfg.log(f"  ! [{no}] 제재사유가 9분류에 없어 집계에서 빠진 행 {n_blank:,}건")

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
                put(lab, "부과액", col, imp)
                put(lab, "납부액", col, paid)
                put(lab, "미납액", col, imp - paid)
                put(lab, "미납률", col, (imp - paid) / imp * 100 if imp else None)

    # 합 계 행
    for col in keys:
        put(TOTAL_LABEL, "건수", col, sum(values[l]["건수"][col] for l in labels))
        if is_money:
            imp = sum(values[l]["부과액"][col] for l in labels)
            paid = sum(values[l]["납부액"][col] for l in labels)
            put(TOTAL_LABEL, "부과액", col, imp)
            put(TOTAL_LABEL, "납부액", col, paid)
            put(TOTAL_LABEL, "미납액", col, imp - paid)
            put(TOTAL_LABEL, "미납률", col, (imp - paid) / imp * 100 if imp else None)

    unit = "건" if not is_money else "건, 억원, %"
    return MonthlyTable(
        no=no, title=title, sanction=sanction, axis=axis,
        labels=labels, extra_labels=present, items=items, values=values, unit=unit,
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
    )


# ---------------------------------------------------------------------------
# 검산
# ---------------------------------------------------------------------------

def integrity(res: MonthlyResult) -> list[dict]:
    """표별로 분류 합 == 합 계 행, 연도별 합 == 합계 열 을 확인."""
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


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------

def run_monthly(raw_path: str, cfg: MonthlyConfig | None = None) -> MonthlyResult:
    cfg = cfg or MonthlyConfig()
    raw = load_raw(raw_path, cfg)
    pre = preprocess(raw, cfg)
    return aggregate(pre, cfg)
