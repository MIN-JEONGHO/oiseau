"""Synthetic offline HWPX regressions; native Hangul visual QA is separate."""
from copy import deepcopy
import builtins
import importlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile, ZIP_STORED

from lxml import etree as E

import hwpx_writer_v15 as writer
import v15_domain as d
from test_v15_domain import synthetic_notice, synthetic_result


def sample_result(method="impact", count=3):
    result, _ = synthetic_result(method, count)
    result["rationale"] = "종합의견 고유문구"
    result["discussion_points"] = "의견차이와 미해결조건 종합토론"
    result["task_snapshot"]["연구내용"] = '첫 문단 <자료> & "인용"\n둘째 문단'
    result["task_fingerprint"] = d.task_fingerprint(result["task_snapshot"])
    for index, reviewer in enumerate(result["reviewers"]):
        reviewer["rationale"] = f"개인의견 고유문구 {index + 1}"
        reviewer["discussion_points"] = f"개인토론 {index + 1}"
        reviewer["notice_comments"][0]["comment"] = f"개인 고시의견 {index + 1}"
        for item in reviewer["item_reviews"]:
            item["note"] = f"개인 항목의견 {index + 1} {item['item']}"
    d.validate_result(result)
    return result


def rebind_notice(result):
    """Rebind an intentionally changed synthetic baseline, never live files."""
    notice = result["notice_review"]
    by_id = {clause["clause_id"]: clause for clause in notice["clause_snapshots"]}
    for entry in notice["catalogue_manifest"]["clause_inventory"]:
        if entry["clause_id"] in by_id:
            entry["sha256"] = d.canonical_hash(by_id[entry["clause_id"]])
    fingerprint = d.canonical_hash(notice["catalogue_manifest"])
    notice["catalogue_fingerprint"] = result["catalogue_fingerprint"] = fingerprint
    for comparison in notice["comparisons"]:
        comparison["comparison_id"] = d.comparison_id(fingerprint, comparison["clause_id"])
    for index, item in enumerate(result["criteria"], 1):
        links = [{"comparison_id": entry["comparison_id"], "source_id": entry["source_id"]}
                 for entry in notice["comparisons"] if index in entry["affected_items"]]
        item["matched_reference"] = json.dumps(links) if links else ""
    for index, reviewer in enumerate(result["reviewers"]):
        reviewer["notice_comments"] = [{"comparison_id": comparison["comparison_id"],
            "comment": f"개인 고시의견 {index + 1} {comparison['clause_id']}"}
            for comparison in notice["comparisons"]]
    result["task_fingerprint"] = d.task_fingerprint(result["task_snapshot"])
    d.validate_result(result)
    return result


def target_result(partial=False):
    result = sample_result(count=1)
    task = result["task_snapshot"]
    task["개발목표 사양"] = "속도 30 GHz"
    notice = result["notice_review"]
    notice["facts"].append(notice["facts"][0] | {"fact_id": "target-1", "basis": "target",
        "source_field": "개발목표 사양", "quote": "속도 30 GHz", "value_text": "30 GHz", "number": "30"})
    comparison = notice["comparisons"][0]
    comparison.update(target_assessment="satisfied")
    comparison["conditions"][1].update(fact_ids=["target-1"], normalized_value="30", normalized_unit="GHz",
        assessment="satisfied", reason="목표 수치 대조")
    if partial:
        clause = notice["clause_snapshots"][0]
        clause["text"] += " 및 추가 적용조건 확인"
        clause["condition"] = {"type": "all", "children": [clause["condition"],
            {"type": "qualitative", "predicate_id": "scope", "text": "추가 적용조건 확인",
             "source_anchor": "합성 주석 1", "subject": "적용범위", "reason": "설명 필요"}]}
        for basis in ("current", "target"):
            comparison["conditions"].append({"predicate_id": "scope", "basis": basis,
                "condition_text": "추가 적용조건 확인", "fact_ids": [], "normalized_value": None,
                "normalized_unit": None, "assessment": "insufficient_info", "reason": "범위 자료 부족",
                "source_anchor": "합성 주석 1"})
            comparison["missing_information"].append({"basis": basis, "predicate_id": "scope",
                "question": f"{basis} 적용범위 자료를 제공해 주세요"})
        comparison.update(current_assessment="insufficient_info", target_assessment="insufficient_info")
        notice.update(status="needs_info", blocking_reasons=["현재 및 목표 적용범위 확인 필요"])
        result.update(status="검토필요", final_grade=None, unresolved_reasons=["추가 적용조건 확인 필요"])
    return rebind_notice(result)


def all_family_result(method="impact", count=3):
    """Make all four families candidates without using any installed source."""
    result = sample_result(method, count)
    notice = result["notice_review"]
    prototype = deepcopy(notice["clause_snapshots"][0])
    comparison = deepcopy(notice["comparisons"][0])
    notice["clause_snapshots"], notice["comparisons"] = [], []
    for entry in notice["families"]:
        family = entry["family"]
        clause = deepcopy(prototype)
        clause.update(clause_id=family + ":1", family=family, source_id="synthetic-" + family,
            title=family + " 고유 후보 제목", text=family + " 고유 원문: 속도 10 GHz 이상",
            source_anchor=family + " 원문 위치")
        clause["condition"]["source_anchor"] = clause["source_anchor"]
        record = deepcopy(comparison)
        record.update(clause_id=clause["clause_id"], family=family, source_id=clause["source_id"],
            rationale=family + " 고유 대조 근거")
        for condition in record["conditions"]:
            condition["source_anchor"] = clause["source_anchor"]
        entry.update(candidate_ids=[clause["clause_id"]], excluded=[])
        notice["clause_snapshots"].append(clause)
        notice["comparisons"].append(record)
    return rebind_notice(result)


def xml_root(path):
    with ZipFile(BytesIO(Path(path).read_bytes())) as z:
        return E.fromstring(z.read(writer.SECTION))


def xml_text(path):
    return "\n".join(xml_root(path).xpath('//*[local-name()="t"]/text()'))


def field_value(path, label):
    for row in xml_root(path).xpath('//*[local-name()="tr"]'):
        cells = ["".join(cell.xpath('.//*[local-name()="t"]/text()')) for cell in row]
        if len(cells) == 2 and cells[0] == label:
            return cells[1]
    return None


class HwpxV15Tests(unittest.TestCase):
    def export(self, result):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        original = deepcopy(result)
        documents = writer.export_documents(result, folder.name)
        self.assertEqual(documents["status"], "완료", documents)
        self.assertEqual(documents["expected_files"], len(result["reviewers"]) + 1)
        d.validate_documents(documents, result["reviewers"])
        d.validate_result(result | {"documents": documents})
        self.assertEqual(result, original)
        return documents

    def test_methods_one_three_keep_common_facts_and_separate_agent_opinions(self):
        for method in ("impact", "checklist"):
            for count in (1, 3):
                with self.subTest(method=method, count=count):
                    result = sample_result(method, count)
                    documents = self.export(result)
                    for index, record in enumerate(documents["files"][:-1]):
                        text = xml_text(record["path"])
                        self.assertIn(f"개인의견 고유문구 {index + 1}", text)
                        self.assertIn(f"개인 고시의견 {index + 1}", text)
                        self.assertNotIn("종합의견 고유문구", text)
                        for other in range(count):
                            if other != index:
                                self.assertNotIn(f"개인의견 고유문구 {other + 1}", text)
                                self.assertNotIn(f"개인 고시의견 {other + 1}", text)
                        self.assertIn('첫 문단 <자료> & "인용"', text)
                        for item in d.ITEM_NAMES:
                            self.assertIn(item, text)
                        self.assertIn(d.PERSONAS[index], text)
                    summary = xml_text(documents["files"][-1]["path"])
                    self.assertIn("종합의견 고유문구", summary)
                    self.assertIn("의견차이", summary)
                    for index in range(count):
                        self.assertIn(f"개인의견 고유문구 {index + 1}", summary)
                        self.assertIn(f"개인 고시의견 {index + 1}", summary)

    def test_checklist_has_no_scores_or_weights(self):
        for record in self.export(sample_result("checklist"))["files"]:
            text = xml_text(record["path"])
            self.assertIn("수치 해당 없음", text)
            for label in ("개인 점수", "가중치", "영향 점수", "에이전트 종합평균"):
                self.assertNotIn(label, text)

    def test_raw_selected_weights_and_scores_and_domain_display_are_preserved(self):
        result = sample_result(count=1)
        names = list(d.ITEM_NAMES[:4])
        result.update(selected_items=names, weights=dict(zip(names, (1.2, 1.1, .9, .8))))
        reviewer = result["reviewers"][0]
        reviewer.update(scores=dict(zip(names, (5, 4, 3, 3))), reviewer_score=3.875)
        result.update(overall_avg=3.875)
        d.validate_result(result)
        documents = self.export(result)
        for record in documents["files"]:
            self.assertEqual(field_value(record["path"], "개인 점수"), d.format_score(3.875))
            text = xml_text(record["path"])
            for weight in ("1.2", "1.1", "0.9", "0.8"):
                self.assertIn(weight, text)
            self.assertIn("영향 점수: 5", text)
            self.assertIn("영향 점수: 3", text)

    def test_all_four_family_scope_sources_and_full_manifest_are_retained(self):
        result = sample_result(count=1)
        for record in self.export(result)["files"]:
            text = xml_text(record["path"])
            for family in result["notice_review"]["families"]:
                self.assertIn(family["family"], text)
                for excluded in family["excluded"]:
                    self.assertIn(excluded["clause_id"], text)
                    self.assertIn(excluded["reason"], text)
            for source in result["notice_review"]["sources"]:
                for value in source.values():
                    if isinstance(value, str) and value:
                        self.assertIn(value, text)
            self.assertIn(result["catalogue_fingerprint"], text)
            self.assertIn("정확성 보증", text)

    def test_both_methods_one_three_agents_keep_all_four_family_candidates_and_citations(self):
        for method in ("impact", "checklist"):
            for count in (1, 3):
                with self.subTest(method=method, count=count):
                    result = all_family_result(method, count)
                    for record in self.export(result)["files"]:
                        text = xml_text(record["path"])
                        for clause in result["notice_review"]["clause_snapshots"]:
                            for key in ("clause_id", "source_id", "source_anchor", "title", "text"):
                                self.assertIn(clause[key], text)
                        for comparison in result["notice_review"]["comparisons"]:
                            self.assertIn(comparison["comparison_id"], text)
                            self.assertIn(comparison["rationale"], text)
                        for fact in result["notice_review"]["facts"]:
                            for key in ("fact_id", "source_field", "quote", "value_text", "number", "unit"):
                                self.assertIn(fact[key], text)
                            self.assertEqual(field_value(record["path"], "인용 위치(start, end)"),
                                f"{fact['start']}, {fact['end']}")
                        self.assertIn(result["task_fingerprint"], text)
                        self.assertIn(result["options_fingerprint"], text)
                        indices = range(count) if record["kind"] == "summary" else [int(record["reviewer_id"].split("-")[-1]) - 1]
                        for index in indices:
                            for comment in result["reviewers"][index]["notice_comments"]:
                                self.assertIn(comment["comment"], text)

    def test_candidate_and_transitive_note_exception_texts_are_not_lost(self):
        result = sample_result(count=1)
        notice = result["notice_review"]
        candidate = notice["clause_snapshots"][0]
        core = candidate | {"clause_id": "core:1", "family": "core", "source_id": "synthetic-core",
            "text": "연결 주석 전체원문 & <예외> 보존", "qualifier_refs": ["dual_use:1"]}
        dual = candidate | {"clause_id": "dual_use:1", "family": "dual_use", "source_id": "synthetic-dual_use",
            "text": "전이적 예외·정의 원문 마지막글자終", "qualifier_refs": []}
        candidate["qualifier_refs"] = ["core:1"]
        notice["clause_snapshots"].extend((deepcopy(core), deepcopy(dual)))
        rebind_notice(result)
        for record in self.export(result)["files"]:
            text = xml_text(record["path"])
            self.assertIn(core["text"], text)
            self.assertIn(dual["text"], text)
            self.assertIn("합성 제1항", text)
            self.assertIn("속도 10 GHz 이상", text)
            self.assertIn("속도 20 GHz", text)
            self.assertIn("fact-1", text)
            self.assertIn("현재 기술사양", text)
            self.assertIn("20 GHz", text)

    def test_target_satisfied_and_partially_satisfied_wording_is_conditional(self):
        for partial, phrase in ((False, "목표 달성 시 해당 가능성"),
                                (True, "목표 조건 일부 충족·추가 확인")):
            result = target_result(partial)
            for record in self.export(result)["files"]:
                text = xml_text(record["path"])
                self.assertIn(phrase, text)
                self.assertIn("속도 30 GHz", text)
                self.assertIn("목표 수치 대조", text)
                self.assertNotIn("현재 확보", text)
                self.assertNotIn("공식 비해당", text)
                self.assertNotIn("지정 확정", text)
                if partial:
                    self.assertIn("target 적용범위 자료를 제공해 주세요", text)
                    self.assertEqual(field_value(record["path"], "AI 종합 참고 등급") if record["kind"] == "summary" else "", "")

    def test_no_automatic_candidates_is_explicit_and_not_an_official_exclusion(self):
        result = sample_result(count=1)
        notice = result["notice_review"]
        notice.update(clause_snapshots=[], comparisons=[])
        notice["families"][0].update(candidate_ids=[], excluded=[{"clause_id": "advanced:1", "reason": "합성 분야 무관"}])
        result["reviewers"][0]["notice_comments"] = []
        rebind_notice(result)
        for record in self.export(result)["files"]:
            self.assertIn("후보 없음(자동 탐색)", xml_text(record["path"]))

    def test_excluded_task_generates_only_summary_notice(self):
        result = sample_result(count=1)
        result.update(status="후보제외", reviewers=[], final_grade=None, selected_items=[], weights={},
            overall_avg=None, rule_grade=None,
            candidate={"is_candidate": False, "reason": "후보 제외 합성 근거", "uncertainty": ""})
        result["documents"]["expected_files"] = 1
        d.validate_result(result)
        documents = self.export(result)
        self.assertEqual(len(documents["files"]), 1)
        self.assertEqual(documents["files"][0]["kind"], "summary")
        text = xml_text(documents["files"][0]["path"])
        self.assertIn("후보 제외 합성 근거", text)
        self.assertIn("개별 평가 미실시", text)
        self.assertNotIn("reviewer-1", text)

    def test_incomplete_and_error_leave_final_grade_blank_and_keep_reasons(self):
        for error in (False, True):
            result = sample_result()
            result.update(status="오류" if error else "검토필요", final_grade=None,
                overall_avg=None, rule_grade=None, unresolved_reasons=["합성 추가 자료 부족"])
            result["reviewers"][1].update(status="검토필요", grade=None, reviewer_score=None,
                unresolved_reasons=["개인 추가 자료 부족"])
            if error:
                result["notice_review"].update(status="error", blocking_reasons=["합성 기준처리 오류"])
            d.validate_result(result)
            documents = self.export(result)
            individual = documents["files"][1]["path"]
            self.assertNotIn("☑", xml_text(individual))
            self.assertIn("개인 추가 자료 부족", xml_text(individual))
            summary = documents["files"][-1]["path"]
            self.assertEqual(field_value(summary, "AI 종합 참고 등급"), "")
            self.assertEqual(field_value(summary, "에이전트 종합평균"), "")
            self.assertIn("합성 추가 자료 부족", xml_text(summary))
            if error:
                self.assertIn("합성 기준처리 오류", xml_text(summary))

    def test_submission_fields_remain_empty_and_ai_reference_is_identified(self):
        for record in self.export(sample_result())["files"]:
            text = xml_text(record["path"])
            self.assertIn("AI 에이전트 검토", text)
            self.assertIn("AI가 생성한 분석·참고 의견", text)
            for label in ("실제 제출일시", "평가위원 이름 / 서명", "간사 확인"):
                self.assertEqual(field_value(record["path"], label), "")
            for misleading in ("가상위원", "가상 위원", "위원회 종합 토론"):
                self.assertNotIn(misleading, text)

    def test_saved_data_only_no_live_catalogue_or_model_calls(self):
        catalogue = types.ModuleType("notice_catalog_v15")
        catalogue.load_catalogue = Mock(side_effect=AssertionError("live load forbidden"))
        engine = types.ModuleType("classification_v15")
        engine.classify_task = Mock(side_effect=AssertionError("model forbidden"))
        client = types.ModuleType("llm_client_v15")
        client.ask_json = Mock(side_effect=AssertionError("model forbidden"))
        with patch.dict(sys.modules, notice_catalog_v15=catalogue, classification_v15=engine, llm_client_v15=client):
            self.export(sample_result(count=1))
        catalogue.load_catalogue.assert_not_called()
        engine.classify_task.assert_not_called()
        client.ask_json.assert_not_called()

    def test_reload_and_past_saved_replay_never_import_runtime_or_read_current_catalogue(self):
        saved = json.loads(json.dumps(all_family_result(count=1)))
        real_import = builtins.__import__
        forbidden = ("notice_catalog", "classification", "credential", "llm_client", "embedded_key")
        imports = []
        def guarded_import(name, *args, **kwargs):
            imports.append(name)
            if any(token in name for token in forbidden):
                raise AssertionError("runtime import forbidden")
            return real_import(name, *args, **kwargs)
        no_current_read = AssertionError("current catalogue read forbidden")
        with patch.object(builtins, "__import__", side_effect=guarded_import), \
                patch.object(Path, "read_text", side_effect=no_current_read), \
                patch.object(Path, "read_bytes", side_effect=no_current_read):
            importlib.reload(writer)
            self.export(saved)
        self.assertFalse(any(any(token in name for token in forbidden) for name in imports))

    def test_tampered_snapshot_score_conditions_and_extra_secret_keys_rejected_before_writes(self):
        changes = (lambda r: r["task_snapshot"].update(연구내용="변조"),
            lambda r: r["notice_review"]["clause_snapshots"][0].update(text="변조"),
            lambda r: r["notice_review"]["comparisons"][0]["conditions"][0].update(normalized_value="999"),
            lambda r: r["reviewers"][0].update(reviewer_score=5.0),
            lambda r: r.update(api_key="SENTINEL_SECRET"))
        for change in changes:
            result = sample_result(count=1)
            change(result)
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError) as raised:
                    writer.export_documents(result, folder)
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_tampered_manifest_fact_quote_anchor_and_comment_identity_fail_before_writes(self):
        changes = (
            lambda r: r["notice_review"]["catalogue_manifest"]["sources"][0].update(sha256="f" * 64),
            lambda r: r["notice_review"]["facts"][0].update(quote="속도 99 GHz"),
            lambda r: r["notice_review"]["facts"][0].update(start=1),
            lambda r: r["notice_review"]["comparisons"][0]["conditions"][0].update(source_anchor="변조"),
            lambda r: r["reviewers"][0]["notice_comments"][0].update(comparison_id="0" * 64),
        )
        for change in changes:
            result = sample_result(count=1)
            change(result)
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    writer.export_documents(result, folder)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_invalid_saved_criteria_links_rejected_before_export_or_regeneration_writes(self):
        from batch_v15 import regenerate_documents

        original = sample_result(count=1)
        link = json.loads(original["criteria"][1]["matched_reference"])[0]
        mutations = ("", "[]", "[invalid", json.dumps(link),
            json.dumps([link | {"source_id": "unknown"}]),
            json.dumps([link | {"comparison_id": "unknown"}]),
            json.dumps([link, link]), json.dumps([link | {"extra": True}]),
            '[{"comparison_id":"unknown","comparison_id":' + json.dumps(link["comparison_id"])
                + ',"source_id":' + json.dumps(link["source_id"]) + '}]')
        for reference in mutations:
            result = deepcopy(original)
            result["criteria"][1]["matched_reference"] = reference
            for export in (writer.export_documents, regenerate_documents):
                with self.subTest(reference=reference, export=export.__name__), tempfile.TemporaryDirectory() as folder:
                    absent = Path(folder) / "must-remain-absent"
                    with self.assertRaises(ValueError):
                        export(result, absent)
                    self.assertFalse(absent.exists())
                    self.assertEqual(list(Path(folder).iterdir()), [])

    def test_actual_saved_engine_result_replays_with_no_model_or_current_catalogue_calls(self):
        import classification_v15 as engine
        import notice_catalogue_v15 as catalogue_module
        from batch_v15 import regenerate_documents
        from test_v15_engine import Client, TASK
        from test_v15_notice_review import catalogue

        client = Client(candidates=("advanced:1",))
        result = engine.classify_task(TASK, {"num_reviewers": 1}, client, catalogue=catalogue())
        self.assertEqual(result["status"], "완료")
        saved = json.loads(json.dumps(result))
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(client, "ask_json", side_effect=AssertionError("model call forbidden")) as ask, \
                patch.object(engine, "classify_task", side_effect=AssertionError("model call forbidden")) as classify, \
                patch.object(catalogue_module, "load_catalogue", side_effect=AssertionError("current catalogue forbidden")) as load:
            documents = writer.export_documents(saved, Path(folder) / "direct")
            regenerated = regenerate_documents(saved, Path(folder) / "replay")
            self.assertEqual(documents["status"], "완료")
            self.assertEqual(regenerated["documents"]["status"], "완료")
            self.assertEqual(saved, result)
            d.validate_result(regenerated)
            ask.assert_not_called()
            classify.assert_not_called()
            load.assert_not_called()

    def test_long_individual_comments_questions_and_source_metadata_continue_without_loss(self):
        result = target_result(partial=True)
        marker = '한글 <조건> & "설명" 𝄞 終' * 250 + "보존끝"
        result["reviewers"][0]["rationale"] = "개인근거 " + marker
        result["reviewers"][0]["discussion_points"] = "개인토론 " + marker
        result["notice_review"]["sources"][0]["review_note"] = "출처메모 " + marker
        comparison = result["notice_review"]["comparisons"][0]
        comparison["conditions"][0]["reason"] = "조건근거 " + marker
        comparison["missing_information"][0]["question"] = "추가질문 " + marker
        rebind_notice(result)
        result["reviewers"][0]["notice_comments"][0]["comment"] = "개인고시 " + marker
        result["discussion_points"] = "종합차이 " + marker
        for record in self.export(result)["files"]:
            root = xml_root(record["path"])
            # Consecutive short rows retain the complete character sequence.
            plain = "".join(root.xpath('//*[local-name()="t"]/text()'))
            for prefix in ("개인근거 ", "개인토론 ", "출처메모 ", "조건근거 ", "추가질문 ", "개인고시 "):
                self.assertIn(prefix + marker, plain)
            if record["kind"] == "summary":
                self.assertIn("종합차이 " + marker, plain)
            else:
                self.assertNotIn("종합차이 ", plain)
            self.assertTrue(all(len(value) <= writer.CHUNK_SIZE for value in root.xpath('//*[local-name()="t"]/text()')))

    def test_unavailable_catalogue_stays_incomplete_with_four_unprocessed_families(self):
        opts = d.normalize_options()
        result = d.make_result({"과제명": "합성 기준본 미제공"}, opts)
        result.update(status="검토필요", unresolved_reasons=["합성 기준본 미제공"])
        result["notice_review"]["blocking_reasons"] = ["합성 기준본 미제공"]
        documents = self.export(result)
        self.assertEqual(len(documents["files"]), 1)
        text = xml_text(documents["files"][0]["path"])
        self.assertIn("저장 기준본 미제공", text)
        self.assertNotIn("후보 없음(자동 탐색)", text)
        for family in d.FAMILIES:
            self.assertIn(family, text)
        self.assertEqual(field_value(documents["files"][0]["path"], "AI 종합 참고 등급"), "")

    def test_family_processing_errors_and_partial_scope_remain_visible(self):
        result = sample_result(count=1)
        notice = result["notice_review"]
        notice.update(status="error", blocking_reasons=["고시 전체 처리 미완료"])
        notice["families"][1].update(status="error", errors=["core 계열 합성 처리 실패"])
        notice["families"][2].update(status="partial")
        result.update(status="오류", final_grade=None, unresolved_reasons=["계열별 처리 재확인"])
        for record in self.export(result)["files"]:
            text = xml_text(record["path"])
            for phrase in ("core 계열 합성 처리 실패", "고시 전체 처리 미완료", "partial"):
                self.assertIn(phrase, text)

    def test_long_text_many_rows_xml_styles_ids_page_flow_and_character_preservation(self):
        result = sample_result(count=1)
        long_value = '긴한글 <원문> & "인용" 𝄞 終.' * 1200 + "마지막확인終"
        result["task_snapshot"]["연구내용"] = long_value + "\n\n끝문단"
        result["reviewers"][0]["item_reviews"][0]["note"] = long_value
        result["notice_review"]["clause_snapshots"][0]["text"] += long_value
        rebind_notice(result)
        for record in self.export(result)["files"]:
            with ZipFile(BytesIO(Path(record["path"]).read_bytes())) as z:
                self.assertEqual(z.infolist()[0].filename, "mimetype")
                self.assertEqual(z.infolist()[0].compress_type, ZIP_STORED)
                self.assertEqual(z.read("mimetype"), b"application/hwp+zip")
                self.assertIsNone(z.testzip())
                names = set(z.namelist())
                self.assertFalse(any(n.startswith(("BinData/", "Preview/")) for n in names))
                roots = {n: E.fromstring(z.read(n)) for n in names if n.endswith((".xml", ".hpf"))}
                section, header = roots[writer.SECTION], roots["Contents/header.xml"]
                self.assertFalse(section.xpath('//*[local-name()="linesegarray" or local-name()="pic" or local-name()="footer" or local-name()="header"]'))
                ids = section.xpath('//*[local-name()="p"]/@id')
                self.assertEqual(len(ids), len(set(ids)))
                table_ids = section.xpath('//*[local-name()="tbl"]/@id')
                self.assertEqual(len(table_ids), len(set(table_ids)))
                for table in section.xpath('//*[local-name()="tbl"]'):
                    rows = table.xpath('./*[local-name()="tr"]')
                    self.assertEqual(int(table.get("rowCnt")), len(rows))
                    self.assertGreater(len(rows), 150)
                    self.assertEqual(table.get("pageBreak"), "CELL")
                    for row_index, row in enumerate(rows):
                        col = 0
                        for cell in row:
                            self.assertEqual(int(cell.find(f"{{{writer.HP}}}cellAddr").get("rowAddr")), row_index)
                            self.assertEqual(int(cell.find(f"{{{writer.HP}}}cellAddr").get("colAddr")), col)
                            col += int(cell.find(f"{{{writer.HP}}}cellSpan").get("colSpan"))
                            self.assertEqual(cell.find(f"{{{writer.HP}}}cellSz").get("height"), "0")
                            self.assertTrue(all(len(t) <= 400 for t in cell.xpath('.//*[local-name()="t"]/text()')))
                        self.assertEqual(col, 4)
                for attr, tag in (("paraPrIDRef", "paraPr"), ("charPrIDRef", "charPr"), ("styleIDRef", "style"), ("borderFillIDRef", "borderFill"), ("tabPrIDRef", "tabPr")):
                    style_ids = set(header.xpath(f'//*[local-name()="{tag}"]/@id'))
                    for root in (section, header):
                        self.assertTrue(set(root.xpath(f'//@{attr}')) <= style_ids, attr)
                manifest = roots["Contents/content.hpf"]
                for item in manifest.xpath('//*[local-name()="manifest"]/*'):
                    self.assertIn(item.get("href"), names)
                spine = manifest.xpath('//*[local-name()="spine"]/*')
                self.assertEqual([item.get("idref") for item in spine], ["header", "section0"])
                plain = "".join(section.xpath('//*[local-name()="t"]/text()'))
                self.assertGreaterEqual(plain.count(long_value), 3)
                self.assertIn("마지막확인終", plain)

    def test_chunking_keeps_empty_paragraphs_and_exact_characters(self):
        text = "한글 & <xml> 𝄞 " * 150
        self.assertEqual("".join(writer._chunks(text)), text)
        self.assertEqual(list(writer._chunks("첫째\n\n셋째\n")), ["첫째", "", "셋째", ""])

    def test_templates_are_v15_isolated_and_have_no_sensitive_residue(self):
        self.assertEqual(writer.TEMPLATE_DIR.name, "v15")
        for name in ("reviewer_opinion.hwpx", "committee_summary.hwpx"):
            with ZipFile(writer.TEMPLATE_DIR / name) as z:
                content = " ".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith((".xml", ".hpf")))
                for residue in ("북극", "인메모리", "서00", "장00", "KISTEP", "test chip"):
                    self.assertNotIn(residue, content)

    def test_filenames_contain_task_fingerprint_identity_and_never_collide(self):
        result = sample_result()
        original = deepcopy(result)
        with tempfile.TemporaryDirectory() as folder:
            first = writer.export_documents(result, folder)
            before = {record["path"]: Path(record["path"]).read_bytes() for record in first["files"]}
            second = writer.export_documents(result, folder)
            paths = [record["path"] for docs in (first, second) for record in docs["files"]]
            self.assertEqual(len(set(paths)), 8)
            for record in first["files"] + second["files"]:
                self.assertIn(result["task_fingerprint"][:12], Path(record["path"]).name)
                if record["reviewer_id"]:
                    self.assertIn(record["reviewer_id"], Path(record["path"]).name)
            for path, data in before.items():
                self.assertEqual(Path(path).read_bytes(), data)
        self.assertEqual(result, original)

    def test_individual_failure_attempts_all_files_and_safe_errors_preserve_dto(self):
        original_write = writer._write_document
        calls = []
        def failing(result, reviewer, path):
            calls.append(reviewer)
            if len(calls) == 1:
                raise OSError("SENTINEL_SECRET")
            return original_write(result, reviewer, path)
        result = sample_result()
        original = deepcopy(result)
        with tempfile.TemporaryDirectory() as folder, patch.object(writer, "_write_document", side_effect=failing):
            documents = writer.export_documents(result, folder)
            self.assertEqual(documents["status"], "일부실패")
            self.assertEqual(len(calls), 4)
            self.assertEqual([r["status"] for r in documents["files"]], ["오류", "완료", "완료", "완료"])
            self.assertEqual(len(list(Path(folder).rglob("*.hwpx"))), 3)
            self.assertEqual(list(Path(folder).rglob("*.tmp")), [])
            self.assertNotIn("SENTINEL_SECRET", json.dumps(documents))
            d.validate_documents(documents, result["reviewers"])
        self.assertEqual(result, original)

    def test_bad_output_directory_reports_every_expected_failure(self):
        result = sample_result()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "occupied"
            target.write_text("existing", encoding="utf-8")
            documents = writer.export_documents(result, target)
            self.assertEqual(documents["status"], "실패")
            self.assertEqual(len(documents["files"]), 4)
            self.assertTrue(all(record["status"] == "오류" for record in documents["files"]))
            self.assertEqual(target.read_text(encoding="utf-8"), "existing")
            d.validate_documents(documents, result["reviewers"])

    def test_atomic_replace_failure_keeps_existing_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.hwpx"
            target.write_bytes(b"previous complete file")
            with patch.object(writer.os, "replace", side_effect=OSError("SENTINEL_SECRET")):
                with self.assertRaises(OSError):
                    writer._write_document(sample_result(count=1), None, target)
            self.assertEqual(target.read_bytes(), b"previous complete file")
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_atomic_zip_failure_keeps_existing_file_and_cleans_temporary(self):
        original_write = ZipFile.writestr
        def failing_write(archive, name, data, *args, **kwargs):
            if name == "Contents/header.xml":
                raise OSError("SENTINEL_SECRET")
            return original_write(archive, name, data, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.hwpx"
            target.write_bytes(b"previous complete file")
            with patch.object(ZipFile, "writestr", new=failing_write):
                with self.assertRaises(OSError):
                    writer._write_document(sample_result(count=1), None, target)
            self.assertEqual(target.read_bytes(), b"previous complete file")
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_summary_failure_retains_successful_individual_documents(self):
        original_write = writer._write_document
        def fail_summary(result, reviewer, path):
            if reviewer is None:
                raise OSError("SENTINEL_SECRET")
            return original_write(result, reviewer, path)
        result = sample_result()
        with tempfile.TemporaryDirectory() as folder, patch.object(writer, "_write_document", side_effect=fail_summary):
            documents = writer.export_documents(result, folder)
            self.assertEqual(documents["status"], "일부실패")
            self.assertEqual([entry["status"] for entry in documents["files"]], ["완료"] * 3 + ["오류"])
            self.assertTrue(all(Path(entry["path"]).is_file() for entry in documents["files"][:-1]))
            self.assertNotIn("SENTINEL_SECRET", json.dumps(documents))
            d.validate_documents(documents, result["reviewers"])

    def test_invalid_xml_characters_report_safe_failures_instead_of_dropping_content(self):
        result = sample_result(count=1)
        result["task_snapshot"]["연구내용"] = "합성 원문\x00제어문자"
        result["task_fingerprint"] = d.task_fingerprint(result["task_snapshot"])
        d.validate_result(result)
        with tempfile.TemporaryDirectory() as folder:
            documents = writer.export_documents(result, folder)
            self.assertEqual(documents["status"], "실패")
            self.assertEqual(len(documents["errors"]), 2)
            self.assertEqual(list(Path(folder).rglob("*.hwpx")), [])
            self.assertEqual(list(Path(folder).rglob("*.tmp")), [])
            self.assertNotIn("제어문자", json.dumps(documents, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
