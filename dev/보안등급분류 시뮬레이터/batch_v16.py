"""v16 Excel batch processing with isolated clients and validated resumption.

No credentials or mutable global configuration enter this module. The caller
supplies a zero-argument client factory; every task obtains its own client.
Only the coordinator writes checkpoint/audit/workbook files. JSONL writes are
serialized and flushed per result; workbook replacement is atomic and periodic.

v16 differs from v15 in three places only: the 고시기준본 sheet has a 고시일
column before 시행일, a selected non-v16 result stops the run before any write
or model call (PreviousResultError), and screen-only progress/status/warning
strings are noun-ending. Every sentence stored in a checkpoint, workbook, audit
record, HWPX document or result is byte-identical to v15.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from classification_v16 import classify_task, normalize_options
from hwpx_writer_v16 import export_documents
from notice_catalogue_v16 import CatalogueError, load_catalogue
# Share the notice pipeline's injected-catalogue preflight; do not duplicate rules.
from notice_review_v16 import _preflight
from v16_domain import (
    COMPARISON_RULES_VERSION, GRADES, SCHEMA_VERSION, STATUSES,
    TASK_COLUMNS, OPTIONAL_TASK_COLUMNS, clean_input_text, format_score, make_result,
    options_fingerprint, task_fingerprint, task_snapshot,
    validate_result as _validate_result, validate_documents as _validate_documents,
)


# Input template marks only (spec 4.4): these four show '(필수)', every other
# column '(선택)'. Reading still requires 과제명 alone; TASK_COLUMNS is unchanged.
REQUIRED_TEMPLATE_COLUMNS = ("과제명", "연구목표", "연구내용", "기대효과")


RESULT_COLUMNS = ["연번", "과제명", "상태", "최종등급(참고)", "신뢰도", "종합평균",
                  "채점항목(선택)", "항목선택방식", "핵심고려지표", "AI 종합 검토의견",
                  "실제 심의위원회 논의 필요사항", "분류방식", "문서상태", "문서예정수",
                  "문서성공수", "문서실패수", "문서누락수", "문서경로"]


class BatchError(RuntimeError):
    """Safe, actionable batch-level I/O or persistence failure."""


# Screen-only fixed text; the bridge may show it as its dedicated progress event.
PREVIOUS_RESULT_MESSAGE = "기존 결과 파일 보호를 위해 중단. 새 결과 엑셀 경로 선택 필요"


class PreviousResultError(BatchError):
    """The selected output belongs to an earlier version or is not a v16 result.

    Raised after input validation and before any checkpoint initialisation,
    workbook replacement, audit append or model call, so the existing
    checkpoint, workbook and audit files remain byte-identical.
    """

    def __init__(self):
        super().__init__(PREVIOUS_RESULT_MESSAGE)


def _require(condition):
    if not condition:
        raise ValueError("저장 결과의 구조 또는 일치 검증에 실패했습니다.")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _decode(line):
    return json.loads(line, object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))


def _atomic_write(path, writer):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".v16-", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
        writer(temporary)
        for attempt in range(3):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(.05 * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def make_template(path):
    """Create the existing input flow using only clearly synthetic example rows.

    The guide text and header marks are the one v16 exception to 'Excel wording
    stays v15': four base columns (과제명·연구목표·연구내용·기대효과) are marked
    required, 세부사업명 and the four extra columns optional. Marks are display
    only; reading still requires 과제명 only.
    """
    target = Path(path).resolve()
    book = Workbook()
    try:
        guide = book.active
        guide.title = "작성안내"
        for row in [
            ["연구보안 등급분류 입력 양식"],
            ["분류대상 시트에 과제별 한 행씩 입력"],
            ["과제명·연구목표·연구내용·기대효과 4개 항목 필수 입력, "
             "세부사업명과 추가 4개 항목(추가 검토정보·부처 세부기준·현재 기술사양·개발목표 사양) 선택 입력"],
            ["과제명이 빈 행과 '(예시)'로 시작하는 행은 검토에서 제외, 같은 과제명은 첫 행만 처리"],
            ["추가 검토정보는 실제 확인한 사실만, 부처 세부기준은 적용할 기준이 있을 때만 입력"],
            ["현재 기술사양과 개발목표 사양은 구분해 입력"],
            ["AI 에이전트 검토의견은 참고 의견이며 실제 심의위원회 심의와 최종 등급 확정을 대신하지 않음"],
        ]:
            guide.append(row)
        sheet = book.create_sheet("분류대상")
        sheet.append([name + ("(필수)" if name in REQUIRED_TEMPLATE_COLUMNS else "(선택)")
                      for name in TASK_COLUMNS + OPTIONAL_TASK_COLUMNS])
        sheet.append(["합성 세부사업 A", "(예시) 합성 과제 A", "시험용 목표", "실제 과제정보가 아닌 합성 내용", "시험용 효과", "", "", "", ""])
        sheet.append(["합성 세부사업 B", "(예시) 합성 과제 B", "시험용 목표", "실제 과제정보가 아닌 합성 내용", "시험용 효과", "합성 검토정보", "합성 부처 기준", "속도 5 GHz", "속도 20 GHz"])
        alignment = Alignment(vertical="top", wrap_text=True)
        body_font = Font(name="맑은 고딕", size=10)
        header_font = Font(name="맑은 고딕", bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="243B53")
        for worksheet in book:
            worksheet.freeze_panes = "A2"
            for row in worksheet:
                for cell in row:
                    cell.font = body_font
                    cell.alignment = alignment
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
        guide.column_dimensions["A"].width = 110
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 32
        sheet.auto_filter.ref = sheet.dimensions
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, lambda temporary: book.save(temporary))
    except Exception:
        raise BatchError("입력 양식을 저장하지 못했습니다. 열린 파일과 저장 위치의 쓰기 권한을 확인하세요.") from None
    finally:
        book.close()
    return str(target)


def _append_checkpoint(path, encoded):
    # Unbuffered binary output lets a failed write/fsync be truncated exactly
    # to the previous valid UTF-8 record boundary, without a later close flush.
    with path.open("ab", buffering=0) as stream:
        previous_size = stream.tell()
        try:
            data = encoded.encode("utf-8")
            if stream.write(data) != len(data):
                raise OSError("Incomplete checkpoint write")
            os.fsync(stream.fileno())
        except Exception:
            try:
                stream.truncate(previous_size)
            except OSError:
                # The caller reports persistence failure; a subsequent resume
                # must validate every line rather than trust a damaged suffix.
                pass
            raise


def _read_tasks(path):
    """Return ``(tasks, excluded, cleaned)`` from the input workbook.

    Every row is cleaned first (clean_input_text); blank, '(예시)' and duplicate
    decisions then use the cleaned 과제명. ``cleaned`` is screen-only: True when
    a kept row has a task column whose cleaned text differs from its plain
    ``str(value).strip()``. Excluded rows and other columns do not count, and it
    never enters ``excluded`` (which is reported and warned about).
    """
    book = None
    try:
        book = load_workbook(path, read_only=True, data_only=False)
        sheet = book["분류대상"] if "분류대상" in book.sheetnames else book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, ())
        columns = [str(value or "").replace("(필수)", "").replace("(선택)", "").strip() for value in header]
        if "과제명" not in columns:
            raise ValueError("입력 엑셀에 '과제명' 열이 필요합니다. 입력 양식을 확인하세요.")
        relevant = TASK_COLUMNS + OPTIONAL_TASK_COLUMNS
        if any(columns.count(name) > 1 for name in relevant):
            raise ValueError("입력 엑셀의 같은 이름을 가진 열이 중복됩니다. 제목 행을 확인하세요.")
        tasks, seen, cleaned = [], set(), False
        excluded = {"blank": 0, "example": 0, "duplicate": 0}
        for values in rows:
            raw = {name: "" if value is None else str(value) for name, value in zip(columns, values)}
            row = {name: clean_input_text(value) for name, value in raw.items()}
            name = row.get("과제명", "")
            reason = "blank" if not name else "example" if name.startswith("(예시)") else "duplicate" if name in seen else None
            if reason:
                excluded[reason] += 1
                continue
            seen.add(name)
            cleaned = cleaned or any(row[column] != raw[column].strip() for column in relevant if column in raw)
            tasks.append(task_snapshot(row))
        return tasks, excluded, cleaned
    except (BatchError, ValueError):
        raise
    except Exception:
        raise BatchError("입력 엑셀을 읽지 못했습니다. 파일 형식과 읽기 권한을 확인하세요.") from None
    finally:
        if book is not None:
            book.close()


def _load_checkpoint(path, opts, tasks, warn):
    if not path.exists():
        return {}
    records = {}
    by_id = {task_fingerprint(task): task for task in tasks}
    mismatch = False
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                record = _decode(line)
                _validate_result(record)
                identity = record["task_fingerprint"]
                if (record["options_fingerprint"] == options_fingerprint(opts)
                        and record["catalogue_fingerprint"] == opts.catalogue_fingerprint
                        and identity in by_id):
                    _validate_result(record, opts, by_id[identity], catalogue_fingerprint=opts.catalogue_fingerprint)
                    records[identity] = record
                else:
                    mismatch = True
        if mismatch:
            warn("중간 저장의 입력·실행 옵션·고시 기준이 현재 실행과 다름. 불일치한 완료 평가 재사용 안 함")
        return {identity: record for identity, record in records.items() if record["status"] == "완료"}
    except Exception:
        warn("중간 저장파일에 구버전 또는 손상·불일치 구조 포함. 이전 완료 평가 재사용 없이 새로 처리")
        return {}


def _older_checkpoint(path):
    """True when any decodable record has an integer schema_version below v16's.

    Undecodable or differently shaped lines are not evidence of an older
    version; damaged v16 checkpoints keep the v15 warn-and-restart behaviour.
    """
    try:
        data = path.read_bytes()
    except OSError:
        # Absent or unreadable content cannot be classified as an older record.
        return False
    for line in data.splitlines():
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            continue
        if isinstance(record, dict):
            version = record.get("schema_version")
            if type(version) is int and version < SCHEMA_VERSION:
                return True
    return False


def _is_v16_workbook(path):
    """An existing result is v16 only when it opens with a 고시일 header."""
    book = None
    try:
        # Read bytes first so this check never holds a handle on the output.
        book = load_workbook(BytesIO(path.read_bytes()), read_only=True, data_only=False)
        if "고시기준본" not in book.sheetnames:
            return False
        header = next(book["고시기준본"].iter_rows(min_row=1, max_row=1, values_only=True), ())
        return "고시일" in header
    except Exception:
        return False
    finally:
        if book is not None:
            book.close()


def _guard_previous_result(output, checkpoint):
    """Stop before any write when the selected output is not a v16 result."""
    if _older_checkpoint(checkpoint):
        raise PreviousResultError()
    if (output.exists() or output.is_symlink()) and not _is_v16_workbook(output):
        raise PreviousResultError()


def _expected_files(result, opts=None):
    if result["reviewers"]:
        return len(result["reviewers"]) + 1
    if result["status"] == "후보제외":
        return 1
    return opts.num_reviewers + 1 if opts is not None else result["documents"]["expected_files"]


def regenerate_documents(saved_result, output_dir):
    """Return a copy with new document status; never call a model or mutate input."""
    _validate_result(saved_result)
    result = deepcopy(saved_result)
    expected = len(result["reviewers"]) + 1
    try:
        documents = export_documents(deepcopy(result), output_dir)
        _validate_documents(documents, result["reviewers"])
        _require(documents["expected_files"] == expected)
        result["documents"] = documents
        _validate_result(result)
    except Exception:
        result["documents"] = {"status": "실패", "expected_files": expected, "files": [],
                               "errors": ["HWPX 문서 저장에 실패했습니다. 저장 위치와 템플릿을 확인하세요."]}
    return result


def _document_counts(result):
    documents = result["documents"]
    completed = sum(entry["status"] == "완료" for entry in documents["files"])
    missing = documents["expected_files"] - completed
    failed = missing if documents["status"] in ("일부실패", "실패") else 0
    return documents["expected_files"], completed, failed, missing


def _counts(results):
    counts = {status: 0 for status in STATUSES}
    counts.update(documents_expected=0, documents_completed=0, documents_failed=0, documents_missing=0)
    for result in results:
        counts[result["status"]] += 1
        for key, value in zip(("documents_expected", "documents_completed", "documents_failed", "documents_missing"), _document_counts(result)):
            counts[key] += value
    return counts


def persist_regenerated_documents(report, saved_result, regenerated_result):
    """Persist one document-only update without evaluating any task again.

    Checkpoint, workbook and audit are separate stores. A successful checkpoint
    remains recoverable when Excel is locked. Returned document results describe
    actual generation; per-store status describes what was durably recorded.
    Neither this function nor its report contains credentials or client options.
    """
    def classification(result):
        return {key: value for key, value in result.items() if key != "documents"}

    try:
        _validate_result(saved_result)
        _validate_result(regenerated_result)
        _require(classification(saved_result) == classification(regenerated_result))
        previous = deepcopy(report)
        matches = [index for index, result in enumerate(previous["results"])
                   if result["task_fingerprint"] == saved_result["task_fingerprint"]]
        _require(len(matches) == 1 and classification(previous["results"][matches[0]]) == classification(saved_result))
    except Exception:
        raise BatchError("문서 재생성 전후의 분류 결과가 일치하지 않습니다. 기존 분류 결과와 기록은 보존됩니다.") from None
    result = deepcopy(regenerated_result)
    updated = deepcopy(previous)
    updated["results"][matches[0]] = result
    updated["counts"] = _counts(updated["results"])
    persistence = {"status": "실패", "checkpoint": "미시도", "workbook": "미시도", "audit": "미시도", "warnings": []}

    def warn(message):
        persistence["warnings"].append(message)
        updated.setdefault("warnings", []).append(message)

    def finish():
        states = [persistence[key] for key in ("checkpoint", "workbook", "audit")]
        persistence["status"] = "완료" if all(state == "완료" for state in states) else ("일부실패" if "완료" in states else "실패")
        updated["document_persistence"] = deepcopy(persistence)
        return {"result": result, "report": updated, "persistence": persistence}

    try:
        source, output = Path(previous["input_path"]).resolve(), Path(previous["output_path"]).resolve()
        checkpoint, audit = Path(previous["checkpoint_path"]).resolve(), Path(previous["audit_path"]).resolve()
        _require(source != output and output.is_file() and checkpoint.is_file())
        _require(not os.path.samefile(source, output))
        _require(checkpoint == Path(str(output) + ".checkpoint.jsonl"))
        _require(audit == Path(str(output) + ".audit.jsonl"))
        _require(previous["selection_mode"] in ("auto", "manual"))
        tasks, _, _ = _read_tasks(source)
        ordered_ids = [task_fingerprint(task) for task in tasks]
        _require(ordered_ids == previous["input_fingerprints"])
        by_id = {task_fingerprint(task): task for task in tasks}
        report_ids = [entry["task_fingerprint"] for entry in previous["results"]]
        _require(len(set(report_ids)) == len(report_ids))
        _require(report_ids == [identity for identity in ordered_ids if identity in set(report_ids)])
        for entry in previous["results"]:
            _validate_result(entry)
            _require(entry["task_snapshot"] == by_id[entry["task_fingerprint"]])
            _require(entry["options_fingerprint"] == previous["options_fingerprint"])
            _require(entry["catalogue_fingerprint"] == previous["catalogue_fingerprint"])
        latest = {}
        with checkpoint.open("r", encoding="utf-8") as stream:
            for line in stream:
                entry = _decode(line)
                _validate_result(entry)
                _require(entry["options_fingerprint"] == previous["options_fingerprint"])
                _require(entry["catalogue_fingerprint"] == previous["catalogue_fingerprint"])
                latest[entry["task_fingerprint"]] = entry
        _require(set(latest) == set(report_ids))
        stale = any(latest[entry["task_fingerprint"]] != entry for entry in previous["results"])
        for entry in previous["results"]:
            _require(classification(latest[entry["task_fingerprint"]]) == classification(entry))
        if stale:
            # Return the current stored view as well as refusing all writes.
            updated["results"] = [deepcopy(latest[identity]) for identity in report_ids]
            updated["counts"] = _counts(updated["results"])
            raise ValueError("stale report")
    except Exception:
        warn("문서 생성 완료, 결과 기록 갱신 중단. 원래 입력·실행 설정·중간 저장의 일치 여부 확인 필요. 기존 기록 변경 없음")
        return finish()

    try:
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        _append_checkpoint(checkpoint, encoded)
        persistence["checkpoint"] = "완료"
    except Exception:
        persistence["checkpoint"] = "실패"
        warn("문서 생성 완료, 중간 저장 갱신 실패. 이전 중간 저장과 결과 엑셀 보존")
    if persistence["checkpoint"] == "완료":
        try:
            _save_workbook(output, updated["results"], SimpleNamespace(selection_mode=previous["selection_mode"]))
            persistence["workbook"] = "완료"
        except Exception:
            persistence["workbook"] = "실패"
            warn("문서 상태 중간 저장 완료, 결과 엑셀 갱신 실패. 열린 엑셀 종료 후 다시 저장 필요. 이전 엑셀 보존, 중간 저장으로 복구 가능")
    try:
        event = {"schema_version": SCHEMA_VERSION, "run_id": uuid4().hex,
                 "timestamp": datetime.now(timezone.utc).isoformat(), "event": "batch_documents_regenerated",
                 "task_fingerprint": result["task_fingerprint"], "options_fingerprint": result["options_fingerprint"],
                 "status": result["status"], "document_status": result["documents"]["status"],
                 "documents_expected": result["documents"]["expected_files"],
                 "documents_completed": _document_counts(result)[1],
                 "checkpoint_status": persistence["checkpoint"], "workbook_status": persistence["workbook"]}
        _append_checkpoint(audit, json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        persistence["audit"] = "완료"
    except Exception:
        persistence["audit"] = "실패"
        updated["audit_status"] = "실패"
        warn("문서 재생성 감사기록 저장 실패. 문서 생성과 중간 저장·엑셀 갱신 상태 각각 확인 필요")
    return finish()


CELL_CHUNK_SIZE = 15000  # Also keeps non-BMP UTF-16 cells below Excel's limit.
NOTICE_COLUMNS = ["과제명", "과제지문", "범위", "범위상태", "후보상태", "대조ID", "조항ID", "출처ID",
    "통제번호", "조항명", "조항원문", "원문위치", "연결조항", "조건구조", "현재결과", "목표결과", "근거", "관련항목",
    "부족정보", "탐색조항", "제외조항", "범위오류"]
CONDITION_COLUMNS = ["과제명", "과제지문", "기록종류", "대조ID", "조항ID", "조건ID", "시점", "조건", "사실ID",
    "입력인용", "값", "단위", "결과", "근거", "원문위치"]
CATALOGUE_COLUMNS = ["과제명", "과제지문", "기록종류", "기준본ID", "기준지문", "대조규칙버전", "출처ID", "범위",
    "고시명", "고시번호", "버전", "고시일", "시행일", "URL", "해시", "상대경로", "수집시각", "검토상태", "처리범위", "검토메모", "저장원문"]


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _append_row(sheet, values):
    """Split EVERY string before openpyxl's silent 32767-character truncation.

    Continuation rows retain column positions; the last column identifies each
    part. Joining that column across the row's parts recovers the original text.
    Numeric cells appear only in the first part and remain numeric.
    """
    parts = [[value[i:i + CELL_CHUNK_SIZE] for i in range(0, len(value), CELL_CHUNK_SIZE)] or [""]
             if isinstance(value, str) else [value] for value in values]
    count = max(map(len, parts), default=1)
    for index in range(count):
        sheet.append([part[index] if index < len(part) else None for part in parts] + [f"{index + 1}/{count}"])
        # sheet[row] computes max_column over every existing cell. Use the
        # just-appended width to keep batch row creation linear.
        for column in range(1, len(values) + 2):
            cell = sheet.cell(sheet._current_row, column)
            if isinstance(cell.value, str):
                cell.data_type = "s"


def _notice_rows(book, result):
    notice = result["notice_review"]
    prefix = [result["task_name"], result["task_fingerprint"]]
    clauses = {entry["clause_id"]: entry for entry in notice["clause_snapshots"]}
    facts = {entry["fact_id"]: entry for entry in notice["facts"]}
    families = {entry["family"]: entry for entry in notice["families"]}
    for family in notice["families"]:
        _append_row(book["고시대조"], prefix + [family["family"], family["status"],
            "후보 있음" if family["candidate_ids"] else "후보 없음" if family["status"] == "complete" else "탐색 미완료",
            "", "", "", "", "", "", "", "", "", "", "", "", "", _json(notice["blocking_reasons"]),
            _json(family["screened_ids"]), _json(family["excluded"]), _json(family["errors"])])
    candidates = set()
    for comparison in notice["comparisons"]:
        clause = clauses[comparison["clause_id"]]
        candidates.add(clause["clause_id"])
        _append_row(book["고시대조"], prefix + [comparison["family"], families[comparison["family"]]["status"], "후보",
            comparison["comparison_id"], clause["clause_id"], clause["source_id"], clause["code"], clause["title"],
            clause["text"], clause["source_anchor"], _json(clause["qualifier_refs"]), _json(clause["condition"]),
            comparison["current_assessment"], comparison["target_assessment"], comparison["rationale"],
            _json(comparison["affected_items"]), _json(comparison["missing_information"]), "", "", ""])
        for condition in comparison["conditions"]:
            _append_row(book["조건별근거"], prefix + ["조건", comparison["comparison_id"], clause["clause_id"],
                condition["predicate_id"], condition["basis"], condition["condition_text"], _json(condition["fact_ids"]),
                _json([facts[identity] for identity in condition["fact_ids"]]), condition["normalized_value"],
                condition["normalized_unit"], condition["assessment"], condition["reason"], condition["source_anchor"]])
    for clause in notice["clause_snapshots"]:
        if clause["clause_id"] not in candidates:
            _append_row(book["고시대조"], prefix + [clause["family"], families[clause["family"]]["status"], "연결조항",
                "", clause["clause_id"], clause["source_id"], clause["code"], clause["title"], clause["text"], clause["source_anchor"],
                _json(clause["qualifier_refs"]), _json(clause["condition"]), "", "", "", "", "", "", "", ""])
    for fact in notice["facts"]:
        _append_row(book["조건별근거"], prefix + ["입력사실", "", "", "", fact["basis"], fact["subject"], fact["fact_id"],
            _json(fact), fact["number"], fact["unit"], "", fact["value_text"],
            _json(dict(source_field=fact["source_field"], start=fact["start"], end=fact["end"]))])
    base = prefix + ["기준본", notice["catalogue_id"], notice["catalogue_fingerprint"], COMPARISON_RULES_VERSION]
    # Eleven blanks: 출처ID through 수집시각, including the v16 고시일 column.
    _append_row(book["고시기준본"], base + ["", "", "", "", "", "", "", "", "", "", "", notice["status"],
        _json(notice["families"]), _json(notice["blocking_reasons"]), _json(notice["catalogue_manifest"])])
    for source in notice["sources"]:
        _append_row(book["고시기준본"], prefix + ["출처", notice["catalogue_id"], notice["catalogue_fingerprint"], COMPARISON_RULES_VERSION,
            source["source_id"], _json(source["families"]), source["title"], source["notice_number"], source["announcement_version"],
            source["announcement_date"], source["effective_date"], source["official_url"], source["sha256"], source["relative_path"], source["retrieved_at"],
            source["review_status"], source["coverage"], source["review_note"], _json(source)])


def _save_workbook(path, results, opts):
    book = Workbook()
    try:
        sheet = book.active
        sheet.title = "분류결과"
        sheet.append(RESULT_COLUMNS + ["이어쓰기"])
        summary = book.create_sheet("요약")
        summary.append(["구분", "건수", "비율", "이어쓰기"])
        for name, columns in (("고시대조", NOTICE_COLUMNS), ("조건별근거", CONDITION_COLUMNS), ("고시기준본", CATALOGUE_COLUMNS)):
            book.create_sheet(name).append(columns + ["이어쓰기"])
        for index, result in enumerate(results, 1):
            expected, completed, failed, missing = _document_counts(result)
            rationale = result["rationale"]
            if result["unresolved_reasons"]:
                rationale += ("\n" if rationale else "") + "\n".join(result["unresolved_reasons"])
            row = sheet._current_row + 1
            _append_row(sheet, [index, result["task_name"], result["status"], result["final_grade"], result["confidence"],
                result["overall_avg"], ", ".join(result["selected_items"]),
                "직접 선택" if opts.selection_mode == "manual" else "자동 선택", "", rationale,
                result["discussion_points"], "체크리스트" if result["method"] == "checklist" else "국가영향 지표",
                result["documents"]["status"], expected, completed, failed, missing,
                "\n".join(entry["path"] for entry in result["documents"]["files"])])
            if result["overall_avg"] is not None:
                display = format_score(result["overall_avg"])
                places = max(2, len(display.split(".", 1)[1]) if "." in display else 0)
                sheet.cell(row, 6).number_format = "0." + "0" * places
            _notice_rows(book, result)
        counts = _counts(results)
        _append_row(summary, ["전체 과제 수", len(results), 1 if results else 0])
        grade_counts = Counter(result["final_grade"] for result in results if result["status"] == "완료")
        for grade in GRADES:
            count = grade_counts[grade]
            _append_row(summary, [grade + "(참고)", count, count / len(results) if results else 0])
        for status in STATUSES:
            _append_row(summary, [status, counts[status], counts[status] / len(results) if results else 0])
        for label, key in (("문서 예정 수", "documents_expected"), ("문서 성공 수", "documents_completed"),
                           ("문서 실패 수", "documents_failed"), ("문서 누락 수", "documents_missing")):
            _append_row(summary, [label, counts[key], None])
        alignment = Alignment(vertical="top", wrap_text=True)
        body_font = Font(name="맑은 고딕", size=10)
        header_font = Font(name="맑은 고딕", bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="243B53")
        for worksheet in book:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for row in worksheet:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
                    cell.alignment = alignment
                    cell.font = body_font
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
            for column in worksheet.columns:
                worksheet.column_dimensions[column[0].column_letter].width = 22
        sheet.column_dimensions["J"].width = 65
        sheet.column_dimensions["K"].width = 45
        _atomic_write(path, lambda temporary: book.save(temporary))
    except Exception:
        raise BatchError("결과 엑셀을 저장하지 못했습니다. 열린 파일을 닫고 저장 위치와 쓰기 권한을 확인하세요. 중간 저장 결과는 보존됩니다.") from None
    finally:
        book.close()


def _error_result(task, opts, manifest):
    result = make_result(task, opts, catalogue_manifest=manifest)
    result.update(status="오류", unresolved_reasons=["과제 분류에 실패했습니다. 입력 또는 모델 연결 설정을 확인하세요."])
    _validate_result(result, opts, task)
    return result


def run_excel(in_path, out_path, options, client_factory, *, resume=True, workers=3,
              make_forms=True, progress_cb=None, status_cb=None, cancel_event=None,
              catalogue=None, output_dir=None, notice_cb=None):
    """Process selected rows; return ordered results, counts and persistence status.

    ``client_factory()`` is called once per new task, inside its worker. Options
    are frozen before workers start; factories/clients/keys are never serialized.
    Both callbacks accept one string and may run on workers, so GUI callers must
    queue messages. ``notice_cb`` receives the fixed name "input_cleaned" once
    when a kept row's text was cleaned, after the previous-result guard and
    before any write or model call; it is screen-only and never stored or warned.
    Cancellation stops new work and preserves in-flight results.
    Global file failures raise BatchError; individual task/document failures do
    not discard successful classifications. Audit errors are reported separately.
    """
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("동시 처리 수는 1~8 정수여야 합니다.")
    provisional = normalize_options(options, allow_row_policy=True)
    source, output = Path(in_path).resolve(), Path(out_path).resolve()
    if source == output or (source.exists() and output.exists() and os.path.samefile(source, output)):
        raise BatchError("결과 저장 위치는 입력 엑셀과 달라야 합니다.")
    tasks, input_counts, input_cleaned = _read_tasks(source)
    # Validate every row before creating clients or changing any output store.
    for task in tasks:
        normalize_options(provisional, ministry_policy_context=task["부처 세부기준"])
    cat = load_catalogue() if catalogue is None else catalogue
    manifest, _ = _preflight(cat)
    if provisional.catalogue_fingerprint and provisional.catalogue_fingerprint != cat.fingerprint:
        raise ValueError("실행 옵션과 고시 기준이 일치하지 않습니다.")
    opts = normalize_options(provisional.to_dict() | {"catalogue_fingerprint": cat.fingerprint}, allow_row_policy=True)
    checkpoint = Path(str(output) + ".checkpoint.jsonl")
    audit = Path(str(output) + ".audit.jsonl")
    # After input validation, before checkpoint/workbook/audit writes or any
    # model call, regardless of resume: never overwrite a non-v16 result.
    _guard_previous_result(output, checkpoint)
    if input_cleaned and notice_cb is not None:
        notice_cb("input_cleaned")
    run_id = uuid4().hex
    forms = Path(output_dir).resolve() if output_dir is not None else output.with_name(output.stem + "_HWPX") / run_id
    warnings = []

    def notify(callback, message):
        if callback is not None:
            callback(str(message))

    def warn(message):
        warnings.append(message)
        notify(progress_cb, message)
        notify(status_cb, message)

    if any(input_counts.values()):
        warn(f"입력 제외: 빈 과제명 {input_counts['blank']}건, 예시 {input_counts['example']}건, 중복 과제명 {input_counts['duplicate']}건. 중복은 첫 행 유지")
    reused = _load_checkpoint(checkpoint, opts, tasks, warn) if resume else {}
    ordered_ids = [task_fingerprint(task) for task in tasks]
    saved = {}
    audit_status = "완료"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        def initialize(temporary):
            # Keep every validated reusable classification in the initial atomic
            # snapshot, even if cancellation interrupts later document retries.
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                for identity in ordered_ids:
                    if identity in reused:
                        stream.write(json.dumps(reused[identity], ensure_ascii=False, allow_nan=False,
                                                separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        _atomic_write(checkpoint, initialize)
    except Exception:
        raise BatchError("중간 저장파일을 준비하지 못했습니다. 저장 위치와 쓰기 권한을 확인하세요. 기존 파일은 보존됩니다.") from None

    def ordered():
        return [saved[identity] for identity in ordered_ids if identity in saved]

    def persist(result):
        nonlocal audit_status
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        try:
            _append_checkpoint(checkpoint, encoded)
        except Exception:
            raise BatchError("과제 결과의 중간 저장에 실패했습니다. 이전 저장 결과를 보존하고 처리를 중단합니다.") from None
        saved[result["task_fingerprint"]] = result
        if audit_status != "실패":
            try:
                event = {"schema_version": SCHEMA_VERSION, "run_id": run_id,
                         "timestamp": datetime.now(timezone.utc).isoformat(), "event": "batch_task_saved",
                         "task_fingerprint": result["task_fingerprint"], "options_fingerprint": result["options_fingerprint"],
                         "status": result["status"], "document_status": result["documents"]["status"]}
                with audit.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                audit_status = "실패"
                warn("감사기록 저장 실패: 분류 결과 중간 저장 완료, 감사기록 누락. 저장 위치와 쓰기 권한 확인 필요")
        notify(status_cb, f"처리 {len(saved)}/{len(tasks)}건 · 분류 {result['status']} · 문서 {result['documents']['status']}")

    def documents(result):
        result = deepcopy(result)
        if make_forms:
            docs = result["documents"]
            if docs["status"] != "완료" or any(not Path(entry["path"]).is_file() for entry in docs["files"]):
                result = regenerate_documents(result, forms)
        else:
            result["documents"] = {"status": "미생성", "expected_files": _expected_files(result, opts), "files": [], "errors": []}
        return result

    # Reused results are checkpointed before starting any new model requests.
    for task in tasks:
        identity = task_fingerprint(task)
        if identity in reused:
            persist(documents(reused[identity]))

    def process(task):
        try:
            result = classify_task(task, opts, client_factory(), progress_callback=lambda message: notify(progress_cb, message), catalogue=cat)
            _validate_result(result, opts, task)
        except Exception:
            result = _error_result(task, opts, manifest)
        return documents(result)

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    pending = iter(task for task in tasks if task_fingerprint(task) not in reused)
    # Every result is durable in JSONL; cap the expensive full-workbook snapshots.
    interval = max(50, (len(tasks) + 4) // 5)
    notify(progress_cb, f"대상 {len(tasks)}건 · 이전 완료 재사용 {len(reused)}건 · 동시 처리 {workers}건")
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="v16-batch") as pool:
        active = set()

        def fill():
            while len(active) < workers and not cancelled():
                task = next(pending, None)
                if task is None:
                    break
                active.add(pool.submit(process, task))

        fill()
        while active:
            finished, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in finished:
                active.remove(future)
                persist(future.result())
                if len(saved) % interval == 0:
                    _save_workbook(output, ordered(), opts)
            fill()
    results = ordered()
    _save_workbook(output, results, opts)
    status = "취소" if cancelled() else "완료"
    counts = _counts(results)
    notify(status_cb, f"대량 처리 {status} · 정상 {counts['완료']} · 검토필요 {counts['검토필요']} · 후보제외 {counts['후보제외']} · 오류 {counts['오류']} · 문서 누락 {counts['documents_missing']} · 감사기록 {audit_status}")
    return {"status": status, "results": results, "counts": counts, "warnings": warnings,
            "input_counts": input_counts, "task_count": len(tasks), "reused_count": len(reused),
            "output_path": str(output), "checkpoint_path": str(checkpoint), "audit_path": str(audit),
            "audit_status": audit_status, "documents_dir": str(forms),
            "input_path": str(source), "input_fingerprints": ordered_ids,
            "options_fingerprint": options_fingerprint(opts), "selection_mode": opts.selection_mode,
            "catalogue_fingerprint": cat.fingerprint}
