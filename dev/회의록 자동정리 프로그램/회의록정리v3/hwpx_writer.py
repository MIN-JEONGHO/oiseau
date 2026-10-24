# -*- coding: utf-8 -*-
"""
표준 회의록 양식(template.hwpx)을 요약 결과로 채운다.

양식 구조 (Contents/section0.xml)
  표0 : 제목 표 (3행 1열)                     -> "ㅇㅇㅇㅇ 회의록"
  문단: (’yy.mm.dd.., KISTEP 연구윤리자산보호센터)
  □ 회의 개요 - ㅇ (일시·장소) / ㅇ (참석) / ㅇ (안건)
  □ 기관별 요약
  표1 : 기관 | 항목 | 발언 내용 (11행 3열)
          row0        머리행
          row1~5      기관1 블록 (col0 은 rowSpan=5 로 병합)
          row6~10     기관2 블록
        행 높이는 3363 으로 균일하고, 블록 시작행만 3열·나머지는 2열이다.
        -> 블록을 기관 수만큼, 블록 안의 행을 항목 수만큼 복제해서 쓴다.
  □ 시사점 및 환류계획 - ㅇ (시사점) / ㅇ (환류계획)
  표2 : 참고 | | 회의록 원문
  문단: ㅇ 회의록 원문 /    -  (참석자1) 내용

문단·셀의 고정 문구는 자리표시자로 보고 문자열 치환한다. 위치(인덱스)로 찾지 않기
때문에 양식에서 문단이 조금 늘거나 줄어도 계속 동작한다.
"""
from __future__ import annotations

import copy
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lxml import etree

from summarizer import Attendee, Summary
from stt import Transcript

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION = "Contents/section0.xml"

ROW_HEIGHT = 3363       # 기관별 요약 표의 행 높이(양식 값)
HEADER_HEIGHT = 2200    # 머리행 높이

# --- 양식 안의 자리표시자 ---
PH_TITLE = "ㅇㅇㅇㅇ 회의록"
PH_DATE = "’yy.mm.dd."
PH_FOOTER = "., KISTEP 연구윤리자산보호센터)"
PH_WHEN_WHERE = "’yy. mm. dd. / “장소”"
PH_ATTEND = "참석자1 기관 참석자1 직위, 참석자2 기관 참석자2 직위, "
PH_AGENDA = "희의록 기록 키워드 2줄"
PH_IMPLICATION = " 회의결과에 따른 시사점"
PH_FEEDBACK = " 향후 조치계획, 환류계획 등"
PH_TRANSCRIPT = "   -  (참석자1) 내용"

SUMMARY_HEADERS = ("기 관", "항 목", "발언 내용")


class HwpxError(RuntimeError):
    pass


def _q(tag: str) -> str:
    return f"{{{HP}}}{tag}"


# ---------------------------------------------------------------------------
# 저수준 헬퍼
# ---------------------------------------------------------------------------

def _cells(tr) -> list:
    return tr.findall(_q("tc"))


def _addr(tc):
    return tc.find(_q("cellAddr"))


def _span(tc):
    return tc.find(_q("cellSpan"))


def _cell_sz(tc):
    return tc.find(_q("cellSz"))


def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(_q("t")))


def _set_para_text(p, text: str) -> None:
    """문단의 첫 run 만 남기고 텍스트를 교체한다(서식 유지)."""
    runs = p.findall(_q("run"))
    if not runs:
        run = etree.SubElement(p, _q("run"))
        runs = [run]
    for extra in runs[1:]:
        p.remove(extra)
    run = runs[0]
    for t in run.findall(_q("t")):
        run.remove(t)
    t = etree.Element(_q("t"))
    t.text = text
    # hp:t 는 run 의 서식(hp:ctrl 등) 뒤가 아니라 앞쪽에 와야 안전하다
    run.insert(0, t)


def _set_cell_lines(tc, lines: Iterable[str]) -> None:
    """셀 내용을 여러 줄로 채운다. 첫 문단을 본떠 줄 수만큼 복제."""
    sub = tc.find(_q("subList"))
    if sub is None:
        return
    paras = sub.findall(_q("p"))
    if not paras:
        return
    proto = copy.deepcopy(paras[0])
    for p in paras:
        sub.remove(p)
    lines = [ln for ln in lines] or [""]
    for ln in lines:
        p = copy.deepcopy(proto)
        _set_para_text(p, ln)
        sub.append(p)


def _set_cell_text(tc, text: str) -> None:
    _set_cell_lines(tc, str(text).split("\n"))


def _replace_placeholder(root, placeholder: str, value: str, limit: int = 0) -> int:
    """본문 전체에서 자리표시자 문자열을 치환한다. 치환 횟수를 돌려준다."""
    n = 0
    for t in root.iter(_q("t")):
        if t.text and placeholder in t.text:
            t.text = t.text.replace(placeholder, value)
            n += 1
            if limit and n >= limit:
                break
    return n


def _find_para_with(root, needle: str):
    for p in root.iter(_q("p")):
        if needle in _para_text(p):
            return p
    return None


def _find_summary_table(root):
    """머리행 문구로 기관별 요약 표를 찾는다."""
    for tbl in root.iter(_q("tbl")):
        trs = tbl.findall(_q("tr"))
        if not trs:
            continue
        texts = tuple("".join(tc.itertext()).strip() for tc in _cells(trs[0]))
        if texts == SUMMARY_HEADERS:
            return tbl
    return None


# ---------------------------------------------------------------------------
# 기관별 요약 표 재구성
# ---------------------------------------------------------------------------

def _build_summary_table(tbl, institutions: list) -> None:
    trs = tbl.findall(_q("tr"))
    if len(trs) < 7:
        raise HwpxError("양식의 기관별 요약 표 구조가 예상과 다릅니다.")

    header = trs[0]
    proto_first_start = copy.deepcopy(trs[1])   # 머리행 바로 아래(테두리가 다름)
    proto_cont = copy.deepcopy(trs[2])          # 블록 안쪽 행 (2열)
    proto_start = copy.deepcopy(trs[6])         # 두 번째 이후 블록의 시작행 (3열)

    for tr in trs:
        tbl.remove(tr)
    tbl.append(header)

    total_rows = 1
    for i, inst in enumerate(institutions):
        items = inst.items or []
        if not items:
            continue
        k = len(items)

        start = copy.deepcopy(proto_first_start if i == 0 else proto_start)
        cs = _cells(start)
        if len(cs) < 3:
            raise HwpxError("양식의 기관 블록 시작행이 3열이 아닙니다.")
        _set_cell_text(cs[0], inst.name)
        _span(cs[0]).set("rowSpan", str(k))
        _cell_sz(cs[0]).set("height", str(k * ROW_HEIGHT))
        _set_cell_text(cs[1], items[0].topic)
        _set_cell_text(cs[2], items[0].content)
        tbl.append(start)
        total_rows += 1

        for item in items[1:]:
            row = copy.deepcopy(proto_cont)
            rc = _cells(row)
            if len(rc) < 2:
                raise HwpxError("양식의 기관 블록 연속행이 2열이 아닙니다.")
            _set_cell_text(rc[0], item.topic)
            _set_cell_text(rc[1], item.content)
            tbl.append(row)
            total_rows += 1

    # rowAddr 재계산
    for ri, tr in enumerate(tbl.findall(_q("tr"))):
        for tc in _cells(tr):
            _addr(tc).set("rowAddr", str(ri))
    tbl.set("rowCnt", str(total_rows))

    sz = tbl.find(_q("sz"))
    if sz is not None:
        sz.set("height", str(HEADER_HEIGHT + (total_rows - 1) * ROW_HEIGHT))


# ---------------------------------------------------------------------------
# 회의록 원문 문단
# ---------------------------------------------------------------------------

def _fill_transcript(root, lines: list[str]) -> None:
    proto = _find_para_with(root, PH_TRANSCRIPT)
    if proto is None:
        return
    parent = proto.getparent()
    at = list(parent).index(proto)
    if not lines:
        _set_para_text(proto, "   -  (기록 없음)")
        return
    made = []
    for ln in lines:
        p = copy.deepcopy(proto)
        _set_para_text(p, ln)
        made.append(p)
    parent.remove(proto)
    for off, p in enumerate(made):
        parent.insert(at + off, p)


def transcript_lines(transcript: Transcript, merge: bool = True) -> list[str]:
    """양식의 '   -  (홍길동) 내용' 형태로 전사문을 줄 목록으로 만든다."""
    segs = [s for s in transcript.segments if (s.text or "").strip()]
    if not segs:
        return []
    if not merge:
        return [f"   -  ({s.speaker or '미상'}) {s.text.strip()}" for s in segs]

    lines: list[str] = []
    cur_spk: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if buf:
            lines.append(f"   -  ({cur_spk or '미상'}) " + " ".join(buf).strip())
            buf.clear()

    for s in segs:
        spk = s.speaker or "미상"
        if spk != cur_spk:
            flush()
            cur_spk = spk
        buf.append(s.text.strip())
    flush()
    return lines


# ---------------------------------------------------------------------------
# 문자열 조립
# ---------------------------------------------------------------------------

def format_attendees(attendees: list[Attendee]) -> str:
    """'기관 직위 이름, 기관 직위 이름' 형태 (양식 예시와 동일한 순서)."""
    bits = []
    for a in attendees:
        parts = [p for p in (a.org, a.position, a.name) if p]
        if parts:
            bits.append(" ".join(parts))
    return ", ".join(bits)


def format_date_kr(value: str | None) -> str:
    """'2026-09-04' / '2026.9.4' -> '’26. 9. 4.' (양식 표기)."""
    raw = (value or "").strip()
    if not raw:
        d = date.today()
    else:
        digits = [p for p in raw.replace(".", "-").replace("/", "-").split("-") if p.strip()]
        try:
            y, m, dd = int(digits[0]), int(digits[1]), int(digits[2])
            if y < 100:
                y += 2000
            d = date(y, m, dd)
        except Exception:  # noqa: BLE001
            return raw  # 해석 못 하면 사용자가 쓴 그대로
    return f"’{d.year % 100:02d}. {d.month}. {d.day}."


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

@dataclass
class Document:
    summary: Summary
    attendees: list[Attendee]
    meeting_date: str = ""        # 예: 2026-09-04
    when_where: str = ""          # 예: ’26. 9. 4. 14:00 / KISTEP 대회의실
    org_footer: str = "KISTEP 연구윤리자산보호센터"
    transcript: Transcript | None = None
    attach_transcript: bool = True
    merge_transcript: bool = True


def fill_hwpx(template: str | Path, out_path: str | Path, doc: Document) -> str:
    template, out_path = Path(template), Path(out_path)
    if not template.exists():
        raise HwpxError(f"양식 파일이 없습니다: {template}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(template) as zin:
        names = zin.namelist()
        blobs = {n: zin.read(n) for n in names}
    if SECTION not in blobs:
        raise HwpxError("양식에서 Contents/section0.xml 을 찾지 못했습니다.")

    root = etree.fromstring(blobs[SECTION], etree.XMLParser(remove_blank_text=False))
    s = doc.summary

    # 1) 제목 / 머리말
    _replace_placeholder(root, PH_TITLE, f"{s.title or '회의'} 회의록")
    _replace_placeholder(root, PH_DATE, format_date_kr(doc.meeting_date))
    _replace_placeholder(root, PH_FOOTER, f", {doc.org_footer})")

    # 2) 회의 개요
    when_where = doc.when_where.strip() or format_date_kr(doc.meeting_date)
    _replace_placeholder(root, PH_WHEN_WHERE, when_where)
    _replace_placeholder(root, PH_ATTEND, format_attendees(doc.attendees))
    _replace_placeholder(root, PH_AGENDA, s.agenda or "")

    # 3) 기관별 요약 표
    tbl = _find_summary_table(root)
    if tbl is None:
        raise HwpxError("양식에서 '기 관 / 항 목 / 발언 내용' 표를 찾지 못했습니다.")
    _build_summary_table(tbl, s.institutions)

    # 4) 시사점 / 환류계획
    _replace_placeholder(root, PH_IMPLICATION, " " + (s.implications or ""))
    _replace_placeholder(root, PH_FEEDBACK, " " + (s.feedback_plan or ""))

    # 5) 회의록 원문
    lines: list[str] = []
    if doc.attach_transcript and doc.transcript is not None:
        lines = transcript_lines(doc.transcript, merge=doc.merge_transcript)
    _fill_transcript(root, lines)

    blobs[SECTION] = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                    standalone=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        if "mimetype" in blobs:   # mimetype 은 압축 없이 맨 앞에
            zout.writestr(zipfile.ZipInfo("mimetype"), blobs["mimetype"],
                          zipfile.ZIP_STORED)
        for n in names:
            if n != "mimetype":
                zout.writestr(n, blobs[n])
    return str(out_path)


def write_transcript_txt(out_path: str | Path, transcript: Transcript,
                         doc_title: str = "") -> str:
    """전사문을 별도 텍스트 파일로도 남긴다."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [f"{doc_title} 전사문", "=" * 40, ""]
    for s in transcript.segments:
        mm, ss = divmod(int(s.start), 60)
        hh, mm = divmod(mm, 60)
        rows.append(f"[{hh:02d}:{mm:02d}:{ss:02d}] ({s.speaker or '미상'}) {s.text}")
    out_path.write_text("\n".join(rows), encoding="utf-8")
    return str(out_path)
