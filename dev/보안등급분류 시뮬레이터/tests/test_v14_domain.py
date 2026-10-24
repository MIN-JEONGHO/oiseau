"""Offline regression tests for the final guideline domain rules."""
import dataclasses
import json
import unittest

import v14_domain as domain


class GuidelineDomainTests(unittest.TestCase):
    def test_exact_identifiers_and_legal_mapping(self):
        self.assertEqual(len(domain.CRITERIA), 8)
        self.assertEqual(domain.resolve_item(8), "부처 정책상 관리 필요성")
        self.assertEqual(domain.resolve_item("3"), "국가핵심기술")
        self.assertIn("제45조제1항제2호다목", domain.CRITERIA[2]["security_refs"])
        self.assertEqual(domain.CRITERIA[2]["sensitive_refs"], ("제45조제2항제1호",))
        self.assertEqual(domain.CRITERIA[6]["sensitive_refs"], ("제45조제2항제3호",))
        self.assertIn("유출", domain.LEGAL_DEFINITIONS["보안과제"])
        for bad in ("", "핵심", "군사", True, 0, 9, None, "3. 국가핵심기술"):
            with self.subTest(item=bad), self.assertRaises(ValueError):
                domain.resolve_item(bad)
        self.assertEqual(domain.canonical_items([3, 1]), domain.ITEM_NAMES[:1] + domain.ITEM_NAMES[2:3])
        with self.assertRaises(ValueError):
            domain.canonical_items([1, domain.ITEM_NAMES[0]])

    def test_rubrics_are_impact_not_merit_and_policy_is_conditional(self):
        self.assertTrue(all(set(c["rubric"]) == set(range(1, 6)) for c in domain.CRITERIA[:7]))
        self.assertEqual(dict(domain.CRITERIA[7]["rubric"]), {})
        self.assertEqual(len(domain.eligible_items()), 7)
        self.assertEqual(len(domain.eligible_items("기관 정책 근거")), 8)
        result = domain.make_result({"과제명": "합성 과제"})
        self.assertEqual(result["criteria"][7]["level"], "미검토")
        self.assertTrue(all(c["level"] == "판단곤란" for c in result["criteria"][:7]))
        policy_result = domain.make_result({"과제명": "합성 과제", "부처 세부기준": "합성 정책"})
        self.assertEqual(policy_result["criteria"][7]["level"], "판단곤란")
        with self.assertRaises(ValueError):
            domain.normalize_options({"selection_mode": "manual", "selected_items": [8]})

    def test_score_validation_has_no_imputation_or_clipping(self):
        for value in (1, "2", "3.0", 4.0, "5e0"):
            self.assertIn(domain.parse_score(value), range(1, 6))
        for value in (None, "", "오류", True, False, "NaN", float("nan"), float("inf"), "-inf", 0, 6, 3.1, "3.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                domain.parse_score(value)

    def test_manual_item_eight_accepts_actual_row_policy_and_defers_only_for_batch(self):
        raw = {"selection_mode": "manual", "selected_items": [8]}
        row = {"과제명": "합성 과제", "부처 세부기준": "합성 부처의 별도 관리 기준"}
        with self.assertRaises(ValueError):
            domain.normalize_options(raw)
        direct = domain.normalize_options(raw, ministry_policy_context=row["부처 세부기준"])
        deferred = domain.normalize_options(raw, allow_row_policy=True)
        self.assertEqual(direct.to_dict(), deferred.to_dict())
        self.assertEqual(direct.ministry_policy, "")
        result = domain.make_result(row, deferred)
        self.assertEqual(result["selected_items"], [domain.ITEM_NAMES[7]])
        self.assertEqual(result["criteria"][7]["level"], "판단곤란")
        for absent in ({"과제명": "합성 과제"}, row | {"부처 세부기준": " \n "}):
            with self.subTest(row=absent), self.assertRaises(ValueError):
                domain.make_result(absent, deferred)
        run_policy = raw | {"ministry_policy": "실행 공통 기준"}
        self.assertEqual(domain.make_result({"과제명": "합성 과제"}, run_policy)["criteria"][7]["level"], "판단곤란")

    def test_row_policy_context_does_not_change_options_fingerprint(self):
        raw = {"selection_mode": "manual", "selected_items": [8]}
        task = {"과제명": "합성 과제", "부처 세부기준": "첫 기준"}
        other_task = task | {"부처 세부기준": "다른 기준"}
        first = domain.make_result(task, raw)
        second = domain.make_result(other_task, raw)
        self.assertEqual(first["options_fingerprint"], second["options_fingerprint"])
        self.assertEqual(first["options_fingerprint"], domain.options_fingerprint(raw))
        self.assertNotEqual(first["task_fingerprint"], second["task_fingerprint"])
        self.assertEqual(domain.options_fingerprint(raw), domain.options_fingerprint(
            domain.normalize_options(raw, ministry_policy_context="첫 기준")))

    def test_weight_limits_and_selected_mean(self):
        self.assertEqual(domain.validate_weights([1, 2], {1: .8, 2: 1.2}),
                         {domain.ITEM_NAMES[0]: .8, domain.ITEM_NAMES[1]: 1.2})
        self.assertEqual(list(domain.validate_weights([1, 2]).values()), [1.0, 1.0])
        for weights in ({1: .79, 2: 1.21}, {1: 1.2, 2: 1.1}, {1: True}, {1: float("nan")}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                domain.validate_weights([1, 2], weights)
        with self.assertRaises(ValueError):
            domain.validate_weights([], {})
        with self.assertRaises(ValueError):
            domain.validate_weights([1, 2, 3], {1: 1.2, 2: 1.1, 3: 1})
        # A full eight-item mean cannot conceal an invalid automatic subset.
        with self.assertRaises(ValueError):
            domain.validate_weights([1], {1: 1.2, 2: .8})
        # A permitted floating-error tolerance is not a reason to clip scores.
        score = domain.calculate_reviewer_score({1: 5}, [1], {1: 1.0000005})
        self.assertEqual(score, 5.0000025)
        self.assertEqual(domain.rule_grade(score), "보안과제")
        self.assertEqual(domain.calculate_committee_average(
            [{"reviewer_id": "1", "status": "완료", "reviewer_score": score}], 1), score)

    def test_formula_and_no_intermediate_rounding(self):
        score = domain.calculate_reviewer_score({1: 5, 2: 4, 3: 3, 4: 3}, [1, 2, 3, 4], {1: 1.2, 2: 1.1, 3: .9, 4: .8})
        self.assertEqual(score, 3.875)
        self.assertEqual(domain.format_score(score), "3.88")
        with self.assertRaises(ValueError):
            domain.calculate_reviewer_score({1: 5}, [1, 2])
        with self.assertRaises(ValueError):
            domain.calculate_reviewer_score({1: 5, 2: 3}, [1])
        reviewers = [{"reviewer_id": str(i), "status": "완료", "reviewer_score": score}
                     for i, score in enumerate([3.499, 3.499, 3.501])]
        average = domain.calculate_committee_average(reviewers, 3)
        self.assertLess(average, 3.5)
        self.assertEqual(domain.rule_grade(average), "일반과제")

    def test_thresholds_and_boundary_display(self):
        for score, grade in ((3.499999, "일반과제"), (3.5, "민감과제"), (3.500001, "민감과제"),
                             (4.499999, "민감과제"), (4.5, "보안과제"), (4.500001, "보안과제")):
            with self.subTest(score=score):
                self.assertEqual(domain.rule_grade(score), grade)
        self.assertEqual(domain.format_score(3.499999), "3.499999")
        self.assertEqual(domain.format_score(4.499), "4.499")
        self.assertEqual(domain.format_score(4.5), "4.50")
        self.assertIsNone(domain.rule_grade(None))

    def test_committee_needs_all_distinct_expected_reviewers(self):
        reviewers = [{"reviewer_id": str(i), "status": "완료", "reviewer_score": value}
                     for i, value in enumerate([5, 4, 3])]
        self.assertEqual(domain.calculate_committee_average(reviewers, 3), 4)
        self.assertIsNone(domain.calculate_committee_average(reviewers[:2], 3))
        reviewers[1]["reviewer_score"] = None
        self.assertIsNone(domain.calculate_committee_average(reviewers, 3))
        reviewers[1]["reviewer_score"] = 4
        reviewers[1]["status"] = "검토필요"
        self.assertIsNone(domain.calculate_committee_average(reviewers, 3))
        reviewers[1]["status"] = "완료"
        reviewers[1]["reviewer_id"] = "0"
        self.assertIsNone(domain.calculate_committee_average(reviewers, 3))

    def test_options_are_frozen_and_secrets_do_not_affect_identity(self):
        raw = {"selection_mode": "manual", "selected_items": [2, 1], "weights": {1: 1.2, 2: .8}, "api_key": "synthetic-secret"}
        opts = domain.normalize_options(raw)
        fingerprint = domain.options_fingerprint(opts)
        raw["weights"][1] = 1
        raw["selected_items"].clear()
        self.assertEqual(opts.selected_items, domain.ITEM_NAMES[:2])
        self.assertEqual(dict(opts.weights)[domain.ITEM_NAMES[0]], 1.2)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            opts.method = "checklist"
        changed_key = opts.to_dict() | {"api_key": "changed", "secret": "another"}
        self.assertEqual(domain.options_fingerprint(changed_key), fingerprint)
        self.assertNotIn("synthetic-secret", json.dumps(opts.to_dict()))
        for change in ({"strictness": "엄격"}, {"num_reviewers": 1}, {"ministry_policy": "새 정책"}, {"method": "checklist"}):
            self.assertNotEqual(domain.options_fingerprint(opts.to_dict() | change), fingerprint)

    def test_only_supported_methods_and_exact_cloud_models(self):
        self.assertEqual(domain.normalize_options({"provider": "openai"}).model, "gpt-6-luna")
        self.assertEqual(domain.normalize_options({"provider": "ollama", "model": "my-model"}).model, "my-model")
        for raw in ({"method": "combined"}, {"provider": "openai", "model": "fallback"}, {"num_reviewers": True}, {"num_reviewers": 2}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                domain.normalize_options(raw)
        for url in ("http://key@localhost:1234", "http://localhost:1234?api_key=secret", "file:///tmp/server"):
            with self.assertRaises(ValueError):
                domain.normalize_options({"local_base_url": url})

    def test_task_and_options_fingerprints_cover_public_inputs(self):
        task = {"과제명": "합성 과제", "연구내용": "합성 자료", "api_key": "discard"}
        self.assertEqual(domain.task_fingerprint(task), domain.task_fingerprint(task | {"api_key": "changed"}))
        for key in domain.TASK_COLUMNS + domain.OPTIONAL_TASK_COLUMNS:
            self.assertNotEqual(domain.task_fingerprint(task), domain.task_fingerprint(task | {key: "새 값"}))
        with self.assertRaises(ValueError):
            domain.task_snapshot({"과제명": "   "})

    def test_result_contract_has_no_invented_judgment_or_checklist_numbers(self):
        result = domain.make_result({"과제명": "합성 과제"}, {"method": "checklist", "weights": {1: 1.1}})
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["weights"], {})
        self.assertEqual(result["reviewers"], [])
        self.assertEqual(result["status"], "검토필요")
        self.assertIsNone(result["overall_avg"])
        self.assertIsNone(result["final_grade"])
        reviewer = domain.make_reviewer("reviewer-1", "기술 관점")
        self.assertEqual(reviewer["scores"], {})
        self.assertIsNone(reviewer["reviewer_score"])
        self.assertIsNone(reviewer["grade"])
        self.assertEqual(reviewer["status"], "미실시")
        self.assertEqual(result["documents"]["expected_files"], 4)
        json.dumps(result, ensure_ascii=False, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
