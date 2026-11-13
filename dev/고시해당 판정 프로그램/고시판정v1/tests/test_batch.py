"""일괄 검토(batch) 시험. 입력 양식·읽기 제외 규칙·선택 칸 정리·미리보기·동시 실행·취소를 합성 엑셀과 모의 클라이언트로 확인한다.

과제 글은 모두 합성이며 실제 과제가 아니다. 실제 AI·키를 쓰지 않는다. 엑셀은 임시 폴더에만 만든다.
"""
import inspect
from pathlib import Path
import tempfile
import threading
import unittest

from openpyxl import Workbook, load_workbook

import batch
import pipeline
from ai_stages import estimate_calls
from tests.mock_model import MockModel
from tests.test_pipeline import ALL_FAMILIES, CONTENT, FACTS, FINAL_GOAL, INDEX, TABLE, UTILIZATION

HEADERS = ["연구개발과제명", "최종목표", "연구개발내용", "활용계획 및 기대효과", "연구개발단계", "정부지원연구개발비(백만원)"]


def write_rows(path, header, rows):
    book = Workbook()
    sheet = book.active
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    book.save(path)


def full(title, goal="목표", content="내용", use="활용", stage=None, fund=None):
    """여섯 칸 순서의 행 하나."""
    return [title, goal, content, use, stage, fund]


class TemplateTests(unittest.TestCase):
    def test_template_sheet_headers_and_example_row(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "양식.xlsx"
            batch.make_template(path)
            book = load_workbook(path)
            self.assertEqual(book.sheetnames, ["연구개발과제 일괄 검토 입력"])
            sheet = book.active
            self.assertEqual([c.value for c in sheet[1]], HEADERS)
            self.assertEqual(list(batch.HEADERS), HEADERS)
            self.assertEqual(list(batch.REQUIRED_HEADERS), HEADERS[:4])
            example = [c.value for c in sheet[2]]
            self.assertTrue(str(example[0]).startswith("(예시)"))
            self.assertTrue(all(example[:4]))
            self.assertIn(example[4], ("기초연구", "응용연구", "개발연구"))
            self.assertEqual(sheet.max_row, 2)
            book.close()
            # 양식을 그대로 읽으면 예시 행만 제외되고 처리할 행은 없다.
            read = batch.read_batch_input(path)
            self.assertEqual(read["rows"], [])
            self.assertEqual(len(read["excluded"]), 1)
            self.assertEqual(read["excluded"][0]["reason"], batch.REASON_EXAMPLE)
            self.assertEqual(read["option_warnings"], [])


class ReadTests(unittest.TestCase):
    def read(self, header, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "입력.xlsx"
            write_rows(path, header, rows)
            return batch.read_batch_input(path)

    def test_rows_keep_four_texts_and_optional_fields(self):
        read = self.read(HEADERS, [full("과제 하나", FINAL_GOAL, CONTENT, UTILIZATION, "응용연구", "1,250.5")])
        self.assertEqual(read["rows"], [dict(row_number=2, title="과제 하나", final_goal=FINAL_GOAL, rnd_content=CONTENT,
                                             utilization=UTILIZATION, rnd_stage="응용연구", gov_fund="1250.5")])
        self.assertEqual(read["excluded"], [])
        self.assertEqual(read["option_warnings"], [])
        self.assertEqual(read["blank_rows"], 0)
        self.assertEqual(read["total_rows"], 1)

    def test_exclusions_with_reason_and_row_number(self):
        read = self.read(HEADERS, [
            full("과제 하나", "목표 하나"),                               # 2행: 처리
            full("", "목표 둘"),                                          # 3행: 연구개발과제명 빈 행
            full("과제 셋", "목표 셋", None),                             # 4행: 연구개발내용 빈 행
            full("(예시) 보기", "예시 목표"),                             # 5행: 예시 행
            full("과제 하나 ", " 목표 하나", stage="기초"),               # 6행: 2행과 중복(앞뒤 공백 무시, 선택 칸은 비교 안 함)
            full("과제 여섯", "목표 여섯"),                               # 7행: 처리
            [None, None, None, None, None, None],                       # 8행: 여섯 칸 모두 빈 행
            ["과제 아홉", None, None, None, None, None],                 # 9행: 연구개발과제명만 있는 행
            [None, None, None, None, "개발", 300],                       # 10행: 선택 칸만 있는 행
            full("과제 하나", "목표 하나", use="다른 활용"),              # 11행: 네 칸 중 하나가 다르면 중복 아님
        ])
        self.assertEqual([(r["row_number"], r["title"]) for r in read["rows"]],
                         [(2, "과제 하나"), (7, "과제 여섯"), (11, "과제 하나")])
        excluded = {e["row_number"]: e for e in read["excluded"]}
        self.assertEqual(sorted(excluded), [3, 4, 5, 6, 9, 10])
        self.assertEqual(excluded[3]["reason"], "필수 칸 빈칸: 연구개발과제명")
        self.assertEqual(excluded[4]["reason"], "필수 칸 빈칸: 연구개발내용")
        self.assertEqual(excluded[5]["reason"], batch.REASON_EXAMPLE)
        self.assertIn(batch.REASON_DUPLICATE, excluded[6]["reason"])
        self.assertIn("2행", excluded[6]["reason"])
        self.assertEqual(excluded[9]["reason"], "필수 칸 빈칸: 최종목표, 연구개발내용, 활용계획 및 기대효과")
        self.assertEqual(excluded[10]["reason"], "필수 칸 빈칸: 연구개발과제명, 최종목표, 연구개발내용, 활용계획 및 기대효과")
        for item in read["excluded"]:
            self.assertEqual(set(item), {"row_number", "reason", "value"})
        self.assertEqual(excluded[4]["value"], "과제 셋")
        self.assertEqual(excluded[3]["value"], "목표 둘")
        self.assertEqual(read["blank_rows"], 1)
        self.assertEqual(read["total_rows"], 10)
        # 제외한 행의 선택 칸은 정리하지 않는다(경고 없음).
        self.assertEqual(read["option_warnings"], [])

    def test_six_empty_cells_are_blank_rows_only(self):
        read = self.read(HEADERS + ["비고"], [
            [None, None, None, None, None, None, None],
            ["  ", "", None, " ", None, None, None],
            [None, None, None, None, None, None, "메모만 있음"],
            full("과제", "목표"),
        ])
        self.assertEqual(read["blank_rows"], 3)
        self.assertEqual(read["excluded"], [])
        self.assertEqual(len(read["rows"]), 1)
        self.assertEqual(read["total_rows"], 4)

    def test_column_order_and_header_spaces_do_not_matter(self):
        read = self.read([" 활용계획및기대효과", "정부지원연구개발비 (백만원)", "비고", "연구개발 과제명 ", "연구개발단계", "최종 목표",
                          "연구개발내용"],
                         [["활용", "12", "메모", "과제", "개발", "목표", "내용"]])
        self.assertEqual(read["rows"], [dict(row_number=2, title="과제", final_goal="목표", rnd_content="내용",
                                             utilization="활용", rnd_stage="개발연구", gov_fund="12")])
        self.assertEqual(read["excluded"], [])
        self.assertEqual(read["option_warnings"], [])

    def test_missing_required_header_stops_with_names(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "입력.xlsx"
            write_rows(path, ["연구개발과제명", "최종목표", "연구개발단계"], [["과제", "목표", "기초"]])
            with self.assertRaises(batch.BatchInputError) as caught:
                batch.read_batch_input(path)
            message = str(caught.exception)
            self.assertIn("연구개발내용", message)
            self.assertIn("활용계획 및 기대효과", message)
            self.assertNotIn("연구개발단계", message)
            self.assertNotIn("정부지원연구개발비", message)
            # 옛 양식(과제번호·과제명·과제요약)도 필수 머리글이 없어 멈춘다.
            write_rows(path, ["과제번호", "과제명", "과제요약"], [["A1", "과제", "요약"]])
            with self.assertRaises(batch.BatchInputError) as caught:
                batch.read_batch_input(path)
            self.assertIn("연구개발과제명", str(caught.exception))

    def test_missing_optional_headers_give_blank_values_and_warning(self):
        read = self.read(HEADERS[:4], [full("과제", "목표")[:4]])
        self.assertEqual(read["rows"][0]["rnd_stage"], "")
        self.assertEqual(read["rows"][0]["gov_fund"], "")
        messages = [w["message"] for w in read["option_warnings"]]
        self.assertEqual(messages, ["선택 머리글 없음: 연구개발단계(값 모두 빈칸)",
                                    "선택 머리글 없음: 정부지원연구개발비(백만원)(값 모두 빈칸)"])
        self.assertTrue(all(w["row_number"] is None for w in read["option_warnings"]))
        read = self.read(HEADERS[:5], [full("과제", "목표", stage="응용")[:5]])
        self.assertEqual(read["rows"][0]["rnd_stage"], "응용연구")
        self.assertEqual([w["message"] for w in read["option_warnings"]],
                         ["선택 머리글 없음: 정부지원연구개발비(백만원)(값 모두 빈칸)"])

    def test_duplicated_header_reads_first_column_and_warns(self):
        headers = list(HEADERS) + ["최종목표"]
        row = list(full("과제", "첫 열 목표")) + ["둘째 열 목표"]
        read = self.read(headers, [row])
        self.assertEqual(read["rows"][0]["final_goal"], "첫 열 목표")
        self.assertEqual([w["message"] for w in read["option_warnings"]],
                         ["같은 머리글이 여러 번: 최종목표(첫 열만 읽음)"])

    def test_stage_short_names_and_bad_values(self):
        read = self.read(HEADERS, [full("과제 기초", stage="기초"), full("과제 응용", stage=" 응용연구 "),
                                   full("과제 개발", stage="개발"), full("과제 빈", stage=None),
                                   full("과제 잘못", stage="상용화"), full("과제 숫자", stage=2)])
        self.assertEqual([r["rnd_stage"] for r in read["rows"]], ["기초연구", "응용연구", "개발연구", "", "", ""])
        self.assertEqual(len(read["rows"]), 6)   # 잘못된 값의 행도 제외하지 않고 검토한다
        self.assertEqual([w["message"] for w in read["option_warnings"]],
                         ["6행: 연구개발단계 값 확인 필요 — 상용화", "7행: 연구개발단계 값 확인 필요 — 2"])
        self.assertEqual([(w["row_number"], w["field"], w["value"]) for w in read["option_warnings"]],
                         [(6, "연구개발단계", "상용화"), (7, "연구개발단계", "2")])

    def test_fund_commas_decimals_excel_numbers_and_bad_values(self):
        read = self.read(HEADERS, [full("과제 쉼표", fund="1,250"), full("과제 소수", fund="0.75"),
                                   full("과제 정수 셀", fund=1500), full("과제 실수 셀", fund=12.5),
                                   full("과제 빈", fund=None), full("과제 영", fund="0"), full("과제 음수", fund=-3),
                                   full("과제 글", fund="약 3억"), full("과제 큰 값", fund="123,456,789,012")])
        self.assertEqual([r["gov_fund"] for r in read["rows"]], ["1250", "0.75", "1500", "12.5", "", "", "", "", "123456789012"])
        self.assertEqual(len(read["rows"]), 9)
        self.assertEqual([w["message"] for w in read["option_warnings"]],
                         ["7행: 정부지원연구개발비 값 확인 필요 — 0", "8행: 정부지원연구개발비 값 확인 필요 — -3",
                          "9행: 정부지원연구개발비 값 확인 필요 — 약 3억"])

    def test_missing_file_is_error(self):
        with self.assertRaises(batch.BatchInputError):
            batch.read_batch_input(Path(tempfile.gettempdir()) / "없는-고시수준검토-시험.xlsx")

    def test_numbers_in_text_cells_are_kept_as_text(self):
        read = self.read(HEADERS, [[2026001, 5, "내용", "활용", None, None]])
        self.assertEqual(read["rows"][0]["title"], "2026001")
        self.assertEqual(read["rows"][0]["final_goal"], "5")


class PreviewTests(unittest.TestCase):
    def test_counts_and_estimated_calls(self):
        rows = [dict(row_number=2, title="a", final_goal="s"), dict(row_number=3, title="b", final_goal="t")]
        preview = batch.batch_preview(rows, ["advanced", "dual_use"], TABLE)
        low, high = estimate_calls(["advanced", "dual_use"], TABLE)
        self.assertEqual(preview["count"], 2)
        self.assertEqual(preview["families"], ["advanced", "dual_use"])
        self.assertEqual(preview["calls_per_task"], (low, high))
        self.assertEqual(preview["calls_total"], (low * 2, high * 2))


class RunTests(unittest.TestCase):
    @staticmethod
    def rows(count):
        return [dict(row_number=i + 2, title=f"합성 과제 {i}", final_goal=FINAL_GOAL, rnd_content=CONTENT,
                     utilization=UTILIZATION, rnd_stage="기초연구" if i % 2 else "", gov_fund=str(100 + i))
                for i in range(count)]

    def test_results_in_input_order_and_error_row_continues(self):
        made = []

        def factory():
            index = len(made)
            if index == 1:
                client = MockModel(facts=FACTS, faults={"extract": ["shape", "shape"]})
            else:
                client = MockModel(facts=FACTS, candidates={"advanced:item:001"})
            made.append(client)
            return client
        results = batch.run_batch(self.rows(4), ALL_FAMILIES, factory, TABLE, INDEX, workers=1)
        self.assertEqual([r.title for r in results], [f"합성 과제 {i}" for i in range(4)])
        self.assertEqual([r.status for r in results], [pipeline.STATUS_DONE, pipeline.STATUS_ERROR,
                                                        pipeline.STATUS_DONE, pipeline.STATUS_DONE])
        self.assertEqual([r.row_number for r in results], [2, 3, 4, 5])
        self.assertEqual([r.rnd_stage for r in results], ["", "기초연구", "", "기초연구"])
        self.assertEqual([r.gov_fund for r in results], ["100", "101", "102", "103"])
        self.assertEqual(len(made), 4)   # 행마다 독립 클라이언트

    def test_stage_and_fund_never_reach_requests(self):
        made = []

        def factory():
            made.append(MockModel(facts=FACTS, candidates={"advanced:item:001"}))
            return made[-1]
        rows = [dict(self.rows(1)[0], rnd_stage="응용연구", gov_fund="76543.21")]
        batch.run_batch(rows, ALL_FAMILIES, factory, TABLE, INDEX, workers=1)
        for request in made[0].requests:
            for text in (request["system"], request["user"]):
                for forbidden in ("응용연구", "76543", "연구개발단계", "정부지원연구개발비"):
                    self.assertNotIn(forbidden, text)

    def test_factory_failure_is_row_error(self):
        def factory():
            raise RuntimeError("키 없음(합성)")
        results = batch.run_batch(self.rows(2), ALL_FAMILIES, factory, TABLE, INDEX, workers=2)
        self.assertEqual([r.status for r in results], [pipeline.STATUS_ERROR] * 2)
        self.assertIn("키 없음(합성)", results[0].error_reason)
        self.assertEqual(results[1].rnd_stage, "기초연구")

    def test_order_kept_with_many_workers(self):
        results = batch.run_batch(self.rows(7), ALL_FAMILIES, lambda: MockModel(facts=FACTS, candidates={"advanced:item:001"}),
                                  TABLE, INDEX, workers=3)
        self.assertEqual([r.row_number for r in results], list(range(2, 9)))
        self.assertTrue(all(r.status == pipeline.STATUS_DONE for r in results))

    def test_invalid_workers(self):
        with self.assertRaises(ValueError):
            batch.run_batch(self.rows(1), ALL_FAMILIES, lambda: MockModel(facts=FACTS), TABLE, INDEX, workers=0)

    def test_cancel_keeps_finished_rows(self):
        cancel = threading.Event()
        events = []

        def progress(event):
            events.append(event)
            if event.get("completed") == 2:
                cancel.set()
        results = batch.run_batch(self.rows(6), ALL_FAMILIES, lambda: MockModel(facts=FACTS, candidates={"advanced:item:001"}),
                                  TABLE, INDEX, workers=1, progress=progress, cancel_event=cancel)
        self.assertEqual(len(results), 6)
        statuses = [r.status for r in results]
        self.assertEqual(statuses[:2], [pipeline.STATUS_DONE] * 2)
        self.assertEqual(statuses.count(pipeline.STATUS_CANCELLED), 4)
        self.assertEqual(batch.count_status(results, pipeline.STATUS_CANCELLED), 4)
        cancelled = results[-1]
        self.assertEqual(cancelled.error_reason, "")
        self.assertEqual(cancelled.calls["total"], 0)
        self.assertEqual(cancelled.overall, "판정 안 함(상태 참고)")
        self.assertEqual(cancelled.row_number, 7)

    def test_cancel_before_start(self):
        cancel = threading.Event()
        cancel.set()
        results = batch.run_batch(self.rows(2), ALL_FAMILIES, lambda: MockModel(facts=FACTS), TABLE, INDEX, cancel_event=cancel)
        self.assertEqual([r.status for r in results], [pipeline.STATUS_CANCELLED] * 2)

    def test_progress_events(self):
        events = []
        batch.run_batch(self.rows(3), ALL_FAMILIES, lambda: MockModel(facts=FACTS, candidates={"advanced:item:001"}),
                        TABLE, INDEX, workers=2, progress=events.append)
        finished = [e for e in events if e.get("stage") == "batch"]
        self.assertEqual([e["completed"] for e in finished], [1, 2, 3])
        self.assertTrue(all(e["total"] == 3 for e in finished))

    def test_rows_missing_summary_fields_are_row_errors_not_crash(self):
        rows = [dict(row_number=2, title="과제", final_goal="목표", rnd_content="", utilization="활용")]
        results = batch.run_batch(rows, ALL_FAMILIES, lambda: MockModel(facts=FACTS), TABLE, INDEX)
        self.assertEqual(results[0].status, pipeline.STATUS_ERROR)


# ── 간단한 결과(brief): 검색 엔진·행별 선택 칸 경고(1.3.0) ─────────────────────

class SharedEngine:
    """여러 행이 함께 쓰는 가짜 검색 엔진. 받은 글을 기록하고 정해 둔 순위를 돌려준다."""

    def __init__(self, ranking):
        self.ranking = ranking
        self.texts = []
        self._lock = threading.Lock()

    def semantic_ranking(self, text):
        with self._lock:
            self.texts.append(text)
        return dict(available=True, reason="", ranking={f: list(self.ranking.get(f, [])) for f in pipeline.FAMILY_ORDER})


def warning(row_number, value="상용화"):
    prefix = f"{row_number}행: " if row_number is not None else ""
    return dict(row_number=row_number, field="연구개발단계", value=value, message=f"{prefix}연구개발단계 값 확인 필요 — {value}")


class BatchBriefTests(unittest.TestCase):
    HINT = "선택 칸 경고 {}건 — 상세 보기에서 확인"

    @staticmethod
    def rows(count):
        return [dict(row_number=i + 2, title=f"합성 과제 {i}", final_goal=FINAL_GOAL, rnd_content=f"{CONTENT} 행 {i}",
                     utilization=UTILIZATION, rnd_stage="", gov_fund="") for i in range(count)]

    @staticmethod
    def factory(detail=("core:item:001",)):
        return lambda: MockModel(facts=FACTS[:1], candidates={"advanced:item:001", "core:item:001"}, detail_matches=set(detail))

    def test_new_arguments_are_optional_keywords(self):
        params = inspect.signature(batch.run_batch).parameters
        for name, default in (("search_engine", None), ("option_warnings", ())):
            self.assertEqual(params[name].kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertEqual(params[name].default if name == "search_engine" else tuple(params[name].default), default)

    def test_row_warnings_reach_only_their_rows(self):
        warnings = [dict(row_number=None, field="정부지원연구개발비(백만원)", value="",
                         message="선택 머리글 없음: 정부지원연구개발비(백만원)(값 모두 빈칸)"),
                    warning(3), warning(3, "2"), warning(5)]
        results = batch.run_batch(self.rows(4), ALL_FAMILIES, self.factory(detail=()), TABLE, INDEX, workers=2,
                                  option_warnings=warnings)
        self.assertEqual([r.status for r in results], [pipeline.STATUS_DONE] * 4)
        self.assertEqual([r.brief["hints"] for r in results], [[], [self.HINT.format(2)], [], [self.HINT.format(1)]])

    def test_cancelled_and_error_rows_keep_their_warning_count(self):
        cancel = threading.Event()
        cancel.set()
        results = batch.run_batch(self.rows(2), ALL_FAMILIES, self.factory(), TABLE, INDEX, cancel_event=cancel,
                                  option_warnings=[warning(2)])
        self.assertEqual([r.brief["overall"] for r in results], ["취소", "취소"])
        self.assertEqual([r.brief["hints"] for r in results], [[self.HINT.format(1)], []])

        def broken():
            raise RuntimeError("키 없음(합성)")
        results = batch.run_batch(self.rows(2), ["core"], broken, TABLE, INDEX, option_warnings=[warning(3)])
        self.assertEqual([r.brief["overall"] for r in results], ["오류", "오류"])
        self.assertEqual([r.brief["families"]["core"] for r in results], ["오류", "오류"])
        self.assertEqual([r.brief["hints"] for r in results], [[], [self.HINT.format(1)]])

    def test_read_then_run_with_read_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "입력.xlsx"
            write_rows(path, HEADERS, [full("과제 가", FINAL_GOAL, CONTENT, UTILIZATION, "상용화", "약 3억"),
                                       full("과제 나", FINAL_GOAL, CONTENT + " 둘", UTILIZATION, "기초", "100")])
            read = batch.read_batch_input(path)
        results = batch.run_batch(read["rows"], ALL_FAMILIES, self.factory(detail=()), TABLE, INDEX,
                                  option_warnings=read["option_warnings"])
        self.assertEqual([r.brief["hints"] for r in results], [[self.HINT.format(2)], []])

    def test_shared_search_engine_and_worker_count(self):
        ranking = dict(core=["core:item:001"])
        briefs = {}
        for workers in (1, 3):
            engine = SharedEngine(ranking)
            results = batch.run_batch(self.rows(6), ALL_FAMILIES, self.factory(), TABLE, INDEX, workers=workers,
                                      search_engine=engine)
            briefs[workers] = [r.brief for r in results]
            self.assertEqual(sorted(engine.texts), sorted(f"합성 과제 {i}\n{FINAL_GOAL}\n{CONTENT} 행 {i}" for i in range(6)))
        self.assertEqual(briefs[1], briefs[3])
        self.assertTrue(all(b["semantic"] == "used" and b["review"][0]["clause_id"] == "core:item:001" for b in briefs[1]))
        # 엔진 없이 돌리면 같은 행이 '의미 검색을 쓸 수 없음'으로 드러난다.
        without = batch.run_batch(self.rows(2), ALL_FAMILIES, self.factory(), TABLE, INDEX)
        self.assertEqual([r.brief["semantic"] for r in without], ["unavailable"] * 2)

    def test_batch_sends_no_per_task_progress(self):
        events = []
        batch.run_batch(self.rows(3), ALL_FAMILIES, self.factory(), TABLE, INDEX, workers=2, progress=events.append,
                        search_engine=SharedEngine(dict(core=["core:item:001"])))
        self.assertEqual({e["stage"] for e in events}, {"batch"})
        self.assertEqual(len(events), 3)


if __name__ == "__main__":
    unittest.main()
