"""Offline HWPX regression checks; native Hangul visual QA is a separate gate."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_STORED
from lxml import etree as E

import hwpx_writer as writer
from v14_domain import ITEM_NAMES, make_result, make_reviewer


def sample_result(method="impact", count=3, long=False):
    task = {"세부사업명": "합성 사업", "과제명": "합성 과제 <검증> & 인용 \"한국어\"",
            "연구목표": "안전한 연구목표", "연구내용": "첫 문단\n둘째 문단", "기대효과": "합성 효과",
            "추가 검토정보": "추가 증거", "부처 세부기준": "합성 세부기준"}
    if long:
        task["과제명"] += " 긴 과제명" * 80
        task["연구내용"] = "\n\n".join(["유출 영향 검토 <자료> & 원문 보존. " * 60] * 4)
    result = make_result(task, {"method": method, "num_reviewers": count})
    result.update(status="완료", selected_items=list(ITEM_NAMES), weights={x: 1.0 for x in ITEM_NAMES},
                  overall_avg=3.0 if method == "impact" else None,
                  rule_grade="일반과제" if method == "impact" else None,
                  final_grade="민감과제", confidence="낮음", rationale="종합의견 고유문구",
                  discussion_points="종합토론", unresolved_reasons=["전문 검토 필요"])
    if method == "checklist":
        result["weights"] = {}
    for index in range(count):
        persona = ("AI 기술분야 전문가", "AI 연구보안 전문가", "AI 기술사업화 전문가")[index]
        reviewer = make_reviewer(f"reviewer-{index + 1}", persona)
        reviewer.update(status="완료", grade=("일반과제", "민감과제", "보안과제")[index], confidence="보통",
                        rationale=f"개인의견 고유문구 {index + 1}", discussion_points=f"개인토론 {index + 1}",
                        item_reviews=[{"item": x, "level": "일부", "note": f"에이전트 {index + 1} 검토정보 {x}" + ("\n긴 근거 & <표현> " * 140 if long else ""),
                                       "law_refs": ["제45조제1항제3호"]} for x in ITEM_NAMES],
                        scores={x: index + 2 for x in ITEM_NAMES} if method == "impact" else {},
                        reviewer_score=index + 2 if method == "impact" else None)
        result["reviewers"].append(reviewer)
    return result


def xml_text(path):
    with ZipFile(path) as z:
        section = E.fromstring(z.read("Contents/section0.xml"))
        return "\n".join(section.xpath('//*[local-name()="t"]/text()'))


def field_value(path, label):
    with ZipFile(path) as z:
        section = E.fromstring(z.read("Contents/section0.xml"))
        for row in section.xpath('//*[local-name()="tr"]'):
            if len(row) == 2 and "".join(row[0].xpath('.//*[local-name()="t"]/text()')) == label:
                return "".join(row[1].xpath('.//*[local-name()="t"]/text()'))
    raise AssertionError(f"Missing field: {label}")


class HwpxTests(unittest.TestCase):
    def export(self, result):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        docs = writer.export_documents(result, folder.name)
        self.assertEqual(docs["status"], "완료", docs)
        self.assertEqual(docs["expected_files"], len(result["reviewers"]) + 1)
        self.assertEqual(len(docs["files"]), docs["expected_files"])
        return docs

    def test_methods_one_and_three_preserve_individual_opinions(self):
        for method in ("impact", "checklist"):
            for count in (1, 3):
                with self.subTest(method=method, count=count):
                    docs = self.export(sample_result(method, count))
                    for index, record in enumerate(docs["files"][:-1]):
                        text = xml_text(record["path"])
                        self.assertIn(f"개인의견 고유문구 {index + 1}", text)
                        self.assertNotIn("종합의견 고유문구", text)
                        self.assertIn("AI가 생성한", text)
                        self.assertIn("AI 에이전트", text)
                        self.assertIn("실제 제출일시", text)
                        self.assertIn("간사 확인", text)
                        for item in ITEM_NAMES:
                            self.assertIn(item, text)
                        if method == "checklist":
                            self.assertIn("수치 해당 없음", text)
                            self.assertNotIn("에이전트 종합평균", text)
                    summary = xml_text(docs["files"][-1]["path"])
                    self.assertIn("종합의견 고유문구", summary)
                    for index in range(count):
                        self.assertIn(f"개인의견 고유문구 {index + 1}", summary)
                    if method == "impact":
                        self.assertIn("구간 불일치", summary)

    def test_incomplete_preserves_notes_and_leaves_grade_unselected(self):
        result = sample_result()
        result.update(status="검토필요", overall_avg=None, final_grade=None)
        result["reviewers"][1].update(status="검토필요", grade=None, reviewer_score=None,
                                      unresolved_reasons=["추가 자료 부족"])
        docs = self.export(result)
        text = xml_text(docs["files"][1]["path"])
        self.assertIn("미완료", text)
        self.assertIn("추가 자료 부족", text)
        self.assertIn("에이전트 2 검토정보", text)
        self.assertNotIn("☑", text)
        self.assertNotIn("에이전트 종합평균: 3", xml_text(docs["files"][-1]["path"]))

    def test_excluded_generates_only_summary_without_fake_people(self):
        result = sample_result()
        result.update(status="후보제외", reviewers=[], final_grade=None,
                      candidate={"is_candidate": False, "reason": "후보 제외 합성 근거", "uncertainty": ""})
        docs = self.export(result)
        self.assertEqual(len(docs["files"]), 1)
        text = xml_text(docs["files"][0]["path"])
        self.assertIn("후보 제외 합성 근거", text)
        self.assertIn("개별 평가 미실시", text)
        self.assertNotIn("reviewer-1", text)

    def test_no_mutation_no_overwrite_and_collision_safe_filenames(self):
        result = sample_result()
        for reviewer, name in zip(result["reviewers"], ("A/B", "A:B", "A\\B")):
            reviewer["reviewer_id"] = name
        original = copy.deepcopy(result)
        with tempfile.TemporaryDirectory() as folder:
            first = writer.export_documents(result, folder)
            second = writer.export_documents(result, folder)
            paths = [x["path"] for docs in (first, second) for x in docs["files"]]
            self.assertEqual(len(set(paths)), 8)
            for path in paths:
                self.assertTrue(Path(path).is_file())
                self.assertLessEqual(len(Path(path).name), 110)
        self.assertEqual(result, original)

    def test_package_references_and_long_text_flow(self):
        result = sample_result(long=True)
        docs = self.export(result)
        for record in docs["files"]:
            with ZipFile(record["path"]) as z:
                self.assertEqual(z.infolist()[0].filename, "mimetype")
                self.assertEqual(z.infolist()[0].compress_type, ZIP_STORED)
                self.assertEqual(z.read("mimetype"), b"application/hwp+zip")
                self.assertIsNone(z.testzip())
                names = set(z.namelist())
                self.assertFalse(any(n.startswith(("BinData/", "Preview/")) for n in names))
                roots = {n: E.fromstring(z.read(n)) for n in names if n.endswith((".xml", ".hpf"))}
                section = roots["Contents/section0.xml"]
                header = roots["Contents/header.xml"]
                self.assertFalse(section.xpath('//*[local-name()="linesegarray" or local-name()="pic" or local-name()="footer" or local-name()="header"]'))
                for tbl in section.xpath('//*[local-name()="tbl"]'):
                    rows = tbl.xpath('./*[local-name()="tr"]')
                    self.assertEqual(int(tbl.get("rowCnt")), len(rows))
                    self.assertEqual(tbl.get("pageBreak"), "CELL")
                    for rowindex, row in enumerate(rows):
                        spans = 0
                        for cell in row:
                            addr = cell.find(f"{{{writer.HP}}}cellAddr")
                            self.assertEqual(int(addr.get("rowAddr")), rowindex)
                            spans += int(cell.find(f"{{{writer.HP}}}cellSpan").get("colSpan"))
                            self.assertTrue(all(len(t) <= 500 for t in cell.xpath('.//*[local-name()="t"]/text()')))
                        self.assertEqual(spans, 4)
                for attr, tag in (("paraPrIDRef", "paraPr"), ("charPrIDRef", "charPr"), ("styleIDRef", "style"), ("borderFillIDRef", "borderFill"), ("tabPrIDRef", "tabPr")):
                    ids = set(header.xpath(f'//*[local-name()="{tag}"]/@id'))
                    for root in (section, header):
                        self.assertTrue(set(root.xpath(f'//@{attr}')) <= ids, (attr, ids))
                for item in roots["Contents/content.hpf"].xpath('//*[local-name()="manifest"]/*'):
                    self.assertIn(item.get("href"), names)
                # Hangul discovers the style header through the spine too.
                spine = roots["Contents/content.hpf"].xpath('//*[local-name()="spine"]/*')
                self.assertEqual([item.get("idref") for item in spine], ["header", "section0"])
                self.assertEqual(spine[0].get("linear"), "yes")
                text = xml_text(record["path"])
                self.assertIn('합성 과제 <검증> & 인용 "한국어"', text)
                self.assertIn("유출 영향 검토", text)
                self.assertIn("긴 근거 & <표현>", text)
                for residue in ("북극", "인메모리", "서00", "장00", "KISTEP", "test chip"):
                    self.assertNotIn(residue, " ".join(z.read(n).decode("utf-8") for n in names if n.endswith((".xml", ".hpf"))))

    def test_individual_failure_still_attempts_remaining_files(self):
        original = writer._write_document
        calls = []
        def failing(result, reviewer, path):
            calls.append(reviewer)
            if len(calls) == 1:
                raise OSError("synthetic failure")
            return original(result, reviewer, path)
        with tempfile.TemporaryDirectory() as folder, patch.object(writer, "_write_document", side_effect=failing):
            result = sample_result()
            docs = writer.export_documents(result, folder)
            self.assertEqual(docs["status"], "일부실패")
            self.assertEqual(len(calls), 4)
            self.assertEqual([x["status"] for x in docs["files"]], ["오류", "완료", "완료", "완료"])
            self.assertEqual(result["status"], "완료")
            self.assertEqual(len(list(Path(folder).rglob("*.hwpx"))), 3)
            self.assertEqual(list(Path(folder).rglob("*.tmp")), [])

    def test_bad_output_directory_returns_all_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "file"
            target.write_text("occupied", encoding="utf-8")
            docs = writer.export_documents(sample_result(), target)
            self.assertEqual(docs["status"], "실패")
            self.assertEqual(len(docs["files"]), 4)
            self.assertTrue(all(x["status"] == "오류" for x in docs["files"]))

    def test_atomic_failure_keeps_previous_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.hwpx"
            target.write_bytes(b"previous complete file")
            with patch.object(writer.os, "replace", side_effect=OSError("SENTINEL_SECRET")):
                with self.assertRaises(OSError):
                    writer._write_document(sample_result(), None, target)
            self.assertEqual(target.read_bytes(), b"previous complete file")
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_raw_errors_are_not_copied_to_document_status(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(writer, "_write_document", side_effect=ValueError("SENTINEL_SECRET")):
            docs = writer.export_documents(sample_result(), folder)
            self.assertEqual(docs["status"], "실패")
            self.assertNotIn("SENTINEL_SECRET", str(docs))

    def test_chunking_preserves_characters_and_empty_paragraphs(self):
        text = "한글 & <xml> " * 150
        self.assertEqual("".join(writer._chunks(text)), text)
        self.assertEqual(list(writer._chunks("첫째\n\n셋째\n")), ["첫째", "", "셋째", ""])

    def test_average_score_display_rounds_without_changing_saved_values(self):
        for raw, expected in ((3.875, "3.88"), (3.4999, "3.4999"), (4.4999, "4.4999")):
            with self.subTest(raw=raw):
                result = sample_result(count=1)
                result["reviewers"][0]["reviewer_score"] = raw
                result["overall_avg"] = raw
                original = copy.deepcopy(result)
                docs = self.export(result)
                individual = docs["files"][0]["path"]
                summary = docs["files"][1]["path"]
                self.assertEqual(field_value(individual, "개인 점수"), expected)
                self.assertEqual(field_value(summary, "개인 점수"), expected)
                self.assertEqual(field_value(summary, "에이전트 종합평균"), expected)
                self.assertEqual(result, original)

    def test_missing_average_scores_stay_blank(self):
        result = sample_result(count=1)
        result.update(status="검토필요", overall_avg=None)
        result["reviewers"][0].update(status="검토필요", reviewer_score=None, grade=None)
        docs = self.export(result)
        for record in docs["files"]:
            self.assertEqual(field_value(record["path"], "개인 점수"), "")
            if record["kind"] == "summary":
                self.assertEqual(field_value(record["path"], "에이전트 종합평균"), "")

    def test_ai_agent_titles_roles_and_human_confirmation_are_distinct(self):
        docs = self.export(sample_result(count=3))
        for index, record in enumerate(docs["files"]):
            text = xml_text(record["path"])
            title = ("AI 에이전트별 보안등급 분류 검토의견서" if record["kind"] == "reviewer"
                     else "AI 보안등급 분류 종합 검토의견서")
            self.assertEqual(text.splitlines()[0], title)
            self.assertIn("추가 검토·논의사항", text)
            self.assertNotIn("가상 위원", text)
            self.assertNotIn("위원회 종합 토론", text)
            self.assertIn("실제 심의 및 보안등급 확정은 담당자", text)
            self.assertEqual(field_value(record["path"], "평가위원 이름 / 서명"), "")
            if record["kind"] == "reviewer":
                self.assertIn("에이전트_", Path(record["path"]).name)
                self.assertIn(("AI 기술분야 전문가", "AI 연구보안 전문가", "AI 기술사업화 전문가")[index], text)


if __name__ == "__main__":
    unittest.main()
