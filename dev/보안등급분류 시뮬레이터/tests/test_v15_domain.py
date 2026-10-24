"""Offline contract regressions using explicitly synthetic notice clauses."""
from copy import deepcopy
import json
import unittest

import v15_domain as d


def synthetic_notice(task=None):
    """Return a complete four-family snapshot; never an official catalogue."""
    snapshot = d.task_snapshot(task or {"과제명": "합성 과제", "현재 기술사양": "속도 20 GHz"})
    clauses = []
    sources = []
    for family in d.FAMILIES:
        source_id = "synthetic-" + family
        sources.append({"source_id": source_id, "families": [family], "title": "합성 기준",
                        "notice_number": "합성-1", "announcement_version": "시험",
                        "effective_date": "2026-01-01", "retrieved_at": "2026-01-01T00:00:00Z",
                        "official_url": "https://example.gov.test/source", "relative_path": family + ".txt",
                        "sha256": "0" * 64, "review_status": "reviewed", "coverage": "full",
                        "review_note": "합성 시험 전용"})
        clauses.append({"clause_id": family + ":1", "source_id": source_id, "family": family,
                        "code": "SYN-1", "title": "합성 속도 기준", "field": "합성",
                        "source_anchor": "합성 제1항", "text": "속도 10 GHz 이상", "qualifier_refs": [],
                        "condition": {"type": "numeric", "predicate_id": "speed", "text": "속도 10 GHz 이상",
                                      "source_anchor": "합성 제1항", "subject": "속도", "operator": "ge",
                                      "threshold": "10", "unit": "GHz"}})
    manifest = {"catalogue_schema_version": 1, "catalogue_id": "synthetic-only", "sources": sources,
                "files": [{"relative_path": source["relative_path"], "sha256": source["sha256"]} for source in sources],
                "clause_inventory": [{"clause_id": c["clause_id"], "family": c["family"], "sha256": d.canonical_hash(c)} for c in clauses]}
    fingerprint = d.canonical_hash(manifest)
    candidate = clauses[0]
    facts = [{"fact_id": "fact-1", "basis": "current", "subject": "속도", "value_text": "20 GHz",
              "number": "20", "unit": "GHz", "source_field": "현재 기술사양", "start": 0, "end": 9,
              "quote": snapshot["현재 기술사양"]}]
    facts[0]["end"] = len(facts[0]["quote"])
    comparison = {"comparison_id": d.comparison_id(fingerprint, candidate["clause_id"]),
                  "family": candidate["family"], "clause_id": candidate["clause_id"], "source_id": candidate["source_id"],
                  "current_assessment": "satisfied", "target_assessment": "not_provided",
                  "conditions": [{"predicate_id": "speed", "basis": basis, "condition_text": "속도 10 GHz 이상",
                                  "fact_ids": ["fact-1"] if basis == "current" else [],
                                  "normalized_value": "20" if basis == "current" else None,
                                  "normalized_unit": "GHz" if basis == "current" else None,
                                  "assessment": "satisfied" if basis == "current" else "insufficient_info",
                                  "reason": "합성 수치 대조" if basis == "current" else "목표 미제공",
                                  "source_anchor": "합성 제1항"} for basis in ("current", "target")],
                  "missing_information": [], "rationale": "합성 기준 충족", "affected_items": [2]}
    families = [{"family": family, "status": "complete", "screened_ids": [family + ":1"],
                 "excluded": [] if family == "advanced" else [{"clause_id": family + ":1", "reason": "합성 분야 무관"}],
                 "candidate_ids": [family + ":1"] if family == "advanced" else [], "errors": []} for family in d.FAMILIES]
    return {"catalogue_id": manifest["catalogue_id"], "catalogue_fingerprint": fingerprint,
            "catalogue_manifest": manifest, "sources": sources, "clause_snapshots": [candidate], "facts": facts,
            "families": families, "comparisons": [comparison], "status": "complete", "blocking_reasons": []}


def synthetic_result(method="impact", count=1):
    notice = synthetic_notice()
    task = {"과제명": "합성 과제", "현재 기술사양": "속도 20 GHz"}
    opts = d.normalize_options({"method": method, "num_reviewers": count,
                                "catalogue_fingerprint": notice["catalogue_fingerprint"]})
    result = d.make_result(task, opts, catalogue_manifest=notice["catalogue_manifest"])
    result["notice_review"] = notice
    result["candidate"] = {"is_candidate": True, "reason": "합성 검토 대상", "uncertainty": ""}
    for index, item in enumerate(result["criteria"]):
        item.update(level="해당" if index == 0 else "미해당" if index < 7 else "미검토",
                    note="합성 검토 근거", needs_expert_review=False)
        links = [{"comparison_id": entry["comparison_id"], "source_id": entry["source_id"]}
                 for entry in notice["comparisons"] if index + 1 in entry["affected_items"]]
        item["matched_reference"] = json.dumps(links) if links else ""
        if index == 7:
            item.update(note="부처 세부기준 미제공", law_refs=[])
    result["selected_items"] = [d.ITEM_NAMES[0]]
    result["weights"] = d.effective_weights(opts, [1])
    for index in range(count):
        reviewer = d.make_reviewer(f"reviewer-{index + 1}", d.PERSONAS[index])
        reviewer.update(status="완료", grade="민감과제", confidence="보통", rationale="합성 보호 필요성",
                        item_reviews=[{k: item[k] for k in ("item", "level", "note", "law_refs")} for item in result["criteria"]],
                        notice_comments=[{"comparison_id": notice["comparisons"][0]["comparison_id"], "comment": "합성 대조 검토"}])
        if method == "impact":
            reviewer.update(scores={d.ITEM_NAMES[0]: 4}, reviewer_score=4.0)
        result["reviewers"].append(reviewer)
    result.update(status="완료", overall_avg=4.0 if method == "impact" else None,
                  rule_grade="민감과제" if method == "impact" else None,
                  final_grade="민감과제", confidence="보통", rationale="합성 보호 필요성")
    return result, opts


class OptionsTests(unittest.TestCase):
    def test_auto_discards_invalid_stale_manual_values_before_parsing(self):
        raw = {"selection_mode": "auto", "selected_items": "old invalid selection", "weights": "not a map",
               "weight_tolerance": "not a number"}
        automatic = d.normalize_options(raw)
        self.assertEqual(automatic.selected_items, ())
        self.assertEqual(automatic.weights, ())
        self.assertEqual(automatic.weight_tolerance, 1e-6)
        self.assertEqual(d.options_fingerprint(raw), d.options_fingerprint())
        self.assertEqual(d.effective_weights(raw, [1, 3]), {d.ITEM_NAMES[0]: 1.0, d.ITEM_NAMES[2]: 1.0})
        frozen_stale = d.RunOptions(selected_items="invalid", weights="invalid", weight_tolerance="invalid")
        self.assertEqual(d.options_fingerprint(frozen_stale), d.options_fingerprint())

    def test_manual_and_checklist_have_distinct_weight_rules(self):
        manual = {"selection_mode": "manual", "selected_items": [1, 2], "weights": {1: .8, 2: 1.2}}
        self.assertEqual(d.effective_weights(manual, [1, 2]), {d.ITEM_NAMES[0]: .8, d.ITEM_NAMES[1]: 1.2})
        for change in ({"weights": {1: .79, 2: 1.21}}, {"weights": {1: 1.2, 2: 1.1}}, {"selected_items": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                d.normalize_options(manual | change)
        check = d.normalize_options(manual | {"method": "checklist", "weights": "invalid", "weight_tolerance": "invalid"})
        self.assertEqual(check.weights, ())
        self.assertEqual(check.selected_items, d.ITEM_NAMES[:2])
        self.assertEqual(d.effective_weights(check, [1, 2]), {})

    def test_standard_only_and_identity_separates_catalogue_and_target_facts(self):
        self.assertEqual(d.normalize_options().strictness, "표준")
        for value in ("엄격", "관대", None, "standard"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                d.normalize_options({"strictness": value})
        self.assertNotEqual(d.options_fingerprint(), d.options_fingerprint({"catalogue_fingerprint": "1" * 64}))
        task = {"과제명": "합성"}
        self.assertEqual(len(d.task_snapshot(task)), 9)
        for column in ("현재 기술사양", "개발목표 사양"):
            self.assertNotEqual(d.task_fingerprint(task), d.task_fingerprint(task | {column: "추가 사양"}))
        self.assertEqual(d.options_fingerprint(), d.options_fingerprint({"api_key": "synthetic-secret", "ui_theme": "changed"}))

    def test_v14_legal_rubric_and_score_boundaries_remain_identical(self):
        import v14_domain as previous
        self.assertEqual(d.CRITERIA, previous.CRITERIA)
        self.assertEqual(d.LEGAL_DEFINITIONS, previous.LEGAL_DEFINITIONS)
        score = d.calculate_reviewer_score({1: 5, 2: 4, 3: 3, 4: 3}, [1, 2, 3, 4],
                                           {1: 1.2, 2: 1.1, 3: .9, 4: .8})
        self.assertEqual(score, 3.875)
        for number, grade in ((3.499999, "일반과제"), (3.5, "민감과제"), (3.500001, "민감과제"),
                              (4.499999, "민감과제"), (4.5, "보안과제"), (4.500001, "보안과제")):
            self.assertEqual(d.rule_grade(number), grade)
        self.assertEqual(d.format_score(3.499999), "3.499999")
        for bad in (None, True, "NaN", float("inf"), 3.5, 0, 6):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                d.parse_score(bad)

    def test_manual_item_eight_requires_actual_row_or_common_policy(self):
        raw = {"selection_mode": "manual", "selected_items": [8]}
        with self.assertRaises(ValueError):
            d.normalize_options(raw)
        options = d.normalize_options(raw, allow_row_policy=True)
        with self.assertRaises(ValueError):
            d.make_result({"과제명": "합성"}, options)
        result = d.make_result({"과제명": "합성", "부처 세부기준": "합성 정책"}, options)
        self.assertEqual(result["criteria"][7]["level"], "판단곤란")
        auto = d.normalize_options({"selected_items": [8], "weights": {8: "invalid"}})
        self.assertEqual(auto.selected_items, ())


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.task = d.task_snapshot({"과제명": "합성 과제", "현재 기술사양": "속도 20 GHz"})
        self.notice = synthetic_notice(self.task)

    def test_historical_evidence_validates_without_current_catalogue_files(self):
        self.assertIs(d.validate_notice_review(self.notice, self.task), self.notice)
        result = d.make_result(self.task, catalogue_manifest=self.notice["catalogue_manifest"])
        result["notice_review"] = self.notice
        self.assertIs(d.validate_result(result), result)
        with self.assertRaises(ValueError):
            d.validate_result(result, catalogue_fingerprint="f" * 64)

    def test_fact_ranges_numbers_and_temporal_basis_are_not_trusted(self):
        mutations = [lambda n: n["facts"][0].update(start=-1),
                     lambda n: n["facts"][0].update(end=999),
                     lambda n: n["facts"][0].update(quote="속도 10 GHz"),
                     lambda n: n["facts"][0].update(number="10"),
                     lambda n: n["facts"][0].update(number="NaN"),
                     lambda n: n["facts"][0].update(basis="target")]
        for mutation in mutations:
            broken = deepcopy(self.notice)
            mutation(broken)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                d.validate_notice_review(broken, self.task)

    def test_numeric_fact_requires_an_associated_complete_unit_from_original_text(self):
        cases = (("20 nm", "20", "m"), ("20 m/s", "20", "m"),
                 ("20 nm, 80 m", "20", "m"), ("20 nm, 80 m", "80", "nm"),
                 ("120 m", "20", "m"), ("20 m/s", "20", "m", "20 m"),
                 ("20 m/s", "20", "m", "20 m", "20 m"),
                 ("20 m s^-1", "20", "m"), ("20 nm", "20", "n"),
                 ("20 m²", "20", "m"), ("20 m⁺¹", "20", "m"),
                 ("20 m×s", "20", "m"), ("20 m／s", "20", "m"),
                 ("20 m.s^-1", "20", "m"), ("20，000 m", "0", "m"),
                 ("−20 m", "20", "m"), ("20 m ²", "20", "m"),
                 ("20 m . s^-1", "20", "m"), ("20 m(s^-1)", "20", "m"))
        for case in cases:
            source, number, unit = case[:3]
            quote = case[4] if len(case) == 5 else source
            value_text = case[3] if len(case) >= 4 else source
            task = self.task | {"현재 기술사양": source}
            fact = self.notice["facts"][0] | {"number": number, "unit": unit, "quote": quote,
                                                "value_text": value_text, "start": 0, "end": len(quote)}
            with self.subTest(case=case), self.assertRaises(ValueError):
                d.validate_fact(fact, task)
        source = "120 m"
        cropped = self.notice["facts"][0] | {"number": "20", "unit": "m", "quote": "20 m",
                                               "value_text": "20 m", "start": 1, "end": len(source)}
        with self.assertRaises(ValueError):
            d.validate_fact(cropped, self.task | {"현재 기술사양": source})
        with self.assertRaises(ValueError):
            d.validate_fact(cropped | {"unit": None}, self.task | {"현재 기술사양": source})
        no_number = cropped | {"quote": "20 nm", "value_text": "20 nm", "start": 0,
                               "end": 5, "number": None, "unit": "m"}
        with self.assertRaises(ValueError):
            d.validate_fact(no_number, self.task | {"현재 기술사양": "20 nm"})

    def test_unassociated_pair_cannot_make_a_false_complete_notice(self):
        task = self.task | {"현재 기술사양": "20 nm"}
        notice = synthetic_notice(task)
        clause = notice["clause_snapshots"][0]
        clause["text"] = clause["condition"]["text"] = "속도 1 m 이상"
        clause["condition"].update(threshold="1", unit="m")
        manifest = notice["catalogue_manifest"]
        manifest["clause_inventory"][0]["sha256"] = d.canonical_hash(clause)
        notice["catalogue_fingerprint"] = d.canonical_hash(manifest)
        notice["facts"][0].update(quote="20 nm", value_text="20 nm", end=5, unit="m")
        comparison = notice["comparisons"][0]
        comparison["comparison_id"] = d.comparison_id(notice["catalogue_fingerprint"], "advanced:1")
        for condition in comparison["conditions"]:
            condition["condition_text"] = "속도 1 m 이상"
        comparison["conditions"][0]["normalized_unit"] = "m"
        with self.assertRaises(ValueError):
            d.validate_notice_review(notice, task)

    def test_measurement_pair_supports_attached_korean_counts_and_explicit_compound_units(self):
        cases = (("128단 이하의 메모리", "128", "단"), ("128층", "128", "층"),
                 ("에너지밀도 250 Wh/kg 이상", "250", "Wh/kg"),
                 ("용량 175 mAh/g", "175", "mAh/g"), ("에너지밀도 250 Wh / kg", "250", "Wh/kg"),
                 ("해상도 20µm", "20", "um"), ("시간 20μs", "20", "us"),
                 ("속도 20nm", "20", "nm"), ("길이 1,000 m", "1000", "m"),
                 ("−20 m", "-20", "m"), ("2e−2 m", "0.02", "m"))
        for source, number, unit in cases:
            task = self.task | {"현재 기술사양": source}
            fact = self.notice["facts"][0] | {"number": number, "unit": unit, "quote": source,
                                                "value_text": source, "start": 0, "end": len(source)}
            with self.subTest(source=source):
                d.validate_fact(fact, task)

    def test_bounds_and_ambiguous_measurements_are_not_turned_into_points(self):
        cases = (("20 m이하", "20", "ge", "20", "insufficient_info", "m"),
                 ("20 m이하", "20", "gt", "20", "not_satisfied", "m"),
                 ("20 m이하", "20", "le", "20", "satisfied", "m"),
                 ("20 m이하", "20", "eq", "20", "insufficient_info", "m"),
                 ("20 m미만", "20", "ge", "20", "not_satisfied", "m"),
                 ("20 m미만", "20", "eq", "20", "not_satisfied", "m"),
                 ("20 m이상", "20", "ge", "20", "satisfied", "m"),
                 ("20 m이상", "20", "gt", "20", "insufficient_info", "m"),
                 ("20 m이상", "20", "eq", "19", "not_satisfied", "m"),
                 ("20 m초과", "20", "gt", "20", "satisfied", "m"),
                 ("≤20 m", "20", "ge", "20", "insufficient_info", "m"),
                 (">20 m", "20", "le", "20", "not_satisfied", "m"),
                 ("최대 20 m", "20", "le", "20", "satisfied", "m"),
                 ("최소 20 m", "20", "lt", "20", "not_satisfied", "m"),
                 ("20 m까지", "20", "le", "20", "satisfied", "m"),
                 ("10~20 m", "20", "ge", "20", "insufficient_info", None),
                 ("±20 m", "20", "ge", "20", "insufficient_info", None),
                 ("약 20 m", "20", "ge", "20", "insufficient_info", None))
        predicate = self.notice["clause_snapshots"][0]["condition"] | {"unit": "m"}
        for source, number, operator, threshold, expected, unit in cases:
            task = self.task | {"현재 기술사양": source}
            fact = self.notice["facts"][0] | {"number": number, "unit": "m", "quote": source,
                                                "value_text": source, "start": 0, "end": len(source)}
            with self.subTest(source=source, operator=operator):
                d.validate_fact(fact, task)
                self.assertEqual(d.assess_numeric(predicate | {"operator": operator, "threshold": threshold}, [fact]),
                                 (expected, None, unit))

    def test_goal_bound_unit_conversion_and_negative_exact_numbers(self):
        predicate = self.notice["clause_snapshots"][0]["condition"]
        for source, number, original_unit, target_unit, operation, threshold, expected in (
                ("−20 m", "-20", "m", "m", "ge", "0", ("not_satisfied", "-20", "m")),
                ("2e−2 m", "0.02", "m", "m", "lt", "0.03", ("satisfied", "0.02", "m")),
                ("10nm이하", "10", "nm", "nm", "le", "16", ("satisfied", None, "nm")),
                ("10nm이하", "10", "nm", "um", "le", "0.016", ("satisfied", None, "um")),
                ("20 GHz 이상", "20", "GHz", "MHz", "ge", "20000", ("satisfied", None, "MHz"))):
            fact = self.notice["facts"][0] | {"basis": "target", "source_field": "개발목표 사양",
                "number": number, "unit": original_unit, "quote": source, "value_text": source, "start": 0, "end": len(source)}
            with self.subTest(source=source, unit=target_unit):
                d.validate_fact(fact, self.task | {"개발목표 사양": source})
                self.assertEqual(d.assess_numeric(predicate | {"unit": target_unit, "operator": operation, "threshold": threshold}, [fact]), expected)

    def test_cropped_quote_cannot_hide_bounds_uncertainty_or_range_operators(self):
        for source in ("약 20 m", "±20 m", "10~20 m", "≤20 m", "20 m이하", "20 m 이상"):
            start = source.index("20 m")
            fact = self.notice["facts"][0] | {"number": "20", "unit": "m", "quote": "20 m",
                                                "value_text": "20 m", "start": start, "end": start + 4}
            with self.subTest(source=source), self.assertRaises(ValueError):
                d.validate_fact(fact, self.task | {"현재 기술사양": source})

    def test_worded_ranges_and_unresolved_multiple_values_do_not_become_endpoints(self):
        sources = ("10 to 20 m", "10 through 20 m", "from 10 to 20 m", "between 10 and 20 m",
                   "10에서 20 m", "10 m부터 20 m", "10 m부터 20 m까지", "10 내지 20 m",
                   "10과 20 m 사이", "10 or 20 m", "10 또는 20 m")
        predicate = self.notice["clause_snapshots"][0]["condition"] | {"unit": "m", "operator": "ge", "threshold": "20"}
        for source in sources:
            fact = self.notice["facts"][0] | {"number": "20", "unit": "m", "quote": source,
                "value_text": source, "start": 0, "end": len(source)}
            with self.subTest(source=source):
                d.validate_fact(fact, self.task | {"현재 기술사양": source})
                self.assertEqual(d.assess_numeric(predicate, [fact]), ("insufficient_info", None, None))
                start = source.index("20 m")
                with self.assertRaises(ValueError):
                    d.validate_fact(fact | {"quote": "20 m", "value_text": "20 m", "start": start, "end": start + 4},
                                    self.task | {"현재 기술사양": source})

    def test_official_clause_without_a_control_code_keeps_an_explicit_empty_string(self):
        clause = deepcopy(self.notice["clause_snapshots"][0])
        clause["code"] = ""
        d.validate_clause(clause)
        for field in ("code", "title", "source_anchor"):
            broken = clause | {field: None}
            with self.subTest(field=field), self.assertRaises(ValueError):
                d.validate_clause(broken)
        with self.assertRaises(ValueError):
            d.validate_clause(clause | {"title": ""})

    def test_separate_list_measurements_keep_their_own_exact_pairs(self):
        source = "20 nm, 80 m"
        start = source.index("80 m")
        fact = self.notice["facts"][0] | {"number": "80", "unit": "m", "quote": "80 m",
            "value_text": "80 m", "start": start, "end": len(source)}
        d.validate_fact(fact, self.task | {"현재 기술사양": source})
        predicate = self.notice["clause_snapshots"][0]["condition"] | {"unit": "m", "operator": "ge", "threshold": "20"}
        self.assertEqual(d.assess_numeric(predicate, [fact]), ("satisfied", "80", "m"))

    def test_independent_source_properties_keep_their_own_exact_pairs(self):
        cases = (("Resolution 20 nm and power 80 W", "20 nm", "20", "nm"),
                 ("Resolution 20 nm and power 80 W", "80 W", "80", "W"),
                 ("해상도 20 nm이고 출력 80 W", "20 nm", "20", "nm"),
                 ("해상도 20 nm이고 출력 80 W", "80 W", "80", "W"),
                 ("Resolution 20 nm and travel distance 80 m", "20 nm", "20", "nm"),
                 ("Resolution 20 nm and travel distance 80 m", "80 m", "80", "m"),
                 ("해상도 20 nm이며 측정거리 80 m", "20 nm", "20", "nm"),
                 ("해상도 20 nm이며 측정거리 80 m", "80 m", "80", "m"),
                 ("Distance 80 m and duration 5 s", "80 m", "80", "m"),
                 ("Distance 80 m and duration 5 s", "5 s", "5", "s"),
                 ("거리 80 m이고 소요시간 5 s", "80 m", "80", "m"),
                 ("거리 80 m이고 소요시간 5 s", "5 s", "5", "s"))
        for source, quote, number, unit in cases:
            start = source.index(quote)
            # Extraction subjects need not reproduce a source label verbatim.
            fact = self.notice["facts"][0] | {"subject": "합성 측정속성", "number": number, "unit": unit,
                "quote": quote, "value_text": quote, "start": start, "end": start + len(quote)}
            predicate = self.notice["clause_snapshots"][0]["condition"] | {
                "subject": "합성 측정속성", "unit": unit, "operator": "eq", "threshold": number}
            with self.subTest(source=source, quote=quote):
                d.validate_fact(fact, self.task | {"현재 기술사양": source})
                self.assertEqual(d.assess_numeric(predicate, [fact]), ("satisfied", number, unit))

    def test_explicit_calendar_roles_do_not_become_measurement_endpoints(self):
        for source in ("In 2026 resolution is 20 nm.", "In 2031 resolution is 20 nm.",
                       "2027년 해상도는 20 nm이다.", "2042년에 측정한 해상도 20 nm"):
            start = source.index("20 nm")
            fact = self.notice["facts"][0] | {"number": "20", "unit": "nm", "quote": "20 nm",
                "value_text": "20 nm", "start": start, "end": start + 5}
            with self.subTest(source=source):
                d.validate_fact(fact, self.task | {"현재 기술사양": source})
                predicate = self.notice["clause_snapshots"][0]["condition"] | {"unit": "nm", "operator": "eq", "threshold": "20"}
                self.assertEqual(d.assess_numeric(predicate, [fact]), ("satisfied", "20", "nm"))

    def test_uncertainty_of_an_independent_property_does_not_modify_the_exact_one(self):
        for source in ("Resolution 20 nm and power about 80 W", "Resolution 20 nm and power ±80 W",
                       "해상도 20 nm이며 측정거리 약 80 m", "측정거리 약 80 m이며 해상도 20 nm",
                       "Distance 80 m during a measurement lasting about 5 s",
                       "Resolution 20 nm and power 10 to 80 W", "Power 10 to 80 W and resolution 20 nm",
                       "해상도 20 nm이며 측정거리 10 m부터 80 m까지",
                       "측정거리 10 m부터 80 m까지이며 해상도 20 nm"):
            quote, number, unit = ("80 m", "80", "m") if source.startswith("Distance") else ("20 nm", "20", "nm")
            start = source.index(quote)
            fact = self.notice["facts"][0] | {"number": number, "unit": unit, "quote": quote,
                "value_text": quote, "start": start, "end": start + len(quote)}
            predicate = self.notice["clause_snapshots"][0]["condition"] | {"unit": unit, "operator": "eq", "threshold": number}
            with self.subTest(source=source):
                d.validate_fact(fact, self.task | {"현재 기술사양": source})
                self.assertEqual(d.assess_numeric(predicate, [fact]), ("satisfied", number, unit))

    def test_same_quantity_ranges_and_unresolved_roles_stay_unknown(self):
        sources = ("Resolution 10 nm to 20 nm", "Resolution between 10 nm and 20 nm",
                   "Resolution 10 nm through 20 nm", "Resolution 10 nm to 20 m",
                   "해상도 10 nm에서 20 nm", "해상도 10 nm부터 20 nm까지",
                   "Resolution 10 nm and resolution 20 nm", "해상도 10 nm이며 해상도 20 nm",
                   "10 nm and 20 m", "10 nm or 20 nm", "10 nm at 20 nm",
                   "Resolution between 10 nm and power 20 nm")
        predicate = self.notice["clause_snapshots"][0]["condition"] | {"unit": "nm", "operator": "eq", "threshold": "20"}
        for source in sources:
            fact = self.notice["facts"][0] | {"number": "20", "unit": "m" if source.endswith("20 m") else "nm",
                "quote": source, "value_text": source, "start": 0, "end": len(source)}
            with self.subTest(source=source):
                d.validate_fact(fact, self.task | {"현재 기술사양": source})
                self.assertEqual(d.assess_numeric(predicate, [fact]), ("insufficient_info", None, None))
                quote = "20 " + fact["unit"]
                start = source.index(quote)
                with self.assertRaises(ValueError):
                    d.validate_fact(fact | {"quote": quote, "value_text": quote, "start": start, "end": start + len(quote)},
                                    self.task | {"현재 기술사양": source})

    def test_complete_notice_accepts_independent_source_structure_without_losing_range_checks(self):
        for source in ("Resolution 20 GHz and power 80 W", "In 2031 resolution is 20 GHz.",
                       "해상도 20 GHz이며 측정거리 약 80 m"):
            task = self.task | {"현재 기술사양": source}
            notice = synthetic_notice(task)
            start = source.index("20 GHz")
            notice["facts"][0].update(quote="20 GHz", value_text="20 GHz", start=start, end=start + 6)
            with self.subTest(source=source):
                d.validate_notice_review(notice, task)

    def test_signed_and_bounded_facts_are_rechecked_when_validating_complete_notice(self):
        for source, threshold in (("−20 m", "0"), ("20 m ²", "1"), ("20 m . s^-1", "1"),
                                  ("20 m(s^-1)", "1"), ("20 m이하", "20"), ("±20 m", "20"),
                                  ("10 to 20 m", "20"), ("10에서 20 m", "20"), ("10 m부터 20 m", "20")):
            task = self.task | {"현재 기술사양": source}
            notice = synthetic_notice(task)
            clause = notice["clause_snapshots"][0]
            clause["text"] = clause["condition"]["text"] = "합성 길이 기준"
            clause["condition"].update(threshold=threshold, unit="m")
            notice["catalogue_manifest"]["clause_inventory"][0]["sha256"] = d.canonical_hash(clause)
            notice["catalogue_fingerprint"] = d.canonical_hash(notice["catalogue_manifest"])
            notice["facts"][0].update(quote=source, value_text=source, end=len(source), unit="m")
            comparison = notice["comparisons"][0]
            comparison["comparison_id"] = d.comparison_id(notice["catalogue_fingerprint"], "advanced:1")
            for condition in comparison["conditions"]:
                condition["condition_text"] = "합성 길이 기준"
            comparison["conditions"][0]["normalized_unit"] = "m"
            with self.subTest(source=source), self.assertRaises(ValueError):
                d.validate_notice_review(notice, task)
            if "10" in source:
                start = source.index("20 m")
                notice["facts"][0].update(quote="20 m", value_text="20 m", start=start, end=start + 4)
                with self.subTest(source=source, cropped=True), self.assertRaises(ValueError):
                    d.validate_notice_review(notice, task)

    def test_assessment_recomputed_from_si_values_and_qualifier_ast(self):
        self.assertEqual(d.normalize_measurement("20000", "MHz", "GHz"), "20")
        self.assertEqual(d.normalize_measurement("123.45", "Wh/kg", "Wh/kg"), "123.45")
        self.assertEqual(d.normalize_measurement("250", "mAh/g", "mAh/g"), "250")
        self.assertEqual(d.normalize_measurement("123456789012345678901234567890", "Hz", "Hz"), "123456789012345678901234567890")
        self.assertIsNone(d.normalize_measurement("20", "GHz", "nm"))
        bad = deepcopy(self.notice)
        bad["comparisons"][0]["current_assessment"] = "not_satisfied"
        with self.assertRaises(ValueError):
            d.validate_notice_review(bad, self.task)
        bad = deepcopy(self.notice)
        bad["comparisons"][0]["conditions"][0]["normalized_value"] = "200"
        with self.assertRaises(ValueError):
            d.validate_notice_review(bad, self.task)
        tree = {"type": "all", "children": [{"type": "qualitative", "predicate_id": "a"},
                                               {"type": "qualitative", "predicate_id": "b"}]}
        self.assertEqual(d.evaluate_condition(tree, {"a": "satisfied", "b": "insufficient_info"}), "insufficient_info")
        self.assertEqual(d.evaluate_condition(tree, {"a": "not_satisfied", "b": "insufficient_info"}), "not_satisfied")
        self.assertEqual(d.evaluate_condition({"type": "not", "child": tree}, {"a": "not_satisfied", "b": "satisfied"}), "satisfied")

    def test_inventory_coverage_snapshot_hash_and_reference_sets_are_enforced(self):
        mutations = [lambda n: n["families"][0]["screened_ids"].clear(),
                     lambda n: n["families"][0]["candidate_ids"].append("core:1"),
                     lambda n: n["clause_snapshots"][0].update(text="changed"),
                     lambda n: n["comparisons"][0].update(comparison_id="forged"),
                     lambda n: n["comparisons"][0].update(affected_items=[2, 2]),
                     lambda n: n["comparisons"][0]["conditions"].append(deepcopy(n["comparisons"][0]["conditions"][0]))]
        for mutation in mutations:
            bad = deepcopy(self.notice)
            mutation(bad)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                d.validate_notice_review(bad, self.task)

    def test_missing_qualifier_snapshot_and_wrong_family_are_rejected(self):
        bad = deepcopy(self.notice)
        clause = bad["clause_snapshots"][0]
        clause["qualifier_refs"] = ["core:1"]
        bad["catalogue_manifest"]["clause_inventory"][0]["sha256"] = d.canonical_hash(clause)
        bad["catalogue_fingerprint"] = d.canonical_hash(bad["catalogue_manifest"])
        bad["comparisons"][0]["comparison_id"] = d.comparison_id(bad["catalogue_fingerprint"], clause["clause_id"])
        with self.assertRaises(ValueError):
            d.validate_notice_review(bad, self.task)

    def test_root_status_cannot_hide_notice_failure_or_invent_checklist_scores(self):
        result = d.make_result(self.task, {"method": "checklist"}, catalogue_manifest=self.notice["catalogue_manifest"])
        result["notice_review"] = self.notice
        result["weights"] = {d.ITEM_NAMES[0]: 1.0}
        with self.assertRaises(ValueError):
            d.validate_result(result)
        result["weights"] = {}
        result["final_grade"] = "일반과제"
        with self.assertRaises(ValueError):
            d.validate_result(result)
        result["final_grade"] = None
        result["notice_review"] = deepcopy(self.notice)
        result["notice_review"].update(status="error", blocking_reasons=["합성 대조 오류"])
        with self.assertRaises(ValueError):
            d.validate_result(result)
        result["status"] = "오류"
        d.validate_result(result)

    def test_numeric_boundaries_and_unknown_exceptions_are_not_boolean_coerced(self):
        predicate = self.notice["clause_snapshots"][0]["condition"]
        for operator, expected in (("lt", "not_satisfied"), ("le", "satisfied"), ("eq", "satisfied"),
                                   ("ge", "satisfied"), ("gt", "not_satisfied")):
            actual = d.assess_numeric(predicate | {"operator": operator, "threshold": "20"}, self.notice["facts"])
            self.assertEqual(actual, (expected, "20", "GHz"))
        exclusion = {"type": "all", "children": [predicate,
                     {"type": "not", "child": {"type": "qualitative", "predicate_id": "exception"}}]}
        self.assertEqual(d.evaluate_condition(exclusion, {"speed": "satisfied", "exception": "insufficient_info"}), "insufficient_info")

    def test_target_omission_is_allowed_only_when_no_target_facts_exist(self):
        notice = deepcopy(self.notice)
        notice["comparisons"][0]["conditions"] = notice["comparisons"][0]["conditions"][:1]
        d.validate_notice_review(notice, self.task)
        target_task = self.task | {"개발목표 사양": "속도 30 GHz"}
        notice["facts"].append(notice["facts"][0] | {"fact_id": "target-1", "basis": "target",
            "source_field": "개발목표 사양", "quote": "속도 30 GHz", "value_text": "30 GHz", "number": "30"})
        with self.assertRaises(ValueError):
            d.validate_notice_review(notice, target_task)

    def test_explicit_target_text_cannot_be_hidden_by_omitting_extracted_facts(self):
        with self.assertRaises(ValueError):
            d.validate_notice_review(self.notice, self.task | {"개발목표 사양": "속도 30 GHz"})

    def test_saved_source_review_and_full_family_inventory_are_required(self):
        for mutate in (lambda m: m["sources"][0].update(review_status="pending"),
                       lambda m: m["sources"][0].update(coverage="partial"),
                       lambda m: m["clause_inventory"].pop()):
            notice = deepcopy(self.notice)
            mutate(notice["catalogue_manifest"])
            notice["sources"] = deepcopy(notice["catalogue_manifest"]["sources"])
            notice["catalogue_fingerprint"] = d.canonical_hash(notice["catalogue_manifest"])
            notice["comparisons"][0]["comparison_id"] = d.comparison_id(notice["catalogue_fingerprint"], "advanced:1")
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                d.validate_notice_review(notice, self.task)

    def test_partial_coverage_is_preserved_without_a_false_complete_status(self):
        notice = deepcopy(self.notice)
        family = notice["families"][1]
        family.update(status="partial", screened_ids=[], excluded=[], candidate_ids=[])
        notice.update(status="needs_info", blocking_reasons=["합성 미완료 범위"])
        d.validate_notice_review(notice, self.task)
        notice["status"] = "complete"
        with self.assertRaises(ValueError):
            d.validate_notice_review(notice, self.task)


class ResultTests(unittest.TestCase):
    def test_optional_policy_link_exception_is_only_the_actual_unprovided_policy_shape(self):
        from classification_v15 import classify_task
        from test_v15_engine import Client, TASK
        from test_v15_notice_review import catalogue

        def policy_relation(data, out):
            if data.get("phase") == "compare":
                out["affected_items"] = [2, 8]
            return out
        for policy in ({}, {"ministry_policy": "실제 공통 정책"}):
            client = Client(candidates=("advanced:1",), transform=policy_relation)
            result = classify_task(TASK, {"num_reviewers": 1} | policy, client, catalogue=catalogue())
            self.assertEqual(result["status"], "완료")
            self.assertEqual(result["notice_review"]["comparisons"][0]["affected_items"], [2, 8])
            self.assertIs(d.validate_result(result), result)
            if not policy:
                self.assertEqual(result["criteria"][7]["matched_reference"], "")
                self.assertEqual(result["criteria"][7]["note"], "부처 세부기준 미제공")
                for change in ({"note": "일반 미검토"}, {"needs_expert_review": True},
                               {"law_refs": list(d.CRITERIA[7]["security_refs"])}):
                    changed = deepcopy(result)
                    changed.update(status="검토필요", final_grade=None)
                    changed["criteria"][7].update(change)
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        d.validate_result(changed)
            else:
                self.assertTrue(result["criteria"][7]["matched_reference"])
                changed = deepcopy(result)
                changed.update(status="검토필요", final_grade=None)
                changed["criteria"][7].update(level="미검토", matched_reference="")
                with self.assertRaises(ValueError):
                    d.validate_result(changed)

    def test_actual_engine_preserves_notice_before_and_after_criteria_failures(self):
        from classification_v15 import classify_task
        from test_v15_engine import Client, TASK
        from test_v15_notice_review import catalogue

        for policy in ({}, {"ministry_policy": "공통 정책"}):
            for stage in ("candidate", "criteria", "reviewer", "summary"):
                def fail_stage(data, out):
                    return {} if data.get("stage") == stage else out
                with self.subTest(policy=policy, stage=stage):
                    result = classify_task(TASK, {"num_reviewers": 1} | policy,
                        Client(candidates=("advanced:1",), transform=fail_stage), catalogue=catalogue())
                    self.assertEqual(result["status"], "오류")
                    self.assertEqual(len(result["notice_review"]["comparisons"]), 1)
                    self.assertIs(d.validate_result(result), result)
                    if stage in ("candidate", "criteria"):
                        self.assertTrue(all(not item["matched_reference"] for item in result["criteria"]))
                        self.assertEqual(result["criteria"][7]["level"], "판단곤란" if policy else "미검토")
                    else:
                        self.assertTrue(result["criteria"][1]["matched_reference"])
                    changed = deepcopy(result)
                    changed["criteria"][0]["matched_reference"] = '[{"comparison_id":"unknown","source_id":"unknown"}]'
                    with self.assertRaises(ValueError):
                        d.validate_result(changed)

    def test_candidate_terminal_placeholders_and_optional_policy_remain_valid(self):
        from classification_v15 import classify_task
        from test_v15_engine import Client, TASK
        from test_v15_notice_review import catalogue, fact

        for value, status in (("5", "후보제외"), ("20", "검토필요")):
            text = "속도 " + value + " GHz"
            result = classify_task(TASK | {"현재 기술사양": text}, {"num_reviewers": 1},
                Client(candidates=("advanced:1",), candidate=False, facts=[fact(text, number=value)]),
                catalogue=catalogue())
            self.assertEqual(result["status"], status)
            self.assertTrue(all(item["level"] == "미검토" and not item["matched_reference"] for item in result["criteria"]))
            self.assertIs(d.validate_result(result), result)
        for policy in ({}, {"ministry_policy": "공통 정책"}):
            result = d.make_result(TASK, {"selection_mode": "manual", "selected_items": [1], "weights": {1: 1.0}} | policy,
                                   catalogue_manifest=synthetic_notice()["catalogue_manifest"])
            result["notice_review"] = synthetic_notice(TASK)
            self.assertIs(d.validate_result(result), result)
        completed, _ = synthetic_result()
        self.assertEqual(completed["criteria"][7]["level"], "미검토")
        self.assertEqual(completed["criteria"][7]["matched_reference"], "")
        completed["criteria"][0]["matched_reference"] = "고시 외 구체적 검토 근거"
        self.assertIs(d.validate_result(completed), completed)

    def test_model_and_saved_boundary_both_reject_duplicate_json_link_keys(self):
        from classification_v15 import classify_task
        from test_v15_engine import Client, TASK
        from test_v15_notice_review import catalogue

        def duplicate_key(data, out):
            if data.get("stage") == "criteria":
                link = json.loads(out["criteria"][1]["matched_reference"])[0]
                out["criteria"][1]["matched_reference"] = '[{"source_id":"unknown","source_id":' + json.dumps(link["source_id"]) + ',"comparison_id":' + json.dumps(link["comparison_id"]) + '}]'
            return out
        result = classify_task(TASK, {"num_reviewers": 1},
            Client(candidates=("advanced:1",), transform=duplicate_key), catalogue=catalogue())
        self.assertEqual(result["status"], "오류")
        self.assertEqual(len(result["notice_review"]["comparisons"]), 1)
        self.assertFalse(result["reviewers"])
        self.assertIs(d.validate_result(result), result)

    def test_saved_engine_criteria_require_exact_source_links_in_every_status(self):
        from classification_v15 import classify_task
        from test_v15_engine import Client, TASK
        from test_v15_notice_review import catalogue

        original = classify_task(TASK, {"num_reviewers": 1},
            Client(candidates=("advanced:1",)), catalogue=catalogue())
        self.assertEqual(original["status"], "완료")
        criterion_index = next(index for index, item in enumerate(original["criteria"])
                               if item["matched_reference"])
        links = json.loads(original["criteria"][criterion_index]["matched_reference"])
        link = links[0]
        mutations = {
            "missing": "",
            "empty_list": "[]",
            "unknown": json.dumps([link | {"comparison_id": "unknown"}]),
            "wrong_source": json.dumps([link | {"source_id": "unknown"}]),
            "duplicate": json.dumps([link, link]),
            "extra_key": json.dumps([link | {"extra": "unknown"}]),
            "invalid_json": "[broken",
            "object_not_list": json.dumps(link),
            "prose_for_linked_item": "별도 고시 근거",
            "duplicate_json_key": '[{"comparison_id":"unknown","comparison_id":'
                + json.dumps(link["comparison_id"]) + ',"source_id":'
                + json.dumps(link["source_id"]) + '}]',
        }
        for status in ("완료", "검토필요", "오류"):
            for name, value in mutations.items():
                changed = deepcopy(original)
                changed["criteria"][criterion_index]["matched_reference"] = value
                if status != "완료":
                    changed.update(status=status, final_grade=None, unresolved_reasons=["종합 검토 미완료"])
                with self.subTest(status=status, mutation=name), self.assertRaises(ValueError):
                    d.validate_result(changed)
            changed = deepcopy(original)
            unrelated = next(index for index in range(7) if index != criterion_index)
            changed["criteria"][unrelated]["matched_reference"] = json.dumps(links)
            if status != "완료":
                changed.update(status=status, final_grade=None, unresolved_reasons=["종합 검토 미완료"])
            with self.subTest(status=status, mutation="another_criterion"), self.assertRaises(ValueError):
                d.validate_result(changed)

    def test_complete_one_and_three_agent_contracts_for_each_method(self):
        for method in ("impact", "checklist"):
            for count in (1, 3):
                with self.subTest(method=method, count=count):
                    result, opts = synthetic_result(method, count)
                    d.validate_result(result, opts)
                    d.validate_result(result)

    def test_complete_reviewer_score_and_comments_checked_even_before_summary(self):
        for mutation in (lambda r: r["reviewers"][0]["notice_comments"].clear(),
                         lambda r: r["reviewers"][0].update(reviewer_score=5.0),
                         lambda r: r["reviewers"][0].update(scores={}),
                         lambda r: r["reviewers"][0].update(grade=None)):
            result, _ = synthetic_result()
            result.update(status="검토필요", final_grade=None, unresolved_reasons=["종합 의견 미완료"])
            mutation(result)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                d.validate_result(result)

    def test_incomplete_agents_never_form_normal_averages(self):
        result, _ = synthetic_result(count=3)
        result.update(status="검토필요", final_grade=None, unresolved_reasons=["합성 누락"])
        result["reviewers"][2].update(status="검토필요", grade=None, unresolved_reasons=["합성 누락"])
        with self.assertRaises(ValueError):
            d.validate_result(result)

    def test_invalid_schema_nonfinite_unknown_keys_and_reviewer_identity_rejected(self):
        mutations = (lambda r: r.update(schema_version=1), lambda r: r.update(overall_avg=float("nan")),
                     lambda r: r.update(extra="unknown"), lambda r: r["reviewers"][0].update(persona="사람 위원"),
                     lambda r: r["reviewers"][0]["notice_comments"][0].update(comparison_id="unknown"))
        for mutation in mutations:
            result, _ = synthetic_result()
            mutation(result)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                d.validate_result(result)

    def test_completed_unknown_criterion_or_unexplained_grade_difference_is_rejected(self):
        for mutation in (lambda r: r["criteria"][1].update(level="판단곤란"),
                         lambda r: r["reviewers"][0]["item_reviews"][1].update(level="판단곤란"),
                         lambda r: r.update(final_grade="보안과제")):
            result, _ = synthetic_result()
            mutation(result)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                d.validate_result(result)
        result, _ = synthetic_result()
        result.update(final_grade="보안과제", confidence="낮음", rationale="제21조제4항에 따른 합성 보호 필요성",
                      discussion_points="합성 법적 사유와 수치 구간 불일치 논의")
        d.validate_result(result)

    def test_malformed_json_shapes_fail_with_safe_value_error(self):
        for mutation in (lambda r: r["notice_review"]["facts"][0].update(source_field=[]),
                         lambda r: r["notice_review"]["families"][0].update(family=[]),
                         lambda r: r["notice_review"]["comparisons"][0].update(clause_id=[])):
            result, _ = synthetic_result()
            mutation(result)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                d.validate_result(result)

    def test_zero_actual_items_cannot_complete_checklist_and_changed_catalogue_cannot_resume(self):
        result, opts = synthetic_result("checklist")
        result["selected_items"] = []
        with self.assertRaises(ValueError):
            d.validate_result(result)
        result, opts = synthetic_result()
        with self.assertRaises(ValueError):
            d.validate_result(result, opts.to_dict() | {"catalogue_fingerprint": "f" * 64})
        d.validate_result(result, opts, catalogue_fingerprint=result["catalogue_fingerprint"])


if __name__ == "__main__":
    unittest.main()
