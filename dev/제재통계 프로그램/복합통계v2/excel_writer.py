# -*- coding: utf-8 -*-
"""
집계 결과를 엑셀로 출력.

xlsxwriter 로 직접 행을 쓴다. pandas.to_excel 은 셀 단위로 돌기 때문에
과제 3만 건 / 연도전개 16만 행 규모에서 두 배 이상 느리다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sanction_pipeline import (
    JUDGMENT_LABELS,
    JUDGMENT_ORDER,
    TOTAL_LABEL,
    AggregateResult,
)

ROW_ITEMS = [
    ("국가R&D연구비", "ref"),
    ("국가R&D과제수", "ref"),
    (JUDGMENT_LABELS["①"], "①"),
    (JUDGMENT_LABELS["②"], "②"),
    (JUDGMENT_LABELS["③"], "③"),
    ("소계(①+②+③)", "sub"),
    ("제재처분 비율(%)", "ratio"),
]

TASK_COLS = [
    "과제번호", "과제명", "소관부처", "사업명",
    "총연구기간시작연도", "총연구기간종료연도", "집계반영연도",
    "과제수행연도(원자료)", "처분연도", "제재유형", "제재대상", "판정",
    "제재ID", "레코드수",
]


# ---------------------------------------------------------------------------
# 데이터 프레임 구성
# ---------------------------------------------------------------------------

def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return int(f) if f == int(f) else round(f, 2)


def build_summary_frame(res: AggregateResult) -> pd.DataFrame:
    """hwpx 양식과 동일한 레이아웃."""
    cols = ["부처별", "항목"] + [str(y) for y in res.years] + ["합계*"]
    keys = [*res.years, "합계"]
    rows = []
    for m in [*res.ministries, TOTAL_LABEL]:
        for label, kind in ROW_ITEMS:
            rec = {"부처별": m, "항목": label}
            for name, key in zip(cols[2:], keys):
                if kind == "ref":
                    rec[name] = _num(res.ref(m, label, key))
                elif kind == "sub":
                    rec[name] = res.subtotal(m, key)
                elif kind == "ratio":
                    r = res.ratio(m, key)
                    rec[name] = None if r is None else round(r, 2)
                else:
                    rec[name] = res.count(m, kind, key)
            rows.append(rec)
    return pd.DataFrame(rows, columns=cols)


def build_pivot_frame(res: AggregateResult) -> pd.DataFrame:
    """부처 x 판정 x 연도 (workflow 피벗 노드 재현)."""
    cols = ["소관부처", "판정"] + [str(y) for y in res.years] + ["합계*"]
    rows = []
    for m in [*res.ministries, TOTAL_LABEL]:
        for c in JUDGMENT_ORDER:
            rec = {"소관부처": m, "판정": JUDGMENT_LABELS[c]}
            for y in res.years:
                rec[str(y)] = res.count(m, c, y)
            rec["합계*"] = res.count(m, c, "합계")
            rows.append(rec)
        rec = {"소관부처": m, "판정": "소계"}
        for y in res.years:
            rec[str(y)] = res.subtotal(m, y)
        rec["합계*"] = res.subtotal(m, "합계")
        rows.append(rec)
    return pd.DataFrame(rows, columns=cols)


def build_task_frame(res: AggregateResult) -> pd.DataFrame:
    t = res.tasks
    cols = [c for c in TASK_COLS if c in t.columns]
    out = t[cols].copy()
    return out.sort_values(["소관부처", "판정", "과제번호"], kind="stable")


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

class _Fmt:
    def __init__(self, wb):
        base = {"font_name": "맑은 고딕", "font_size": 10, "border": 1,
                "border_color": "#A6A6A6"}
        self.head = wb.add_format({**base, "bold": True, "bg_color": "#D9E1F2",
                                   "align": "center", "valign": "vcenter",
                                   "text_wrap": True})
        self.label = wb.add_format({**base, "align": "left", "valign": "vcenter"})
        self.name = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                   "text_wrap": True, "bold": True})
        self.num = wb.add_format({**base, "align": "right", "num_format": "#,##0"})
        self.ratio = wb.add_format({**base, "align": "right", "num_format": "0.00"})
        self.sub_label = wb.add_format({**base, "align": "left", "bold": True,
                                        "bg_color": "#F2F2F2"})
        self.sub_num = wb.add_format({**base, "align": "right", "bold": True,
                                      "bg_color": "#F2F2F2", "num_format": "#,##0"})
        self.sub_ratio = wb.add_format({**base, "align": "right", "bold": True,
                                        "bg_color": "#F2F2F2", "num_format": "0.00"})
        self.tot_label = wb.add_format({**base, "align": "left", "bg_color": "#FFF2CC"})
        self.tot_num = wb.add_format({**base, "align": "right", "bg_color": "#FFF2CC",
                                      "num_format": "#,##0"})
        self.tot_ratio = wb.add_format({**base, "align": "right", "bg_color": "#FFF2CC",
                                        "num_format": "0.00"})
        self.tot_name = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                       "bold": True, "bg_color": "#FFF2CC",
                                       "text_wrap": True})
        self.plain = wb.add_format({"font_name": "맑은 고딕", "font_size": 10})
        self.plain_num = wb.add_format({"font_name": "맑은 고딕", "font_size": 10,
                                        "num_format": "#,##0"})


def _write_summary(wb, res: AggregateResult, df: pd.DataFrame, f: _Fmt) -> None:
    ws = wb.add_worksheet("집계표(양식)")
    ncol = len(df.columns)
    block = len(ROW_ITEMS)

    ws.write_row(0, 0, list(df.columns), f.head)
    ws.set_row(0, 30)

    vals = df.values.tolist()
    for i, row in enumerate(vals):
        r = i + 1
        kind = ROW_ITEMS[i % block][1]
        is_total = row[0] == TOTAL_LABEL
        if is_total:
            lab_f, num_f = f.tot_label, (f.tot_ratio if kind == "ratio" else f.tot_num)
        elif kind in ("sub", "ratio"):
            lab_f, num_f = f.sub_label, (f.sub_ratio if kind == "ratio" else f.sub_num)
        else:
            lab_f, num_f = f.label, (f.ratio if kind == "ratio" else f.num)
        ws.write(r, 1, row[1], lab_f)
        for c in range(2, ncol):
            v = row[c]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                ws.write_blank(r, c, None, num_f)
            else:
                ws.write_number(r, c, v, num_f)

    # 부처명 열 병합
    for bi, m in enumerate([*res.ministries, TOTAL_LABEL]):
        top = 1 + bi * block
        fmt = f.tot_name if m == TOTAL_LABEL else f.name
        ws.merge_range(top, 0, top + block - 1, 0, m, fmt)

    ws.set_column(0, 0, 22)
    ws.set_column(1, 1, 24)
    ws.set_column(2, ncol - 1, 11)
    ws.freeze_panes(1, 2)


def _write_table(wb, name: str, df: pd.DataFrame, f: _Fmt,
                 freeze_col: int = 0, autofilter: bool = False) -> None:
    ws = wb.add_worksheet(name)
    ws.write_row(0, 0, [str(c) for c in df.columns], f.head)

    numeric = [
        bool(pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]))
        for c in df.columns
    ]
    for r, row in enumerate(df.itertuples(index=False, name=None), start=1):
        for c, v in enumerate(row):
            if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
                continue
            if numeric[c]:
                ws.write_number(r, c, v, f.plain_num)
            else:
                ws.write_string(r, c, str(v), f.plain)

    head = df.head(400)
    for c, col in enumerate(df.columns):
        try:
            w = max([len(str(col))] + [len(str(v)) for v in head[col]])
        except Exception:  # noqa: BLE001
            w = 14
        ws.set_column(c, c, min(max(w + 3, 9), 52))
    ws.freeze_panes(1, freeze_col)
    if autofilter and len(df):
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)


def write_excel(res: AggregateResult, path: str, include_long: bool = False) -> str:
    """집계 결과를 엑셀로 저장.

    include_long=True 면 '연도전개' 시트(과제 x 연도 long 포맷)를 함께 넣는다.
    행 수가 크게 늘어 저장이 느려지므로 기본은 제외이며,
    같은 정보는 '과제단위_판정' 시트의 집계반영연도 열로 확인할 수 있다.
    """
    import xlsxwriter

    wb = xlsxwriter.Workbook(path, {"constant_memory": False, "default_date_format": "yyyy-mm-dd"})
    f = _Fmt(wb)
    try:
        _write_summary(wb, res, build_summary_frame(res), f)
        _write_table(wb, "부처별_판정별", build_pivot_frame(res), f, freeze_col=2)
        _write_table(wb, "과제단위_판정", build_task_frame(res), f,
                     freeze_col=3, autofilter=True)
        if include_long:
            _write_table(wb, "연도전개", res.long, f, freeze_col=1)
    finally:
        wb.close()
    return path
