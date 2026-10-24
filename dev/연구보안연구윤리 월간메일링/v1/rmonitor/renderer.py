# -*- coding: utf-8 -*-
"""수집 데이터(JSON) → 완성 HTML 렌더링.

원본 템플릿의 G-Cloud 호환 규칙을 그대로 지킨다.
  · <style> 태그·미디어쿼리·class 사용 금지 (모든 CSS 인라인)
  · 배경색은 <td> 에만 지정
  · border-radius, <ul>, <ol>, <hr>, <h1~h6> 사용 금지
"""
from __future__ import annotations

from typing import Any, Dict, List

from .profiles import COUNTRY_NAMES, ReportProfile
from .utils import esc, esc_inline, safe_url

TBL = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"')


def render(profile: ReportProfile, data: Dict[str, Any]) -> str:
    if profile.key == "security":
        return _render_security(profile, data)
    return _render_ethics(profile, data)


def _grouped(data: Dict[str, Any]) -> Dict[str, List[dict]]:
    g: Dict[str, List[dict]] = {}
    for issue in data["issues"]:
        g.setdefault(issue["country"], []).append(issue)
    return g


def _link_block(issue: dict, color: str, bold: bool = False) -> str:
    """원문/보조 링크 줄."""
    weight = " font-weight:bold;" if bold else ""
    href = safe_url(issue.get("source_url"))
    out = (f'🔗 <a href="{href}" style="color:{color}; text-decoration:underline;{weight}">'
           f'원문 보기</a>')
    sub = safe_url(issue.get("sub_url"))
    if sub:
        label = esc(issue.get("sub_label")) or "보조 출처"
        out += (f' | 보조: <a href="{sub}" style="color:{color}; text-decoration:underline;'
                f'{weight}">{label}</a>')
    return out


# ==========================================================================
# 연구보안 리포트
# ==========================================================================
def _render_security(p: ReportProfile, d: Dict[str, Any]) -> str:
    A = p.accent
    period = d["period"]
    grouped = _grouped(d)
    h: List[str] = []
    add = h.append

    add(f'{TBL} style="background-color:#f4f6f8; padding:16px 8px;">')
    add('<tr><td align="center">')
    add(f'{TBL} style="max-width:{p.max_width}px; width:100%; background-color:#ffffff; '
        f'font-family:{p.font_family}; color:#222222; line-height:1.65;">')

    # ---- 헤더 ----
    add('<tr>')
    add(f'<td style="background-color:{A}; padding:28px 30px;">')
    add(f'<div style="font-size:23px; color:#ffffff; font-weight:bold; line-height:1.4;">'
        f'{esc(p.title_kr)}</div>')
    add(f'<div style="font-size:13px; color:#c9d6e5; margin-top:6px;">{esc(p.title_en)} | '
        f'{esc(d["report_month"])}</div>')
    add('</td></tr>')

    # ---- 리포트 정보 ----
    add('<tr><td style="padding:0;">')
    add(f'{TBL} style="border-collapse:collapse; font-size:13px;">')
    info_rows = [("수집 기간", f'{period["start"]} ~ {period["end"]} (KST)'),
                 ("발행일", period["report_date"])] + list(p.scope_rows)
    for i, (label, value) in enumerate(info_rows):
        width = ' width="130"' if i == 0 else ""
        add('<tr>')
        add(f'<td{width} style="background-color:{p.accent_soft}; padding:10px 14px; '
            f'border:1px solid #d5dee7; font-weight:bold; color:{A};">{esc(label)}</td>')
        add(f'<td style="padding:10px 14px; border:1px solid #d5dee7;">{esc(value)}</td>')
        add('</tr>')
    add('</table>')
    add('</td></tr>')

    # ---- 1. 핵심 요약 ----
    add('<tr><td style="padding:28px 20px 0 20px;">')
    add(f'<div style="font-size:18px; color:{A}; font-weight:bold; border-left:5px solid {A}; '
        f'padding-left:10px; margin-bottom:12px;">1. 이달의 핵심 요약 (Executive Summary)</div>')
    add(f'{TBL} style="font-size:14px; line-height:1.7; color:#222222;">')
    summaries = d["executive_summary"] or ["이번 호에는 요약할 신규 이슈가 확인되지 않았다."]
    for i, s in enumerate(summaries):
        width = ' width="20"' if i == 0 else ""
        add(f'<tr><td valign="top"{width} style="padding:0 0 8px 0; color:{A}; '
            f'font-weight:bold;">·</td>'
            f'<td style="padding:0 0 8px 0;">{esc_inline(s)}</td></tr>')
    add('</table>')
    add('</td></tr>')

    # ---- 2. G7 및 EU ----
    add('<tr><td style="padding:30px 20px 14px 20px;">')
    add(f'<div style="font-size:18px; color:{A}; font-weight:bold; border-left:5px solid {A}; '
        f'padding-left:10px;">2. G7 주요국 및 EU 연구보안 이슈</div>')
    add('</td></tr>')

    for code in p.countries:
        name, flag = COUNTRY_NAMES[code]
        issues = grouped.get(code, [])
        add('<tr><td style="padding:0 20px 16px 20px;">')
        add(f'{TBL} style="border:1px solid #d5dee7;">')
        add(f'<tr><td style="background-color:{A}; color:#ffffff; padding:8px 14px; '
            f'font-size:15px; font-weight:bold;">{flag} {esc(name)}</td></tr>')
        if issues:
            for idx, issue in enumerate(issues):
                border = ("border-bottom:1px dashed #d5dee7;" if idx < len(issues) - 1 else "")
                add(f'<tr><td style="padding:14px; {border}">')
                title = f'<b>{esc(issue["title_kr"])}</b>'
                if issue.get("title_original"):
                    title += f' (원문: <i>{esc(issue["title_original"])}</i>)'
                add(f'<div style="font-size:14px; margin-bottom:4px;">{title}</div>')
                add(f'<div style="font-size:12px; color:#666666; margin-bottom:4px;">'
                    f'{esc(issue["org"])} | {esc(issue["date"])} | {esc(issue["category"])}</div>')
                add(f'<div style="font-size:13px; margin-bottom:6px;">{esc(issue["content"])}</div>')
                add(f'<div style="font-size:13px; word-break:break-all;">'
                    f'{_link_block(issue, p.link_color)}</div>')
                add('</td></tr>')
        else:
            note = d["no_issue_countries"].get(code, "이번 달 특이사항 없음 (신규 1차 발표 미확인)")
            add('<tr><td style="padding:14px;">')
            add(f'{TBL}>')
            add(f'<tr><td align="center" style="border:1px dashed #b0bcc9; '
                f'background-color:#f5f7f9; padding:12px; color:#777777; font-size:13px;">'
                f'{esc(note)}</td></tr>')
            add('</table>')
            add('</td></tr>')
        add('</table>')
        add('</td></tr>')

    # ---- 3. 대한민국 ----
    add('<tr><td style="padding:30px 20px 14px 20px;">')
    add(f'<div style="font-size:18px; color:{A}; font-weight:bold; border-left:5px solid {A}; '
        f'padding-left:10px;">3. 대한민국 주요 연구보안·연구안보 이슈</div>')
    add('</td></tr>')
    add('<tr><td style="padding:0 20px 16px 20px;">')
    add(f'{TBL} style="border:1px solid #c0392b;">')
    add('<tr><td style="background-color:#c0392b; color:#ffffff; padding:8px 14px; '
        'font-size:15px; font-weight:bold;">🇰🇷 대한민국 (South Korea)</td></tr>')
    kr_issues = grouped.get("KR", [])
    circled = ["①", "②", "③"]
    if kr_issues:
        for idx, issue in enumerate(kr_issues):
            pad = "padding:14px;" if idx == 0 else "padding:0 14px 14px 14px;"
            add(f'<tr><td style="{pad}">')
            if idx > 0:
                add('<div style="border-top:1px dashed #d5dee7; padding-top:12px;">')
            mark = circled[idx] if idx < len(circled) else f"{idx + 1}."
            add(f'<div style="font-size:14px; margin-bottom:4px;"><b>{mark} '
                f'{esc(issue["title_kr"])}</b></div>')
            add(f'<div style="font-size:12px; color:#666666; margin-bottom:4px;">'
                f'{esc(issue["org"])} | {esc(issue["date"])} | {esc(issue["category"])}</div>')
            add(f'<div style="font-size:13px; margin-bottom:6px;">{esc(issue["content"])}</div>')
            add(f'<div style="font-size:13px; word-break:break-all;">'
                f'{_link_block(issue, p.link_color)}</div>')
            if idx > 0:
                add('</div>')
            add('</td></tr>')
    else:
        note = d["no_issue_countries"].get("KR", "이번 달 특이사항 없음 (신규 1차 발표 미확인)")
        add('<tr><td style="padding:14px;">')
        add(f'{TBL}>')
        add(f'<tr><td align="center" style="border:1px dashed #b0bcc9; background-color:#f5f7f9; '
            f'padding:12px; color:#777777; font-size:13px;">{esc(note)}</td></tr>')
        add('</table>')
        add('</td></tr>')

    trend = d.get("kr_other_trend") or {}
    if trend.get("text"):
        link = ""
        if safe_url(trend.get("url")):
            link = (f' 🔗 <a href="{safe_url(trend["url"])}" style="color:{A}; '
                    f'text-decoration:underline;">원문 보기</a>')
        add('<tr><td style="padding:0 14px 14px 14px;">')
        add(f'<div style="border-top:1px dashed #d5dee7; padding-top:12px; font-size:12px; '
            f'color:#555555; word-break:break-all;"><b>기타 동향:</b> {esc(trend["text"])}'
            f'{link}</div>')
        add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    # ---- 4. 종합 분석 ----
    add('<tr><td style="padding:30px 20px 14px 20px;">')
    add(f'<div style="font-size:18px; color:{A}; font-weight:bold; border-left:5px solid {A}; '
        f'padding-left:10px;">4. 종합 분석 및 시사점</div>')
    add('</td></tr>')
    add('<tr><td style="padding:0 20px;">')
    add(f'{TBL} style="background-color:#f7f9fb; border:1px solid #d5dee7;">')
    add('<tr><td style="padding:16px; font-size:13px; line-height:1.75; color:#222222;">')
    items = [(k, l) for k, l in p.analysis_items if d["analysis"].get(k)]
    for i, (key, label) in enumerate(items):
        margin = "" if i == len(items) - 1 else ' style="margin-bottom:10px;"'
        add(f'<div{margin}><b>{esc(label)}:</b> {esc(d["analysis"][key])}</div>')
    if not items:
        add('<div>이번 호에는 별도 종합 분석 사항이 없다.</div>')
    add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    # ---- 출처 원칙 ----
    if d.get("source_compliance_note"):
        add('<tr><td style="padding:16px 20px 0 20px;">')
        add(f'{TBL} style="background-color:#fff8e6; border-left:4px solid #e0a800;">')
        add('<tr><td style="padding:12px 14px; font-size:12.5px; line-height:1.7; '
            'color:#5c4a10;">')
        add(f'<b>[출처 및 작성 원칙]</b> {esc(d["source_compliance_note"])}')
        add('</td></tr>')
        add('</table>')
        add('</td></tr>')

    # ---- 푸터 ----
    add('<tr><td style="padding:24px 20px 0 20px;">')
    add(f'{TBL}>')
    add(f'<tr><td style="background-color:{A}; padding:16px 20px;">')
    add(f'<div style="font-size:12px; color:#c9d6e5; margin-bottom:4px; word-break:break-all;">'
        f'<b>메일 제목:</b> {esc(p.subject_format.format(report_month=d["report_month"], **period))}'
        f'</div>')
    add(f'<div style="font-size:11px; color:#9fb3c8; line-height:1.6;">{esc(p.footer_note)}</div>')
    add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    add('<tr><td style="height:16px; font-size:0; line-height:0;">&nbsp;</td></tr>')
    add('</table>')
    add('</td></tr>')
    add('</table>')
    return "\n".join(h)


# ==========================================================================
# 연구윤리 리포트
# ==========================================================================
def _render_ethics(p: ReportProfile, d: Dict[str, Any]) -> str:
    A = p.accent
    L = p.link_color
    period = d["period"]
    grouped = _grouped(d)
    h: List[str] = []
    add = h.append

    add(f'{TBL} style="background-color:#f4f6f8; padding:16px 8px;">')
    add('<tr><td align="center">')
    add(f'{TBL} style="max-width:{p.max_width}px; width:100%; background-color:#ffffff; '
        f'font-family:{p.font_family}; color:#222222; line-height:1.6;">')

    # ---- 헤더 ----
    add(f'<tr><td style="padding:28px 28px 18px 28px; border-bottom:4px solid {A};">')
    add(f'<div style="font-size:26px; color:{A}; font-weight:bold; line-height:1.35;">'
        f'{esc(p.title_kr)}</div>')
    add(f'<div style="font-size:14px; color:#555555; margin-top:8px;">{esc(p.title_en)} | '
        f'{esc(d["report_month"])}</div>')
    add('</td></tr>')

    # ---- 리포트 정보 ----
    add('<tr><td style="padding:22px 28px 0 28px;">')
    add(f'{TBL} style="background-color:{p.accent_soft}; border-left:5px solid {A};">')
    add('<tr><td style="padding:16px 20px;">')
    add(f'{TBL} style="font-size:13.5px; line-height:1.7;">')
    info_rows = [("수집 기간", f'{period["start"]} ~ {period["end"]} (KST)'),
                 ("발행일", period["report_date"])] + list(p.scope_rows)
    for i, (label, value) in enumerate(info_rows):
        width = ' width="120"' if i == 0 else ""
        add(f'<tr><td{width} valign="top" style="color:{A}; font-weight:bold; '
            f'padding:3px 8px 3px 0;">{esc(label)}</td>'
            f'<td valign="top" style="color:#333333; padding:3px 0;">{esc(value)}</td></tr>')
    add('</table>')
    add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    has_any = bool(d["issues"])

    # ---- 1. 핵심 요약 ----
    add('<tr><td style="padding:30px 28px 0 28px;">')
    add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
        f'border-bottom:2px solid #ddd2ec; padding-bottom:8px; margin-bottom:14px;">'
        f'1. 이달의 핵심 요약</div>')
    add(f'{TBL} style="background-color:#fff8e5; border:1px solid #f1d27a;">')
    add('<tr><td style="padding:16px 20px;">')
    add(f'{TBL} style="font-size:14px; line-height:1.7; color:#333333;">')
    summaries = d["executive_summary"] or ["이번 호에는 요약할 신규 이슈가 확인되지 않았다."]
    for i, s in enumerate(summaries):
        last = (i == len(summaries) - 1)
        pad = "padding:0;" if last else "padding:0 0 8px 0;"
        width = ' width="20"' if i == 0 else ""
        add(f'<tr><td valign="top"{width} style="{pad} color:{A}; font-weight:bold;">·</td>'
            f'<td style="{pad}">{esc_inline(s)}</td></tr>')
    add('</table>')
    add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    def issue_card(issue: dict, left_border: str = "") -> None:
        border = f'border:1px solid #dddddd;{left_border}'
        add('<tr><td style="padding:0 28px 14px 28px;">')
        add(f'{TBL} style="{border}">')
        add('<tr><td style="padding:16px 18px;">')
        add(f'<div style="font-size:16px; font-weight:bold; color:{A}; line-height:1.45;">'
            f'{esc(issue["title_kr"])}</div>')
        if issue.get("title_original"):
            add(f'<div style="font-size:13px; color:#555555; margin-top:4px;">원문: '
                f'{esc(issue["title_original"])}</div>')
        add(f'<div style="font-size:13px; color:#555555; margin:10px 0; line-height:1.7;">'
            f'<b>국가/기관:</b> {esc(issue["org"])} &nbsp;|&nbsp; '
            f'<b>발표일:</b> {esc(issue["date"])} &nbsp;|&nbsp; '
            f'<b>이슈 유형:</b> {esc(issue["category"])}</div>')
        if issue.get("status"):
            add(f'{TBL} style="margin-bottom:10px;">')
            add(f'<tr><td style="background-color:#f7f2fb; border:1px solid #d6c5ea; '
                f'padding:9px 12px; font-size:13px; color:#333333;">'
                f'<b style="color:{A};">진행 상태:</b> {esc(issue["status"])}</td></tr>')
            add('</table>')
        add(f'<div style="font-size:14px; color:#333333; margin-bottom:10px; line-height:1.75;">'
            f'{esc(issue["content"])}</div>')
        add(f'<div style="font-size:13px; word-break:break-all;">'
            f'{_link_block(issue, L, bold=True)}</div>')
        add('</td></tr>')
        add('</table>')
        add('</td></tr>')

    def no_issue_box(code: str) -> None:
        note = d["no_issue_countries"].get(code, "이번 달 검증 가능한 신규 이슈 없음")
        add('<tr><td style="padding:0 28px 18px 28px;">')
        add(f'{TBL}>')
        add(f'<tr><td style="background-color:#f7f7f7; border:1px dashed #bbbbbb; '
            f'padding:13px 16px; color:#666666; font-size:13.5px; line-height:1.7;">'
            f'{esc(note)}</td></tr>')
        add('</table>')
        add('</td></tr>')

    if has_any:
        # ---- 2. G7 및 EU ----
        add('<tr><td style="padding:32px 28px 0 28px;">')
        add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
            f'border-bottom:2px solid #ddd2ec; padding-bottom:8px;">'
            f'2. G7 주요국 및 EU 연구윤리·연구진실성 이슈</div>')
        add('</td></tr>')

        for n, code in enumerate(p.countries, start=1):
            label = COUNTRY_NAMES[code][0].split(" (")[0]
            pad = "24px 28px 0 28px" if n == 1 else "10px 28px 0 28px"
            add(f'<tr><td style="padding:{pad};">')
            add(f'<div style="font-size:17px; color:#333333; font-weight:bold; '
                f'border-left:4px solid #8e63c7; padding-left:10px; margin-bottom:12px;">'
                f'2.{n} {esc(label)}</div>')
            add('</td></tr>')
            issues = grouped.get(code, [])
            for issue in issues:
                issue_card(issue)
            if not issues:
                no_issue_box(code)

        # ---- 3. 대한민국 ----
        add('<tr><td style="padding:22px 28px 0 28px;">')
        add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
            f'border-bottom:2px solid #ddd2ec; padding-bottom:8px; margin-bottom:14px;">'
            f'3. 대한민국 연구윤리·연구진실성 이슈</div>')
        add('</td></tr>')
        kr_issues = grouped.get("KR", [])
        for issue in kr_issues:
            issue_card(issue, left_border=" border-left:4px solid #c0392b;")
        if not kr_issues:
            no_issue_box("KR")

        # ---- 4. 국제기관 ----
        add('<tr><td style="padding:22px 28px 0 28px;">')
        add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
            f'border-bottom:2px solid #ddd2ec; padding-bottom:8px; margin-bottom:14px;">'
            f'4. 주요 국제기관 동향</div>')
        add('</td></tr>')
        intl_issues = grouped.get("INTL", [])
        for issue in intl_issues:
            issue_card(issue, left_border=" border-left:4px solid #4f8a5b;")
        if not intl_issues:
            no_issue_box("INTL")

        # ---- 5. 종합 분석 ----
        add('<tr><td style="padding:22px 28px 0 28px;">')
        add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
            f'border-bottom:2px solid #ddd2ec; padding-bottom:8px; margin-bottom:14px;">'
            f'5. 종합 분석 및 시사점</div>')
        add(f'{TBL} style="background-color:#f2f7f2; border-left:5px solid #4f8a5b;">')
        add('<tr><td style="padding:16px 20px; font-size:13.5px; line-height:1.8; '
            'color:#333333;">')
        items = [(k, l) for k, l in p.analysis_items if d["analysis"].get(k)]
        for i, (key, label) in enumerate(items):
            margin = "" if i == len(items) - 1 else ' style="margin-bottom:10px;"'
            add(f'<div{margin}><b>{esc(label)}:</b> {esc(d["analysis"][key])}</div>')
        if not items:
            add('<div>이번 호에는 별도 종합 분석 사항이 없다.</div>')
        add('</td></tr>')
        add('</table>')
        add('</td></tr>')
    else:
        # ---- 전체 이슈 없음 블록 ----
        add('<tr><td style="padding:22px 28px 0 28px;">')
        add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
            f'border-bottom:2px solid #ddd2ec; padding-bottom:8px; margin-bottom:14px;">'
            f'해당 기간 특이사항 없음</div>')
        add(f'{TBL}>')
        add(f'<tr><td style="background-color:#f7f7f7; border:1px dashed #bbbbbb; '
            f'padding:14px 18px; color:#666666; font-size:14px; line-height:1.7;">'
            f'{period["start"]} ~ {period["end"]} 기간 중 G7 주요국, EU, 대한민국 및 주요 '
            f'국제기관의 연구윤리·연구진실성 관련 검증 가능한 주요 신규 이슈는 확인되지 '
            f'않았습니다.</td></tr>')
        add('</table>')
        add('</td></tr>')

    # ---- 6. 출처 및 작성 기준 ----
    add('<tr><td style="padding:22px 28px 0 28px;">')
    add(f'<div style="font-size:20px; color:{A}; font-weight:bold; '
        f'border-bottom:2px solid #ddd2ec; padding-bottom:8px; margin-bottom:14px;">'
        f'6. 출처 및 작성 기준</div>')
    add(f'{TBL} style="background-color:#fff3f3; border-left:5px solid #c0392b;">')
    add('<tr><td style="padding:16px 20px; font-size:13px; line-height:1.8; color:#333333;">')
    add('<div style="margin-bottom:8px;">본 리포트는 각 이슈별로 검증 가능한 원문 출처 링크가 '
        '확인된 자료만을 포함합니다. 정부·공공기관 발표, 연구지원기관 자료, 대학·연구기관 공지, '
        '출판사·학회 공식 발표, Retraction Watch 등 신뢰 가능한 출처를 우선 활용했습니다.</div>')
    add('<div style="margin-bottom:8px;">연구부정행위, 논문 철회, 우려표명, 조사·제재 등 민감한 '
        '사안은 확인된 사실관계와 공식적으로 공개된 조사 진행 단계에 한정하여 서술했습니다.</div>')
    add('<div style="margin-bottom:8px;">검증 가능한 URL이 없는 정보는 리포트에 포함하지 '
        '않았습니다.</div>')
    if d.get("source_compliance_note"):
        add(f'<div>{esc(d["source_compliance_note"])}</div>')
    add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    # ---- 푸터 ----
    add('<tr><td style="padding:32px 28px 28px 28px;">')
    add(f'{TBL} style="border-top:1px solid #dddddd;">')
    add('<tr><td style="padding-top:16px; font-size:12.5px; color:#666666; line-height:1.8;">')
    subject = p.subject_format.format(report_month=d["report_month"], **period)
    add(f'<div style="word-break:break-all;"><b>메일 제목:</b> {esc(subject)}</div>')
    add(f'<div style="margin-top:12px; color:#888888;">{esc(p.footer_note)}</div>')
    add('</td></tr>')
    add('</table>')
    add('</td></tr>')

    add('</table>')
    add('</td></tr>')
    add('</table>')
    return "\n".join(h)


def build_subject(profile: ReportProfile, data: Dict[str, Any]) -> str:
    return profile.subject_format.format(report_month=data["report_month"], **data["period"])


def wrap_full_document(body_html: str, title: str) -> str:
    """브라우저 미리보기/보관용 전체 HTML 문서로 감싼다(메일 본문에는 body_html 만 사용)."""
    return ('<!DOCTYPE html>\n<html lang="ko"><head><meta charset="utf-8">'
            f'<title>{esc(title)}</title></head>\n<body style="margin:0; padding:0;">\n'
            f'{body_html}\n</body></html>')
