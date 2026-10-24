"""Offline v16 engine regressions; every catalogue and model is synthetic."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest import mock

import v16_domain as d
import classification_v16 as engine
from notice_catalogue_v16 import Catalogue, CatalogueError
from test_v16_notice_review import catalogue, fact, repack, Client as NoticeClient


TASK = {"과제명": "합성 과제", "현재 기술사양": "속도 20 GHz"}


def items(policy="", detailed=False, chosen=(1, 2)):
    result = []
    for index, criterion in enumerate(d.CRITERIA, 1):
        entry = dict(item=criterion["name"], level="해당" if index in chosen else "미해당",
                     note="합성 사실 및 유출 영향 검토", law_refs=list(criterion["security_refs"]))
        if index == 8 and not policy:
            entry.update(level="미검토", law_refs=[])
        if detailed:
            entry.update(matched_reference="", needs_expert_review=False)
        result.append(entry)
    return result


class Client(NoticeClient):
    provider = "claude"
    model = "claude-sonnet-5-5"

    def __init__(self, *, candidates=(), facts=None, transform=None, chosen=(1, 2),
                 scores=(4, 4), candidate=True):
        super().__init__([fact()] if facts is None else facts, candidates=candidates)
        self.change = transform
        self.chosen, self.score_values, self.candidate = chosen, scores, candidate
        self.engine_calls = []

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        data = json.loads(user_prompt)
        if "phase" in data:
            out = super().ask_json(system_prompt, user_prompt, temperature)
        else:
            self.engine_calls.append((system_prompt, data))
            policy = data["effective_ministry_policy"]
            stage = data["stage"]
            if stage == "candidate":
                out = dict(is_candidate=self.candidate, reason="합성 후보 여부 확인", uncertainty="")
            elif stage == "criteria":
                common = items(policy, True, self.chosen)
                for index, entry in enumerate(common, 1):
                    links = [dict(comparison_id=c["comparison_id"], source_id=c["source_id"])
                             for c in data["notice_review"]["comparisons"] if index in c["affected_items"]]
                    if links:
                        entry["matched_reference"] = json.dumps(links)
                out = {"criteria": common}
            elif stage == "reviewer":
                values = self.score_values
                if isinstance(values, dict):
                    values = values[data["reviewer_id"]]
                score_map = {name: values[index % len(values)] for index, name in enumerate(data["selected_items"])}
                score = d.calculate_reviewer_score(score_map, data["selected_items"], data["weights"]) if data["method"] == "impact" else None
                out = dict(item_reviews=items(policy, False, self.chosen),
                    scores=score_map if data["method"] == "impact" else {},
                    grade=d.rule_grade(score) if score is not None else "민감과제", confidence="보통",
                    rationale=data["persona"] + " 독립 보호 필요성", discussion_points="역할별 논의", unresolved_reasons=[],
                    notice_comments=[dict(comparison_id=c["comparison_id"], comment=data["persona"] + " 고시 검토")
                                     for c in data["notice_review"]["comparisons"]])
            else:
                out = dict(final_grade=data["rule_grade"] or "민감과제", confidence="보통",
                    rationale="합성 법정의 및 보호 필요성 종합", discussion_points="독립 의견 차이 검토", unresolved_reasons=[])
        return self.change(data, out) if self.change else out


class EngineTests(unittest.TestCase):
    def run_engine(self, options=None, client=None, task=None, cat=None, **kwargs):
        task = TASK if task is None else task
        cat = catalogue() if cat is None else cat
        result = engine.classify_task(task, options or {"num_reviewers": 1}, client or Client(), catalogue=cat, **kwargs)
        opts = d.normalize_options((options or {"num_reviewers": 1}) | {"catalogue_fingerprint": cat.fingerprint},
                                   ministry_policy_context=task.get("부처 세부기준", ""))
        self.assertIs(d.validate_result(result, opts, task), result)
        return result

    def test_methods_and_panels_auto_manual(self):
        for method in ("checklist", "impact"):
            for count in (1, 3):
                for selection in ("auto", "manual"):
                    with self.subTest(method=method, count=count, selection=selection):
                        opts = dict(method=method, num_reviewers=count, selection_mode=selection,
                                    selected_items=[1, 2], weights={1: .8, 2: 1.2})
                        result = self.run_engine(opts)
                        self.assertEqual(result["status"], "완료")
                        self.assertEqual(len(result["reviewers"]), count)
                        self.assertEqual(result["overall_avg"], 4 if method == "impact" else None)
                        expected = {} if method == "checklist" else dict(zip(d.ITEM_NAMES[:2], (1., 1.) if selection == "auto" else (.8, 1.2)))
                        self.assertEqual(result["weights"], expected)

    def test_auto_discards_stale_invalid_values(self):
        result = self.run_engine(dict(num_reviewers=1, selected_items=object(), weights="invalid", weight_tolerance="invalid"))
        self.assertEqual(result["weights"], dict.fromkeys(d.ITEM_NAMES[:2], 1.))

    def test_policy_row_overrides_common_and_item_eight(self):
        client = Client(chosen=(8,))
        result = self.run_engine(dict(num_reviewers=1, ministry_policy="공통기준"), client,
                                 TASK | {"부처 세부기준": "과제별기준"})
        self.assertEqual(result["selected_items"], [d.ITEM_NAMES[7]])
        self.assertTrue(all(c[1]["effective_ministry_policy"] == "과제별기준" for c in client.engine_calls))
        self.assertEqual(self.run_engine(client=Client(chosen=(8,)))["status"], "검토필요")

    def test_bad_public_input_and_options_raise_before_model(self):
        for task, opts in [({}, {}), (TASK, {"strictness": "엄격"}), (TASK, {"selection_mode": "manual", "selected_items": []}),
                           (TASK, {"selection_mode": "manual", "selected_items": [8]}),
                           (TASK, {"selection_mode": "manual", "selected_items": [1], "weights": {1: .8}})]:
            client = Client()
            with self.subTest(task=task, opts=opts), self.assertRaises(ValueError):
                engine.classify_task(task, opts, client, catalogue=catalogue())
            self.assertFalse(client.calls)

    def test_invalid_option_shapes_raise_safe_value_error(self):
        for options in (1, object(), {"selection_mode": "manual", "selected_items": [1], "weights": 1}):
            client = Client()
            with self.subTest(options=type(options)), self.assertRaises(ValueError):
                engine.classify_task(TASK, options, client, catalogue=catalogue())
            self.assertFalse(client.calls)
            with self.assertRaises(ValueError):
                engine.normalize_options(options)

    def test_invalid_catalogues_raise_before_model(self):
        original = catalogue()
        for cat in (object(), replace(original, fingerprint="0" * 64), replace(original, by_family={}),
                    replace(original, clauses=()), replace(original, manifest={})):
            client = Client()
            with self.subTest(cat=type(cat)), self.assertRaises(CatalogueError):
                engine.classify_task(TASK, {}, client, catalogue=cat)
            self.assertFalse(client.calls)

    def test_default_loader_is_consumed(self):
        with mock.patch.object(engine, "load_catalogue", return_value=catalogue()) as loader:
            result = engine.classify_task(TASK, {"num_reviewers": 1}, Client())
        loader.assert_called_once_with()
        self.assertEqual(d.validate_result(result)["status"], "완료")

    def test_notices_precede_candidate_and_exclusion_retains_inventory(self):
        client = Client(candidate=False)
        result = self.run_engine(client=client)
        self.assertEqual(result["status"], "후보제외")
        self.assertEqual(result["notice_review"]["status"], "complete")
        self.assertEqual(sum(len(f["screened_ids"]) for f in result["notice_review"]["families"]), 4)
        self.assertEqual(result["documents"]["expected_files"], 1)
        self.assertFalse(result["reviewers"])
        self.assertEqual(client.engine_calls[0][1]["stage"], "candidate")
        self.assertTrue(client.calls)

    def test_relevant_notice_prevents_unsupported_exclusion(self):
        result = self.run_engine(client=Client(candidates=("advanced:1",), candidate=False))
        self.assertEqual(result["status"], "검토필요")
        self.assertEqual(len(result["notice_review"]["comparisons"]), 1)

    def test_notice_unknown_related_blocks_unrelated_does_not(self):
        self.assertEqual(self.run_engine(client=Client(facts=[]))["status"], "완료")
        related = self.run_engine(client=Client(candidates=("advanced:1",), facts=[]))
        self.assertEqual(related["status"], "검토필요")
        self.assertIsNone(related["final_grade"])

    def test_target_is_possibility_not_current(self):
        task = TASK | {"현재 기술사양": "속도 5 GHz", "개발목표 사양": "속도 20 GHz"}
        facts = [fact("속도 5 GHz", number="5"), fact(field="개발목표 사양", basis="target", identity="t1")]
        client = Client(candidates=("advanced:1",), facts=facts)
        result = self.run_engine(client=client, task=task)
        comparison = result["notice_review"]["comparisons"][0]
        self.assertEqual((comparison["current_assessment"], comparison["target_assessment"]), ("not_satisfied", "satisfied"))
        self.assertEqual(result["status"], "완료")
        self.assertIn("가능성", client.engine_calls[0][0])

    def test_partial_and_error_notice_states(self):
        def partial(data, out):
            return {"decisions": []} if data.get("phase") == "screen" else out
        result = self.run_engine(client=Client(transform=partial))
        self.assertEqual((result["notice_review"]["status"], result["status"]), ("needs_info", "검토필요"))
        def bad(data, out):
            if data.get("phase") == "screen":
                out["decisions"][0]["clause_id"] = "missing"
            return out
        result = self.run_engine(client=Client(transform=bad))
        self.assertEqual((result["notice_review"]["status"], result["status"]), ("error", "오류"))
        self.assertTrue(result["notice_review"]["facts"])

    def test_same_context_independent_roles_and_standard_only_summary(self):
        client = Client(candidates=("advanced:1",))
        result = self.run_engine({"num_reviewers": 3}, client)
        requests = [p for _, p in client.engine_calls if p["stage"] == "reviewer"]
        self.assertEqual([p["persona"] for p in requests], list(d.PERSONAS))
        for request in requests:
            self.assertNotIn("reviewers", request)
            self.assertNotIn("strictness", request)
            self.assertEqual(request["notice_review"], result["notice_review"])
            self.assertEqual(request["criteria"], result["criteria"])
            self.assertEqual(request["weights"], result["weights"])
        self.assertEqual(client.engine_calls[-1][1]["strictness"], "표준")
        self.assertEqual(len({r["rationale"] for r in result["reviewers"]}), 3)
        self.assertNotEqual(result["rationale"], result["reviewers"][0]["rationale"])

    def test_exact_score_boundaries_and_no_intermediate_rounding(self):
        for scores, expected, grade in [((3, 4), 3.5, "민감과제"), ((4, 5), 4.5, "보안과제")]:
            result = self.run_engine(client=Client(scores=scores))
            self.assertEqual((result["overall_avg"], result["rule_grade"]), (expected, grade))
        opts = dict(num_reviewers=3, selection_mode="manual", selected_items=[1, 2], weights={1: .999999, 2: 1.000001})
        result = self.run_engine(opts, Client(scores=(4, 3)))
        self.assertLess(result["overall_avg"], 3.5)
        self.assertEqual(result["rule_grade"], "일반과제")
        self.assertEqual(result["overall_avg"], result["reviewers"][0]["reviewer_score"])

    def test_bad_scores_are_errors_and_never_replaced(self):
        for value in (3.5, float("nan"), 0, 6, True, None):
            def corrupt(data, out):
                if data.get("stage") == "reviewer":
                    out["scores"][d.ITEM_NAMES[0]] = value
                return out
            with self.subTest(value=value):
                result = self.run_engine(client=Client(transform=corrupt))
                self.assertEqual(result["status"], "오류")
                self.assertIsNone(result["overall_avg"])
                self.assertFalse(result["reviewers"][0]["scores"])

    def test_missing_extra_and_duplicate_scores_are_errors(self):
        for attack in ("missing", "extra", "duplicate"):
            def corrupt(data, out):
                if data.get("stage") == "reviewer":
                    if attack == "missing":
                        out["scores"].pop(d.ITEM_NAMES[0])
                    elif attack == "extra":
                        out["scores"][d.ITEM_NAMES[2]] = 4
                    else:
                        out["scores"]["1"] = 4
                return out
            self.assertEqual(self.run_engine(client=Client(transform=corrupt))["status"], "오류")

    def test_one_role_failure_never_averages_smaller_panel(self):
        def fail_second(data, out):
            if data.get("reviewer_id") == "reviewer-2":
                raise RuntimeError("SYNTHETIC_SECRET")
            return out
        result = self.run_engine({"num_reviewers": 3}, Client(transform=fail_second))
        self.assertEqual(result["status"], "오류")
        self.assertEqual(result["reviewers"][0]["status"], "완료")
        self.assertEqual(len(result["reviewers"]), 3)
        self.assertIsNone(result["overall_avg"])
        self.assertNotIn("SYNTHETIC_SECRET", str(result))

    def test_legal_mismatch_requires_specific_law_and_low_confidence(self):
        def mismatch(data, out):
            if data.get("stage") == "summary":
                out.update(final_grade="보안과제", rationale="제21조제4항: 합성 국가안보 유출 영향이 상당하여 별도 보호 필요")
            return out
        result = self.run_engine(client=Client(transform=mismatch))
        self.assertEqual((result["status"], result["confidence"]), ("완료", "낮음"))
        self.assertTrue(result["discussion_points"])
        def no_law(data, out):
            if data.get("stage") == "summary":
                out["final_grade"] = "보안과제"
            return out
        self.assertEqual(self.run_engine(client=Client(transform=no_law))["status"], "오류")

    def test_comparison_comments_missing_duplicate_and_unknown_rejected(self):
        for attack in ("missing", "duplicate", "unknown"):
            def corrupt(data, out):
                if data.get("stage") == "reviewer":
                    if attack == "missing":
                        out["notice_comments"] = []
                    elif attack == "duplicate":
                        out["notice_comments"] *= 2
                    else:
                        out["notice_comments"][0]["comparison_id"] = "0" * 64
                return out
            self.assertEqual(self.run_engine(client=Client(candidates=("advanced:1",), transform=corrupt))["status"], "오류")

    def test_criteria_bad_comparison_or_source_link_is_error(self):
        for key in ("comparison_id", "source_id"):
            def corrupt(data, out):
                if data.get("stage") == "criteria":
                    links = json.loads(out["criteria"][1]["matched_reference"])
                    links[0][key] = "0" * 64
                    out["criteria"][1]["matched_reference"] = json.dumps(links)
                return out
            self.assertEqual(self.run_engine(client=Client(candidates=("advanced:1",), transform=corrupt))["status"], "오류")

    def test_client_model_mismatch_and_mutation_fail_closed(self):
        client = Client()
        client.model = "other"
        result = self.run_engine(client=client)
        self.assertEqual(result["status"], "오류")
        self.assertFalse(client.calls)
        for stage in ("facts", "candidate", "reviewer"):
            client = Client()
            def mutate(data, out):
                if data.get("phase", data.get("stage")) == stage:
                    client.model = "other"
                return out
            client.change = mutate
            self.assertEqual(self.run_engine(client=client)["status"], "오류")

    def test_progress_callback_cannot_change_result(self):
        seen = []
        def callback(event):
            seen.append(event)
            raise RuntimeError("ignored")
        result = self.run_engine(progress_callback=callback)
        self.assertEqual(result["status"], "완료")
        self.assertTrue(seen)
        self.assertTrue(all(isinstance(event, dict) and "stage" in event for event in seen))

    def test_model_mutation_in_completion_callback_is_error(self):
        client = Client()
        def callback(event):
            if event["stage"] == "summary" and event["completed"] == 1:
                client.model = "other"
        result = self.run_engine(client=client, progress_callback=callback)
        self.assertEqual(result["status"], "오류")
        self.assertIsNone(result["final_grade"])

    def test_malformed_stages_are_errors_preserving_prior_valid_data(self):
        for stage in ("candidate", "criteria", "summary"):
            def invalid(data, out):
                return {} if data.get("stage") == stage else out
            result = self.run_engine(client=Client(transform=invalid))
            self.assertEqual(result["status"], "오류")
            self.assertEqual(result["notice_review"]["status"], "complete")
            self.assertIsNone(result["final_grade"])
            if stage == "summary":
                self.assertEqual(result["reviewers"][0]["status"], "완료")

    def test_long_notice_original_and_reference_survive_context_failure(self):
        note_text = "합성 공통 주석 원문 " * 7200 + "END_NOTE"
        note = dict(clause_id="advanced:note", source_id="advanced-body", family="advanced", code="NOTE",
            title="합성 주석", field="공통정의·주석", source_anchor="advanced.txt#note", text=note_text,
            qualifier_refs=[], condition=dict(type="unsupported", predicate_id="note", subject="주석", text="원문 주석",
                                           source_anchor="advanced.txt#note", reason="시험 주석"))
        plain = catalogue(extras=(note,)).to_dict()
        original_text = "속도 10 GHz 이상 " + "합성 기술 원문 " * 6700 + "END_ORIGINAL"
        plain["clauses"][0].update(text=original_text, qualifier_refs=["advanced:note"])
        cat = repack(plain)
        def input_limit(data, out):
            if data.get("stage") == "candidate":
                raise RuntimeError("maximum context token length SYNTHETIC_SECRET")
            return out
        client = Client(candidates=("advanced:1",), transform=input_limit)
        result = self.run_engine(client=client, cat=cat)
        self.assertEqual(result["status"], "오류")
        self.assertEqual(result["notice_review"]["status"], "complete")
        snapshots = {c["clause_id"]: c for c in result["notice_review"]["clause_snapshots"]}
        self.assertEqual(snapshots["advanced:1"]["text"], original_text)
        self.assertEqual(snapshots["advanced:note"]["text"], note_text)
        self.assertEqual(client.engine_calls[0][1]["notice_review"], result["notice_review"])
        self.assertNotIn("SYNTHETIC_SECRET", str(result))
        self.assertIsNone(result["final_grade"])

    def test_empty_selection_blocks_both_methods(self):
        for method in ("impact", "checklist"):
            result = self.run_engine(dict(num_reviewers=1, method=method), Client(chosen=()))
            self.assertEqual(result["status"], "검토필요")
            self.assertFalse(result["weights"])
            self.assertFalse(result["reviewers"])

    def test_unresolved_candidate_and_items_keep_final_null(self):
        for stage in ("candidate", "criteria", "reviewer", "summary"):
            def uncertain(data, out):
                if data.get("stage") == stage:
                    if stage == "candidate":
                        out.update(is_candidate=None, uncertainty="합성 후보 확인 부족")
                    elif stage == "criteria":
                        out["criteria"][0].update(level="판단곤란", needs_expert_review=True)
                    else:
                        out["unresolved_reasons"] = ["합성 보호 필요성 확인 부족"]
                        out["final_grade" if stage == "summary" else "grade"] = None
                return out
            with self.subTest(stage=stage):
                result = self.run_engine(client=Client(transform=uncertain))
                self.assertEqual(result["status"], "검토필요")
                self.assertIsNone(result["final_grade"])

    def test_error_precedes_prior_notice_needs_info(self):
        def fail_role(data, out):
            if data.get("stage") == "reviewer":
                return {}
            return out
        result = self.run_engine(client=Client(candidates=("advanced:1",), facts=[], transform=fail_role))
        self.assertEqual(result["notice_review"]["status"], "needs_info")
        self.assertEqual(result["status"], "오류")

    def test_selected_provider_model_and_local_models_are_pinned(self):
        for provider, model in (("openai", "gpt-6-luna"), ("ollama", "synthetic-local"), ("lmstudio", "synthetic-local")):
            client = Client()
            client.provider, client.model = provider, model
            result = self.run_engine(dict(num_reviewers=1, provider=provider, model=model), client)
            self.assertEqual((result["provider"], result["model"], result["status"]), (provider, model, "완료"))

    def test_invalid_item_shapes_checklist_scores_and_law_refs(self):
        for attack in ("missing_item", "duplicate_item", "invalid_law", "checklist_score", "extra_root"):
            def corrupt(data, out):
                if data.get("stage") == "reviewer":
                    if attack == "missing_item":
                        out["item_reviews"].pop()
                    elif attack == "duplicate_item":
                        out["item_reviews"][1]["item"] = out["item_reviews"][0]["item"]
                    elif attack == "invalid_law":
                        out["item_reviews"][0]["law_refs"] = ["합성 허위 조항"]
                    elif attack == "checklist_score":
                        out["scores"] = {d.ITEM_NAMES[0]: 3}
                    else:
                        out["unexpected"] = True
                return out
            result = self.run_engine(dict(num_reviewers=1, method="checklist"), Client(transform=corrupt))
            self.assertEqual(result["status"], "오류")


class RecordingClient(Client):
    """Records the exact system/user wire strings of every ask."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wire = []

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        self.wire.append((system_prompt, user_prompt, temperature))
        return super().ask_json(system_prompt, user_prompt, temperature)


class V15ParityTests(unittest.TestCase):
    """Spec 6: identical system prompts; user prompts/saved text equal after mapping."""

    def test_system_prompt_builder_is_byte_identical_to_v15(self):
        import classification_v15 as previous
        for policy in ("", "합성 부처 기준", "따옴표 \" 와 줄바꿈\n포함"):
            with self.subTest(policy=policy):
                self.assertEqual(engine._system(policy).encode("utf-8"), previous._system(policy).encode("utf-8"))

    def test_same_synthetic_task_sends_identical_prompts_and_saves_identical_text(self):
        import classification_v15 as previous
        from test_v16_notice_review import catalogue_mapping, normalise, substitute

        def fail_reviewer(data, out):
            return {} if data.get("stage") == "reviewer" else out
        scenarios = (
            ("complete_impact_three", dict(num_reviewers=3), TASK, dict(candidates=("advanced:1", "core:1"))),
            ("complete_checklist_policy", dict(num_reviewers=1, method="checklist", ministry_policy="합성 공통 기준"),
             TASK, dict(candidates=("advanced:1",), chosen=(1, 8))),
            ("manual_weights_target", dict(num_reviewers=1, selection_mode="manual", selected_items=[1, 2], weights={1: .8, 2: 1.2}),
             TASK | {"현재 기술사양": "속도 5 GHz", "개발목표 사양": "속도 20 GHz"},
             dict(candidates=("advanced:1",), facts=[fact("속도 5 GHz", number="5"),
                  fact(field="개발목표 사양", basis="target", identity="t1")])),
            ("candidate_excluded", dict(num_reviewers=1), TASK, dict(candidate=False)),
            ("notice_pending_review", dict(num_reviewers=1), TASK, dict(candidates=("advanced:1",), facts=[])),
            ("reviewer_failure", dict(num_reviewers=3), TASK, dict(candidates=("advanced:1",), transform=fail_reviewer)),
        )
        for name, options, task, client_options in scenarios:
            with self.subTest(scenario=name):
                old_cat = catalogue(v15=True, catalogue_id="synthetic-v15")
                new_cat = catalogue(catalogue_id="synthetic-v16")
                old_client, new_client = RecordingClient(**client_options), RecordingClient(**client_options)
                old = previous.classify_task(task, options, old_client, catalogue=old_cat)
                new = engine.classify_task(task, options, new_client, catalogue=new_cat)
                self.assertEqual((old["schema_version"], new["schema_version"]), (2, 3))
                d.validate_result(new)
                mapping = catalogue_mapping(old_cat, new_cat)
                mapping[old["options_fingerprint"]] = new["options_fingerprint"]
                self.assertEqual(len(old_client.wire), len(new_client.wire))
                self.assertTrue(new_client.engine_calls)
                for (old_system, old_user, old_temperature), (new_system, new_user, new_temperature) in zip(old_client.wire, new_client.wire):
                    self.assertEqual(old_system.encode("utf-8"), new_system.encode("utf-8"))
                    self.assertEqual(old_temperature, new_temperature)
                    self.assertEqual(normalise(json.loads(substitute(old_user, mapping))), normalise(json.loads(new_user)))
                old_saved = normalise(json.loads(substitute(json.dumps(old, ensure_ascii=False), mapping)))
                new_saved = normalise(deepcopy(new))
                for saved in (old_saved, new_saved):
                    saved.pop("schema_version")
                self.assertEqual(old_saved, new_saved)

    def test_progress_labels_are_screen_only_noun_style(self):
        from test_v16_notice_review import STYLE_ENDINGS
        events = []
        result = engine.classify_task(TASK, {"num_reviewers": 1}, Client(candidates=("advanced:1",)),
                                      events.append, catalogue=catalogue())
        self.assertEqual(result["status"], "완료")
        labels = {event["stage"]: event["message"] for event in events}
        self.assertEqual({key: labels[key] for key in ("candidate", "criteria", "reviewer", "summary")},
                         dict(candidate="등급분류 대상 여부 검토", criteria="검토항목 확인",
                              reviewer="AI 에이전트 독립 검토", summary="표준 종합 의견 작성"))
        saved = json.dumps(result, ensure_ascii=False)
        for message in set(labels.values()):
            self.assertFalse(message.rstrip(". ").endswith(STYLE_ENDINGS), message)
            self.assertNotIn(message, saved)


if __name__ == "__main__":
    unittest.main()
