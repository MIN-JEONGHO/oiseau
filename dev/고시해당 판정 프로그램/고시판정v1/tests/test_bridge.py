"""연결 함수(bridge) 시험. 모의 엔진·가짜 키 저장소·가짜 파일 선택으로 화면 경계의 약속을 확인한다.

실제 AI·키·WebView 창을 쓰지 않는다. 과제 글·조항·기준값은 tests/test_pipeline의 합성 자료다.
확인하는 것: 허용 함수 목록이 호스트와 같음, 토큰 없는 경로 거부, 잘못된 토큰 거부, 작업 중 두 번째 시작 거부, 취소,
키 저장·삭제 뒤 모든 응답에 키 원문 없음, 오류 응답에 스택·키 없음, extract_attachment의 실패 사유, estimate 값,
save_report가 excel_report를 부름.
고시 검색(search_notices·get_notice_detail): 허용 목록에 있음, 검토 작업 중에도 응답, 엔진은 한 번만 만들고 불러 둔
기준본·기준값 표를 넘김, 초기 상태의 검색 상태, 엔진 준비 실패가 안전한 응답, 검색어 길이 상한·잘못된 고시·잘못된 조항
ID·잘못된 쪽 값 거부, 결과에 점수 없음, 다음 위치(next_offset), 검색어를 브리지에 남기지 않음. 검색 거부·결과 시험은
실제 고시 자료(공개 자료)·실제 관련어 사전·실제 모델로 만든 엔진을 쓴다(SearchBridgeTests).
간단한 결과(1.3.0, 모양은 1.4.0 spec R7-1): 개별·일괄 결과에 brief가 있음, 검토가 03 탭과 같은 검색 엔진을
run_task/run_batch에 넘김, 선택 칸 경고가 넘어감, 일괄의 선택 칸 경고 안내 줄(Python이 만듦), 실행 정보의 의미 검색 지문
두 값(실행이 끝난 뒤 값, 못 쓰면 빈 글), 함수 17개의 이름·인자 불변.
일괄 결과(1.4.0 spec R4·R7-2): 종합 건수 tally(합 = counts.total, 오류·취소 0이면 항목 없음, 일부 오류·일괄 취소·전부
오류)와 과제 묶음 groups(모든 행이 정확히 한 묶음, 중점은 종합 초과 → 근접)가 brief.tally_briefs의 결과 그대로임(연결
함수가 따로 세지 않음), 묶음 제목 글 셋과 focus_empty_message(0건일 때 포함), notices 키 없음, 건수가 서로 맞지 않으면
결과를 내지 않고 작업 실패, 개별 결과에는 더하는 키 없음, 일괄·개별 결과를 저장한 엑셀의 시트 구성(숨김 처리내역)과
화면·엑셀의 종합 건수·중점 과제 순서가 같음, 처음 상태의 note.
"""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import batch
import brief
import bridge as bridge_module
import judge_engine as je
from ai_stages import estimate_calls
from bridge import Bridge, Resources
from credential_store import KeyManager
from doc_extract import DocumentError, ExtractResult, GoalSection
from notice_catalogue import note_records
import notice_search
import pipeline
from tests.mock_model import MockModel
from tests.test_pipeline import ALL_FAMILIES, CONTENT, FACTS, FINAL_GOAL, INDEX, TABLE, TASK, UTILIZATION

SECRET = "sk-synthetic-SECRET-0123456789"
CANDIDATES = {"advanced:item:001", "advanced:item:002", "dual_use:control:1A003", "military:item:001"}
CATALOGUE_SUMMARY = dict(catalogue_id="synthetic", fingerprint="0" * 64, item_count=len(INDEX),
                         family_item_counts={"advanced": 2, "core": 1, "dual_use": 2, "military": 1},
                         notices=[dict(notice_number="합성 고시 제1호", title="합성 고시", announcement_date="2026-01-01",
                                       effective_date="2026-01-02", families=["advanced"])])
TERMINAL = ("done", "cancelled", "failed")
EXCERPT = "필름 두께 0.3 mm 이상 코팅 공정 개발"


def task(title="합성", **changes):
    """화면이 보내는 개별 검토 과제 입력(과제요약정보 세 칸을 채움)."""
    return dict(dict(title=title, final_goal=FINAL_GOAL, rnd_content=CONTENT, utilization=UTILIZATION), **changes)


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.fail = set()

    def _check(self, operation):
        if operation in self.fail:
            raise RuntimeError("native credential error " + SECRET)

    def get(self, provider):
        self._check("get")
        return self.values.get(provider)

    def set(self, provider, key):
        self._check("set")
        self.values[provider] = key

    def delete(self, provider):
        self._check("delete")
        self.values.pop(provider, None)


class GateClient:
    """첫 요청에서 gate가 열릴 때까지 기다리는 모의 클라이언트(작업 중 상태를 만들기 위해)."""

    def __init__(self, gate, inner):
        self.gate = gate
        self.inner = inner

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        self.gate.wait(10)
        return self.inner.ask_json(system_prompt, user_prompt, temperature)


SEARCH_ITEM = dict(clause_id="advanced:item:001", family="advanced", family_label="국가첨단전략기술", code="",
                   title="합성 D램 조항", field="반도체", reason="검색어 일치", reasons=["검색어 일치"],
                   snippet="합성 D램 원문", highlights=[[3, 5]])


class FakeSearchEngine:
    """합성 고시 검색 엔진(점수 없음). 검토 작업과 무관하게 응답하는지 보는 데 쓴다. 부른 횟수만 센다."""

    def __init__(self):
        self.calls = 0

    def status(self):
        return dict(dictionary=dict(available=True, reason="", reviewed_on=None, notice=""),
                    semantic=dict(state="pending", available=False, reason="", notice=""))

    def search(self, query, family=notice_search.FILTER_ALL, limit=20, offset=0, similar_offset=0):
        self.calls += 1
        items = [dict(SEARCH_ITEM)] if offset == 0 else []

        def group(rows, start):
            return dict(items=rows, total=1, offset=start, limit=limit, remaining=0, has_more=False, visible=True,
                        empty_message="")
        return dict(mode="keyword", family=family, family_label="전체", results=group(items, offset),
                    similar=dict(group([], similar_offset), notice=notice_search.NOTICE_SIMILAR), status=self.status(),
                    footer=notice_search.NOTICE_FOOTER, empty_message="")

    def detail(self, clause_id, query=""):
        self.calls += 1
        if clause_id != SEARCH_ITEM["clause_id"]:
            raise notice_search.UnknownClauseError("synthetic unknown clause")
        return dict(clause_id=clause_id, family="advanced", family_label="국가첨단전략기술", code="", title="합성 D램 조항",
                    field="반도체", source_anchor="synthetic", text="합성 D램 원문", highlights=[[3, 5]],
                    criteria=notice_search.criteria_list(None))


MODEL_FP, VECTORS_FP = "a" * 64, "b" * 64
RUN_HINT = "선택 칸 경고 {}건 — 상세 보기·처리내역(숨김 시트)에서 확인"
TASK_HINT = "선택 칸 경고 {}건 — 상세 보기에서 확인"
# 화면 맨 아래 한 줄(처음 상태의 note). 결과마다 되풀이하지 않지만 프로그램에는 늘 보인다(spec R3).
FOOTER_NOTE = "이 결과는 고시 수치 기준과의 참고 대조이며 고시 해당 여부의 공식 판정이 아님."
# 일괄 결과의 묶음 제목 글과 빈 경우 글(spec R7-2, 글자 그대로).
FOCUS_LABEL = "중점 검토 과제 (초과·근접 {}건)"
OTHER_LABEL = "그 밖의 과제 (고시 사양 미달 {}건)"
UNJUDGED_LABEL = "판정하지 못한 과제 (오류 {} · 취소 {})"
FOCUS_EMPTY = "고시 사양을 초과하거나 근접한 과제 없음"
# 일괄 결과(화면용)의 키 전체와 요약 행의 키 전체. notices는 없다.
BATCH_RESULT_KEYS = {"name", "counts", "tally", "groups", "tally_members", "focus_label", "focus_empty_message", "unjudged_label",
                     "other_label", "excluded", "option_warnings", "hints", "rows", "run"}
BATCH_COUNT_KEYS = {"total", "done", "no_facts", "no_candidates", "error", "cancelled", "excluded", "blank_rows",
                    "option_warnings"}
BATCH_ROW_KEYS = {"row_number", "title", "rnd_stage", "gov_fund", "status", "overall", "families", "counts",
                  "flagged_clause_count", "error_reason", "calls", "dropped_count", "brief"}
BATCH_ONLY_KEYS = ("tally", "groups", "tally_members", "focus_label", "focus_empty_message", "unjudged_label", "other_label", "notices")
REPORT_SHEETS = ["초과·근접 조항", "과제별 검토 결과", "고시 조항별 상세", "처리내역"]
ERROR_MARK, WAIT_MARK = "오류 표시", "대기 표시"


def goal(node):
    """합성 최종목표 글. 합성 표의 D램 공정노드 기준(16 nm 이하)과 견주어 14 → 초과, 17 → 근접, 20 → 미달."""
    return f"본 과제의 최종 목표는 D램 공정노드 {node} nm 달성이다."


def tally_of(result):
    """일괄 결과의 종합 건수 → [(kind, label, count)]."""
    for entry in result["tally"]:
        assert set(entry) == {"kind", "label", "count"}, entry
    return [(entry["kind"], entry["label"], entry["count"]) for entry in result["tally"]]


class MarkedClient:
    """연구개발과제명에 표시 글이 든 과제만 다르게 다루는 모의 클라이언트(실제 AI 아님).

    ERROR_MARK → 인증 오류(그 과제가 '오류'로 끝난다), WAIT_MARK → gate가 열릴 때까지 기다린다(일괄 취소 시험).
    """

    def __init__(self, inner, gate=None):
        self.inner = inner
        self.gate = gate

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        from llm_client import AuthenticationError
        if ERROR_MARK in user_prompt:
            raise AuthenticationError()
        if self.gate is not None and WAIT_MARK in user_prompt:
            self.gate.wait(10)
        return self.inner.ask_json(system_prompt, user_prompt, temperature)


class RankingSearchEngine(FakeSearchEngine):
    """의미 검색 순위도 주는 합성 엔진. 실제 엔진처럼 지문은 처음 semantic_ranking을 부를 때 생긴다(그 전엔 빈 글).

    available=False이면 모델을 불러오지 못한 엔진처럼 '쓸 수 없음'을 돌려주고 지문은 빈 글로 남는다.
    """

    def __init__(self, ranking=None, available=True):
        super().__init__()
        self.ranking = ranking if ranking is not None else {"advanced": ["advanced:item:002", "advanced:item:001"]}
        self.available = available
        self.ranking_calls = 0
        self.semantic_model_fingerprint = ""
        self.semantic_vectors_fingerprint = ""
        self._ranking_lock = threading.Lock()

    def semantic_ranking(self, text):
        with self._ranking_lock:
            self.ranking_calls += 1
            if not self.available:
                return dict(available=False, reason="합성: 모델 없음", ranking=None)
            self.semantic_model_fingerprint, self.semantic_vectors_fingerprint = MODEL_FP, VECTORS_FP
        return dict(available=True, reason="", ranking={f: list(self.ranking.get(f, [])) for f in pipeline.FAMILY_ORDER})


def recording(real):
    """부른 키워드 인자를 기록하고 실제 함수를 그대로 부르는 실행기(task_runner·batch_runner 자리)."""
    calls = []

    def runner(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)
    return runner, calls


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.attachment = self.root / "계획서.hwpx"
        self.attachment.write_bytes(b"synthetic; extractor is injected")
        self.batch_input = self.root / "입력.xlsx"
        self.report_path = self.root / "결과.xlsx"
        self.template_path = self.root / "양식.xlsx"
        self.selected = {"attachment": self.attachment, "batch_input": self.batch_input,
                         "save_report": self.report_path, "save_template": self.template_path}
        self.backend = FakeBackend()
        self.backend.values["claude"] = SECRET
        self.client_keys = []
        self.models = []
        self.detail_matches = None
        self.gate = None
        self.written = []
        self.templates = []
        self.extract_calls = []
        self.bridge = self.make_bridge()

    # ── 도우미 ────────────────────────────────────────────────────────
    def make_client(self, settings, key):
        self.client_keys.append((dict(settings), key))
        inner = MockModel(facts=FACTS, candidates=CANDIDATES, detail_matches=self.detail_matches)
        self.models.append(inner)
        return GateClient(self.gate, inner) if self.gate is not None else inner

    def write_report(self, path, results, run_info=None):
        self.written.append(dict(path=Path(path), results=[r.to_dict() if hasattr(r, "to_dict") else r for r in results],
                                 run_info=deepcopy(run_info)))
        Path(path).write_bytes(b"synthetic workbook")
        return Path(path)

    def make_template(self, path):
        self.templates.append(Path(path))
        Path(path).write_bytes(b"synthetic template")
        return Path(path)

    def extract(self, path):
        self.extract_calls.append(Path(path))
        text = "1. 개요\n내용\n2. 최종 목표\n출력 5 kW 이상\n빔 품질 M2 1.3 이하\n3. 기대효과\n효과"
        return ExtractResult(text=text, kind="hwpx", warnings=["그림 2건 제외"], page_count=None), \
            [GoalSection(heading="2. 최종 목표", start=12, end=38, body=text[12:38])]

    def make_bridge(self, **overrides):
        kwargs = dict(key_manager=KeyManager(self.backend, environ={}),
                      resources_loader=lambda: Resources(catalogue=CATALOGUE_SUMMARY, index=INDEX, table=TABLE),
                      client_factory=self.make_client, path_selector=lambda kind: self.selected.get(kind),
                      extractor=self.extract, report_writer=self.write_report, template_maker=self.make_template,
                      search_factory=self.make_search_engine)
        kwargs.update(overrides)
        return Bridge(**kwargs)

    def make_search_engine(self, resources):
        self.search_factory_calls = getattr(self, "search_factory_calls", [])
        self.search_factory_calls.append(resources)
        self.search_engine = FakeSearchEngine()
        return self.search_engine

    def ok(self, response):
        self.assertIsInstance(response, dict)
        self.assertEqual(set(response), {"ok", "data"}, response)
        self.assertIs(response["ok"], True)
        text = json.dumps(response, ensure_ascii=False, allow_nan=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("Traceback", text)
        return response["data"]

    def refused(self, response, code=None):
        self.assertIsInstance(response, dict)
        self.assertEqual(set(response), {"ok", "code", "message"}, response)
        self.assertIs(response["ok"], False)
        self.assertIsInstance(response["message"], str)
        self.assertTrue(response["message"])
        text = json.dumps(response, ensure_ascii=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("File \"", text)
        if code:
            self.assertEqual(response["code"], code)
        return response

    def token(self, kind, bridge=None):
        data = self.ok((bridge or self.bridge).select_path(kind))
        self.assertIs(data["cancelled"], False)
        self.assertIsInstance(data["token"], str)
        self.assertTrue(data["token"])
        self.assertNotIn(str(self.root), data["token"])
        self.assertEqual(data["name"], self.selected[kind].name)
        return data["token"]

    def wait(self, bridge=None, timeout=8):
        bridge = bridge or self.bridge
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.ok(bridge.poll_progress(0))
            if data["state"] in TERMINAL:
                return data
            time.sleep(.005)
        self.fail("합성 작업이 끝나지 않음")

    def write_batch_input(self, rows):
        book_rows = [list(batch.HEADERS)] + rows
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        for row in book_rows:
            sheet.append(row)
        book.save(self.batch_input)

    def marked_factory(self, gate=None):
        """과제 글의 수를 규칙으로 읽는 모의 모델(행마다 판정이 달라진다)을 MarkedClient로 감싼 클라이언트 공장."""
        return lambda settings, key: MarkedClient(MockModel(facts=None, candidates=CANDIDATES), gate)

    def write_goal_rows(self, rows):
        """(연구개발과제명, 최종목표 글) 목록으로 합성 일괄 입력을 만든다. 입력 행 번호는 2부터다."""
        self.write_batch_input([[title, final_goal, CONTENT, UTILIZATION, None, None] for title, final_goal in rows])

    def run_batch_job(self, bridge, families=ALL_FAMILIES):
        token = self.token("batch_input", bridge)
        self.ok(bridge.read_batch(token))
        self.ok(bridge.run_batch(token, families))
        return self.wait(bridge)

    def read_report(self):
        """저장한 결과 엑셀의 시트 이름·보임 상태·열린 시트·시트별 값."""
        from openpyxl import load_workbook
        book = load_workbook(self.report_path)
        try:
            return dict(names=list(book.sheetnames), states={name: book[name].sheet_state for name in book.sheetnames},
                        active=book.active.title,
                        sheets={name: [[c.value for c in row] for row in book[name].iter_rows()] for name in book.sheetnames})
        finally:
            book.close()

    def assert_report_layout(self, report):
        """보이는 시트 셋과 숨김 처리내역(spec R6-1). 파일을 열면 첫 시트가 보인다."""
        self.assertEqual(report["names"], REPORT_SHEETS)
        self.assertEqual(report["states"], {"초과·근접 조항": "visible", "과제별 검토 결과": "visible",
                                            "고시 조항별 상세": "visible", "처리내역": "hidden"})
        self.assertEqual(report["active"], "초과·근접 조항")

    def assert_groups_cover_rows(self, result):
        """모든 행이 정확히 한 묶음에 들고, 종합 건수의 합이 처리한 과제 수(counts.total)와 같다."""
        groups = result["groups"]
        self.assertEqual(list(groups), ["focus", "unjudged", "other"])
        positions = groups["focus"] + groups["unjudged"] + groups["other"]
        self.assertEqual(sorted(positions), list(range(len(result["rows"]))))
        self.assertEqual(sum(entry["count"] for entry in result["tally"]), result["counts"]["total"])
        self.assertEqual(result["counts"]["total"], len(result["rows"]))
        # 묶음은 그 행의 간단한 결과가 말하는 묶음과 같다(화면은 groups만 보고 그린다).
        for name, members in groups.items():
            self.assertEqual([result["rows"][i]["brief"]["group"] for i in members], [name] * len(members))
        # 종합 건수를 눌렀을 때 보일 과제(tally_members): 항목마다 길이가 그 건수와 같고, 모든 행이 정확히 한 항목에 든다.
        picked = result["tally_members"]
        self.assertEqual(list(picked), ["over", "near", "under", "unjudged"])
        self.assertEqual(sorted(i for members in picked.values() for i in members), list(range(len(result["rows"]))))
        for entry in result["tally"]:
            self.assertEqual(len(picked[entry["kind"]]), entry["count"], entry["kind"])
            self.assertEqual({result["rows"][i]["brief"]["overall"] for i in picked[entry["kind"]]} - {"오류", "취소"},
                             {entry["label"]} if entry["kind"] != "unjudged" and entry["count"] else set(), entry["kind"])

    # ── 허용 함수 목록 ─────────────────────────────────────────────────
    def test_public_methods_match_host_and_are_the_only_public_callables(self):
        import app
        self.assertEqual(tuple(app.PUBLIC_METHODS), tuple(bridge_module.PUBLIC_METHODS))
        self.assertEqual(len(set(bridge_module.PUBLIC_METHODS)), len(bridge_module.PUBLIC_METHODS))
        public = {name for name in dir(self.bridge) if not name.startswith("_") and callable(getattr(self.bridge, name))}
        self.assertEqual(public, set(bridge_module.PUBLIC_METHODS))
        for name in ("get_initial_state", "select_path", "extract_attachment", "estimate", "run_single", "read_batch",
                     "run_batch", "cancel", "poll_progress", "save_report", "save_template", "get_key_state",
                     "save_key", "delete_key", "set_model_settings"):
            self.assertIn(name, bridge_module.PUBLIC_METHODS)

    def test_wrong_arity_and_wrong_types_are_safe_envelopes(self):
        for name in bridge_module.PUBLIC_METHODS:
            self.refused(getattr(self.bridge, name)({"unexpected": 1}, [], None, {}, False, 7))
        self.refused(self.bridge.select_path(5), "validation")
        self.refused(self.bridge.estimate("advanced", False, 1), "validation")
        self.refused(self.bridge.run_single("과제", ["advanced"]), "validation")
        self.refused(self.bridge.poll_progress("0"), "validation")

    # ── 초기 상태·키 ──────────────────────────────────────────────────
    def test_initial_state_shape_without_key_text(self):
        data = self.ok(self.bridge.get_initial_state())
        self.assertEqual(data["program"]["name"], pipeline.PROGRAM_NAME)
        self.assertEqual(data["program"]["version"], pipeline.PROGRAM_VERSION)
        self.assertEqual(data["catalogue"]["catalogue_id"], "synthetic")
        self.assertEqual(data["catalogue"]["fingerprint"], "0" * 64)
        self.assertEqual(data["table"]["fingerprint"], TABLE.fingerprint)
        self.assertEqual(data["table"]["near_percent"], str(je.NEAR_PERCENT))
        self.assertEqual([f["id"] for f in data["families"]], list(pipeline.FAMILY_ORDER))
        self.assertEqual([f["label"] for f in data["families"]],
                         ["국가첨단전략기술", "국가핵심기술", "전략물자(이중용도)", "전략물자(군용)"])
        self.assertEqual(data["program"], dict(name="연구보안 등급분류 분류기준(고시) 검토", version="1.4.2"))
        self.assertEqual(data["families"][0]["count"], 2)
        self.assertEqual([p["id"] for p in data["providers"]], ["claude", "openai", "ollama", "lmstudio"])
        self.assertTrue(all(p["default_model"] for p in data["providers"]))
        self.assertEqual(data["key_state"]["claude"]["has_key"], True)
        self.assertEqual(data["key_state"]["openai"]["has_key"], False)
        self.assertEqual(set(data["key_state"]["claude"]), {"provider", "has_key", "stored", "source", "warning"})
        self.assertEqual(data["settings"], dict(provider="claude", model="claude-sonnet-5-5", base_url=""))
        # 화면 맨 아래 한 줄은 그대로 나온다(결과에서 공통 안내를 빼도 이 줄은 남는다).
        self.assertEqual(data["note"], bridge_module.NOTE_TEXT)
        self.assertEqual(data["note"], FOOTER_NOTE)
        self.assertEqual(data["supported_extensions"], [".hwpx", ".docx", ".pdf"])
        self.assertEqual(data["job"]["state"], "idle")

    def test_key_save_delete_and_failures_never_return_key_text(self):
        data = self.ok(self.bridge.save_key("openai", SECRET + "-openai"))
        self.assertEqual(data["provider"], "openai")
        self.assertIs(data["has_key"], True)
        self.assertIs(data["stored"], True)
        self.assertEqual(self.backend.values["openai"], SECRET + "-openai")
        state = self.ok(self.bridge.get_key_state())
        self.assertEqual(set(state), {"claude", "openai"})
        self.assertIs(state["openai"]["has_key"], True)
        data = self.ok(self.bridge.delete_key("openai"))
        self.assertIs(data["has_key"], False)
        self.assertNotIn("openai", self.backend.values)
        # 마스킹 값·빈 값·지원하지 않는 제공자는 거부한다.
        self.refused(self.bridge.save_key("openai", "****"), "validation")
        self.refused(self.bridge.save_key("openai", ""), "validation")
        self.refused(self.bridge.save_key("ollama", "x"), "validation")
        self.refused(self.bridge.delete_key("lmstudio"), "validation")
        # 저장소 오류는 고정 문구로만 보인다.
        self.backend.fail.add("set")
        response = self.refused(self.bridge.save_key("openai", SECRET + "-again"), "credential")
        self.assertNotIn("native credential error", response["message"])
        self.backend.fail.add("get")
        self.ok(self.bridge.get_key_state())

    def test_run_single_without_key_is_refused_before_any_client(self):
        self.backend.values.clear()
        self.refused(self.bridge.run_single(task("합성"), ALL_FAMILIES), "credential")
        self.assertEqual(self.client_keys, [])
        self.assertEqual(self.ok(self.bridge.poll_progress(0))["state"], "idle")

    # ── 경로 토큰 ─────────────────────────────────────────────────────
    def test_select_path_returns_tokens_and_cancellation(self):
        token = self.token("attachment")
        self.assertNotEqual(token, self.token("attachment"))
        self.selected["batch_input"] = None
        data = self.ok(self.bridge.select_path("batch_input"))
        self.assertEqual(data, dict(cancelled=True, token=None, name=None))
        self.refused(self.bridge.select_path("anything"), "validation")
        self.refused(self.make_bridge(path_selector=None).select_path("attachment"), "runtime")

    def test_raw_paths_and_wrong_kind_tokens_are_rejected(self):
        for raw in (str(self.attachment), self.attachment.as_posix(), "", None, 3):
            self.refused(self.bridge.extract_attachment(raw), "validation")
            self.refused(self.bridge.read_batch(raw), "validation")
            self.refused(self.bridge.run_batch(raw, ALL_FAMILIES), "validation")
            self.refused(self.bridge.save_template(raw), "validation")
            self.refused(self.bridge.save_report(raw, "single"), "validation")
        self.assertEqual(self.extract_calls, [])
        attachment = self.token("attachment")
        self.refused(self.bridge.read_batch(attachment), "validation")
        self.refused(self.bridge.save_template(attachment), "validation")
        self.refused(self.bridge.save_report(attachment, "single"), "validation")
        self.refused(self.bridge.extract_attachment(self.token("save_report")), "validation")
        # 다른 브리지의 토큰은 통하지 않는다.
        other = self.make_bridge()
        self.refused(other.extract_attachment(attachment), "validation")
        self.assertEqual(self.extract_calls, [])
        self.assertEqual(self.written, [])

    # ── 첨부 글 꺼내기 ─────────────────────────────────────────────────
    def test_extract_attachment_returns_text_sections_and_warnings(self):
        data = self.ok(self.bridge.extract_attachment(self.token("attachment")))
        self.assertEqual(self.extract_calls, [self.attachment])
        self.assertEqual(data["name"], "계획서.hwpx")
        self.assertEqual(data["kind"], "hwpx")
        self.assertEqual(data["warnings"], ["그림 2건 제외"])
        self.assertIsNone(data["page_count"])
        self.assertIn("최종 목표", data["text"])
        self.assertEqual(len(data["sections"]), 1)
        self.assertEqual(data["sections"][0]["heading"], "2. 최종 목표")
        self.assertEqual(data["sections"][0]["body"], data["text"][data["sections"][0]["start"]:data["sections"][0]["end"]])
        self.assertEqual(data["text_length"], len(data["text"]))

    def test_extract_attachment_reports_failure_reason(self):
        def failing(path):
            raise DocumentError("encrypted", f"암호가 걸린 파일: {Path(path).name}")
        bridge = self.make_bridge(extractor=failing)
        response = self.refused(bridge.extract_attachment(self.token("attachment", bridge)), "encrypted")
        self.assertIn("암호", response["message"])
        # 실제 추출기: HWP는 지원하지 않는 형식으로 거부한다.
        hwp = self.root / "예전.hwp"
        hwp.write_bytes(b"\xd0\xcf\x11\xe0")
        self.selected["attachment"] = hwp
        real = self.make_bridge(extractor=None)
        response = self.refused(real.extract_attachment(self.token("attachment", real)), "unsupported_format")
        self.assertIn("지원하지 않는 형식", response["message"])
        # 없는 파일은 not_found.
        self.selected["attachment"] = self.root / "없음.pdf"
        token = self.ok(real.select_path("attachment"))
        self.assertIs(token["cancelled"], False)
        self.refused(real.extract_attachment(token["token"]), "not_found")

    # ── 예상 호출 수 ──────────────────────────────────────────────────
    def test_estimate_matches_ai_stages(self):
        low, high = estimate_calls(["advanced", "dual_use"], TABLE)
        data = self.ok(self.bridge.estimate(["advanced", "dual_use"], False, 1))
        self.assertEqual(data, dict(families=["advanced", "dual_use"], count=1, per_task=[low, high], total=[low, high]))
        data = self.ok(self.bridge.estimate(["advanced", "dual_use", "advanced"], True, 3))
        self.assertEqual(data["families"], ["advanced", "dual_use"])
        self.assertEqual(data["total"], [low * 3, high * 3])
        self.refused(self.bridge.estimate([], False, 1), "validation")
        self.refused(self.bridge.estimate(["unknown"], False, 1), "validation")
        self.refused(self.bridge.estimate(["advanced"], True, 0), "validation")

    # ── 한 건 판정 ─────────────────────────────────────────────────────
    def test_run_single_passes_confirmed_excerpt_and_returns_display_result(self):
        single = task(TASK["title"], excerpt=EXCERPT, attachment_name="계획서.hwpx", rnd_stage="응용연구", gov_fund="1,250.5")
        data = self.ok(self.bridge.run_single(single, ALL_FAMILIES))
        self.assertEqual(data["state"], "running")
        self.assertEqual(data["kind"], "single")
        job = self.wait()
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["kind"], "single")
        result = job["result"]
        self.assertEqual(result["status"], pipeline.STATUS_DONE)
        self.assertNotIn("task_no", result)
        self.assertIsNone(result["row_number"])
        self.assertEqual(result["rnd_stage"], "응용연구")
        self.assertEqual(result["gov_fund"], "1250.5")
        self.assertEqual(result["option_warnings"], [])
        self.assertEqual(result["input_description"], "과제요약정보; 계획서.hwpx")
        self.assertEqual(result["overall"], "초과")
        self.assertEqual(result["families"]["advanced"], "초과")
        self.assertIn("comparisons", result["judge"])
        self.assertEqual(result["calls"]["total"], 3)
        self.assertEqual(result["run"]["provider"], "claude")
        self.assertEqual(result["run"]["model"], "claude-sonnet-5-5")
        self.assertEqual(result["run"]["families"], ALL_FAMILIES)
        self.assertEqual(result["run"]["near_percent"], str(je.NEAR_PERCENT))
        self.assertEqual(result["run"]["table_fingerprint"], TABLE.fingerprint)
        # 발췌와 요약이 그대로 AI 요청에 들어갔다(키는 클라이언트 생성에만 쓰인다).
        self.assertEqual(self.client_keys[-1][1], SECRET)
        self.assertEqual(self.client_keys[-1][0]["provider"], "claude")
        # 진행 이벤트는 순번이 오르고 단계 이름이 명사형이다.
        events = job["events"]
        self.assertTrue(events)
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(any("최종목표 사양 추출" in e["label"] for e in events))
        self.assertTrue(any("관련 고시 조항 선별" in e["label"] for e in events))
        self.assertFalse(any("목표 수치 추출" in e["label"] or "후보 조항" in e["label"] for e in events))
        self.assertTrue(any(e["label"] == "검토 완료" for e in events))
        # 연구개발단계·지원금은 AI 요청에 들어가지 않는다.
        for request in self.models[-1].requests:
            for forbidden in ("응용연구", "1250", "연구개발단계", "정부지원연구개발비"):
                self.assertNotIn(forbidden, request["user"] + request["system"])
        self.assertTrue(all(set(e) == {"sequence", "stage", "label", "message", "completed", "total"} for e in events))
        self.assertTrue(all(not e["label"].endswith(("다.", "요.")) for e in events))
        # 이후 순번만 받는다.
        later = self.ok(self.bridge.poll_progress(events[-1]["sequence"]))
        self.assertEqual(later["events"], [])
        self.assertEqual(later["state"], "done")

    def test_run_single_validation_and_family_rules(self):
        self.refused(self.bridge.run_single(task(""), ALL_FAMILIES), "validation")
        self.refused(self.bridge.run_single(dict(title="과제", excerpt=""), ALL_FAMILIES), "validation")
        self.refused(self.bridge.run_single(task("과제"), []), "validation")
        self.refused(self.bridge.run_single(task("과제"), ["x"]), "validation")
        self.refused(self.bridge.run_single(task("과제", extra="1"), ALL_FAMILIES), "validation")
        self.refused(self.bridge.run_single(task("과제", final_goal=5), ALL_FAMILIES), "validation")
        self.refused(self.bridge.run_single(task("과제", gov_fund=1250), ALL_FAMILIES), "validation")
        # 옛 입력 키(과제번호·과제요약)는 받지 않는다.
        self.refused(self.bridge.run_single(task("과제", number="S-001"), ALL_FAMILIES), "validation")
        self.refused(self.bridge.run_single(dict(title="과제", summary="요약"), ALL_FAMILIES), "validation")
        self.assertEqual(self.client_keys, [])
        self.assertEqual(self.ok(self.bridge.poll_progress(0))["state"], "idle")

    def test_single_start_condition(self):
        # 확인한 발췌 없음 + 세 칸 중 하나 빈칸 → 거부(첨부를 골랐어도).
        for key in ("final_goal", "rnd_content", "utilization"):
            self.refused(self.bridge.run_single(task("과제", **{key: ""}), ALL_FAMILIES), "validation")
            self.refused(self.bridge.run_single(task("과제", **{key: " "}, excerpt="", attachment_name="계획서.hwpx"),
                                                ALL_FAMILIES), "validation")
        # 연구개발과제명 없음 → 거부(발췌가 있어도).
        self.refused(self.bridge.run_single(dict(title=" ", excerpt=EXCERPT, attachment_name="계획서.hwpx"), ALL_FAMILIES),
                     "validation")
        self.assertEqual(self.client_keys, [])
        # 세 칸 모두 빈칸 + 확인한 발췌 → 허용.
        self.ok(self.bridge.run_single(dict(title="발췌만", final_goal="", rnd_content="", utilization="", excerpt=EXCERPT,
                                            attachment_name="계획서.hwpx"), ALL_FAMILIES))
        result = self.wait()["result"]
        self.assertEqual(result["status"], pipeline.STATUS_DONE)
        self.assertEqual(result["input_description"], "계획서.hwpx")
        # 세 칸 모두 있음 + 발췌를 확인하지 않은 첨부 → 허용, 파일 이름은 '입력 정보'에 나오지 않는다.
        self.ok(self.bridge.run_single(task("첨부 미확인", excerpt="", attachment_name="계획서.hwpx"), ALL_FAMILIES))
        result = self.wait()["result"]
        self.assertEqual(result["input_description"], "과제요약정보")
        self.assertNotIn("계획서", json.dumps(result, ensure_ascii=False))

    def test_unconfirmed_attachment_adds_no_file_warnings(self):
        self.ok(self.bridge.extract_attachment(self.token("attachment")))
        self.ok(self.bridge.run_single(task("첨부 미확인", excerpt="", attachment_name="계획서.hwpx"), ALL_FAMILIES))
        self.wait()
        self.ok(self.bridge.save_report(self.token("save_report"), "single"))
        self.assertEqual(self.written[-1]["run_info"]["file_warnings"], [])
        self.ok(self.bridge.run_single(task("첨부 확인", excerpt=EXCERPT, attachment_name="계획서.hwpx"), ALL_FAMILIES))
        self.wait()
        self.ok(self.bridge.save_report(self.token("save_report"), "single"))
        self.assertEqual(self.written[-1]["run_info"]["file_warnings"], ["그림 2건 제외"])

    def test_single_optional_fields_are_cleaned_with_warnings(self):
        data = self.ok(self.bridge.run_single(task("선택 칸", rnd_stage="기초", gov_fund="약 3억"), ALL_FAMILIES))
        # 시작 응답에 경고가 실려 화면이 그 칸 아래에 안내를 보인다(검토는 막지 않는다).
        self.assertEqual(data["option_warnings"], [dict(row_number=None, field="정부지원연구개발비", value="약 3억",
                                                        message="정부지원연구개발비 값 확인 필요 — 약 3억")])
        self.assertEqual(data["state"], "running")
        result = self.wait()["result"]
        self.assertEqual(result["status"], pipeline.STATUS_DONE)
        self.assertEqual(result["rnd_stage"], "기초연구")
        self.assertEqual(result["gov_fund"], "")
        self.assertEqual([w["message"] for w in result["option_warnings"]], ["정부지원연구개발비 값 확인 필요 — 약 3억"])
        for fund, shown in (("0", "0"), ("-12", "-12"), ("1e3", "1e3")):
            data = self.ok(self.bridge.run_single(task("지원금 " + fund, gov_fund=fund), ALL_FAMILIES))
            self.assertEqual([w["value"] for w in data["option_warnings"]], [shown])
            self.assertEqual(self.wait()["result"]["gov_fund"], "")
        data = self.ok(self.bridge.run_single(task("단계 잘못", rnd_stage="상용화", gov_fund="2,000"), ALL_FAMILIES))
        self.assertEqual([w["message"] for w in data["option_warnings"]], ["연구개발단계 값 확인 필요 — 상용화"])
        result = self.wait()["result"]
        self.assertEqual((result["rnd_stage"], result["gov_fund"]), ("", "2000"))

    def test_single_fund_warning_reaches_report_log(self):
        real = self.make_bridge(report_writer=None)
        self.ok(real.run_single(task("엑셀 경고", gov_fund="많음"), ALL_FAMILIES))
        self.wait(real)
        self.ok(real.save_report(self.token("save_report", real), "single"))
        from openpyxl import load_workbook
        book = load_workbook(self.report_path)
        rows = [[c.value for c in row] for row in book["처리내역"].iter_rows()]
        summary = [[c.value for c in row] for row in book["과제별 검토 결과"].iter_rows()]
        book.close()
        self.assertIn(["선택 칸 경고 건수", 1], rows)
        self.assertIn(["선택 칸 경고", "정부지원연구개발비 값 확인 필요 — 많음"], rows)
        header = summary[0]
        self.assertIsNone(summary[1][header.index("정부지원연구개발비(백만원)")])
        self.assertIsNone(summary[1][header.index("입력 행 번호")])

    def test_second_start_is_refused_while_running_and_cancel_keeps_no_result(self):
        batch_token, report_token = self.token("batch_input"), self.token("save_report")
        self.gate = threading.Event()
        self.ok(self.bridge.run_single(task("합성 A"), ALL_FAMILIES))
        time.sleep(.05)
        self.refused(self.bridge.run_single(task("합성 B"), ALL_FAMILIES), "busy")
        self.refused(self.bridge.run_batch(batch_token, ALL_FAMILIES), "busy")
        self.refused(self.bridge.save_report(report_token, "single"), "busy")
        self.refused(self.bridge.select_path("attachment"), "busy")
        self.refused(self.bridge.extract_attachment("not-a-token"), "busy")
        self.assertEqual(self.ok(self.bridge.poll_progress(0))["state"], "running")
        data = self.ok(self.bridge.cancel())
        self.assertEqual(data["state"], "cancelling")
        self.gate.set()
        job = self.wait()
        self.assertEqual(job["state"], "cancelled")
        self.assertIsNone(job["result"])
        self.assertTrue(any("취소" in e["message"] for e in job["events"]))
        self.refused(self.bridge.save_report(self.token("save_report"), "single"), "not_found")
        # 다음 작업은 받는다.
        self.gate = None
        self.ok(self.bridge.run_single(task("합성 C"), ALL_FAMILIES))
        self.assertEqual(self.wait()["state"], "done")
        self.assertEqual(self.ok(self.bridge.cancel())["state"], "done")

    def test_engine_exception_becomes_safe_failed_job(self):
        def boom(*args, **kwargs):
            raise RuntimeError("engine boom " + SECRET)
        bridge = self.make_bridge(task_runner=boom)
        self.ok(bridge.run_single(task("합성"), ALL_FAMILIES))
        job = self.wait(bridge)
        self.assertEqual(job["state"], "failed")
        self.assertIsNone(job["result"])
        self.assertIsInstance(job["message"], str)
        self.assertNotIn("engine boom", job["message"])
        self.assertNotIn(SECRET, json.dumps(job, ensure_ascii=False))

    def test_pipeline_error_status_is_a_done_job_with_error_result(self):
        from llm_client import AuthenticationError

        class Broken:
            # llm_client의 예외는 코드만 담는다(응답 본문·키 없음).
            def ask_json(self, *args, **kwargs):
                raise AuthenticationError()
        bridge = self.make_bridge(client_factory=lambda settings, key: Broken())
        self.ok(bridge.run_single(task("합성"), ALL_FAMILIES))
        job = self.wait(bridge)
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result"]["status"], pipeline.STATUS_ERROR)
        self.assertIn("model_authentication_failed", job["result"]["error_reason"])
        self.assertNotIn(SECRET, json.dumps(job, ensure_ascii=False))

    # ── 결과 저장 ─────────────────────────────────────────────────────
    def test_save_report_calls_excel_report_with_single_result_and_run_info(self):
        self.refused(self.bridge.save_report(self.token("save_report"), "single"), "not_found")
        self.ok(self.bridge.run_single(task("합성"), ["advanced", "core"]))
        self.wait()
        data = self.ok(self.bridge.save_report(self.token("save_report"), "single"))
        self.assertEqual(data, dict(saved=True, name="결과.xlsx", which="single", count=1))
        self.assertEqual(len(self.written), 1)
        call = self.written[0]
        self.assertEqual(call["path"], self.report_path)
        self.assertEqual(len(call["results"]), 1)
        self.assertEqual(call["results"][0]["title"], "합성")
        info = call["run_info"]
        self.assertEqual(info["catalogue_id"], "synthetic")
        self.assertEqual(info["catalogue_fingerprint"], "0" * 64)
        self.assertEqual(info["table_fingerprint"], TABLE.fingerprint)
        self.assertEqual(info["provider"], "claude")
        self.assertEqual(info["model"], "claude-sonnet-5-5")
        self.assertEqual(info["near_percent"], str(je.NEAR_PERCENT))
        self.assertEqual(info["families"], ["advanced", "core"])
        self.assertEqual(info["excluded"], [])
        self.assertNotIn(SECRET, json.dumps(info, ensure_ascii=False))
        self.refused(self.bridge.save_report(self.token("save_report"), "batch"), "not_found")
        self.refused(self.bridge.save_report(self.token("save_report"), "other"), "validation")

    def test_save_report_io_failure_is_safe(self):
        def failing(path, results, run_info=None):
            raise OSError("permission " + SECRET)
        bridge = self.make_bridge(report_writer=failing)
        self.ok(bridge.run_single(task("합성"), ALL_FAMILIES))
        self.wait(bridge)
        response = self.refused(bridge.save_report(self.token("save_report", bridge), "single"), "io")
        self.assertNotIn("permission", response["message"])

    def test_save_template_calls_batch_template(self):
        data = self.ok(self.bridge.save_template(self.token("save_template")))
        self.assertEqual(data, dict(saved=True, name="양식.xlsx"))
        self.assertEqual(self.templates, [self.template_path])
        # 실제 양식 함수로도 저장된다.
        real = self.make_bridge(template_maker=None)
        self.selected["save_template"] = self.root / "실제양식.xlsx"
        self.ok(real.save_template(self.token("save_template", real)))
        self.assertEqual(batch.read_batch_input(self.root / "실제양식.xlsx")["rows"], [])

    # ── 일괄 판정 ─────────────────────────────────────────────────────
    def test_read_batch_reports_excluded_rows_and_run_batch_counts(self):
        self.write_batch_input([
            ["합성 과제 하나", FINAL_GOAL, CONTENT, UTILIZATION, "개발", "1,500"],
            ["", "목표만", "내용", "활용", None, None],
            ["(예시) 보기", "예시", "예시", "예시", None, None],
            ["합성 과제 둘", "최종 목표 수치 없음", "내용", "활용", "상용화", "약 3억"],
        ])
        token = self.token("batch_input")
        data = self.ok(self.bridge.read_batch(token))
        self.assertEqual(data["name"], "입력.xlsx")
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["total_rows"], 4)
        self.assertEqual(data["blank_rows"], 0)
        self.assertEqual([r["reason"] for r in data["excluded"]], ["필수 칸 빈칸: 연구개발과제명", batch.REASON_EXAMPLE])
        self.assertEqual([r["row_number"] for r in data["rows"]], [2, 5])
        self.assertEqual(data["rows"][0], dict(row_number=2, title="합성 과제 하나", rnd_stage="개발연구"))
        self.assertEqual([w["message"] for w in data["option_warnings"]],
                         ["5행: 연구개발단계 값 확인 필요 — 상용화", "5행: 정부지원연구개발비 값 확인 필요 — 약 3억"])
        preview = self.ok(self.bridge.estimate(["advanced"], True, data["count"]))
        self.assertEqual(preview["count"], 2)

        self.ok(self.bridge.run_batch(token, ALL_FAMILIES))
        job = self.wait()
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["kind"], "batch")
        result = job["result"]
        self.assertEqual(result["counts"]["total"], 2)
        self.assertEqual(result["counts"]["done"], 1)
        self.assertEqual(result["counts"]["no_facts"], 1)
        self.assertEqual(result["counts"]["error"], 0)
        self.assertEqual(result["counts"]["cancelled"], 0)
        self.assertEqual(result["counts"]["excluded"], 2)
        self.assertEqual(result["counts"]["option_warnings"], 2)
        self.assertEqual(len(result["option_warnings"]), 2)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["row_number"], 2)
        self.assertEqual(result["rows"][0]["rnd_stage"], "개발연구")
        self.assertEqual(result["rows"][0]["gov_fund"], "1500")
        self.assertNotIn("task_no", result["rows"][0])
        self.assertEqual(result["rows"][0]["status"], pipeline.STATUS_DONE)
        self.assertEqual(result["rows"][1]["status"], pipeline.STATUS_NO_FACTS)
        self.assertNotIn("judge", result["rows"][0])
        # 기존 건수 줄과 요약 행의 키는 그대로이고, 종합 건수는 완료 1건(초과)·목표 수치 없음 1건(미달)이다.
        self.assertEqual(set(result), BATCH_RESULT_KEYS)
        self.assertEqual(set(result["counts"]), BATCH_COUNT_KEYS)
        self.assertTrue(all(set(row) == BATCH_ROW_KEYS for row in result["rows"]))
        self.assertEqual(tally_of(result), [("over", "고시 사양 초과", 1), ("near", "고시 사양 근접", 0),
                                            ("under", "고시 사양 미달", 1)])
        self.assertEqual(result["groups"], dict(focus=[0], unjudged=[], other=[1]))
        self.assert_groups_cover_rows(result)
        self.assertEqual(set(result["run"]), {"provider", "model", "families", "run_time"})
        self.assertTrue(any(e["stage"] == "batch" for e in job["events"]))
        # 저장: 결과 2건과 제외 행이 run_info로 간다.
        saved = self.ok(self.bridge.save_report(self.token("save_report"), "batch"))
        self.assertEqual(saved["count"], 2)
        call = self.written[-1]
        self.assertEqual(len(call["results"]), 2)
        self.assertEqual(len(call["run_info"]["excluded"]), 2)
        self.assertEqual(len(call["run_info"]["option_warnings"]), 2)
        self.assertEqual(call["run_info"]["families"], ALL_FAMILIES)
        self.assertTrue(any(e["label"].startswith("일괄 검토 중") for e in job["events"]))

    def test_read_batch_header_error_and_empty_input(self):
        self.write_batch_input([])
        token = self.token("batch_input")
        data = self.ok(self.bridge.read_batch(token))
        self.assertEqual(data["count"], 0)
        self.refused(self.bridge.run_batch(token, ALL_FAMILIES), "validation")
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(["이름", "내용"])
        book.save(self.batch_input)
        token = self.token("batch_input")
        response = self.refused(self.bridge.read_batch(token), "input")
        self.assertIn("머리글", response["message"])
        self.assertIn("연구개발과제명", response["message"])
        self.refused(self.bridge.run_batch(token, ALL_FAMILIES), "input")

    def test_batch_cancel_keeps_finished_rows_and_marks_rest_cancelled(self):
        self.write_batch_input([[f"합성 과제 {i}", FINAL_GOAL, CONTENT, UTILIZATION, None, None] for i in range(1, 7)])
        token = self.token("batch_input")
        self.ok(self.bridge.read_batch(token))
        self.gate = threading.Event()
        self.ok(self.bridge.run_batch(token, ALL_FAMILIES))
        time.sleep(.05)
        self.refused(self.bridge.run_single(task("x"), ALL_FAMILIES), "busy")
        self.assertEqual(self.ok(self.bridge.cancel())["state"], "cancelling")
        self.gate.set()
        job = self.wait()
        self.assertEqual(job["state"], "cancelled")
        counts = job["result"]["counts"]
        self.assertEqual(counts["total"], 6)
        self.assertEqual(counts["done"] + counts["cancelled"] + counts["error"], 6)
        self.assertGreaterEqual(counts["cancelled"], 1)
        # 취소 뒤 AI 요청이 거부된 행은 '오류'가 아니라 '취소'다(가짜 실행기는 취소 전에 끝난 행이 없다).
        self.assertEqual(counts["error"], 0)
        self.assertEqual(counts["cancelled"], 6)
        # 취소된 행은 어떤 건수에서도 미달이 아니다: 종합 건수의 '오류·취소(판정 없음)'와 판정 못 함 묶음에 든다.
        result = job["result"]
        self.assertEqual(tally_of(result), [("over", "고시 사양 초과", 0), ("near", "고시 사양 근접", 0),
                                            ("under", "고시 사양 미달", 0), ("unjudged", "오류·취소(판정 없음)", 6)])
        self.assertEqual(result["groups"], dict(focus=[], unjudged=[0, 1, 2, 3, 4, 5], other=[]))
        self.assert_groups_cover_rows(result)
        self.assertEqual(result["unjudged_label"], UNJUDGED_LABEL.format(0, 6))
        self.assertEqual((result["focus_label"], result["focus_empty_message"], result["other_label"]),
                         (FOCUS_LABEL.format(0), FOCUS_EMPTY, ""))
        saved = self.ok(self.bridge.save_report(self.token("save_report"), "batch"))
        self.assertEqual(saved["count"], 6)

    def test_batch_cancel_keeps_finished_verdicts_and_puts_unstarted_rows_in_unjudged(self):
        # 일괄 취소(spec 10절): 끝난 과제는 판정대로, 시작하지 않은 행은 '취소'로 판정 못 함 묶음에 든다.
        self.write_goal_rows([("합성 과제 끝남", goal(14)), ("합성 과제 " + WAIT_MARK, goal(14)),
                              ("합성 과제 뒤 하나", goal(14)), ("합성 과제 뒤 둘", goal(20))])
        gate = threading.Event()
        self.addCleanup(gate.set)
        bridge = self.make_bridge(client_factory=self.marked_factory(gate), workers=1)
        token = self.token("batch_input", bridge)
        self.ok(bridge.read_batch(token))
        self.ok(bridge.run_batch(token, ALL_FAMILIES))
        deadline = time.monotonic() + 8
        while self.ok(bridge.poll_progress(0))["completed"] < 1:      # 첫 행이 끝날 때까지(둘째 행은 gate에서 기다린다)
            self.assertLess(time.monotonic(), deadline, "첫 행이 끝나지 않음")
            time.sleep(.005)
        self.assertEqual(self.ok(bridge.cancel())["state"], "cancelling")
        gate.set()
        job = self.wait(bridge)
        self.assertEqual(job["state"], "cancelled")
        result = job["result"]
        self.assertEqual([row["status"] for row in result["rows"]],
                         [pipeline.STATUS_DONE] + [pipeline.STATUS_CANCELLED] * 3)
        self.assertEqual((result["counts"]["total"], result["counts"]["done"], result["counts"]["cancelled"],
                          result["counts"]["error"]), (4, 1, 3, 0))
        self.assertEqual(tally_of(result), [("over", "고시 사양 초과", 1), ("near", "고시 사양 근접", 0),
                                            ("under", "고시 사양 미달", 0), ("unjudged", "오류·취소(판정 없음)", 3)])
        self.assertEqual(result["groups"], dict(focus=[0], unjudged=[1, 2, 3], other=[]))
        self.assert_groups_cover_rows(result)
        self.assertEqual((result["focus_label"], result["focus_empty_message"], result["unjudged_label"],
                          result["other_label"]), (FOCUS_LABEL.format(1), "", UNJUDGED_LABEL.format(0, 3), ""))
        # 취소된 행의 간단한 결과: 종합 '취소', 사유·빈 경우 글은 빈 글(판정된 것이 아니다).
        for row in result["rows"][1:]:
            self.assertEqual((row["brief"]["overall"], row["brief"]["reason"], row["brief"]["empty_message"]),
                             (brief.VERDICT_CANCELLED, "", ""))
            self.assertEqual((row["brief"]["focus"], row["brief"]["under"], row["brief"]["review"]), ([], [], []))

    # ── 간단한 결과(brief)·검색 엔진·선택 칸 경고(1.3.0) ──────────────────────
    def test_public_method_names_and_arguments_are_unchanged(self):
        expected = {"get_initial_state": [], "select_path": ["kind"], "extract_attachment": ["token"],
                    "estimate": ["families", "is_batch", "row_count"], "run_single": ["task", "families"],
                    "read_batch": ["token"], "run_batch": ["token", "families"], "cancel": [],
                    "poll_progress": ["after_sequence"], "save_report": ["token", "which"], "save_template": ["token"],
                    "get_key_state": [], "save_key": ["provider", "key"], "delete_key": ["provider"],
                    "set_model_settings": ["provider", "model", "base_url"],
                    "search_notices": ["query", "family", "limit", "offset", "similar_offset"],
                    "get_notice_detail": ["clause_id", "query"]}
        self.assertEqual(len(bridge_module.PUBLIC_METHODS), 17)
        self.assertEqual(list(bridge_module.PUBLIC_METHODS), list(expected))
        for name, arguments in expected.items():
            self.assertEqual(list(inspect.signature(getattr(Bridge, name)).parameters)[1:], arguments, name)

    def test_single_passes_the_search_engine_and_option_warnings_and_returns_brief(self):
        engine = RankingSearchEngine()
        runner, calls = recording(pipeline.run_task)
        bridge = self.make_bridge(search_factory=lambda resources: engine, task_runner=runner)
        self.detail_matches = {"advanced:item:002"}
        started = self.ok(bridge.run_single(task("합성 세부 일치", excerpt=EXCERPT, attachment_name="계획서.hwpx", gov_fund="약 3억"),
                                             ALL_FAMILIES))
        job = self.wait(bridge)
        self.assertEqual(job["state"], "done")
        # 03 고시 검색 탭이 쓰는 같은 엔진과, 시작 응답에 실린 선택 칸 경고가 그대로 run_task에 간다.
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0]["search_engine"], engine)
        self.assertIs(bridge._search(), engine)
        self.assertEqual(calls[0]["option_warnings"], started["option_warnings"])
        self.assertEqual(len(started["option_warnings"]), 1)
        result = job["result"]
        summary = result["brief"]
        self.assertEqual(tuple(summary), brief.BRIEF_KEYS)
        self.assertEqual(summary["semantic"], brief.SEMANTIC_USED)
        self.assertEqual(summary["overall"], brief.VERDICT_OVER)
        self.assertEqual((summary["group"], summary["empty_message"]), (brief.GROUP_FOCUS, ""))
        self.assertEqual(summary["reason"], "국가첨단전략기술 16나노 이하급 D램 외 1건")
        # 초과·근접 조항(focus)과 사양 줄은 간단한 결과 그대로 실린다(R7-1 모양). 미달 조항은 없다.
        self.assertEqual([clause["clause_id"] for clause in summary["focus"]], ["advanced:item:001", "dual_use:control:1A003"])
        for clause in summary["focus"]:
            self.assertEqual(tuple(clause), brief.CLAUSE_KEYS)
            self.assertEqual((clause["verdict"], clause["others"], len(clause["lines"])), (brief.VERDICT_OVER, 0, 1))
            self.assertEqual(tuple(clause["lines"][0]), brief.LINE_KEYS)
            self.assertTrue(clause["lines"][0]["display_reason"])
        self.assertEqual(summary["under"], [])
        self.assertEqual([entry["clause_id"] for entry in summary["review"]], ["advanced:item:002"])
        self.assertEqual(summary["review"][0]["kept_because"], brief.KEPT_DETAIL_MATCH)
        self.assertEqual(summary["counts"], dict(over=2, near=0, under=0, review=1, hidden=1, detail_match_dropped=0))
        self.assertEqual(summary["hints"], [TASK_HINT.format(1)])
        # 없어진 키(공통 안내·옛 요약)는 간단한 결과에도, 개별 결과에도 없다.
        for gone in ("notices", "summary_cell", "items"):
            self.assertNotIn(gone, summary)
        # 개별 결과는 과제 결과 그대로다: 더하는 것은 지금처럼 선택 칸 경고와 실행 정보뿐(일괄 결과의 키는 없다).
        self.assertEqual(set(result), set(pipeline.TaskResult().to_dict()) | {"option_warnings", "run"})
        for name in BATCH_ONLY_KEYS:
            self.assertNotIn(name, result)
        self.assertEqual(engine.ranking_calls, 1)
        # 의미 검색을 쓰는 동안 기존 단계 이름으로 진행 글이 보인다(0/1, 1/1 — 화면은 'label · message').
        semantic = [e for e in job["events"] if e["message"] == brief.PROGRESS_MESSAGE]
        self.assertEqual([(e["label"], e["completed"], e["total"]) for e in semantic],
                         [("관련 고시 조항 선별 중", 0, 1), ("관련 고시 조항 선별 중", 1, 1)])
        # 실행 정보의 지문은 실행이 끝난 뒤 값이다(엔진은 처음 쓸 때 불러오므로 시작할 때는 빈 글이었다).
        self.assertEqual((result["run"]["semantic_model_fingerprint"], result["run"]["semantic_vectors_fingerprint"]),
                         (MODEL_FP, VECTORS_FP))
        self.ok(bridge.save_report(self.token("save_report", bridge), "single"))
        written = self.written[-1]
        self.assertEqual((written["run_info"]["semantic_model_fingerprint"], written["run_info"]["semantic_vectors_fingerprint"]),
                         (MODEL_FP, VECTORS_FP))
        self.assertEqual(written["results"][0]["brief"], summary)

    def test_single_without_usable_semantic_search_says_so_and_fingerprints_stay_blank(self):
        self.detail_matches = {"advanced:item:002"}

        def broken(resources):
            raise RuntimeError("search engine boom " + SECRET)
        cases = (("엔진 만들기 실패", broken, None), ("모델 없음", None, RankingSearchEngine(available=False)))
        for name, factory, engine in cases:
            with self.subTest(name):
                bridge = self.make_bridge(search_factory=factory or (lambda resources, engine=engine: engine))
                self.ok(bridge.run_single(task(name, excerpt=EXCERPT), ALL_FAMILIES))
                job = self.wait(bridge)
                self.assertEqual(job["state"], "done")
                summary = job["result"]["brief"]
                self.assertEqual(summary["semantic"], brief.SEMANTIC_UNAVAILABLE)
                self.assertEqual(summary["hints"], [brief.HINT_SEMANTIC_UNAVAILABLE])
                self.assertEqual(summary["review"], [])
                self.assertEqual(summary["counts"]["detail_match_dropped"], 1)
                run = job["result"]["run"]
                self.assertEqual((run["semantic_model_fingerprint"], run["semantic_vectors_fingerprint"]), ("", ""))
                self.ok(bridge.save_report(self.token("save_report", bridge), "single"))
                info = self.written[-1]["run_info"]
                self.assertEqual((info["semantic_model_fingerprint"], info["semantic_vectors_fingerprint"]), ("", ""))
                self.assertNotIn(SECRET, json.dumps(job, ensure_ascii=False))
        self.assertEqual(engine.ranking_calls, 1)
        # 따질 조항이 없으면 엔진을 부르지 않는다(not_needed, 지문은 엔진이 알려 주는 빈 글).
        self.detail_matches = None
        engine = RankingSearchEngine()
        bridge = self.make_bridge(search_factory=lambda resources: engine)
        self.ok(bridge.run_single(task("세부 일치 없음", excerpt=EXCERPT), ALL_FAMILIES))
        result = self.wait(bridge)["result"]
        self.assertEqual(result["brief"]["semantic"], brief.SEMANTIC_NOT_NEEDED)
        self.assertEqual(engine.ranking_calls, 0)
        self.assertEqual((result["run"]["semantic_model_fingerprint"], result["run"]["semantic_vectors_fingerprint"]), ("", ""))

    def test_batch_passes_the_search_engine_and_read_warnings_and_rows_carry_brief(self):
        self.write_batch_input([
            ["합성 과제 하나", FINAL_GOAL, CONTENT, UTILIZATION, "개발", "1,500"],
            ["합성 과제 둘", FINAL_GOAL, CONTENT + " 둘", UTILIZATION, "상용화", None],
            ["합성 과제 셋", FINAL_GOAL, CONTENT + " 셋", UTILIZATION, None, "약 3억"],
        ])
        engine = RankingSearchEngine()
        runner, calls = recording(batch.run_batch)
        bridge = self.make_bridge(search_factory=lambda resources: engine, batch_runner=runner)
        self.detail_matches = {"advanced:item:002"}
        token = self.token("batch_input", bridge)
        read = self.ok(bridge.read_batch(token))
        self.ok(bridge.run_batch(token, ALL_FAMILIES))
        job = self.wait(bridge)
        self.assertEqual(job["state"], "done")
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0]["search_engine"], engine)
        self.assertIs(bridge._search(), engine)
        self.assertEqual(calls[0]["option_warnings"], read["option_warnings"])
        result = job["result"]
        # 실행 전체의 선택 칸 경고 안내 줄은 Python이 만든 글이다. 공통 안내(notices)는 싣지 않는다.
        self.assertEqual(result["hints"], [RUN_HINT.format(2)])
        self.assertEqual(result["hints"], ["선택 칸 경고 2건 — 상세 보기·처리내역(숨김 시트)에서 확인"])
        self.assertNotIn("notices", result)
        self.assertEqual(set(result), BATCH_RESULT_KEYS)
        rows = result["rows"]
        self.assertEqual([r["row_number"] for r in rows], [2, 3, 4])
        for row in rows:
            self.assertEqual(set(row), BATCH_ROW_KEYS)
            self.assertEqual(tuple(row["brief"]), brief.BRIEF_KEYS)
            self.assertEqual(row["brief"]["semantic"], brief.SEMANTIC_USED)
            # 일괄에는 발췌가 없어 두께 수치(발췌 인용)를 버린다: 이중용도 조항은 '추가 검토 필요'로 남는다.
            self.assertEqual([entry["clause_id"] for entry in row["brief"]["review"]],
                             ["advanced:item:002", "dual_use:control:1A003"])
            # 화면이 그리는 초과·근접 조항과 사양 줄, '추가 검토 n건'의 n이 간단한 결과 그대로 실린다.
            self.assertEqual((row["brief"]["overall"], row["brief"]["group"]), (brief.VERDICT_OVER, brief.GROUP_FOCUS))
            self.assertEqual([clause["clause_id"] for clause in row["brief"]["focus"]], ["advanced:item:001"])
            self.assertTrue(all(line["display_reason"] for clause in row["brief"]["focus"] for line in clause["lines"]))
            self.assertEqual(row["brief"]["counts"]["review"], 2)
            for gone in ("notices", "summary_cell", "items"):
                self.assertNotIn(gone, row["brief"])
            self.assertNotIn("judge", row)
        self.assertEqual(tally_of(result), [("over", "고시 사양 초과", 3), ("near", "고시 사양 근접", 0),
                                            ("under", "고시 사양 미달", 0)])
        self.assertEqual(result["groups"], dict(focus=[0, 1, 2], unjudged=[], other=[]))
        self.assert_groups_cover_rows(result)
        dropped = "버린 최종목표 사양·매핑 1건"
        self.assertEqual([r["brief"]["hints"] for r in rows],
                         [[dropped + " — 상세 보기에서 확인"], [f"{dropped} · " + TASK_HINT.format(1)],
                          [f"{dropped} · " + TASK_HINT.format(1)]])
        self.assertEqual(engine.ranking_calls, 3)
        self.ok(bridge.save_report(self.token("save_report", bridge), "batch"))
        written = self.written[-1]
        self.assertEqual((written["run_info"]["semantic_model_fingerprint"], written["run_info"]["semantic_vectors_fingerprint"]),
                         (MODEL_FP, VECTORS_FP))
        self.assertEqual([r["brief"] for r in written["results"]], [r["brief"] for r in rows])

    def test_batch_hint_line_counts_every_option_warning_and_is_absent_without_warnings(self):
        self.write_batch_input([["합성 과제 하나", FINAL_GOAL, CONTENT, UTILIZATION, "개발", "1,500"]])
        token = self.token("batch_input")
        self.ok(self.bridge.read_batch(token))
        self.ok(self.bridge.run_batch(token, ALL_FAMILIES))
        result = self.wait()["result"]
        self.assertEqual(result["hints"], [])
        self.assertNotIn("notices", result)
        # 오류·취소가 없으면 종합 건수에 그 항목이 없고, 0건인 묶음의 제목은 빈 글이다(화면이 그 묶음을 숨긴다).
        self.assertEqual([entry["kind"] for entry in result["tally"]], ["over", "near", "under"])
        self.assertEqual((result["focus_label"], result["focus_empty_message"], result["unjudged_label"],
                          result["other_label"]), ("중점 검토 과제 (초과·근접 1건)", "", "", ""))
        # 행이 없는 칸(선택 머리글 없음) 경고도 실행 전체의 선택 칸 경고로 센다. 행에는 나누지 않는다.
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(list(batch.REQUIRED_HEADERS))
        book.active.append(["합성 과제 둘", FINAL_GOAL, CONTENT, UTILIZATION])
        book.save(self.batch_input)
        token = self.token("batch_input")
        read = self.ok(self.bridge.read_batch(token))
        self.assertEqual(len(read["option_warnings"]), 2)
        self.ok(self.bridge.run_batch(token, ALL_FAMILIES))
        job = self.wait()
        result = job["result"]
        self.assertEqual(result["hints"], [RUN_HINT.format(2)])
        self.assertEqual(result["counts"]["option_warnings"], 2)
        self.assertFalse(any("선택 칸 경고" in hint for hint in result["rows"][0]["brief"]["hints"]))
        # 엔진을 쓰지 않은 실행의 지문은 빈 글(합성 엔진에는 지문 속성이 없다).
        self.ok(self.bridge.save_report(self.token("save_report"), "batch"))
        info = self.written[-1]["run_info"]
        self.assertEqual((info["semantic_model_fingerprint"], info["semantic_vectors_fingerprint"]), ("", ""))

    def test_batch_rows_keep_status_specific_brief(self):
        self.write_batch_input([
            ["합성 과제 하나", FINAL_GOAL, CONTENT, UTILIZATION, None, None],
            ["합성 과제 둘", "최종 목표 수치 없음", "내용", "활용", None, None],
        ])
        # 둘째 행 글에는 모의 수치의 인용이 없어 최종목표 사양이 남지 않는다(목표 수치 없음).
        token = self.token("batch_input")
        self.ok(self.bridge.read_batch(token))
        self.ok(self.bridge.run_batch(token, ["advanced", "core"]))
        result = self.wait()["result"]
        rows = result["rows"]
        self.assertEqual([r["status"] for r in rows], [pipeline.STATUS_DONE, pipeline.STATUS_NO_FACTS])
        # 과제 상태와 내부 판정 값은 그대로이고, 목표 수치 없음 과제는 간단한 결과에서만 '고시 사양 미달'로 보인다.
        self.assertEqual(rows[1]["overall"], je.FAMILY_VERDICT_STATUS)
        no_facts = rows[1]["brief"]
        self.assertEqual(tuple(no_facts), brief.BRIEF_KEYS)
        self.assertEqual((no_facts["overall"], no_facts["reason"], no_facts["group"]),
                         ("고시 사양 미달", "최종목표 수치 없음", "other"))
        self.assertEqual(no_facts["families"], dict(advanced=brief.VERDICT_UNDER, core=brief.VERDICT_UNDER,
                                                    dual_use=brief.VERDICT_EXCLUDED, military=brief.VERDICT_EXCLUDED))
        self.assertEqual((no_facts["focus"], no_facts["under"], no_facts["review"], no_facts["empty_message"]),
                         ([], [], [], brief.EMPTY_MESSAGE))
        # 옛 판정 이름 둘은 일괄 결과의 간단한 결과 어디에도 판정 이름으로 나오지 않는다.
        verdicts = [row["brief"]["overall"] for row in rows] + [v for row in rows for v in row["brief"]["families"].values()]
        self.assertFalse({"사양 미달 또는 무관", "최종목표 수치 없음"} & set(verdicts), verdicts)
        self.assertEqual(result["groups"], dict(focus=[0], unjudged=[], other=[1]))
        self.assertEqual((result["focus_label"], result["other_label"], result["unjudged_label"]),
                         (FOCUS_LABEL.format(1), OTHER_LABEL.format(1), ""))

    # ── 일괄 결과의 종합 건수·과제 묶음·묶음 제목 글(1.4.0 spec R4·R7-2) ──────────────
    def test_batch_tally_groups_and_labels_for_a_mixed_run(self):
        self.write_goal_rows([("합성 과제 미달", goal(20)), ("합성 과제 근접", goal(17)),
                              ("합성 과제 " + ERROR_MARK, goal(14)), ("합성 과제 초과 하나", goal(14)),
                              ("합성 과제 수치 없음", "최종 목표 수치 없음"), ("합성 과제 초과 둘", goal(14))])
        bridge = self.make_bridge(client_factory=self.marked_factory(), report_writer=None)
        job = self.run_batch_job(bridge)
        self.assertEqual(job["state"], "done")
        result = job["result"]
        self.assertEqual(set(result), BATCH_RESULT_KEYS)
        rows = result["rows"]
        self.assertEqual([row["status"] for row in rows],
                         [pipeline.STATUS_DONE, pipeline.STATUS_DONE, pipeline.STATUS_ERROR, pipeline.STATUS_DONE,
                          pipeline.STATUS_NO_FACTS, pipeline.STATUS_DONE])
        self.assertEqual([row["brief"]["overall"] for row in rows],
                         ["고시 사양 미달", "고시 사양 근접", "오류", "고시 사양 초과", "고시 사양 미달", "고시 사양 초과"])
        # 종합 건수: R4의 순서와 이름. 오류 과제는 미달에 들지 않고 '오류·취소(판정 없음)'로 따로 센다.
        self.assertEqual(tally_of(result), [("over", "고시 사양 초과", 2), ("near", "고시 사양 근접", 1),
                                            ("under", "고시 사양 미달", 2), ("unjudged", "오류·취소(판정 없음)", 1)])
        # 과제 묶음: rows의 위치(0부터)를 그릴 순서대로. 중점은 종합 초과 → 종합 근접(같으면 입력 순), 나머지는 입력 순.
        self.assertEqual(result["groups"], dict(focus=[3, 5, 1], unjudged=[2], other=[0, 4]))
        self.assert_groups_cover_rows(result)
        # 묶음 제목 글: 중점·그 밖의 수는 종합 건수 함수의 묶음에서, 오류·취소의 수는 기존 건수 줄에서 온다.
        self.assertEqual(result["focus_label"], "중점 검토 과제 (초과·근접 3건)")
        self.assertEqual(result["other_label"], "그 밖의 과제 (고시 사양 미달 2건)")
        self.assertEqual(result["unjudged_label"], "판정하지 못한 과제 (오류 1 · 취소 0)")
        self.assertEqual(result["focus_empty_message"], "")
        self.assertEqual((result["counts"]["total"], result["counts"]["done"], result["counts"]["no_facts"],
                          result["counts"]["error"], result["counts"]["cancelled"]), (6, 4, 1, 1, 0))
        # 종합 건수와 묶음은 종합 건수 함수(brief.tally_briefs)가 같은 간단한 결과로 낸 것과 같다.
        self.assertEqual(dict(tally=result["tally"], groups=result["groups"], members=result["tally_members"]),
                         brief.tally_briefs([row["brief"] for row in rows]))
        self.assertEqual(result["tally_members"], dict(over=[3, 5], near=[1], under=[0, 4], unjudged=[2]))
        # 화면이 쓰는 값: 미달 과제의 사유와 추가 검토 건수, 오류 과제의 오류 사유.
        self.assertEqual([rows[i]["brief"]["reason"] for i in result["groups"]["other"]], ["기준에 못 미침", "최종목표 수치 없음"])
        self.assertEqual([rows[i]["brief"]["counts"]["review"] for i in result["groups"]["other"]], [1, 0])
        self.assertTrue(rows[2]["error_reason"])
        self.assertEqual((rows[2]["brief"]["reason"], rows[2]["brief"]["empty_message"]), ("", ""))
        # 저장한 결과 엑셀: 보이는 시트 셋 + 숨김 처리내역. 종합 결과 줄과 중점 과제 순서가 화면이 받은 것과 같다.
        self.ok(bridge.save_report(self.token("save_report", bridge), "batch"))
        report = self.read_report()
        self.assert_report_layout(report)
        self.assertIn(["종합 결과", brief.tally_text(result["tally"])], [row[:2] for row in report["sheets"]["과제별 검토 결과"]])
        self.assertEqual(brief.tally_text(result["tally"]),
                         "고시 사양 초과 2건 · 고시 사양 근접 1건 · 고시 사양 미달 2건 · 오류·취소(판정 없음) 1건")
        focus_numbers = [row[0] for row in report["sheets"]["초과·근접 조항"][1:]]
        self.assertEqual(list(dict.fromkeys(focus_numbers)), [rows[i]["row_number"] for i in result["groups"]["focus"]])
        self.assertIn(["오류 건수", 1], report["sheets"]["처리내역"])

    def test_batch_without_focus_tasks_says_so_and_hides_empty_groups(self):
        # 초과·근접 과제가 한 건도 없는 실행: 중점 제목은 0건으로 남고 빈 경우 글이 실린다. 오류·취소 항목·묶음은 없다.
        self.write_goal_rows([("합성 과제 수치 없음", "최종 목표 수치 없음"), ("합성 과제 미달", goal(20))])
        result = self.run_batch_job(self.make_bridge(client_factory=self.marked_factory()))["result"]
        self.assertEqual(tally_of(result), [("over", "고시 사양 초과", 0), ("near", "고시 사양 근접", 0),
                                            ("under", "고시 사양 미달", 2)])
        self.assertEqual(result["groups"], dict(focus=[], unjudged=[], other=[0, 1]))
        self.assert_groups_cover_rows(result)
        self.assertEqual(result["focus_label"], "중점 검토 과제 (초과·근접 0건)")
        self.assertEqual(result["focus_empty_message"], "고시 사양을 초과하거나 근접한 과제 없음")
        self.assertEqual((result["other_label"], result["unjudged_label"]), ("그 밖의 과제 (고시 사양 미달 2건)", ""))

    def test_batch_where_every_task_fails_counts_nothing_as_under(self):
        # 전부 오류인 실행(spec 10절): 미달 0건, '오류·취소(판정 없음)' n건, 중점 자리에는 빈 경우 글.
        self.write_goal_rows([("합성 과제 하나 " + ERROR_MARK, goal(14)), ("합성 과제 둘 " + ERROR_MARK, goal(20))])
        bridge = self.make_bridge(client_factory=self.marked_factory(), report_writer=None)
        job = self.run_batch_job(bridge)
        self.assertEqual(job["state"], "done")
        result = job["result"]
        self.assertEqual([row["status"] for row in result["rows"]], [pipeline.STATUS_ERROR] * 2)
        self.assertEqual(brief.tally_text(result["tally"]),
                         "고시 사양 초과 0건 · 고시 사양 근접 0건 · 고시 사양 미달 0건 · 오류·취소(판정 없음) 2건")
        self.assertEqual(result["groups"], dict(focus=[], unjudged=[0, 1], other=[]))
        self.assert_groups_cover_rows(result)
        self.assertEqual((result["focus_label"], result["focus_empty_message"], result["unjudged_label"],
                          result["other_label"]),
                         (FOCUS_LABEL.format(0), FOCUS_EMPTY, "판정하지 못한 과제 (오류 2 · 취소 0)", ""))
        self.assertTrue(all(row["error_reason"] for row in result["rows"]))
        self.ok(bridge.save_report(self.token("save_report", bridge), "batch"))
        report = self.read_report()
        self.assert_report_layout(report)
        self.assertEqual(report["sheets"]["초과·근접 조항"][1][0], "고시 사양을 초과하거나 근접한 조항 없음")

    def test_batch_tally_and_groups_come_from_the_brief_module_unchanged(self):
        # 연결 함수는 판정 이름을 비교해 세지 않는다: 종합 건수 함수가 준 것을 그대로 옮기고 제목 글의 수도 거기서 온다.
        self.write_goal_rows([("합성 과제 하나", goal(14)), ("합성 과제 둘", goal(14))])
        received = []
        fake = dict(tally=[dict(kind="near", label="합성 이름", count=2)], groups=dict(focus=[1, 0], unjudged=[], other=[]),
                    members=dict(over=[], near=[1, 0], under=[], unjudged=[]))

        def tally_briefs(briefs):
            received.append(deepcopy(list(briefs)))
            return deepcopy(fake)
        with mock.patch.object(bridge_module.brief, "tally_briefs", tally_briefs):
            result = self.run_batch_job(self.make_bridge(client_factory=self.marked_factory()))["result"]
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], [row["brief"] for row in result["rows"]])
        self.assertEqual((result["tally"], result["groups"], result["tally_members"]),
                         (fake["tally"], fake["groups"], fake["members"]))
        self.assertEqual((result["focus_label"], result["focus_empty_message"], result["other_label"]),
                         (FOCUS_LABEL.format(2), "", ""))
        source = inspect.getsource(bridge_module)
        self.assertIn("brief.tally_briefs(", source)
        for name in ("VERDICT_OVER", "VERDICT_NEAR", "VERDICT_UNDER", "VERDICT_ERROR", "VERDICT_CANCELLED", ".NOTICES"):
            self.assertNotIn(name, source, name)

    def test_batch_with_inconsistent_counts_fails_instead_of_showing_wrong_numbers(self):
        # 건수가 서로 맞지 않으면(있을 수 없는 경우) 틀린 숫자를 보이지 않고 작업을 실패로 끝낸다.
        self.write_goal_rows([("합성 과제 하나", goal(14)), ("합성 과제 둘", goal(14))])

        def mismatched(briefs):       # 기존 건수 줄은 오류·취소 0건인데 판정 못 함 묶음에 한 행이 들었다
            return dict(tally=[dict(kind="over", label="합성 이름", count=1), dict(kind="unjudged", label="합성 이름", count=1)],
                        groups=dict(focus=[0], unjudged=[1], other=[]),
                        members=dict(over=[0], near=[], under=[], unjudged=[1]))

        def without_brief(*args, **kwargs):   # 간단한 결과가 없는 과제 결과
            return [pipeline.TaskResult(row_number=2, title="합성", status=pipeline.STATUS_DONE)]
        cases = (("묶음과 건수 줄이 다름", dict(), mismatched), ("간단한 결과 없음", dict(batch_runner=without_brief), None))
        for name, overrides, tally_briefs in cases:
            with self.subTest(name):
                bridge = self.make_bridge(client_factory=self.marked_factory(), **overrides)
                if tally_briefs is None:
                    job = self.run_batch_job(bridge)
                else:
                    with mock.patch.object(bridge_module.brief, "tally_briefs", tally_briefs):
                        job = self.run_batch_job(bridge)
                self.assertEqual(job["state"], "failed")
                self.assertIsNone(job["result"])
                self.assertEqual(job["message"], bridge_module.MESSAGES["failed"])
                self.refused(bridge.save_report(self.token("save_report", bridge), "batch"), "not_found")

    def test_single_report_has_three_visible_sheets_and_hidden_log(self):
        real = self.make_bridge(report_writer=None)
        self.ok(real.run_single(task("합성 개별", excerpt=EXCERPT, attachment_name="계획서.hwpx"), ALL_FAMILIES))
        result = self.wait(real)["result"]
        self.assertEqual(result["brief"]["overall"], "고시 사양 초과")
        self.ok(real.save_report(self.token("save_report", real), "single"))
        report = self.read_report()
        self.assert_report_layout(report)
        summary = [row[:2] for row in report["sheets"]["과제별 검토 결과"]]
        self.assertIn(["종합 결과", "고시 사양 초과 1건 · 고시 사양 근접 0건 · 고시 사양 미달 0건"], summary)
        self.assertIn(["검토에서 빠진 행", "0건"], summary)
        # 사양 줄마다 한 줄: 초과 조항 둘의 사양 줄이 하나씩이다.
        self.assertEqual(len(report["sheets"]["초과·근접 조항"]) - 1,
                         sum(len(clause["lines"]) for clause in result["brief"]["focus"]))
        self.assertEqual(len(result["brief"]["focus"]), 2)
        # 공통 안내 세 줄은 저장한 파일의 어느 시트에도 없다(화면 맨 아래 한 줄과 같은 글 포함).
        cells = [value for rows in report["sheets"].values() for row in rows for value in row if isinstance(value, str)]
        for gone in ("고시 기준값 대부분은 AI가 고시 원문에서 읽은 값으로", "용도·양산 목적·예외 같은 숫자 외 조건은", FOOTER_NOTE):
            self.assertFalse([cell for cell in cells if gone in cell], gone)

    # ── 모델 설정 ─────────────────────────────────────────────────────
    def test_set_model_settings_defaults_and_validation(self):
        data = self.ok(self.bridge.set_model_settings("ollama", "", ""))
        self.assertEqual(data, dict(provider="ollama", model="qwen2.5:14b", base_url="http://localhost:11434"))
        data = self.ok(self.bridge.set_model_settings("lmstudio", " my-model ", "http://127.0.0.1:1234/"))
        self.assertEqual(data, dict(provider="lmstudio", model="my-model", base_url="http://127.0.0.1:1234"))
        self.assertEqual(self.ok(self.bridge.get_initial_state())["settings"], data)
        self.refused(self.bridge.set_model_settings("gemini", "", ""), "validation")
        self.refused(self.bridge.set_model_settings("ollama", "", "ftp://x"), "validation")
        self.refused(self.bridge.set_model_settings("ollama", "", "http://user:pw@localhost:1"), "validation")
        self.refused(self.bridge.set_model_settings("claude", "other-model", ""), "validation")
        data = self.ok(self.bridge.set_model_settings("claude", "", "http://ignored"))
        self.assertEqual(data, dict(provider="claude", model="claude-sonnet-5-5", base_url=""))
        # 로컬 제공자는 키 없이 실행된다.
        self.ok(self.bridge.set_model_settings("ollama", "", ""))
        self.backend.values.clear()
        self.ok(self.bridge.run_single(task("합성"), ALL_FAMILIES))
        self.assertEqual(self.wait()["state"], "done")
        self.assertEqual(self.client_keys[-1][1], "")
        self.assertEqual(self.client_keys[-1][0], dict(provider="ollama", model="qwen2.5:14b", base_url="http://localhost:11434"))

    def test_default_client_factory_builds_tolerant_client_without_network(self):
        from llm_json import TolerantLLMClient
        client = bridge_module.make_client(dict(provider="claude", model="claude-sonnet-5-5", base_url=""), SECRET)
        self.assertIsInstance(client, TolerantLLMClient)
        self.assertNotIn(SECRET, repr(client))
        client = bridge_module.make_client(dict(provider="ollama", model="qwen2.5:14b", base_url="http://localhost:11434"), "")
        self.assertEqual(client.base_url, "http://localhost:11434")

    def test_fixed_messages_are_noun_style(self):
        for text in list(bridge_module.MESSAGES.values()):
            self.assertFalse(text.endswith(("다.", "요.", "니다", "세요", "하다", "이다", "한다", "된다")), text)

    def test_fixed_messages_use_new_terms(self):
        self.assertEqual(bridge_module.MESSAGES["done"], "검토 완료")
        self.assertEqual(bridge_module.MESSAGES["batch_label"], "일괄 검토 중")
        # 새 이름(연구개발과제명·과제요약정보)을 지운 뒤 옛 이름이 남지 않았는지 본다.
        text = " ".join(bridge_module.MESSAGES.values()).replace("연구개발과제명", "").replace("과제요약정보", "")
        for old in ("판정 완료", "일괄 판정", "판정 중단", "과제요약", "과제명", "기준값 표", "고시 범위"):
            self.assertNotIn(old, text, old)

    # ── 고시 검색(합성 엔진) ───────────────────────────────────────────
    def test_search_methods_are_public_and_allowed_by_host(self):
        import app
        for name in ("search_notices", "get_notice_detail"):
            self.assertIn(name, bridge_module.PUBLIC_METHODS)
            self.assertIn(name, app.PUBLIC_METHODS)
            self.assertTrue(callable(getattr(self.bridge, name)))

    def test_initial_state_carries_search_state(self):
        data = self.ok(self.bridge.get_initial_state())
        search = data["search"]
        self.assertIs(search["available"], True)
        self.assertEqual(search["message"], "")
        self.assertEqual(search["status"], FakeSearchEngine().status())
        self.assertEqual([f["id"] for f in search["filters"]], list(notice_search.FILTERS))
        self.assertEqual([f["label"] for f in search["filters"]],
                         ["전체", "국가첨단전략기술", "국가핵심기술", "전략물자(이중용도)", "전략물자(군용)"])
        self.assertEqual(search["default_filter"], "전체")
        self.assertEqual(search["max_query_chars"], notice_search.MAX_QUERY_CHARS)
        self.assertEqual(search["default_limit"], notice_search.DEFAULT_LIMIT)
        self.assertEqual(search["footer"], notice_search.NOTICE_FOOTER)
        self.assertEqual(search["similar_notice"], notice_search.NOTICE_SIMILAR)

    def test_search_engine_is_built_once_from_loaded_resources(self):
        self.ok(self.bridge.get_initial_state())
        self.ok(self.bridge.search_notices("D램"))
        self.ok(self.bridge.get_notice_detail("advanced:item:001", "D램"))
        self.ok(self.bridge.search_notices("D램", "advanced", 5, 0, 0))
        self.assertEqual(len(self.search_factory_calls), 1)
        resources = self.search_factory_calls[0]
        self.assertIsInstance(resources, Resources)
        self.assertIs(resources.table, TABLE)
        self.assertEqual(self.search_engine.calls, 3)

    def test_search_answers_while_a_review_job_is_running(self):
        self.gate = threading.Event()
        self.ok(self.bridge.run_single(task("합성 A"), ALL_FAMILIES))
        time.sleep(.05)
        self.assertEqual(self.ok(self.bridge.poll_progress(0))["state"], "running")
        self.refused(self.bridge.run_single(task("합성 B"), ALL_FAMILIES), "busy")
        data = self.ok(self.bridge.search_notices("D램", "전체", 20, 0, 0))
        self.assertEqual(data["results"]["items"][0]["clause_id"], "advanced:item:001")
        detail = self.ok(self.bridge.get_notice_detail("advanced:item:001", "D램"))
        self.assertEqual(detail["clause_id"], "advanced:item:001")
        self.assertIn("search", self.ok(self.bridge.get_initial_state()))
        self.assertIn(self.ok(self.bridge.poll_progress(0))["state"], ("running", "cancelling"))
        self.gate.set()
        self.assertEqual(self.wait()["state"], "done")
        self.gate = None

    def test_search_adds_next_offset_and_keeps_engine_shape(self):
        data = self.ok(self.bridge.search_notices("D램"))
        self.assertEqual(data["results"]["next_offset"], 1)
        self.assertEqual(data["similar"]["next_offset"], 0)
        self.assertEqual(data["results"]["items"], [SEARCH_ITEM])
        self.assertEqual(self.ok(self.bridge.search_notices("D램", "전체", 20, 1, 0))["results"]["next_offset"], 1)

    def test_search_argument_types_are_refused(self):
        self.refused(self.bridge.search_notices(5), "validation")
        self.refused(self.bridge.search_notices(None), "validation")
        self.refused(self.bridge.search_notices("D램", 3), "validation")
        self.refused(self.bridge.get_notice_detail(None), "validation")
        self.refused(self.bridge.get_notice_detail(""), "validation")
        self.refused(self.bridge.get_notice_detail("advanced:item:001", 7), "validation")
        response = self.refused(self.bridge.get_notice_detail("advanced:item:999"), "validation")
        self.assertEqual(response["message"], bridge_module.MESSAGES["search_clause"])

    def test_search_engine_failure_is_a_safe_response_and_review_still_starts(self):
        def broken(resources):
            raise RuntimeError("search engine boom " + SECRET)
        bridge = self.make_bridge(search_factory=broken)
        data = self.ok(bridge.get_initial_state())
        self.assertIs(data["search"]["available"], False)
        self.assertIsNone(data["search"]["status"])
        self.assertEqual(data["search"]["message"], bridge_module.MESSAGES["search"])
        response = self.refused(bridge.search_notices("D램"), "search")
        self.assertEqual(response["message"], bridge_module.MESSAGES["search"])
        self.refused(bridge.get_notice_detail("advanced:item:001"), "search")
        self.assertNotIn("boom", json.dumps(response, ensure_ascii=False))
        self.ok(bridge.run_single(task("합성"), ALL_FAMILIES))
        self.assertEqual(self.wait(bridge)["state"], "done")

    def test_search_messages_are_noun_style_and_name_the_limit(self):
        self.assertIn(str(notice_search.MAX_QUERY_CHARS), bridge_module.MESSAGES["search_query"])
        for key in ("search", "search_failed", "search_query", "search_filter", "search_page", "search_clause"):
            self.assertIn(key, bridge_module.MESSAGES)


class SearchBridgeTests(unittest.TestCase):
    """실제 고시 자료·관련어 사전·모델로 만든 엔진을 쓰는 브리지(기본 자원 불러오기와 기본 검색 엔진)."""

    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge(key_manager=KeyManager(FakeBackend(), environ={}))

    def ok(self, response):
        self.assertEqual(set(response), {"ok", "data"}, response)
        self.assertIs(response["ok"], True)
        return response["data"]

    def refused(self, response, message_key):
        self.assertEqual(set(response), {"ok", "code", "message"}, response)
        self.assertIs(response["ok"], False)
        self.assertEqual(response["code"], "validation")
        self.assertEqual(response["message"], bridge_module.MESSAGES[message_key])
        self.assertNotIn("Traceback", json.dumps(response, ensure_ascii=False))
        return response

    def test_default_engine_reuses_loaded_catalogue_and_table(self):
        self.ok(self.bridge.get_initial_state())
        resources = self.bridge._get_resources()
        engine = self.bridge._search()
        self.assertIsNotNone(resources.full_catalogue)
        self.assertIs(engine.catalogue, resources.full_catalogue)
        self.assertIs(engine.table, resources.table)
        self.assertIs(self.bridge._search(), engine)
        state = self.ok(self.bridge.get_initial_state())["search"]
        self.assertIs(state["available"], True)
        self.assertIs(state["status"]["dictionary"]["available"], True)
        self.assertIn(state["status"]["semantic"]["state"], (notice_search.SEMANTIC_PENDING, notice_search.SEMANTIC_READY))

    def test_query_length_limit(self):
        self.ok(self.bridge.search_notices("가" * notice_search.MAX_QUERY_CHARS))
        self.refused(self.bridge.search_notices("가" * (notice_search.MAX_QUERY_CHARS + 1)), "search_query")
        self.refused(self.bridge.get_notice_detail("advanced:item:001", "가" * (notice_search.MAX_QUERY_CHARS + 1)),
                     "search_query")

    def test_wrong_family_is_refused_and_filter_applies(self):
        self.refused(self.bridge.search_notices("D램", "국가첨단전략기술"), "search_filter")
        self.refused(self.bridge.search_notices("D램", "없는 고시"), "search_filter")
        data = self.ok(self.bridge.search_notices("D램", "core", notice_search.MAX_LIMIT, 0, 0))
        self.assertTrue(data["results"]["items"])
        for group in ("results", "similar"):
            self.assertTrue(all(item["family"] == "core" for item in data[group]["items"]))

    def test_wrong_clause_id_is_refused(self):
        self.refused(self.bridge.get_notice_detail("advanced:item:999"), "search_clause")
        self.refused(self.bridge.get_notice_detail("dual_use:control:3A001 "), "search_clause")
        notes = note_records(self.bridge._get_resources().full_catalogue)
        self.assertTrue(notes)
        self.refused(self.bridge.get_notice_detail(notes[0]["clause_id"]), "search_clause")
        detail = self.ok(self.bridge.get_notice_detail("dual_use:control:3A001", "3A001"))
        self.assertEqual(detail["code"], "3A001")
        self.assertIn("criteria", detail)

    def test_wrong_page_values_are_refused(self):
        for args in ((0, 0, 0), (20, -1, 0), (20, 0, -1), (True, 0, 0), ("20", 0, 0), (notice_search.MAX_LIMIT + 1, 0, 0)):
            with self.subTest(args=args):
                self.refused(self.bridge.search_notices("D램", "전체", *args), "search_page")

    def test_results_have_no_scores_and_pages_continue(self):
        data = self.ok(self.bridge.search_notices("D램"))
        self.assertIn("advanced:item:001", [item["clause_id"] for item in data["results"]["items"][:10]])

        def keys(value):
            if isinstance(value, dict):
                for key, inner in value.items():
                    yield key
                    yield from keys(inner)
            elif isinstance(value, list):
                for inner in value:
                    yield from keys(inner)
        names = set(keys(data))
        self.assertFalse({name for name in names if "score" in name or "similarity" in name}, names)
        for group in ("results", "similar"):
            self.assertEqual(data[group]["next_offset"], data[group]["offset"] + len(data[group]["items"]))
        first = self.ok(self.bridge.search_notices("", "전체", 5, 0, 0))
        self.assertEqual(first["mode"], notice_search.MODE_ALL)
        self.assertIs(first["results"]["has_more"], True)
        self.assertEqual(first["results"]["next_offset"], 5)
        second = self.ok(self.bridge.search_notices("", "전체", 5, first["results"]["next_offset"], 0))
        self.assertFalse({i["clause_id"] for i in first["results"]["items"]} & {i["clause_id"] for i in second["results"]["items"]})
        unrelated = self.ok(self.bridge.search_notices("김치찌개"))
        self.assertEqual((unrelated["results"]["total"], unrelated["similar"]["total"]), (0, 0))
        self.assertEqual(unrelated["empty_message"], notice_search.NOTICE_NO_RESULTS)

    def test_search_query_is_not_kept_by_the_bridge(self):
        query = "브리지보관확인용검색어"
        self.ok(self.bridge.search_notices(query))
        self.ok(self.bridge.get_notice_detail("advanced:item:001", query))
        self.assertNotIn(query, repr(vars(self.bridge)))


class ProviderOutputLimitTests(unittest.TestCase):
    """제공자별 출력 한도(1.3.1): Claude·OpenAI 32,000, Ollama·LM Studio 8,000. 대기 시간 600·재시도·추론 설정 불변.

    클라이언트를 만들기만 한다(SDK·HTTP 세션은 첫 요청 때 만들어지므로 네트워크·실제 키 없음).
    """
    EXPECTED = {"claude": 32000, "openai": 32000, "ollama": 8000, "lmstudio": 8000}

    def test_table_keys_match_provider_list(self):
        from llm_client import DEFAULT_MODELS
        self.assertEqual(set(bridge_module.MAX_OUTPUT_TOKENS), set(bridge_module.PROVIDERS))
        self.assertEqual(set(bridge_module.MAX_OUTPUT_TOKENS), set(DEFAULT_MODELS))
        self.assertEqual(dict(bridge_module.MAX_OUTPUT_TOKENS), self.EXPECTED)

    def test_make_client_passes_provider_output_limit_and_keeps_timeout(self):
        from llm_client import DEFAULT_BASE_URLS, DEFAULT_MODELS
        from llm_json import TolerantLLMClient
        for provider, limit in self.EXPECTED.items():
            with self.subTest(provider=provider):
                needs_key = provider in bridge_module.KEY_PROVIDERS
                settings = dict(provider=provider, model=DEFAULT_MODELS[provider],
                                base_url="" if needs_key else DEFAULT_BASE_URLS[provider])
                client = bridge_module.make_client(settings, SECRET if needs_key else "")
                self.assertIsInstance(client, TolerantLLMClient)
                self.assertEqual(client.max_tokens, limit)
                self.assertEqual(client.timeout, 600)
                self.assertEqual(client.max_retries, 2)
                self.assertEqual(client.reasoning_effort, "medium")


if __name__ == "__main__":
    unittest.main()
