"""Editable v15 HWPX reference opinions from the validated saved result only.

The v15 templates derive from the approved guide's four-column individual forms
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

from v15_domain import GRADES, format_score, validate_result, validate_documents

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION = "Contents/section0.xml"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "v15"
WIDTH = 45252
# Bound continuation content without clipping; native pagination needs visual QA.
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
    return result["task_fingerprint"][:12]


def _complete(reviewer):
    return reviewer.get("status") == "완료" and reviewer.get("grade") in GRADES


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _target_description(comparison):
    assessment = comparison["target_assessment"]
    if assessment == "satisfied":
        return "목표 달성 시 해당 가능성"
    if assessment == "not_provided":
        return "목표 사양 미제공"
    if assessment == "not_satisfied":
        return "제공된 목표 사양과 대조 조건 불충족"
    target_conditions = [condition for condition in comparison["conditions"] if condition["basis"] == "target"]
    if any(condition["assessment"] == "satisfied" for condition in target_conditions):
        return "목표 조건 일부 충족·추가 확인"
    return "목표 조건 추가 확인 필요"


def _notice_rows(notice, full, field):
    """Render the complete frozen evidence, including transitive references.

    Complete is a coverage status. All assessments retain their temporal basis;
    neither a candidate nor an automated condition result is an official ruling.
    """
    basis_names = {"current": "현재", "target": "목표", "both": "현재·목표", "unspecified": "시점 미확인"}
    assessment_names = {"satisfied": "조건 충족", "not_satisfied": "조건 불충족",
                        "insufficient_info": "정보 부족", "not_provided": "미제공"}
    full("부록 1. 고시 대조 및 저장 기준본", True)
    full("저장된 기준본·조항 스냅샷·입력 인용에 따른 자동 탐색·대조 참고자료입니다. 담당자의 원문 확인과 전문 검토가 필요합니다.")
    full("complete는 지정된 처리범위의 완료 상태이며 법적 판단의 정확성 보증을 뜻하지 않습니다.")
    field("기준본 식별자", notice["catalogue_id"])
    field("기준본 지문(SHA256)", notice["catalogue_fingerprint"])
    field("고시 처리 상태", notice["status"])
    for reason in notice["blocking_reasons"]:
        full("고시 미해결 사유: " + reason)
    full("네 고시 계열의 처리범위", True)
    for family in notice["families"]:
        full("계열: " + family["family"], True)
        field("계열 처리 상태", family["status"])
        field("탐색 조항", ", ".join(family["screened_ids"]))
        field("후보 조항", ", ".join(family["candidate_ids"]))
        if not family["candidate_ids"]:
            full("후보 없음(자동 탐색)" if family["status"] == "complete"
                 else "후보 탐색 미완료: 저장된 후보 조항 없음")
        for excluded in family["excluded"]:
            field("탐색 제외 조항", excluded["clause_id"])
            field("탐색 제외 사유", excluded["reason"])
        for error in family["errors"]:
            full("계열 처리 오류: " + error)
    full("출처 및 버전·시행일·URL·SHA256", True)
    source_labels = {"source_id": "출처 ID", "families": "계열", "title": "고시명",
        "notice_number": "고시번호", "announcement_version": "공고 버전", "effective_date": "시행일",
        "retrieved_at": "수집시각", "official_url": "공식 URL", "relative_path": "기준본 상대경로",
        "sha256": "출처 SHA256", "review_status": "원문 검토 상태", "coverage": "수록 범위", "review_note": "원문 검토 메모"}
    for source in notice["sources"]:
        full("출처: " + source["source_id"], True)
        for key, value in source.items():
            field(source_labels[key], ", ".join(value) if isinstance(value, list) else value)
    full("후보 조항 및 연결 주석·예외의 전체 스냅샷", True)
    if not notice["comparisons"]:
        if all(family["status"] == "complete" for family in notice["families"]):
            full("후보 없음(자동 탐색): 저장된 후보 대조 항목이 없습니다.")
        else:
            full("고시 대조 미완료: 저장된 후보 대조 항목이 없습니다.")
    clause_labels = {"clause_id": "조항 ID", "source_id": "출처 ID", "family": "계열", "code": "통제번호",
        "title": "조항명", "field": "분야", "source_anchor": "원문 위치", "text": "조항 전체 원문"}
    candidates = {comparison["clause_id"] for comparison in notice["comparisons"]}
    for clause in notice["clause_snapshots"]:
        full(("후보 조항: " if clause["clause_id"] in candidates else "연결 주석·예외 조항: ") + clause["clause_id"], True)
        for key, label in clause_labels.items():
            field(label, clause[key])
        field("연결 주석·정의·예외 ID", ", ".join(clause["qualifier_refs"]))
        field("조건 결합 구조(저장값)", _json(clause["condition"]))
    full("입력 사실 및 원문 인용", True)
    for fact in notice["facts"]:
        full("입력 사실: " + fact["fact_id"], True)
        field("사실 ID", fact["fact_id"])
        field("적용 시점", basis_names[fact["basis"]] + " / " + fact["basis"])
        field("대상 특성", fact["subject"])
        field("입력 필드", fact["source_field"])
        field("인용 위치(start, end)", f"{fact['start']}, {fact['end']}")
        field("입력 원문 인용", fact["quote"])
        field("입력 값 원문", fact["value_text"])
        field("추출 수치(원값)", fact["number"])
        field("추출 단위", fact["unit"])
    full("현재·목표별 조건 대조와 추가 질문", True)
    for comparison in notice["comparisons"]:
        full("대조 ID: " + comparison["comparison_id"], True)
        field("대조 계열", comparison["family"])
        field("대조 조항 ID", comparison["clause_id"])
        field("대조 출처 ID", comparison["source_id"])
        field("현재 조건 대조", assessment_names[comparison["current_assessment"]] + " / " + comparison["current_assessment"])
        field("목표 조건 대조", _target_description(comparison) + " / " + comparison["target_assessment"])
        field("대조 근거", comparison["rationale"])
        field("영향 항목 번호", ", ".join(map(str, comparison["affected_items"])))
        for condition in comparison["conditions"]:
            full(basis_names[condition["basis"]] + " 조건: " + condition["predicate_id"], True)
            field("조건 ID", condition["predicate_id"])
            field("조건 시점", basis_names[condition["basis"]] + " / " + condition["basis"])
            field("조건 원문", condition["condition_text"])
            field("조건 원문 위치", condition["source_anchor"])
            field("입력 사실 연결 ID", ", ".join(condition["fact_ids"]))
            field("정규화 값(저장 원값)", condition["normalized_value"])
            field("정규화 단위", condition["normalized_unit"])
            field("조건 상태", assessment_names[condition["assessment"]] + " / " + condition["assessment"])
            field("조건 대조 사유", condition["reason"])
        for question in comparison["missing_information"]:
            field("추가 확인 시점·조건", basis_names[question["basis"]] + " / " + question["predicate_id"])
            field("추가 확인 질문", question["question"])
    full("부록 2. 저장 기준본 manifest 전체", True)
    if notice["catalogue_manifest"] is None:
        full("저장 기준본 미제공: 고시 검토가 완료되지 않았습니다.")
    else:
        full(_json(notice["catalogue_manifest"]))


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
    def notice_comments(subject):
        full("개인 고시 대조 검토의견", True)
        if not subject["notice_comments"]:
            full("저장된 개인 고시 대조 검토의견 없음")
        for comment in subject["notice_comments"]:
            field("고시 대조 ID", comment["comparison_id"])
            field("개인 고시의견", comment["comment"])
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
        notice_comments(subject)
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
            field("공통 해당 수준", common.get("level"))
            field("공통 검토정보", common.get("note"))
            field("공통 법적 근거", ", ".join(common.get("law_refs", [])))
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
    field("의견 기준", "표준(고정)")
    field("과제 지문(SHA256)", result["task_fingerprint"])
    field("실행 옵션 지문(SHA256)", result["options_fingerprint"])
    field("분류 상태", result.get("status"))
    field("후보 판단 사유", result["candidate"]["reason"])
    field("후보 판단 불확실성", result["candidate"]["uncertainty"])
    if result.get("status") != "완료":
        full("미완료 · 검토필요 안내: 상태와 사유를 확인하여 사람이 검토해야 합니다.")
    if reviewer is not None:
        field("AI 에이전트", reviewer.get("reviewer_id"))
        field("관점", reviewer.get("persona"))
        full("2. 항목별 검토", True)
        items(reviewer)
        if impact:
            field("개인 점수", _display_score(reviewer.get("reviewer_score")))
            field("개인 점수(계산 원값)", _number(reviewer.get("reviewer_score")))
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
        notice_comments(reviewer)
    else:
        full("2. 공통 검토항목 및 에이전트별 검토의견", True)
        reviewers = result.get("reviewers", []) or []
        if not reviewers:
            full("개별 평가 미실시: AI 에이전트별 검토의견서를 만들지 않았습니다.")
            candidate = result.get("candidate") or {}
            full("후보 판단 사유: " + _text(candidate.get("reason")))
            full("후보 판단 불확실성: " + _text(candidate.get("uncertainty")))
            items({})
        for index, subject in enumerate(reviewers):
            personal(subject, index)
            items(subject)
            if impact:
                field("개인 점수(계산 원값)", _number(subject.get("reviewer_score")))
        full("3. AI 종합 검토의견", True)
        if impact:
            # A partial committee never acquires an apparent complete mean.
            complete = bool(reviewers) and all(_complete(subject) and subject.get("reviewer_score") is not None for subject in reviewers)
            field("에이전트 종합평균", _display_score(result.get("overall_avg")) if complete else "")
            field("종합평균(계산 원값)", _number(result.get("overall_avg")) if complete else "")
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
    full("AI 에이전트 검토 참고자료")
    full("AI가 생성한 분석·참고 의견입니다. 실제 심의 및 보안등급 확정은 담당자의 판단과 절차에 따릅니다.")
    _notice_rows(result["notice_review"], full, field)
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
    # Validate frozen source hashes, condition results, quotations, scores and
    # permitted fields before creating any output directory. No current
    # catalogue fingerprint is supplied when replaying an old saved result.
    validate_result(result)
    result = deepcopy(result)
    reviewers = result["reviewers"]
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
    validate_documents(documents, reviewers)
    return documents
