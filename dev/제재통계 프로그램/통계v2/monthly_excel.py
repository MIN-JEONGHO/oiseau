# -*- coding: utf-8 -*-
"""월별통계 결과를 엑셀로 출력 — 결과표 9시트 + 전처리 + 검산."""
from __future__ import annotations

import numpy as np
import pandas as pd

from monthly_pipeline import TOTAL_LABEL, MonthlyResult, display_label, integrity

PRE_COLS = [
    "처분연도", "제재유형구분", "연구수행주체(정제)", "제재사유(기본법)",
    "제재사유(혁신법)", "미납금액", "대상금액(원)", "납부금액(원)",
    "소관부처", "제재ID", "건수", "_제재사유",
]


class _Fmt:
    def __init__(self, wb):
        base = {"font_name": "맑은 고딕", "font_size": 10, "border": 1,
                "border_color": "#A6A6A6"}
        self.head = wb.add_format({**base, "bold": True, "bg_color": "#D9E1F2",
                                   "align": "center", "valign": "vcenter",
                                   "text_wrap": True})
        self.title = wb.add_format({"font_name": "맑은 고딕", "font_size": 12,
                                    "bold": True})
        self.unit = wb.add_format({"font_name": "맑은 고딕", "font_size": 9,
                                   "font_color": "#57686F"})
        self.label = wb.add_format({**base, "align": "left", "valign": "vcenter",
                                    "text_wrap": True})
        self.label_extra = wb.add_format({**base, "align": "left",
                                          "valign": "vcenter", "text_wrap": True,
                                          "font_color": "#8C3A2B", "italic": True})
        self.item = wb.add_format({**base, "align": "center", "font_size": 9,
                                   "font_color": "#57686F"})
        self.cnt = wb.add_format({**base, "align": "right", "num_format": "#,##0"})
        self.money = wb.add_format({**base, "align": "right", "num_format": "#,##0.0"})
        self.pct = wb.add_format({**base, "align": "right", "num_format": "0.0"})
        self.tot_label = wb.add_format({**base, "align": "left", "bold": True,
                                        "bg_color": "#FFF2CC", "valign": "vcenter"})
        self.tot_item = wb.add_format({**base, "align": "center", "font_size": 9,
                                       "bg_color": "#FFF2CC"})
        self.tot_cnt = wb.add_format({**base, "align": "right", "bold": True,
                                      "bg_color": "#FFF2CC", "num_format": "#,##0"})
        self.tot_money = wb.add_format({**base, "align": "right", "bold": True,
                                        "bg_color": "#FFF2CC", "num_format": "#,##0.0"})
        self.tot_pct = wb.add_format({**base, "align": "right", "bold": True,
                                      "bg_color": "#FFF2CC", "num_format": "0.0"})
        self.plain = wb.add_format({"font_name": "맑은 고딕", "font_size": 10})
        self.plain_num = wb.add_format({"font_name": "맑은 고딕", "font_size": 10,
                                        "num_format": "#,##0"})
        self.ok = wb.add_format({**base, "align": "center", "bold": True,
                                 "font_color": "#1F5F5B"})
        self.bad = wb.add_format({**base, "align": "center", "bold": True,
                                  "font_color": "#8C3A2B"})

    def num(self, item: str, total: bool = False):
        if item == "건수":
            return self.tot_cnt if total else self.cnt
        if item == "미납률":
            return self.tot_pct if total else self.pct
        return self.tot_money if total else self.money


def _write_table(wb, res: MonthlyResult, stat, f: _Fmt) -> None:
    ws = wb.add_worksheet(f"{stat.no}")
    years = res.years
    ws.write(0, 0, f"{stat.no}. {stat.title}", f.title)
    ws.write(1, 0, f"(단위 : {stat.unit})", f.unit)

    r0 = 3
    ws.write(r0, 0, stat.axis, f.head)
    ws.write(r0, 1, "항목", f.head)
    for i, y in enumerate(years):
        ws.write_number(r0, 2 + i, y, f.head)
    ws.write(r0, 2 + len(years), "합 계", f.head)

    keys = [*years, "합계"]
    rows = [*stat.labels, TOTAL_LABEL]
    n = len(stat.items)
    r = r0 + 1
    for label in rows:
        is_tot = label == TOTAL_LABEL
        is_extra = label in stat.extra_labels
        lab_f = f.tot_label if is_tot else (f.label_extra if is_extra else f.label)
        disp = display_label(label)
        if n > 1:
            ws.merge_range(r, 0, r + n - 1, 0, disp, lab_f)
        else:
            ws.write(r, 0, disp, lab_f)
        for k, item in enumerate(stat.items):
            ws.write(r + k, 1, item, f.tot_item if is_tot else f.item)
            for c, col in enumerate(keys):
                v = stat.get(label, item, col)
                cell_f = f.num(item, is_tot)
                # 원본 워크북과 같이 0 은 공란으로 둔다 (IF(..=0,""))
                if v is None or not v:
                    ws.write_blank(r + k, 2 + c, None, cell_f)
                else:
                    ws.write_number(r + k, 2 + c, round(float(v), 4), cell_f)
        r += n

    ws.set_column(0, 0, 34)
    ws.set_column(1, 1, 9)
    ws.set_column(2, 2 + len(years), 11)
    ws.freeze_panes(r0 + 1, 2)

    if stat.extra_labels:
        ws.write(
            r + 1, 0,
            "※ 표준 목록에 없어 추가한 분류: " + ", ".join(stat.extra_labels),
            f.unit,
        )


def _write_pre(wb, res: MonthlyResult, f: _Fmt) -> None:
    ws = wb.add_worksheet("전처리")
    df = res.pre[[c for c in PRE_COLS if c in res.pre.columns]].rename(
        columns={"_제재사유": "제재사유(9분류)"}
    )
    ws.write_row(0, 0, [str(c) for c in df.columns], f.head)
    numeric = [
        bool(pd.api.types.is_numeric_dtype(df[c])) for c in df.columns
    ]
    for r, row in enumerate(df.itertuples(index=False, name=None), start=1):
        for c, v in enumerate(row):
            if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
                continue
            if numeric[c]:
                ws.write_number(r, c, float(v), f.plain_num)
            else:
                ws.write_string(r, c, str(v), f.plain)
    for c, col in enumerate(df.columns):
        w = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)])
        ws.set_column(c, c, min(max(w + 3, 9), 40))
    ws.freeze_panes(1, 0)
    if len(df):
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)


def _write_audit(wb, res: MonthlyResult, f: _Fmt) -> None:
    ws = wb.add_worksheet("검산")
    ws.write(0, 0, "검산", f.title)
    ws.write_row(2, 0, ["통계", "분류 합 = 합 계 행", "연도별 합 = 합계 열"], f.head)
    for i, c in enumerate(integrity(res)):
        ws.write(3 + i, 0, c["label"], f.label)
        mark = "✓ 일치" if c["ok"] else "✕ 불일치"
        ws.write(3 + i, 1, mark, f.ok if c["ok"] else f.bad)
        ws.write(3 + i, 2, mark, f.ok if c["ok"] else f.bad)
    r = 4 + len(res.tables)
    ws.write(r, 0, "연도축", f.head)
    ws.write(r, 1, f"{res.years[0]}~{res.years[-1]}", f.label)
    ws.write(r + 1, 0, "전처리 행수", f.head)
    ws.write_number(r + 1, 1, len(res.pre), f.plain_num)
    ws.write(r + 2, 0, "연도축 밖 제외", f.head)
    ws.write_number(r + 2, 1, int(res.dropped.get("연도밖", 0)), f.plain_num)
    ws.set_column(0, 0, 30)
    ws.set_column(1, 2, 20)


def write_monthly_excel(res: MonthlyResult, path: str, include_pre: bool = True) -> str:
    import xlsxwriter

    wb = xlsxwriter.Workbook(path, {"constant_memory": False})
    f = _Fmt(wb)
    try:
        for stat in res.tables:
            _write_table(wb, res, stat, f)
        _write_audit(wb, res, f)
        if include_pre:
            _write_pre(wb, res, f)
    finally:
        wb.close()
    return path
