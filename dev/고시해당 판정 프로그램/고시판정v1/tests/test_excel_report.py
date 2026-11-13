"""결과 엑셀(excel_report) 시험. 1.4.0 spec 4절(R3의 엑셀 쪽)·7절(R6)·8절 R7-1·10절.

보이는 시트 셋(`초과·근접 조항`·`과제별 검토 결과`·`고시 조항별 상세`)과 숨김 `처리내역`의 이름·순서·보임, 두 앞 시트의
열 이름·순서와 값(과제 결과의 brief 그대로), 사양 줄 수·순서, 빈 경우 한 줄, 실행 정보 줄, 처리내역이 `참고`만 빠지고
그대로인지, 공통 안내 세 줄이 파일 어디에도 없는지, 글 셀·긴 셀·숫자 셀 규칙을 확인한다.

결과는 합성 과제·합성 표·모의 AI·가짜 검색 엔진으로 만든 것이며 실제 과제가 아니다. 엑셀은 임시 폴더에만 만든다.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from openpyxl import load_workbook

import brief
import excel_report
import judge_engine as je
import pipeline
from ai_stages import SOURCE_FINAL_GOAL, SOURCE_UTILIZATION
from threshold_table import BODY_SOURCE, STATUS_HAS
from tests import test_pipeline as tp
from tests.mock_model import MockModel
from tests.test_pipeline import ALL_FAMILIES, FACTS, INDEX, SUMMARY_TASK, TABLE, TASK

SHEET_FOCUS, SHEET_SUMMARY, SHEET_DETAIL, SHEET_LOG = "초과·근접 조항", "과제별 검토 결과", "고시 조항별 상세", "처리내역"
SHEETS = [SHEET_FOCUS, SHEET_SUMMARY, SHEET_DETAIL, SHEET_LOG]
GONE_SHEETS = ["검토 결과 요약", "해당 고시 조항"]      # 1.3.x의 앞 두 시트(내용은 새 앞 두 시트로 합쳐졌다)
FOCUS_COLUMNS = ["입력 행 번호", "연구개발과제명", "판정", "검토 대상 고시", "통제번호", "고시 조항명", "사양 비교 결과", "최종목표 사양",
                 "고시 기준 사양", "차이", "확인 표시", "사유"]
SUMMARY_COLUMNS = ["입력 행 번호", "연구개발과제명", "판정", "사유", "국가첨단전략기술", "국가핵심기술", "전략물자(이중용도)",
                   "전략물자(군용)", "초과 조항 수", "근접 조항 수", "추가 검토 필요", "연구개발단계", "정부지원연구개발비(백만원)",
                   "입력 정보", "상태", "오류 사유", "안내"]
GONE_SUMMARY_COLUMNS = ["미달 조항 수", "수치 비교 불가 조항 수", "수치 기준 없음 조항 수", "확인 표시 조항 수", "참고"]
DETAIL_COLUMNS = ["입력 행 번호", "연구개발과제명", "검토 대상 고시", "조항 ID", "통제번호", "고시 조항명", "갈래 설명", "고시 기준 물리량",
                  "비교어", "고시 기준 사양", "고시 기준 단위", "고시 기준 출처", "고시 기준 원문 인용", "최종목표 물리량",
                  "최종목표 사양(원문)", "사용한 값", "최종목표 단위", "환산한 최종목표 사양", "최종목표 인용", "최종목표 위치", "차이 %",
                  "사양 비교 결과", "조항 검토 결과", "비교 불가 사유", "빠진 고시 기준", "확인 표시", "추가 확인 조건 원문", "매핑 근거"]
# 결과에서 뺀 공통 안내 세 줄(spec R3). 셋째 줄은 화면 맨 아래 한 줄의 글로만 남는다(excel_report.NOTE_TEXT).
NOTICES = ["고시 기준값 대부분은 AI가 고시 원문에서 읽은 값으로, 원문 확인이 필요함.",
           "용도·양산 목적·예외 같은 숫자 외 조건은 판정에 넣지 않았으므로 원문으로 확인이 필요함.",
           "이 결과는 고시 수치 기준과의 참고 대조이며 고시 해당 여부의 공식 판정이 아님."]
EMPTY = "고시 사양을 초과하거나 근접한 조항 없음"
OVER, NEAR, UNDER, EXCLUDED = "고시 사양 초과", "고시 사양 근접", "고시 사양 미달", "대조 안 함(선택 제외)"
# 실행 정보 줄(`과제별 검토 결과` 표 아래, spec R6-3)의 항목 이름과 순서.
RUN_LABELS = ["실행 일시", "프로그램 버전", "AI 모델", "종합 결과", "검토에서 빠진 행"]
# 처리내역(spec R6-4): 1.3.x의 줄 그대로에서 마지막 `참고`만 뺀다.
LOG_HEAD_LABELS = ["실행 시각", "프로그램 버전", "기준본 이름", "기준본 지문", "고시 기준 사양 표 지문", "AI 제공자", "AI 모델",
                   "근접 기준(%)", "검토 대상 고시", "처리 과제 수", "제외 행 건수", "빈 행 건수(모든 칸이 빈 행)"]
BRIEF_LOG_LABELS = ["세부 기술 일치 확인", "세부 기술 일치 순위 기준", "의미 검색 모델 지문", "의미 검색 조항 벡터 지문",
                    "해당 조항 수 합계", "추가 검토 필요 수 합계", "간단한 결과에 넣지 않은 관련 조항 수 합계",
                    "세부 기술 일치로 답했지만 남기지 않은 조항 수 합계"]
HIDDEN_LINE = "간단한 결과에 넣지 않은 조항"
NOT_LOADED = "불러오지 못함"
OPTION_WARNINGS = [dict(row_number=None, field="연구개발단계", value="", message="선택 머리글 없음: 연구개발단계(값 모두 빈칸)"),
                   dict(row_number=4, field="정부지원연구개발비", value="약 3억", message="4행: 정부지원연구개발비 값 확인 필요 — 약 3억"),
                   dict(row_number=5, field="연구개발단계", value="상용화", message="5행: 연구개발단계 값 확인 필요 — 상용화")]
EXCLUDED_ROWS = [dict(row_number=10, reason="필수 칸 빈칸: 연구개발과제명", value=""),
                 dict(row_number=11, reason="같은 연구개발과제명", value="합성 겹친 과제")]
EXCLUDED_LINES = ["10행: 필수 칸 빈칸: 연구개발과제명", "11행: 같은 연구개발과제명 — 합성 겹친 과제"]
SEMANTIC_INFO = dict(semantic_model_fingerprint="m" * 64, semantic_vectors_fingerprint="v" * 64)
RUN_INFO = dict(run_time="2026-11-05 10:00:00", catalogue_id="synthetic", catalogue_fingerprint="0" * 64,
                table_fingerprint="1" * 64, provider="claude", model="합성-모델", near_percent="10", families=ALL_FAMILIES,
                excluded=EXCLUDED_ROWS, blank_rows=2, option_warnings=OPTION_WARNINGS, file_warnings=["쪽 7: 글자 깨짐 2건"],
                **SEMANTIC_INFO)
PROGRAM_LINE = f"{pipeline.PROGRAM_NAME} {pipeline.PROGRAM_VERSION}"


# ── 합성 표: 과제 흐름 시험의 표에 기준 둘·갈래 둘·정성 통제 조항을 더한다 ──────────────────

def multi_record(clause_id, family, title, branches, checks=()):
    """갈래마다 기준 목록 [(물리량, 비교어, 값, 단위), ...]을 받는 합성 표 기록."""
    short = clause_id.replace(":", "_")
    made = []
    for b, thresholds in enumerate(branches, start=1):
        made.append(dict(branch_id=f"{short}:b{b}", label="가나다"[b - 1], text="", thresholds=[
            dict(threshold_id=f"{short}:b{b}t{t}", subject=subject, operator=operator, value=value, unit=unit,
                 quote=f"{subject} {value} {unit}", quote_source=BODY_SOURCE, origin="structured")
            for t, (subject, operator, value, unit) in enumerate(thresholds, start=1)]))
    return dict(clause_id=clause_id, family=family, numeric_status=STATUS_HAS, title=title, branches=made, rejected=[],
                checks=[dict(quote=q, source=BODY_SOURCE) for q in checks])


RECORDS = tp.RECORDS + [
    # 한 갈래에 기준 둘(빔 길이 100nm 이상 그리고 펄스 에너지 10J 이상).
    multi_record("core:item:002", "core", "합성 레이저 가공기", [[("빔 길이", "ge", "100", "nm"), ("펄스 에너지", "ge", "10", "J")]]),
    tp.text_record("dual_use:control:1A005", "dual_use", "합성 정성 통제 항목"),
    # 갈래 둘(평균 출력 300W 이상 또는 저장 에너지 500J 이상)과 추가 확인 조건.
    multi_record("military:item:002", "military", "합성 전원 장치", [[("평균 출력", "ge", "300", "W")], [("저장 에너지", "ge", "500", "J")]],
                 checks=["수출용에 한함"]),
]
BIG_TABLE = tp.make_table(RECORDS)
BIG_INDEX = [dict(clause_id=r["clause_id"], family=r["family"],
                  code=r["clause_id"].split(":")[-1] if r["family"] == "dual_use" else "", title=r["title"], field="합성 분야")
             for r in RECORDS]

CANDIDATES = {"advanced:item:001", "advanced:item:002", "dual_use:control:1A003", "military:item:001"}
DETAIL = {"military:item:001", "core:item:001"}
# 군용 채택 실패 조항은 같은 고시 안 1위, 국가핵심기술 정성 조항은 6위(상위 5위 밖).
RANKING = dict(military=["military:item:001"], core=[f"core:other:{i}" for i in range(5)] + ["core:item:001"])
BAD_FACT = dict(FACTS[0], fact_id="bad", quote="99 zz")   # 인용이 글에 없어 버려지는 최종목표 사양

UNDER_GOAL = "D램 공정노드 20 nm 달성을 최종 목표로 한다."
NEAR_GOAL = "빔 길이 120 nm와 펄스 에너지 9.5 J 달성을 최종 목표로 한다."
BOTH_GOAL = "평균 출력 330 W와 저장 에너지 550 J 달성을 최종 목표로 한다."
REACTOR_USE = "원자로 출력 14250 kW 실증에 활용한다."


class RankEngine:
    """가짜 PC 안 검색 엔진(semantic_ranking과 같은 모양). 고시별 순위를 정해 둔다. 받은 글은 기록하지 않는다."""

    def __init__(self, ranking=None, *, available=True):
        self.ranking, self.available = ranking or {}, available

    def semantic_ranking(self, text):
        if not self.available:
            return dict(available=False, reason="합성 사유", ranking=None)
        return dict(available=True, reason="", ranking={f: list(self.ranking.get(f, [])) for f in pipeline.FAMILY_ORDER})


def warning(row_number, message):
    return dict(row_number=row_number, field="연구개발단계", value="상용화", message=message)


def no_branch_choice(stage, payload, out):
    """모의 AI가 갈래를 고르지 않게 한다(갈래 둘이 모두 판정을 정하는 경우를 만들려고)."""
    if stage == "pair":
        out["branch_choices"] = []
    return out


def run(task, model, **kwargs):
    return pipeline.run_task(task, ALL_FAMILIES, model, BIG_TABLE, BIG_INDEX, **kwargs)


def under_result(**changes):
    """종합 미달 + 추가 검토 필요 1건(이중용도) + 의미 검색을 쓸 수 없음."""
    task = dict(SUMMARY_TASK, title="미달 과제", final_goal=UNDER_GOAL, row_number=2, rnd_stage="기초연구")
    task.update(changes)
    facts = [tp.fact("u1", UNDER_GOAL, SOURCE_FINAL_GOAL, "20 nm", "D램 공정노드", "20", "20", "nm")]
    model = MockModel(facts=facts, candidates={"advanced:item:001", "core:item:001", "dual_use:control:1A004"},
                      detail_matches={"core:item:001"})
    return run(task, model, option_warnings=[warning(2, "2행: 연구개발단계 값 확인 필요")])


def near_result(**changes):
    """종합 근접: 기준 둘인 조항에서 한 사양은 충족, 한 사양은 근접(spec 10절)."""
    task = dict(SUMMARY_TASK, title="근접 과제", final_goal=NEAR_GOAL, row_number=3)
    task.update(changes)
    facts = [tp.fact("n1", NEAR_GOAL, SOURCE_FINAL_GOAL, "120 nm", "빔 길이", "120", "120", "nm"),
             tp.fact("n2", NEAR_GOAL, SOURCE_FINAL_GOAL, "9.5 J", "펄스 에너지", "9.5", "9.5", "J")]
    return run(task, MockModel(facts=facts, candidates={"core:item:002"}))


def over_result(**changes):
    """종합 초과: 초과 조항 둘 + 근접 조항 하나 + 추가 검토 필요 둘 + 감춘 조항."""
    task = dict(TASK, title="초과 과제 가", utilization=REACTOR_USE, row_number=4)
    task.update(changes)
    facts = FACTS + [tp.fact("f3", REACTOR_USE, SOURCE_UTILIZATION, "14250 kW", "출력", "14250", "14250", "kW")]
    candidates = {"advanced:item:001", "advanced:item:002", "core:item:001", "dual_use:control:1A003", "dual_use:control:1A004",
                  "dual_use:control:1A005", "military:item:001"}
    return run(task, MockModel(facts=facts, candidates=candidates, detail_matches=DETAIL), search_engine=RankEngine(RANKING))


def both_branches_result(**changes):
    """종합 초과: 판정을 정한 갈래가 둘(spec 10절) — 갈래 순서대로 사양 줄 둘."""
    task = dict(SUMMARY_TASK, title="초과 과제 나", final_goal=BOTH_GOAL, row_number=7, gov_fund="300")
    task.update(changes)
    facts = [tp.fact("b1", BOTH_GOAL, SOURCE_FINAL_GOAL, "330 W", "평균 출력", "330", "330", "W"),
             tp.fact("b2", BOTH_GOAL, SOURCE_FINAL_GOAL, "550 J", "저장 에너지", "550", "550", "J")]
    return run(task, MockModel(facts=facts, candidates={"military:item:002"}, transform=no_branch_choice))


def error_result():
    return run(dict(SUMMARY_TASK, title="오류 과제", row_number=6), MockModel(facts=FACTS, faults={"extract": ["shape", "shape"]}))


def mixed_results():
    """일괄 한 번: 미달·근접·초과·목표 수치 없음·오류·초과·관련 고시 항목 없음·취소(입력 순)."""
    return [
        under_result(),
        near_result(),
        over_result(),
        run(dict(SUMMARY_TASK, title="수치 없는 과제", row_number=5), MockModel(facts=[BAD_FACT]),
            option_warnings=[warning(5, "5행: 연구개발단계 값 확인 필요")]),
        error_result(),
        both_branches_result(),
        run(dict(TASK, title="관련 없는 과제", row_number=8), MockModel(facts=FACTS, candidates=set())),
        pipeline.cancelled_result(dict(SUMMARY_TASK, title="취소 과제", row_number=9, gov_fund="77"), ALL_FAMILIES),
    ]


def rows_of(sheet):
    return [[c.value for c in row] for row in sheet.iter_rows()]


def log_items_of(rows):
    items = {}
    for key, value in rows[1:]:
        items.setdefault(key, []).append(value)
    return items


def write_and_read(results, run_info=None):
    """결과 엑셀을 임시 폴더에 만들어 시트마다 값·셀 형식·보임 상태를 읽고, 파일 안의 글 전체도 함께 돌려준다."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "결과.xlsx"
        excel_report.write_report(path, results, run_info)
        with zipfile.ZipFile(path) as archive:
            raw = "\n".join(archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist())
        book = load_workbook(path)
        try:
            names = list(book.sheetnames)
            sheets = {name: rows_of(book[name]) for name in names}
            types = {name: [[c.data_type for c in row] for row in book[name].iter_rows()] for name in names}
            wraps = {name: [[bool(c.alignment.wrap_text) for c in row] for row in book[name].iter_rows()] for name in names}
            states = {name: book[name].sheet_state for name in names}
            heights = {name: [book[name].row_dimensions[number].height for number in range(1, book[name].max_row + 1)]
                       for name in names}
            selected = [name for name in names if book[name].sheet_view.tabSelected]
            active, active_tab = book.active.title, book.views[0].activeTab
        finally:
            book.close()
    return dict(names=names, sheets=sheets, types=types, wraps=wraps, states=states, heights=heights, selected=selected, active=active,
                active_tab=active_tab, raw=raw, log=log_items_of(sheets[SHEET_LOG]))


def all_cells(out):
    return [value for rows in out["sheets"].values() for row in rows for value in row if value is not None]


def run_lines(out, task_count):
    """`과제별 검토 결과` 표 아래의 줄들(빈 줄 포함)."""
    return out["sheets"][SHEET_SUMMARY][1 + task_count:]


def shown(value):
    """엑셀에서 읽은 값: 빈 글은 빈칸(None)으로 남는다."""
    return None if value in ("", None) else value


def expected_focus_rows(result):
    """한 과제의 `초과·근접 조항` 줄: brief의 초과·근접 조항 순서 → 사양 줄 순서 그대로."""
    data = result.to_dict() if hasattr(result, "to_dict") else result
    rows = []
    for clause in data["brief"]["focus"]:
        for line in clause["lines"]:
            rows.append([data["row_number"], data["title"], clause["verdict"], clause["family_label"], shown(clause["code"]),
                         clause["title"], line["verdict"], line["target"], line["basis"], line["difference"],
                         shown("; ".join(clause["flags"])), line["reason"]])
    return rows


# ── 시트 구성(R6-1) ─────────────────────────────────────────────────────

class WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = mixed_results()
        cls.out = write_and_read(cls.results, RUN_INFO)

    def test_scenarios_are_what_the_test_needs(self):
        self.assertEqual([r.status for r in self.results],
                         ["완료", "완료", "완료", "목표 수치 없음", "오류", "완료", "관련 고시 항목 없음", "취소"])
        self.assertEqual([r.brief["overall"] for r in self.results], [UNDER, NEAR, OVER, UNDER, "오류", OVER, UNDER, "취소"])
        self.assertEqual([r.brief["group"] for r in self.results],
                         ["other", "focus", "focus", "other", "unjudged", "focus", "other", "unjudged"])
        self.assertEqual([r.brief["semantic"] for r in self.results],
                         ["unavailable", "not_needed", "used", "not_needed", "not_needed", "not_needed", "not_needed", "not_needed"])
        self.assertEqual([len(r.brief["review"]) for r in self.results], [1, 0, 2, 0, 0, 0, 0, 0])

    def test_sheet_names_and_order(self):
        self.assertEqual(self.out["names"], SHEETS)
        self.assertEqual((excel_report.SHEET_FOCUS, excel_report.SHEET_SUMMARY, excel_report.SHEET_DETAIL, excel_report.SHEET_LOG),
                         tuple(SHEETS))
        for gone in GONE_SHEETS:
            self.assertNotIn(gone, self.out["names"])
            self.assertNotIn(gone, self.out["raw"])

    def test_only_log_sheet_is_hidden_and_first_sheet_opens(self):
        # 처리내역은 엑셀의 '시트 숨기기 취소'로 볼 수 있는 보통 숨김이다(veryHidden이 아니다).
        self.assertEqual(self.out["states"], {SHEET_FOCUS: "visible", SHEET_SUMMARY: "visible", SHEET_DETAIL: "visible",
                                              SHEET_LOG: "hidden"})
        self.assertEqual(self.out["active"], SHEET_FOCUS)
        self.assertEqual(self.out["active_tab"], 0)
        self.assertEqual(self.out["selected"], [SHEET_FOCUS])

    def test_column_constants(self):
        self.assertEqual(list(excel_report.FOCUS_COLUMNS), FOCUS_COLUMNS)
        self.assertEqual(list(excel_report.SUMMARY_COLUMNS), SUMMARY_COLUMNS)
        self.assertEqual(list(excel_report.DETAIL_COLUMNS), DETAIL_COLUMNS)
        self.assertEqual((len(FOCUS_COLUMNS), len(SUMMARY_COLUMNS)), (12, 17))
        self.assertEqual(list(excel_report.RUN_INFO_LABELS), RUN_LABELS)

    def test_common_notices_are_nowhere_in_the_file(self):
        cells = [str(value) for value in all_cells(self.out)]
        for notice in NOTICES:
            self.assertFalse(any(notice in cell for cell in cells), notice)
            self.assertNotIn(notice, self.out["raw"], notice)
        # `참고` 열·`참고` 줄도 없다.
        for name in SHEETS:
            self.assertNotIn("참고", self.out["sheets"][name][0], name)
        self.assertNotIn("참고", self.out["log"])
        self.assertNotIn("참고", [row[0] for row in self.out["sheets"][SHEET_SUMMARY]])
        # 화면 맨 아래 한 줄의 글은 같은 이름·같은 글의 상수로 남는다(연결 함수가 쓴다).
        self.assertEqual(excel_report.NOTE_TEXT, NOTICES[2])

    def test_old_verdict_names_are_not_in_front_sheets(self):
        for name in (SHEET_FOCUS, SHEET_SUMMARY):
            cells = [str(v) for row in self.out["sheets"][name] for v in row if v is not None]
            self.assertFalse(any("사양 미달 또는 무관" in cell for cell in cells), name)
        # `최종목표 수치 없음`은 판정 칸이 아니라 과제 사유 글로만 나온다.
        table = self.out["sheets"][SHEET_SUMMARY][1:1 + len(self.results)]
        for row in table:
            line = dict(zip(SUMMARY_COLUMNS, row))
            for column in ("판정", "국가첨단전략기술", "국가핵심기술", "전략물자(이중용도)", "전략물자(군용)"):
                self.assertIn(line[column], (OVER, NEAR, UNDER, "오류", "취소", EXCLUDED), column)

    def test_no_key_like_text(self):
        for value in all_cells(self.out):
            self.assertNotIn("sk-", str(value))


# ── 초과·근접 조항(R6-2) ────────────────────────────────────────────────

class FocusSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = mixed_results()
        cls.out = write_and_read(cls.results, RUN_INFO)
        cls.rows = cls.out["sheets"][SHEET_FOCUS]
        cls.lines = [dict(zip(FOCUS_COLUMNS, row)) for row in cls.rows[1:]]

    def test_header(self):
        self.assertEqual(self.rows[0], FOCUS_COLUMNS)

    def test_one_row_per_spec_line_and_order(self):
        # 과제: 종합 초과(입력 순: 4행·7행) → 종합 근접(3행). 조항: 초과 → 근접, 고시 순. 사양 줄: 갈래·기준 순.
        self.assertEqual([(d["입력 행 번호"], d["판정"], d["고시 조항명"], d["사양 비교 결과"]) for d in self.lines], [
            (4, OVER, "16나노 이하급 D램", OVER),
            (4, OVER, "필름 두께", OVER),
            (4, NEAR, "원자로 출력", NEAR),
            (7, OVER, "합성 전원 장치", OVER),
            (7, OVER, "합성 전원 장치", OVER),
            (3, NEAR, "합성 레이저 가공기", OVER),
            (3, NEAR, "합성 레이저 가공기", NEAR),
        ])
        over, both, near = self.results[2], self.results[5], self.results[1]
        self.assertEqual(self.rows[1:], expected_focus_rows(over) + expected_focus_rows(both) + expected_focus_rows(near))
        # 줄 수 = 중점 과제의 사양 줄 수 합(미달 조항·추가 검토 필요는 이 시트에 없다).
        self.assertEqual(len(self.lines), sum(len(c["lines"]) for r in self.results for c in r.brief["focus"]))
        self.assertNotIn(2, [d["입력 행 번호"] for d in self.lines])
        self.assertFalse(any(d["판정"] == UNDER or d["사양 비교 결과"] == UNDER for d in self.lines))
        self.assertFalse(any("추가 검토 필요" in str(v) for row in self.rows for v in row))

    def test_row_values(self):
        dram, film, reactor = self.lines[:3]
        self.assertEqual(dram, dict(zip(FOCUS_COLUMNS, [
            4, "초과 과제 가", OVER, "국가첨단전략기술", None, "16나노 이하급 D램", OVER, "14 nm", "D램 공정노드 16nm 이하",
            "기준보다 12.5% 초과", "추가 확인 조건", '최종목표 "14 nm" ↔ 기준 D램 공정노드 16nm 이하, 기준보다 12.5% 초과'])))
        self.assertEqual(film, dict(zip(FOCUS_COLUMNS, [
            4, "초과 과제 가", OVER, "전략물자(이중용도)", "1A003", "필름 두께", OVER, "0.3 mm", "두께 0.254mm 초과",
            "기준보다 18.1% 초과", "갈래 확인 필요", '목표 발췌 "0.3 mm" ↔ 기준 두께 0.254mm 초과, 기준보다 18.1% 초과'])))
        self.assertEqual(reactor, dict(zip(FOCUS_COLUMNS, [
            4, "초과 과제 가", NEAR, "전략물자(이중용도)", "1A004", "원자로 출력", NEAR, "14250 kW", "출력 15,000kW 이상",
            "기준보다 5.0% 미달", None, '활용계획 및 기대효과 "14250 kW" ↔ 기준 출력 15,000kW 이상, 기준보다 5.0% 미달'])))

    def test_every_deciding_branch_makes_a_row_and_flags_repeat(self):
        first, second = self.lines[3:5]
        self.assertEqual((first["최종목표 사양"], first["고시 기준 사양"], first["차이"]),
                         ("330 W", "평균 출력 300W 이상", "기준보다 10.0% 초과"))
        self.assertEqual((second["최종목표 사양"], second["고시 기준 사양"], second["차이"]),
                         ("550 J", "저장 에너지 500J 이상", "기준보다 10.0% 초과"))
        # 확인 표시 여럿은 "; "로 잇고, 같은 조항의 줄마다 같은 값이 들어간다.
        self.assertEqual((first["확인 표시"], second["확인 표시"]), ("추가 확인 조건; 갈래 확인 필요",) * 2)
        self.assertEqual((first["통제번호"], first["검토 대상 고시"]), (None, "전략물자(군용)"))

    def test_near_clause_mixing_met_and_near(self):
        met, short = self.lines[5:7]
        self.assertEqual((met["판정"], met["사양 비교 결과"], met["차이"]), (NEAR, OVER, "기준보다 20.0% 초과"))
        self.assertEqual((short["판정"], short["사양 비교 결과"], short["차이"]), (NEAR, NEAR, "기준보다 5.0% 미달"))
        self.assertEqual(short["사유"], '최종목표 "9.5 J" ↔ 기준 펄스 에너지 10J 이상, 기준보다 5.0% 미달')
        self.assertEqual((met["확인 표시"], short["확인 표시"]), (None, None))

    def test_reason_is_not_cut_and_has_no_tails(self):
        long_quote = "가" * 200 + " 14 nm"
        goal = f"최종 목표는 {long_quote} 달성이다."
        facts = [dict(tp.fact("q1", goal, SOURCE_FINAL_GOAL, long_quote, "D램 공정노드", "14", "14", "nm"), value_text="14 nm")]
        result = run(dict(SUMMARY_TASK, title="긴 인용 과제", final_goal=goal), MockModel(facts=facts, candidates={"advanced:item:001"}))
        line = result.brief["focus"][0]["lines"][0]
        self.assertNotEqual(line["reason"], line["display_reason"])      # 화면용만 80자에서 자른다
        row = dict(zip(FOCUS_COLUMNS, write_and_read(result)["sheets"][SHEET_FOCUS][1]))
        self.assertEqual(row["사유"], line["reason"])
        self.assertIn(long_quote, row["사유"])
        self.assertNotIn("…", row["사유"])
        for d in self.lines:
            self.assertNotIn(" · 외 ", d["사유"])
            self.assertNotIn("확인:", d["사유"])

    def test_cell_types(self):
        for row in self.out["types"][SHEET_FOCUS][1:]:
            self.assertEqual(row[0], "n")                                   # 입력 행 번호는 숫자 셀
            self.assertTrue(all(kind in ("s", "n") for kind in row))      # 빈칸(n)이 아니면 글 셀

    def test_task_order_follows_tally_groups(self):
        # 과제 순서는 간단한 결과 모듈의 종합 건수 함수가 준 중점 순서를 그대로 쓴다(이 모듈에서 따로 정하지 않는다).
        real = brief.tally_briefs

        def reversed_focus(briefs):
            made = real(briefs)
            made["groups"]["focus"] = list(reversed(made["groups"]["focus"]))
            return made
        with mock.patch.object(brief, "tally_briefs", side_effect=reversed_focus):
            out = write_and_read(self.results, RUN_INFO)
        self.assertEqual(list(dict.fromkeys(row[0] for row in out["sheets"][SHEET_FOCUS][1:])), [3, 7, 4])

    def test_same_overall_keeps_input_order_and_over_comes_first(self):
        results = [near_result(row_number=2, title="근접 가"), over_result(row_number=3, title="초과 가"),
                   near_result(row_number=4, title="근접 나"), over_result(row_number=5, title="초과 나")]
        rows = write_and_read(results)["sheets"][SHEET_FOCUS][1:]
        self.assertEqual(list(dict.fromkeys(row[1] for row in rows)), ["초과 가", "초과 나", "근접 가", "근접 나"])


class EmptyFocusSheetTests(unittest.TestCase):
    """초과·근접이 한 건도 없는 실행(spec 10절): 머리글 아래 첫 칸에 한 줄."""

    def check_empty(self, results, run_info=None):
        out = write_and_read(results, run_info)
        rows = out["sheets"][SHEET_FOCUS]
        self.assertEqual(rows, [FOCUS_COLUMNS, [EMPTY] + [None] * (len(FOCUS_COLUMNS) - 1)])
        self.assertEqual(out["types"][SHEET_FOCUS][1][0], "s")
        self.assertEqual(brief.EMPTY_MESSAGE, EMPTY)
        return out

    def test_only_under_tasks(self):
        self.check_empty([under_result(), run(dict(TASK, title="관련 없는 과제", row_number=8),
                                               MockModel(facts=FACTS, candidates=set()))], RUN_INFO)

    def test_all_errors(self):
        out = self.check_empty([error_result(), pipeline.cancelled_result(dict(SUMMARY_TASK, title="취소 과제", row_number=9),
                                                                         ALL_FAMILIES)])
        lines = dict((row[0], row[1]) for row in run_lines(out, 2)[1:5])
        self.assertEqual(lines["종합 결과"], "고시 사양 초과 0건 · 고시 사양 근접 0건 · 고시 사양 미달 0건 · 오류·취소(판정 없음) 2건")

    def test_single_no_facts(self):
        result = pipeline.run_task(dict(SUMMARY_TASK, title="개별 수치 없음"), ["core"], MockModel(facts=[]), TABLE, INDEX)
        self.check_empty(result)

    def test_no_results_at_all(self):
        out = self.check_empty([], dict(run_time="2026-11-05 10:00:00"))
        self.assertEqual(out["sheets"][SHEET_SUMMARY][0], SUMMARY_COLUMNS)


# ── 과제별 검토 결과(R6-3) ──────────────────────────────────────────────

class SummarySheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = mixed_results()
        cls.out = write_and_read(cls.results, RUN_INFO)
        cls.rows = cls.out["sheets"][SHEET_SUMMARY]
        cls.table = [dict(zip(SUMMARY_COLUMNS, row)) for row in cls.rows[1:1 + len(cls.results)]]
        cls.by_title = {line["연구개발과제명"]: line for line in cls.table}

    def test_header_and_result_order(self):
        self.assertEqual(self.rows[0], SUMMARY_COLUMNS)
        for gone in GONE_SUMMARY_COLUMNS:
            self.assertNotIn(gone, self.rows[0])
        # 줄 순서는 결과 순서(입력 순)다. 중점 과제를 앞으로 옮기지 않는다.
        self.assertEqual([line["입력 행 번호"] for line in self.table], [2, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual([line["연구개발과제명"] for line in self.table], [r.title for r in self.results])

    def test_rows_copy_the_brief(self):
        for result, line in zip(self.results, self.table):
            data = result.to_dict()
            b = data["brief"]
            self.assertEqual((line["판정"], line["사유"]), (b["overall"], shown(b["reason"])), data["title"])
            self.assertEqual([line[c] for c in SUMMARY_COLUMNS[4:8]],
                             [b["families"][f] for f in ("advanced", "core", "dual_use", "military")], data["title"])
            self.assertEqual((line["초과 조항 수"], line["근접 조항 수"]), (b["counts"]["over"], b["counts"]["near"]), data["title"])
            self.assertEqual(line["안내"], shown("; ".join(b["hints"])), data["title"])
            self.assertEqual((line["상태"], line["오류 사유"], line["입력 정보"], line["연구개발단계"]),
                             (data["status"], shown(data["error_reason"]), data["input_description"], shown(data["rnd_stage"])),
                             data["title"])

    def test_over_task(self):
        line = self.by_title["초과 과제 가"]
        self.assertEqual((line["판정"], line["사유"]), (OVER, "국가첨단전략기술 16나노 이하급 D램 외 2건"))
        self.assertEqual((line["국가첨단전략기술"], line["국가핵심기술"], line["전략물자(이중용도)"], line["전략물자(군용)"]),
                         (OVER, UNDER, OVER, UNDER))
        self.assertEqual((line["초과 조항 수"], line["근접 조항 수"]), (2, 1))
        self.assertEqual((line["연구개발단계"], line["정부지원연구개발비(백만원)"], line["입력 정보"], line["상태"]),
                         ("응용연구", 1250.5, "과제요약정보", "완료"))
        self.assertEqual((line["오류 사유"], line["안내"]), (None, None))

    def test_review_cell_joins_entries_with_newline(self):
        # 추가 검토 필요: 조항마다 '{고시 이름} {통제번호} {고시 조항명} — {남긴 이유}, {비교하지 못한 이유}'. 통제번호가 없으면 뺀다.
        line = self.by_title["초과 과제 가"]
        self.assertEqual(line["추가 검토 필요"],
                         "전략물자(이중용도) 1A005 합성 정성 통제 항목 — 이중용도 관련(AI 선별), 숫자 기준 없음\n"
                         "전략물자(군용) 군용 채택 실패 항목 — 세부 기술 일치(AI·검색), 기준값 채택 실패(원문 확인 필요)")
        at = SUMMARY_COLUMNS.index("추가 검토 필요")
        self.assertEqual(self.out["types"][SHEET_SUMMARY][3][at], "s")
        self.assertTrue(self.out["wraps"][SHEET_SUMMARY][3][at])          # 줄바꿈이 보이게
        # 종합이 미달인데 추가 검토 필요가 있는 과제(spec 10절): 이 칸에 남는다.
        under = self.by_title["미달 과제"]
        self.assertEqual(under["추가 검토 필요"], "전략물자(이중용도) 1A004 원자로 출력 — 이중용도 관련(AI 선별), 맞는 최종목표 수치 없음")
        for title in ("근접 과제", "수치 없는 과제", "오류 과제", "초과 과제 나", "관련 없는 과제", "취소 과제"):
            self.assertIsNone(self.by_title[title]["추가 검토 필요"], title)

    def test_reasons_by_case(self):
        self.assertEqual({title: line["사유"] for title, line in self.by_title.items()}, {
            "미달 과제": "기준에 못 미침",
            "근접 과제": "국가핵심기술 합성 레이저 가공기",
            "초과 과제 가": "국가첨단전략기술 16나노 이하급 D램 외 2건",
            "수치 없는 과제": "최종목표 수치 없음",
            "오류 과제": None,
            "초과 과제 나": "전략물자(군용) 합성 전원 장치",
            "관련 없는 과제": "관련 고시 조항 없음",
            "취소 과제": None,
        })
        self.assertEqual({title: line["판정"] for title, line in self.by_title.items()}, {
            "미달 과제": UNDER, "근접 과제": NEAR, "초과 과제 가": OVER, "수치 없는 과제": UNDER, "오류 과제": "오류",
            "초과 과제 나": OVER, "관련 없는 과제": UNDER, "취소 과제": "취소"})

    def test_status_error_and_hints(self):
        under = self.by_title["미달 과제"]
        # 안내 줄 여럿은 "; "로 잇는다.
        self.assertEqual(under["안내"], "의미 검색을 쓸 수 없어 세부 기술 일치 확인 안 함; 선택 칸 경고 1건 — 상세 보기에서 확인")
        self.assertEqual(under["연구개발단계"], "기초연구")
        no_facts = self.by_title["수치 없는 과제"]
        self.assertEqual((no_facts["상태"], no_facts["안내"]),
                         ("목표 수치 없음", "버린 최종목표 사양·매핑 1건 · 선택 칸 경고 1건 — 상세 보기에서 확인"))
        unrelated = self.by_title["관련 없는 과제"]
        self.assertEqual((unrelated["상태"], unrelated["안내"]), ("관련 고시 항목 없음", None))
        error = self.by_title["오류 과제"]
        self.assertEqual((error["상태"], error["판정"], error["국가첨단전략기술"], error["전략물자(군용)"]), ("오류",) * 4)
        self.assertIn("최종목표 사양 추출", error["오류 사유"])
        self.assertEqual(error["오류 사유"], self.results[4].error_reason)
        cancelled = self.by_title["취소 과제"]
        self.assertEqual((cancelled["상태"], cancelled["판정"], cancelled["오류 사유"], cancelled["안내"]), ("취소", "취소", None, None))
        self.assertEqual(cancelled["정부지원연구개발비(백만원)"], 77)
        self.assertIsNone(self.by_title["근접 과제"]["정부지원연구개발비(백만원)"])
        self.assertEqual(self.by_title["초과 과제 나"]["정부지원연구개발비(백만원)"], 300)

    def test_number_cells(self):
        types = self.out["types"][SHEET_SUMMARY]
        fund_at = SUMMARY_COLUMNS.index("정부지원연구개발비(백만원)")
        over_at, near_at = SUMMARY_COLUMNS.index("초과 조항 수"), SUMMARY_COLUMNS.index("근접 조항 수")
        for row in types[1:1 + len(self.results)]:
            self.assertEqual((row[0], row[over_at], row[near_at], row[fund_at]), ("n",) * 4)
        for line in self.table:
            self.assertIs(type(line["초과 조항 수"]), int)
            self.assertIs(type(line["근접 조항 수"]), int)

    def test_run_info_lines_after_one_blank_row(self):
        after = run_lines(self.out, len(self.results))
        self.assertEqual(after[0], [None] * len(SUMMARY_COLUMNS))
        self.assertEqual([row[:2] for row in after[1:]], [
            ["실행 일시", "2026-11-05 10:00:00"],
            ["프로그램 버전", PROGRAM_LINE],
            ["AI 모델", "claude · 합성-모델"],
            ["종합 결과", "고시 사양 초과 2건 · 고시 사양 근접 1건 · 고시 사양 미달 3건 · 오류·취소(판정 없음) 2건"],
            ["검토에서 빠진 행", "2건"],
            ["검토에서 빠진 행", EXCLUDED_LINES[0]],
            ["검토에서 빠진 행", EXCLUDED_LINES[1]],
        ])
        # 머리줄(항목·값)은 따로 쓰지 않고, 셋째 칸부터는 비어 있다.
        self.assertFalse(any(row[:2] == ["항목", "값"] for row in self.rows))
        for row in after[1:]:
            self.assertEqual(row[2:], [None] * (len(SUMMARY_COLUMNS) - 2))
        for row in self.out["types"][SHEET_SUMMARY][2 + len(self.results):]:
            self.assertEqual(row[:2], ["s", "s"])
        # 처리내역의 같은 줄과 같은 글이다.
        self.assertEqual(self.out["log"]["프로그램 버전"], [PROGRAM_LINE])
        self.assertEqual(self.out["log"]["실행 시각"], ["2026-11-05 10:00:00"])
        self.assertEqual(self.out["log"]["제외 행"], EXCLUDED_LINES)
        # 종합 건수의 합은 처리한 과제 수와 같다(오류·취소는 미달에 들지 않는다).
        self.assertEqual(2 + 1 + 3 + 2, len(self.results))

    def test_tally_line_comes_from_brief_module(self):
        with mock.patch.object(brief, "tally_text", return_value="합성 종합 건수") as tally_text:
            out = write_and_read(self.results, RUN_INFO)
        lines = dict((row[0], row[1]) for row in run_lines(out, len(self.results))[1:5])
        self.assertEqual(lines["종합 결과"], "합성 종합 건수")
        (given,), _ = tally_text.call_args
        self.assertEqual(given, brief.tally_briefs([r.brief for r in self.results])["tally"])

    def test_run_time_is_the_same_in_both_sheets_when_not_given(self):
        out = write_and_read(self.results[:1])
        lines = dict((row[0], row[1]) for row in run_lines(out, 1)[1:5])
        self.assertTrue(lines["실행 일시"])
        self.assertEqual([lines["실행 일시"]], out["log"]["실행 시각"])


class RunInfoLineTests(unittest.TestCase):
    def lines(self, results, run_info=None):
        results = results if isinstance(results, list) else [results]
        out = write_and_read(results, run_info)
        after = run_lines(out, len(results))
        self.assertEqual(after[0], [None] * len(SUMMARY_COLUMNS))
        return [row[:2] for row in after[1:]]

    def test_single_review_has_zero_excluded_rows(self):
        result = pipeline.run_task(dict(TASK, title="개별 과제"), ALL_FAMILIES, MockModel(facts=FACTS, candidates=CANDIDATES),
                                   TABLE, INDEX)
        lines = self.lines(result, dict(run_time="2026-11-06 09:30:00", provider="gemini", model="합성-모델-2",
                                        families=ALL_FAMILIES))
        self.assertEqual(lines, [
            ["실행 일시", "2026-11-06 09:30:00"],
            ["프로그램 버전", PROGRAM_LINE],
            ["AI 모델", "gemini · 합성-모델-2"],
            ["종합 결과", "고시 사양 초과 1건 · 고시 사양 근접 0건 · 고시 사양 미달 0건"],      # 오류·취소가 0이면 그 항목이 없다
            ["검토에서 빠진 행", "0건"],
        ])

    def test_missing_provider_or_model(self):
        result = near_result()
        for info, expected in ((None, "(없음) · (없음)"), (dict(provider="claude"), "claude · (없음)"),
                               (dict(model="합성-모델"), "(없음) · 합성-모델"), (dict(provider="", model=""), "(없음) · (없음)")):
            lines = dict(self.lines(result, info))
            self.assertEqual(lines["AI 모델"], expected, info)
            self.assertEqual(lines["검토에서 빠진 행"], "0건")

    def test_label_order(self):
        labels = [label for label, _ in self.lines(mixed_results(), RUN_INFO)]
        self.assertEqual(labels, RUN_LABELS + ["검토에서 빠진 행"] * len(EXCLUDED_ROWS))


# ── 고시 조항별 상세(지금 그대로) ───────────────────────────────────────────

def done_result(**changes):
    model = MockModel(facts=FACTS, candidates=CANDIDATES)
    return pipeline.run_task(dict(TASK, **changes), ALL_FAMILIES, model, TABLE, INDEX)


class DetailSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = [done_result(row_number=2),
                       pipeline.run_task(dict(SUMMARY_TASK, title="수치 없는 과제", row_number=4, rnd_stage="기초연구"),
                                         ALL_FAMILIES, MockModel(facts=[]), TABLE, INDEX),
                       pipeline.run_task(dict(SUMMARY_TASK, title="오류 과제", row_number=5), ALL_FAMILIES,
                                         MockModel(facts=FACTS, faults={"extract": ["shape", "shape"]}), TABLE, INDEX),
                       pipeline.cancelled_result(dict(SUMMARY_TASK, title="취소 과제", row_number=6, gov_fund="77"), ALL_FAMILIES)]
        cls.out = write_and_read(cls.results, RUN_INFO)

    def test_detail_sheet(self):
        rows = self.out["sheets"][SHEET_DETAIL]
        self.assertEqual(rows[0], DETAIL_COLUMNS)
        details = [dict(zip(DETAIL_COLUMNS, row)) for row in rows[1:]]
        # 비교 2건 + 매핑 없는 관련 고시 조항 2건(수치 기준 없음·수치 비교 불가) = 4줄, 과제 1건만 조항이 있다.
        self.assertEqual(len(details), 4)
        self.assertTrue(all(d["입력 행 번호"] == 2 for d in details))
        self.assertTrue(all(d["연구개발과제명"] == TASK["title"] for d in details))
        by_clause = {d["조항 ID"]: d for d in details}
        dram = by_clause["advanced:item:001"]
        self.assertEqual(dram["검토 대상 고시"], "국가첨단전략기술")
        self.assertEqual(dram["통제번호"], None)
        self.assertEqual(dram["고시 조항명"], "16나노 이하급 D램")
        self.assertEqual(dram["갈래 설명"], "가")
        self.assertEqual(dram["고시 기준 물리량"], "D램 공정노드")
        self.assertEqual(dram["비교어"], "이하")
        self.assertEqual(dram["고시 기준 사양"], "16")
        self.assertEqual(dram["고시 기준 단위"], "nm")
        self.assertEqual(dram["고시 기준 출처"], "정리된 기준")
        self.assertEqual(dram["고시 기준 원문 인용"], "D램 공정노드 16 nm")
        self.assertEqual(dram["최종목표 물리량"], "D램 공정노드")
        self.assertEqual(dram["최종목표 사양(원문)"], "14 nm")
        self.assertEqual(dram["사용한 값"], "14")
        self.assertEqual(dram["최종목표 단위"], "nm")
        self.assertEqual(dram["환산한 최종목표 사양"], "14")
        self.assertEqual(dram["최종목표 인용"], "14 nm")
        self.assertEqual(dram["최종목표 위치"], "최종목표")
        self.assertEqual(dram["차이 %"], "-12.5")
        # 이 시트는 판정 엔진의 내부 값(초과·근접·미달 …)을 그대로 보인다.
        self.assertEqual(dram["사양 비교 결과"], je.VERDICT_OVER)
        self.assertEqual(dram["조항 검토 결과"], je.VERDICT_OVER)
        self.assertEqual(dram["추가 확인 조건 원문"], "양산 가능한 것에 한함")
        self.assertIn(je.FLAG_CHECK, dram["확인 표시"])
        self.assertIn("추가 확인 조건", dram["확인 표시"])
        self.assertTrue(dram["매핑 근거"])
        film = by_clause["dual_use:control:1A003"]
        self.assertEqual(film["검토 대상 고시"], "전략물자(이중용도)")
        self.assertEqual(film["통제번호"], "1A003")
        self.assertEqual(film["비교어"], "초과")
        self.assertEqual(film["최종목표 위치"], "목표 발췌")
        self.assertIn("갈래 확인 필요", film["확인 표시"])
        # 매핑 없는 관련 고시 조항: 비교 칸은 비고 조항 검토 결과·사유만 채운다.
        text_item = by_clause["advanced:item:002"]
        self.assertEqual(text_item["조항 검토 결과"], "수치 기준 없음(관련 분야)")
        for column in ("고시 기준 물리량", "비교어", "고시 기준 사양", "최종목표 사양(원문)", "차이 %", "사양 비교 결과", "매핑 근거"):
            self.assertIsNone(text_item[column], column)
        self.assertEqual(text_item["갈래 설명"], "합성 정성 조건")
        failed = by_clause["military:item:001"]
        self.assertEqual(failed["검토 대상 고시"], "전략물자(군용)")
        self.assertEqual(failed["조항 검토 결과"], "수치 비교 불가")
        self.assertEqual(failed["비교 불가 사유"], je.REASON_FAILED)
        self.assertIn("기준값 채택 실패(원문 확인 필요)", failed["확인 표시"])

    def test_detail_keeps_every_comparison(self):
        # 비교마다 한 줄, 매핑 없는 관련 조항마다 한 줄 — 미달 조항·감춘 조항도 이 시트에는 그대로 있다.
        results = mixed_results()
        out = write_and_read(results, RUN_INFO)
        details = out["sheets"][SHEET_DETAIL][1:]
        expected = sum(len(r.judge["comparisons"])
                       + sum(1 for c in r.judge["clauses"]
                             if not any(comp["clause_id"] == c["clause_id"] for comp in r.judge["comparisons"]))
                       for r in results if r.judge)
        self.assertEqual(len(details), expected)
        self.assertEqual(sorted({row[0] for row in details}), [2, 3, 4, 7])

    def test_detail_positions_name_each_of_the_four_texts(self):
        texts = dict(final_goal="원자로 출력 15000 kW", rnd_content="시험 출력 15500 kW", utilization="확장 출력 16000 kW",
                     excerpt="발췌 출력 17000 kW")
        names = dict(final_goal="최종목표", rnd_content="연구개발내용", utilization="활용계획 및 기대효과", excerpt="목표 발췌")
        facts = []
        for key, text in texts.items():
            quote = " ".join(text.split()[-2:])   # 예: "15000 kW"
            start = text.index(quote)
            value = quote.split()[0]
            facts.append(dict(fact_id=key, subject="출력", value_text=quote, low=value, high=value, unit="kW",
                              source_field=names[key], start=start, end=start + len(quote), quote=quote))
        result = pipeline.run_task(dict(title="네 출처 과제", **texts), ["dual_use"],
                                   MockModel(facts=facts, candidates={"dual_use:control:1A004"}), TABLE, INDEX)
        out = write_and_read(result, dict(families=["dual_use"]))
        details = [dict(zip(DETAIL_COLUMNS, row)) for row in out["sheets"][SHEET_DETAIL][1:]]
        self.assertEqual(sorted(d["최종목표 위치"] for d in details),
                         sorted(["최종목표", "연구개발내용", "활용계획 및 기대효과", "목표 발췌"]))
        self.assertTrue(all("입력 간 목표값 불일치" in d["확인 표시"] for d in details))
        self.assertTrue(all(d["검토 대상 고시"] == "전략물자(이중용도)" for d in details))
        # 같은 기준에 출처가 다른 값 넷(spec 10절): 앞 시트에는 가장 높은 판정의 비교 하나만 줄, 확인 표시로 드러난다.
        focus = [dict(zip(FOCUS_COLUMNS, row)) for row in out["sheets"][SHEET_FOCUS][1:]]
        self.assertEqual(len(focus), 1)
        self.assertEqual((focus[0]["판정"], focus[0]["확인 표시"]), (OVER, "입력 간 목표값 불일치"))
        self.assertEqual(len(details), 4)

    def test_detail_sheet_does_not_read_brief(self):
        changed = []
        for result in self.results:
            data = result.to_dict()
            data["brief"] = deepcopy(data["brief"])
            data["brief"]["reason"] = "바꾼 과제 사유"
            for clause in data["brief"]["focus"]:
                clause["title"] = "바꾼 조항명"
                for line in clause["lines"]:
                    line["reason"] = "바꾼 사유"
            changed.append(data)
        other = write_and_read(changed, RUN_INFO)
        self.assertEqual(other["sheets"][SHEET_DETAIL], self.out["sheets"][SHEET_DETAIL])
        self.assertNotEqual(other["sheets"][SHEET_FOCUS], self.out["sheets"][SHEET_FOCUS])


# ── 처리내역(R6-4, 숨김) ────────────────────────────────────────────────

class LogSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = mixed_results()
        cls.out = write_and_read(cls.results, RUN_INFO)
        cls.rows = cls.out["sheets"][SHEET_LOG]
        cls.items = cls.out["log"]

    def test_lines_are_the_same_except_the_last_note(self):
        self.assertEqual(self.rows[0], ["항목", "값"])
        labels = [row[0] for row in self.rows[1:]]
        # 1.3.x의 줄과 순서 그대로이고 마지막 `참고` 줄만 없다.
        self.assertEqual(labels, LOG_HEAD_LABELS + ["제외 행"] * 2 + ["선택 칸 경고 건수"] + ["선택 칸 경고"] * 3
                         + ["버린 최종목표 사양·매핑 건수", "버린 최종목표 사양·매핑", "파일 읽기 경고 건수", "파일 읽기 경고", "오류 건수", "오류",
                            "취소 건수", "AI 호출 수", "AI 호출 수(단계별)"] + BRIEF_LOG_LABELS + [HIDDEN_LINE] * 2)
        self.assertNotIn("참고", labels)
        for old in ("기준값 표 지문", "고른 고시 범위", "빈 행 건수(세 칸 모두 비어 제외)", "버린 목표 수치·짝 건수",
                    "버린 목표 수치·짝", "버린 최종목표 사양·짝 건수", "버린 최종목표 사양·짝"):     # 1.4.1: '짝' → '매핑'
            self.assertNotIn(old, self.items, old)

    def test_values(self):
        items = self.items
        self.assertEqual(items["실행 시각"], ["2026-11-05 10:00:00"])
        # 프로그램 버전 줄은 버전 상수를 따른다(글자를 박지 않는다).
        self.assertEqual(pipeline.PROGRAM_NAME, "연구보안 등급분류 분류기준(고시) 검토")
        self.assertEqual(items["프로그램 버전"], [PROGRAM_LINE])
        self.assertEqual(items["기준본 이름"], ["synthetic"])
        self.assertEqual(items["기준본 지문"], ["0" * 64])
        self.assertEqual(items["고시 기준 사양 표 지문"], ["1" * 64])
        self.assertEqual(items["AI 제공자"], ["claude"])
        self.assertEqual(items["AI 모델"], ["합성-모델"])
        self.assertEqual(items["근접 기준(%)"], ["10"])
        self.assertEqual(items["검토 대상 고시"], ["국가첨단전략기술; 국가핵심기술; 전략물자(이중용도); 전략물자(군용)"])
        self.assertEqual(items["처리 과제 수"], [8])
        self.assertEqual(items["제외 행 건수"], [2])
        self.assertEqual(items["빈 행 건수(모든 칸이 빈 행)"], [2])
        self.assertEqual(items["제외 행"], EXCLUDED_LINES)
        self.assertEqual(items["선택 칸 경고 건수"], [3])
        self.assertEqual(items["선택 칸 경고"], ["선택 머리글 없음: 연구개발단계(값 모두 빈칸)",
                                              "4행: 정부지원연구개발비 값 확인 필요 — 약 3억",
                                              "5행: 연구개발단계 값 확인 필요 — 상용화"])
        self.assertEqual(items["버린 최종목표 사양·매핑 건수"], [1])
        self.assertEqual(items["버린 최종목표 사양·매핑"], ["5행 수치 없는 과제: [최종목표 사양 추출] 최종목표 사양 bad: 인용이 글에 없음"])
        self.assertEqual(items["파일 읽기 경고 건수"], [1])
        self.assertEqual(items["파일 읽기 경고"], ["쪽 7: 글자 깨짐 2건"])
        self.assertEqual(items["오류 건수"], [1])
        # 과제를 가리키는 줄: 일괄 검토이면 'N행 연구개발과제명'.
        self.assertEqual(items["오류"], ["6행 오류 과제: " + self.results[4].error_reason])
        self.assertEqual(items["취소 건수"], [1])
        self.assertEqual(items["AI 호출 수"], [sum(r.calls["total"] for r in self.results)])
        calls = {k: sum(r.calls[k] for r in self.results) for k in ("extract", "screen", "pair")}
        self.assertEqual(items["AI 호출 수(단계별)"],
                         [f"최종목표 사양 추출 {calls['extract']}; 관련 고시 조항 선별 {calls['screen']}; 매핑 {calls['pair']}"])

    def test_brief_lines(self):
        items = self.items
        self.assertEqual(items["세부 기술 일치 확인"], ["의미 검색을 쓸 수 없음(세부 기술 일치 확인 안 함, 1건)"])
        self.assertEqual(items["세부 기술 일치 순위 기준"], [f"같은 고시 안 상위 {brief.TOP_RANK}위"])
        self.assertEqual(items["의미 검색 모델 지문"], ["m" * 64])
        self.assertEqual(items["의미 검색 조항 벡터 지문"], ["v" * 64])
        counts = [r.brief["counts"] for r in self.results]
        # 해당 조항 수 합계 = 초과·근접·미달 조항 수의 합(1.3.x의 '해당 조항 수'와 같은 수).
        self.assertEqual(items["해당 조항 수 합계"], [sum(c["over"] + c["near"] + c["under"] for c in counts)])
        self.assertEqual(items["추가 검토 필요 수 합계"], [sum(c["review"] for c in counts)])
        self.assertEqual(items["간단한 결과에 넣지 않은 관련 조항 수 합계"], [sum(c["hidden"] for c in counts)])
        self.assertEqual(items["세부 기술 일치로 답했지만 남기지 않은 조항 수 합계"], [sum(c["detail_match_dropped"] for c in counts)])
        # 미달 1 + 근접 1 + (초과 2·근접 1) + 초과 1 = 6, 추가 검토 필요 1 + 2 = 3.
        self.assertEqual([items[label][0] for label in BRIEF_LOG_LABELS[4:]], [6, 3, 3, 2])
        # 과제별 줄: 일괄은 'N행 연구개발과제명', 두 건수가 모두 0인 과제는 줄이 없다.
        self.assertEqual(items[HIDDEN_LINE], ["2행 미달 과제: 넣지 않은 관련 조항 1건 · 남기지 않은 세부 일치 1건",
                                              "4행 초과 과제 가: 넣지 않은 관련 조항 2건 · 남기지 않은 세부 일치 1건"])
        labels = [row[0] for row in self.rows[1:]]
        types = dict(zip(labels, [row[1] for row in self.out["types"][SHEET_LOG][1:]]))
        for label in BRIEF_LOG_LABELS[4:] + ["처리 과제 수", "제외 행 건수", "오류 건수", "취소 건수", "AI 호출 수"]:
            self.assertEqual(types[label], "n", label)

    def test_dropped_lines_name_the_row_and_new_stage_names(self):
        result = pipeline.run_task(dict(TASK, row_number=9), ALL_FAMILIES, MockModel(facts=[BAD_FACT] + FACTS, candidates=CANDIDATES),
                                   TABLE, INDEX)
        items = write_and_read([result], dict(families=ALL_FAMILIES))["log"]
        self.assertEqual(items["버린 최종목표 사양·매핑 건수"], [len(result.dropped)])
        self.assertEqual(items["버린 최종목표 사양·매핑"][0], f"9행 {TASK['title']}: [최종목표 사양 추출] 최종목표 사양 bad: 인용이 글에 없음")

    def test_single_review_lines(self):
        """개별 검토: 입력 행 번호는 빈칸, 과제를 가리키는 줄은 연구개발과제명만."""
        result = pipeline.run_task(dict(SUMMARY_TASK, excerpt="x", attachment_name="계획서.hwpx"), ALL_FAMILIES,
                                   MockModel(facts=FACTS, faults={"extract": ["shape", "shape"]}), TABLE, INDEX)
        warnings = [dict(row_number=None, field="정부지원연구개발비", value="많음", message="정부지원연구개발비 값 확인 필요 — 많음")]
        out = write_and_read(result, dict(families=["advanced"], option_warnings=warnings))
        self.assertEqual(out["names"], SHEETS)
        self.assertEqual(out["states"][SHEET_LOG], "hidden")
        rows = out["sheets"][SHEET_SUMMARY]
        first = dict(zip(SUMMARY_COLUMNS, rows[1]))
        self.assertIsNone(first["입력 행 번호"])
        self.assertIsNone(first["연구개발단계"])
        self.assertIsNone(first["정부지원연구개발비(백만원)"])
        self.assertEqual(first["입력 정보"], "과제요약정보; 계획서.hwpx")
        # 이 결과는 네 고시를 골라 돌렸다(처리내역의 검토 대상 고시와 별개로 brief를 그대로 옮긴다).
        self.assertEqual((first["상태"], first["판정"], first["국가첨단전략기술"], first["국가핵심기술"]), ("오류",) * 4)
        self.assertEqual(first["오류 사유"], result.error_reason)
        items = out["log"]
        self.assertEqual(items["오류"], [f"{SUMMARY_TASK['title']}: {result.error_reason}"])
        self.assertEqual(items["선택 칸 경고 건수"], [1])
        self.assertEqual(items["선택 칸 경고"], ["정부지원연구개발비 값 확인 필요 — 많음"])
        self.assertEqual(items["검토 대상 고시"], ["국가첨단전략기술"])
        self.assertEqual(items["취소 건수"], [0])
        self.assertEqual(items["제외 행 건수"], [0])
        self.assertEqual(items["빈 행 건수(모든 칸이 빈 행)"], [0])
        self.assertNotIn("참고", items)

    def test_no_warnings_means_zero_count(self):
        items = write_and_read(done_result(), dict(families=ALL_FAMILIES))["log"]
        self.assertEqual(items["선택 칸 경고 건수"], [0])
        self.assertNotIn("선택 칸 경고", items)
        self.assertTrue(items["실행 시각"][0])


class SemanticLogTests(unittest.TestCase):
    """처리내역 `세부 기술 일치 확인`의 세 경우와 지문 두 줄."""

    @classmethod
    def setUpClass(cls):
        cls.results = mixed_results()
        cls.plain = cls.results[3:]        # 모두 not_needed

    def check_value(self, results, expected):
        self.assertEqual(write_and_read(results)["log"]["세부 기술 일치 확인"], [expected])

    def test_unavailable_count_is_number_of_tasks(self):
        again = under_result(title="또 쓸 수 없는 과제", row_number=12)
        self.assertEqual(again.brief["semantic"], "unavailable")
        self.check_value(self.results + [again], "의미 검색을 쓸 수 없음(세부 기술 일치 확인 안 함, 2건)")
        # 하나라도 쓸 수 없으면 사용한 과제가 있어도 쓸 수 없음이 앞선다.
        self.check_value([self.results[2], self.results[0]], "의미 검색을 쓸 수 없음(세부 기술 일치 확인 안 함, 1건)")

    def test_used_without_unavailable(self):
        self.check_value(self.results[2:], "의미 검색 사용")

    def test_all_not_needed(self):
        self.check_value(self.plain, "확인할 조항 없음")

    def test_unknown_semantic_value_is_refused(self):
        data = self.results[1].to_dict()
        data["brief"]["semantic"] = "모르는 값"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                excel_report.write_report(Path(folder) / "모름.xlsx", data)

    def test_fingerprints_missing_or_empty(self):
        for info in (None, {}, dict(semantic_model_fingerprint="", semantic_vectors_fingerprint=""),
                     dict(semantic_model_fingerprint=None, semantic_vectors_fingerprint=None)):
            log = write_and_read(self.plain, info)["log"]
            self.assertEqual(log["의미 검색 모델 지문"], [NOT_LOADED], info)
            self.assertEqual(log["의미 검색 조항 벡터 지문"], [NOT_LOADED], info)
        log = write_and_read(self.plain, dict(semantic_model_fingerprint="a" * 64))["log"]
        self.assertEqual((log["의미 검색 모델 지문"], log["의미 검색 조항 벡터 지문"]), (["a" * 64], [NOT_LOADED]))

    def test_rank_label_follows_constant(self):
        with mock.patch.object(brief, "TOP_RANK", 7):
            log = write_and_read(self.plain)["log"]
        self.assertEqual(log["세부 기술 일치 순위 기준"], ["같은 고시 안 상위 7위"])
        self.assertEqual(write_and_read(self.plain)["log"]["세부 기술 일치 순위 기준"], [f"같은 고시 안 상위 {brief.TOP_RANK}위"])

    def test_zero_counts_have_no_task_lines(self):
        log = write_and_read([self.plain[1], self.plain[3], self.plain[4]])["log"]       # 오류·관련 없음·취소
        self.assertNotIn(HIDDEN_LINE, log)
        self.assertEqual([log[label] for label in BRIEF_LOG_LABELS[4:]], [[0], [0], [0], [0]])


# ── 개별 검토(과제 하나) ────────────────────────────────────────────────

class SingleReviewTests(unittest.TestCase):
    """개별 검토도 같은 형식(과제 1건)이다. 입력 행 번호는 빈칸, 고르지 않은 고시는 '대조 안 함(선택 제외)'."""

    def test_single_done_result(self):
        families = ["advanced", "military"]
        model = MockModel(facts=FACTS, candidates=CANDIDATES | {"core:item:001", "dual_use:control:1A004"}, detail_matches=DETAIL)
        result = pipeline.run_task(dict(TASK, title="개별 과제"), families, model, TABLE, INDEX, search_engine=RankEngine(RANKING))
        out = write_and_read(result, dict(families=families, **SEMANTIC_INFO))
        self.assertEqual(out["names"], SHEETS)
        self.assertEqual((out["active"], out["states"][SHEET_LOG]), (SHEET_FOCUS, "hidden"))
        focus = out["sheets"][SHEET_FOCUS]
        self.assertEqual(focus[1:], expected_focus_rows(result))
        self.assertEqual([(row[0], row[2], row[5]) for row in focus[1:]], [(None, OVER, "16나노 이하급 D램")])
        rows = out["sheets"][SHEET_SUMMARY]
        self.assertEqual(len(rows), 1 + 1 + 1 + len(RUN_LABELS))
        line = dict(zip(SUMMARY_COLUMNS, rows[1]))
        self.assertIsNone(line["입력 행 번호"])
        self.assertEqual((line["판정"], line["사유"]), (OVER, "국가첨단전략기술 16나노 이하급 D램"))
        self.assertEqual((line["국가첨단전략기술"], line["국가핵심기술"], line["전략물자(이중용도)"], line["전략물자(군용)"]),
                         (OVER, EXCLUDED, EXCLUDED, UNDER))
        self.assertEqual(line["추가 검토 필요"], "전략물자(군용) 군용 채택 실패 항목 — 세부 기술 일치(AI·검색), 기준값 채택 실패(원문 확인 필요)")
        log = out["log"]
        self.assertEqual(log["세부 기술 일치 확인"], ["의미 검색 사용"])
        self.assertEqual(log[HIDDEN_LINE], ["개별 과제: 넣지 않은 관련 조항 1건 · 남기지 않은 세부 일치 0건"])
        counts = result.brief["counts"]
        self.assertEqual([log[label][0] for label in BRIEF_LOG_LABELS[4:]],
                         [counts["over"] + counts["near"] + counts["under"], counts["review"], counts["hidden"],
                          counts["detail_match_dropped"]])

    def test_single_no_facts_result(self):
        result = pipeline.run_task(dict(SUMMARY_TASK, title="개별 수치 없음"), ["core"], MockModel(facts=[]), TABLE, INDEX)
        out = write_and_read(result)
        line = dict(zip(SUMMARY_COLUMNS, out["sheets"][SHEET_SUMMARY][1]))
        self.assertEqual((line["상태"], line["판정"], line["사유"], line["국가핵심기술"], line["국가첨단전략기술"], line["안내"]),
                         ("목표 수치 없음", UNDER, "최종목표 수치 없음", UNDER, EXCLUDED, None))
        self.assertEqual((line["초과 조항 수"], line["근접 조항 수"]), (0, 0))
        self.assertEqual(out["log"]["세부 기술 일치 확인"], ["확인할 조항 없음"])


# ── 셀 규칙: 값은 brief에서만, 글 셀·긴 셀 ────────────────────────────────────

class CellRuleTests(unittest.TestCase):
    def base(self):
        return over_result(title="셀 규칙 과제", row_number=2).to_dict()

    def test_values_come_from_brief_as_given(self):
        data = self.base()
        b = data["brief"]
        b["reason"], b["families"]["core"] = "합성 과제 사유", "합성 핵심"
        b["counts"].update(over=9, near=8, under=7, review=6, hidden=5, detail_match_dropped=4)
        b["hints"] = ["첫 안내", "둘째 안내"]
        clause = b["focus"][0]
        clause.update(verdict="합성 조항 판정", family_label="합성 고시", code="합성 번호", title="합성 조항명",
                      flags=["갈래 확인 필요", "범위 목표"])
        clause["lines"][0].update(verdict="합성 비교 판정", target="합성 목표", basis="합성 기준", difference="합성 차이",
                                  reason="합성 사유")
        b["review"][0].update(family_label="합성 고시", code="", title="합성 검토 조항", reason="합성 남긴 이유")
        out = write_and_read(data)
        first = out["sheets"][SHEET_FOCUS][1]
        self.assertEqual(first, [2, "셀 규칙 과제", "합성 조항 판정", "합성 고시", "합성 번호", "합성 조항명", "합성 비교 판정", "합성 목표",
                                 "합성 기준", "합성 차이", "갈래 확인 필요; 범위 목표", "합성 사유"])
        line = dict(zip(SUMMARY_COLUMNS, out["sheets"][SHEET_SUMMARY][1]))
        self.assertEqual((line["판정"], line["사유"], line["국가핵심기술"], line["초과 조항 수"], line["근접 조항 수"], line["안내"]),
                         (OVER, "합성 과제 사유", "합성 핵심", 9, 8, "첫 안내; 둘째 안내"))
        self.assertEqual(line["추가 검토 필요"].split("\n")[0], "합성 고시 합성 검토 조항 — 합성 남긴 이유")
        log = out["log"]
        self.assertEqual([log[label][0] for label in BRIEF_LOG_LABELS[4:]], [9 + 8 + 7, 6, 5, 4])
        self.assertEqual(log[HIDDEN_LINE], ["2행 셀 규칙 과제: 넣지 않은 관련 조항 5건 · 남기지 않은 세부 일치 4건"])

    def test_rows_keep_one_line_height_even_with_many_lines_in_a_cell(self):
        # 1.4.1: 여러 줄인 칸(추가 검토 필요)이 있어도 행 높이는 한 줄(ROW_HEIGHT)로 고정한다. 셀 값·줄바꿈은 그대로다.
        self.assertEqual(excel_report.ROW_HEIGHT, 16.5)
        data = self.base()
        entry = data["brief"]["review"][0]
        data["brief"]["review"] = [dict(entry, title=f"합성 검토 조항 {number}") for number in range(12)]
        out = write_and_read([data, under_result(title="한 줄 과제", row_number=3)], RUN_INFO)
        summary = out["sheets"][SHEET_SUMMARY]
        cell = dict(zip(SUMMARY_COLUMNS, summary[1]))["추가 검토 필요"]
        self.assertEqual(len(cell.split("\n")), 12)                                  # 값은 줄이지 않는다
        self.assertTrue(out["wraps"][SHEET_SUMMARY][1][SUMMARY_COLUMNS.index("추가 검토 필요")])
        for name in out["names"]:
            for number, (row, height) in enumerate(zip(out["sheets"][name], out["heights"][name]), start=1):
                if any(value is not None for value in row):
                    self.assertEqual(height, excel_report.ROW_HEIGHT, (name, number))
                else:                                                               # 표와 실행 정보 줄 사이의 빈 줄
                    self.assertIsNone(height, (name, number))

    def test_long_cells_are_truncated(self):
        data = self.base()
        b = data["brief"]
        line = b["focus"][0]["lines"][0]
        line["target"], line["reason"] = "가" * 40000, "나" * 33000
        b["hints"] = ["다" * 20000, "라" * 20000]
        b["review"][0]["reason"] = "마" * 40000
        out = write_and_read(data)
        first = dict(zip(FOCUS_COLUMNS, out["sheets"][SHEET_FOCUS][1]))
        for column, length in (("최종목표 사양", 40000), ("사유", 33000)):
            value = first[column]
            self.assertEqual(len(value), excel_report.CELL_LIMIT, column)
            omitted = int(value.split("…(이하 생략, ")[1].rstrip("자)"))
            self.assertEqual(len(value) - len(f"…(이하 생략, {omitted}자)") + omitted, length, column)
        summary = dict(zip(SUMMARY_COLUMNS, out["sheets"][SHEET_SUMMARY][1]))
        for column in ("안내", "추가 검토 필요"):
            self.assertEqual(len(summary[column]), excel_report.CELL_LIMIT, column)
            self.assertIn("…(이하 생략, ", summary[column], column)

    def test_long_title_and_warning(self):
        long_text = "가" * 40000
        result = pipeline.cancelled_result(dict(SUMMARY_TASK, title=long_text), ALL_FAMILIES)
        out = write_and_read([result], dict(families=ALL_FAMILIES, file_warnings=["나" * 33000]))
        title = out["sheets"][SHEET_SUMMARY][1][1]
        self.assertLessEqual(len(title), excel_report.CELL_LIMIT)
        self.assertTrue(title.endswith("자)"))
        self.assertIn("…(이하 생략, ", title)
        omitted = int(title.split("…(이하 생략, ")[1].rstrip("자)"))
        self.assertEqual(len(title) - len("…(이하 생략, " + str(omitted) + "자)") + omitted, 40000)
        warning_text = out["log"]["파일 읽기 경고"][0]
        self.assertLessEqual(len(warning_text), excel_report.CELL_LIMIT)
        self.assertIn("…(이하 생략, ", warning_text)

    def test_formula_like_text_stays_text(self):
        # spec 10절: 과제명·인용이 '='로 시작하거나 꺾쇠가 든 글 → 글 셀.
        data = self.base()
        data["title"] = "=HYPERLINK(\"x\")"
        data["error_reason"] = "<b>합성</b>"
        b = data["brief"]
        b["reason"] = "=2+2"
        b["hints"] = ["-1+1"]
        clause = b["focus"][0]
        clause["title"] = "+SUM(A1)"
        clause["lines"][0].update(target="=1+1", reason="@합성", difference="=A1")
        info = dict(provider="=cmd", model="x", excluded=[dict(row_number=3, reason="=1+1", value="")])
        out = write_and_read(data, info)
        focus, focus_types = out["sheets"][SHEET_FOCUS], out["types"][SHEET_FOCUS]
        for column, text in (("연구개발과제명", "=HYPERLINK(\"x\")"), ("고시 조항명", "+SUM(A1)"), ("최종목표 사양", "=1+1"),
                             ("차이", "=A1"), ("사유", "@합성")):
            at = FOCUS_COLUMNS.index(column)
            self.assertEqual((focus[1][at], focus_types[1][at]), (text, "s"), column)
        summary, summary_types = out["sheets"][SHEET_SUMMARY], out["types"][SHEET_SUMMARY]
        for column, text in (("연구개발과제명", "=HYPERLINK(\"x\")"), ("사유", "=2+2"), ("안내", "-1+1"), ("오류 사유", "<b>합성</b>")):
            at = SUMMARY_COLUMNS.index(column)
            self.assertEqual((summary[1][at], summary_types[1][at]), (text, "s"), column)
        # 파일 어디에도 수식 셀이 없다(실행 정보 줄·처리내역 포함).
        for name in SHEETS:
            for row in out["types"][name]:
                self.assertNotIn("f", row, name)
        lines = run_lines(out, 1)
        self.assertEqual(lines[3][:2], ["AI 모델", "=cmd · x"])
        self.assertEqual(lines[6][:2], ["검토에서 빠진 행", "3행: =1+1"])

    def test_formula_like_title_of_cancelled_task(self):
        result = pipeline.cancelled_result(dict(SUMMARY_TASK, title="=HYPERLINK(\"x\")"), ALL_FAMILIES)
        out = write_and_read([result], dict(families=ALL_FAMILIES))
        self.assertEqual((out["sheets"][SHEET_SUMMARY][1][1], out["types"][SHEET_SUMMARY][1][1]), ("=HYPERLINK(\"x\")", "s"))

    def test_truncate_helper(self):
        self.assertEqual(excel_report.fit_cell("짧은 글"), "짧은 글")
        cut = excel_report.fit_cell("a" * (excel_report.CELL_LIMIT + 1))
        self.assertEqual(len(cut), excel_report.CELL_LIMIT)
        self.assertTrue(cut.endswith("자)"))


# ── 저장 전에 거부하는 결과 ───────────────────────────────────────────────

class RefusalTests(unittest.TestCase):
    def refused(self, results):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "거부.xlsx"
            with self.assertRaises(ValueError):
                excel_report.write_report(path, results)
            self.assertFalse(path.exists())      # 저장 전에 거부한다(반쯤 만든 파일을 남기지 않는다)

    def test_result_without_brief_is_refused(self):
        data = over_result().to_dict()
        del data["brief"]
        self.refused(data)
        self.refused([near_result().to_dict(), data])

    def test_unknown_overall_or_group_is_refused(self):
        # 종합 건수 함수가 모르는 값을 거부한다(조용히 한쪽으로 세지 않는다).
        for key, value in (("overall", "사양 미달 또는 무관"), ("group", "모르는 묶음")):
            data = over_result().to_dict()
            data["brief"][key] = value
            self.refused(data)

    def test_focus_clauses_outside_focus_group_are_refused(self):
        # 중점 묶음이 아닌 과제에 초과·근접 조항이 있으면 그 줄이 시트에서 조용히 빠지게 되므로 받지 않는다.
        data = under_result().to_dict()
        data["brief"]["focus"] = deepcopy(over_result().brief["focus"])
        self.refused(data)
        # 중점 묶음 과제인데 초과·근접 조항이나 사양 줄이 없는 것도 마찬가지다.
        data = over_result().to_dict()
        data["brief"]["focus"] = []
        self.refused(data)
        data = over_result().to_dict()
        data["brief"]["focus"][0]["lines"] = []
        self.refused(data)


if __name__ == "__main__":
    unittest.main()
