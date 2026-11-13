"""기준값 표 생성 도구(tools/build_threshold_table)와 실행용 로더(threshold_table) 시험.

- 합성 기준본 보기(CatalogueView)와 합성 추출 파일로 4.2 검증 규칙·구조 변환·누락·중복을 확인한다.
  글은 모두 합성이며 실제 과제가 아니다.
- 실제 복사본(resources/notices)으로는 structured 57개 잎만 넣고 전체 생성을 돌려 41개 항목이 들어가고
  나머지 466개가 누락으로 드러나는지 확인한다. 출력은 임시 폴더에만 쓴다. `resources/thresholds.json`은 남기지 않는다.
"""
import contextlib
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import paths
from notice_catalogue import NOTE_FIELD, canonical_hash, clause_index, load_catalogue, numeric_leaves
from threshold_table import ThresholdTableError, load_threshold_table
from tools.build_threshold_table import (
    BODY_SOURCE,
    STATUS_FAILED,
    STATUS_HAS,
    STATUS_NONE,
    CatalogueView,
    build,
    main,
    read_extracted,
    write_review,
    write_table,
)

PROGRAM = Path(__file__).resolve().parents[1]
ARTICLE_4_TEXT = ("제4조(국가첨단전략기술의 범위) 국가첨단전략기술은 별표의 각 기술에 특화되어 양산을 목적으로 "
                  "개발되거나 양산에 사용되는 기술이다.")


def leaf(predicate_id, text, anchor, **numeric):
    """조건 트리 잎. numeric 인자가 있으면 숫자 잎, 없으면 정성 잎."""
    node = dict(predicate_id=predicate_id, text=text, source_anchor=anchor, subject=numeric.pop("subject", "대상"))
    if numeric:
        node.update(type="numeric", **numeric)
    else:
        node.update(type="qualitative", reason="합성")
    return node


def clause(clause_id, family, text, *, code="", title="", field="시험", refs=(), condition=None, anchor=None):
    anchor = anchor or f"raw/{family}.txt#{clause_id}"
    if condition is None:
        condition = dict(type="unsupported", predicate_id=clause_id + ":p", text=text, source_anchor=anchor,
                         subject="원문", reason="합성")
    return dict(clause_id=clause_id, family=family, code=code, title=title or clause_id, field=field, text=text,
                qualifier_refs=list(refs), condition=condition, source_anchor=anchor)


def make_view(extra_items=()):
    """합성 기준본 보기: 첨단 1(숫자 조건)·핵심 1·이중용도 2·군용 1 항목과 공통 정의 3개."""
    note4 = clause("advanced:article:4", "advanced", ARTICLE_4_TEXT, title="제4조", field=NOTE_FIELD)
    note_core = clause("core:article:2", "core", "제2조(정의) 합성 정의문.", field=NOTE_FIELD)
    note_du = clause("dual_use:notes:t01:r01", "dual_use", "주: 합성 공통 주석. 두께 기준 0.254 mm 를 초과하는 것.",
                     field=NOTE_FIELD)
    adv_anchor = "raw/advanced.txt#advanced:item:001"
    adv1 = clause(
        "advanced:item:001", "advanced", "16나노 이하급 D램에 해당하는 설계 기\n\n 술", title="16나노 이하급 D램",
        field="반도체", refs=["advanced:article:4"], anchor=adv_anchor,
        condition=dict(type="all", children=[
            leaf("advanced:item:001:numeric", "16나노 이하급", adv_anchor, subject="D램 공정노드", operator="le",
                 threshold="16", unit="nm"),
            leaf("advanced:item:001:production", ARTICLE_4_TEXT, "raw/advanced-body.html#Y0004000000"),
        ]))
    core1 = clause("core:item:001", "core", "30나노 이하급 D램에 해당되는 설계 기술", title="30나노 D램", field="반도체",
                   refs=["core:article:2"])
    du_text = ("[통제번호·원문 메타정보]\n1A003\n(IL1.A.3)\n\n[국문 원문]\n필름 형태의 제조품으로서 다음 중 한 개의 특성을 "
               "지닌 것:\na. 두께가 0.254 mm 를 초과하는 것; 또는\nb. 탄소로 코팅된 것\n\n[영문 원문]\nManufactures "
               "having any of the following:\na. A thickness exceeding 0.254 mm; or\nb. Coated with carbon.\n")
    du1 = clause("dual_use:control:1A003", "dual_use", du_text, code="1A003", title="1A003 통제기준 원문", field="1부",
                 refs=["dual_use:notes:t01:r01"])
    du0 = clause("dual_use:control:0A001", "dual_use", "[통제번호·원문 메타정보]\n0A001\n\n[국문 원문]\n원자로로서 "
                 "다음의 것:\n출력이 15,000 kW 이상인 것; 1만 시간 이상 운전; 3천톤 이상\n", code="0A001",
                 title="0A001 통제기준 원문", field="0부", refs=["dual_use:notes:t01:r01"])
    mil1 = clause("military:control:ML1", "military", "[통제번호·원문 메타정보]\nML1\n\n[국문 원문]\n구경이 20mm 미만인 "
                  "활강무기\n", code="ML1", title="ML1 통제기준 원문", field="군용")
    clauses = [note4, note_core, note_du, adv1, core1, du1, du0, mil1, *extra_items]
    items = [dict(clause_id=c["clause_id"], family=c["family"], code=c["code"], title=c["title"], field=c["field"])
             for c in clauses if c["field"] != NOTE_FIELD]
    return CatalogueView(catalogue_id="synthetic", fingerprint="0" * 64, items=items,
                         clauses={c["clause_id"]: c for c in clauses})


def threshold(**kwargs):
    base = dict(subject="두께", operator="gt", value="0.254", unit="mm", quote="두께가 0.254 mm 를 초과하는 것",
                quote_source=BODY_SOURCE)
    base.update(kwargs)
    return base


def extracted(items, scope=None, path="synthetic.json"):
    """추출 파일을 메모리에서 만든다. scope 기본값은 네 범위 전부."""
    return read_extracted(dict(scope=scope or dict(families=["advanced", "core", "dual_use", "military"]), items=items),
                          path)


def full_items(**overrides):
    """합성 보기의 모든 항목을 덮는 추출 항목 목록. overrides로 항목 하나를 바꿀 수 있다."""
    items = {
        "advanced:item:001": dict(clause_id="advanced:item:001", branches=[], checks=[]),
        "core:item:001": dict(clause_id="core:item:001", branches=[dict(label="", thresholds=[
            dict(subject="D램 공정노드", operator="le", value="30", unit="nm", quote="30나노 이하급",
                 quote_source=BODY_SOURCE)], text="")], checks=[]),
        "dual_use:control:1A003": dict(clause_id="dual_use:control:1A003", branches=[
            dict(label="a", thresholds=[threshold()], text=""),
            dict(label="b", thresholds=[], text="b. 탄소로 코팅된 것")], checks=[]),
        "dual_use:control:0A001": dict(clause_id="dual_use:control:0A001", branches=[dict(label="", thresholds=[
            dict(subject="출력", operator="ge", value="15000", unit="kW", quote="출력이 15,000 kW 이상인 것",
                 quote_source=BODY_SOURCE),
            dict(subject="운전 시간", operator="ge", value="10000", unit="시간", quote="1만 시간 이상",
                 quote_source=BODY_SOURCE),
            dict(subject="질량", operator="ge", value="3000", unit="톤", quote="3천톤 이상", quote_source=BODY_SOURCE),
        ], text="")], checks=[]),
        "military:control:ML1": dict(clause_id="military:control:ML1", branches=[dict(label="", thresholds=[
            dict(subject="구경", operator="lt", value="20", unit="mm", quote="구경이 20mm 미만인", quote_source=BODY_SOURCE)],
            text="")], checks=[dict(quote="활강무기", source=BODY_SOURCE)]),
    }
    items.update(overrides)
    return list(items.values())


def record_of(result, clause_id):
    return next(r for r in result.records if r["clause_id"] == clause_id)


def du_item(**threshold_overrides):
    """이중용도 1A003 항목 하나만 든 추출 항목(검증 규칙 시험용)."""
    return dict(clause_id="dual_use:control:1A003",
                branches=[dict(label="a", thresholds=[threshold(**threshold_overrides)], text="")], checks=[])


class ValidationTests(unittest.TestCase):
    """4.2 검증: 어긋나면 채택하지 않고 rejected에 사유와 함께 남긴다."""

    def setUp(self):
        self.view = make_view()

    def run_one(self, item):
        result = build(self.view, [extracted([item], scope=dict(families=["dual_use"], code_prefixes=["1"]))])
        self.assertEqual(result.errors, [])
        return record_of(result, "dual_use:control:1A003")

    def test_accepts_valid_threshold(self):
        record = self.run_one(du_item())
        self.assertEqual(record["numeric_status"], STATUS_HAS)
        self.assertEqual(record["rejected"], [])
        accepted = record["branches"][0]["thresholds"][0]
        self.assertEqual((accepted["operator"], accepted["value"], accepted["unit"], accepted["origin"]),
                         ("gt", "0.254", "mm", "extracted"))
        self.assertEqual(accepted["threshold_id"], "dual_use:control:1A003:b1:t1")
        self.assertEqual(record["branches"][0]["branch_id"], "dual_use:control:1A003:b1")

    def assert_rejected(self, item, reason_part):
        record = self.run_one(item)
        self.assertEqual(record["numeric_status"], STATUS_FAILED)
        self.assertEqual(record["branches"], [], "채택 실패한 기준값이 갈래에 남아 있다")
        self.assertEqual(len(record["rejected"]), 1)
        rejected = record["rejected"][0]
        self.assertEqual(set(rejected), {"branch_id", "subject", "quote", "reason"})
        self.assertIn(reason_part, rejected["reason"])
        return rejected

    def test_quote_not_in_source(self):
        self.assert_rejected(du_item(quote="두께가 0.255 mm 를 초과하는 것"), "인용")

    def test_value_differs_from_quote(self):
        self.assert_rejected(du_item(value="0.25"), "수")

    def test_comparator_direction_mismatch(self):
        self.assert_rejected(du_item(operator="ge"), "비교어")

    def test_comparator_missing(self):
        self.assert_rejected(du_item(quote="두께가 0.254 mm", value="0.254"), "비교어")

    def test_unit_outside_alias_table(self):
        rejected = self.assert_rejected(du_item(unit="mili", quote="두께가 0.254 mm 를 초과하는 것"), "단위")
        self.assertEqual(rejected["subject"], "두께")

    def test_unit_absent_from_quote(self):
        self.assert_rejected(du_item(unit="cm"), "단위")

    def test_unlinked_definition_source(self):
        item = du_item(quote="합성 정의문", quote_source="core:article:2", value="0.254")
        self.assert_rejected(item, "qualifier_refs")

    def test_linked_definition_source_is_accepted(self):
        record = self.run_one(du_item(quote="두께 기준 0.254 mm 를 초과하는 것", quote_source="dual_use:notes:t01:r01"))
        self.assertEqual(record["numeric_status"], STATUS_HAS)
        self.assertEqual(record["branches"][0]["thresholds"][0]["quote_source"], "dual_use:notes:t01:r01")

    def test_non_decimal_value(self):
        self.assert_rejected(du_item(value="FHD", quote="두께가 0.254 mm 를 초과하는 것"), "10진수")

    def test_invalid_operator(self):
        self.assert_rejected(du_item(operator="eq"), "operator")

    def test_failed_check_is_rejected(self):
        item = dict(clause_id="dual_use:control:1A003", branches=[],
                    checks=[dict(quote="없는 글", source=BODY_SOURCE), dict(quote="합성 정의문", source="core:article:2")])
        record = self.run_one(item)
        self.assertEqual(record["checks"], [])
        self.assertEqual(len(record["rejected"]), 2)
        self.assertEqual(record["numeric_status"], STATUS_FAILED)

    def test_unit_alias_in_quote_is_accepted(self):
        item = dict(clause_id="dual_use:control:0A001", branches=[dict(label="", thresholds=[
            dict(subject="질량", operator="ge", value="3000", unit="t", quote="3천톤 이상", quote_source=BODY_SOURCE)],
            text="")], checks=[])
        result = build(self.view, [extracted([item], scope=dict(families=["dual_use"], code_prefixes=["0"]))])
        record = record_of(result, "dual_use:control:0A001")
        self.assertEqual(record["numeric_status"], STATUS_HAS)
        self.assertEqual(record["branches"][0]["thresholds"][0]["unit"], "t")

    def test_comma_and_korean_numerals_and_line_breaks(self):
        """쉼표·만·천 표기는 같은 수로 보고, 줄바꿈을 걸친 인용은 공백 하나로 맞춰 찾는다."""
        extra = clause("advanced:item:002", "advanced", "고에너지밀도 배터리(에너지밀도가\n\n   280Wh/kg 이상인 파우치형)",
                       field="배터리", refs=["advanced:article:4"])
        view = make_view([extra])
        items = full_items()
        items.append(dict(clause_id="advanced:item:002", branches=[dict(label="", thresholds=[
            dict(subject="에너지밀도", operator="ge", value="280", unit="Wh/kg", quote="에너지밀도가 280Wh/kg 이상인",
                 quote_source=BODY_SOURCE)], text="")], checks=[]))
        result = build(view, [extracted(items)])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.missing, [])
        self.assertEqual(record_of(result, "advanced:item:002")["numeric_status"], STATUS_HAS)
        record = record_of(result, "dual_use:control:0A001")
        self.assertEqual(record["numeric_status"], STATUS_HAS)
        self.assertEqual([t["value"] for t in record["branches"][0]["thresholds"]], ["15000", "10000", "3000"])
        self.assertEqual([t["unit"] for t in record["branches"][0]["thresholds"]], ["kW", "시간", "t"])
        self.assertEqual(record["rejected"], [])


class StructureTests(unittest.TestCase):
    """structured 조건 트리 옮기기, 제4조 확인, 상태값, 제목."""

    def test_structured_leaf_is_copied_without_validation(self):
        view = make_view()
        result = build(view, [extracted(full_items())])
        self.assertEqual(result.errors, [])
        record = record_of(result, "advanced:item:001")
        self.assertEqual(record["numeric_status"], STATUS_HAS)
        self.assertEqual(len(record["branches"]), 1)
        accepted = record["branches"][0]["thresholds"][0]
        self.assertEqual(accepted["origin"], "structured")
        self.assertEqual((accepted["operator"], accepted["value"], accepted["unit"], accepted["quote"]),
                         ("le", "16", "nm", "16나노 이하급"))
        self.assertEqual(accepted["quote_source"], BODY_SOURCE)
        self.assertEqual(record["title"], "16나노 이하급 D램")

    def test_advanced_article_4_check_always_present(self):
        view = make_view()
        result = build(view, [extracted(full_items())])
        for clause_id in ("advanced:item:001",):
            checks = record_of(result, clause_id)["checks"]
            self.assertIn(dict(quote=ARTICLE_4_TEXT, source="advanced:article:4"), checks)
            self.assertEqual(sum(1 for c in checks if c["source"] == "advanced:article:4"), 1)
        extra = clause("advanced:item:003", "advanced", "합성 첨단 항목", field="배터리", refs=["advanced:article:4"])
        view = make_view([extra])
        items = full_items()
        items.append(dict(clause_id="advanced:item:003", branches=[], checks=[]))
        result = build(view, [extracted(items)])
        self.assertEqual(record_of(result, "advanced:item:003")["checks"],
                         [dict(quote=ARTICLE_4_TEXT, source="advanced:article:4")])
        self.assertNotIn("advanced:article:4", [c["source"] for c in record_of(result, "core:item:001")["checks"]])

    def test_eq_becomes_ge_with_check(self):
        anchor = "raw/core.txt#core:item:060"
        item = clause("core:item:060", "core", "초고해상도(고도 500Km기준 50cm이하급) 광학위성", field="우주",
                      title="초고해상도(고도 500Km기준 50cm이하급) 광학위성", refs=["core:article:2"], anchor=anchor,
                      condition=dict(type="all", children=[
                          leaf("core:item:060:value:1", "500Km기준", anchor, subject="위성 고도", operator="eq",
                               threshold="500", unit="km"),
                          leaf("core:item:060:value:2", "50cm이하급", anchor, subject="해상도", operator="le",
                               threshold="50", unit="cm")]))
        view = make_view([item])
        result = build(view, [extracted(full_items())])
        record = record_of(result, "core:item:060")
        thresholds = record["branches"][0]["thresholds"]
        self.assertEqual([(t["operator"], t["value"], t["unit"]) for t in thresholds],
                         [("ge", "500", "km"), ("le", "50", "cm")])
        self.assertIn(dict(quote="500Km기준", source=BODY_SOURCE), record["checks"])
        self.assertEqual(record["title"], "초고해상도(고도 500Km기준 50cm이하급) 광학위성")

    def test_any_alternatives_and_not_and_qualitative(self):
        """any 아래 숫자 없는 대안은 text 갈래, all 아래 qualitative와 not 아래 조건은 checks, 갈래 공통이 아닌 정성은 label."""
        anchor = "raw/dual_use.txt#dual_use:control:1A003"
        text = make_view().clauses["dual_use:control:1A003"]["text"]
        condition = dict(type="all", children=[
            leaf("x:form", "필름 형태의 제조품", anchor),
            dict(type="any", children=[
                leaf("x:thickness", "0.254 mm 를 초과", anchor, subject="두께", operator="gt", threshold="0.254", unit="mm"),
                leaf("x:coated", "탄소로 코팅된 것", anchor),
                dict(type="all", children=[
                    leaf("x:alt-type", "구리 코팅", anchor),
                    leaf("x:alt-thickness", "0.1 mm 이상", anchor, subject="두께", operator="ge", threshold="0.1",
                         unit="mm")]),
            ]),
            dict(type="not", child=leaf("x:excluded", "인쇄회로 기판용은 통제하지 않는다", anchor)),
        ])
        item = clause("dual_use:control:1A003", "dual_use", text, code="1A003", field="1부", anchor=anchor,
                      refs=["dual_use:notes:t01:r01"], condition=condition)
        view = make_view()
        view.clauses["dual_use:control:1A003"] = item
        result = build(view, [extracted([dict(clause_id="dual_use:control:1A003", branches=[], checks=[])],
                                        scope=dict(families=["dual_use"], code_prefixes=["1"]))])
        self.assertEqual(result.errors, [])
        record = record_of(result, "dual_use:control:1A003")
        branches = record["branches"]
        self.assertEqual(len(branches), 3)
        self.assertEqual([len(b["thresholds"]) for b in branches], [1, 0, 1])
        self.assertEqual(branches[0]["label"], "")
        self.assertEqual(branches[0]["text"], "")
        self.assertEqual(branches[1]["text"], "탄소로 코팅된 것")
        self.assertEqual(branches[1]["thresholds"], [])
        self.assertEqual(branches[2]["label"], "구리 코팅")
        self.assertEqual(branches[2]["thresholds"][0]["value"], "0.1")
        self.assertEqual(len({b["branch_id"] for b in branches}), 3)
        self.assertIn(dict(quote="필름 형태의 제조품", source=BODY_SOURCE), record["checks"])
        self.assertIn(dict(quote="인쇄회로 기판용은 통제하지 않는다", source=BODY_SOURCE), record["checks"])
        self.assertEqual(record["numeric_status"], STATUS_HAS)
        self.assertEqual(record["title"], "필름 형태의 제조품으로서 다음 중 한 개의 특성을 지닌 것:")

    def test_numeric_status_three_values(self):
        view = make_view()
        result = build(view, [extracted(full_items(**{"advanced:item:001": dict(
            clause_id="advanced:item:001", branches=[], checks=[])}))])
        self.assertEqual(record_of(result, "core:item:001")["numeric_status"], STATUS_HAS)
        self.assertEqual(record_of(result, "military:control:ML1")["numeric_status"], STATUS_HAS)
        items = full_items(**{"military:control:ML1": dict(clause_id="military:control:ML1", branches=[], checks=[]),
                              "core:item:001": dict(clause_id="core:item:001", branches=[dict(label="", thresholds=[
                                  dict(subject="D램 공정노드", operator="le", value="31", unit="nm", quote="30나노 이하급",
                                       quote_source=BODY_SOURCE)], text="")], checks=[])})
        result = build(view, [extracted(items)])
        self.assertEqual(record_of(result, "military:control:ML1")["numeric_status"], STATUS_NONE)
        self.assertEqual(record_of(result, "core:item:001")["numeric_status"], STATUS_FAILED)
        self.assertEqual(record_of(result, "advanced:item:001")["numeric_status"], STATUS_HAS)
        self.assertEqual(result.counts["status"][STATUS_NONE], 1)
        self.assertEqual(result.counts["status"][STATUS_FAILED], 1)
        self.assertEqual(result.counts["status"][STATUS_HAS], 3)

    def test_titles_follow_family_rule(self):
        view = make_view()
        result = build(view, [extracted(full_items())])
        self.assertEqual(record_of(result, "military:control:ML1")["title"], "구경이 20mm 미만인 활강무기")
        self.assertEqual(record_of(result, "core:item:001")["title"], "30나노 D램")
        items = full_items(**{"core:item:001": dict(clause_id="core:item:001", title="추출 제목", branches=[], checks=[])})
        result = build(view, [extracted(items)])
        self.assertEqual(record_of(result, "core:item:001")["title"], "추출 제목")

    def test_records_follow_index_order_and_structured_only_items_are_not_missing(self):
        view = make_view()
        items = [i for i in full_items() if i["clause_id"] != "advanced:item:001"]
        result = build(view, [extracted(items)])
        self.assertEqual(result.missing, [])
        self.assertEqual([r["clause_id"] for r in result.records], [i["clause_id"] for i in view.items])


class CoverageTests(unittest.TestCase):
    def test_missing_items_fail_build(self):
        view = make_view()
        items = [i for i in full_items() if i["clause_id"] not in ("core:item:001", "military:control:ML1")]
        result = build(view, [extracted(items)])
        self.assertEqual(result.missing, ["core:item:001", "military:control:ML1"])
        self.assertFalse(result.ok)

    def test_duplicate_item_across_files_is_an_error(self):
        view = make_view()
        first = extracted(full_items(), path="a.json")
        second = extracted([dict(clause_id="core:item:001", branches=[], checks=[])], scope=dict(families=["core"]),
                           path="b.json")
        result = build(view, [first, second])
        self.assertFalse(result.ok)
        self.assertTrue(any("core:item:001" in e and "중복" in e for e in result.errors))

    def test_item_outside_scope_and_unknown_item_are_errors(self):
        view = make_view()
        result = build(view, [extracted([dict(clause_id="core:item:001", branches=[], checks=[])],
                                        scope=dict(families=["military"]))])
        self.assertTrue(any("범위" in e for e in result.errors))
        result = build(view, [extracted([dict(clause_id="core:item:999", branches=[], checks=[])],
                                        scope=dict(families=["core"]))])
        self.assertTrue(any("core:item:999" in e for e in result.errors))

    def test_scope_limits_missing_check(self):
        view = make_view()
        file = extracted([dict(clause_id="dual_use:control:1A003", branches=[], checks=[])],
                         scope=dict(families=["dual_use"], code_prefixes=["1"]))
        result = build(view, [file], scope_only=True)
        self.assertEqual(result.missing, [])
        file = extracted([], scope=dict(families=["dual_use"]))
        result = build(view, [file], scope_only=True)
        self.assertEqual(result.missing, ["dual_use:control:1A003", "dual_use:control:0A001"])

    def test_extracted_file_shape_errors(self):
        for payload in (dict(items=[]), dict(scope=dict(families=["nowhere"]), items=[]),
                        dict(scope=dict(families=["core"], code_prefixes=["1"]), items=[]),
                        dict(scope=dict(families=["core"]), items=[dict(clause_id="core:item:001")]),
                        dict(scope=dict(families=["core"]), items=[dict(clause_id="core:item:001", branches=[
                            dict(label="", thresholds=[], text="")], checks=[])])):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    read_extracted(payload, "bad.json")


class TableFileTests(unittest.TestCase):
    """표 파일 쓰기·불러오기·지문·유일성."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.view = make_view()
        self.result = build(self.view, [extracted(full_items())])
        self.assertTrue(self.result.ok)
        self.path = self.dir / "thresholds.json"
        write_table(self.result, self.view, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        table = load_threshold_table(self.path)
        self.assertEqual(table.catalogue_id, "synthetic")
        self.assertEqual(table.catalogue_fingerprint, "0" * 64)
        self.assertEqual(table.near_percent, 10)
        self.assertEqual(len(table.all_records()), 5)
        self.assertEqual(table.record("core:item:001")["numeric_status"], STATUS_HAS)
        self.assertEqual([r["clause_id"] for r in table.records_for_family("dual_use")],
                         ["dual_use:control:1A003", "dual_use:control:0A001"])
        with self.assertRaises(KeyError):
            table.record("none")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload), {"catalogue_id", "catalogue_fingerprint", "near_percent", "records", "fingerprint"})
        expected = canonical_hash({k: v for k, v in payload.items() if k != "fingerprint"})
        self.assertEqual(table.fingerprint, expected)
        self.assertEqual(payload["fingerprint"], expected)
        self.assertEqual(Decimal(table.record("dual_use:control:1A003")["branches"][0]["thresholds"][0]["value"]),
                         Decimal("0.254"))

    def test_fingerprint_mismatch_fails_loading(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["records"][1]["branches"][0]["thresholds"][0]["value"] = "31"
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ThresholdTableError, "지문"):
            load_threshold_table(self.path)

    def test_duplicate_ids_fail_loading(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        core = next(r for r in payload["records"] if r["clause_id"] == "core:item:001")
        military = next(r for r in payload["records"] if r["clause_id"] == "military:control:ML1")
        military["branches"][0]["thresholds"][0]["threshold_id"] = core["branches"][0]["thresholds"][0]["threshold_id"]
        payload["fingerprint"] = canonical_hash({k: v for k, v in payload.items() if k != "fingerprint"})
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ThresholdTableError, "threshold_id"):
            load_threshold_table(self.path)

    def test_catalogue_fingerprint_is_checked_when_catalogue_given(self):
        class FakeCatalogue:
            fingerprint = "1" * 64
        with self.assertRaisesRegex(ThresholdTableError, "기준본"):
            load_threshold_table(self.path, catalogue=FakeCatalogue())

    def test_missing_file(self):
        with self.assertRaises(ThresholdTableError):
            load_threshold_table(self.dir / "absent.json")

    def test_review_workbook(self):
        import openpyxl
        xlsx = self.dir / "review.xlsx"
        write_review(self.result, xlsx)
        workbook = openpyxl.load_workbook(xlsx, read_only=True)
        names = workbook.sheetnames
        workbook.close()
        for name in ("기준값", "숫자 기준 없음", "채택 실패", "범위별 건수", "누락"):
            self.assertIn(name, names)


class CommandLineTests(unittest.TestCase):
    """--check 는 아무 파일도 쓰지 않는다. 전체 생성은 누락이 있으면 표를 쓰지 않는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        return {p.relative_to(self.dir).as_posix(): os.stat(p).st_mtime_ns for p in self.dir.rglob("*") if p.is_file()}

    def test_check_mode_writes_nothing(self):
        extracted_dir = self.dir / "extracted"
        extracted_dir.mkdir()
        file = extracted_dir / "military.json"
        file.write_text(json.dumps(dict(scope=dict(families=["military"]), items=[]), ensure_ascii=False),
                        encoding="utf-8")
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()) as console:
            code = main(["--check", str(file), "--notices-root", str(paths.notices_root()),
                         "--output", str(self.dir / "thresholds.json"), "--review-xlsx", str(self.dir / "review.xlsx")])
        self.assertNotEqual(code, 0)
        self.assertIn("누락 22개", console.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_full_build_with_structured_only_reports_466_missing(self):
        """실제 복사본에서 structured 57개 잎만으로 생성하면 41개 항목이 들어가고 466개가 누락으로 실패한다."""
        real_table = PROGRAM / "resources" / "thresholds.json"
        self._real_table_before = (real_table.exists(), real_table.stat().st_mtime_ns if real_table.exists() else None)
        extracted_dir = self.dir / "extracted"
        extracted_dir.mkdir()
        output = self.dir / "thresholds.json"
        review = self.dir / "review.xlsx"
        with contextlib.redirect_stdout(io.StringIO()) as console:
            code = main(["--notices-root", str(paths.notices_root()), "--extracted-dir", str(extracted_dir),
                         "--output", str(output), "--review-xlsx", str(review)])
        self.assertNotEqual(code, 0)
        self.assertIn("누락 466개", console.getvalue())
        self.assertFalse(output.exists())
        self.assertTrue(review.exists())
        catalogue = load_catalogue()
        view = CatalogueView.from_catalogue(catalogue)
        self.assertEqual(len(view.items), 507)
        result = build(view, [])
        self.assertEqual(len(result.missing), 466)
        self.assertEqual(len(result.records), 41)
        thresholds = [t for r in result.records for b in r["branches"] for t in b["thresholds"]]
        self.assertEqual(len(thresholds), 57)
        self.assertTrue(all(t["origin"] == "structured" for t in thresholds))
        self.assertEqual(sorted({t["operator"] for t in thresholds}), ["ge", "gt", "le"])
        self.assertEqual({l["predicate_id"] for l in numeric_leaves(catalogue) if l["operator"] == "eq"},
                         {"core:item:060:value:1", "core:item:068:value:1"})
        for clause_id, quote in (("core:item:060", "500Km기준"), ("core:item:068", "5축")):
            record = record_of(result, clause_id)
            self.assertIn(dict(quote=quote, source=BODY_SOURCE), record["checks"])
        self.assertEqual({t["unit"] for t in thresholds if t["unit"] in ("um", "㎛")}, set())
        self.assertIn("μm", {t["unit"] for t in thresholds})
        self.assertIn("t", {t["unit"] for t in thresholds})
        self.assertEqual(sum(1 for r in result.records if r["family"] == "advanced"), 14)
        for record in result.records:
            if record["family"] == "advanced":
                self.assertTrue(any(c["source"] == "advanced:article:4" for c in record["checks"]), record["clause_id"])
        ids = [t["threshold_id"] for t in thresholds]
        self.assertEqual(len(set(ids)), 57)
        real_table = PROGRAM / "resources" / "thresholds.json"
        self.assertEqual(real_table.exists(), self._real_table_before[0],
                         "시험이 실제 자원 폴더에 표를 새로 만들면 안 된다")
        if real_table.exists():
            self.assertEqual(real_table.stat().st_mtime_ns, self._real_table_before[1],
                             "시험이 실제 자원 폴더의 표를 고치면 안 된다")

    def test_structured_items_in_real_copy_have_all_seven_any_alternatives(self):
        view = CatalogueView.from_catalogue(load_catalogue())
        result = build(view, [])
        record = record_of(result, "advanced:item:013")
        self.assertEqual(len(record["branches"]), 4)
        self.assertEqual([len(b["thresholds"]) for b in record["branches"]], [1, 1, 2, 2])
        self.assertTrue(all(b["label"] for b in record["branches"]))
        record = record_of(result, "dual_use:control:1A003")
        self.assertEqual([len(b["thresholds"]) for b in record["branches"]], [1, 0])
        self.assertTrue(record["branches"][1]["text"])
        self.assertEqual(set(clause_index(load_catalogue())[0]), {"clause_id", "family", "code", "title", "field"})


if __name__ == "__main__":
    unittest.main()
