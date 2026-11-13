"""결과 엑셀(1.4.0 spec 7절 R6): 보이는 시트 셋 `초과·근접 조항`·`과제별 검토 결과`·`고시 조항별 상세`와 숨김 시트
`처리내역`을 이 순서로 둔다. 파일을 열면 `초과·근접 조항`이 보인다. 개별 검토도 같은 형식(과제 1건)으로 저장한다.

- `초과·근접 조항`: 중점 과제(종합이 초과·근접)의 초과·근접 조항을 사양 줄마다 한 줄씩. 과제 순서는
  brief.tally_briefs가 준 중점 순서(종합 초과 → 종합 근접, 같으면 결과 순서), 그 안은 brief의 조항·사양 줄 순서 그대로다.
  줄이 하나도 없으면 머리글 아래 첫 칸에 brief.EMPTY_MESSAGE 한 줄.
- `과제별 검토 결과`: 모든 과제 한 줄씩(결과 순서). 표 아래 빈 줄 하나 뒤에 실행 정보 줄(RUN_INFO_LABELS 순서, 머리줄 없이
  첫 칸 항목 이름·둘째 칸 값)을 적는다. `종합 결과` 값은 brief.tally_text가 만든 한 줄이다.
- `고시 조항별 상세`: 판정 기록의 모든 비교와 매핑 없는 관련 조항(판정 엔진의 값 그대로).
- `처리내역`: 실행 기록. 엑셀의 '시트 숨기기 취소'로 볼 수 있는 보통 숨김이다. 기록 항목은 줄이지 않는다.

앞의 두 시트와 처리내역의 간단한 결과 줄은 과제 결과의 `brief`(brief.build_brief가 만든 사전, spec R7-1)를 그대로 옮긴다.
이 모듈은 판정·사유·건수·과제 순서를 다시 계산하지 않는다(판정 이름을 비교해 세지 않는다). brief가 없는 결과, 종합 건수
함수가 모르는 값, 과제 묶음과 초과·근접 조항이 어긋난 결과는 저장 전에 거부한다(ValueError — 빈칸·0으로 조용히 채우거나
줄을 조용히 빼지 않는다). 공통 안내 세 줄과 `참고` 열·줄은 어디에도 쓰지 않는다(spec R3).

시트·열 이름과 순서, 실행 정보 줄의 항목 이름은 명세 글자 그대로다. `고시 조항별 상세`·`처리내역`의 값 문자열(판정·확인
표시·상태·기준 출처)은 판정 엔진·pipeline의 값을 그대로 쓴다. `입력 행 번호`는 일괄 검토의 입력 엑셀 행 번호(개별 검토는
빈칸), `정부지원연구개발비(백만원)`·조항 수는 숫자 셀이다. 처리내역에서 과제를 가리키는 줄은 일괄 검토이면
`N행 연구개발과제명`, 개별 검토이면 `연구개발과제명`으로 시작한다. 여러 값은 "; "로 잇는다(추가 검토 필요 칸만 조항마다
줄바꿈). 긴 셀은 엑셀 한도(32,767자) 안에서 잘라 "…(이하 생략, N자)"를 붙인다. 글 셀은 언제나 글로 쓴다(수식으로
해석되지 않도록). 키 원문은 받지도 쓰지도 않는다. 저장 위치는 호출자가 준다(프로그램 폴더 밖).
행 높이는 모든 시트에서 한 줄(ROW_HEIGHT)로 고정한다(1.4.1). 여러 줄인 칸은 첫 줄만 보이고 값은 그대로다.

run_info(모두 선택): run_time(문자열 또는 datetime), catalogue_id, catalogue_fingerprint, table_fingerprint,
provider, model, near_percent, families(검토 대상 고시), excluded([{row_number, reason, value}]), blank_rows,
option_warnings([{row_number, field, value, message}] — 선택 칸 경고), file_warnings([str]),
semantic_model_fingerprint·semantic_vectors_fingerprint(PC 안 의미 검색 모델·조항 벡터 지문, 비면 '불러오지 못함').
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from ai_stages import STAGE_EXTRACT, STAGE_LABELS, STAGE_PAIR, STAGE_SCREEN
import brief
import pipeline

SHEET_FOCUS = "초과·근접 조항"
SHEET_SUMMARY = "과제별 검토 결과"
SHEET_DETAIL = "고시 조항별 상세"
SHEET_LOG = "처리내역"          # 숨김 시트

FOCUS_COLUMNS = ("입력 행 번호", "연구개발과제명", "판정", "검토 대상 고시", "통제번호", "고시 조항명", "사양 비교 결과", "최종목표 사양",
                 "고시 기준 사양", "차이", "확인 표시", "사유")
SUMMARY_COLUMNS = ("입력 행 번호", "연구개발과제명", "판정", "사유", "국가첨단전략기술", "국가핵심기술", "전략물자(이중용도)",
                   "전략물자(군용)", "초과 조항 수", "근접 조항 수", "추가 검토 필요", "연구개발단계", "정부지원연구개발비(백만원)",
                   "입력 정보", "상태", "오류 사유", "안내")
DETAIL_COLUMNS = ("입력 행 번호", "연구개발과제명", "검토 대상 고시", "조항 ID", "통제번호", "고시 조항명", "갈래 설명", "고시 기준 물리량",
                  "비교어", "고시 기준 사양", "고시 기준 단위", "고시 기준 출처", "고시 기준 원문 인용", "최종목표 물리량",
                  "최종목표 사양(원문)", "사용한 값", "최종목표 단위", "환산한 최종목표 사양", "최종목표 인용", "최종목표 위치", "차이 %",
                  "사양 비교 결과", "조항 검토 결과", "비교 불가 사유", "빠진 고시 기준", "확인 표시", "추가 확인 조건 원문", "매핑 근거")
LOG_COLUMNS = ("항목", "값")
# `과제별 검토 결과` 표 아래 실행 정보 줄의 항목 이름(이 순서). 마지막 이름은 건수 줄과 행마다 한 줄에 같이 쓴다.
RUN_TIME_LABEL = "실행 일시"
RUN_VERSION_LABEL = "프로그램 버전"
RUN_MODEL_LABEL = "AI 모델"
RUN_TALLY_LABEL = "종합 결과"
RUN_EXCLUDED_LABEL = "검토에서 빠진 행"
RUN_INFO_LABELS = (RUN_TIME_LABEL, RUN_VERSION_LABEL, RUN_MODEL_LABEL, RUN_TALLY_LABEL, RUN_EXCLUDED_LABEL)
RUN_MODEL_TEXT = "{} · {}"        # '{제공자} · {모델}'. 없는 쪽은 그 자리에 '(없음)'
RUN_EXCLUDED_COUNT = "{}건"
REVIEW_LINE = "{} — {}"           # 추가 검토 필요 칸의 한 줄: '{고시 이름} {통제번호} {고시 조항명} — {남긴 이유}, {비교하지 못한 이유}'
REVIEW_SEPARATOR = "\n"           # 추가 검토 필요 칸은 조항마다 줄을 바꾼다
# 처리내역의 간단한 결과 줄의 값 글
SEMANTIC_LOG_UNAVAILABLE = "의미 검색을 쓸 수 없음(세부 기술 일치 확인 안 함, {}건)"
SEMANTIC_LOG_USED = "의미 검색 사용"
SEMANTIC_LOG_NOT_NEEDED = "확인할 조항 없음"
RANK_LOG = "같은 고시 안 상위 {}위"
FINGERPRINT_MISSING = "불러오지 못함"
HIDDEN_LOG = "{}: 넣지 않은 관련 조항 {}건 · 남기지 않은 세부 일치 {}건"
_SEMANTIC_VALUES = (brief.SEMANTIC_USED, brief.SEMANTIC_UNAVAILABLE, brief.SEMANTIC_NOT_NEEDED)
# 처리내역의 합계 줄: (항목 이름, 더할 brief.counts 키들). 해당 조항 수 = 초과·근접·미달 조항 수의 합.
_COUNT_TOTALS = (("해당 조항 수 합계", ("over", "near", "under")), ("추가 검토 필요 수 합계", ("review",)),
                 ("간단한 결과에 넣지 않은 관련 조항 수 합계", ("hidden",)),
                 ("세부 기술 일치로 답했지만 남기지 않은 조항 수 합계", ("detail_match_dropped",)))
# 매핑 없는 조항 줄에서 비워 두는 비교 칸 수: '고시 기준 물리량'부터 '사양 비교 결과'까지.
_COMPARISON_BLANKS = DETAIL_COLUMNS.index("사양 비교 결과") - DETAIL_COLUMNS.index("고시 기준 물리량") + 1

# 화면 맨 아래에 늘 보이는 한 줄의 글(연결 함수가 처음 상태의 note로 쓴다). 결과 엑셀에는 쓰지 않는다(spec R3).
NOTE_TEXT = "이 결과는 고시 수치 기준과의 참고 대조이며 고시 해당 여부의 공식 판정이 아님."
OPERATOR_LABELS = {"ge": "이상", "gt": "초과", "le": "이하", "lt": "미만"}
ORIGIN_LABELS = {"structured": "정리된 기준", "extracted": "AI가 읽은 기준값"}
SEPARATOR = "; "
CELL_LIMIT = 32767
ROW_HEIGHT = 16.5      # 모든 시트의 행 높이(포인트, 1.4.1). 엑셀의 한 줄 기본 높이이며 여러 줄인 칸이 있어도 이 높이다
_TRUNCATE_HEAD = "…(이하 생략, "
_TRUNCATE_TAIL = "자)"
_NOT_GIVEN = "(없음)"
_NO_TITLE = "(연구개발과제명 없음)"

__all__ = ["SHEET_FOCUS", "SHEET_SUMMARY", "SHEET_DETAIL", "SHEET_LOG", "FOCUS_COLUMNS", "SUMMARY_COLUMNS", "DETAIL_COLUMNS",
           "LOG_COLUMNS", "RUN_INFO_LABELS", "SEMANTIC_LOG_UNAVAILABLE", "SEMANTIC_LOG_USED", "SEMANTIC_LOG_NOT_NEEDED",
           "RANK_LOG", "FINGERPRINT_MISSING", "HIDDEN_LOG", "NOTE_TEXT", "OPERATOR_LABELS", "ORIGIN_LABELS", "SEPARATOR",
           "CELL_LIMIT", "ROW_HEIGHT", "fit_cell", "write_report"]


# ── 셀 도우미 ─────────────────────────────────────────────────────────

def fit_cell(value):
    """글 셀을 엑셀 한도 안으로 자른다. 잘렸으면 끝에 '…(이하 생략, N자)'(N = 뺀 글자 수)를 붙인다."""
    if not isinstance(value, str) or len(value) <= CELL_LIMIT:
        return value
    omitted = len(value) - CELL_LIMIT
    # 꼬리표를 붙이면 그만큼 더 빼야 하므로 자릿수가 늘어날 때까지 맞춘다.
    while True:
        tail = f"{_TRUNCATE_HEAD}{omitted}{_TRUNCATE_TAIL}"
        keep = CELL_LIMIT - len(tail)
        if len(value) - keep == omitted:
            return value[:keep] + tail
        omitted = len(value) - keep


def _clean(value):
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
        return fit_cell(value) if value else None
    return value


def _join(values):
    return SEPARATOR.join(str(v) for v in values if v not in (None, ""))


def _append(sheet, values):
    sheet.append([_clean(value) for value in values])
    # 여러 줄인 칸이 있어도 행이 늘어나지 않게 한 줄 높이로 고정한다(값·줄바꿈은 그대로 — 셀을 고르거나 행을 늘려 본다).
    sheet.row_dimensions[sheet.max_row].height = ROW_HEIGHT
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"   # '='로 시작해도 수식이 아니라 글로 둔다
            if "\n" in cell.value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")


def _header(sheet, columns, widths=None):
    _append(sheet, columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, width in enumerate(widths or (), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"


def _as_dict(result):
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def _family_label(family):
    return pipeline.FAMILY_LABELS.get(family, family)


def _row_number(result):
    row_number = result.get("row_number")
    return row_number if type(row_number) is int else None


def _task_label(result):
    """처리내역에서 과제를 가리키는 글: 일괄 검토는 'N행 연구개발과제명', 개별 검토는 '연구개발과제명'."""
    title = result.get("title", "") or _NO_TITLE
    row_number = _row_number(result)
    return f"{row_number}행 {title}" if row_number is not None else title


def _fund_cell(value):
    """정부지원연구개발비(백만원): 숫자 셀(정수 또는 실수) 또는 빈칸. 값은 pipeline이 이미 정리한 10진수 글이다."""
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return str(value)   # 정리되지 않은 값은 숫자로 바꾸지 않고 글 그대로 보인다
    if not number.is_finite():
        return str(value)
    return int(number) if number == number.to_integral_value() else float(number)


def _brief(result):
    """과제 결과의 간단한 결과 사전. 없으면 ValueError(앞의 두 시트·처리내역 줄을 빈칸·0으로 조용히 채우지 않는다)."""
    data = result.get("brief")
    if not isinstance(data, dict):
        raise ValueError(f"간단한 결과(brief)가 없는 과제 결과: {_task_label(result)}")
    return data


def _run_summary(results):
    """저장 전에 확인하고 실행 한 번의 종합 건수·과제 순서(brief.tally_briefs의 결과)를 돌려준다.

    간단한 결과가 없는 결과, 종합 건수 함수가 모르는 값은 ValueError. 과제 묶음과 초과·근접 조항이 어긋난 결과도
    받지 않는다 — 중점 묶음이 아닌 과제의 초과·근접 조항, 중점 과제의 빈 조항 목록·빈 사양 줄은 `초과·근접 조항`
    시트에서 줄이 조용히 빠지게 된다.
    """
    summary = brief.tally_briefs([_brief(result) for result in results])
    focus_positions = set(summary["groups"][brief.GROUP_FOCUS])
    for position, result in enumerate(results):
        clauses = result["brief"]["focus"]
        if bool(clauses) != (position in focus_positions) or any(not clause["lines"] for clause in clauses):
            raise ValueError(f"과제 묶음과 초과·근접 조항이 맞지 않는 과제 결과: {_task_label(result)}")
    return summary


# ── 초과·근접 조항(중점 과제의 초과·근접 조항, 사양 줄마다 한 줄) ─────────────────────

def _focus_rows(result):
    head = (_row_number(result), result.get("title", ""))
    rows = []
    for clause in result["brief"]["focus"]:     # brief가 정한 조항 순서(R2-2) → 사양 줄 순서(R2-3) 그대로
        flags = _join(clause["flags"])          # 같은 조항의 줄마다 같은 값
        for line in clause["lines"]:
            rows.append(head + (clause["verdict"], clause["family_label"], clause["code"], clause["title"], line["verdict"],
                                line["target"], line["basis"], line["difference"], flags, line["reason"]))
    return rows


# ── 과제별 검토 결과(모든 과제 한 줄씩)와 실행 정보 줄 ───────────────────────────────

def _review_cell(entries):
    """추가 검토 필요 칸: 조항마다 '{고시 이름} {통제번호} {고시 조항명} — {남긴 이유}, {비교하지 못한 이유}'. 통제번호가 없으면 뺀다."""
    return REVIEW_SEPARATOR.join(
        REVIEW_LINE.format(brief.clause_name(entry),
                           entry["reason"])
        for entry in entries)


def _summary_row(result):
    data = result["brief"]
    families, counts = data["families"], data["counts"]
    return ((_row_number(result), result.get("title", ""), data["overall"], data["reason"])
            + tuple(families[family] for family in pipeline.FAMILY_ORDER)
            + (counts["over"], counts["near"], _review_cell(data["review"]), result.get("rnd_stage", ""),
               _fund_cell(result.get("gov_fund")), result.get("input_description", ""), result.get("status", ""),
               result.get("error_reason", ""), _join(data["hints"])))


def _excluded_text(item):
    """제외 행 한 줄의 글: '{N}행: {사유}'에 값이 있으면 ' — {값}'. 처리내역과 실행 정보 줄이 같은 글을 쓴다."""
    value = item.get("value", "")
    return f"{item.get('row_number', '?')}행: {item.get('reason', '')}" + (f" — {value}" if value else "")


def _run_info_rows(info, run_time, tally):
    """`과제별 검토 결과` 표 아래에 적는 실행 정보 줄(항목 이름, 값). 종합 결과는 brief.tally_text가 만든 한 줄이다."""
    excluded = list(info.get("excluded") or [])
    rows = [(RUN_TIME_LABEL, run_time),
            (RUN_VERSION_LABEL, _program_text()),
            (RUN_MODEL_LABEL, RUN_MODEL_TEXT.format(info.get("provider") or _NOT_GIVEN, info.get("model") or _NOT_GIVEN)),
            (RUN_TALLY_LABEL, brief.tally_text(tally)),
            (RUN_EXCLUDED_LABEL, RUN_EXCLUDED_COUNT.format(len(excluded)))]
    rows.extend((RUN_EXCLUDED_LABEL, _excluded_text(item)) for item in excluded)
    return rows


# ── 고시 조항별 상세 ───────────────────────────────────────────────────

def _detail_rows(result):
    judged = result.get("judge")
    if not judged:
        return []
    row_number, title = _row_number(result), result.get("title", "")
    comparisons_by_clause = {}
    for comp in judged.get("comparisons", []):
        comparisons_by_clause.setdefault(comp["clause_id"], []).append(comp)
    rows = []
    for clause in judged.get("clauses", []):
        common_tail = (clause.get("reason", ""), _join(clause.get("missing_subjects", [])), _join(clause.get("flags", [])),
                       _join(c.get("quote", "") for c in clause.get("checks", [])))
        head = (row_number, title, _family_label(clause.get("family", "")), clause.get("clause_id", ""), clause.get("code", ""),
                clause.get("title", ""))
        comps = comparisons_by_clause.get(clause["clause_id"], [])
        if not comps:
            # 매핑이 없는 관련 고시 조항: 비교 칸은 비우고 조항 검토 결과·사유만 채운다.
            branch_text = _join(clause.get("branch_texts", []))
            rows.append(head + (branch_text,) + ("",) * _COMPARISON_BLANKS + (clause.get("verdict", ""),) + common_tail + ("",))
            continue
        for comp in comps:
            rows.append(head + (
                comp.get("branch_label", ""), comp.get("subject", ""), OPERATOR_LABELS.get(comp.get("operator"), comp.get("operator", "")),
                comp.get("threshold_value", ""), comp.get("threshold_unit", ""),
                ORIGIN_LABELS.get(comp.get("origin"), comp.get("origin", "")), comp.get("threshold_quote", ""),
                comp.get("fact_subject", ""), comp.get("value_text", ""), comp.get("used_value", ""), comp.get("fact_unit", ""),
                comp.get("converted_value") or "", comp.get("fact_quote", ""), comp.get("source_field", ""),
                comp.get("gap_percent_display") or "", comp.get("verdict", ""), clause.get("verdict", ""))
                + common_tail + (comp.get("pair_reason", ""),))
    return rows


# ── 처리내역 ───────────────────────────────────────────────────────────

def _run_time(value):
    if value is None:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _program_text():
    return f"{pipeline.PROGRAM_NAME} {pipeline.PROGRAM_VERSION}"


def _log_rows(results, info, run_time):
    families = [str(f) for f in info.get("families") or []]
    excluded = list(info.get("excluded") or [])
    option_warnings = list(info.get("option_warnings") or [])
    warnings = list(info.get("file_warnings") or [])
    errors = [r for r in results if r.get("status") == pipeline.STATUS_ERROR]
    cancelled = sum(1 for r in results if r.get("status") == pipeline.STATUS_CANCELLED)
    rows = [
        ("실행 시각", run_time),
        ("프로그램 버전", _program_text()),
        ("기준본 이름", info.get("catalogue_id") or _NOT_GIVEN),
        ("기준본 지문", info.get("catalogue_fingerprint") or _NOT_GIVEN),
        ("고시 기준 사양 표 지문", info.get("table_fingerprint") or _NOT_GIVEN),
        ("AI 제공자", info.get("provider") or _NOT_GIVEN),
        ("AI 모델", info.get("model") or _NOT_GIVEN),
        ("근접 기준(%)", str(info["near_percent"]) if info.get("near_percent") is not None else _NOT_GIVEN),
        ("검토 대상 고시", _join(_family_label(f) for f in families) or _NOT_GIVEN),
        ("처리 과제 수", len(results)),
        ("제외 행 건수", len(excluded)),
        ("빈 행 건수(모든 칸이 빈 행)", int(info.get("blank_rows") or 0)),
    ]
    for item in excluded:
        rows.append(("제외 행", _excluded_text(item)))
    rows.append(("선택 칸 경고 건수", len(option_warnings)))
    for item in option_warnings:
        rows.append(("선택 칸 경고", item.get("message", "") if isinstance(item, dict) else str(item)))
    dropped_total = sum(len(r.get("dropped") or []) for r in results)
    rows.append(("버린 최종목표 사양·매핑 건수", dropped_total))
    for result in results:
        label = _task_label(result)
        for item in result.get("dropped") or []:
            rows.append(("버린 최종목표 사양·매핑",
                         f"{label}: [{item.get('stage', '')}] {item.get('kind', '')} {item.get('ids', '')}: {item.get('reason', '')}"))
    rows.append(("파일 읽기 경고 건수", len(warnings)))
    for warning in warnings:
        rows.append(("파일 읽기 경고", str(warning)))
    rows.append(("오류 건수", len(errors)))
    for result in errors:
        rows.append(("오류", f"{_task_label(result)}: {result.get('error_reason', '')}"))
    rows.append(("취소 건수", cancelled))
    calls = {key: 0 for key in pipeline.CALL_KEYS}
    for result in results:
        for key in pipeline.CALL_KEYS:
            calls[key] += int((result.get("calls") or {}).get(key, 0))
    rows.append(("AI 호출 수", calls["total"]))
    rows.append(("AI 호출 수(단계별)", f"{STAGE_LABELS[STAGE_EXTRACT]} {calls['extract']}; {STAGE_LABELS[STAGE_SCREEN]} "
                                     f"{calls['screen']}; {STAGE_LABELS[STAGE_PAIR]} {calls['pair']}"))
    rows.extend(_brief_log_rows(results, info))
    return rows


def _fingerprint(value):
    text = "" if value is None else str(value).strip()
    return text or FINGERPRINT_MISSING


def _semantic_log(briefs):
    """세부 기술 일치 확인: 쓸 수 없는 과제가 하나라도 있으면 그 수, 아니고 사용한 과제가 있으면 사용,
    모두 not_needed이면 확인할 조항 없음. 모르는 값은 ValueError(조용히 한쪽으로 세지 않는다)."""
    values = [data["semantic"] for data in briefs]
    unknown = [value for value in values if value not in _SEMANTIC_VALUES]
    if unknown:
        raise ValueError(f"간단한 결과의 semantic 값이 아니다: {unknown[0]!r}")
    unavailable = values.count(brief.SEMANTIC_UNAVAILABLE)
    if unavailable:
        return SEMANTIC_LOG_UNAVAILABLE.format(unavailable)
    if brief.SEMANTIC_USED in values:
        return SEMANTIC_LOG_USED
    return SEMANTIC_LOG_NOT_NEEDED


def _brief_log_rows(results, info):
    """처리내역의 간단한 결과 줄. 값은 과제 결과의 brief와 실행 정보에서만 가져온다.
    순위 기준은 brief.TOP_RANK를 부를 때 읽는다(상수를 바꾸면 따라 바뀐다)."""
    briefs = [_brief(result) for result in results]
    rows = [("세부 기술 일치 확인", _semantic_log(briefs)),
            ("세부 기술 일치 순위 기준", RANK_LOG.format(brief.TOP_RANK)),
            ("의미 검색 모델 지문", _fingerprint(info.get("semantic_model_fingerprint"))),
            ("의미 검색 조항 벡터 지문", _fingerprint(info.get("semantic_vectors_fingerprint")))]
    for label, keys in _COUNT_TOTALS:
        rows.append((label, sum(data["counts"][key] for data in briefs for key in keys)))
    for result, data in zip(results, briefs):
        hidden, dropped = data["counts"]["hidden"], data["counts"]["detail_match_dropped"]
        if hidden or dropped:
            rows.append(("간단한 결과에 넣지 않은 조항", HIDDEN_LOG.format(_task_label(result), hidden, dropped)))
    return rows


# ── 저장 ───────────────────────────────────────────────────────────────

def write_report(path, results, run_info=None):
    """결과 엑셀을 path에 저장한다. results는 TaskResult(또는 to_dict() 결과) 하나이거나 목록이다."""
    if hasattr(results, "to_dict") or isinstance(results, dict):
        results = [results]
    results = [_as_dict(r) for r in results]
    run = _run_summary(results)     # 저장 전에 확인한다(간단한 결과가 없거나 어긋난 결과는 받지 않음)
    info = dict(run_info or {})
    run_time = _run_time(info.get("run_time"))      # 실행 정보 줄과 처리내역이 같은 시각을 쓴다
    path = Path(path)

    book = Workbook()
    focus = book.active             # 첫 시트: 파일을 열면 이 시트가 보인다
    focus.title = SHEET_FOCUS
    _header(focus, FOCUS_COLUMNS, widths=(10, 30, 16, 18, 10, 30, 16, 18, 30, 26, 26, 70))
    focus_rows = [row for position in run["groups"][brief.GROUP_FOCUS] for row in _focus_rows(results[position])]
    for row in focus_rows or [(brief.EMPTY_MESSAGE,)]:      # 줄이 하나도 없으면 첫 칸에 한 줄
        _append(focus, row)

    summary = book.create_sheet(SHEET_SUMMARY)
    # 첫 칸은 실행 정보 줄의 항목 이름(검토에서 빠진 행)도 보이는 너비로 둔다.
    _header(summary, SUMMARY_COLUMNS, widths=(18, 40, 16, 40, 18, 18, 18, 18, 10, 10, 50, 12, 16, 22, 14, 40, 60))
    for result in results:
        _append(summary, _summary_row(result))
    summary.append([])              # 표 아래 빈 줄 하나 뒤에 실행 정보 줄(머리줄 없이 항목 이름·값)
    for row in _run_info_rows(info, run_time, run["tally"]):
        _append(summary, row)

    detail = book.create_sheet(SHEET_DETAIL)
    _header(detail, DETAIL_COLUMNS, widths=(10, 30, 18, 24, 10, 30, 20, 16, 8, 12, 12, 16, 40, 16, 16, 12, 12, 16, 30, 18, 8,
                                            16, 20, 24, 20, 30, 40, 40))
    for result in results:
        for row in _detail_rows(result):
            _append(detail, row)

    log = book.create_sheet(SHEET_LOG)
    _header(log, LOG_COLUMNS, widths=(50, 100))     # 항목 칸: 긴 항목 이름(…남기지 않은 조항 수 합계)이 보이게
    for row in _log_rows(results, info, run_time):
        _append(log, row)
    log.sheet_state = "hidden"      # 보통 숨김: 엑셀의 '시트 숨기기 취소'로 볼 수 있다(veryHidden이 아니다)

    book.active = 0                 # 파일을 열면 첫 시트(초과·근접 조항)
    focus.sheet_view.tabSelected = True
    book.save(path)
    return path
