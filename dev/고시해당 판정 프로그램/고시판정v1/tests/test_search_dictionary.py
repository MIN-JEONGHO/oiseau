"""관련어 사전 생성 도구(tools/build_search_dictionary) 시험.

- 합성 원문(Corpus)과 합성 관련어 파일로 형식 검증·원문 근거·중복·순환·지문·검수 반영을 확인한다.
  글은 모두 합성이며 실제 과제가 아니다.
- 실제 고시 자료(resources/notices)와 tools/synonyms/core.json으로 실제 생성이 되는지 확인한다.
  출력은 임시 폴더에만 쓴다. 실제 `resources/search_dictionary.json`은 새로 만들거나 고치지 않는다.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.build_search_dictionary import (
    IN_TEXT,
    NOT_IN_TEXT,
    REVIEW_COLUMN,
    REVIEW_DELETE,
    SHEET_GROUPS,
    SHEET_RELATIONS,
    SHEET_SUMMARY,
    Corpus,
    SearchDictionaryError,
    SynonymFileError,
    build,
    count_term,
    dictionary_fingerprint,
    load_dictionary,
    main,
    normalize_term,
    read_synonym_file,
)

PROGRAM = Path(__file__).resolve().parents[1]
REAL_SYNONYMS = PROGRAM / "tools" / "synonyms"
REAL_DICTIONARY = PROGRAM / "resources" / "search_dictionary.json"

# 합성 원문 세 항목. 'D램'·'메모리'·'반도체'·'디스플레이'·'OLED'·'레이저'가 나오고 'DRAM'·'드론'은 나오지 않는다.
SYNTHETIC_DOCS = (
    ("advanced:item:001", "16나노 이하급 D램 설계 기술\n반도체"),
    ("dual_use:control:3A001", "비휘발성 메모리 소자. Non-volatile memory devices; 반도체 소자"),
    ("advanced:item:009", "AMOLED 패널 기술 디스플레이\nOLED용 구동 칩. cooled laser 레이저"),
)


def corpus(docs=SYNTHETIC_DOCS):
    return Corpus(catalogue_id="synthetic", fingerprint="0" * 64, docs=list(docs))


def payload(groups, relations=(), scope="합성 범위"):
    return {"scope": scope, "groups": list(groups), "relations": list(relations)}


def group(group_id, *terms, note=None):
    entry = {"id": group_id, "terms": list(terms)}
    if note is not None:
        entry["note"] = note
    return entry


def rel(narrow, broad):
    return {"narrow": narrow, "broad": broad}


BASE_GROUPS = (
    group("dram", "D램", "DRAM", "디램", "D-RAM"),
    group("memory", "메모리", "memory"),
    group("semiconductor", "반도체", "semiconductor"),
)
BASE_RELATIONS = (rel("dram", "memory"), rel("memory", "semiconductor"))


def build_from(*payloads, docs=SYNTHETIC_DOCS, focus=None):
    files = [read_synonym_file(p, f"file{n}.json") for n, p in enumerate(payloads, 1)]
    return build(files, corpus(docs), focus=focus)


def messages(result):
    return [problem.message for problem in result.errors]


def quiet(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = function(*args, **kwargs)
    return code, out.getvalue()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None


class TermMatchingTests(unittest.TestCase):
    def test_whitespace_and_case_are_ignored(self):
        self.assertEqual(normalize_term(" 마이크로 LED "), "마이크로led")
        self.assertEqual(count_term("마이크로LED", "크기 30㎛ 이하 마이크로 LED를"), 1)
        self.assertEqual(count_term("리튬 이차전지", "차세대 리튬이차전지와 리튬\n이차전지"), 2)
        self.assertEqual(count_term("oled", "OLED용 DDI"), 1)

    def test_latin_terms_need_word_start_and_allow_plural(self):
        self.assertEqual(count_term("OLED", "cooled laser"), 0)
        self.assertEqual(count_term("NAND", "ion and lithium"), 0)
        self.assertEqual(count_term("UAV", "unmanned aerial vehicles (UAVs)"), 1)
        self.assertEqual(count_term("laser", "lasers and laser"), 2)
        self.assertEqual(count_term("memory", "non-volatile memories and memory"), 2)
        self.assertEqual(count_term("memory", "memoryless"), 0)
        self.assertEqual(count_term("D램", "16나노 이하급 D램"), 1)


class FileFormatTests(unittest.TestCase):
    def assert_format_error(self, data):
        with self.assertRaises(SynonymFileError):
            read_synonym_file(data, "bad.json")

    def test_valid_file(self):
        file = read_synonym_file(payload(BASE_GROUPS, BASE_RELATIONS), "ok.json")
        self.assertEqual([g["id"] for g in file.groups], ["dram", "memory", "semiconductor"])
        self.assertEqual(len(file.relations), 2)

    def test_shape_errors(self):
        self.assert_format_error({"groups": [], "relations": []})                       # scope 없음
        self.assert_format_error({**payload(BASE_GROUPS), "extra": 1})                    # 모르는 키
        self.assert_format_error(payload([group("Bad Id", "반도체")]))                     # id 모양
        self.assert_format_error(payload([group("x")]))                                    # 낱말 없음
        self.assert_format_error(payload([group("x", "")]))                                # 빈 낱말
        self.assert_format_error(payload([group("x", " 반도체")]))                          # 앞뒤 공백
        self.assert_format_error(payload([group("x", "반도체"), group("x", "메모리")]))       # 한 파일 안 id 중복
        self.assert_format_error(payload([group("x", "마이크로 LED", "마이크로LED")]))       # 묶음 안 공백만 다른 낱말
        self.assert_format_error(payload([group("x", "반도체")], [rel("x", "x")]))           # 자기 자신 관계
        self.assert_format_error(payload([group("x", "반도체")], [{"narrow": "x"}]))         # 관계 필드


class ValidationTests(unittest.TestCase):
    def test_base_dictionary_builds(self):
        result = build_from(payload(BASE_GROUPS, BASE_RELATIONS))
        self.assertEqual(messages(result), [])
        self.assertTrue(result.ok)

    def test_group_without_any_term_in_text_is_an_error(self):
        result = build_from(payload([*BASE_GROUPS, group("drone", "드론", "UAV")]))
        self.assertFalse(result.ok)
        self.assertTrue(any("drone" in m and "원문" in m for m in messages(result)), messages(result))

    def test_some_terms_missing_from_text_are_marked_not_errors(self):
        result = build_from(payload(BASE_GROUPS, BASE_RELATIONS))
        terms = {t["term"]: t for t in result.groups["dram"]["terms"]}
        self.assertGreater(terms["D램"]["count"], 0)
        self.assertEqual(terms["DRAM"]["count"], 0)
        self.assertEqual(terms["디램"]["count"], 0)
        self.assertIn("DRAM", [t["term"] for t in result.terms_not_in_text()])

    def test_same_term_in_two_groups_is_an_error(self):
        result = build_from(payload([*BASE_GROUPS, group("chip", "반도체 칩", "Memory")]))
        self.assertFalse(result.ok)
        self.assertTrue(any("memory" in m.casefold() and "chip" in m for m in messages(result)), messages(result))

    def test_same_term_in_two_groups_across_files_is_an_error(self):
        result = build_from(payload(BASE_GROUPS), payload([group("display", "디스플레이", "D램")]))
        self.assertFalse(result.ok)

    def test_same_id_across_files_is_merged(self):
        result = build_from(payload(BASE_GROUPS, BASE_RELATIONS), payload([group("memory", "메모리", "비휘발성 메모리")]))
        self.assertTrue(result.ok, messages(result))
        terms = [t["term"] for t in result.groups["memory"]["terms"]]
        self.assertEqual(terms, ["메모리", "memory", "비휘발성 메모리"])
        self.assertEqual(result.groups["memory"]["sources"], ["file1.json", "file2.json"])

    def test_relation_cycle_is_an_error(self):
        result = build_from(payload(BASE_GROUPS, [*BASE_RELATIONS, rel("semiconductor", "dram")]))
        self.assertFalse(result.ok)
        self.assertTrue(any("순환" in m for m in messages(result)), messages(result))

    def test_two_node_cycle_across_files_is_an_error(self):
        result = build_from(payload(BASE_GROUPS, BASE_RELATIONS), payload([], [rel("memory", "dram")]))
        self.assertFalse(result.ok)
        self.assertTrue(any("순환" in m for m in messages(result)), messages(result))

    def test_relation_to_missing_group_is_an_error(self):
        result = build_from(payload(BASE_GROUPS, [*BASE_RELATIONS, rel("dram", "electronics")]))
        self.assertFalse(result.ok)
        self.assertTrue(any("electronics" in m for m in messages(result)), messages(result))

    def test_relation_may_point_to_group_in_another_file(self):
        result = build_from(payload(BASE_GROUPS), payload([group("display", "디스플레이")], [rel("dram", "memory")]))
        self.assertTrue(result.ok, messages(result))
        self.assertEqual(result.relations[0]["sources"], ["file2.json"])

    def test_focus_limits_problems_to_that_file(self):
        result = build_from(payload([group("drone", "드론")]), payload(BASE_GROUPS, BASE_RELATIONS),
                            focus="file2.json")
        self.assertEqual(result.focus_errors(), [])
        self.assertFalse(result.ok)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        (self.dir / "syn").mkdir()
        write_json(self.dir / "syn" / "a.json", payload(BASE_GROUPS, BASE_RELATIONS))
        self.output = self.dir / "out" / "search_dictionary.json"
        self.review = self.dir / "out" / "관련어_검수.xlsx"
        code, self.log = quiet(main, ["--synonyms-dir", str(self.dir / "syn"), "--output", str(self.output),
                                      "--review-xlsx", str(self.review)], corpus=corpus())
        self.assertEqual(code, 0, self.log)

    def test_round_trip_and_fields(self):
        data = load_dictionary(self.output)
        self.assertEqual(data["fingerprint"], dictionary_fingerprint(data))
        self.assertIsNone(data["reviewed_on"])
        self.assertTrue(data["generated_at"])
        self.assertEqual(data["catalogue_id"], "synthetic")
        self.assertEqual([g["id"] for g in data["groups"]], ["dram", "memory", "semiconductor"])
        self.assertEqual(data["relations"][0]["narrow"], "dram")
        self.assertEqual(data["relations"][0]["broad"], "memory")
        dram = {t["term"]: t for t in data["groups"][0]["terms"]}
        self.assertEqual(dram["D램"]["count"], 1)
        self.assertEqual(dram["D램"]["clauses"], 1)
        self.assertEqual(dram["DRAM"]["count"], 0)

    def test_fingerprint_does_not_depend_on_key_order(self):
        data = load_dictionary(self.output)
        reordered = dict(reversed(list(data.items())))
        self.assertEqual(dictionary_fingerprint(reordered), data["fingerprint"])

    def test_fingerprint_mismatch_fails_loading(self):
        data = json.loads(self.output.read_text(encoding="utf-8"))
        data["groups"][0]["terms"].append({"term": "디램2", "count": 0, "clauses": 0})
        self.output.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SearchDictionaryError):
            load_dictionary(self.output)

    def test_changed_review_date_without_new_fingerprint_fails_loading(self):
        data = json.loads(self.output.read_text(encoding="utf-8"))
        data["reviewed_on"] = "2026-11-07"
        self.output.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SearchDictionaryError):
            load_dictionary(self.output)

    def test_missing_file_fails_loading(self):
        with self.assertRaises(SearchDictionaryError):
            load_dictionary(self.dir / "없음.json")

    def test_review_workbook_sheets(self):
        import openpyxl
        workbook = openpyxl.load_workbook(self.review)
        self.assertEqual(workbook.sheetnames[:3], [SHEET_GROUPS, SHEET_RELATIONS, SHEET_SUMMARY])
        rows = list(workbook[SHEET_GROUPS].iter_rows(values_only=True))
        header = rows[0]
        self.assertIn(REVIEW_COLUMN, header)
        by_term = {row[header.index("낱말")]: row for row in rows[1:]}
        self.assertEqual(by_term["DRAM"][header.index("원문 확인")], NOT_IN_TEXT)
        self.assertEqual(by_term["D램"][header.index("원문 확인")], IN_TEXT)
        self.assertEqual(by_term["D램"][header.index("원문 등장 건수")], 1)
        relation_rows = list(workbook[SHEET_RELATIONS].iter_rows(values_only=True))
        self.assertIn(REVIEW_COLUMN, relation_rows[0])
        self.assertEqual(len(relation_rows), 3)

    def test_reviewed_on_option_is_recorded(self):
        code, log = quiet(main, ["--synonyms-dir", str(self.dir / "syn"), "--output", str(self.output),
                                 "--review-xlsx", str(self.review), "--reviewed-on", "2026-11-07"], corpus=corpus())
        self.assertEqual(code, 0, log)
        self.assertEqual(load_dictionary(self.output)["reviewed_on"], "2026-11-07")
        code, log = quiet(main, ["--synonyms-dir", str(self.dir / "syn"), "--output", str(self.output),
                                 "--review-xlsx", str(self.review), "--reviewed-on", "2026-13-40"], corpus=corpus())
        self.assertEqual(code, 2)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.syn = self.dir / "syn"
        self.syn.mkdir()
        self.output = self.dir / "out" / "search_dictionary.json"
        self.review = self.dir / "out" / "관련어_검수.xlsx"

    def run_main(self, *extra):
        return quiet(main, ["--synonyms-dir", str(self.syn), "--output", str(self.output),
                            "--review-xlsx", str(self.review), *extra], corpus=corpus())

    def test_check_writes_nothing(self):
        write_json(self.syn / "a.json", payload(BASE_GROUPS, BASE_RELATIONS))
        before = sorted(p.relative_to(self.dir) for p in self.dir.rglob("*"))
        code, log = self.run_main("--check", str(self.syn / "a.json"))
        self.assertEqual(code, 0, log)
        self.assertEqual(sorted(p.relative_to(self.dir) for p in self.dir.rglob("*")), before)
        self.assertIn("DRAM", log)   # 원문에 없는 낱말을 알린다

    def test_check_reports_problems_with_nonzero_exit(self):
        write_json(self.syn / "a.json", payload([*BASE_GROUPS, group("drone", "드론")], BASE_RELATIONS))
        code, log = self.run_main("--check", str(self.syn / "a.json"))
        self.assertEqual(code, 1, log)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.review.exists())

    def test_check_resolves_relations_against_other_files(self):
        write_json(self.syn / "a.json", payload(BASE_GROUPS))
        write_json(self.syn / "b.json", payload([group("display", "디스플레이")], [rel("dram", "memory")]))
        code, log = self.run_main("--check", str(self.syn / "b.json"))
        self.assertEqual(code, 0, log)

    def test_format_error_exit_code(self):
        write_json(self.syn / "a.json", {"scope": "x", "groups": "틀림", "relations": []})
        code, log = self.run_main()
        self.assertEqual(code, 2, log)
        self.assertFalse(self.output.exists())

    def test_build_with_errors_writes_review_but_not_dictionary(self):
        write_json(self.syn / "a.json", payload([*BASE_GROUPS, group("drone", "드론")], BASE_RELATIONS))
        code, log = self.run_main()
        self.assertEqual(code, 1, log)
        self.assertFalse(self.output.exists())
        self.assertTrue(self.review.exists())

    def test_no_synonym_files_is_an_error(self):
        code, log = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertFalse(self.output.exists())


class ApplyReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.syn = self.dir / "syn"
        self.syn.mkdir()
        write_json(self.syn / "a.json", payload(
            [*BASE_GROUPS, group("display", "디스플레이", "display"), group("oled", "OLED", "오엘이디")],
            [*BASE_RELATIONS, rel("oled", "display"), rel("oled", "semiconductor")]))
        write_json(self.syn / "b.json", payload([group("memory", "메모리", "기억소자")]))
        self.output = self.dir / "out" / "search_dictionary.json"
        self.review = self.dir / "out" / "관련어_검수.xlsx"
        code, log = self.run_main()
        self.assertEqual(code, 0, log)

    def run_main(self, *extra):
        return quiet(main, ["--synonyms-dir", str(self.syn), "--output", str(self.output),
                            "--review-xlsx", str(self.review), *extra], corpus=corpus())

    def fill_review(self, group_marks=None, relation_marks=None, path=None):
        """검수 엑셀의 '검수 결과' 칸을 채워 다른 이름으로 저장한다."""
        import openpyxl
        workbook = openpyxl.load_workbook(self.review)
        sheet = workbook[SHEET_GROUPS]
        header = [cell.value for cell in sheet[1]]
        for row in sheet.iter_rows(min_row=2):
            key = (row[header.index("묶음 id")].value, row[header.index("낱말")].value)
            if group_marks and key in group_marks:
                row[header.index(REVIEW_COLUMN)].value = group_marks[key]
        sheet = workbook[SHEET_RELATIONS]
        header = [cell.value for cell in sheet[1]]
        for row in sheet.iter_rows(min_row=2):
            key = (row[header.index("아래 묶음")].value, row[header.index("위 묶음")].value)
            if relation_marks and key in relation_marks:
                row[header.index(REVIEW_COLUMN)].value = relation_marks[key]
        path = path or self.dir / "검수함.xlsx"
        workbook.save(path)
        return path

    def synonyms(self, name):
        return json.loads((self.syn / name).read_text(encoding="utf-8"))

    def test_delete_and_replace_terms_and_relations(self):
        reviewed = self.fill_review(
            group_marks={("dram", "D-RAM"): REVIEW_DELETE, ("dram", "디램"): "디-램",
                         ("memory", "기억소자"): REVIEW_DELETE},
            relation_marks={("oled", "semiconductor"): REVIEW_DELETE, ("memory", "semiconductor"): "memory → semiconductor"})
        code, log = self.run_main("--apply-review", str(reviewed), "--reviewed-on", "2026-11-07")
        self.assertEqual(code, 0, log)
        a = self.synonyms("a.json")
        dram = next(g for g in a["groups"] if g["id"] == "dram")
        self.assertEqual(dram["terms"], ["D램", "DRAM", "디-램"])
        self.assertNotIn({"narrow": "oled", "broad": "semiconductor"}, a["relations"])
        b = self.synonyms("b.json")
        self.assertEqual(b["groups"][0]["terms"], ["메모리"])
        data = load_dictionary(self.output)
        self.assertEqual(data["reviewed_on"], "2026-11-07")
        self.assertNotIn(("oled", "semiconductor"), [(r["narrow"], r["broad"]) for r in data["relations"]])
        self.assertIn("삭제", log)
        self.assertIn("디-램", log)

    def test_relation_value_with_new_broad(self):
        reviewed = self.fill_review(relation_marks={("oled", "semiconductor"): "memory"})
        code, log = self.run_main("--apply-review", str(reviewed))
        self.assertEqual(code, 0, log)
        pairs = [(r["narrow"], r["broad"]) for r in self.synonyms("a.json")["relations"]]
        self.assertIn(("oled", "memory"), pairs)
        self.assertNotIn(("oled", "semiconductor"), pairs)

    def test_deleting_every_term_removes_group_and_its_relations(self):
        reviewed = self.fill_review(group_marks={("oled", "OLED"): REVIEW_DELETE, ("oled", "오엘이디"): REVIEW_DELETE})
        code, log = self.run_main("--apply-review", str(reviewed))
        self.assertEqual(code, 0, log)
        a = self.synonyms("a.json")
        self.assertNotIn("oled", [g["id"] for g in a["groups"]])
        self.assertFalse([r for r in a["relations"] if "oled" in (r["narrow"], r["broad"])])
        self.assertIn("oled", log)

    def test_review_that_breaks_validation_writes_nothing(self):
        before = {name: (self.syn / name).read_bytes() for name in ("a.json", "b.json")}
        output_before = self.output.read_bytes()
        # 원문에 있는 유일한 낱말을 지우면 묶음이 원문 근거를 잃는다 → 오류, 아무것도 쓰지 않는다.
        reviewed = self.fill_review(group_marks={("dram", "D램"): REVIEW_DELETE})
        code, log = self.run_main("--apply-review", str(reviewed))
        self.assertEqual(code, 1, log)
        self.assertEqual({name: (self.syn / name).read_bytes() for name in before}, before)
        self.assertEqual(self.output.read_bytes(), output_before)

    def test_unknown_row_is_an_error(self):
        import openpyxl
        workbook = openpyxl.load_workbook(self.review)
        sheet = workbook[SHEET_GROUPS]
        header = [cell.value for cell in sheet[1]]
        row = [None] * len(header)
        row[header.index("묶음 id")] = "dram"
        row[header.index("낱말")] = "없는낱말"
        row[header.index(REVIEW_COLUMN)] = REVIEW_DELETE
        sheet.append(row)
        reviewed = self.dir / "검수함.xlsx"
        workbook.save(reviewed)
        before = (self.syn / "a.json").read_bytes()
        code, log = self.run_main("--apply-review", str(reviewed))
        self.assertNotEqual(code, 0, log)
        self.assertEqual((self.syn / "a.json").read_bytes(), before)

    def test_blank_review_keeps_everything_and_records_date(self):
        before = {name: (self.syn / name).read_bytes() for name in ("a.json", "b.json")}
        reviewed = self.fill_review()
        code, log = self.run_main("--apply-review", str(reviewed), "--reviewed-on", "2026-11-08")
        self.assertEqual(code, 0, log)
        self.assertEqual({name: (self.syn / name).read_bytes() for name in before}, before)
        self.assertEqual(load_dictionary(self.output)["reviewed_on"], "2026-11-08")
        # 내용이 같으면 다시 생성해도 검수 일자를 유지한다.
        code, log = self.run_main()
        self.assertEqual(code, 0, log)
        self.assertEqual(load_dictionary(self.output)["reviewed_on"], "2026-11-08")


class RealCatalogueTests(unittest.TestCase):
    """실제 고시 자료와 core.json으로 생성한다. 출력은 임시 폴더에만."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.temp.name)
        (cls.dir / "syn").mkdir()
        shutil.copyfile(REAL_SYNONYMS / "core.json", cls.dir / "syn" / "core.json")
        cls.output = cls.dir / "out" / "search_dictionary.json"
        cls.review = cls.dir / "out" / "관련어_검수.xlsx"
        cls.real_before = file_digest(REAL_DICTIONARY)
        cls.code, cls.log = quiet(main, ["--synonyms-dir", str(cls.dir / "syn"), "--output", str(cls.output),
                                         "--review-xlsx", str(cls.review)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_core_build_succeeds(self):
        self.assertEqual(self.code, 0, self.log)
        data = load_dictionary(self.output)
        self.assertTrue(self.review.exists())
        self.assertEqual(file_digest(REAL_DICTIONARY), self.real_before)   # 실제 사전을 건드리지 않았다
        groups = {g["id"]: g for g in data["groups"]}
        broad = {}
        for relation in data["relations"]:
            broad.setdefault(relation["narrow"], set()).add(relation["broad"])

        def group_of(term):
            key = normalize_term(term)
            found = [g for g in groups.values() if key in {normalize_term(t["term"]) for t in g["terms"]}]
            self.assertEqual(len(found), 1, term)
            return found[0]["id"]

        # spec 5 질의에 필요한 관계
        self.assertEqual(group_of("DRAM"), group_of("D램"))
        self.assertEqual(group_of("디램"), group_of("D램"))
        self.assertIn(group_of("메모리"), broad[group_of("D램")])
        self.assertIn(group_of("반도체"), broad[group_of("메모리")])
        for term in ("OLED", "AMOLED", "LCD", "마이크로 LED"):
            reachable = set(broad.get(group_of(term), ()))
            for parent in list(reachable):
                reachable |= broad.get(parent, set())
            self.assertIn(group_of("디스플레이"), reachable, term)
        self.assertIn(group_of("배터리"), broad[group_of("이차전지")])
        self.assertEqual(group_of("드론"), group_of("무인항공기"))
        self.assertEqual(group_of("UAV"), group_of("무인항공기"))
        self.assertIn(group_of("암호"), broad[group_of("암호화")])
        self.assertIn(group_of("정보보안"), broad[group_of("암호")])
        self.assertTrue(group_of("레이저"))
        # '메모리 반도체'처럼 원문에 없는 중간 낱말을 쓰지 않는다.
        self.assertNotIn("메모리반도체", {normalize_term(t["term"]) for g in groups.values() for t in g["terms"]})

    def test_every_group_is_grounded_in_text(self):
        data = load_dictionary(self.output)
        for g in data["groups"]:
            self.assertTrue(any(t["count"] > 0 for t in g["terms"]), g["id"])

    def test_shipped_dictionary_is_valid_when_present(self):
        if not REAL_DICTIONARY.exists():
            self.skipTest("resources/search_dictionary.json 없음")
        data = load_dictionary(REAL_DICTIONARY)
        self.assertEqual(data["fingerprint"], dictionary_fingerprint(data))


if __name__ == "__main__":
    unittest.main()
