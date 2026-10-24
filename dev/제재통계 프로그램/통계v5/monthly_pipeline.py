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
    # 아래 셋은 분류축 전용. 별칭 목록은 sanction_pipeline 과 같게 둔다.
    "제재대상": ["제재대상", "제재대상구분"],
    "사업명": ["사업명"],
    "과제유형": ["과제유형", "과제유형명", "연구과제유형", "과제구분"],
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

# ---------------------------------------------------------------------------
# 분류축 레지스트리
#
# 표는 (제재유형 x 분류축) 로 만들어진다. 축을 늘리려면 AXES 에 한 줄 더 적는다.
#
# 공란 정책이 이 설계의 핵심이다. cross_checks 는 '같은 제재유형의 모든 축 표에서
# 건수 합계 == 모집단' 을 요구하는데, 축 값이 빈 행은 그 표에서만 빠지므로
# 빈 값이 생길 수 있는 축은 반드시 대체 라벨을 가져야 한다. 빈 값을 대체 라벨로
# 바꿔 두면 _build_table 의 dropped 계산(ax.eq(""))이 저절로 0 이 되어 검산이 통과한다.
#
# 예외는 제재사유 하나뿐이다. 9분류에 없는 행이 빠지는 것은 결함이 아니라 기능이고,
# cross_checks 는 그것을 드러내려고 있다.
# ---------------------------------------------------------------------------

AXIS_REASON, AXIS_ORG, AXIS_MINISTRY = "제재사유", "기관유형", "부처"
AXIS_TARGET, AXIS_TASKTYPE, AXIS_PROGRAM = "제재대상", "과제유형", "사업명"

#: 공란 정책
BLANK_DROP = "drop"          # 이 표에서 뺀다 (검산이 어긋남을 드러낸다)
BLANK_FALLBACK = "fallback"  # blank_label 행으로 모은다 (모집단 보존)

#: 표준 라벨 산출 방식
LABELS_FIXED = "fixed"       # std 고정 목록 + 데이터에만 있는 값은 뒤에 덧붙임
LABELS_TOPN = "topn"         # 건수 상위 N개 + '기타'. 집계 전에 한 번만 확정


@dataclass(frozen=True)
class AxisSpec:
    """분류축 하나의 정의."""

    key: str                        # 안정 식별자. 설정값·검산 라벨에 그대로 쓰인다
    column: str                     # preprocess 결과의 원천 열 ('_' 시작 = 파생열)
    labels: str = LABELS_FIXED
    std: tuple = ()                 # LABELS_FIXED 일 때 표준 목록
    normalize: str = ""             # "" | "org" | "ministry" — std 에 적용할 치환표
    blank: str = BLANK_FALLBACK
    blank_label: str = ""           # BLANK_FALLBACK 일 때 쓸 라벨
    blank_note: str = "값이 비어"     # BLANK_DROP 일 때 로그 문구
    top_n: int = 0                  # LABELS_TOPN 기본값
    other_label: str = "기타"
    drop_empty: bool = False        # 전 연도 0인 행 숨김 기본값
    title_word: str = ""            # 표 제목에 쓸 말. 비면 key

    @property
    def word(self) -> str:
        return self.title_word or self.key


AXES: dict = {
    a.key: a for a in (
        AxisSpec(AXIS_REASON, "_제재사유", std=tuple(REASON_LABELS),
                 blank=BLANK_DROP, blank_note="9분류에 없어"),
        AxisSpec(AXIS_ORG, "연구수행주체(정제)", std=tuple(ORG_LABELS),
                 normalize="org", blank_label=ORG_FALLBACK),
        AxisSpec(AXIS_MINISTRY, "소관부처", std=tuple(MINISTRY_LABELS),
                 normalize="ministry", blank_label=UNASSIGNED, drop_empty=True),
        AxisSpec(AXIS_TARGET, "제재대상", std=("기관", "인물"),
                 blank_label="(대상 미상)"),
        AxisSpec(AXIS_TASKTYPE, "과제유형",
                 std=("세부(주관/협동)", "공동", "위탁", "기타"),
                 blank_label="(유형 미상)"),
        # 사업명은 값이 2천 종이 넘어 상위 N + '기타' 로 접는다.
        # '기타' 와 '(사업명 미상)' 은 반드시 갈라 둔다 — 섞으면 작은 사업과 결측이
        # 한 줄에 들어가 표를 읽을 수 없다.
        AxisSpec(AXIS_PROGRAM, "_사업명", labels=LABELS_TOPN, top_n=20,
                 blank_label="(사업명 미상)", drop_empty=True, title_word="사업"),
    )
}

#: 한글 표준양식이 담는 축·제재유형 (표 9개 고정)
STANDARD_AXES = (AXIS_REASON, AXIS_ORG, AXIS_MINISTRY)
STANDARD_SANCTIONS = (SANCTION_LIMIT, SANCTION_RECOVER, SANCTION_FEE)

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
    #: 기관유형 별칭 치환 적용 여부. 끄면 '출연연구소'·'정부부처'가 원자료 표기대로 갈라진다.
    org_alias_on: bool = True
    #: 만들 표 = sanctions x axes
    axes: tuple = STANDARD_AXES
    sanctions: tuple = STANDARD_SANCTIONS
    #: 상위 N 축의 N (사업명 등)
    top_n: dict = field(default_factory=lambda: {AXIS_PROGRAM: AXES[AXIS_PROGRAM].top_n})
    #: 전 연도가 0인 행을 빼는 분류축. 부처는 23개 중 대부분이 0이라 표가 길어진다.
    #: 제재사유·기관유형은 목록이 짧아 0이어도 남긴다(양식과 대조하기 쉽도록).
    #: None 이면 AxisSpec.drop_empty 를 따른다.
    drop_empty_axes: tuple | None = None
    verbose: bool = True
    resolved: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.axes = tuple(dict.fromkeys(self.axes))      # 중복 제거, 순서 유지
        self.sanctions = tuple(dict.fromkeys(self.sanctions))
        if not self.axes:
            raise ValueError("분류축을 하나 이상 선택해 주세요.")
        if not self.sanctions:
            raise ValueError("제재유형을 하나 이상 선택해 주세요.")
        for a in self.axes:
            axis_spec(a)                                  # 모르는 축이면 여기서 멈춘다
        for s in self.sanctions:
            if s not in STANDARD_SANCTIONS:
                raise ValueError(
                    f"알 수 없는 제재유형 '{s}' 입니다. "
                    f"쓸 수 있는 값: {', '.join(STANDARD_SANCTIONS)}"
                )

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg)


def _drop_empty_axes(cfg: MonthlyConfig) -> tuple:
    if cfg.drop_empty_axes is not None:
        return tuple(cfg.drop_empty_axes)
    return tuple(k for k, s in AXES.items() if s.drop_empty)


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

    # 기관유형 별칭 적용 (정부부처 → 국공립연구소 등).
    # 끄면 원자료 표기가 그대로 남아 '출연연구소'·'정부부처'가 따로 보인다.
    # 표준 7개 밖 값이 되므로 아래 '기타' 편입이 아니라 별도 행으로 살려 둔다.
    if cfg.org_alias_on:
        alias = resolve_rename_chains(cfg.org_alias)
        hits = org[org.isin(alias)].value_counts()
        for old, n in hits.items():
            cfg.log(f"  ! 기관유형 치환: {old} → {alias[old]} ({n:,}건)")
        cfg.resolved["org_alias_hits"] = {str(k): [alias[k], int(v)] for k, v in hits.items()}
        org = org.replace(alias)
    else:
        cfg.resolved["org_alias_hits"] = {}
        cfg.log("  ! 기관유형 별칭 치환을 끄고 원자료 표기를 그대로 씁니다")

    n_blank_org = int(org.eq("").sum())
    if cfg.org_alias_on:
        # 표준 7개에 없는 값과 공란은 '기타'로 편입한다.
        # 양식의 기관유형은 7개로 고정이고, 목록 밖 값을 남기면 그 표만 합계가 갈라진다.
        unlisted = org.ne("") & ~org.isin(ORG_LABELS)
        if unlisted.any():
            cnt = org[unlisted].value_counts()
            cfg.log(
                f"  ! 표준 목록에 없는 기관유형 {int(unlisted.sum()):,}건을 '{ORG_FALLBACK}'로 편입: "
                + ", ".join(f"{k} {v:,}건" for k, v in cnt.items())
            )
            cfg.resolved["org_to_other"] = {str(k): int(v) for k, v in cnt.items()}
        org = org.where(org.isin(ORG_LABELS), ORG_FALLBACK)
    elif n_blank_org:
        # 치환을 껐어도 공란은 표에서 빠지면 안 되므로 '기타'로만 모은다
        org = org.mask(org.eq(""), ORG_FALLBACK)
    if n_blank_org:
        cfg.log(
            f"  ! 연구수행주체가 두 열 모두 빈 행 {n_blank_org:,}건도 '{ORG_FALLBACK}'로 편입"
        )
    cfg.resolved["org_blank_to_other"] = n_blank_org
    out["연구수행주체(정제)"] = org

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
    # 공란을 '(부처 미지정)' 으로 바꾸는 일은 분류축 계층(_axis_series)이 맡는다.
    # 정책을 한 곳에 두어야 축이 늘어도 규칙이 갈라지지 않는다.
    out["소관부처"] = m.replace(rn)

    # 분류축 전용 열 — 없는 파일이면 col() 이 빈 값을 돌려주고,
    # 그 축을 고르면 aggregate 의 _guard_axis_columns 가 막는다.
    out["제재대상"] = _clean_text(col("제재대상"))
    out["과제유형"] = _clean_text(col("과제유형"))
    out["사업명"] = _clean_text(col("사업명"))

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
    #: 이 결과에 쓰인 분류축 (선택 순서)
    axes: list = field(default_factory=list)
    dropped: dict = field(default_factory=dict)
    #: 전처리 요약 (연구수행주체 출처 내역, 금액 변환 실패 등)
    prep: dict = field(default_factory=dict)

    def table(self, no: int) -> MonthlyTable:
        return next(t for t in self.tables if t.no == no)


def check_label(t: MonthlyTable) -> str:
    """검산 결과와 표를 잇는 키. 이 키를 만드는 곳은 여기 하나뿐이어야 한다.

    예전에는 monthly_pipeline 과 app.py 가 같은 문자열을 따로 조립했다. 어긋나면
    payload 쪽 .get(label, True) 기본값 때문에 모든 표가 조용히 '검산 통과'로 보인다."""
    return f"{t.no}. {t.axis}별 {t.sanction}"


def axis_spec(axis: str) -> AxisSpec:
    """분류축 정의를 찾는다.

    모르는 축을 조용히 부처로 떨어뜨리지 않고 즉시 멈춘다. 예전에는 if/else 의
    마지막 갈래가 부처였던 탓에, 오타 하나가 '부처별 표에 다른 이름표를 붙인'
    그럴듯하게 틀린 결과를 만들 수 있었다."""
    try:
        return AXES[axis]
    except KeyError:
        raise KeyError(
            f"알 수 없는 분류축 '{axis}' 입니다. 쓸 수 있는 값: {', '.join(AXES)}"
        ) from None


def _axis_series(pre: pd.DataFrame, axis: str, cfg: MonthlyConfig) -> pd.Series:
    """분류축 라벨 Series. 공란 정책까지 적용해 돌려준다.

    BLANK_FALLBACK 축은 여기서 빈 값이 사라지므로 _build_table 의
    dropped 계산(ax.eq(""))이 저절로 0 이 되고 cross_checks 가 통과한다."""
    spec = axis_spec(axis)
    if spec.column not in pre.columns:
        raise KeyError(
            f"'{axis}' 분류축에 필요한 열 '{spec.column}' 이(가) 전처리 결과에 없습니다."
        )
    s = _clean_text(pre[spec.column])
    if spec.blank == BLANK_FALLBACK:
        s = s.mask(s.eq(""), spec.blank_label)
    return s


def _std_labels(axis: str, cfg: MonthlyConfig) -> list[str]:
    """표준 분류 목록. 치환 규칙을 적용하고 공란 라벨을 맨 뒤에 붙인다.

    상위 N 축의 목록은 aggregate 가 미리 확정해 cfg.resolved["topn"] 에 넣어 둔다 —
    제재유형 3종이 같은 목록을 써야 표를 나란히 놓고 읽을 수 있다."""
    spec = axis_spec(axis)
    if spec.labels == LABELS_TOPN:
        out = [*(cfg.resolved.get("topn", {}).get(axis) or []), spec.other_label]
    else:
        table = {
            "org": lambda: resolve_rename_chains(cfg.org_alias) if cfg.org_alias_on else {},
            "ministry": lambda: resolve_rename_chains(cfg.ministry_rename),
        }.get(spec.normalize, dict)()
        # 치환으로 두 라벨이 한 이름이 되면 순서를 지키며 하나로 합친다
        out = list(dict.fromkeys(table.get(x, x) for x in spec.std))
    if spec.blank == BLANK_FALLBACK and spec.blank_label not in out:
        out.append(spec.blank_label)
    return out


def _build_table(
    pre: pd.DataFrame, years: list[int], no: int, title: str, sanction: str, axis: str,
    cfg: MonthlyConfig,
) -> MonthlyTable:
    spec = axis_spec(axis)
    sub = pre[pre["제재유형구분"].eq(sanction) & pre["처분연도"].isin(years)]
    ax = _axis_series(sub, axis, cfg)

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
        cfg.log(f"  ! [{no}] {axis}가 {spec.blank_note} 이 표에서 빠진 건수 "
                f"{dropped:,}건 (모집단 {base:,}건)")

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

    # '미지정/미상' 행은 값이 있을 때만 남긴다 — 0 인 행은 노이즈다.
    # (드롭 정책 축은 애초에 이 라벨이 없으므로 걸리지 않는다)
    if spec.blank == BLANK_FALLBACK and spec.blank_label in values:
        if not any((values[spec.blank_label]["건수"][c] or 0) for c in keys):
            labels = [l for l in labels if l != spec.blank_label]
            present = [p for p in present if p != spec.blank_label]
            values.pop(spec.blank_label, None)

    # 전 연도가 0인 행 제거 (부처 축 기본). 표준 목록이 길어 대부분 0인 축에만 적용한다.
    if axis in _drop_empty_axes(cfg):
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


def build_table_defs(cfg: MonthlyConfig) -> list[tuple]:
    """(번호, 제목, 제재유형, 분류축) 목록.

    표준 3축을 먼저 1~9번으로 채우고 추가 축을 10번부터 붙인다. 이 순서 규칙이 있어야
    표준 3축만 골랐을 때 결과가 예전 TABLES 상수와 완전히 같고, 축을 더 골라도
    1~9번의 뜻이 변하지 않는다(한글 양식·기존 산출물과 대조할 수 있어야 한다)."""
    std = [a for a in cfg.axes if a in STANDARD_AXES]
    extra = [a for a in cfg.axes if a not in STANDARD_AXES]
    defs, no = [], 0
    for block in (std, extra):
        for sanction in cfg.sanctions:
            for axis in block:
                no += 1
                word = axis_spec(axis).word
                defs.append((no, f"국가R&D사업 {sanction} 현황({word}별)", sanction, axis))
    return defs


def standard_tables(res: MonthlyResult) -> list:
    """한글 표준양식(표 9개)에 대응하는 표만 양식 순서대로 고른다.

    양식의 표는 위치로만 짝지어지고 분류축 이름·제목이 문서에 박혀 있어 다른 축을
    넣을 수 없다. 번호나 인덱스가 아니라 (제재유형, 축) 으로 고르는 이유는,
    축을 더 선택해 번호가 밀려도 양식에 엉뚱한 표가 들어가지 않게 하기 위해서다."""
    idx = {(t.sanction, t.axis): t for t in res.tables}
    missing = [f"{s}×{a}" for s in STANDARD_SANCTIONS for a in STANDARD_AXES
               if (s, a) not in idx]
    if missing:
        raise ValueError(
            "한글 표준양식은 제재사유·기관유형·부처 3개 분류축 × 제재유형 3종 = "
            "9개 표로 고정되어 있습니다.\n"
            "  다음 표가 없어 양식을 채울 수 없습니다: " + ", ".join(missing)
            + "\n  해당 분류축·제재유형을 다시 선택하시거나 엑셀로 저장해 주세요."
        )
    return [idx[(s, a)] for s in STANDARD_SANCTIONS for a in STANDARD_AXES]


def _guard_axis_columns(pre: pd.DataFrame, cfg: MonthlyConfig) -> None:
    """고른 축의 원천 열이 통째로 비어 있으면 멈춘다.

    그냥 두면 한 줄짜리 표가 나오는데 그 표의 합계는 모집단과 같아서
    integrity 도 cross_checks 도 통과해 버린다 — 아무 검사도 잡지 못하는
    '그럴듯하게 틀린 결과'라서 여기서 막는 수밖에 없다."""
    for axis in cfg.axes:
        spec = axis_spec(axis)
        src = spec.column.lstrip("_") if spec.labels == LABELS_TOPN else spec.column
        if src in pre.columns and _clean_text(pre[src]).eq("").all():
            raise ValueError(
                f"'{axis}' 분류축을 선택했지만 원자료의 '{src}' 열이 모두 비어 있습니다.\n"
                "  컬럼명 또는 헤더 행 설정을 확인해 주세요."
            )


def _apply_topn(pre: pd.DataFrame, years: list[int], cfg: MonthlyConfig) -> pd.DataFrame:
    """상위 N 축의 목록을 모집단 전체에서 한 번만 확정하고 나머지를 '기타'로 접는다.

    제재유형별로 따로 순위를 매기면 cross_checks 는 여전히 통과하지만('기타'가
    나머지를 흡수하므로 합계는 보존된다) 표마다 사업 목록이 달라져 나란히 놓고
    읽을 수 없다 — 어떤 자동 검사도 잡지 못하는 종류의 결함이라 여기서 못박는다."""
    in_range = pre["처분연도"].isin(years)
    for axis in cfg.axes:
        spec = axis_spec(axis)
        if spec.labels != LABELS_TOPN:
            continue
        src = spec.column.lstrip("_")
        n = int(cfg.top_n.get(axis, spec.top_n))
        s = _clean_text(pre[src])
        # 순위는 표가 실제로 보여주는 값(건수)으로 매긴다. 행 수로 매기면
        # 제재ID 가 없어 건수 0 인 행까지 순위에 끼어든다.
        pick = in_range & s.ne("")
        cnt = pre.loc[pick, "건수"].groupby(s[pick]).sum()
        # 동수는 이름순으로 끊는다 — 실행할 때마다 목록이 바뀌면 안 된다
        ranked = sorted(cnt.index, key=lambda k: (-int(cnt[k]), str(k)))
        top = ranked[:n]
        cfg.resolved.setdefault("topn", {})[axis] = list(top)
        pre[spec.column] = s.where(s.isin(top) | s.eq(""), spec.other_label)
        rest = len(ranked) - len(top)
        if rest:
            n_other = int((pre[spec.column].eq(spec.other_label) & in_range).sum())
            cfg.log(f"  ! {axis} 상위 {len(top)}개 외 {rest:,}종 {n_other:,}건을 "
                    f"'{spec.other_label}'로 묶었습니다")
    return pre


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

    _guard_axis_columns(pre, cfg)
    pre = _apply_topn(pre, years, cfg)

    tables = [
        _build_table(pre, years, no, title, sanction, axis, cfg)
        for no, title, sanction, axis in build_table_defs(cfg)
    ]
    cfg.log(f"[집계] 통계 {len(tables)}개 / 연도축 {years[0]}~{years[-1]}")
    return MonthlyResult(
        years=years, tables=tables, pre=pre, axes=list(cfg.axes),
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
        checks.append({"label": check_label(t), "ok": ok})
    return checks


def cross_checks(res: MonthlyResult) -> list[dict]:
    """같은 제재유형의 여러 표(분류축만 다름)는 모집단이 같으므로 합계가 같아야 한다.

    어긋나면 그 표에서만 빠진 건수를 함께 알려 준다. 실제로 갈라지는 경우는 하나뿐이다.
      - 제재사유가 9분류 어디에도 없는 행 -> 제재사유별 표에서만 빠짐
    나머지 축은 값이 비면 '(… 미상)' 같은 대체 라벨로 남으므로 빠지지 않는다.
    """
    out = []
    for sanction in dict.fromkeys(t.sanction for t in res.tables):
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
            "label": f"{sanction} 표 {len(group)}개 건수 합계 일치",
            "sanction": sanction,
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
