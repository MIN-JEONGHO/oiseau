# -*- coding: utf-8 -*-
"""검토 결과 리포트 출력 (엑셀 / 마크다운 / 콘솔)."""
from __future__ import annotations

import datetime as _dt
import os
from typing import List

from . import CRITERIA_VERSION, DOMAIN_LABEL
from .models import Level, Result

FILL = {"반려": "FFB2263B", "보완필요": "FFC07A00", "확인권장": "FF3D6F9E", "적합": "FF1F6F58"}


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _scale(res: Result) -> str:
    """규모 한 줄. 파일데이터는 행×열, OPEN API 는 오퍼레이션·파라메터 수."""
    if res.domain == "api":
        return (f"오퍼레이션 {res.rows}개 × 파라메터 {res.cols}개, "
                f"등록유형 {res.api.get('reg_type') or '-'}")
    return f"{res.rows}행 × {res.cols}열, 인코딩 {res.encoding or '-'}"


# ---- 콘솔 --------------------------------------------------------------
def to_console(results: List[Result]) -> str:
    lines: List[str] = []
    for res in results:
        c = res.counts()
        lines.append("=" * 78)
        lines.append(f"[{res.verdict.value}] {res.file_name}  "
                     f"({DOMAIN_LABEL.get(res.domain, res.domain)} · {_scale(res)})")
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
    head = ["구분", "대상", "판정", "행 · 오퍼레이션", "열 · 파라메터",
            "인코딩 · 등록유형", "구분자 · 응답포맷",
            "반려", "보완필요", "확인권장", "기준일 후보"]
    ws.append(head)
    for res in results:
        c = res.counts()
        api = res.domain == "api"
        ws.append([DOMAIN_LABEL.get(res.domain, res.domain), res.file_name,
                   res.verdict.value, res.rows, res.cols,
                   (res.api.get("reg_type") if api else res.encoding) or "-",
                   ("+".join(res.api.get("formats") or []) if api
                    else res.delimiter) or "-",
                   c["반려"], c["보완필요"], c["확인권장"],
                   res.suggested_base_date or "-"])

    ws2 = wb.create_sheet("상세지적사항")
    head2 = ["구분", "대상", "등급", "기준조항", "항목", "지적내용", "조치방법",
             "건수", "위치", "값 예시"]
    ws2.append(head2)
    for res in results:
        label = DOMAIN_LABEL.get(res.domain, res.domain)
        for f in res.sorted_findings():
            ws2.append([label, res.file_name, f.level.value, f.rule_id, f.item,
                        f.message, f.fix, f.count,
                        ", ".join(f.locations[:50]), " | ".join(f.samples[:5])])

    _api_sheets(wb, results)

    bold = Font(bold=True, color="FFFFFFFF")
    header_fill = PatternFill("solid", fgColor="FF16202B")
    for sheet, widths in ((ws, [11, 30, 10, 14, 14, 16, 16, 8, 10, 10, 14]),
                          (ws2, [11, 24, 10, 12, 20, 58, 58, 8, 32, 32])):
        for i, w in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(i)].width = w
        for cell in sheet[1]:
            cell.font = bold
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"

    # 판정 열은 두 시트에서 자리가 다르다 (요약 3열 · 상세 3열)
    for sheet, lv_idx in ((ws, 2), (ws2, 2)):
        for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
            lv = row[lv_idx].value
            if lv in FILL:
                row[lv_idx].fill = PatternFill("solid", fgColor=FILL[lv])
                row[lv_idx].font = Font(bold=True, color="FFFFFFFF")
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    wb.save(path)
    return path


def _api_sheets(wb, results: List[Result]) -> None:
    """OPEN API 검토 결과가 있으면 오퍼레이션·파라메터 시트를 덧붙인다.

    지적사항만으로는 '무엇을 보고 그렇게 판정했는지' 되짚기 어려워서, 프로그램이
    실제로 읽어 들인 명세를 그대로 남긴다.
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    apis = [r for r in results if r.domain == "api" and r.api.get("ops")]
    if not apis:
        return

    ws = wb.create_sheet("API명세")
    ws.append(["대상", "오퍼레이션(국문)", "오퍼레이션(영문)", "전송방식", "URL",
               "구분", "항목명(영문)", "항목명(국문)", "항목유형", "필수",
               "샘플", "설명"])
    for res in apis:
        for op in res.api.get("ops") or []:
            params = [*(op.get("request") or []), *(op.get("response") or [])]
            if not params:
                ws.append([res.file_name, op.get("name_ko"), op.get("name_en"),
                           op.get("method"), op.get("url"), "-", "-", "-", "-",
                           "-", "-", "(파라메터 없음)"])
                continue
            for p in params:
                req = p.get("required")
                ws.append([res.file_name, op.get("name_ko"), op.get("name_en"),
                           op.get("method"), op.get("url"),
                           "요청" if p.get("where") == "request" else "응답",
                           p.get("name"), p.get("ko_name"), p.get("type"),
                           "필수" if req else ("옵션" if req is False else "-"),
                           p.get("sample"), p.get("desc")])

    codes = [(r, c) for r in apis for c in (r.api.get("codes") or [])]
    probes = [(r, p) for r in apis for p in (r.api.get("probes") or [])]
    if codes:
        we = wb.create_sheet("API에러코드")
        we.append(["대상", "에러코드", "에러메시지", "설명"])
        for r, c in codes:
            we.append([r.file_name, c.get("code"), c.get("message"), c.get("desc")])
    if probes:
        wp = wb.create_sheet("API실호출")
        wp.append(["대상", "호출 URL", "상태코드", "응답시간(초)", "Content-Type",
                   "응답형태", "응답 항목", "오류"])
        for r, p in probes:
            wp.append([r.file_name, p.get("called"), p.get("status"),
                       p.get("elapsed"), p.get("content_type"), p.get("body_kind"),
                       ", ".join((p.get("fields") or [])[:40]), p.get("error")])

    bold = Font(bold=True, color="FFFFFFFF")
    fill = PatternFill("solid", fgColor="FF16202B")
    widths = {"API명세": [22, 22, 18, 9, 42, 7, 20, 18, 11, 7, 16, 46],
              "API에러코드": [22, 12, 34, 46], "API실호출": [22, 46, 10, 12, 26, 10, 40, 34]}
    for title, ws_widths in widths.items():
        if title not in wb.sheetnames:
            continue
        sheet = wb[title]
        for i, w in enumerate(ws_widths, start=1):
            sheet.column_dimensions[get_column_letter(i)].width = w
        for cell in sheet[1]:
            cell.font = bold
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"
        for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
