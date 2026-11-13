"""판정 엔진(judge_engine) 시험. spec 7장(매핑 거르기·비교·항목·과제 판정)을 합성 표 기록과 합성 목표 수치로 확인한다.

글·숫자는 모두 합성이며 실제 과제가 아니다. 외부 파일을 읽지 않는다.
"""
from decimal import Decimal
import json
import unittest

import judge_engine as je
from threshold_table import STATUS_FAILED, STATUS_HAS, STATUS_NONE, BODY_SOURCE


# ---------- 합성 자료 만들기 ----------

def threshold(tid, subject, operator, value, unit="", origin="structured", quote=None):
    return dict(threshold_id=tid, subject=subject, operator=operator, value=str(value), unit=unit,
                quote=quote or f"{subject} {value}{unit} {operator}", quote_source=BODY_SOURCE, origin=origin)


def branch(bid, thresholds=(), text="", label=""):
    return dict(branch_id=bid, label=label or bid, thresholds=list(thresholds), text=text)


def record(cid, family="advanced", branches=(), rejected=(), checks=(), title="합성 항목", code=None):
    branches = list(branches)
    if any(b["thresholds"] for b in branches):
        status = STATUS_HAS
    elif rejected:
        status = STATUS_FAILED
    else:
        status = STATUS_NONE
    item = dict(clause_id=cid, family=family, numeric_status=status, title=title, branches=branches,
                rejected=list(rejected), checks=list(checks))
    if code is not None:
        item["code"] = code
    return item


def rejected(bid="", subject="채택 실패 물리량", reason="수치를 읽지 못함"):
    return dict(branch_id=bid, subject=subject, quote="원문 일부", reason=reason)


def fact(fid, value, unit="", subject="물리량", source_field="최종목표", low=None, high=None):
    low = str(value if low is None else low)
    high = str(value if high is None else high)
    return dict(fact_id=fid, subject=subject, value_text=f"{value}{unit}", low=low, high=high, unit=unit,
                source_field=source_field, start=0, end=5, quote=f"목표 {value}{unit}")


def pair(cid, fid, tid, branch_id="", ambiguous=False, reason="합성 매핑"):
    return dict(clause_id=cid, fact_id=fid, threshold_id=tid, branch_id=branch_id, reason=reason, ambiguous=ambiguous)


def single(operator, threshold_value, fact_value, threshold_unit="", fact_unit="", origin="structured",
           low=None, high=None, ambiguous=False, near_percent=je.NEAR_PERCENT):
    """기준 하나·목표 하나로 judge를 돌리고 (결과, 비교 하나, 항목 하나)를 돌려준다."""
    cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", operator, threshold_value, threshold_unit, origin)])])
    facts = [fact("f1", fact_value, fact_unit, low=low, high=high)]
    result = je.judge(facts, [cand], [pair("advanced:1", "f1", "t1", ambiguous=ambiguous)], ["advanced"], near_percent=near_percent)
    assert len(result.comparisons) == 1, result.comparisons
    assert len(result.clauses) == 1
    return result, result.comparisons[0], result.clauses[0]


ALL_FAMILIES = ["advanced", "core", "dual_use", "military"]


class ComparisonTest(unittest.TestCase):
    """7.2 비교 하나."""

    def test_ge_equal_is_over(self):
        _, comp, clause = single("ge", 100, 100)
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(comp["gap_percent"], "0")
        self.assertEqual(comp["gap_percent_display"], "0.0")
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)

    def test_ge_ninety_percent_is_near(self):
        _, comp, clause = single("ge", 100, 90)
        self.assertEqual(comp["verdict"], je.VERDICT_NEAR)
        self.assertEqual(Decimal(comp["gap_percent"]), Decimal("10"))
        self.assertEqual(comp["gap_percent_display"], "10.0")
        self.assertEqual(clause["verdict"], je.VERDICT_NEAR)

    def test_ge_below_ninety_is_under(self):
        _, comp, _ = single("ge", 100, "89.9")
        self.assertEqual(comp["verdict"], je.VERDICT_UNDER)
        self.assertEqual(Decimal(comp["gap_percent"]), Decimal("10.1"))

    def test_judgement_uses_unrounded_gap(self):
        # 차이 10.04% → 표시는 10.0이지만 판정은 반올림 전 값으로 미달
        _, comp, _ = single("ge", 10000, "8996")
        self.assertEqual(comp["gap_percent_display"], "10.0")
        self.assertEqual(comp["verdict"], je.VERDICT_UNDER)

    def test_gt_equal_is_near_zero(self):
        _, comp, _ = single("gt", 100, 100)
        self.assertEqual(comp["verdict"], je.VERDICT_NEAR)
        self.assertEqual(Decimal(comp["gap_percent"]), Decimal("0"))

    def test_gt_above_is_over(self):
        _, comp, _ = single("gt", 100, "100.01")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)

    def test_le_directions(self):
        self.assertEqual(single("le", 100, 100)[1]["verdict"], je.VERDICT_OVER)
        self.assertEqual(single("le", 100, 50)[1]["verdict"], je.VERDICT_OVER)
        near = single("le", 100, 110)[1]
        self.assertEqual(near["verdict"], je.VERDICT_NEAR)
        self.assertEqual(Decimal(near["gap_percent"]), Decimal("10"))
        self.assertEqual(single("le", 100, "110.1")[1]["verdict"], je.VERDICT_UNDER)

    def test_lt_directions(self):
        self.assertEqual(single("lt", 100, 99)[1]["verdict"], je.VERDICT_OVER)
        equal = single("lt", 100, 100)[1]
        self.assertEqual(equal["verdict"], je.VERDICT_NEAR)
        self.assertEqual(Decimal(equal["gap_percent"]), Decimal("0"))
        self.assertEqual(single("lt", 100, 120)[1]["verdict"], je.VERDICT_UNDER)

    def test_negative_threshold_uses_absolute(self):
        # T=-100, ge, V=-105 → (T-V)/|T| = 5%
        _, comp, _ = single("ge", -100, -105)
        self.assertEqual(comp["verdict"], je.VERDICT_NEAR)
        self.assertEqual(Decimal(comp["gap_percent"]), Decimal("5"))

    def test_range_goal_picks_favourable_end(self):
        _, comp, clause = single("ge", 100, None, low=50, high=100)
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(Decimal(comp["used_value"]), Decimal("100"))
        self.assertIn(je.FLAG_RANGE, comp["flags"])
        self.assertIn(je.FLAG_RANGE, clause["flags"])
        _, comp, _ = single("le", 50, None, low=50, high=100)
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(Decimal(comp["used_value"]), Decimal("50"))
        _, comp, _ = single("lt", 100, None, low=50, high=100)
        self.assertEqual(Decimal(comp["used_value"]), Decimal("50"))
        _, comp, _ = single("gt", 100, None, low=50, high=100)
        self.assertEqual(Decimal(comp["used_value"]), Decimal("100"))

    def test_single_value_has_no_range_flag(self):
        _, comp, _ = single("ge", 100, 100)
        self.assertNotIn(je.FLAG_RANGE, comp["flags"])

    def test_zero_threshold(self):
        _, comp, clause = single("ge", 0, -1)
        self.assertEqual(comp["verdict"], je.VERDICT_ZERO)
        self.assertIsNone(comp["gap_percent"])
        self.assertIsNone(comp["gap_percent_display"])
        self.assertEqual(clause["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        self.assertEqual(clause["reason"], je.VERDICT_ZERO)
        _, comp, _ = single("ge", 0, 0)
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)

    def test_near_percent_parameter(self):
        result, comp, _ = single("ge", 100, 92, near_percent=Decimal("5"))
        self.assertEqual(comp["verdict"], je.VERDICT_UNDER)
        self.assertEqual(result.near_percent, "5")
        result, comp, _ = single("ge", 100, 92)
        self.assertEqual(comp["verdict"], je.VERDICT_NEAR)
        self.assertEqual(result.near_percent, str(je.NEAR_PERCENT))
        self.assertEqual(je.NEAR_PERCENT, Decimal("10"))


class UnitTest(unittest.TestCase):
    """7.1 단위 처리."""

    def test_same_unit_after_alias(self):
        _, comp, _ = single("ge", 100, 100, threshold_unit="nm", fact_unit="㎚")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(comp["fact_unit"], "nm")
        self.assertEqual(comp["threshold_unit"], "nm")
        self.assertEqual(Decimal(comp["converted_value"]), Decimal("100"))

    def test_empty_units_compare_directly(self):
        _, comp, _ = single("ge", 3, 3, threshold_unit="", fact_unit="")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)

    def test_convertible_nano_to_micro(self):
        _, comp, _ = single("le", 1, 500, threshold_unit="μm", fact_unit="나노")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(Decimal(comp["converted_value"]), Decimal("0.5"))
        self.assertEqual(Decimal(comp["used_value"]), Decimal("500"))

    def test_convertible_kw_to_w(self):
        _, comp, _ = single("ge", 900, 1, threshold_unit="W", fact_unit="kW")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(Decimal(comp["converted_value"]), Decimal("1000"))

    def test_watt_hour_goal_against_joule_threshold_1_3_3(self):
        # 1.3.2까지는 Wh를 3,600배 작게 환산해 5 Wh(=18 kJ)가 '10 kJ 초과'에 미달로 나왔다.
        _, comp, _ = single("gt", 10, 5, threshold_unit="kJ", fact_unit="Wh")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(comp["converted_value"], "18")
        _, comp, _ = single("le", 10, 5, threshold_unit="kJ", fact_unit="Wh")
        self.assertEqual(comp["verdict"], je.VERDICT_UNDER)
        _, comp, _ = single("ge", "3.6", 1, threshold_unit="MJ", fact_unit="kWh")
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertEqual(comp["converted_value"], "3.6")

    def test_converted_value_equal_to_threshold_compares_as_equal_1_3_3(self):
        # 1.3.2까지는 끊긴 소수 계수 때문에 환산한 값이 기준값보다 조금 크게 나와 한 단계 틀렸다.
        cases = (
            ("gt", "600", "m/s", "2160", "km/h", je.VERDICT_NEAR),   # 같은 값은 '초과' 기준에 근접
            ("ge", "600", "m/s", "2160", "km/h", je.VERDICT_OVER),
            ("le", "0.2", "°", "720", "arcsec", je.VERDICT_OVER),    # 같은 값은 '이하' 기준을 충족
            ("lt", "0.2", "°", "720", "arcsec", je.VERDICT_NEAR),
            ("le", "0.05", "°", "180", "arcsec", je.VERDICT_OVER),
            ("le", "6", "°/s", "21600", "°/h", je.VERDICT_OVER),
            ("gt", "30", "kn", "55.56", "km/h", je.VERDICT_NEAR),
            ("le", "2", "m3/s", "7200", "m3/h", je.VERDICT_OVER),
            ("le", "1", "atm", "760", "Torr", je.VERDICT_OVER),
        )
        for operator, threshold_value, threshold_unit, fact_value, fact_unit, expected in cases:
            _, comp, _ = single(operator, threshold_value, fact_value, threshold_unit=threshold_unit, fact_unit=fact_unit)
            label = (operator, threshold_value, threshold_unit, fact_value, fact_unit)
            self.assertEqual(comp["verdict"], expected, label)
            self.assertEqual(comp["converted_value"], threshold_value, label)
            self.assertEqual(Decimal(comp["gap_percent"]), 0, label)
        # 정확히 10% 못 미친 값은 근접, 그보다 조금 더 못 미치면 미달.
        _, comp, _ = single("gt", 600, 1944, threshold_unit="m/s", fact_unit="km/h")
        self.assertEqual((comp["verdict"], Decimal(comp["gap_percent"])), (je.VERDICT_NEAR, Decimal("10")))
        _, comp, _ = single("gt", 600, "1943.9", threshold_unit="m/s", fact_unit="km/h")
        self.assertEqual(comp["verdict"], je.VERDICT_UNDER)

    def test_different_kind(self):
        _, comp, clause = single("ge", 100, 100, threshold_unit="m", fact_unit="초")
        self.assertEqual(comp["verdict"], je.VERDICT_UNIT_KIND)
        self.assertIsNone(comp["converted_value"])
        self.assertIsNone(comp["gap_percent"])
        self.assertEqual(clause["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        self.assertEqual(clause["reason"], je.VERDICT_UNIT_KIND)

    def test_not_convertible(self):
        _, comp, clause = single("ge", 100, 100, threshold_unit="K", fact_unit="℃")
        self.assertEqual(comp["verdict"], je.VERDICT_UNIT_CONVERT)
        self.assertEqual(clause["reason"], je.VERDICT_UNIT_CONVERT)

    def test_unknown_unit_is_different_kind(self):
        _, comp, _ = single("ge", 100, 100, threshold_unit="m", fact_unit="알수없음")
        self.assertEqual(comp["verdict"], je.VERDICT_UNIT_KIND)


class ClauseTest(unittest.TestCase):
    """7.3 항목 판정."""

    def two_threshold_clause(self):
        return record("advanced:1", branches=[branch("b1", [
            threshold("t1", "길이", "ge", 100, "nm"),
            threshold("t2", "출력", "ge", 10, "W"),
        ])])

    def test_and_takes_lowest(self):
        cand = self.two_threshold_clause()
        facts = [fact("f1", 100, "nm"), fact("f2", 5, "W")]
        pairs = [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t2")]
        result = je.judge(facts, [cand], pairs, ["advanced"])
        clause = result.clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_UNDER)
        self.assertNotIn(je.FLAG_PARTIAL, clause["flags"])
        self.assertEqual(clause["missing_subjects"], [])

    def test_and_partial_when_threshold_unpaired(self):
        cand = self.two_threshold_clause()
        result = je.judge([fact("f1", 100, "nm")], [cand], [pair("advanced:1", "f1", "t1")], ["advanced"])
        clause = result.clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_PARTIAL, clause["flags"])
        self.assertEqual(clause["missing_subjects"], ["출력"])

    def test_and_partial_when_threshold_not_comparable(self):
        cand = self.two_threshold_clause()
        facts = [fact("f1", 100, "nm"), fact("f2", 5, "초")]
        pairs = [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t2")]
        clause = je.judge(facts, [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_PARTIAL, clause["flags"])
        self.assertEqual(clause["missing_subjects"], ["출력"])

    def test_and_partial_when_branch_has_rejected(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])],
                      rejected=[rejected("b1", subject="질량")])
        clause = je.judge([fact("f1", 100, "nm")], [cand], [pair("advanced:1", "f1", "t1")], ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_PARTIAL, clause["flags"])
        self.assertIn(je.FLAG_REJECTED, clause["flags"])
        self.assertEqual(clause["missing_subjects"], ["질량"])
        self.assertEqual(len(clause["rejected"]), 1)

    def two_branch_clause(self, text_branch=False):
        branches = [branch("bA", [threshold("tA", "길이", "ge", 100, "nm")]),
                    branch("bB", [threshold("tB", "출력", "ge", 10, "W")])]
        if text_branch:
            branches.append(branch("bC", text="숫자 없는 갈래 원문"))
        return record("advanced:1", branches=branches)

    def test_or_takes_highest_when_branch_undecided(self):
        cand = self.two_branch_clause()
        facts = [fact("f1", 50, "nm"), fact("f2", 9.5, "W")]  # A 미달, B 근접
        pairs = [pair("advanced:1", "f1", "tA"), pair("advanced:1", "f2", "tB")]
        clause = je.judge(facts, [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_NEAR)
        self.assertIn(je.FLAG_BRANCH, clause["flags"])
        self.assertEqual(clause["branch_texts"], [])

    def test_or_only_branches_with_comparison_count(self):
        cand = self.two_branch_clause()
        clause = je.judge([fact("f1", 50, "nm")], [cand], [pair("advanced:1", "f1", "tA")], ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_UNDER)
        self.assertIn(je.FLAG_BRANCH, clause["flags"])

    def test_chosen_branch_only(self):
        cand = self.two_branch_clause()
        facts = [fact("f1", 50, "nm"), fact("f2", 9.5, "W")]
        pairs = [pair("advanced:1", "f1", "tA", branch_id="bA"), pair("advanced:1", "f2", "tB", branch_id="bA")]
        clause = je.judge(facts, [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_UNDER)
        self.assertNotIn(je.FLAG_BRANCH, clause["flags"])

    def test_chosen_branch_by_branch_only_pair(self):
        cand = self.two_branch_clause()
        facts = [fact("f1", 50, "nm"), fact("f2", 9.5, "W")]
        pairs = [pair("advanced:1", "f1", "tA"), pair("advanced:1", "f2", "tB"), pair("advanced:1", "", "", branch_id="bB")]
        clause = je.judge(facts, [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_NEAR)
        self.assertNotIn(je.FLAG_BRANCH, clause["flags"])

    def test_conflicting_branch_ids_mean_undecided(self):
        cand = self.two_branch_clause()
        facts = [fact("f1", 50, "nm"), fact("f2", 9.5, "W")]
        pairs = [pair("advanced:1", "f1", "tA", branch_id="bA"), pair("advanced:1", "f2", "tB", branch_id="bB")]
        clause = je.judge(facts, [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_NEAR)
        self.assertIn(je.FLAG_BRANCH, clause["flags"])

    def test_chosen_numeric_branch_without_comparison_is_not_comparable(self):
        cand = self.two_branch_clause()
        pairs = [pair("advanced:1", "f1", "tA", branch_id="bB")]
        clause = je.judge([fact("f1", 50, "nm")], [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        self.assertEqual(clause["reason"], je.REASON_NO_FACT)

    def test_text_branch_chosen(self):
        cand = self.two_branch_clause(text_branch=True)
        pairs = [pair("advanced:1", "f1", "tA", branch_id="bC")]
        clause = je.judge([fact("f1", 100, "nm")], [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_BRANCH, clause["flags"])
        self.assertEqual(clause["branch_texts"], ["숫자 없는 갈래 원문"])

    def test_text_branch_present_flags_even_when_numeric_chosen(self):
        cand = self.two_branch_clause(text_branch=True)
        pairs = [pair("advanced:1", "f1", "tA", branch_id="bA")]
        clause = je.judge([fact("f1", 100, "nm")], [cand], pairs, ["advanced"]).clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_BRANCH, clause["flags"])
        self.assertEqual(clause["branch_texts"], ["숫자 없는 갈래 원문"])

    def test_single_branch_no_branch_flag(self):
        _, _, clause = single("ge", 100, 100)
        self.assertNotIn(je.FLAG_BRANCH, clause["flags"])

    def test_not_comparable_no_pairs(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        result = je.judge([], [cand], [], ["advanced"])
        clause = result.clauses[0]
        self.assertEqual(clause["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        self.assertEqual(clause["reason"], je.REASON_NO_FACT)
        self.assertEqual(result.comparisons, [])

    def test_no_numeric_status(self):
        cand = record("core:1", family="core", branches=[branch("b1", text="정성 조건 원문")])
        result = je.judge([], [cand], [], ["core"])
        clause = result.clauses[0]
        self.assertEqual(clause["verdict"], je.CLAUSE_VERDICT_NO_NUMERIC)
        self.assertEqual(clause["numeric_status"], STATUS_NONE)
        self.assertEqual(clause["branch_texts"], ["정성 조건 원문"])
        self.assertEqual(result.families["core"], je.FAMILY_VERDICT_NONE)
        self.assertEqual(result.counts[je.COUNT_NO_NUMERIC], 1)

    def test_failed_status(self):
        cand = record("core:1", family="core", branches=[], rejected=[rejected("", subject="길이")])
        result = je.judge([], [cand], [], ["core"])
        clause = result.clauses[0]
        self.assertEqual(clause["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        self.assertEqual(clause["reason"], je.REASON_FAILED)
        self.assertIn(je.FLAG_REJECTED, clause["flags"])
        self.assertEqual(clause["numeric_status"], STATUS_FAILED)
        self.assertEqual(clause["rejected"][0]["subject"], "길이")

    def test_checks_flag(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])],
                      checks=[dict(quote="단서 원문", source=BODY_SOURCE)])
        clause = je.judge([fact("f1", 100, "nm")], [cand], [pair("advanced:1", "f1", "t1")], ["advanced"]).clauses[0]
        self.assertIn(je.FLAG_CHECK, clause["flags"])
        self.assertEqual(clause["checks"], [dict(quote="단서 원문", source=BODY_SOURCE)])

    def test_no_checks_no_flag(self):
        _, _, clause = single("ge", 100, 100)
        self.assertNotIn(je.FLAG_CHECK, clause["flags"])
        self.assertEqual(clause["checks"], [])

    def test_extracted_origin_flag(self):
        _, comp, clause = single("ge", 100, 100, origin="extracted")
        self.assertIn(je.FLAG_EXTRACTED, comp["flags"])
        self.assertIn(je.FLAG_EXTRACTED, clause["flags"])
        self.assertEqual(comp["origin"], "extracted")
        _, comp, clause = single("ge", 100, 100, origin="structured")
        self.assertNotIn(je.FLAG_EXTRACTED, comp["flags"])
        self.assertNotIn(je.FLAG_EXTRACTED, clause["flags"])

    def test_ambiguous_pair_flag(self):
        _, comp, clause = single("ge", 100, 100, ambiguous=True)
        self.assertEqual(comp["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_PAIR, comp["flags"])
        self.assertIn(je.FLAG_PAIR, clause["flags"])

    def test_code_passthrough(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])], code="A1")
        result = je.judge([fact("f1", 100, "nm")], [cand], [pair("advanced:1", "f1", "t1")], ["advanced"])
        self.assertEqual(result.clauses[0]["code"], "A1")
        self.assertEqual(result.comparisons[0]["code"], "A1")
        _, comp, clause = single("ge", 100, 100)
        self.assertEqual(clause["code"], "")
        self.assertEqual(comp["code"], "")


class PairFilterTest(unittest.TestCase):
    """7.1 매핑 거르기."""

    def test_missing_ids_are_dropped(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        pairs = [pair("advanced:1", "없는fact", "t1"), pair("advanced:1", "f1", "없는threshold"),
                 pair("없는clause", "f1", "t1"), pair("advanced:1", "f1", "t1", branch_id="없는branch")]
        result = je.judge([fact("f1", 100, "nm")], [cand], pairs, ["advanced"])
        self.assertEqual(len(result.dropped), 4)
        self.assertEqual(result.comparisons, [])
        for entry in result.dropped:
            self.assertIn("pair", entry)
            self.assertTrue(entry["reason"])
        self.assertEqual(result.clauses[0]["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        self.assertEqual(result.clauses[0]["reason"], je.REASON_NO_FACT)

    def test_threshold_of_other_clause_is_dropped(self):
        cands = [record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])]),
                 record("advanced:2", branches=[branch("b2", [threshold("t2", "길이", "ge", 100, "nm")])])]
        result = je.judge([fact("f1", 100, "nm")], cands, [pair("advanced:1", "f1", "t2")], ["advanced"])
        self.assertEqual(len(result.dropped), 1)
        self.assertEqual(result.comparisons, [])

    def test_half_pair_is_dropped(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        result = je.judge([fact("f1", 100, "nm")], [cand], [pair("advanced:1", "f1", ""), pair("advanced:1", "", "t1")], ["advanced"])
        self.assertEqual(len(result.dropped), 2)
        self.assertEqual(result.comparisons, [])

    def test_non_decimal_fact_is_dropped(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        bad = fact("f1", 100, "nm")
        bad["low"] = bad["high"] = "약 백"
        result = je.judge([bad], [cand], [pair("advanced:1", "f1", "t1")], ["advanced"])
        self.assertEqual(len(result.dropped), 1)
        self.assertEqual(result.comparisons, [])

    def test_candidate_in_unselected_family_is_skipped(self):
        cand = record("military:1", family="military", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        result = je.judge([fact("f1", 100, "nm")], [cand], [pair("military:1", "f1", "t1")], ["advanced"])
        self.assertEqual(result.clauses, [])
        self.assertEqual(result.comparisons, [])
        self.assertEqual(len(result.dropped), 1)
        self.assertEqual(len(result.skipped_clauses), 1)
        self.assertEqual(result.families["military"], je.FAMILY_VERDICT_EXCLUDED)


class InconsistencyTest(unittest.TestCase):
    """7.4 같은 물리량의 목표가 여러 곳에."""

    def test_two_sources_different_values(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        facts = [fact("f1", 100, "nm", source_field="최종목표"), fact("f2", 50, "nm", source_field="목표 발췌")]
        pairs = [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t1")]
        result = je.judge(facts, [cand], pairs, ["advanced"])
        self.assertEqual(len(result.comparisons), 2)
        verdicts = {c["fact_id"]: c["verdict"] for c in result.comparisons}
        self.assertEqual(verdicts, {"f1": je.VERDICT_OVER, "f2": je.VERDICT_UNDER})
        for comp in result.comparisons:
            self.assertIn(je.FLAG_INCONSISTENT, comp["flags"])
        clause = result.clauses[0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertIn(je.FLAG_INCONSISTENT, clause["flags"])

    def test_two_sources_same_value_no_flag(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        facts = [fact("f1", 100, "nm", source_field="최종목표"), fact("f2", 100, "nm", source_field="목표 발췌")]
        pairs = [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t1")]
        result = je.judge(facts, [cand], pairs, ["advanced"])
        for comp in result.comparisons:
            self.assertNotIn(je.FLAG_INCONSISTENT, comp["flags"])
        self.assertNotIn(je.FLAG_INCONSISTENT, result.clauses[0]["flags"])

    def test_any_two_of_the_four_sources(self):
        # 네 출처(최종목표·연구개발내용·활용계획 및 기대효과·목표 발췌) 중 어느 두 곳이든 다른 값이면 표시하고 더 높은 판정.
        sources = ("최종목표", "연구개발내용", "활용계획 및 기대효과", "목표 발췌")
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        for low_source in sources:
            for high_source in sources:
                if low_source == high_source:
                    continue
                facts = [fact("f1", 50, "nm", source_field=low_source), fact("f2", 120, "nm", source_field=high_source)]
                pairs = [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t1")]
                result = je.judge(facts, [cand], pairs, ["advanced"])
                verdicts = {c["fact_id"]: c["verdict"] for c in result.comparisons}
                self.assertEqual(verdicts, {"f1": je.VERDICT_UNDER, "f2": je.VERDICT_OVER}, (low_source, high_source))
                for comp in result.comparisons:
                    self.assertIn(je.FLAG_INCONSISTENT, comp["flags"], (low_source, high_source))
                self.assertEqual(result.clauses[0]["verdict"], je.VERDICT_OVER, (low_source, high_source))
                self.assertIn(je.FLAG_INCONSISTENT, result.clauses[0]["flags"])
                self.assertEqual(result.overall, je.VERDICT_OVER)

    def test_same_source_two_values_is_not_cross_source_inconsistency(self):
        cand = record("advanced:1", branches=[branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        facts = [fact("f1", 50, "nm", source_field="활용계획 및 기대효과"),
                 fact("f2", 120, "nm", source_field="활용계획 및 기대효과")]
        pairs = [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t1")]
        result = je.judge(facts, [cand], pairs, ["advanced"])
        for comp in result.comparisons:
            self.assertNotIn(je.FLAG_INCONSISTENT, comp["flags"])


class ProjectTest(unittest.TestCase):
    """7.5 과제 판정과 값 집합."""

    def build(self):
        cands = [
            record("advanced:1", "advanced", [branch("a1", [threshold("ta1", "길이", "ge", 100, "nm")])]),
            record("advanced:2", "advanced", [branch("a2", [threshold("ta2", "출력", "ge", 100, "W")])]),
            record("core:1", "core", [branch("c1", [threshold("tc1", "질량", "le", 10, "kg")])]),
            record("core:2", "core", [branch("c2", text="정성 조건")]),
            record("dual_use:1", "dual_use", [branch("d1", [threshold("td1", "길이", "ge", 1, "m")])]),
            record("dual_use:2", "dual_use", [], rejected=[rejected()]),
            record("military:1", "military", [branch("m1", [threshold("tm1", "속도", "ge", 100, "m/s")])]),
        ]
        facts = [fact("f1", 95, "nm"), fact("f2", 10, "W"), fact("f3", 10, "kg"), fact("f4", 1, "초", subject="시간")]
        pairs = [pair("advanced:1", "f1", "ta1"), pair("advanced:2", "f2", "ta2"), pair("core:1", "f3", "tc1"),
                 pair("dual_use:1", "f4", "td1")]
        return facts, cands, pairs

    def test_family_and_overall(self):
        facts, cands, pairs = self.build()
        result = je.judge(facts, cands, pairs, ["advanced", "core", "dual_use"])
        self.assertEqual(result.families, {
            "advanced": je.VERDICT_NEAR, "core": je.VERDICT_OVER, "dual_use": je.FAMILY_VERDICT_NONE,
            "military": je.FAMILY_VERDICT_EXCLUDED,
        })
        self.assertEqual(result.overall, je.VERDICT_OVER)
        self.assertEqual(result.counts, {
            je.COUNT_OVER: 1, je.COUNT_NEAR: 1, je.COUNT_UNDER: 1, je.COUNT_NOT_COMPARABLE: 2, je.COUNT_NO_NUMERIC: 1,
        })
        self.assertEqual(len(result.clauses), 6)
        self.assertEqual(len(result.skipped_clauses), 1)
        # 표시가 붙은 항목: dual_use:1(비교 불가는 표시 아님) 제외, dual_use:2(기준값 채택 실패) 1개
        self.assertEqual(result.flagged_clause_count, 1)

    def test_overall_none_when_no_numeric(self):
        cand = record("core:1", family="core", branches=[branch("b1", text="정성")])
        result = je.judge([], [cand], [], ["core"])
        self.assertEqual(result.overall, je.FAMILY_VERDICT_NONE)
        self.assertEqual(result.families["advanced"], je.FAMILY_VERDICT_EXCLUDED)

    def test_overall_takes_highest_across_families(self):
        cands = [record("advanced:1", "advanced", [branch("a1", [threshold("ta1", "길이", "ge", 100, "nm")])]),
                 record("core:1", "core", [branch("c1", [threshold("tc1", "질량", "le", 10, "kg")])])]
        facts = [fact("f1", 10, "nm"), fact("f3", 11, "kg")]
        pairs = [pair("advanced:1", "f1", "ta1"), pair("core:1", "f3", "tc1")]
        result = je.judge(facts, cands, pairs, ALL_FAMILIES)
        self.assertEqual(result.families["advanced"], je.VERDICT_UNDER)
        self.assertEqual(result.families["core"], je.VERDICT_NEAR)
        self.assertEqual(result.overall, je.VERDICT_NEAR)

    def test_flagged_clause_count(self):
        facts, cands, pairs = self.build()
        pairs[0]["ambiguous"] = True
        result = je.judge(facts, cands, pairs, ALL_FAMILIES)
        self.assertEqual(result.flagged_clause_count, 2)

    def test_values_within_sets_and_json(self):
        facts, cands, pairs = self.build()
        pairs[0]["ambiguous"] = True
        facts.append(fact("f5", 50, "nm", source_field="목표 발췌", low=40, high=50))
        pairs.append(pair("advanced:1", "f5", "ta1"))
        result = je.judge(facts, cands, pairs, ["advanced", "core", "dual_use"])
        for comp in result.comparisons:
            self.assertIn(comp["verdict"], je.COMPARISON_VERDICTS)
            self.assertTrue(set(comp["flags"]) <= set(je.FLAGS), comp["flags"])
        for clause in result.clauses:
            self.assertIn(clause["verdict"], je.CLAUSE_VERDICTS)
            self.assertTrue(set(clause["flags"]) <= set(je.FLAGS), clause["flags"])
        for verdict in result.families.values():
            self.assertIn(verdict, je.FAMILY_VERDICTS)
        self.assertIn(result.overall, je.FAMILY_VERDICTS)
        payload = result.to_dict()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertIn("near_percent", payload)
        self.assertEqual(json.loads(text)["overall"], result.overall)
        for key in ("comparisons", "clauses", "families", "overall", "counts", "flagged_clause_count", "dropped", "near_percent"):
            self.assertIn(key, payload)

    def test_constant_sets(self):
        self.assertEqual(je.COMPARISON_VERDICTS, ("초과", "근접", "미달", "비교 불가(단위 종류 다름)", "비교 불가(단위 환산 불가)", "비교 불가(기준값 0)"))
        self.assertEqual(je.CLAUSE_VERDICTS, ("초과", "근접", "미달", "수치 비교 불가", "수치 기준 없음(관련 분야)"))
        self.assertEqual(je.FAMILY_VERDICTS, ("초과", "근접", "미달", "수치 판정 없음", "대조 안 함(선택 제외)", "판정 안 함(상태 참고)"))
        self.assertEqual(je.FLAGS, ("추가 확인 조건", "갈래 확인 필요", "매핑 확인 필요", "범위 목표", "일부 수치만 비교",
                                    "입력 간 목표값 불일치", "AI가 읽은 기준값(원문 확인 필요)", "기준값 채택 실패(원문 확인 필요)"))
        self.assertEqual(je.FAMILY_VERDICT_STATUS, "판정 안 함(상태 참고)")

    def test_comparison_record_keys(self):
        _, comp, clause = single("ge", 100, 100, threshold_unit="nm", fact_unit="nm")
        expected = {"clause_id", "family", "code", "title", "branch_id", "branch_label", "threshold_id", "subject",
                    "operator", "threshold_value", "threshold_unit", "origin", "threshold_quote", "quote_source",
                    "fact_id", "fact_subject", "value_text", "used_value", "fact_unit", "converted_value", "fact_quote",
                    "source_field", "gap_percent", "gap_percent_display", "verdict", "flags", "pair_reason"}
        self.assertEqual(set(comp), expected)
        self.assertEqual(comp["branch_label"], "b1")
        self.assertEqual(comp["pair_reason"], "합성 매핑")
        self.assertEqual(comp["threshold_value"], "100")
        clause_keys = {"clause_id", "family", "code", "title", "numeric_status", "verdict", "reason", "missing_subjects",
                       "deciding_branch_ids", "flags", "checks", "branch_texts", "rejected"}
        self.assertEqual(set(clause), clause_keys)
        self.assertEqual(clause["reason"], "")


class DecidingBranchTest(unittest.TestCase):
    """조항 기록의 deciding_branch_ids: 판정을 정한 갈래(OR 갈래 중 조항 판정과 같은 판정의 갈래들, 갈래 순서).

    간단한 결과의 사유가 어느 비교를 쓸지 고르는 데만 쓴다. 판정 계산은 그대로다.
    """

    def two_branches(self, text_branch=False):
        branches = [branch("bA", [threshold("tA", "길이", "ge", 100, "nm")]),
                    branch("bB", [threshold("tB", "출력", "ge", 10, "W")])]
        if text_branch:
            branches.append(branch("bC", text="숫자 없는 갈래 원문"))
        return record("advanced:1", branches=branches)

    def clause(self, facts, pairs, cand=None):
        return je.judge(facts, [cand or self.two_branches()], pairs, ["advanced"]).clauses[0]

    def test_single_branch(self):
        _, _, clause = single("ge", 100, 120)
        self.assertEqual(clause["deciding_branch_ids"], ["b1"])

    def test_or_undecided_keeps_only_the_highest_branch(self):
        facts = [fact("f1", 50, "nm"), fact("f2", "9.5", "W")]       # A 미달, B 근접
        clause = self.clause(facts, [pair("advanced:1", "f1", "tA"), pair("advanced:1", "f2", "tB")])
        self.assertEqual(clause["verdict"], je.VERDICT_NEAR)
        self.assertEqual(clause["deciding_branch_ids"], ["bB"])

    def test_or_same_verdict_lists_branches_in_branch_order(self):
        facts = [fact("f1", 120, "nm"), fact("f2", 11, "W")]          # 둘 다 초과, 매핑 순서는 B가 먼저
        clause = self.clause(facts, [pair("advanced:1", "f2", "tB"), pair("advanced:1", "f1", "tA")])
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertEqual(clause["deciding_branch_ids"], ["bA", "bB"])

    def test_chosen_branch_only(self):
        facts = [fact("f1", 50, "nm"), fact("f2", "9.5", "W")]
        clause = self.clause(facts, [pair("advanced:1", "f1", "tA", branch_id="bA"),
                                     pair("advanced:1", "f2", "tB", branch_id="bA")])
        self.assertEqual(clause["verdict"], je.VERDICT_UNDER)
        self.assertEqual(clause["deciding_branch_ids"], ["bA"])

    def test_text_branch_chosen_considers_numeric_branches(self):
        facts = [fact("f1", 120, "nm"), fact("f2", 5, "W")]           # A 초과, B 미달
        cand = self.two_branches(text_branch=True)
        clause = self.clause(facts, [pair("advanced:1", "f1", "tA", branch_id="bC"),
                                     pair("advanced:1", "f2", "tB", branch_id="bC")], cand)
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)
        self.assertEqual(clause["deciding_branch_ids"], ["bA"])

    def test_not_compared_clauses_have_empty_list(self):
        no_fact = je.judge([], [self.two_branches()], [], ["advanced"]).clauses[0]
        self.assertEqual(no_fact["verdict"], je.CLAUSE_VERDICT_NOT_COMPARABLE)
        unit = single("ge", 100, 100, threshold_unit="m", fact_unit="초")[2]
        no_numeric = je.judge([], [record("core:1", family="core", branches=[branch("b1", text="정성")])], [], ["core"]).clauses[0]
        failed = je.judge([], [record("core:2", family="core", rejected=[rejected()])], [], ["core"]).clauses[0]
        for clause in (no_fact, unit, no_numeric, failed):
            self.assertEqual(clause["deciding_branch_ids"], [], clause["verdict"])

    def test_verdicts_and_counts_do_not_change(self):
        # 새 키를 더해도 판정·건수·확인 표시는 이전 계산 그대로다(같은 입력 → 같은 값).
        facts = [fact("f1", 50, "nm"), fact("f2", "9.5", "W")]
        result = je.judge(facts, [self.two_branches()], [pair("advanced:1", "f1", "tA"), pair("advanced:1", "f2", "tB")],
                          ["advanced"])
        clause = result.clauses[0]
        self.assertEqual((clause["verdict"], clause["flags"], clause["reason"]), (je.VERDICT_NEAR, [je.FLAG_BRANCH], ""))
        self.assertEqual(result.counts[je.COUNT_NEAR], 1)
        self.assertEqual(result.overall, je.VERDICT_NEAR)
        json.dumps(result.to_dict(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
