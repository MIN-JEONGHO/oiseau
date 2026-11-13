"""연구개발과제 일괄 검토(spec 2.3): 입력 양식 만들기, 입력 엑셀 읽기(제외 규칙·선택 칸 정리), 시작 전 미리보기, 동시 실행·취소.

입력 엑셀은 첫 시트 1행 머리글 `연구개발과제명`·`최종목표`·`연구개발내용`·`활용계획 및 기대효과`(필수)와
`연구개발단계`·`정부지원연구개발비(백만원)`(선택)이다. 머리글 이름으로 열을 찾으므로 순서는 상관없고, 머리글의
앞뒤 공백과 글자 사이 공백 차이는 무시한다. 첨부파일 열은 없다.
- 필수 머리글이 없으면 없는 이름을 알리고 멈춘다(BatchInputError). 선택 머리글이 없으면 그 값은 모두 빈칸이고
  `선택 머리글 없음: 이름(값 모두 빈칸)` 경고를 남긴다.
- 제외한 행은 건수와 행 번호·사유·값을 함께 돌려주며 조용히 빼지 않는다. 여섯 칸이 모두 빈 행은 제외 목록이
  아니라 빈 행 건수로만 센다.
- 선택 칸의 잘못된 값은 행을 제외하지 않고 빈칸으로 두며 행 번호·원래 값을 담은 경고를 남긴다
  (pipeline.normalize_rnd_stage·normalize_gov_fund — 개별 검토와 같은 규칙).
실행은 행마다 독립 클라이언트(client_factory())로 pipeline.run_task를 돌리고, 행 오류는 그 행만 '오류'로 두고
계속한다. 취소되면 끝난 행 결과를 보존하고 시작하지 않은 행은 '취소' 상태로 둔다. 이어하기는 없다.
결과는 입력 순서다. 저장 위치는 호출자가 준다.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import threading

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

import pipeline
from ai_stages import estimate_calls

HEADER_TITLE = pipeline.FIELD_TITLE
HEADER_FINAL_GOAL = pipeline.FIELD_FINAL_GOAL
HEADER_CONTENT = pipeline.FIELD_CONTENT
HEADER_UTILIZATION = pipeline.FIELD_UTILIZATION
HEADER_STAGE = pipeline.FIELD_STAGE
HEADER_FUND = pipeline.FIELD_FUND
HEADERS = (HEADER_TITLE, HEADER_FINAL_GOAL, HEADER_CONTENT, HEADER_UTILIZATION, HEADER_STAGE, HEADER_FUND)
REQUIRED_HEADERS = HEADERS[:4]
OPTIONAL_HEADERS = HEADERS[4:]
# 머리글 → 행 키
HEADER_KEYS = {HEADER_TITLE: "title", HEADER_FINAL_GOAL: "final_goal", HEADER_CONTENT: "rnd_content",
               HEADER_UTILIZATION: "utilization", HEADER_STAGE: "rnd_stage", HEADER_FUND: "gov_fund"}
TEMPLATE_SHEET = "연구개발과제 일괄 검토 입력"

# 양식의 예시 행. 연구개발과제명이 이 머리말로 시작하면 예시 행으로 보고 제외한다.
EXAMPLE_TITLE_PREFIX = "(예시)"
EXAMPLE_ROW = ("(예시) 고출력 레이저 가공 장비 개발",
               "(예시) 이 행은 양식 보기이며 처리하지 않습니다. 최종 목표 수치를 적으세요. 예: 출력 5 kW 이상, 빔 품질 M² 1.3 이하.",
               "(예시) 광원·광학계 설계, 시제품 제작과 성능 시험",
               "(예시) 정밀 가공 장비 업체에 기술 이전",
               "응용연구", 1500)

REASON_EMPTY_REQUIRED = "필수 칸 빈칸"
REASON_EXAMPLE = "양식의 예시 행"
REASON_DUPLICATE = "중복 행"
WARNING_DUPLICATED_HEADER = "같은 머리글이 여러 번"
WARNING_MISSING_OPTIONAL = "선택 머리글 없음"

DEFAULT_WORKERS = 3
PROGRESS_STAGE = "batch"
_SPACES = re.compile(r"\s+")

__all__ = ["HEADERS", "REQUIRED_HEADERS", "OPTIONAL_HEADERS", "TEMPLATE_SHEET", "EXAMPLE_TITLE_PREFIX",
           "REASON_EMPTY_REQUIRED", "REASON_EXAMPLE", "REASON_DUPLICATE", "WARNING_MISSING_OPTIONAL", "DEFAULT_WORKERS",
           "BatchInputError", "make_template", "read_batch_input", "batch_preview", "run_batch", "count_status"]


class BatchInputError(ValueError):
    """입력 엑셀이 없거나 열 수 없거나 필수 머리글이 없다."""


# ── 양식 ───────────────────────────────────────────────────────────────

def make_template(path):
    """입력 양식 엑셀을 만든다: 시트 `연구개발과제 일괄 검토 입력`, 머리글 한 줄과 예시 행 하나."""
    path = Path(path)
    book = Workbook()
    sheet = book.active
    sheet.title = TEMPLATE_SHEET
    sheet.append(list(HEADERS))
    sheet.append(list(EXAMPLE_ROW))
    for letter, width in zip("ABCDEF", (40, 60, 60, 60, 14, 26)):
        sheet.column_dimensions[letter].width = width
    book.save(path)
    return path


# ── 읽기 ───────────────────────────────────────────────────────────────

def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _header_key(value):
    """머리글 비교용 글: 앞뒤·글자 사이 공백을 모두 뺀다."""
    return _SPACES.sub("", _cell_text(value))


def _is_example(title):
    return title.startswith(EXAMPLE_TITLE_PREFIX)


def read_batch_input(path):
    """입력 엑셀을 읽어 처리할 행과 제외한 행, 선택 칸 경고를 돌려준다.

    돌려주는 것: {"rows": [{row_number, title, final_goal, rnd_content, utilization, rnd_stage, gov_fund}],
    "excluded": [{row_number, reason, value}], "option_warnings": [{row_number, field, value, message}],
    "blank_rows": 여섯 칸이 모두 빈 행 수, "total_rows": 머리글을 뺀 전체 행 수}.
    제외 규칙: 필수 네 칸 중 빈 칸이 있는 행(사유에 빈 칸 이름), 양식의 예시 행, 필수 네 칸이 모두 같은 중복 행
    (첫 행만 처리). 선택 칸은 처리할 행에서만 정리한다. 필수 머리글이 없으면 BatchInputError.
    """
    path = Path(path)
    if not path.is_file():
        raise BatchInputError(f"입력 파일이 없다: {path.name}")
    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, ValueError) as error:
        raise BatchInputError(f"입력 파일을 열 수 없다: {path.name} ({type(error).__name__})") from error
    try:
        sheet = book.worksheets[0]
        iterator = sheet.iter_rows(values_only=True)
        header = next(iterator, None) or ()
        wanted = {_header_key(name): name for name in HEADERS}
        positions, duplicated = {}, []
        for index, value in enumerate(header):
            name = wanted.get(_header_key(value))
            if name is None:
                continue
            if name in positions:
                if name not in duplicated:
                    duplicated.append(name)
                continue
            positions[name] = index
        missing = [name for name in REQUIRED_HEADERS if name not in positions]
        if missing:
            raise BatchInputError("입력 파일 1행에 필수 머리글이 없다: " + ", ".join(missing))
        option_warnings = [dict(row_number=None, field=name, value="",
                                message=f"{WARNING_MISSING_OPTIONAL}: {name}(값 모두 빈칸)")
                           for name in OPTIONAL_HEADERS if name not in positions]
        option_warnings += [dict(row_number=None, field=name, value="",
                                 message=f"{WARNING_DUPLICATED_HEADER}: {name}(첫 열만 읽음)")
                            for name in duplicated]

        def pick(cells, name):
            index = positions.get(name)
            return cells[index] if index is not None and index < len(cells) else None

        rows, excluded, seen = [], [], {}
        blank_rows = total_rows = 0
        for row_number, cells in enumerate(iterator, start=2):
            cells = tuple(cells)
            raw = {name: pick(cells, name) for name in HEADERS}
            if all(_cell_text(value) == "" for value in raw.values()):
                blank_rows += 1
                continue
            total_rows += 1
            texts = {name: _cell_text(raw[name]) for name in REQUIRED_HEADERS}
            title = texts[HEADER_TITLE]
            value = title or next((texts[name] for name in REQUIRED_HEADERS if texts[name]), "")[:50]
            if _is_example(title):
                excluded.append(dict(row_number=row_number, reason=REASON_EXAMPLE, value=value))
                continue
            empty = [name for name in REQUIRED_HEADERS if not texts[name]]
            if empty:
                excluded.append(dict(row_number=row_number, reason=f"{REASON_EMPTY_REQUIRED}: " + ", ".join(empty),
                                     value=value))
                continue
            key = tuple(texts[name] for name in REQUIRED_HEADERS)
            if key in seen:
                excluded.append(dict(row_number=row_number,
                                     reason=f"{REASON_DUPLICATE}({seen[key]}행과 필수 네 칸이 같음)", value=value))
                continue
            seen[key] = row_number
            rnd_stage, stage_warning = pipeline.normalize_rnd_stage(raw[HEADER_STAGE], row_number)
            gov_fund, fund_warning = pipeline.normalize_gov_fund(raw[HEADER_FUND], row_number)
            option_warnings.extend(w for w in (stage_warning, fund_warning) if w)
            row = {HEADER_KEYS[name]: texts[name] for name in REQUIRED_HEADERS}
            rows.append(dict(row_number=row_number, **row, rnd_stage=rnd_stage, gov_fund=gov_fund))
        # 빈 행은 자료가 아니므로 제외 목록에 넣지 않되, 건수는 따로 드러낸다.
        return dict(rows=rows, excluded=excluded, option_warnings=option_warnings, blank_rows=blank_rows,
                    total_rows=total_rows + blank_rows)
    finally:
        book.close()


# ── 미리보기 ───────────────────────────────────────────────────────────

def batch_preview(rows, families, table):
    """시작 전 확인용: 처리할 건수, 검토 대상 고시, 건당·합계 예상 AI 호출 수(최소, 최대)."""
    families = [str(f) for f in dict.fromkeys(families)]
    low, high = estimate_calls(families, table)
    count = len(rows)
    return dict(count=count, families=families, calls_per_task=(low, high), calls_total=(low * count, high * count))


# ── 실행 ───────────────────────────────────────────────────────────────

def _row_task(row):
    """읽은 행 → 과제 입력. 일괄 검토에는 첨부·발췌가 없다."""
    return dict(title=row.get("title", ""), final_goal=row.get("final_goal", ""), rnd_content=row.get("rnd_content", ""),
                utilization=row.get("utilization", ""), excerpt="", rnd_stage=row.get("rnd_stage", ""),
                gov_fund=row.get("gov_fund", ""), row_number=row.get("row_number"))


def _warnings_by_row(option_warnings):
    """선택 칸 경고 → {행 번호: [경고]}. 행 번호가 없는 경고(머리글 경고)는 실행 전체의 것이라 행에 나누지 않는다."""
    by_row = {}
    for warning in option_warnings or ():
        number = warning.get("row_number") if isinstance(warning, dict) else None
        if type(number) is int:
            by_row.setdefault(number, []).append(warning)
    return by_row


def run_batch(rows, families, client_factory, table, catalogue_index, *, workers=DEFAULT_WORKERS, progress=None,
              cancel_event=None, search_engine=None, option_warnings=()):
    """행들을 동시 처리(workers)한다. 결과는 입력 순서의 TaskResult 목록.

    행마다 client_factory()로 독립 클라이언트를 만든다. 행 오류(클라이언트 생성 실패·입력 어긋남·예외)는 그 행만
    '오류'로 두고 계속한다. cancel_event가 설정되면 아직 시작하지 않은 행은 '취소' 상태가 된다.
    progress(event)는 행이 끝날 때마다 {stage:"batch", message, completed, total, row_number, status}를 받는다
    (과제별 단계 진행은 보내지 않는다).
    search_engine: 모든 행이 함께 쓰는 PC 안 검색 엔진(선택, pipeline.run_task에 그대로 넘긴다). 동시 처리에서도
        행마다 계산이 따로이므로 결과는 처리 순서와 무관하다.
    option_warnings: read_batch_input의 option_warnings. 행 번호가 있는 경고만 그 행 과제의 건수 안내에 쓴다.
    """
    if type(workers) is not int or workers < 1:
        raise ValueError("동시 처리 수는 1 이상 정수여야 한다")
    rows = list(rows)
    families = [str(f) for f in dict.fromkeys(families)]
    warnings_by_row = _warnings_by_row(option_warnings)
    total = len(rows)
    lock = threading.Lock()
    done = 0

    def report(result):
        nonlocal done
        with lock:
            done += 1
            completed = done
        if progress is not None:
            progress(dict(stage=PROGRESS_STAGE, message=f"{completed}/{total}건 처리", completed=completed, total=total,
                          row_number=result.row_number, status=result.status))

    def work(row):
        task = _row_task(row)
        row_warnings = list(warnings_by_row.get(row.get("row_number"), ()))
        if cancel_event is not None and cancel_event.is_set():
            result = pipeline.cancelled_result(task, families, option_warnings=row_warnings)
        else:
            try:
                client = client_factory()
                result = pipeline.run_task(task, families, client, table, catalogue_index, search_engine=search_engine,
                                           option_warnings=row_warnings)
            except Exception as error:  # noqa: BLE001 — 행 하나의 실패는 그 행의 '오류'로 남긴다
                reason = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
                result = pipeline.error_result(task, families, reason, option_warnings=row_warnings)
        report(result)
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, rows))
    return results


def count_status(results, status):
    return sum(1 for result in results if result.status == status)
