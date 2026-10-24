"""Offline engine regressions: every model response is synthetic."""
import copy
import json
import unittest

from classification_v14 import classify_task
from llm_client_v14 import AuthenticationError, InvalidResponseError, PermissionError, UnsupportedModelError
from v14_domain import ITEM_NAMES, CRITERIA


TASK = {"과제명": "합성 시험 과제", "연구내용": "시험용 가상 연구 정보"}


def items(level="해당", detailed=True):
    result = []
    for definition in CRITERIA:
        entry = {"item": definition["name"], "level": level,
                 "note": "제공한 합성 사실에 따른 검토 이유", "law_refs": list(definition["security_refs"])}
        if detailed:
            entry.update(matched_reference="", needs_expert_review=False)
        result.append(entry)
    return result


class FakeClient:
    def __init__(self, overrides=None, scores=(2, 4, 5), grades=None):
        self.calls = []
        self.overrides = overrides or {}
        self.values = scores
        self.grades = grades or ("일반과제", "민감과제", "보안과제")

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        request = json.loads(user_prompt)
        self.calls.append((system_prompt, request))
        stage = request["stage"]
        key = request.get("reviewer_id", stage)
        if key in self.overrides:
            response = self.overrides[key]
            if callable(response):
                response = response(request)
            if isinstance(response, Exception):
                raise response
            return copy.deepcopy(response)
        if stage == "candidate":
            return {"is_candidate": True, "reason": "검토할 유출 영향이 있음", "uncertainty": ""}
        if stage == "criteria":
            return {"criteria": items()}
        if stage == "reviewer":
            index = int(request["reviewer_id"].split("-")[-1]) - 1
            return {"item_reviews": items(detailed=False),
                    "scores": {name: self.values[index] for name in request["selected_items"]}
                    if request["method"] == "impact" else {},
                    "grade": self.grades[index], "confidence": "보통",
                    "rationale": "독립적인 법적 정의 및 유출 영향 검토",
                    "discussion_points": "추가 보호 범위 논의", "unresolved_reasons": []}
        return {"final_grade": "민감과제", "confidence": "높음",
                "rationale": "법 제21조제5항상 추가 관리 필요성을 제공된 사실과 대조함",
                "discussion_points": "에이전트별 차이와 적용 근거 논의", "unresolved_reasons": []}


class EngineTests(unittest.TestCase):
    def test_agent_personas_and_prompts_keep_independent_same_model_reviews(self):
        expected = ('AI 기술분야 전문가', 'AI 연구보안 전문가', 'AI 기술사업화 전문가')
        for count in (1, 3):
            client = FakeClient()
            progress = []
            result = classify_task(TASK, {'num_reviewers': count}, client, progress.append)
            self.assertEqual(tuple(r['persona'] for r in result['reviewers']), expected[:count])
            requests = [request for _, request in client.calls if request['stage'] == 'reviewer']
            self.assertEqual(tuple(r['persona'] for r in requests), expected[:count])
            self.assertTrue(all('다른 에이전트의 결과 없이' in request['instructions'] for request in requests))
            self.assertTrue(all('strictness' not in request for request in requests))
            self.assertIn('AI 에이전트 독립 검토', progress)
            self.assertIn('AI 종합 검토의견 작성', progress)
            self.assertIn('실제 심의위원회', client.calls[0][0])

    def test_two_methods_and_reviewer_counts(self):
        for method in ("impact", "checklist"):
            for count in (1, 3):
                with self.subTest(method=method, count=count):
                    client = FakeClient()
                    result = classify_task(TASK, {"method": method, "num_reviewers": count}, client)
                    self.assertEqual(result["status"], "완료")
                    self.assertEqual(len(result["reviewers"]), count)
                    self.assertEqual(len(client.calls), count + 3)
                    self.assertEqual(result["criteria"][7]["level"], "미검토")
                    self.assertNotIn(ITEM_NAMES[7], result["selected_items"])
                    if method == "checklist":
                        self.assertEqual(result["weights"], {})
                        self.assertIsNone(result["overall_avg"])
                        self.assertIsNone(result["rule_grade"])
                        for reviewer in result["reviewers"]:
                            self.assertEqual(reviewer["scores"], {})
                            self.assertIsNone(reviewer["reviewer_score"])
                    else:
                        self.assertIsNotNone(result["overall_avg"])

    def test_row_and_run_policy_enable_eighth(self):
        for task, options in ((dict(TASK, **{"부처 세부기준": "합성 부처 판단척도 1~5"}), {}),
                              (TASK, {"ministry_policy": "합성 부처 기준"})):
            result = classify_task(task, options, FakeClient())
            self.assertIn(ITEM_NAMES[7], result["selected_items"])
            self.assertEqual(result["criteria"][7]["level"], "해당")

    def test_candidate_exclusion_and_uncertainty_are_distinct(self):
        for candidate, status in (({"is_candidate": False, "reason": "충분히 검토한 명확한 제외", "uncertainty": ""}, "후보제외"),
                                  ({"is_candidate": None, "reason": "자료 부족", "uncertainty": "사양 미제공"}, "검토필요"),
                                  ({"is_candidate": False, "reason": "제외 추정", "uncertainty": "미확인"}, "검토필요")):
            client = FakeClient({"candidate": candidate})
            result = classify_task(TASK, {}, client)
            self.assertEqual(result["status"], status)
            self.assertIsNone(result["final_grade"])
            self.assertEqual(result["reviewers"], [])
            self.assertEqual(len(client.calls), 1)

    def test_empty_impact_selection_but_checklist_can_be_ordinary(self):
        for method in ("impact", "checklist"):
            client = FakeClient({"criteria": {"criteria": items("미해당")}}, grades=("일반과제",) * 3)
            client.overrides["summary"] = {"final_grade": "일반과제", "confidence": "높음", "rationale": "보호 필요성 없음",
                                            "discussion_points": "", "unresolved_reasons": []}
            result = classify_task(TASK, {"method": method}, client)
            self.assertEqual(result["status"], "검토필요" if method == "impact" else "완료")
            self.assertIsNone(result["overall_avg"])
            self.assertEqual(result["final_grade"], None if method == "impact" else "일반과제")

    def test_independent_scores_grades_and_unrounded_average(self):
        client = FakeClient()
        result = classify_task(TASK, {}, client)
        self.assertEqual([r["reviewer_score"] for r in result["reviewers"]], [2, 4, 5])
        self.assertEqual([r["grade"] for r in result["reviewers"]], ["일반과제", "민감과제", "보안과제"])
        self.assertAlmostEqual(result["overall_avg"], 11 / 3)
        reviewers = [payload for _, payload in client.calls if payload["stage"] == "reviewer"]
        self.assertEqual([r["persona"] for r in reviewers], ["AI 기술분야 전문가", "AI 연구보안 전문가", "AI 기술사업화 전문가"])
        self.assertTrue(all("reviewers" not in reviewer for reviewer in reviewers))

    def test_one_failed_review_preserves_other_reviewers_and_no_average(self):
        client = FakeClient({"reviewer-2": {"item_reviews": []}})
        result = classify_task(TASK, {}, client)
        self.assertEqual(result["status"], "검토필요")
        self.assertEqual([r["status"] for r in result["reviewers"]], ["완료", "검토필요", "완료"])
        self.assertEqual(result["reviewers"][2]["scores"][ITEM_NAMES[0]], 5)
        self.assertIsNone(result["overall_avg"])
        self.assertIsNone(result["final_grade"])
        self.assertEqual(sum(p.get("reviewer_id") == "reviewer-2" for _, p in client.calls), 2)

    def test_strictness_only_reaches_last_call_and_does_not_change_scores(self):
        results = []
        for strictness in ("엄격", "표준", "관대"):
            client = FakeClient()
            results.append(classify_task(TASK, {"strictness": strictness}, client))
            for _, payload in client.calls[:-1]:
                self.assertNotIn("strictness", json.dumps(payload))
                self.assertNotIn("options_fingerprint", json.dumps(payload))
            self.assertEqual(client.calls[-1][1]["strictness"], strictness)
            reviewer_payloads = [p for _, p in client.calls if p["stage"] == "reviewer"]
            self.assertTrue(all("reviewers" not in p for p in reviewer_payloads))
        self.assertEqual([r["overall_avg"] for r in results], [11 / 3] * 3)

    def test_band_discrepancy_preserves_legal_opinion_and_marks_low_confidence(self):
        result = classify_task(TASK, {"num_reviewers": 1}, FakeClient())
        self.assertEqual(result["rule_grade"], "일반과제")
        self.assertEqual(result["final_grade"], "민감과제")
        self.assertEqual(result["confidence"], "낮음")
        self.assertIn("불일치", result["discussion_points"])

    def test_invalid_criteria_not_treated_as_all_nonapplicable(self):
        variants = [[], items()[:-1], items() + [items()[0]]]
        for field, value in (("item", ""), ("item", "군사"), ("level", "모름"), ("note", ""),
                             ("needs_expert_review", "false"), ("law_refs", ["제45조제1항제2호라목"]),
                             ("law_refs", ["제45조제1항제1호", "제45조제1항제1호"])):
            changed = items()
            changed[0][field] = value
            variants.append(changed)
        for invalid in variants:
            with self.subTest(invalid=invalid):
                client = FakeClient({"criteria": {"criteria": invalid}})
                result = classify_task(TASK, {}, client)
                self.assertEqual(result["status"], "검토필요")
                self.assertIsNone(result["final_grade"])
                self.assertEqual(result["reviewers"], [])
                self.assertEqual(len(client.calls), 3)

    def test_invalid_reviewer_scores_grades_and_reasons(self):
        for field, value in (("scores", {}), ("scores", {ITEM_NAMES[0]: float("nan")}),
                             ("scores", {name: 2.5 for name in ITEM_NAMES[:7]}),
                             ("scores", {name: 6 for name in ITEM_NAMES[:7]}),
                             ("grade", "확정"), ("grade", ""), ("rationale", ""), ("confidence", "매우 높음")):
            def altered(request, field=field, value=value):
                good = {"item_reviews": items(detailed=False), "scores": {n: 2 for n in request["selected_items"]},
                        "grade": "일반과제", "confidence": "보통", "rationale": "합성 검토 이유", "discussion_points": "", "unresolved_reasons": []}
                good[field] = value
                return good
            result = classify_task(TASK, {"num_reviewers": 1}, FakeClient({"reviewer-1": altered}))
            self.assertEqual(result["status"], "검토필요")
            self.assertIsNone(result["overall_avg"])
            self.assertIsNone(result["final_grade"])

    def test_expert_or_uncertain_evidence_remains_unresolved(self):
        for field, value in (("needs_expert_review", True), ("level", "판단곤란")):
            criterion = items()
            criterion[0][field] = value
            result = classify_task(TASK, {}, FakeClient({"criteria": {"criteria": criterion}}))
            self.assertEqual(result["status"], "검토필요")
            self.assertIsNone(result["final_grade"])
            self.assertTrue(result["unresolved_reasons"])

    def test_applicability_without_legal_reference_is_unresolved(self):
        criterion = items()
        criterion[0]["law_refs"] = []
        result = classify_task(TASK, {}, FakeClient({"criteria": {"criteria": criterion}}))
        self.assertEqual(result["status"], "검토필요")
        self.assertIsNone(result["final_grade"])
        self.assertIn("근거", " ".join(result["unresolved_reasons"]))

    def test_invalid_response_retry_and_auth_terminal_safe_failure(self):
        for exception, count, status in ((InvalidResponseError(), 2, "검토필요"), (AuthenticationError(), 1, "오류"),
                                         (PermissionError(), 1, "오류"), (UnsupportedModelError(), 1, "오류"),
                                         (RuntimeError("FAKE_SECRET in raw request"), 1, "오류")):
            client = FakeClient({"candidate": exception})
            result = classify_task(TASK, {}, client)
            self.assertEqual(len(client.calls), count)
            self.assertEqual(result["status"], status)
            self.assertNotIn("FAKE_SECRET", json.dumps(result))

    def test_terminal_reviewer_failure_retains_good_review_and_unstarted_slot(self):
        client = FakeClient({"reviewer-2": AuthenticationError()})
        result = classify_task(TASK, {}, client)
        self.assertEqual(result["status"], "오류")
        self.assertEqual([r["status"] for r in result["reviewers"]], ["완료", "검토필요", "미실시"])
        self.assertEqual(result["reviewers"][0]["scores"][ITEM_NAMES[0]], 2)
        self.assertEqual(result["reviewers"][2]["scores"], {})
        self.assertEqual(len(client.calls), 4)
        self.assertIsNone(result["overall_avg"])

    def test_summary_invalid_or_unresolved_does_not_invent_final_grade(self):
        for summary in ({"final_grade": ""},
                        {"final_grade": "민감과제", "confidence": "높음", "rationale": "근거 없는 상향",
                         "discussion_points": "", "unresolved_reasons": []},
                        {"final_grade": None, "confidence": "낮음", "rationale": "추가 사양 필요",
                         "discussion_points": "미확인 영향 논의", "unresolved_reasons": ["사양 미확인"]}):
            client = FakeClient({"summary": summary})
            result = classify_task(TASK, {"num_reviewers": 1}, client)
            self.assertEqual(result["status"], "검토필요")
            self.assertIsNone(result["final_grade"])
            self.assertEqual(result["overall_avg"], 2)
            self.assertEqual(result["reviewers"][0]["status"], "완료")

    def test_response_retry_can_recover_without_changing_model(self):
        attempts = []
        def candidate(request):
            attempts.append(request)
            return {} if len(attempts) == 1 else {"is_candidate": True, "reason": "충분한 검토 대상", "uncertainty": ""}
        client = FakeClient({"candidate": candidate})
        result = classify_task(TASK, {}, client)
        self.assertEqual(result["status"], "완료")
        self.assertEqual(len(attempts), 2)
        self.assertIn("validation_feedback", attempts[1])

    def test_manual_eighth_uses_row_policy_without_mutating_options(self):
        options = {"selection_mode": "manual", "selected_items": [8], "num_reviewers": 1}
        before = copy.deepcopy(options)
        result = classify_task(dict(TASK, **{"부처 세부기준": "가상 부처의 적용 척도"}), options, FakeClient())
        self.assertEqual(result["status"], "완료")
        self.assertEqual(result["selected_items"], [ITEM_NAMES[7]])
        self.assertEqual(options, before)
        with self.assertRaises(ValueError):
            classify_task(TASK, options, FakeClient())

    def test_numeric_ids_canonicalized_and_checklist_scores_rejected(self):
        criterion = items()
        for index, entry in enumerate(criterion, 1):
            entry["item"] = index
        result = classify_task(TASK, {}, FakeClient({"criteria": {"criteria": criterion}}))
        self.assertEqual([entry["item"] for entry in result["criteria"]], list(ITEM_NAMES))
        def wrong_scores(request):
            return {"item_reviews": items(detailed=False), "scores": {ITEM_NAMES[0]: 3},
                    "grade": "일반과제", "confidence": "보통", "rationale": "합성 이유",
                    "discussion_points": "", "unresolved_reasons": []}
        result = classify_task(TASK, {"method": "checklist", "num_reviewers": 1}, FakeClient({"reviewer-1": wrong_scores}))
        self.assertEqual(result["status"], "검토필요")
        self.assertEqual(result["reviewers"][0]["scores"], {})
        self.assertIsNone(result["overall_avg"])

    def test_auto_subset_weights_rejected_and_manual_canonical_ids(self):
        criterion = items("미해당")
        criterion[0]["level"] = "해당"
        result = classify_task(TASK, {"weights": {1: 1.2, 2: 0.8}}, FakeClient({"criteria": {"criteria": criterion}}))
        self.assertEqual(result["status"], "검토필요")
        self.assertIn("가중치", " ".join(result["unresolved_reasons"]))
        result = classify_task(TASK, {"selection_mode": "manual", "selected_items": [2, 1], "weights": {1: 1.2, 2: 0.8}}, FakeClient())
        self.assertEqual(result["selected_items"], list(ITEM_NAMES[:2]))
        self.assertEqual(result["weights"], {ITEM_NAMES[0]: 1.2, ITEM_NAMES[1]: 0.8})

    def test_client_model_mismatch_prevents_calls_and_options_secret_not_saved(self):
        client = FakeClient()
        client.provider = "openai"
        client.model = "gpt-6-luna"
        result = classify_task(TASK, {}, client)
        self.assertEqual(result["status"], "오류")
        self.assertFalse(client.calls)
        result = classify_task(TASK, {"api_key": "FAKE_SECRET"}, FakeClient())
        self.assertNotIn("FAKE_SECRET", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
