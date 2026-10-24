"""Editable v14 HWPX reference opinions from the saved result DTO only.

Templates derive from the approved guide's 21-row, four-column individual forms
1137197348 / 1137197437. They contain only needed form styles and page geometry.
Long values flow through short continuation rows, never a fixed-height book cell.
No classification, credential, engine, or network call occurs while exporting.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from lxml import etree as E

from v14_domain import format_score

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION = "Contents/section0.xml"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
GRADES = ("보안과제", "민감과제", "일반과제")
WIDTH = 45252
# Every continuation cell stays shorter than a page even at large font scaling.
CHUNK_SIZE = 400


def _q(name):
    return f"{{{HP}}}{name}"


def _text(value):
    return "" if value is None else str(value)


def _chunks(value, limit=CHUNK_SIZE):
    """Preserve all characters and explicit paragraphs; bound each physical row."""
    value = _text(value).replace("\r\n", "\n").replace("\r", "\n")
    for paragraph in value.split("\n"):
        if not paragraph:
            yield ""
        for start in range(0, len(paragraph), limit):
            yield paragraph[start:start + limit]


def _number(value):
    # Integer item scores and configured weights retain their supplied display.
    return "" if value is None else str(value)


def _display_score(value):
    # Share the domain display rule without changing the saved raw score. Keep
    # absent values blank rather than turning an incomplete review into a score.
    return "" if value is None else format_score(value)


def _safe_name(value, limit=24):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", _text(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return cleaned[:limit].rstrip(" .") or "과제"


def _hash(value, length=12):
    return hashlib.sha256(_text(value).encode("utf-8")).hexdigest()[:length]


def _task_id(result):
    fingerprint = result.get("task_fingerprint")
    if not fingerprint:
        fingerprint = json.dumps(result.get("task_snapshot", {}), sort_keys=True, ensure_ascii=False)
    return _hash(fingerprint)


def _complete(reviewer):
    return reviewer.get("status") == "완료" and reviewer.get("grade") in GRADES


def _rows(result, reviewer, generated):
    """Row tuples are (texts, spans, header); full-width rows split long values."""
    rows = []
    def full(value, header=False):
        for chunk in _chunks(value):
            rows.append(([chunk], [4], header))
    def field(label, value):
        chunks = list(_chunks(value))
        if max(map(len, chunks), default=0) > 220 or len(chunks) > 1:
            full(label)
            for chunk in chunks:
                full(chunk)
        else:
            rows.append(([label, chunks[0] if chunks else ""], [1, 3], False))
    def reasons(subject):
        for reason in subject.get("unresolved_reasons", []) or []:
            full("검토필요 사유: " + _text(reason))
    def personal(subject, index=None):
        identity = _text(subject.get("reviewer_id"))
        full((f"AI 에이전트 {index + 1}: " if index is not None else "AI 에이전트: ") + identity, True)
        field("관점", subject.get("persona"))
        field("평가 상태", subject.get("status"))
        if not _complete(subject):
            full("미완료 · 검토필요: 미산출 등급은 선택하지 않았습니다.")
        field("참고 등급", subject.get("grade") if _complete(subject) else "")
        field("신뢰도", subject.get("confidence"))
        if result.get("method") == "impact":
            field("개인 점수", _display_score(subject.get("reviewer_score")))
        else:
            full("수치 해당 없음 (체크리스트)")
        full("등급 결정 시 가장 중요하게 고려한 사항")
        full(subject.get("rationale"))
        full("추가 검토·논의사항")
        full(subject.get("discussion_points"))
        reasons(subject)
    def items(subject):
        notes = {entry.get("item"): entry for entry in subject.get("item_reviews", []) or []}
        criteria = result.get("criteria", []) or []
        known = [entry.get("item") for entry in criteria]
        for name in notes:
            if name not in known:
                known.append(name)
        selected = result.get("selected_items", []) or []
        for index, name in enumerate(known):
            entry = notes.get(name, {})
            score = (subject.get("scores") or {}).get(name)
            rows.append(([f"{index + 1}. {_text(name)}", "선택" if name in selected else "미선택",
                          _text(entry.get("level")) or "미검토",
                          "영향 점수: " + _number(score) if impact else "수치 해당 없음"], [1, 1, 1, 1], False))
            if impact:
                field("가중치", _number((result.get("weights") or {}).get(name)) if name in selected else "해당 없음")
            full("검토정보: " + _text(entry.get("note")))
            full("법적 근거: " + ", ".join(map(str, entry.get("law_refs", []) or [])))
            common = next((c for c in criteria if c.get("item") == name), {})
            if common.get("matched_reference"):
                full("참조자료: " + _text(common["matched_reference"]))
            if common.get("needs_expert_review"):
                full("전문 검토 필요")
    impact = result.get("method") == "impact"
    full("1. 보안등급 분류 대상", True)
    for key, value in (result.get("task_snapshot") or {}).items():
        field(key, value)
    field("분류 방식", "국가영향 지표" if impact else "체크리스트")
    field("적용 모델", f"{_text(result.get('provider'))} / {_text(result.get('model'))}")
    field("적용 기준", result.get("guideline_id"))
    field("분류 상태", result.get("status"))
    if result.get("status") != "완료":
        full("미완료 · 검토필요 안내: 상태와 사유를 확인하여 사람이 검토해야 합니다.")
    if reviewer is not None:
        field("AI 에이전트", reviewer.get("reviewer_id"))
        field("관점", reviewer.get("persona"))
        full("2. 항목별 검토", True)
        items(reviewer)
        if impact:
            field("개인 점수", _display_score(reviewer.get("reviewer_score")))
        full("3. 에이전트별 참고 등급", True)
        for grade in GRADES:
            full(("☑ " if _complete(reviewer) and reviewer.get("grade") == grade else "□ ") + grade)
        if not _complete(reviewer):
            full("미완료 · 검토필요: 참고 등급 미선택")
        field("신뢰도", reviewer.get("confidence"))
        full("4. 종합 의견", True)
        full("등급 결정 시 가장 중요하게 고려한 사항")
        full(reviewer.get("rationale"))
        full("추가 검토·논의사항")
        full(reviewer.get("discussion_points"))
        reasons(reviewer)
    else:
        full("2. 공통 검토항목 및 에이전트별 검토의견", True)
        reviewers = result.get("reviewers", []) or []
        if not reviewers:
            full("개별 평가 미실시: AI 에이전트별 검토의견서를 만들지 않았습니다.")
            candidate = result.get("candidate") or {}
            full("후보 판단 사유: " + _text(candidate.get("reason")))
            full("후보 판단 불확실성: " + _text(candidate.get("uncertainty")))
        for index, subject in enumerate(reviewers):
            personal(subject, index)
            items(subject)
        full("3. AI 종합 검토의견", True)
        if impact:
            # A partial committee never acquires an apparent complete mean.
            complete = bool(reviewers) and all(_complete(subject) and subject.get("reviewer_score") is not None for subject in reviewers)
            field("에이전트 종합평균", _display_score(result.get("overall_avg")) if complete else "")
            field("수치 구간 참고 등급", result.get("rule_grade") if complete and result.get("overall_avg") is not None else "")
            if result.get("rule_grade") and result.get("final_grade") and result["rule_grade"] != result["final_grade"]:
                full("구간 불일치: 수치 구간 참고 등급과 AI 종합 참고 등급이 다릅니다. 근거 및 전문가 검토가 필요합니다.")
        else:
            full("수치 해당 없음 (체크리스트): 해당 여부와 법적 정의를 검토합니다.")
        field("AI 종합 참고 등급", result.get("final_grade") if result.get("status") == "완료" else "")
        field("신뢰도", result.get("confidence"))
        if result.get("confidence") == "낮음":
            full("낮은 신뢰도 · 재검토 필요")
        full("4. 종합 의견 및 추가 검토·논의사항", True)
        full(result.get("rationale"))
        full(result.get("discussion_points"))
        reasons(result)
    full("5. 제출확인", True)
    field("문서 생성 시각", generated)
    field("실제 제출일시", "")
    field("평가위원 이름 / 서명", "")
    field("간사 확인", "")
    full("AI가 생성한 분석·참고 의견입니다. 실제 심의 및 보안등급 확정은 담당자의 판단과 절차에 따릅니다.")
    return rows


def _paragraph(text, identity, *, heading=False):
    para = E.Element(_q("p"), id=str(identity), paraPrIDRef="1" if heading else "0", styleIDRef="0",
                     pageBreak="0", columnBreak="0", merged="0")
    run = E.SubElement(para, _q("run"), charPrIDRef="1" if heading else "0")
    E.SubElement(run, _q("t")).text = text
    return para


def _fill_section(section, rows, title):
    root = E.fromstring(section)
    first_text = root.find(f".//{_q('t')}")
    first_text.text = title
    # The source heading char is white, so the title uses normal black text.
    table = root.find(f".//{_q('tbl')}")
    prototype = deepcopy(table.find(_q("tr"))[0])
    for row in list(table.findall(_q("tr"))):
        table.remove(row)
    identity = 10
    for row_index, (texts, spans, heading) in enumerate(rows):
        row = E.SubElement(table, _q("tr"))
        col = 0
        for text, span in zip(texts, spans):
            cell = deepcopy(prototype)
            cell.set("borderFillIDRef", "4" if heading else "3")
            cell.find(_q("cellAddr")).set("rowAddr", str(row_index))
            cell.find(_q("cellAddr")).set("colAddr", str(col))
            cell.find(_q("cellSpan")).set("colSpan", str(span))
            cell.find(_q("cellSpan")).set("rowSpan", "1")
            # Heights are minimums; no cached line positions constrain the text.
            cell.find(_q("cellSz")).set("height", "0")
            cell.find(_q("cellSz")).set("width", str(WIDTH * (col + span) // 4 - WIDTH * col // 4))
            sub = cell.find(_q("subList"))
            sub[:] = [_paragraph(text, identity, heading=heading)]
            sub.set("vertAlign", "TOP")
            identity += 1
            row.append(cell)
            col += span
    table.set("rowCnt", str(len(rows)))
    table.find(_q("sz")).set("height", "0")
    return E.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def _write_document(result, reviewer, path):
    """Write one complete ZIP to a sibling temp file before atomic replacement."""
    template = TEMPLATE_DIR / ("reviewer_opinion.hwpx" if reviewer is not None else "committee_summary.hwpx")
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    title = "AI 에이전트별 보안등급 분류 검토의견서" if reviewer is not None else "AI 보안등급 분류 종합 검토의견서"
    with ZipFile(template) as zin:
        blobs = {name: zin.read(name) for name in zin.namelist()}
    blobs[SECTION] = _fill_section(blobs[SECTION], _rows(result, reviewer, generated), title)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".hwpx-", suffix=".tmp", dir=path.parent, delete=False) as temp:
            temporary = Path(temp.name)
        with ZipFile(temporary, "w", ZIP_DEFLATED) as zout:
            zout.writestr("mimetype", b"application/hwp+zip", compress_type=ZIP_STORED)
            for name, data in blobs.items():
                if name != "mimetype":
                    zout.writestr(name, data)
        with ZipFile(temporary) as check:
            if check.testzip() is not None:
                raise ValueError("Invalid generated ZIP")
            E.fromstring(check.read(SECTION))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_documents(result, output_dir):
    """Return the documents contract without changing the saved classification.

    Each call creates a fresh run/task folder. Even equal display names or IDs
    that sanitize identically cannot overwrite another document. Failures remain
    per-file and all remaining reviewer and summary files are still attempted.
    """
    reviewers = list(result.get("reviewers", []) or [])
    documents = {"status": "미생성", "expected_files": len(reviewers) + 1, "files": [], "errors": []}
    task_id = _task_id(result)
    folder = Path(output_dir) / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:12]) / (f"{_safe_name(result.get('task_name'))}_{task_id}")
    directory_ok = True
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError):
        directory_ok = False
    for index, reviewer in enumerate(reviewers + [None]):
        reviewer_id = reviewer.get("reviewer_id") if reviewer is not None else None
        kind = "reviewer" if reviewer is not None else "summary"
        suffix = f"에이전트_{index + 1}_{_safe_name(reviewer_id, 12)}_{_hash(reviewer_id, 8)}" if reviewer is not None else "종합"
        path = folder / (f"{_safe_name(result.get('task_name'), 20)}_{task_id}_{suffix}.hwpx")
        record = {"kind": kind, "reviewer_id": reviewer_id, "path": str(path), "status": "오류", "error": ""}
        try:
            if not directory_ok:
                raise OSError("Output directory unavailable")
            _write_document(result, reviewer, path)
            record["status"] = "완료"
        except Exception:
            # Raw provider errors and filesystem details are never copied into a
            # report. The caller already has the intended path for remediation.
            record["error"] = "HWPX 파일을 저장하지 못했습니다. 저장 위치와 템플릿을 확인해 주세요."
            documents["errors"].append(f"{kind} {index + 1}: {record['error']}")
        documents["files"].append(record)
    completed = sum(record["status"] == "완료" for record in documents["files"])
    documents["status"] = "완료" if completed == documents["expected_files"] else "일부실패" if completed else "실패"
    return documents
