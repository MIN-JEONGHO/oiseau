"""한 과제 흐름(pipeline) 시험. 입력 확인·선택 칸 정리·상태·고시별 검토 결과·branch_choices 합치기를 합성 표·모의 클라이언트로 확인한다.

과제 글·조항·기준값은 모두 합성이며 실제 과제가 아니다. 실제 AI·키·파일을 쓰지 않는다.
"""
from copy import deepcopy
from decimal import Decimal
import inspect
import json
import unittest
from unittest import mock

import judge_engine as je
import pipeline
from ai_stages import SOURCE_EXCERPT, SOURCE_FINAL_GOAL, SOURCE_UTILIZATION, StageError
from threshold_table import BODY_SOURCE, STATUS_FAILED, STATUS_HAS, STATUS_NONE, ThresholdTable, validate_record
from tests.mock_model import MockModel

ALL_FAMILIES = ["advanced", "core", "dual_use", "military"]


# ── 합성 표·색인 ─────────────────────────────────────────────────────

def numeric_record(clause_id, family, title, subject, operator, value, unit, text_branch=None, checks=()):
    short = clause_id.replace(":", "_")
    branches = [dict(branch_id=short + ":b1", label="가", text="",
                     thresholds=[dict(threshold_id=short + ":t1", subject=subject, operator=operator, value=value,
                                      unit=unit, quote=f"{subject} {value} {unit}", quote_source=BODY_SOURCE,
                                      origin="structured")])]
    if text_branch:
        branches.append(dict(branch_id=short + ":b2", label="나", thresholds=[], text=text_branch))
    return dict(clause_id=clause_id, family=family, numeric_status=STATUS_HAS, title=title, branches=branches,
                rejected=[], checks=[dict(quote=q, source=BODY_SOURCE) for q in checks])


def text_record(clause_id, family, title):
    short = clause_id.replace(":", "_")
    return dict(clause_id=clause_id, family=family, numeric_status=STATUS_NONE, title=title,
                branches=[dict(branch_id=short + ":b1", label="", thresholds=[], text="합성 정성 조건")],
                rejected=[], checks=[])


def failed_record(clause_id, family, title):
    return dict(clause_id=clause_id, family=family, numeric_status=STATUS_FAILED, title=title, branches=[],
                rejected=[dict(branch_id="", subject="출력", quote="큰 출력", reason="수가 없음")], checks=[])


def make_table(records):
    for record in records:
        validate_record(record)
    return ThresholdTable(catalogue_id="synthetic", catalogue_fingerprint="0" * 64, near_percent=10,
                          fingerprint="1" * 64, records=tuple(deepcopy(records)))


RECORDS = [
    numeric_record("advanced:item:001", "advanced", "16나노 이하급 D램", "D램 공정노드", "le", "16", "nm",
                   checks=["양산 가능한 것에 한함"]),
    text_record("advanced:item:002", "advanced", "첨단 정성 항목"),
    text_record("core:item:001", "core", "30나노 D램"),
    numeric_record("dual_use:control:1A003", "dual_use", "필름 두께", "두께", "gt", "0.254", "mm", text_branch="탄소로 코팅된 것"),
    numeric_record("dual_use:control:1A004", "dual_use", "원자로 출력", "출력", "ge", "15000", "kW"),
    failed_record("military:item:001", "military", "군용 채택 실패 항목"),
]
TABLE = make_table(RECORDS)
INDEX = [dict(clause_id=r["clause_id"], family=r["family"],
              code=r["clause_id"].split(":")[-1] if r["family"] == "dual_use" else "",
              title=r["title"], field="합성 분야") for r in RECORDS]

FINAL_GOAL = "본 과제의 최종 목표는 D램 공정노드 14 nm 달성이다. 현재 보유 수준은 20 nm이다."
CONTENT = "메모리 공정 개선과 소재 평가를 수행한다."
UTILIZATION = "반도체 제조사에 기술 이전을 추진한다."
EXCERPT = "필름 두께 0.3 mm 이상 코팅 공정 개발"
# 과제요약정보 세 칸만 있는 과제 입력(발췌 없음). 연구개발단계·지원금은 판정·AI에 쓰지 않는다.
SUMMARY_TASK = dict(title="합성 과제 — 차세대 메모리 공정", final_goal=FINAL_GOAL, rnd_content=CONTENT, utilization=UTILIZATION)
TASK = dict(SUMMARY_TASK, excerpt=EXCERPT, rnd_stage="응용연구", gov_fund="1250.5")


def fact(fact_id, text, field_name, quote, subject, low, high, unit):
    start = text.index(quote)
    return dict(fact_id=fact_id, subject=subject, value_text=quote, low=low, high=high, unit=unit,
                source_field=field_name, start=start, end=start + len(quote), quote=quote)


FACTS = [
    fact("f1", FINAL_GOAL, SOURCE_FINAL_GOAL, "14 nm", "D램 공정노드", "14", "14", "nm"),
    fact("f2", EXCERPT, SOURCE_EXCERPT, "0.3 mm", "두께", "0.3", "0.3", "mm"),
]


class BoomClient:
    """첫 요청에서 일반 예외를 내는 클라이언트."""

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        raise RuntimeError("합성 연결 실패")


# ── 입력 확인(개별 검토 시작 조건) ───────────────────────────────────────

class InputTests(unittest.TestCase):
    def test_title_required(self):
        with self.assertRaises(pipeline.InputError) as caught:
            pipeline.validate_task(dict(SUMMARY_TASK, title="  "))
        self.assertIn("연구개발과제명", str(caught.exception))
        with self.assertRaises(pipeline.InputError):
            pipeline.validate_task(dict(title="", excerpt="확인한 발췌 글"))

    def test_all_three_summary_fields_required_without_excerpt(self):
        for key, label in (("final_goal", "최종목표"), ("rnd_content", "연구개발내용"), ("utilization", "활용계획 및 기대효과")):
            with self.assertRaises(pipeline.InputError) as caught:
                pipeline.validate_task(dict(SUMMARY_TASK, **{key: " "}))
            self.assertIn(label, str(caught.exception))
        clean = pipeline.validate_task(SUMMARY_TASK)
        self.assertEqual((clean["final_goal"], clean["rnd_content"], clean["utilization"]), (FINAL_GOAL, CONTENT, UTILIZATION))
        self.assertEqual(clean["excerpt"], "")

    def test_attachment_without_confirmed_excerpt_counts_as_no_attachment(self):
        # 첨부를 골랐어도 발췌를 확인하지 않았으면(빈 발췌) 세 칸이 모두 필요하고, 파일 이름은 '입력 정보'에 나오지 않는다.
        with self.assertRaises(pipeline.InputError):
            pipeline.validate_task(dict(SUMMARY_TASK, utilization="", excerpt="", attachment_name="계획서.hwpx"))
        clean = pipeline.validate_task(dict(SUMMARY_TASK, excerpt="  ", attachment_name="계획서.hwpx"))
        self.assertEqual(clean["attachment_name"], "")
        self.assertEqual(pipeline.describe_input(clean), "과제요약정보")

    def test_confirmed_excerpt_makes_three_fields_optional(self):
        clean = pipeline.validate_task(dict(title="과제", excerpt="발췌 글", attachment_name="계획서.hwpx"))
        self.assertEqual((clean["final_goal"], clean["rnd_content"], clean["utilization"]), ("", "", ""))
        self.assertEqual(clean["excerpt"], "발췌 글")
        self.assertEqual(pipeline.describe_input(clean), "계획서.hwpx")
        partial = pipeline.validate_task(dict(title="과제", final_goal="최종 목표 글", excerpt="발췌 글"))
        self.assertEqual(partial["final_goal"], "최종 목표 글")

    def test_task_number_key_is_gone(self):
        clean = pipeline.validate_task(dict(SUMMARY_TASK, task_no="S-001"))
        self.assertNotIn("task_no", clean)
        self.assertEqual(set(clean), {"title", "final_goal", "rnd_content", "utilization", "excerpt", "attachment_name",
                                      "rnd_stage", "gov_fund", "row_number"})
        self.assertNotIn("task_no", pipeline.TaskResult().to_dict())

    def test_optional_fields_kept_after_cleaning(self):
        clean = pipeline.validate_task(dict(SUMMARY_TASK, rnd_stage="개발", gov_fund="1,250.5"))
        self.assertEqual(clean["rnd_stage"], "개발연구")
        self.assertEqual(clean["gov_fund"], "1250.5")
        empty = pipeline.validate_task(SUMMARY_TASK)
        self.assertEqual((empty["rnd_stage"], empty["gov_fund"]), ("", ""))
        # 정리하지 않은 잘못된 값이 그대로 들어오면 조용히 지우지 않고 거부한다.
        with self.assertRaises(pipeline.InputError):
            pipeline.validate_task(dict(SUMMARY_TASK, rnd_stage="중간연구"))
        with self.assertRaises(pipeline.InputError):
            pipeline.validate_task(dict(SUMMARY_TASK, gov_fund="-3"))

    def test_run_task_rejects_bad_input(self):
        with self.assertRaises(pipeline.InputError):
            pipeline.run_task(dict(SUMMARY_TASK, title=""), ALL_FAMILIES, MockModel(facts=FACTS), TABLE, INDEX)
        with self.assertRaises(pipeline.InputError) as caught:
            pipeline.run_task(SUMMARY_TASK, [], MockModel(facts=FACTS), TABLE, INDEX)
        self.assertIn("검토 대상 고시", str(caught.exception))

    def test_input_description(self):
        self.assertEqual(pipeline.describe_input(dict(title="t", final_goal="목표")), "과제요약정보")
        self.assertEqual(pipeline.describe_input(dict(title="t", utilization="활용")), "과제요약정보")
        self.assertEqual(pipeline.describe_input(dict(title="t", excerpt="x", attachment_name="계획서.hwpx")), "계획서.hwpx")
        self.assertEqual(pipeline.describe_input(dict(SUMMARY_TASK, excerpt="x", attachment_name="계획서.hwpx")),
                         "과제요약정보; 계획서.hwpx")
        # 발췌를 확인하지 않은 첨부는 파일 이름이 나오지 않는다.
        self.assertEqual(pipeline.describe_input(dict(SUMMARY_TASK, excerpt="", attachment_name="계획서.hwpx")), "과제요약정보")


# ── 선택 칸 정리(연구개발단계·정부지원연구개발비) ──────────────────────────

class OptionalFieldTests(unittest.TestCase):
    def test_stage_short_names_become_full_names(self):
        for raw, full in (("기초연구", "기초연구"), ("기초", "기초연구"), (" 응용 ", "응용연구"), ("응용 연구", "응용연구"),
                          ("개발연구", "개발연구"), ("개발", "개발연구")):
            self.assertEqual(pipeline.normalize_rnd_stage(raw, 4), (full, None), raw)

    def test_stage_blank_has_no_warning(self):
        for raw in (None, "", "   "):
            self.assertEqual(pipeline.normalize_rnd_stage(raw, 4), ("", None))

    def test_stage_other_value_is_blank_with_warning(self):
        value, warning = pipeline.normalize_rnd_stage("중간연구", 7)
        self.assertEqual(value, "")
        self.assertEqual(warning, dict(row_number=7, field="연구개발단계", value="중간연구",
                                       message="7행: 연구개발단계 값 확인 필요 — 중간연구"))
        value, warning = pipeline.normalize_rnd_stage(3, 8)
        self.assertEqual(value, "")
        self.assertEqual(warning["message"], "8행: 연구개발단계 값 확인 필요 — 3")
        # 개별 검토(행 번호 없음)는 같은 형식에서 행 번호만 뺀다.
        self.assertEqual(pipeline.normalize_rnd_stage("기타", None)[1]["message"], "연구개발단계 값 확인 필요 — 기타")

    def test_fund_accepts_commas_decimals_and_excel_numbers(self):
        cases = (("1,250", "1250"), ("1,250.75", "1250.75"), (" 0.5 ", "0.5"), ("12,345,678", "12345678"),
                 (1500, "1500"), (1500.0, "1500"), (12.25, "12.25"), (Decimal("3.5"), "3.5"), ("99999999999", "99999999999"))
        for raw, text in cases:
            self.assertEqual(pipeline.normalize_gov_fund(raw, 2), (text, None), raw)

    def test_fund_blank_has_no_warning(self):
        for raw in (None, "", "  "):
            self.assertEqual(pipeline.normalize_gov_fund(raw, 2), ("", None))

    def test_fund_zero_negative_or_text_is_blank_with_warning(self):
        for raw, shown in (("0", "0"), ("-5", "-5"), (0, "0"), (-2.5, "-2.5"), ("약 10억", "약 10억"), ("1e3", "1e3"),
                           ("10백만원", "10백만원"), (True, "True"), (float("nan"), "nan"), ("NaN", "NaN"), ("Infinity", "Infinity")):
            value, warning = pipeline.normalize_gov_fund(raw, 5)
            self.assertEqual(value, "", raw)
            self.assertEqual(warning["field"], "정부지원연구개발비")
            self.assertEqual(warning["row_number"], 5)
            self.assertEqual(warning["value"], shown)
            self.assertEqual(warning["message"], f"5행: 정부지원연구개발비 값 확인 필요 — {shown}")
        self.assertEqual(pipeline.normalize_gov_fund("없음", None)[1]["message"], "정부지원연구개발비 값 확인 필요 — 없음")


# ── 상태 다섯 가지 ─────────────────────────────────────────────────────

class StatusTests(unittest.TestCase):
    def test_done(self):
        model = MockModel(facts=FACTS, candidates={"advanced:item:001", "advanced:item:002", "dual_use:control:1A003",
                                                   "military:item:001"})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        self.assertEqual(result.error_reason, "")
        self.assertEqual(result.title, TASK["title"])
        # 발췌는 있으나 첨부 파일 이름이 없으면 '입력 정보'는 과제요약정보뿐이다.
        self.assertEqual(result.input_description, "과제요약정보")
        # 연구개발단계·지원금은 결과에 실리지만 판정에는 쓰지 않는다.
        self.assertEqual(result.rnd_stage, "응용연구")
        self.assertEqual(result.gov_fund, "1250.5")
        self.assertIsNone(result.row_number)
        self.assertEqual(result.calls["extract"], 1)
        self.assertEqual(result.calls["screen"], 1)
        self.assertEqual(result.calls["pair"], 1)
        self.assertEqual(result.calls["total"], 3)
        self.assertEqual(result.families["advanced"], je.VERDICT_OVER)   # 14 nm ≤ 16 nm
        self.assertEqual(result.families["dual_use"], je.VERDICT_OVER)   # 0.3 mm > 0.254 mm
        self.assertEqual(result.families["core"], je.FAMILY_VERDICT_NONE)
        self.assertEqual(result.families["military"], je.FAMILY_VERDICT_NONE)  # 채택 실패 항목뿐
        self.assertEqual(result.overall, je.VERDICT_OVER)
        self.assertEqual(result.counts[je.COUNT_OVER], 2)
        self.assertEqual(result.counts[je.COUNT_NO_NUMERIC], 1)
        self.assertEqual(result.counts[je.COUNT_NOT_COMPARABLE], 1)
        self.assertEqual(sorted(result.candidate_ids), sorted(["advanced:item:001", "advanced:item:002",
                                                               "dual_use:control:1A003", "military:item:001"]))
        # 후보 기록에 기준본 색인의 code가 들어가 판정 결과에 남는다.
        codes = {c["clause_id"]: c["code"] for c in result.judge["clauses"]}
        self.assertEqual(codes["dual_use:control:1A003"], "1A003")
        self.assertEqual(codes["advanced:item:001"], "")
        comparison_codes = {c["clause_id"]: c["code"] for c in result.judge["comparisons"]}
        self.assertEqual(comparison_codes["dual_use:control:1A003"], "1A003")
        # JSON 직렬화 가능
        json.dumps(result.to_dict(), ensure_ascii=False)

    def test_no_facts_makes_no_more_calls(self):
        model = MockModel(facts=[])
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_NO_FACTS)
        self.assertEqual([r["stage"] for r in model.requests], ["extract"])
        self.assertEqual(result.calls, dict(extract=1, screen=0, pair=0, total=1))
        self.assertEqual(result.families, {f: je.FAMILY_VERDICT_STATUS for f in ALL_FAMILIES})
        self.assertEqual(result.overall, je.FAMILY_VERDICT_STATUS)
        self.assertIsNone(result.judge)
        self.assertEqual(result.counts, {k: 0 for k in je.COUNT_KEYS})

    def test_no_candidates(self):
        model = MockModel(facts=FACTS, candidates=set())
        result = pipeline.run_task(TASK, ["advanced", "core"], model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_NO_CANDIDATES)
        self.assertEqual([r["stage"] for r in model.requests], ["extract", "screen"])
        self.assertEqual(result.families, dict(advanced=je.FAMILY_VERDICT_NONE, core=je.FAMILY_VERDICT_NONE,
                                               dual_use=je.FAMILY_VERDICT_EXCLUDED, military=je.FAMILY_VERDICT_EXCLUDED))
        self.assertEqual(result.overall, je.FAMILY_VERDICT_NONE)
        self.assertEqual(result.facts, FACTS)

    def test_stage_error_becomes_error_status(self):
        model = MockModel(facts=FACTS, faults={"extract": ["shape", "shape"]})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_ERROR)
        self.assertIn("최종목표 사양 추출", result.error_reason)
        self.assertNotIn("목표 수치 추출", result.error_reason)
        self.assertEqual(result.calls["extract"], 2)
        self.assertEqual(result.families, {f: je.FAMILY_VERDICT_STATUS for f in ALL_FAMILIES})
        self.assertEqual(result.overall, je.FAMILY_VERDICT_STATUS)

    def test_generic_exception_becomes_error_status(self):
        result = pipeline.run_task(TASK, ["advanced"], BoomClient(), TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_ERROR)
        self.assertIn("RuntimeError", result.error_reason)
        self.assertIn("합성 연결 실패", result.error_reason)
        self.assertEqual(result.families, dict(advanced=je.FAMILY_VERDICT_STATUS, core=je.FAMILY_VERDICT_EXCLUDED,
                                               dual_use=je.FAMILY_VERDICT_EXCLUDED, military=je.FAMILY_VERDICT_EXCLUDED))

    def test_pairing_skipped_when_no_numeric_candidates(self):
        model = MockModel(facts=FACTS, candidates={"advanced:item:002"})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        self.assertEqual(result.calls["pair"], 0)
        self.assertEqual(result.families["advanced"], je.FAMILY_VERDICT_NONE)

    def test_status_rule_helper(self):
        rule = pipeline.family_verdicts_for_status
        self.assertEqual(rule(pipeline.STATUS_CANCELLED, ["core"], None),
                         (dict(advanced=je.FAMILY_VERDICT_EXCLUDED, core=je.FAMILY_VERDICT_STATUS,
                               dual_use=je.FAMILY_VERDICT_EXCLUDED, military=je.FAMILY_VERDICT_EXCLUDED), je.FAMILY_VERDICT_STATUS))
        self.assertEqual(rule(pipeline.STATUS_ERROR, ALL_FAMILIES, None)[1], je.FAMILY_VERDICT_STATUS)
        self.assertEqual(rule(pipeline.STATUS_NO_FACTS, ALL_FAMILIES, None)[1], je.FAMILY_VERDICT_STATUS)
        self.assertEqual(rule(pipeline.STATUS_NO_CANDIDATES, ["military"], None)[0]["military"], je.FAMILY_VERDICT_NONE)
        judged = dict(families=dict(advanced=je.VERDICT_NEAR, core=je.FAMILY_VERDICT_EXCLUDED,
                                    dual_use=je.FAMILY_VERDICT_EXCLUDED, military=je.FAMILY_VERDICT_EXCLUDED), overall=je.VERDICT_NEAR)
        self.assertEqual(rule(pipeline.STATUS_DONE, ["advanced"], judged), (judged["families"], je.VERDICT_NEAR))


# ── branch_choices 합치기·dropped 합치기 ─────────────────────────────

class MergeTests(unittest.TestCase):
    def test_fill_empty_branch_id_and_add_choice_only_pair(self):
        pairs = [dict(clause_id="c1", fact_id="f1", threshold_id="t1", branch_id="", reason="r", ambiguous=False),
                 dict(clause_id="c1", fact_id="f2", threshold_id="t2", branch_id="c1:b2", reason="r", ambiguous=False),
                 dict(clause_id="c3", fact_id="f1", threshold_id="t3", branch_id="", reason="r", ambiguous=False)]
        choices = [dict(clause_id="c1", branch_id="c1:b1", reason="갈래 가"),
                   dict(clause_id="c2", branch_id="c2:b1", reason="갈래 나")]
        merged = pipeline.merge_branch_choices(pairs, choices)
        self.assertEqual(merged[0]["branch_id"], "c1:b1")
        self.assertEqual(merged[1]["branch_id"], "c1:b2")      # 이미 있는 값은 두고
        self.assertEqual(merged[2]["branch_id"], "")           # 선택이 없는 조항은 그대로
        self.assertEqual(merged[3], dict(clause_id="c2", fact_id="", threshold_id="", branch_id="c2:b1",
                                         reason="갈래 나", ambiguous=False))
        self.assertEqual(len(merged), 4)
        self.assertEqual(pairs[0]["branch_id"], "")             # 입력은 바꾸지 않는다

    def test_choice_reaches_judge(self):
        # 숫자 갈래가 둘인 합성 항목. 갈래를 고르지 않으면 엔진이 '갈래 확인 필요'를 붙이고, 고르면 붙이지 않는다.
        two = numeric_record("dual_use:control:9Z999", "dual_use", "두 갈래 필름", "두께", "gt", "0.254", "mm")
        two["branches"].append(dict(branch_id="dual_use_control_9Z999:b2", label="나", text="",
                                    thresholds=[dict(threshold_id="dual_use_control_9Z999:t2", subject="두께", operator="gt",
                                                     value="0.5", unit="mm", quote="두께 0.5 mm", quote_source=BODY_SOURCE,
                                                     origin="structured")]))
        table = make_table(RECORDS + [two])
        index = INDEX + [dict(clause_id=two["clause_id"], family="dual_use", code="9Z999", title=two["title"], field="합성")]

        def transform(stage, payload, out, choose=True):
            if stage == "pair":
                for pair in out["pairs"]:
                    pair["branch_id"] = ""
                out["branch_choices"] = ([dict(clause_id=two["clause_id"], branch_id="dual_use_control_9Z999:b1", reason="갈래 가")]
                                         if choose else [])
            return out
        chosen = pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=FACTS, candidates={two["clause_id"]}, transform=transform),
                                   table, index)
        self.assertEqual(chosen.status, pipeline.STATUS_DONE)
        clause = chosen.judge["clauses"][0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)             # 갈래 가: 0.3 mm > 0.254 mm
        self.assertNotIn(je.FLAG_BRANCH, clause["flags"])              # 갈래를 골랐으니 갈래 확인 표시가 없다
        unchosen = pipeline.run_task(TASK, ALL_FAMILIES,
                                     MockModel(facts=FACTS, candidates={two["clause_id"]},
                                               transform=lambda s, p, o: transform(s, p, o, choose=False)), table, index)
        self.assertIn(je.FLAG_BRANCH, unchosen.judge["clauses"][0]["flags"])

    def test_dropped_merges_all_stages(self):
        bad_fact = dict(FACTS[0], fact_id="bad", quote="99 zz")   # 인용이 글에 없어 버려지는 최종목표 사양

        def transform(stage, payload, out):
            if stage == "pair":
                out["pairs"].append(dict(clause_id="advanced:item:001", fact_id="없는 수치", threshold_id="advanced_item_001:t1",
                                         branch_id="", reason="r", ambiguous=False))
            return out
        model = MockModel(facts=[bad_fact] + FACTS, candidates={"advanced:item:001"}, transform=transform)
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        stages = [d["stage"] for d in result.dropped]
        self.assertIn(pipeline.DROP_STAGE_EXTRACT, stages)
        self.assertIn(pipeline.DROP_STAGE_PAIR, stages)
        for item in result.dropped:
            self.assertEqual(set(item), {"stage", "kind", "ids", "reason"})
            self.assertTrue(item["reason"])

    def test_candidate_missing_from_table_is_reported(self):
        index = INDEX + [dict(clause_id="advanced:item:099", family="advanced", code="", title="표에 없는 항목", field="합성")]
        model = MockModel(facts=FACTS, candidates={"advanced:item:099", "advanced:item:001"})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, index)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        self.assertEqual(len(result.judge["clauses"]), 1)
        self.assertTrue(any(d["stage"] == pipeline.DROP_STAGE_CANDIDATE and "advanced:item:099" in d["ids"] for d in result.dropped))
        missing = [d for d in result.dropped if d["stage"] == pipeline.DROP_STAGE_CANDIDATE]
        self.assertEqual(missing[0]["stage"], "관련 고시 조항")
        self.assertEqual(missing[0]["kind"], "관련 고시 조항")
        self.assertEqual(missing[0]["reason"], "고시 기준 사양 표에 없는 관련 고시 조항")

    def test_dropped_stage_and_kind_names(self):
        self.assertEqual(pipeline.DROP_STAGE_EXTRACT, "최종목표 사양 추출")
        self.assertEqual(pipeline.DROP_STAGE_PAIR, "매핑")
        bad_fact = dict(FACTS[0], fact_id="bad", quote="99 zz")   # 인용이 글에 없어 버려지는 최종목표 사양
        result = pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=[bad_fact]), TABLE, INDEX)
        self.assertEqual(result.dropped[0]["stage"], "최종목표 사양 추출")
        self.assertEqual(result.dropped[0]["kind"], "최종목표 사양")
        self.assertEqual(result.dropped[0]["reason"], "인용이 글에 없음")

    def test_progress_and_counter_passed_through(self):
        events = []
        counter = pipeline.CallCounter()
        model = MockModel(facts=FACTS, candidates={"advanced:item:001"})
        pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX, progress=events.append, counter=counter)
        self.assertEqual(counter.calls, 3)
        self.assertTrue(any(e["stage"] == "extract" for e in events))


# ── 네 출처 사이 목표값 불일치(spec 3) ──────────────────────────────────

class FourSourceInconsistencyTests(unittest.TestCase):
    """같은 고시 기준에 서로 다른 출처의 다른 값이 매핑되면 더 높은 판정과 '입력 간 목표값 불일치'."""

    def test_final_goal_and_utilization_values_differ(self):
        final_goal = "최종 목표: 원자로 출력 12000 kW 달성."
        utilization = "향후 확장 시 원자로 출력 16000 kW 적용."
        task = dict(title="합성 원자로 과제", final_goal=final_goal, rnd_content="원자로 설계와 시험을 수행한다.",
                    utilization=utilization, rnd_stage="개발연구", gov_fund="300")
        facts = [fact("g1", final_goal, SOURCE_FINAL_GOAL, "12000 kW", "출력", "12000", "12000", "kW"),
                 fact("u1", utilization, SOURCE_UTILIZATION, "16000 kW", "출력", "16000", "16000", "kW")]
        model = MockModel(facts=facts, candidates={"dual_use:control:1A004"})
        result = pipeline.run_task(task, ["dual_use"], model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        comparisons = {c["fact_id"]: c for c in result.judge["comparisons"]}
        self.assertEqual(comparisons["g1"]["verdict"], je.VERDICT_UNDER)   # 12000 kW: 기준 15000 kW에 20% 못 미침
        self.assertEqual(comparisons["u1"]["verdict"], je.VERDICT_OVER)    # 16000 kW ≥ 15000 kW
        self.assertEqual(comparisons["g1"]["source_field"], "최종목표")
        self.assertEqual(comparisons["u1"]["source_field"], "활용계획 및 기대효과")
        for comp in comparisons.values():
            self.assertIn(je.FLAG_INCONSISTENT, comp["flags"])
        clause = result.judge["clauses"][0]
        self.assertEqual(clause["verdict"], je.VERDICT_OVER)               # 더 높은 판정
        self.assertIn(je.FLAG_INCONSISTENT, clause["flags"])
        self.assertEqual(result.families["dual_use"], je.VERDICT_OVER)
        self.assertEqual(result.overall, je.VERDICT_OVER)


# ── 간단한 결과(brief) 연결(1.3.0, 모양은 1.4.0 spec R7-1) ──────────────────────

OLD_RESULT_KEYS = {"title", "rnd_stage", "gov_fund", "input_description", "status", "error_reason", "families", "overall",
                   "counts", "flagged_clause_count", "judge", "facts", "candidate_ids", "dropped", "calls", "row_number"}
BRIEF_KEYS = ("overall", "reason", "group", "families", "hints", "empty_message", "focus", "under", "review", "counts",
              "semantic")


class RankingEngine:
    """가짜 검색 엔진: 정해 둔 순위를 돌려준다."""

    def __init__(self, ranking):
        self.ranking = ranking
        self.texts = []

    def semantic_ranking(self, text):
        self.texts.append(text)
        return dict(available=True, reason="", ranking={f: list(self.ranking.get(f, [])) for f in pipeline.FAMILY_ORDER})


class BriefPlumbingTests(unittest.TestCase):
    def test_new_arguments_are_optional_keywords(self):
        for function, names in ((pipeline.run_task, ("search_engine", "option_warnings")),
                                (pipeline.cancelled_result, ("option_warnings",)),
                                (pipeline.error_result, ("option_warnings",))):
            params = inspect.signature(function).parameters
            for name in names:
                self.assertEqual(params[name].kind, inspect.Parameter.KEYWORD_ONLY, (function.__name__, name))
        self.assertIsNone(inspect.signature(pipeline.run_task).parameters["search_engine"].default)
        for function in (pipeline.run_task, pipeline.cancelled_result, pipeline.error_result):
            self.assertEqual(tuple(inspect.signature(function).parameters["option_warnings"].default), ())

    def test_every_status_has_brief_and_old_keys_stay(self):
        results = [
            pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=FACTS, candidates={"advanced:item:001"}), TABLE, INDEX),
            pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=[]), TABLE, INDEX),
            pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=FACTS, candidates=set()), TABLE, INDEX),
            pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=FACTS, faults={"pair": ["shape", "shape"]},
                                                            candidates={"advanced:item:001"}), TABLE, INDEX),
            pipeline.run_task(TASK, ["core"], BoomClient(), TABLE, INDEX),
            pipeline.cancelled_result(TASK, ALL_FAMILIES),
            pipeline.error_result(TASK, ALL_FAMILIES, "합성 오류"),
        ]
        self.assertEqual([r.status for r in results], [pipeline.STATUS_DONE, pipeline.STATUS_NO_FACTS,
                                                       pipeline.STATUS_NO_CANDIDATES, pipeline.STATUS_ERROR,
                                                       pipeline.STATUS_ERROR, pipeline.STATUS_CANCELLED, pipeline.STATUS_ERROR])
        for result in results:
            data = result.to_dict()
            self.assertEqual(set(data), OLD_RESULT_KEYS | {"brief"}, result.status)
            self.assertEqual(tuple(data["brief"]), BRIEF_KEYS, result.status)
            for gone in ("notices", "summary_cell", "items"):       # 1.4.0: 공통 안내와 옛 키는 싣지 않는다
                self.assertNotIn(gone, data["brief"])
            json.dumps(data, ensure_ascii=False, allow_nan=False)
        self.assertEqual([(r.brief["overall"], r.brief["group"], r.brief["reason"]) for r in results], [
            ("고시 사양 초과", "focus", "국가첨단전략기술 16나노 이하급 D램"), ("고시 사양 미달", "other", "최종목표 수치 없음"),
            ("고시 사양 미달", "other", "관련 고시 조항 없음"), ("오류", "unjudged", ""), ("오류", "unjudged", ""),
            ("취소", "unjudged", ""), ("오류", "unjudged", "")])
        # 내부 값(과제 상태·고시별·종합 검토 결과)은 그대로다.
        self.assertEqual([r.overall for r in results], [je.VERDICT_OVER, je.FAMILY_VERDICT_STATUS, je.FAMILY_VERDICT_NONE]
                         + [je.FAMILY_VERDICT_STATUS] * 4)
        # to_dict는 사본이다.
        data = results[0].to_dict()
        data["brief"]["focus"].clear()
        self.assertTrue(results[0].brief["focus"])

    def test_option_warnings_only_reach_the_count_hint(self):
        warnings = [dict(row_number=None, field="연구개발단계", value="중간연구", message="연구개발단계 값 확인 필요 — 중간연구"),
                    dict(row_number=None, field="정부지원연구개발비", value="약 3억", message="정부지원연구개발비 값 확인 필요 — 약 3억")]
        plain_model, warned_model = (MockModel(facts=FACTS, candidates={"advanced:item:001"}) for _ in range(2))
        plain = pipeline.run_task(TASK, ALL_FAMILIES, plain_model, TABLE, INDEX)
        warned = pipeline.run_task(TASK, ALL_FAMILIES, warned_model, TABLE, INDEX, option_warnings=warnings)
        self.assertEqual(plain.brief["hints"], [])
        self.assertEqual(warned.brief["hints"], ["선택 칸 경고 2건 — 상세 보기에서 확인"])
        self.assertEqual([r["user"] for r in warned_model.requests], [r["user"] for r in plain_model.requests])
        for request in warned_model.requests:
            for text in ("중간연구", "약 3억"):
                self.assertNotIn(text, request["user"])
        self.assertEqual(warned.judge, plain.judge)
        self.assertNotIn("option_warnings", warned.to_dict())

    def test_counter_counts_once_and_brief_failure_is_visible(self):
        import brief
        counter = pipeline.CallCounter()
        engine = RankingEngine(dict(core=["core:item:001"]))
        model = MockModel(facts=FACTS, candidates={"advanced:item:001", "core:item:001"}, detail_matches={"core:item:001"})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX, counter=counter, search_engine=engine)
        self.assertEqual(counter.calls, result.calls["total"])
        self.assertEqual(len(engine.texts), 1)
        self.assertEqual(result.brief["review"][0]["clause_id"], "core:item:001")
        # brief를 만들다 실패하면 조용히 넘기지 않고 '오류'가 되며, 보낸 요청 수는 한 번만 센다.
        real = brief.build_brief

        def broken(status, *args, **kwargs):
            if status == pipeline.STATUS_DONE:
                raise ValueError("합성 brief 실패")
            return real(status, *args, **kwargs)
        counter = pipeline.CallCounter()
        with mock.patch.object(brief, "build_brief", side_effect=broken):
            failed = pipeline.run_task(TASK, ALL_FAMILIES, MockModel(facts=FACTS, candidates={"advanced:item:001"}), TABLE,
                                       INDEX, counter=counter)
        self.assertEqual(failed.status, pipeline.STATUS_ERROR)
        self.assertIn("합성 brief 실패", failed.error_reason)
        self.assertEqual(failed.brief["overall"], "오류")
        self.assertEqual(counter.calls, 3)


if __name__ == "__main__":
    unittest.main()
