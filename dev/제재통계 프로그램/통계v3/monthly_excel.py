# -*- coding: utf-8 -*-
"""월별통계 결과를 엑셀로 출력 — 결과표 9시트 + 전처리 + 검산."""
from __future__ import annotations

import numpy as np
import pandas as pd

from monthly_pipeline import (
    TOTAL_LABEL,
    MonthlyResult,
    cross_checks,
    display_label,
    integrity,
)

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
                # 양식 각주대로 '당해 연도 미발생'만 공란으로 둔다.
                # 미납률 0% 는 전액 납부를 뜻하므로 0 을 그대로 쓴다.
                occurred = bool(stat.get(label, "부과액", col))
                blank = (
                    v is None
                    or (item == "건수" and not v)
                    or (item != "건수" and not occurred)
                )
                if blank:
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

    # 1) 표 간 검산 — 같은 제재유형의 세 표는 건수 합계가 같아야 한다
    ws.write(2, 0, "표 간 · 같은 제재유형의 세 표 건수 합계", f.unit)
    ws.write_row(3, 0, ["제재유형", "결과", "모집단", "제재사유별", "기관유형별",
                        "부처별", "빠진 건수"], f.head)
    r = 4
    for c in cross_checks(res):
        s = c["label"].split()[0]
        ws.write(r, 0, s, f.label)
        ws.write(r, 1, "✓ 일치" if c["ok"] else "✕ 불일치", f.ok if c["ok"] else f.bad)
        ws.write_number(r, 2, c["base"], f.cnt)
        for i, ax in enumerate(("제재사유", "기관유형", "부처")):
            v = c["sums"].get(ax)
            cell = f.cnt if (v is None or v == c["base"]) else f.bad
            if v is None:
                ws.write_blank(r, 3 + i, None, cell)
            else:
                ws.write_number(r, 3 + i, v, cell)
        miss = " · ".join(
            f"{t.axis} −{t.dropped_count:,}"
            for t in res.tables if t.sanction == s and t.dropped_count
        )
        ws.write(r, 6, miss, f.label)
        r += 1

    # 2) 표 안쪽 검산
    r += 1
    ws.write(r, 0, "표 안쪽 · 분류 합과 연도 합", f.unit)
    ws.write_row(r + 1, 0, ["통계", "분류 합 = 합 계 행", "연도별 합 = 합계 열"], f.head)
    r += 2
    for c in integrity(res):
        ws.write(r, 0, c["label"], f.label)
        mark = "✓ 일치" if c["ok"] else "✕ 불일치"
        ws.write(r, 1, mark, f.ok if c["ok"] else f.bad)
        ws.write(r, 2, mark, f.ok if c["ok"] else f.bad)
        r += 1

    # 3) 전처리 내역
    src = res.prep.get("org_source") or {}
    bad_money = res.prep.get("money_unparsed") or {}
    r += 1
    ws.write(r, 0, "전처리 내역", f.unit)
    r += 1
    rows = [
        ("연구수행주체 · 정제 값 사용", src.get("정제사용")),
        ("연구수행주체 · L열로 보완", src.get("L열보완")),
        ("연구수행주체 · 두 열 불일치(정제 채택)", src.get("불일치")),
        ("연구수행주체 · 두 열 모두 공란", src.get("둘다공란")),
    ]
    for label, val in rows:
        if val is None:
            continue
        ws.write(r, 0, label, f.label)
        ws.write_number(r, 1, int(val), f.plain_num)
        r += 1
    for name, n in bad_money.items():
        ws.write(r, 0, f"{name} · 숫자 변환 실패(0 처리)", f.label)
        ws.write_number(r, 1, int(n), f.bad)
        r += 1
    if bad_money:
        ws.write(r, 0,
                 "※ 금액이 텍스트로 저장된 파일일 수 있습니다. 합계가 실제보다 작습니다.",
                 f.unit)
        r += 1

    # 4) 읽은 범위
    r += 1
    for label, val in (
        ("연도축", f"{res.years[0]}~{res.years[-1]}"),
        ("전처리 행수", len(res.pre)),
        ("연도축 밖 제외", int(res.dropped.get("연도밖", 0))),
        ("집계 대상 아닌 제재유형", ", ".join(res.dropped.get("제재유형외", [])) or "없음"),
    ):
        ws.write(r, 0, label, f.head)
        if isinstance(val, int):
            ws.write_number(r, 1, val, f.plain_num)
        else:
            ws.write(r, 1, val, f.label)
        r += 1

    ws.write(r + 1, 0,
             "※ 세 표의 합계가 다르면: 제재사유가 9분류에 없는 행은 제재사유별 표에서, "
             "연구수행주체가 빈 행은 기관유형별 표에서 각각 빠집니다.", f.unit)
    ws.set_column(0, 0, 30)
    ws.set_column(1, 6, 15)


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
