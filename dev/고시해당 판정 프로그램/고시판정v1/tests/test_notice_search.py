"""고시 검색 엔진(notice_search)과 조항 벡터 시험. spec 3·4·5·10, plan T3.

- 실제 고시 자료(resources/notices, 공개 자료)·실제 관련어 사전·실제 모델·실제 조항 벡터로 spec 5장의 시험 질의를 돌린다.
  기대 조항 ID는 원문을 확인해 고정했다(D램: 첨단 001·002/핵심 001·002, AMOLED: 첨단 009/핵심 013, 리튬이차전지:
  첨단 013·014·015/핵심 014·015·017, 무인항공기 9A012, 정보보안 5A002, 레이저 6A005).
- 사전·모델·벡터가 망가진 경우는 임시 폴더의 복사본(또는 가짜 파일)으로만 만든다. 실제 자원 파일은 고치지 않는다.
- 사전 내용(묶음·관계)은 사용자 검수로 바뀔 수 있으므로, 사전 쪽 단언은 spec 5 질의와 일반 성질(값 집합·규칙)에만 둔다.
"""
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np

import excel_report
import notice_search as ns
from notice_catalogue import canonical_hash, clause_index, load_catalogue, note_records
from threshold_table import load_threshold_table
from tools import build_search_dictionary as tool
from tools import compare_search_models as compare

PROGRAM = Path(__file__).resolve().parents[1]
REAL_DICTIONARY = PROGRAM / "resources" / "search_dictionary.json"
REAL_MODEL = PROGRAM / "resources" / "search_model"
REAL_VECTORS = PROGRAM / "resources" / "search_vectors.json"

DRAM = ["advanced:item:001", "advanced:item:002", "core:item:001", "core:item:002"]
AMOLED = ["advanced:item:009", "core:item:013"]
SECONDARY_BATTERY = ["advanced:item:013", "advanced:item:014", "advanced:item:015",
                     "core:item:014", "core:item:015", "core:item:017"]
UAV = "dual_use:control:9A012"
INFOSEC = "dual_use:control:5A002"
LASER = "dual_use:control:6A005"
SEMANTIC_QUERIES = {"DRAM": DRAM, "디스플레이": AMOLED, "이차전지": SECONDARY_BATTERY, "드론": [UAV],
                    "암호": [INFOSEC], "레이저": [LASER]}

CATALOGUE = None
TABLE = None
ENGINE = None


def setUpModule():
    global CATALOGUE, TABLE, ENGINE
    CATALOGUE = load_catalogue()
    TABLE = load_threshold_table(catalogue=CATALOGUE)
    ENGINE = ns.SearchEngine(CATALOGUE, TABLE)


def ids(group, top=None):
    items = group["items"] if top is None else group["items"][:top]
    return [item["clause_id"] for item in items]


def search_all(query, family=ns.FILTER_ALL, engine=None):
    return (engine or ENGINE).search(query, family=family, limit=ns.MAX_LIMIT)


def reason_ok(reason):
    if reason in ns.REASON_PLAIN:
        return True
    kind, sep, term = reason.partition(": ")
    return bool(sep) and kind in ns.REASON_WITH_TERM and bool(term.strip())


def walk_values(value):
    if isinstance(value, dict):
        for inner in value.values():
            yield from walk_values(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from walk_values(inner)
    else:
        yield value


@contextmanager
def blocked_network():
    def refuse(*args, **kwargs):
        raise OSError("network blocked in test")

    class NoSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise OSError("network blocked in test")

    saved = socket.socket, socket.create_connection, socket.getaddrinfo
    socket.socket, socket.create_connection, socket.getaddrinfo = NoSocket, refuse, refuse
    try:
        yield
    finally:
        socket.socket, socket.create_connection, socket.getaddrinfo = saved


def copy_vectors(folder):
    shutil.copy2(REAL_VECTORS, folder / ns.VECTORS_JSON)
    shutil.copy2(REAL_VECTORS.with_name(ns.VECTORS_NPY), folder / ns.VECTORS_NPY)
    return folder / ns.VECTORS_JSON


# ---------------------------------------------------------------------------
# spec 5 시험 질의
# ---------------------------------------------------------------------------

class SpecQueryTest(unittest.TestCase):
    def test_dram_variants_top10(self):
        for query in ("DRAM", "디램", "D램"):
            with self.subTest(query=query):
                result = ENGINE.search(query)
                self.assertEqual(result["mode"], ns.MODE_KEYWORD)
                self.assertTrue(set(DRAM) <= set(ids(result["results"], 10)), ids(result["results"], 10))

    def test_semiconductor_includes_field_and_dram(self):
        found = ids(search_all("반도체")["results"])
        semiconductor_field = [doc.clause_id for doc in ENGINE.docs if doc.field == "반도체"]
        self.assertTrue(semiconductor_field)
        self.assertTrue(set(semiconductor_field) <= set(found))
        self.assertTrue(set(DRAM) <= set(found))

    def test_display_amoled_top20(self):
        top = ids(ENGINE.search("디스플레이", limit=20)["results"])
        self.assertTrue(set(AMOLED) <= set(top), top)

    def test_oled_finds_display_field(self):
        found = set(ids(search_all("OLED")["results"]))
        display_field = {doc.clause_id for doc in ENGINE.docs if doc.field == "디스플레이"}
        self.assertTrue(display_field)
        self.assertTrue(display_field <= found, display_field - found)

    def test_secondary_battery_top10(self):
        top = set(ids(ENGINE.search("이차전지")["results"], 10))
        self.assertTrue(set(SECONDARY_BATTERY) <= top, top)
        top = set(ids(ENGINE.search("배터리")["results"], 10))
        self.assertTrue(set(SECONDARY_BATTERY) & top, top)

    def test_drone_crypto_laser_top10(self):
        for query, expected in (("드론", UAV), ("암호", INFOSEC), ("레이저", LASER)):
            with self.subTest(query=query):
                self.assertIn(expected, ids(ENGINE.search(query)["results"], 10))

    def test_control_number_3a001(self):
        for query in ("3A001", "3a001.a", " 3A001.a.2 "):
            with self.subTest(query=query):
                result = search_all(query)
                self.assertEqual(result["mode"], ns.MODE_CODE)
                items = result["results"]["items"]
                self.assertEqual(items[0]["clause_id"], "dual_use:control:3A001")
                self.assertEqual(items[0]["reason"], ns.REASON_CODE)
                self.assertGreater(len(items), 1)
                self.assertTrue(all(item["reason"] == ns.REASON_MENTION for item in items[1:]))
                self.assertTrue(all(item["code"] != "3A001" for item in items[1:]))
                self.assertEqual(result["similar"]["total"], 0)
                self.assertEqual(result["similar"]["items"], [])

    def test_control_number_ml1_not_ml10_to_19(self):
        items = search_all("ML1")["results"]["items"]
        exact = [item["code"] for item in items if item["reason"] == ns.REASON_CODE]
        self.assertEqual(exact, ["ML1"])
        self.assertEqual(items[0]["clause_id"], "military:control:ML1")
        self.assertTrue(all(item["reason"] == ns.REASON_MENTION for item in items[1:]))
        lower = search_all("ml 1")["results"]["items"]
        self.assertEqual(ids({"items": lower}), ids({"items": items}))

    def test_typo_display(self):
        result = search_all("디스프레이")
        found = {item["clause_id"]: item for item in result["results"]["items"]}
        self.assertTrue(set(AMOLED) <= set(found))
        self.assertIn(f"{ns.REASON_FUZZY}: 디스플레이", found["core:item:013"]["reasons"])

    def test_unrelated_word_zero(self):
        result = ENGINE.search("김치찌개")
        self.assertEqual(result["results"]["total"], 0)
        self.assertEqual(result["similar"]["total"], 0)
        self.assertEqual(result["empty_message"], ns.NOTICE_NO_RESULTS)
        self.assertEqual(result["results"]["empty_message"], ns.NOTICE_NO_RESULTS)

    def test_semantic_min_similarity(self):
        """최소 유사도 상수: 여섯 질의의 기대 조항은 걸리고 '김치찌개'는 걸리지 않는다(spec 4.5)."""
        for query, expected in SEMANTIC_QUERIES.items():
            with self.subTest(query=query):
                scores = ENGINE.semantic_scores(query)
                self.assertGreaterEqual(max(scores[c] for c in expected), ns.MIN_SIMILARITY)
        self.assertLess(max(ENGINE.semantic_scores("김치찌개").values()), ns.MIN_SIMILARITY)


# ---------------------------------------------------------------------------
# 필터·빈 검색어·값 집합·묶음
# ---------------------------------------------------------------------------

class FilterAndListTest(unittest.TestCase):
    def test_core_filter_only_core(self):
        for query in ("반도체", "레이저", "DRAM", "", "3A001", "디스프레이"):
            with self.subTest(query=query):
                result = search_all(query, family="core")
                self.assertEqual(result["family_label"], "국가핵심기술")
                families = {item["family"] for item in result["results"]["items"] + result["similar"]["items"]}
                self.assertTrue(families <= {"core"}, families)

    def test_empty_query_lists_everything_in_order(self):
        result = search_all("")
        self.assertEqual(result["mode"], ns.MODE_ALL)
        items = result["results"]["items"]
        self.assertEqual(len(items), 507)
        self.assertEqual(result["results"]["total"], 507)
        self.assertTrue(all(item["reasons"] == [ns.REASON_ALL] and item["reason"] == ns.REASON_ALL for item in items))
        self.assertFalse(result["similar"]["visible"])
        self.assertEqual(result["similar"]["total"], 0)
        order = [ns.FAMILY_ORDER.index(item["family"]) for item in items]
        self.assertEqual(order, sorted(order))
        military = [item["code"] for item in items if item["family"] == "military"]
        self.assertEqual(military[:3], ["ML1", "ML2", "ML3"])
        for family in ns.FAMILY_ORDER:
            with self.subTest(family=family):
                listed = search_all("   ", family=family)["results"]
                expected = [e["clause_id"] for e in clause_index(CATALOGUE) if e["family"] == family]
                self.assertEqual(sorted(ids(listed)), sorted(expected))

    def test_note_records_are_not_indexed(self):
        notes = {note["clause_id"] for note in note_records(CATALOGUE)}
        self.assertEqual(len(ENGINE.docs), 507)
        self.assertFalse(notes & set(ENGINE.by_id))
        with self.assertRaises(ns.UnknownClauseError):
            ENGINE.detail(sorted(notes)[0])

    def test_reason_value_set_and_more_label(self):
        for query in ("DRAM", "반도체", "디스프레이", "드론", "3A001", "", "레이저 거울", "OLED"):
            result = search_all(query)
            for item in result["results"]["items"] + result["similar"]["items"]:
                with self.subTest(query=query, clause=item["clause_id"]):
                    self.assertTrue(item["reasons"])
                    self.assertTrue(all(reason_ok(reason) for reason in item["reasons"]), item["reasons"])
                    self.assertEqual(len(item["reasons"]), len(set(item["reasons"])))
                    extra = len(item["reasons"]) - 1
                    expected = item["reasons"][0] + (f" 외 {extra}" if extra else "")
                    self.assertEqual(item["reason"], expected)
            for item in result["similar"]["items"]:
                self.assertEqual(item["reasons"], [ns.REASON_SEMANTIC])

    def test_grade_order(self):
        """검색어 일치 > 같은 말 > 한 단계 > 두 단계 > 글자 유사(가장 앞선 이유의 등급이 줄지 않는다)."""
        rank = {ns.REASON_QUERY: 0, ns.REASON_SYNONYM: 1, ns.REASON_ONE_STEP: 2, ns.REASON_TWO_STEP: 3,
                ns.REASON_FUZZY: 4}
        for query in ("D램", "DRAM", "디스플레이", "배터리"):
            items = search_all(query)["results"]["items"]
            grades = [rank[item["reasons"][0].split(": ")[0]] for item in items]
            self.assertEqual(grades, sorted(grades), query)
        dram = search_all("DRAM")["results"]["items"]
        self.assertTrue(all(item["reasons"][0] == f"{ns.REASON_SYNONYM}: D램" for item in dram[:4]))

    def test_multi_word_more_matches_first(self):
        items = search_all("레이저 거울")["results"]["items"]
        both = [i for i, item in enumerate(items)
                if all(ns.count_term(w, ENGINE.by_id[item["clause_id"]].search_text) for w in ("레이저", "거울"))]
        self.assertTrue(both)
        self.assertEqual(both, list(range(len(both))))   # 두 낱말 다 맞은 조항이 앞에 모인다
        self.assertGreater(len(items), len(both))        # 하나만 맞아도 들어간다

    def test_groups_do_not_overlap_and_pages_are_consistent(self):
        for query in ("DRAM", "디스플레이", "이차전지", "OLED", "디램", "반도체"):
            with self.subTest(query=query):
                full = search_all(query)
                self.assertFalse(set(ids(full["results"])) & set(ids(full["similar"])))
                paged, offset = [], 0
                while True:
                    page = ENGINE.search(query, limit=7, offset=offset)["results"]
                    paged += ids(page)
                    self.assertEqual(page["remaining"], max(0, page["total"] - offset - len(page["items"])))
                    self.assertEqual(page["has_more"], page["remaining"] > 0)
                    if not page["has_more"]:
                        break
                    offset += 7
                self.assertEqual(paged, ids(full["results"]))
                similar_paged = ENGINE.search(query, limit=3, similar_offset=3)["similar"]
                self.assertEqual(ids(similar_paged), ids(full["similar"])[3:6])

    def test_similar_group_visible_with_notice(self):
        result = ENGINE.search("디스플레이")
        self.assertTrue(result["similar"]["visible"])
        self.assertEqual(result["similar"]["notice"], ns.NOTICE_SIMILAR)
        self.assertEqual(result["footer"], ns.NOTICE_FOOTER)
        self.assertEqual(result["status"]["semantic"]["state"], ns.SEMANTIC_READY)
        self.assertEqual(result["status"]["semantic"]["notice"], "")
        self.assertTrue(result["status"]["dictionary"]["available"])

    def test_results_are_json_without_scores(self):
        for query in ("디스플레이", "3A001", ""):
            result = ENGINE.search(query)
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            self.assertFalse(any(isinstance(value, float) for value in walk_values(result)))
            for item in result["results"]["items"] + result["similar"]["items"]:
                self.assertEqual(set(item), {"clause_id", "family", "family_label", "code", "title", "field", "reason",
                                             "reasons", "snippet", "highlights"})
        detail = ENGINE.detail(LASER, "레이저")
        json.dumps(detail, ensure_ascii=False, allow_nan=False)
        self.assertFalse(any(isinstance(value, float) for value in walk_values(detail)))

    def test_snippet_highlights(self):
        items = ENGINE.search("D램")["results"]["items"]
        for item in items[:4]:
            self.assertTrue(item["highlights"])
            for start, end in item["highlights"]:
                self.assertEqual(item["snippet"][start:end], "D램")
        for query in ("레이저", "3A001", "드론", "디스프레이"):
            for item in ENGINE.search(query)["results"]["items"]:
                for start, end in item["highlights"]:
                    with self.subTest(query=query, clause=item["clause_id"]):
                        self.assertTrue(0 <= start < end <= len(item["snippet"]))
                        self.assertTrue(item["snippet"][start:end].strip())
                self.assertLessEqual(len(item["snippet"]), ns.SNIPPET_CHARS + 2)
        mention = search_all("3A001")["results"]["items"][1]
        self.assertTrue(all(mention["snippet"][a:b] == "3A001" for a, b in mention["highlights"]))

    def test_excerpt_maps_highlights_after_whitespace_cleanup(self):
        text = "가나\n\n  다라 D램  마바"
        start = text.index("D램")
        snippet, highlights = ns.excerpt(text, 0, len(text), [(start, start + 2)])
        self.assertEqual(snippet, "가나 다라 D램 마바")
        self.assertEqual([snippet[a:b] for a, b in highlights], ["D램"])
        snippet, highlights = ns.excerpt(text, 2, start + 1, [(start, start + 2)])
        self.assertTrue(snippet.startswith("…") and snippet.endswith("…"))
        self.assertEqual([snippet[a:b] for a, b in highlights], ["D"])


# ---------------------------------------------------------------------------
# 입력 검사·통제번호 모양
# ---------------------------------------------------------------------------

class InputTest(unittest.TestCase):
    def test_query_limits(self):
        ENGINE.search("가" * ns.MAX_QUERY_CHARS)
        with self.assertRaises(ns.SearchQueryError):
            ENGINE.search("가" * (ns.MAX_QUERY_CHARS + 1))
        with self.assertRaises(ns.SearchQueryError):
            ENGINE.search(123)
        with self.assertRaises(ns.SearchQueryError):
            ENGINE.detail(LASER, "가" * (ns.MAX_QUERY_CHARS + 1))

    def test_filter_and_page_values(self):
        for family in ("all", "국가핵심기술", "", 1):
            with self.assertRaises(ns.SearchFilterError):
                ENGINE.search("레이저", family=family)
        for kwargs in (dict(limit=0), dict(limit=ns.MAX_LIMIT + 1), dict(offset=-1), dict(limit=True),
                       dict(limit="20"), dict(similar_offset=-1)):
            with self.assertRaises(ns.SearchError):
                ENGINE.search("레이저", **kwargs)
        self.assertEqual(ENGINE.search("레이저", family=None)["family"], ns.FILTER_ALL)

    def test_unknown_clause(self):
        for clause_id in ("dual_use:control:9Z999", "", None, 3):
            with self.assertRaises(ns.UnknownClauseError):
                ENGINE.detail(clause_id)

    def test_control_number_shape(self):
        cases = {"3A001": "3A001", "3a001.a": "3A001", " 3A001.a.2 ": "3A001", "3 a 001": "3A001", "ML8": "ML8",
                 "ml 8": "ML8", "ML1.a": "ML1", "5A002.d.": "5A002", "ML19": "ML19"}
        for query, code in cases.items():
            self.assertEqual(ns.parse_control_number(query), code, query)
        for query in ("3A", "3A00", "3F001", "ML123", "ML", "IL3.A.1", "3A0011", "레이저 3A001", "MT14.A.1.b"):
            self.assertIsNone(ns.parse_control_number(query), query)
        self.assertEqual(ENGINE.search("3A00")["mode"], ns.MODE_KEYWORD)

    def test_mention_pattern_boundaries(self):
        pattern = ns.mention_pattern("ML1")
        for text in ("ML10", "ML19.a", "HTML1", "5 ml 1회"):
            self.assertIsNone(pattern.search(text), text)
        for text in ("ML1.", "ML 1", "(ML1)", "ML1.a.2"):
            self.assertIsNotNone(pattern.search(text), text)
        pattern = ns.mention_pattern("3A001")
        self.assertIsNone(pattern.search("13A001"))
        self.assertIsNotNone(pattern.search("3A001.e.2"))


# ---------------------------------------------------------------------------
# 상세
# ---------------------------------------------------------------------------

class DetailTest(unittest.TestCase):
    def test_detail_text_and_highlights(self):
        detail = ENGINE.detail(LASER, "레이저")
        self.assertEqual(detail["text"], ENGINE.by_id[LASER].text)
        self.assertIn("[국문 원문]", detail["text"])
        self.assertIn("[영문 원문]", detail["text"])
        marked = {detail["text"][a:b].casefold() for a, b in detail["highlights"]}
        self.assertIn("레이저", marked)
        self.assertIn("laser", marked)     # 같은 말도 강조
        self.assertEqual(ENGINE.detail(LASER)["highlights"], [])
        code = ENGINE.detail("dual_use:control:3B001", "3A001")
        self.assertTrue(code["highlights"])
        self.assertTrue(all(code["text"][a:b] == "3A001" for a, b in code["highlights"]))

    def test_criteria_ai_extracted_threshold(self):
        criteria = ENGINE.detail(LASER)["criteria"]
        self.assertTrue(criteria["has_numeric"])
        self.assertEqual(criteria["message"], "")
        thresholds = [t for branch in criteria["branches"] for t in branch["thresholds"]]
        self.assertTrue(thresholds)
        for threshold in thresholds:
            self.assertIn(threshold["operator_label"], ("이상", "초과", "이하", "미만"))
            self.assertTrue(threshold["subject"] and threshold["value"])
            self.assertEqual(threshold["origin"], "extracted")
            self.assertEqual(threshold["origin_label"], "AI가 읽은 기준값")
            self.assertEqual(threshold["flag"], "AI가 읽은 기준값(원문 확인 필요)")

    def test_criteria_structured_threshold(self):
        thresholds = [t for b in ENGINE.detail("advanced:item:001")["criteria"]["branches"] for t in b["thresholds"]]
        self.assertTrue(thresholds)
        self.assertTrue(all(t["origin_label"] == "정리된 기준" and t["flag"] == "" for t in thresholds))

    def test_criteria_no_numeric(self):
        criteria = ENGINE.detail("core:item:013")["criteria"]
        self.assertFalse(criteria["has_numeric"])
        self.assertEqual(criteria["message"], "수치 기준 없음")
        self.assertEqual(criteria["numeric_status"], "숫자 기준 없음")

    def test_criteria_text_branch_checks_and_rejected(self):
        record = dict(clause_id="synthetic:item:001", family="core", numeric_status="기준값 채택 실패", title="합성",
                      branches=[dict(branch_id="b1", label="갈래 1", thresholds=[], text="숫자 없는 갈래 원문")],
                      rejected=[dict(branch_id="b2", subject="두께", quote="두께가 매우 얇은 것", reason="수가 없다")],
                      checks=[dict(quote="군용으로 설계된 것", source="항목 본문")])
        criteria = ns.criteria_list(record)
        self.assertEqual(criteria["message"], "수치 기준 없음")
        self.assertEqual(criteria["branches"][0]["text"], "숫자 없는 갈래 원문")
        self.assertFalse(criteria["branches"][0]["numeric"])
        self.assertEqual(criteria["rejected"][0]["flag"], "기준값 채택 실패(원문 확인 필요)")
        self.assertEqual(criteria["checks"], [dict(quote="군용으로 설계된 것", source="항목 본문", from_body=True)])
        checks = [c for r in TABLE.all_records() for c in r["checks"]]
        self.assertTrue(checks)
        any_check = next(r["clause_id"] for r in TABLE.all_records() if r["checks"])
        self.assertEqual(len(ENGINE.detail(any_check)["criteria"]["checks"]), len(TABLE.record(any_check)["checks"]))

    def test_labels_match_excel_report(self):
        self.assertEqual(ns.OPERATOR_LABELS, excel_report.OPERATOR_LABELS)
        self.assertEqual(ns.ORIGIN_LABELS, excel_report.ORIGIN_LABELS)


# ---------------------------------------------------------------------------
# 사전·모델·벡터가 없거나 망가졌을 때
# ---------------------------------------------------------------------------

class FailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assert_semantic_off_but_searching(self, engine, reason_part):
        result = engine.search("D램")
        semantic = result["status"]["semantic"]
        self.assertEqual(semantic["state"], ns.SEMANTIC_OFF)
        self.assertFalse(semantic["available"])
        self.assertIn(reason_part, semantic["reason"])
        self.assertEqual(semantic["notice"], ns.NOTICE_SEMANTIC_OFF)
        self.assertFalse(result["similar"]["visible"])
        self.assertEqual(result["similar"]["items"], [])
        self.assertTrue(set(DRAM) <= set(ids(result["results"], 10)))
        self.assertEqual(engine.semantic_scores("D램"), {})

    def test_model_missing(self):
        engine = ns.SearchEngine(CATALOGUE, TABLE, model_folder=self.folder / "없는 폴더")
        self.assertEqual(engine.status()["semantic"]["state"], ns.SEMANTIC_PENDING)
        self.assert_semantic_off_but_searching(engine, "MODEL_INFO.json")

    def test_model_file_missing(self):
        shutil.copy2(REAL_MODEL / ns.MODEL_INFO_NAME, self.folder / ns.MODEL_INFO_NAME)
        engine = ns.SearchEngine(CATALOGUE, TABLE, model_folder=self.folder)
        self.assert_semantic_off_but_searching(engine, "모델 파일이 없다")

    def test_model_fingerprint_mismatch(self):
        shutil.copy2(REAL_MODEL / ns.MODEL_INFO_NAME, self.folder / ns.MODEL_INFO_NAME)
        for name in ns.MODEL_RUNTIME_FILES:
            (self.folder / name).write_bytes(b"not the model")
        engine = ns.SearchEngine(CATALOGUE, TABLE, model_folder=self.folder)
        self.assert_semantic_off_but_searching(engine, "지문")

    def test_semantic_failure_during_search_turns_off_and_keeps_searching(self):
        engine = ns.SearchEngine(CATALOGUE, TABLE)
        self.assertEqual(engine.ensure_semantic()["state"], ns.SEMANTIC_READY)

        def broken(query, allowed):
            raise RuntimeError("encode failed")

        engine._semantic_rows = broken
        result = engine.search("D램")
        self.assertEqual(result["status"]["semantic"]["state"], ns.SEMANTIC_OFF)
        self.assertIn("RuntimeError", result["status"]["semantic"]["reason"])
        self.assertEqual(result["similar"]["items"], [])
        self.assertTrue(set(DRAM) <= set(ids(result["results"], 10)))

    def test_vectors_missing(self):
        engine = ns.SearchEngine(CATALOGUE, TABLE, vectors_file=self.folder / ns.VECTORS_JSON)
        self.assert_semantic_off_but_searching(engine, ns.VECTORS_JSON)

    def test_vectors_fingerprint_and_content_mismatch(self):
        path = copy_vectors(self.folder)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["chunk_counts"][0] += 1                                      # 지문을 고치지 않고 내용만 바꿈
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        engine = ns.SearchEngine(CATALOGUE, TABLE, vectors_file=path)
        self.assert_semantic_off_but_searching(engine, "지문")

    def test_vectors_array_changed(self):
        path = copy_vectors(self.folder)
        matrix = np.load(self.folder / ns.VECTORS_NPY, allow_pickle=False)
        matrix[0, 0] = -matrix[0, 0] if matrix[0, 0] else 0.5
        np.save(self.folder / ns.VECTORS_NPY, matrix, allow_pickle=False)
        engine = ns.SearchEngine(CATALOGUE, TABLE, vectors_file=path)
        self.assert_semantic_off_but_searching(engine, "배열 파일 지문")

    def test_vectors_other_model(self):
        path = copy_vectors(self.folder)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["model"]["fingerprint"] = "0" * 64
        payload["fingerprint"] = ns.vectors_fingerprint(payload)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        engine = ns.SearchEngine(CATALOGUE, TABLE, vectors_file=path)
        self.assert_semantic_off_but_searching(engine, "모델 지문")

    def assert_dictionary_off(self, engine, reason_part):
        status = engine.status()["dictionary"]
        self.assertFalse(status["available"])
        self.assertIn(reason_part, status["reason"])
        self.assertEqual(status["notice"], ns.NOTICE_DICTIONARY_OFF)
        for query in ("DRAM", "D램", "디스플레이", "드론"):
            result = engine.search(query, limit=ns.MAX_LIMIT)
            self.assertFalse(result["status"]["dictionary"]["available"])
            for item in result["results"]["items"]:
                self.assertTrue(item["reasons"][0] == ns.REASON_QUERY or item["reasons"][0].startswith(ns.REASON_FUZZY))
                self.assertFalse([r for r in item["reasons"] if r.startswith(("같은 말", "관련어"))])
        self.assertTrue(set(DRAM) <= set(ids(engine.search("D램")["results"], 10)))
        self.assertIn("advanced:item:009", ids(engine.search("디스플레이", limit=ns.MAX_LIMIT)["results"]))

    def test_dictionary_fingerprint_mismatch(self):
        data = json.loads(REAL_DICTIONARY.read_text(encoding="utf-8"))
        data["groups"][0]["terms"][0]["count"] += 1
        path = self.folder / "search_dictionary.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        engine = ns.SearchEngine(CATALOGUE, TABLE, dictionary_file=path, model_folder=self.folder / "없음")
        self.assert_dictionary_off(engine, "지문")

    def test_dictionary_other_catalogue_or_missing(self):
        data = json.loads(REAL_DICTIONARY.read_text(encoding="utf-8"))
        data["catalogue_fingerprint"] = "f" * 64
        data["fingerprint"] = ns.dictionary_fingerprint(data)
        path = self.folder / "search_dictionary.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        engine = ns.SearchEngine(CATALOGUE, TABLE, dictionary_file=path, model_folder=self.folder / "없음")
        self.assert_dictionary_off(engine, "기준본")
        engine = ns.SearchEngine(CATALOGUE, TABLE, dictionary_file=self.folder / "없는.json",
                                 model_folder=self.folder / "없음")
        self.assert_dictionary_off(engine, "읽지 못했다")


# ---------------------------------------------------------------------------
# 네트워크·파일 기록 없음
# ---------------------------------------------------------------------------

class PrivacyTest(unittest.TestCase):
    def test_search_with_sockets_blocked(self):
        with blocked_network():
            engine = ns.SearchEngine(CATALOGUE, TABLE)
            result = engine.search("디스플레이")
            self.assertEqual(result["status"]["semantic"]["state"], ns.SEMANTIC_READY)
            self.assertTrue(result["results"]["items"])
            self.assertTrue(result["similar"]["items"])
            engine.search("3A001")
            engine.detail(LASER, "레이저")
        self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
        self.assertEqual(os.environ.get("HF_HUB_DISABLE_TELEMETRY"), "1")
        self.assertNotIn("huggingface_hub", sys.modules)

    def test_no_files_or_logs_from_search(self):
        def snapshot(root):
            return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*")}

        before = snapshot(PROGRAM)
        system_temp = Path(tempfile.gettempdir())
        temp_before = {p.name for p in system_temp.iterdir()}
        queries = ("검색어기록시험 레이저", "DRAM", "3A001", "디스프레이", "", "김치찌개")
        with tempfile.TemporaryDirectory() as fresh:
            saved = tempfile.tempdir, {key: os.environ.get(key) for key in ("TMP", "TEMP", "TMPDIR")}
            tempfile.tempdir = fresh
            for key in saved[1]:
                os.environ[key] = fresh
            try:
                with self.assertNoLogs(level=logging.DEBUG):
                    engine = ns.SearchEngine(CATALOGUE, TABLE)
                    for query in queries:
                        engine.search(query)
                    engine.detail(LASER, "검색어기록시험")
                self.assertEqual(list(Path(fresh).iterdir()), [])
            finally:
                tempfile.tempdir = saved[0]
                for key, value in saved[1].items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertEqual(snapshot(PROGRAM), before)
        new_temp = {p.name for p in system_temp.iterdir()} - temp_before
        self.assertFalse([name for name in new_temp if "검색어기록시험" in name])


# ---------------------------------------------------------------------------
# 과제 글 의미 순위(1.3.0 spec 5.2, plan T2): 고시별 실제 검토 항목 전체를 뜻 유사도 순으로
# ---------------------------------------------------------------------------

# 합성 과제 글(연구개발과제명 + 최종목표 + 연구개발내용을 줄바꿈으로 이은 꼴). 실제 과제 자료가 아니다.
DRAM_TASK = ("D램 적층조립 공정 고도화\n"
             "HBM용 D램 다이를 16단 이상 적층하는 조립 기술과 검사 기술 개발\n"
             "실리콘관통전극(TSV) 기반 적층조립, 하이브리드 본딩 공정, 적층 후 전기적 검사 장비 개발")
AMOLED_TASK = ("고해상도 AMOLED 패널 기술 개발\n"
               "화소밀도 2000ppi 이상의 AMOLED 디스플레이 패널 구현\n"
               "마이크로 디스플레이용 OLED 증착 공정과 화소 구동 회로 설계")
LASER_TASK = ("고출력 광섬유 레이저 개발\n"
              "평균 출력 10kW 이상의 연속파 광섬유 레이저 발진기 개발\n"
              "레이저 이득 매질, 펌프 광원, 빔 품질 개선 및 출력 안정화 기술")
RANKING_TASKS = (DRAM_TASK, AMOLED_TASK, LASER_TASK)


def family_ids(family):
    return [entry["clause_id"] for entry in clause_index(CATALOGUE) if entry["family"] == family]


def expected_ranking(engine, text):
    """단독 계산: semantic_scores(03 '뜻 비슷'과 같은 계산)의 값으로 고시마다 (유사도 높은 순, 엔진 order_key) 정렬."""
    scores = engine.semantic_scores(" ".join(text.split()))
    ranking = {}
    for family in ns.FAMILY_ORDER:
        docs = [doc for doc in engine.docs if doc.family == family]
        ranking[family] = [doc.clause_id for doc in sorted(docs, key=lambda d: (-scores[d.clause_id], d.order_key))]
    return ranking


def chunk_range(starts, total, number):
    end = int(starts[number + 1]) if number + 1 < len(starts) else total
    return int(starts[number]), end


class SemanticRankingTest(unittest.TestCase):
    def ranking(self, text, engine=None):
        result = (engine or ENGINE).semantic_ranking(text)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(result["reason"], "")
        return result["ranking"]

    def test_synthetic_tasks_rank_expected_clauses_in_top5(self):
        cases = ((DRAM_TASK, "core", "core:item:002"), (DRAM_TASK, "advanced", "advanced:item:002"),
                 (AMOLED_TASK, "advanced", "advanced:item:009"), (AMOLED_TASK, "core", "core:item:013"),
                 (LASER_TASK, "dual_use", LASER))
        for text, family, clause in cases:
            with self.subTest(clause=clause):
                self.assertIn(clause, self.ranking(text)[family][:5])

    def test_each_family_lists_all_review_items_without_notes(self):
        notes = {note["clause_id"] for note in note_records(CATALOGUE)}
        self.assertTrue(notes)
        for text in RANKING_TASKS:
            ranking = self.ranking(text)
            self.assertEqual(list(ranking), list(ns.FAMILY_ORDER))
            for family in ns.FAMILY_ORDER:
                with self.subTest(family=family):
                    listed = ranking[family]
                    self.assertEqual(len(listed), len(set(listed)))
                    self.assertEqual(sorted(listed), sorted(family_ids(family)))
                    self.assertFalse(notes & set(listed))
            self.assertEqual(sum(len(listed) for listed in ranking.values()), 507)

    def test_same_order_as_semantic_scores(self):
        for text in RANKING_TASKS + ("레이저", "  D램\n\n적층조립  "):
            with self.subTest(text=text[:12]):
                self.assertEqual(self.ranking(text), expected_ranking(ENGINE, text))

    def test_long_text_is_not_cut_at_search_limit(self):
        text = "\n".join([DRAM_TASK] * 40)
        self.assertGreater(len(text), ns.MAX_QUERY_CHARS * 10)
        self.assertEqual(self.ranking(text), expected_ranking(ENGINE, text))

    def test_result_is_json_without_scores(self):
        result = ENGINE.semantic_ranking(AMOLED_TASK)
        self.assertEqual(set(result), {"available", "reason", "ranking"})
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.assertFalse(any(isinstance(value, float) for value in walk_values(result)))
        self.assertTrue(all(isinstance(value, str) for value in walk_values(result["ranking"])))

    def test_ties_follow_engine_order_key(self):
        """같은 값이면 고시·통제번호 순(order_key). 조항 벡터를 합성 값으로 바꿔 같은 값을 만든다(실제 파일은 그대로)."""
        text = " ".join(LASER_TASK.split())
        core_docs = sorted((doc for doc in ENGINE.docs if doc.family == "core"), key=lambda d: d.order_key)
        top, second = core_docs[-1], core_docs[-2]
        real_loader = ns.load_vectors_with_fingerprint

        def fake_loader(path, catalogue, model, chunks=None):
            matrix, starts, texts, fingerprint = real_loader(path, catalogue, model, chunks)
            fake = np.zeros_like(matrix)
            vector = model.encode([text])[0]
            for doc, weight in ((top, 1.0), (second, 0.5)):
                start, end = chunk_range(starts, len(matrix), doc.number)
                fake[start:end] = vector * weight
            return fake, starts, texts, fingerprint

        with mock.patch.object(ns, "load_vectors_with_fingerprint", fake_loader):
            engine = ns.SearchEngine(CATALOGUE, TABLE)
            ranking = self.ranking(text, engine)
        rest = [doc.clause_id for doc in core_docs[:-2]]
        self.assertEqual(ranking["core"], [top.clause_id, second.clause_id] + rest)
        for family in ("advanced", "dual_use", "military"):
            with self.subTest(family=family):
                ordered = [d.clause_id for d in sorted((d for d in ENGINE.docs if d.family == family),
                                                       key=lambda d: d.order_key)]
                self.assertEqual(ranking[family], ordered)
        dual_use = [ENGINE.by_id[c].code for c in ranking["dual_use"]]
        self.assertEqual(dual_use, sorted(dual_use, key=ns._code_key))

    def test_fingerprints_match_model_info_and_vectors_file(self):
        fresh = ns.SearchEngine(CATALOGUE, TABLE)
        self.assertEqual(fresh.semantic_model_fingerprint, "")      # 아직 불러오지 않음
        self.assertEqual(fresh.semantic_vectors_fingerprint, "")
        self.ranking(DRAM_TASK)
        info = json.loads((REAL_MODEL / ns.MODEL_INFO_NAME).read_text(encoding="utf-8"))
        hashes = {name: info["files"][name]["sha256"] for name in ns.MODEL_RUNTIME_FILES}
        payload = json.loads(REAL_VECTORS.read_text(encoding="utf-8"))
        self.assertEqual(ENGINE.semantic_model_fingerprint, ns.model_fingerprint(hashes))
        self.assertEqual(ENGINE.semantic_model_fingerprint, payload["model"]["fingerprint"])
        self.assertEqual(ENGINE.semantic_vectors_fingerprint, payload["fingerprint"])
        self.assertEqual(ENGINE.semantic_vectors_fingerprint, ns.vectors_fingerprint(payload))
        self.assertRegex(ENGINE.semantic_model_fingerprint, r"\A[0-9a-f]{64}\Z")
        self.assertRegex(ENGINE.semantic_vectors_fingerprint, r"\A[0-9a-f]{64}\Z")

    def test_concurrent_rankings_match_single_runs_and_load_once(self):
        expected = {text: expected_ranking(ENGINE, text) for text in RANKING_TASKS}
        loads = []
        real_model = ns.StaticEmbeddingModel

        class CountingModel(real_model):
            def __init__(self, *args, **kwargs):
                loads.append(1)
                super().__init__(*args, **kwargs)

        orders = (list(RANKING_TASKS), list(RANKING_TASKS[::-1]), [DRAM_TASK] * 3)   # 다른 글·같은 글
        results, errors = [], []
        with mock.patch.object(ns, "StaticEmbeddingModel", CountingModel):
            engine = ns.SearchEngine(CATALOGUE, TABLE)
            barrier = threading.Barrier(len(orders))

            def worker(texts):
                try:
                    barrier.wait(timeout=60)
                    for text in texts:
                        results.append((text, engine.semantic_ranking(text)))
                except Exception as error:   # noqa: BLE001 — 스레드 안 실패를 시험 실패로 넘긴다
                    errors.append(error)

            threads = [threading.Thread(target=worker, args=(texts,)) for texts in orders]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=180)
        self.assertEqual(errors, [])
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(results), sum(len(texts) for texts in orders))
        for text, result in results:
            self.assertTrue(result["available"], result["reason"])
            self.assertEqual(result["ranking"], expected[text])

    def test_ranking_text_stays_in_memory_only(self):
        marker = "순위글기록시험"
        text = f"{marker} {DRAM_TASK}"

        def listing(root):
            return {str(p.relative_to(root)) for p in root.rglob("*") if "__pycache__" not in p.parts}

        def resource_times():
            return {str(p): p.stat().st_mtime_ns for p in (PROGRAM / "resources").rglob("*")}

        before, times = listing(PROGRAM), resource_times()
        with tempfile.TemporaryDirectory() as fresh:
            saved = tempfile.tempdir, {key: os.environ.get(key) for key in ("TMP", "TEMP", "TMPDIR")}
            tempfile.tempdir = fresh
            for key in saved[1]:
                os.environ[key] = fresh
            try:
                with blocked_network(), self.assertNoLogs(level=logging.DEBUG):
                    engine = ns.SearchEngine(CATALOGUE, TABLE)
                    result = engine.semantic_ranking(text)
                self.assertEqual(list(Path(fresh).iterdir()), [])
            finally:
                tempfile.tempdir = saved[0]
                for key, value in saved[1].items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertTrue(result["available"], result["reason"])
        self.assertNotIn(marker, json.dumps(result, ensure_ascii=False))
        self.assertFalse([v for v in vars(engine).values() if isinstance(v, str) and marker in v])
        self.assertEqual(listing(PROGRAM) - before, set())
        self.assertEqual(resource_times(), times)


class SemanticRankingUnavailableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assert_unavailable(self, engine, text, reason_part):
        result = engine.semantic_ranking(text)     # 예외 없이 돌아온다
        self.assertEqual(set(result), {"available", "reason", "ranking"})
        self.assertIs(result["available"], False)
        self.assertIsNone(result["ranking"])
        self.assertIn(reason_part, result["reason"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result

    def assert_no_fingerprints(self, engine):
        self.assertEqual(engine.semantic_model_fingerprint, "")
        self.assertEqual(engine.semantic_vectors_fingerprint, "")

    def test_model_missing(self):
        engine = ns.SearchEngine(CATALOGUE, TABLE, model_folder=self.folder / "없는 폴더")
        self.assert_no_fingerprints(engine)
        self.assert_unavailable(engine, DRAM_TASK, "MODEL_INFO.json")
        self.assert_no_fingerprints(engine)
        self.assertTrue(set(DRAM) <= set(ids(engine.search("D램")["results"], 10)))   # 03 검색은 계속

    def test_model_fingerprint_mismatch(self):
        shutil.copy2(REAL_MODEL / ns.MODEL_INFO_NAME, self.folder / ns.MODEL_INFO_NAME)
        for name in ns.MODEL_RUNTIME_FILES:
            (self.folder / name).write_bytes(b"not the model")
        engine = ns.SearchEngine(CATALOGUE, TABLE, model_folder=self.folder)
        self.assert_unavailable(engine, DRAM_TASK, "지문")
        self.assert_no_fingerprints(engine)

    def test_vectors_missing(self):
        engine = ns.SearchEngine(CATALOGUE, TABLE, vectors_file=self.folder / ns.VECTORS_JSON)
        self.assert_unavailable(engine, DRAM_TASK, ns.VECTORS_JSON)
        self.assert_no_fingerprints(engine)

    def test_empty_or_blank_text(self):
        for text in ("", "   ", "\n\t \n", None):
            with self.subTest(text=text):
                result = self.assert_unavailable(ENGINE, text, ns.RANKING_EMPTY_TEXT)
                self.assertEqual(result["reason"], ns.RANKING_EMPTY_TEXT)
        fresh = ns.SearchEngine(CATALOGUE, TABLE)
        self.assert_unavailable(fresh, "  ", ns.RANKING_EMPTY_TEXT)
        self.assertEqual(fresh.status()["semantic"]["state"], ns.SEMANTIC_PENDING)   # 빈 글로는 모델을 불러오지 않는다

    def test_text_without_any_model_word(self):
        result = self.assert_unavailable(ENGINE, "​ ​", ns.RANKING_NO_WORDS)
        self.assertEqual(result["reason"], ns.RANKING_NO_WORDS)

    def test_non_text_is_rejected(self):
        for value in (123, ["D램"], "D램".encode("utf-8")):
            with self.subTest(value=value):
                with self.assertRaises(ns.SearchQueryError):
                    ENGINE.semantic_ranking(value)

    def test_error_during_ranking_is_unavailable_and_keeps_search_on(self):
        engine = ns.SearchEngine(CATALOGUE, TABLE)
        expected = expected_ranking(ENGINE, DRAM_TASK)
        self.assertEqual(engine.semantic_ranking(DRAM_TASK)["ranking"], expected)
        model = engine._model

        def broken(texts):
            raise RuntimeError("encode failed 비밀글")

        model.encode = broken
        try:
            result = self.assert_unavailable(engine, DRAM_TASK, ns.RANKING_ERROR)
        finally:
            del model.encode
        self.assertIn("RuntimeError", result["reason"])
        self.assertNotIn("비밀글", result["reason"])
        self.assertEqual(engine.status()["semantic"]["state"], ns.SEMANTIC_READY)   # 03 의미 유사를 끄지 않는다
        self.assertNotEqual(engine.semantic_model_fingerprint, "")
        self.assertEqual(engine.semantic_ranking(DRAM_TASK)["ranking"], expected)


# ---------------------------------------------------------------------------
# 생성 도구·비교 도구와 같은 규칙
# ---------------------------------------------------------------------------

class SameRulesAsToolsTest(unittest.TestCase):
    EDGE_TERMS = ("D램", "DRAM", "D-RAM", "마이크로 LED", "memory", "UAV", "OLED", "3D", "IC", "battery", "Ni",
                  "x", "가", "1A", "C4", "a.b", "fly", "Σ")
    SYNTHETIC_TEXTS = ("16나노 이하급 D램 및 DRAMs, D-RAM", "cooled OLEDs와 AMOLED 마이크로LED 마이크로 LED",
                       "memories memoryless UAVs UAV3 3D 3Dx IC ICs", "batteries battery-powered Ni-Cd NiCd x-ray",
                       "가나다 1A 21A C4 C40 a.b a. b fly flies Σ σ")

    def test_term_matching_rules_identical(self):
        data = json.loads(REAL_DICTIONARY.read_text(encoding="utf-8"))
        terms = [t["term"] for g in data["groups"] for t in g["terms"]] + list(self.EDGE_TERMS)
        for term in terms:
            self.assertEqual(ns.normalize_term(term), tool.normalize_term(term), term)
            self.assertEqual(ns.term_pattern(term).pattern, tool.term_pattern(term).pattern, term)
            self.assertEqual(ns.term_pattern(term).flags, tool.term_pattern(term).flags, term)
            for text in self.SYNTHETIC_TEXTS:
                self.assertEqual(ns.count_term(term, text), tool.count_term(term, text), (term, text))
            self.assertEqual(ns.term_problem(term), tool.term_problem(term))

    def test_engine_counts_match_tool_counts(self):
        """엔진의 빠른 후보 거르기가 규칙을 바꾸지 않는다: 낱말마다 조항별 건수가 도구 규칙으로 센 값과 같다."""
        data = json.loads(REAL_DICTIONARY.read_text(encoding="utf-8"))
        terms = [t["term"] for g in data["groups"] for t in g["terms"]][::9] + ["laser", "memory", "D램", "battery"]
        for term in terms:
            expected = {doc.number: tool.count_term(term, doc.search_text) for doc in ENGINE.docs}
            expected = {number: count for number, count in expected.items() if count}
            actual = {number: hit[0] for number, hit in ENGINE.term_hits(term).items()}
            self.assertEqual(actual, expected, term)

    def test_dictionary_validation_identical(self):
        data = json.loads(REAL_DICTIONARY.read_text(encoding="utf-8"))
        self.assertEqual(ns.load_dictionary(REAL_DICTIONARY, CATALOGUE), tool.load_dictionary(REAL_DICTIONARY, CATALOGUE))

        def mutated(change, refingerprint=True):
            copy = json.loads(json.dumps(data))
            change(copy)
            if refingerprint:
                copy["fingerprint"] = canonical_hash({k: v for k, v in copy.items() if k != "fingerprint"})
            return copy

        def add_cycle(d):
            first = d["relations"][0]
            d["relations"].append(dict(narrow=first["broad"], broad=first["narrow"], note="", sources=[]))

        cases = [
            mutated(lambda d: d.__setitem__("format", "other"), True),
            mutated(lambda d: d["groups"][0]["terms"][0].__setitem__("count", 99), False),
            mutated(lambda d: d["groups"][1]["terms"].append(dict(d["groups"][0]["terms"][0])), True),
            mutated(lambda d: d["groups"][0].__setitem__("id", "Bad-Id"), True),
            mutated(lambda d: d["relations"].append(dict(narrow="nope", broad=d["groups"][0]["id"], note="",
                                                         sources=[])), True),
            mutated(add_cycle, True),
            mutated(lambda d: d.__setitem__("reviewed_on", "2026-13-01"), True),
            mutated(lambda d: [t.__setitem__("count", 0) for t in d["groups"][0]["terms"]], True),
            mutated(lambda d: d.__setitem__("extra", 1), True),
        ]
        for case in cases:
            with self.assertRaises(tool.SearchDictionaryError):
                tool.validate_dictionary(json.loads(json.dumps(case)))
            with self.assertRaises(ns.SearchDictionaryError):
                ns.validate_dictionary(json.loads(json.dumps(case)))
        self.assertEqual(ns.dictionary_fingerprint(data), tool.dictionary_fingerprint(data))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dup.json"
            path.write_text('{"format": 1, "format": 2}', encoding="utf-8")
            with self.assertRaises(ns.SearchDictionaryError):
                ns.load_dictionary(path)

    def test_chunks_and_vectors_match_comparison_tool(self):
        ids_, texts, counts = ns.clause_chunks(CATALOGUE)
        tool_ids, tool_texts, owners = compare.clause_chunks(CATALOGUE)
        self.assertEqual(ids_, tool_ids)
        self.assertEqual(texts, tool_texts)
        self.assertEqual(list(np.bincount(owners)), counts)
        self.assertEqual(ns.CHUNK_CHARS, compare.CHUNK_CHARS)
        ENGINE.ensure_semantic()
        reference = compare.PackedStaticEncoder(REAL_MODEL, compare.VARIANTS["potion_256_i8_pruned"])
        sample = texts[:40] + ["DRAM", "김치찌개", "", "디스플레이"]
        np.testing.assert_allclose(ENGINE._model.encode(sample), reference.encode(sample), atol=1e-6)
        stored = ENGINE._chunk_vectors[:40]
        np.testing.assert_allclose(stored, reference.encode(texts[:40]), atol=2e-3)
        self.assertEqual(ENGINE._chunk_vectors.shape, (len(texts), 256))

    def test_vectors_file_records(self):
        payload = json.loads(REAL_VECTORS.read_text(encoding="utf-8"))
        self.assertEqual(payload["fingerprint"], ns.vectors_fingerprint(payload))
        self.assertEqual(payload["catalogue_fingerprint"], CATALOGUE.fingerprint)
        self.assertEqual(payload["chunk_rule"], ns.CHUNK_RULE)
        self.assertEqual(len(payload["clause_ids"]), 507)
        info = json.loads((REAL_MODEL / ns.MODEL_INFO_NAME).read_text(encoding="utf-8"))
        hashes = {name: info["files"][name]["sha256"] for name in ns.MODEL_RUNTIME_FILES}
        self.assertEqual(payload["model"]["fingerprint"], ns.model_fingerprint(hashes))
        self.assertEqual(payload["model"]["files"], hashes)
        self.assertEqual(payload["vectors"]["sha256"], ns.file_sha256(REAL_VECTORS.with_name(ns.VECTORS_NPY)))

    def test_runtime_module_does_not_import_tools_or_hub(self):
        source = (PROGRAM / "notice_search.py").read_text(encoding="utf-8")
        self.assertNotIn("import tools", source)
        self.assertNotIn("from tools", source)
        self.assertNotIn("huggingface_hub", source.replace("HF_HUB", ""))
        self.assertNotIn("from_pretrained", source)


if __name__ == "__main__":
    unittest.main()
