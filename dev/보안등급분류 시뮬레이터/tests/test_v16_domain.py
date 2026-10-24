"""Offline v16 contract regressions using explicitly synthetic notice clauses."""
from copy import deepcopy
import json
import unittest

import v16_domain as d


# One synthetic source per family; each notice has exactly one '-body' source.
SYNTHETIC_NOTICES = {
    "advanced": ("synthetic-advanced-body", "산업통상자원부고시 제2025-71호", "2025-05-12", "2025-05-18"),
    "core": ("synthetic-core-body", "산업통상부고시 제2025-2호", "2025-10-02", "2025-10-02"),
    "dual_use": ("synthetic-strategic-body", "산업통상부고시 제2026-101호", "2026-08-31", "2026-09-01"),
    "military": ("synthetic-military-annex", "산업통상부고시 제2026-101호", "2026-08-31", "2026-09-01"),
}


def synthetic_notice(task=None):
    """Return a complete four-family snapshot; never an official catalogue."""
    snapshot = d.task_snapshot(task or {"과제명": "합성 과제", "현재 기술사양": "속도 20 GHz"})
    clauses = []
    sources = []
    for family in d.FAMILIES:
        source_id, number, announced, effective = SYNTHETIC_NOTICES[family]
        sources.append({"source_id": source_id, "families": [family], "title": "합성 기준",
                        "notice_number": number, "announcement_version": "시험",
                        "announcement_date": announced,
                        "effective_date": effective, "retrieved_at": "2026-01-01T00:00:00Z",
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


# Spec 5 input rows (synthetic text only).
CLEANING_ROWS = (
    ("줄1_x000D_\n줄2", "줄1\n줄2"),
    ("20_x000D_30", "20\n30"),
    ("_x00_x000D_0D_", "_x00\n0D_"),
    ("_x005F_x000D_", "_x005F_x000D_"),
    ("a_x000D_x005F_x000D_b", "a\nx005F\nb"),
    ("a  \t\n\n\n\nb", "a\n\nb"),
    ("첫 줄\n  들여쓴 줄\n끝 줄", "첫 줄\n  들여쓴 줄\n끝 줄"),
)
CLEANING_EXTRA = (
    ("줄1_x000A_줄2_x0009_칸", "줄1\n줄2\t칸"),
    ("_X000d_가_x000a_나_X0009_다", "가\n나\t다"),
    ("_x005f_X000A_ 그대로", "_x005f_X000A_ 그대로"),
    ("_x0020_ 다른 표시_x00E9_", "_x0020_ 다른 표시_x00E9_"),
    ("가\r\n나\r다\n\r라", "가\n나\n다\n\n라"),
    ("가 _x000D_\n _x0009_\n\n나", "가\n\n나"),
    ("  앞뒤  ", "앞뒤"),
    ("_x000D_", ""),
    ("", ""),
)
CLEANING_FRAGMENTS = ("_x000D_", "_x005F", "_x000A_", "_x0009_", "_x00", "0D_", "\r", "\n", " ", "\t", "a", "가", "_")


class InputCleaningTests(unittest.TestCase):
    def test_spec_rows_and_marker_rules(self):
        for raw, expected in CLEANING_ROWS + CLEANING_EXTRA:
            with self.subTest(raw=raw):
                self.assertEqual(d.clean_input_text(raw), expected)
                self.assertEqual(d.clean_input_text(expected), expected)

    def test_idempotent_on_fixed_and_random_fragment_strings(self):
        import random
        fixed = [raw for raw, _ in CLEANING_ROWS + CLEANING_EXTRA] + [
            "_x005F_x005F_x000D_", "_x000D_x000D_", "_x000D_x0009__", "_x00_x000A_0A_", "_x005F_x000D__x000D_",
            "a\t_x000D_\t\r\n b", "\n\n\n_x0009_\n\n\n", "_x000D_x005F_x000A_x005F_x0009_",
        ]
        rng = random.Random(20261024)
        generated = ["".join(rng.choice(CLEANING_FRAGMENTS) for _ in range(rng.randint(0, 24)))
                     for _ in range(5000)]
        for raw in fixed + generated:
            once = d.clean_input_text(raw)
            twice = d.clean_input_text(once)
            if once != twice:
                self.fail(f"not idempotent: {raw!r} -> {once!r} -> {twice!r}")
            self.assertNotIn("\r", once)
            self.assertNotIn("\n\n\n", once)
            self.assertEqual(once, once.strip())

    def test_other_control_characters_in_the_middle_are_preserved(self):
        for char in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", " ", " "):
            with self.subTest(char=repr(char)):
                self.assertEqual(d.clean_input_text("가" + char + "나"), "가" + char + "나")
                # Only space and tab are removed at a line end; the line split is LF only.
                self.assertEqual(d.clean_input_text("가" + char + " \t\n나"), "가" + char + "\n나")
                self.assertEqual(d.clean_input_text("가\n" + char + "나"), "가\n" + char + "나")
                # At either end str.strip() still removes it, exactly as before.
                self.assertEqual(d.clean_input_text(char + "가" + char), "가")

    def test_task_snapshot_cleans_all_nine_columns(self):
        columns = d.TASK_COLUMNS + d.OPTIONAL_TASK_COLUMNS
        self.assertEqual(len(columns), 9)
        dirty = {column: f" {column}_x000D_\n둘째 줄 \t_x000D_\n\n\n셋째 " for column in columns}
        snapshot = d.task_snapshot(dirty)
        # "_x000D_\n" is one CRLF, so it becomes a single line break.
        self.assertEqual(snapshot, {column: f"{column}\n둘째 줄\n\n셋째" for column in columns})
        self.assertEqual(snapshot, d.task_snapshot(snapshot))
        self.assertEqual(d.task_fingerprint(dirty), d.task_fingerprint(snapshot))
        self.assertEqual(d.task_snapshot({"과제명": 20, "연구내용": None})["과제명"], "20")
        for name in ("_x000D_", "_x000D__x000A_ \t_x0009_", "\r\n"):
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                d.task_snapshot({"과제명": name, "연구내용": "합성 내용"})
            self.assertEqual(str(caught.exception), "과제명은 필수입니다.")

    def test_cleaned_result_snapshot_passes_validation(self):
        manifest = synthetic_notice()["catalogue_manifest"]
        dirty = {"과제명": "합성_x000D_\n과제", "현재 기술사양": "속도 20 GHz_x000D_",
                 "연구내용": "_x005F_x000D_ 글자 그대로\r\n  들여쓴 줄"}
        result = d.make_result(dirty, catalogue_manifest=manifest)
        self.assertEqual(result["task_snapshot"]["과제명"], "합성\n과제")
        self.assertEqual(result["task_snapshot"]["연구내용"], "_x005F_x000D_ 글자 그대로\n  들여쓴 줄")
        self.assertEqual(result["task_name"], "합성\n과제")
        self.assertEqual(result["task_fingerprint"], d.task_fingerprint(result["task_snapshot"]))
        d.validate_result(result)
        d.validate_result(result, task=dirty)

    def test_normalize_options_cleans_common_policy_and_fingerprint_uses_cleaned_text(self):
        raw = {"ministry_policy": "  공통_x000D_\n정책 \t\n\n\n\n끝_x000A_"}
        options = d.normalize_options(raw)
        self.assertEqual(options.ministry_policy, "공통\n정책\n\n끝")
        self.assertEqual(d.options_fingerprint(raw), d.options_fingerprint({"ministry_policy": "공통\n정책\n\n끝"}))
        self.assertEqual(d.normalize_options(options), options)
        empty = d.normalize_options({"ministry_policy": "_x000D_\r\n_x0009_"})
        self.assertEqual(empty.ministry_policy, "")
        self.assertEqual(d.options_fingerprint({"ministry_policy": "_x000D_"}), d.options_fingerprint())
        manual = {"selection_mode": "manual", "selected_items": [8]}
        for policy in ("_x000D_", "_x000A__x0009_ "):
            with self.subTest(policy=policy):
                with self.assertRaises(ValueError):
                    d.normalize_options(manual | {"ministry_policy": policy})
                with self.assertRaises(ValueError):
                    d.normalize_options(manual, ministry_policy_context=policy)
        self.assertEqual(d.normalize_options(manual, ministry_policy_context="정책_x000D_").selected_items,
                         (d.ITEM_NAMES[7],))
        with self.assertRaises(ValueError):
            d.make_result({"과제명": "합성", "부처 세부기준": "_x000D_"}, d.normalize_options(manual, allow_row_policy=True))

    def test_clean_inputs_keep_v15_snapshot_and_fingerprints(self):
        import v15_domain as previous
        tasks = [
            {"과제명": "합성 과제"},
            {"과제명": " 합성 과제 \n", "연구목표": "  첫 줄\n  둘째 줄\n\n셋째", "부처 세부기준": "정책",
             "현재 기술사양": "속도 20 GHz", "개발목표 사양": "속도 30 GHz", "세부사업명": "합성 사업"},
            {"과제명": "_x005F_x000D_ 글자 그대로", "연구내용": "가\t나\n다"},
        ]
        for task in tasks:
            with self.subTest(task=task):
                self.assertEqual(d.task_snapshot(task), previous.task_snapshot(task))
                self.assertEqual(d.task_fingerprint(task), previous.task_fingerprint(task))
        for options in ({}, {"ministry_policy": " 공통 정책 "}, {"ministry_policy": "첫 줄\n  둘째 줄"},
                        {"method": "checklist", "selection_mode": "manual", "selected_items": [1, 8],
                         "ministry_policy": "정책"}):
            with self.subTest(options=options):
                self.assertEqual(d.options_fingerprint(options), previous.options_fingerprint(options))
                self.assertEqual(d.normalize_options(options).to_dict(), previous.normalize_options(options).to_dict())


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
        from classification_v16 import classify_task
        from test_v16_engine import Client, TASK
        from test_v16_notice_review import catalogue

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
        from classification_v16 import classify_task
        from test_v16_engine import Client, TASK
        from test_v16_notice_review import catalogue

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
        from classification_v16 import classify_task
        from test_v16_engine import Client, TASK
        from test_v16_notice_review import catalogue, fact

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
        from classification_v16 import classify_task
        from test_v16_engine import Client, TASK
        from test_v16_notice_review import catalogue

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
        from classification_v16 import classify_task
        from test_v16_engine import Client, TASK
        from test_v16_notice_review import catalogue

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


# Spec 부록 A, copied into this test source character for character.
APPENDIX_A_DEFINITIONS = [
    {"heading": "법 제21조제4항(보안과제)",
     "text": "④ 중앙행정기관의 장은 외부로 유출될 경우 기술적･재산적 가치에 상당한 손실이 예상되거나 국가안보를 위하여 별도로 높은 수준의 보안이 필요하다고 인정하는 연구개발과제를 보안과제로 분류할 수 있다."},
    {"heading": "법 제21조제5항(민감과제)",
     "text": "⑤ 중앙행정기관의 장은 제4항의 보안과제로 분류하지 아니하였으나 유출 시 국가에 미치는 영향을 고려하여 추가적인 관리가 필요하다고 인정하는 연구개발과제를 민감과제로 분류할 수 있다."},
    {"heading": "시행령 제45조제1항(보안과제 분류 기준)",
     "text": "\n".join((
         "① 중앙행정기관의 장은 법제21조제4항에 따라 다음 각 호의 연구개발과제를 보안과제로 분류할 수 있다.",
         "1. 「방위사업법」 제3조제1호에 따른 방위력개선사업과 관련된 연구개발과제",
         "2. 다음 각 목의 어느 하나에 해당하는 기술과 관련된 연구개발과제",
         "가. 외국에서 기술이전을 거부하여 국산화를 추진 중인 기술",
         "나. 중앙행정기관의 장이 보호의 필요성이 있다고 인정하는 미래핵심기술",
         "다. 「산업기술의 유출방지 및 보호에 관한 법률」 제2조제2호에 따른 국가핵심기술",
         "라. 「대외무역법」 제19조에 따른 수출허가 등 제한이 필요한 기술",
         "3. 그 밖에 중앙행정기관의 장이 보안과제로 분류할 필요가 있다고 인정하는 연구개발과제"))},
    {"heading": "시행령 제45조제2항(민감과제 분류 기준)",
     "text": "\n".join((
         "② 중앙행정기관의 장은 법 제21조제5항에 따라 보안과제로 분류하지 않는 연구개발과제 중에서 다음 각 호의 사항을 종합적으로 고려하여 추가적인 관리가 필요하다고 인정하는 연구개발과제를 민감과제로 분류할 수 있다.",
         "1. 국가안보･외교 등을 위한 전략적 필요성",
         "2. 기술적･재산적 가치",
         "3. 그 밖에 연구개발과제의 수행 과정 및 결과의 유출 시 국가 전체에 미치는 영향의 정도"))},
    {"heading": "일반과제(가이드라인)",
     "text": "보안과제 또는 민감과제에 해당하지 않으며, 통상적인 연구관리 및 기본 보안관리 조치 하에서 수행 가능한 연구개발과제"},
]
APPENDIX_A_PRINCIPLES = [
    {"title": "국가 차원의 보호 필요성에 비례한 종합적 판단",
     "details": ["보안등급 분류는 ‘참여자･특정주제･기술수준’ 등 단일 요건이 아닌 연구성과 유출 시 국가에 미치는 영향 수준을 종합적으로 고려",
                 "국가안보를 위해 법령에 따라 지정된 보안과제를 최우선 식별･분류하되 그 외 중앙행정기관의 기술보호･육성 지정 법령 준수"]},
    {"title": "협력적･전문적 의사결정",
     "details": ["보안등급 분류는 다양한 이해관계자의 전문성을 기반으로 한 집단적 의사결정 체계를 기반으로 실시",
                 "보안등급분류위원회의 심의･의결을 통해 투명성･객관성･책임성 확보",
                 "전문 기술판정 필요 시 관계 기관에 문의",
                 "※ 예시: 전략물자(무역안보관리원･한국원자력통제기술원･방위사업청),국가핵심기술 및 첨단전략기술(산업기술기획평가원 기술안보센터)",
                 "연구개발기관이 보안등급 의견을 제시하도록 하여 현장 전문성 반영(붙임2 자가점검서 양식 참고)",
                 "국가정보원･과학기술정보통신부 및 관계 중앙행정기관은 관련 정보를 공유하고 역할을 분담하여 공동책임 기반의 보안관리 체계 구축"]},
    {"title": "예측 가능성 및 절차적 안정성 원칙",
     "details": ["R&D 기획･공고･협약단계에서 보안등급을 분류하거나 안내하여 예측 가능성을 높이되 상황에 따라 전 주기상 보안등급 지정･변경 추진",
                 "대외환경 변화 또는 연구 성격･활용계획 변경 등으로 보안등급 변경이 필요한 경우 이해관계자 간 사전 협의를 거쳐 다시 분류 여부 검토"]},
    {"title": "과제 단위 분류",
     "details": ["연구개발과제의 특성(목표･성과활용 계획)을 고려한 과제 단위 분류",
                 "주관･공동･위탁연구개발기관이 수행하는 연구개발과제의 보안등급은 주관 연구개발기관의 연구개발과제를 기준으로 일괄 지정하기보다, 각 연구개발기관의 연구수행 범위와 성과 활용계획 등을 고려하여 개별적으로 지정할 것을 권고",
                 "국가 전략적 중요도가 높거나 보안 민감성이 큰 사업군의 경우 중앙행정기관의 판단에 따라 사업 단위 보안등급 분류도 검토 가능"]},
]
SAFE_MESSAGE = "저장 결과의 구조 또는 일치 검증에 실패했습니다."


class V16DomainTests(unittest.TestCase):
    def setUp(self):
        self.notice = synthetic_notice()
        self.manifest = self.notice["catalogue_manifest"]

    def test_schema_three_results_carry_announcement_dates_and_older_schemas_are_rejected(self):
        self.assertEqual(d.SCHEMA_VERSION, 3)
        result, opts = synthetic_result()
        self.assertEqual(result["schema_version"], 3)
        d.validate_result(result, opts)
        self.assertTrue(all("announcement_date" in source for source in result["notice_review"]["sources"]))
        self.assertTrue(all("announcement_date" in source for source in result["notice_review"]["catalogue_manifest"]["sources"]))
        fresh = d.make_result({"과제명": "합성"}, catalogue_manifest=self.manifest)
        self.assertEqual(fresh["schema_version"], 3)
        self.assertEqual(fresh["notice_review"]["sources"], self.manifest["sources"])
        for value in (2, 1, 4, "3", 3.0, True, None):
            changed = deepcopy(result)
            changed["schema_version"] = value
            with self.subTest(schema=value), self.assertRaises(ValueError):
                d.validate_result(changed)

    def test_v15_schema2_result_cannot_pass_v16_validation(self):
        import test_v15_domain as previous
        old_result, _ = previous.synthetic_result()
        with self.assertRaises(ValueError):
            d.validate_result(old_result)
        upgraded = deepcopy(old_result)
        upgraded["schema_version"] = 3
        # The v15 manifest lacks announcement dates: still not a v16 result.
        with self.assertRaises(ValueError):
            d.validate_result(upgraded)

    def test_source_keys_and_notice_title_table(self):
        self.assertEqual(d.SOURCE_KEYS, frozenset({
            "source_id", "families", "title", "notice_number", "announcement_version", "announcement_date",
            "effective_date", "official_url", "retrieved_at", "relative_path", "sha256", "review_status",
            "coverage", "review_note"}))
        self.assertEqual(dict(d.NOTICE_TITLES), {
            "산업통상자원부고시 제2025-71호": "국가첨단전략기술 지정 등에 관한 고시",
            "산업통상부고시 제2025-2호": "국가핵심기술 지정 등에 관한 고시",
            "산업통상부고시 제2026-101호": "전략물자수출입고시",
        })
        with self.assertRaises(TypeError):
            d.NOTICE_TITLES["추가"] = "변경"

    def test_manifest_date_title_and_body_rules(self):
        def each(predicate, **changes):
            def mutate(manifest):
                for source in manifest["sources"]:
                    if predicate(source):
                        source.update(changes)
            return mutate

        def remove_announcement(manifest):
            del manifest["sources"][0]["announcement_date"]
        core = lambda source: source["notice_number"] == "산업통상부고시 제2025-2호"
        military = lambda source: source["source_id"] == "synthetic-military-annex"
        advanced = lambda source: source["source_id"] == "synthetic-advanced-body"
        cases = {
            "announcement_after_effective": each(core, announcement_date="2025-10-03"),
            "different_announcement_same_notice": each(military, announcement_date="2026-08-30"),
            "different_effective_same_notice": each(military, effective_date="2026-09-02"),
            "unknown_notice_number": each(advanced, notice_number="합성-1"),
            "missing_announcement_key": remove_announcement,
            "extra_source_key": lambda manifest: manifest["sources"][0].update(notice_title="추가"),
            "two_body_sources": each(military, source_id="synthetic-military-body"),
            "no_body_source": each(core, source_id="synthetic-core-main"),
        }
        for key in ("announcement_date", "effective_date"):
            for value in ("2025-5-12", "20251002", "2025-02-30", "2025-10-02 ", "", None, 20251002):
                changes = {key: value}
                if key == "effective_date":
                    changes["announcement_date"] = "2025-01-01"
                cases[key + "_invalid_" + repr(value)] = each(core, **changes)
        for name, mutate in cases.items():
            manifest = deepcopy(self.manifest)
            mutate(manifest)
            with self.subTest(case=name):
                with self.assertRaises(ValueError) as caught:
                    d.validate_manifest(manifest)
                self.assertEqual(str(caught.exception), SAFE_MESSAGE)
                notice = deepcopy(self.notice)
                notice.update(catalogue_manifest=manifest, sources=deepcopy(manifest["sources"]),
                              catalogue_fingerprint=d.canonical_hash(manifest))
                notice["comparisons"][0]["comparison_id"] = d.comparison_id(notice["catalogue_fingerprint"], "advanced:1")
                with self.assertRaises(ValueError):
                    d.validate_notice_review(notice, {"과제명": "합성 과제", "현재 기술사양": "속도 20 GHz"})
        # Same-day announcement/effective (산업통상부고시 제2025-2호) is valid.
        self.assertIs(d.validate_manifest(self.manifest, require_executable=True), self.manifest)

    def test_display_guideline_is_appendix_a_verbatim_and_separate_from_prompt_constants(self):
        display = d.guideline_display()
        self.assertEqual(set(display), {"id", "definitions", "principles"})
        self.assertEqual(display["id"], d.GUIDELINE_ID)
        self.assertEqual(display["definitions"], APPENDIX_A_DEFINITIONS)
        self.assertEqual(display["principles"], APPENDIX_A_PRINCIPLES)
        self.assertEqual(json.dumps(display["definitions"], ensure_ascii=False).encode("utf-8"),
                         json.dumps(APPENDIX_A_DEFINITIONS, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(json.dumps(display["principles"], ensure_ascii=False).encode("utf-8"),
                         json.dumps(APPENDIX_A_PRINCIPLES, ensure_ascii=False).encode("utf-8"))
        for entry in display["definitions"]:
            self.assertEqual(type(entry), dict)
            self.assertEqual(list(entry), ["heading", "text"])
        for entry in display["principles"]:
            self.assertEqual(list(entry), ["title", "details"])
            self.assertEqual(type(entry["details"]), list)
        self.assertNotIn("대체값으로 사용하지 않는다", json.dumps(display, ensure_ascii=False))
        display["definitions"][0]["text"] = "변경"
        display["principles"][0]["details"].append("변경")
        self.assertEqual(d.guideline_display()["definitions"], APPENDIX_A_DEFINITIONS)
        self.assertEqual(d.guideline_display()["principles"], APPENDIX_A_PRINCIPLES)

    def test_v16_core_modules_import_only_v16_or_reused_modules(self):
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        project = {path.stem for path in root.glob("*.py")}
        allowed = {"v16_domain", "notice_catalogue_v16", "notice_review_v16", "classification_v16",
                   "llm_client_v14", "credential_store"}
        for name in ("v16_domain", "notice_catalogue_v16", "notice_review_v16", "classification_v16"):
            tree = ast.parse((root / (name + ".py")).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            with self.subTest(module=name):
                self.assertLessEqual(imported & project, allowed)

    def test_ai_prompt_constants_are_byte_identical_to_v15(self):
        import v15_domain as previous
        for name in ("LEGAL_DEFINITIONS", "CLASSIFICATION_PRINCIPLES", "CRITERIA", "ITEM_NAMES", "PERSONAS",
                     "GUIDELINE_ID", "COMPARISON_RULES_VERSION", "FAMILIES", "GRADES", "LEVELS", "STATUSES"):
            with self.subTest(name=name):
                self.assertEqual(getattr(d, name), getattr(previous, name))
        dump = lambda module: json.dumps(dict(principles=module.CLASSIFICATION_PRINCIPLES,
            legal_definitions=dict(module.LEGAL_DEFINITIONS),
            criteria=[dict(c, rubric=dict(c["rubric"])) for c in module.CRITERIA]), ensure_ascii=False).encode("utf-8")
        self.assertEqual(dump(d), dump(previous))


if __name__ == "__main__":
    unittest.main()
