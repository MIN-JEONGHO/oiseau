# -*- coding: utf-8 -*-
"""검토 결과 리포트 출력 (엑셀 / 마크다운 / 콘솔)."""
from __future__ import annotations

import datetime as _dt
import os
from typing import List

from . import CRITERIA_VERSION
from .models import Level, Result

FILL = {"반려": "FFB2263B", "보완필요": "FFC07A00", "확인권장": "FF3D6F9E", "적합": "FF1F6F58"}


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


# ---- 콘솔 --------------------------------------------------------------
def to_console(results: List[Result]) -> str:
    lines: List[str] = []
    for res in results:
        c = res.counts()
        lines.append("=" * 78)
        lines.append(f"[{res.verdict.value}] {res.file_name}  "
                     f"({res.rows}행 × {res.cols}열, 인코딩 {res.encoding or '-'})")
        lines.append(f"반려 {c['반려']} · 보완필요 {c['보완필요']} · 확인권장 {c['확인권장']}")
        if res.error:
            lines.append(f"  ! {res.error}")
        lines.append("-" * 78)
        for f in res.sorted_findings():
            lines.append(f"  [{f.level.value}] {f.rule_id} {f.item}")
            lines.append(f"     {f.message}")
            if f.fix:
                lines.append(f"     ▸ 조치: {f.fix}")
            if f.locations:
                more = f" 외 {f.count - len(f.locations[:12])}건" if f.count > 12 else ""
                lines.append(f"     ▸ 위치: {', '.join(f.locations[:12])}{more}")
            if f.samples:
                lines.append(f"     ▸ 예시: {' | '.join(f.samples[:4])}")
        if res.suggested_base_date:
            lines.append(f"  · 데이터 기준일 후보(파일 내 최근 날짜): {res.suggested_base_date}")
        if not res.findings:
            lines.append("  지적사항 없음. 기준을 모두 충족합니다.")
    return "\n".join(lines)


# ---- 엑셀 --------------------------------------------------------------
def to_xlsx(results: List[Result], path: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "검토요약"
    head = ["파일명", "판정", "행", "열", "인코딩", "구분자",
            "반려", "보완필요", "확인권장", "기준일 후보"]
    ws.append(head)
    for res in results:
        c = res.counts()
        ws.append([res.file_name, res.verdict.value, res.rows, res.cols,
                   res.encoding or "-", res.delimiter or "-",
                   c["반려"], c["보완필요"], c["확인권장"],
                   res.suggested_base_date or "-"])

    ws2 = wb.create_sheet("상세지적사항")
    head2 = ["파일명", "등급", "기준조항", "항목", "지적내용", "조치방법",
             "건수", "위치", "값 예시"]
    ws2.append(head2)
    for res in results:
        for f in res.sorted_findings():
            ws2.append([res.file_name, f.level.value, f.rule_id, f.item,
                        f.message, f.fix, f.count,
                        ", ".join(f.locations[:50]), " | ".join(f.samples[:5])])

    bold = Font(bold=True, color="FFFFFFFF")
    header_fill = PatternFill("solid", fgColor="FF16202B")
    for sheet, widths in ((ws, [34, 10, 8, 8, 12, 12, 8, 10, 10, 14]),
                          (ws2, [28, 10, 12, 22, 60, 60, 8, 34, 34])):
        for i, w in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(i)].width = w
        for cell in sheet[1]:
            cell.font = bold
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"

    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        lv = row[1].value
        if lv in FILL:
            row[1].fill = PatternFill("solid", fgColor=FILL[lv])
            row[1].font = Font(bold=True, color="FFFFFFFF")
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        lv = row[1].value
        if lv in FILL:
            row[1].fill = PatternFill("solid", fgColor=FILL[lv])
            row[1].font = Font(bold=True, color="FFFFFFFF")

    wb.save(path)
    return path
