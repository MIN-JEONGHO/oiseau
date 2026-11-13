"""고시 기준본 로더(notice_catalogue) 시험.

두 묶음으로 나뉜다.
- 합성 fixture: 임시 폴더에 작은 가짜 기준본을 만들어 검증 규칙(해시·검수·참조·불변성)을 확인한다.
  fixture 글은 모두 합성이며 실제 과제·실제 고시가 아니다.
- 실제 복사본: 프로그램 폴더의 `resources/notices`(paths.notices_root())를 읽어 지문·건수를 확인한다.
  실행 중 시뮬레이터 폴더는 읽지 않는다. 복사본 파일의 SHA256은 복사본 자신의 manifest와 대조한다.
"""
import ast
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import paths
from notice_catalogue import (
    CatalogueError,
    NOTE_FIELD,
    canonical_hash,
    catalogue_summary,
    clause_index,
    clause_record,
    load_catalogue,
    note_records,
    numeric_leaves,
)

PROGRAM = Path(__file__).resolve().parents[1]
# 시뮬레이터 v17이 읽던 kr-notices-v16-1 기준본의 manifest 정규 해시. 복사본도 같아야 한다.
EXPECTED_FINGERPRINT = "ed1cd61bda96d7e8fb577fd91561407fb5331f15304c5c297ebf150715952d6b"
EXPECTED_CATALOGUE_ID = "kr-notices-v16-1"
# 합성 fixture의 출처는 모두 제목표에 있는 실제 고시번호 하나를 쓴다(본문 출처 1개 규칙 때문).
FIXTURE_NOTICE = "산업통상부고시 제2026-101호"


def fixture_bundle(root):
    """네 범위에 조항 하나씩 둔 합성 기준본을 root 아래에 만든다. 첨단 조항만 숫자 조건이다."""
    clauses = []
    sources = []
    for family in ("advanced", "core", "dual_use", "military"):
        source_id = family + "-source"
        path = "raw/" + family + (".hwpx" if family in ("dual_use", "military") else ".txt")
        (root / path).parent.mkdir(exist_ok=True)
        (root / path).write_text("synthetic public-source fixture", encoding="utf-8")
        digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
        sources.append(dict(
            source_id=source_id, families=[family], title="synthetic", notice_number=FIXTURE_NOTICE,
            announcement_version="test", announcement_date="2025-12-31", effective_date="2026-01-01",
            official_url=f"https://www.law.go.kr/example?flSeq={len(sources) + 1}",
            retrieved_at="2026-10-20T00:00:00+09:00", relative_path=path, sha256=digest,
            review_status="reviewed", coverage="full", review_note="fixture"))
        clause_id = family + ":001"
        anchor = path + "#page=1&row=1"
        condition = dict(type="unsupported", predicate_id=clause_id + ":p1", text="synthetic criterion",
                         source_anchor=anchor, subject="criterion", reason="synthetic")
        if family == "advanced":
            condition = {key: value for key, value in condition.items() if key != "reason"}
            condition.update(type="numeric", operator="ge", threshold="1", unit="nm")
        clauses.append(dict(
            clause_id=clause_id, source_id=source_id, family=family,
            code="SYN-" + family if family in ("dual_use", "military") else "",
            title="synthetic clause", field="test", source_anchor=anchor, text="synthetic criterion",
            qualifier_refs=[], condition=condition))
    (root / "normalized").mkdir()
    (root / "normalized/clauses.json").write_text(json.dumps(clauses, ensure_ascii=False), encoding="utf-8")
    fixture_review(root, sources, clauses)
    files = [dict(relative_path=p.relative_to(root).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
             for p in sorted(root.rglob("*")) if p.is_file()]
    manifest = dict(catalogue_schema_version=1, catalogue_id="synthetic", sources=sources, files=files,
                    clause_inventory=[dict(clause_id=c["clause_id"], family=c["family"], sha256=canonical_hash(c))
                                      for c in clauses])
    save_manifest(root, manifest)
    return manifest, clauses


def fixture_review(root, sources, clauses):
    """실제 검수 기록과 같은 필드 구조를 가진 작은 합성 검수 증빙."""
    def write(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    positions = {}
    audits = {}
    pairs = []
    for clause in clauses:
        family = clause["family"]
        write("extracted/" + family.replace("_", "-") + ".pages.json", [dict(page=1, text="synthetic public source")])
        if family not in ("dual_use", "military"):
            continue
        position = dict(code=clause["code"], root_code=clause["code"], page=1, bbox=[0, 0, 1, 1])
        positions[family] = [position]
        audit = dict(root_code_count=1, code_position_count=1, missing_from_normalized=[], unexpected_normalized=[],
                     checked_boundaries=1, boundary_failures=[], checked_category_transitions=0,
                     category_assignment_failures=[])
        audits[family] = {
            **audit, "independent_source_positions": [position], "paragraph_count": 2,
            "whole_paragraph_assignments": [
                dict(paragraph_id=family + ":" + language, owner=clause["clause_id"], language=language,
                     source_anchor=clause["source_anchor"],
                     text_sha256=hashlib.sha256(clause["text"].encode()).hexdigest())
                for language in ("ko", "en")],
            "whole_paragraph_assignment_failures": []}
        source = next(s for s in sources if s["source_id"] == clause["source_id"])
        pdf_path = "raw/" + family + ".pdf"
        pdf_url = source["official_url"] + "00"
        (root / pdf_path).write_text("synthetic paired public source", encoding="utf-8")
        pairs.append(dict(
            source_id=source["source_id"], original_relative_path=source["relative_path"],
            original_url=source["official_url"], original_sha256=source["sha256"], retrieved_at=source["retrieved_at"],
            paired_pdf=pdf_path, paired_pdf_sha256=hashlib.sha256((root / pdf_path).read_bytes()).hexdigest(),
            paired_pdf_url=pdf_url, same_final_notice_links_present=True))
    body_path = "raw/shared-body.html"
    (root / body_path).write_text("\n".join(pair[key] for pair in pairs for key in ("original_url", "paired_pdf_url")),
                                  encoding="utf-8")
    sources.append({**sources[0], "source_id": "shared-body", "families": ["dual_use", "military"],
                    "relative_path": body_path, "sha256": hashlib.sha256((root / body_path).read_bytes()).hexdigest()})
    write("review/structured-source-verification.json",
          dict(notice_number=FIXTURE_NOTICE, effective_date="2026-01-01", captured_body=body_path,
               captured_body_sha256=sources[-1]["sha256"], pairs=pairs))
    write("review/source-positions.json", dict(
        control_positions=positions,
        table_positions=[dict(clause_id=c["clause_id"], page=1, table=1, row=1, item=1, bbox=[0, 0, 1, 1],
                              text_sha256=hashlib.sha256(c["text"].encode()).hexdigest())
                         for c in clauses if c["family"] in ("advanced", "core")]))
    write("review/control-boundaries.json", audits)
    numeric = [dict(clause_id=clauses[0]["clause_id"], source_anchor=clauses[0]["source_anchor"],
                    literal="synthetic criterion", operator="ge", threshold="1", unit="nm")]
    write("review/numeric-evidence.json", numeric)
    audit_keys = ("root_code_count", "code_position_count", "missing_from_normalized", "unexpected_normalized",
                  "checked_boundaries", "boundary_failures", "checked_category_transitions",
                  "category_assignment_failures")
    write("review/review.json", dict(
        review_kind="source-coverage-and-conservative-normalization",
        source_page_counts={f.replace("_", "-"): 1 for f in ("advanced", "core", "dual_use", "military")},
        family_clause_counts={f: 1 for f in ("advanced", "core", "dual_use", "military")},
        designated_technology_counts={f: 1 for f in ("advanced", "core")},
        control_root_counts={f: 1 for f in ("dual_use", "military")},
        designated_field_counts={f: {"test": 1} for f in ("advanced", "core")},
        code_position_counts={f: 1 for f in positions},
        independent_control_audit={f: {k: v for k, v in audits[f].items() if k in audit_keys} for f in audits},
        condition_node_counts=dict(numeric=1, unsupported=3), numeric_examples=numeric,
        support_counts=dict(designation_or_control_items=4, complete_numeric_and_qualitative_ast=1,
                            complete_qualitative_ast=0, partially_structured_with_unsupported=0,
                            uninterpreted_original=3)))


def save_manifest(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


class FixtureTests(unittest.TestCase):
    """합성 기준본으로 검증 규칙을 확인한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest, self.clauses = fixture_bundle(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_bundle_is_immutable_and_fingerprinted(self):
        catalogue = load_catalogue(self.root)
        self.assertEqual(catalogue.fingerprint, canonical_hash(self.manifest))
        self.assertEqual(catalogue.fingerprint, canonical_hash(catalogue.manifest))
        self.assertEqual(set(catalogue.by_family), {"advanced", "core", "dual_use", "military"})
        with self.assertRaises(TypeError):
            catalogue.manifest["catalogue_id"] = "mutated"
        with self.assertRaises(TypeError):
            catalogue.clauses[0]["title"] = "mutated"
        independent = catalogue.to_dict()
        independent["clauses"][0]["title"] = "copy"
        self.assertNotEqual(catalogue.clauses[0]["title"], "copy")

    def test_one_changed_file_fails_loading(self):
        """파일 하나만 바꿔도(해시 불일치) 불러오기가 예외로 끝난다. 조용히 넘어가지 않는다."""
        load_catalogue(self.root)
        target = self.root / "raw/core.txt"
        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaisesRegex(CatalogueError, "raw/core.txt"):
            load_catalogue(self.root)

    def test_missing_file_fails_loading(self):
        (self.root / "raw/core.txt").unlink()
        with self.assertRaisesRegex(CatalogueError, "raw/core.txt"):
            load_catalogue(self.root)

    def test_missing_manifest_is_actionable(self):
        (self.root / "manifest.json").unlink()
        with self.assertRaisesRegex(CatalogueError, "manifest"):
            load_catalogue(self.root)

    def test_review_and_coverage_gate(self):
        for field, value in (("review_status", "pending"), ("coverage", "partial"), ("coverage", "unavailable")):
            manifest = copy.deepcopy(self.manifest)
            manifest["sources"][0][field] = value
            save_manifest(self.root, manifest)
            with self.assertRaises(CatalogueError):
                load_catalogue(self.root)

    def test_missing_family_is_rejected(self):
        self.manifest["sources"] = self.manifest["sources"][:3]
        save_manifest(self.root, self.manifest)
        with self.assertRaises(CatalogueError):
            load_catalogue(self.root)

    def test_path_traversal_absolute_and_windows_path(self):
        for path in ("../escape.txt", "/absolute.txt", "C:/absolute.txt", "raw\\..\\escape.txt"):
            manifest = copy.deepcopy(self.manifest)
            manifest["files"][0]["relative_path"] = path
            save_manifest(self.root, manifest)
            with self.assertRaises(CatalogueError):
                load_catalogue(self.root)

    def rewrite_clauses(self, clauses):
        path = self.root / "normalized/clauses.json"
        path.write_text(json.dumps(clauses, ensure_ascii=False), encoding="utf-8")
        for record in self.manifest["files"]:
            if record["relative_path"] == "normalized/clauses.json":
                record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest["clause_inventory"] = [dict(clause_id=c["clause_id"], family=c["family"], sha256=canonical_hash(c))
                                             for c in clauses]
        save_manifest(self.root, self.manifest)

    def test_unresolved_and_cyclic_qualifier_references(self):
        self.clauses[0]["qualifier_refs"] = ["missing"]
        self.rewrite_clauses(self.clauses)
        with self.assertRaises(CatalogueError):
            load_catalogue(self.root)
        self.clauses[0]["qualifier_refs"] = [self.clauses[1]["clause_id"]]
        self.clauses[1]["qualifier_refs"] = [self.clauses[0]["clause_id"]]
        self.rewrite_clauses(self.clauses)
        with self.assertRaises(CatalogueError):
            load_catalogue(self.root)

    def test_inventory_tamper_and_duplicate_clause(self):
        self.manifest["clause_inventory"][0]["sha256"] = "0" * 64
        save_manifest(self.root, self.manifest)
        with self.assertRaises(CatalogueError):
            load_catalogue(self.root)
        self.clauses.append(copy.deepcopy(self.clauses[0]))
        self.rewrite_clauses(self.clauses)
        with self.assertRaises(CatalogueError):
            load_catalogue(self.root)

    def test_bad_ast_and_nonfinite_threshold(self):
        for condition in ({"type": "all", "children": []}, {"type": "not", "child": {}},
                          {"type": "numeric", "predicate_id": "p", "text": "x", "source_anchor": "p1", "subject": "x",
                           "operator": "ge", "threshold": "NaN", "unit": "nm"}):
            self.clauses[0]["condition"] = condition
            self.rewrite_clauses(self.clauses)
            with self.assertRaises(CatalogueError):
                load_catalogue(self.root)

    def test_review_files_must_be_bound_by_manifest(self):
        original = copy.deepcopy(self.manifest)
        reviews = [r["relative_path"] for r in original["files"] if r["relative_path"].startswith("review/")]
        self.assertEqual(len(reviews), 5)
        for path in reviews:
            with self.subTest(path=path):
                self.manifest = copy.deepcopy(original)
                self.manifest["files"] = [r for r in self.manifest["files"] if r["relative_path"] != path]
                save_manifest(self.root, self.manifest)
                with self.assertRaises(CatalogueError):
                    load_catalogue(self.root)
        save_manifest(self.root, original)
        load_catalogue(self.root)

    def test_canonical_hash_is_order_and_unicode_stable(self):
        self.assertEqual(canonical_hash({"나": 2, "a": 1}), canonical_hash({"a": 1, "나": 2}))

    def test_accessors_on_fixture(self):
        catalogue = load_catalogue(self.root)
        index = clause_index(catalogue)
        self.assertEqual([entry["clause_id"] for entry in index], ["advanced:001", "core:001", "dual_use:001", "military:001"])
        self.assertEqual(set(index[0]), {"clause_id", "family", "code", "title", "field"})
        self.assertEqual(index[2]["code"], "SYN-dual_use")
        self.assertEqual(index[0]["code"], "")
        self.assertEqual(note_records(catalogue), [])
        record = clause_record(catalogue, "advanced:001")
        self.assertEqual(record["text"], "synthetic criterion")
        self.assertEqual(record["condition"]["type"], "numeric")
        self.assertEqual(record["qualifier_refs"], [])
        self.assertEqual(record["source_anchor"], "raw/advanced.txt#page=1&row=1")
        with self.assertRaises(KeyError):
            clause_record(catalogue, "advanced:999")
        leaves = numeric_leaves(catalogue)
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["clause_id"], "advanced:001")
        self.assertEqual(leaves[0]["predicate_id"], "advanced:001:p1")
        self.assertEqual((leaves[0]["operator"], leaves[0]["threshold"], leaves[0]["unit"]), ("ge", "1", "nm"))
        self.assertEqual(leaves[0]["path"], [])
        summary = catalogue_summary(catalogue)
        self.assertEqual(summary["catalogue_id"], "synthetic")
        self.assertEqual(summary["fingerprint"], catalogue.fingerprint)
        self.assertEqual(summary["clause_count"], 4)
        self.assertEqual(summary["item_count"], 4)
        self.assertEqual(summary["note_count"], 0)
        self.assertEqual(len(summary["sources"]), 5)

    def test_numeric_leaf_path_records_nested_operators(self):
        """all > not > any 아래의 숫자 잎은 경로 [all, not, any]를 가진다."""
        leaf = dict(type="numeric", predicate_id="advanced:001:deep", text="deep", source_anchor="raw/advanced.txt#page=1&row=1",
                    subject="x", operator="lt", threshold="2", unit="mm")
        other = dict(type="qualitative", predicate_id="advanced:001:q", text="q", source_anchor="raw/advanced.txt#page=1&row=1",
                     subject="y", reason="synthetic")
        self.clauses[0]["condition"] = dict(type="all", children=[
            dict(type="not", child=dict(type="any", children=[leaf, other]))])
        self.rewrite_clauses(self.clauses)
        report_path = self.root / "review/review.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["condition_node_counts"] = dict(all=1, any=1, numeric=1, qualitative=1, unsupported=3)
        report["condition_node_counts"]["not"] = 1
        report["numeric_examples"] = [dict(clause_id="advanced:001", source_anchor="raw/advanced.txt#page=1&row=1",
                                           literal="deep", operator="lt", threshold="2", unit="mm")]
        (self.root / "review/numeric-evidence.json").write_text(json.dumps(report["numeric_examples"], ensure_ascii=False),
                                                                 encoding="utf-8")
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        for record in self.manifest["files"]:
            if record["relative_path"] in ("review/review.json", "review/numeric-evidence.json"):
                record["sha256"] = hashlib.sha256((self.root / record["relative_path"]).read_bytes()).hexdigest()
        save_manifest(self.root, self.manifest)
        leaves = numeric_leaves(load_catalogue(self.root))
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["path"], ["all", "not", "any"])
        self.assertEqual(leaves[0]["predicate_id"], "advanced:001:deep")


class CopiedBundleTests(unittest.TestCase):
    """프로그램 폴더의 실제 복사본(resources/notices)을 확인한다. 시뮬레이터 폴더는 읽지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.root = paths.notices_root()
        cls.manifest = json.loads((cls.root / "manifest.json").read_text(encoding="utf-8"))
        cls.catalogue = load_catalogue()

    def test_bundle_lives_under_program_resources(self):
        self.assertEqual(self.root, PROGRAM / "resources" / "notices")
        self.assertTrue(self.root.is_dir())

    def test_every_copied_file_matches_its_manifest_hash(self):
        """manifest에 적힌 24개 파일 전부의 SHA256이 복사본과 같고, 폴더에는 그 24개와 manifest.json만 있다."""
        listed = {record["relative_path"]: record["sha256"] for record in self.manifest["files"]}
        self.assertEqual(len(listed), 24)
        on_disk = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(on_disk, sorted([*listed, "manifest.json"]))
        self.assertIn(".gitattributes", listed)
        mismatched = []
        for relative, expected in listed.items():
            actual = hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
            if actual != expected:
                mismatched.append(relative)
        self.assertEqual(mismatched, [], f"SHA256 불일치 {len(mismatched)}건")

    def test_fingerprint_and_catalogue_id(self):
        self.assertEqual(self.catalogue.fingerprint, EXPECTED_FINGERPRINT)
        self.assertEqual(canonical_hash(self.manifest), EXPECTED_FINGERPRINT)
        self.assertEqual(self.catalogue.manifest["catalogue_id"], EXPECTED_CATALOGUE_ID)
        self.assertEqual(len(self.catalogue.clauses), 571)

    def test_item_and_note_counts(self):
        index = clause_index(self.catalogue)
        notes = note_records(self.catalogue)
        self.assertEqual(len(index), 507)
        self.assertEqual(len(notes), 64)
        self.assertEqual(Counter(entry["family"] for entry in index),
                         {"advanced": 19, "core": 79, "dual_use": 387, "military": 22})
        self.assertEqual(Counter(entry["family"] for entry in notes),
                         {"advanced": 1, "core": 1, "dual_use": 21, "military": 41})
        self.assertEqual({f: len(cs) for f, cs in self.catalogue.by_family.items()},
                         {"advanced": 20, "core": 80, "dual_use": 408, "military": 63})
        self.assertTrue(all(entry["field"] != NOTE_FIELD for entry in index))
        self.assertTrue(all(set(entry) == {"clause_id", "family", "code", "title", "field"} for entry in index))
        self.assertTrue(all(set(entry) == {"clause_id", "text", "family", "title"} for entry in notes))
        self.assertEqual(len({entry["clause_id"] for entry in index} | {entry["clause_id"] for entry in notes}), 571)
        self.assertTrue(all(entry["code"] == "" for entry in index if entry["family"] in ("advanced", "core")))
        self.assertTrue(all(entry["code"] for entry in index if entry["family"] in ("dual_use", "military")))
        self.assertEqual({entry["code"] for entry in index if entry["family"] == "military"},
                         {f"ML{i}" for i in range(1, 23)})

    def test_numeric_leaves(self):
        leaves = numeric_leaves(self.catalogue)
        self.assertEqual(len(leaves), 57)
        self.assertEqual(Counter(leaf["operator"] for leaf in leaves), {"ge": 34, "le": 16, "gt": 5, "eq": 2})
        self.assertEqual(sorted(leaf["clause_id"] for leaf in leaves if leaf["operator"] == "eq"),
                         ["core:item:060", "core:item:068"])
        self.assertEqual(len({leaf["predicate_id"] for leaf in leaves}), 57)
        for leaf in leaves:
            self.assertEqual(set(leaf), {"clause_id", "predicate_id", "subject", "operator", "threshold", "unit",
                                         "text", "source_anchor", "path"})
            self.assertTrue(all(step in ("all", "any", "not") for step in leaf["path"]))
            self.assertNotEqual(clause_record(self.catalogue, leaf["clause_id"])["field"], NOTE_FIELD)
        boundary = {"advanced:item:014": ("gt", "80", "%"), "advanced:item:005": ("le", "0.8", "um"),
                    "core:item:008": ("ge", "300", "mm"), "dual_use:control:3A102": ("gt", "300", "km")}
        for clause_id, expected in boundary.items():
            values = [(l["operator"], l["threshold"], l["unit"]) for l in leaves if l["clause_id"] == clause_id]
            self.assertIn(expected, values)

    def test_clause_record_fields(self):
        record = clause_record(self.catalogue, "dual_use:control:1A003")
        self.assertEqual(set(record), {"clause_id", "text", "qualifier_refs", "condition", "family", "code", "title",
                                       "field", "source_anchor"})
        self.assertEqual(record["code"], "1A003")
        self.assertEqual(record["condition"]["type"], "all")
        self.assertEqual([child["type"] for child in record["condition"]["children"]], ["qualitative", "any", "not"])
        self.assertIn("child", record["condition"]["children"][2])
        self.assertIn("dual_use:control:1C008", record["qualifier_refs"])
        record["condition"]["type"] = "mutated"
        self.assertEqual(clause_record(self.catalogue, "dual_use:control:1A003")["condition"]["type"], "all")
        note = clause_record(self.catalogue, "advanced:article:4")
        self.assertEqual(note["field"], NOTE_FIELD)
        self.assertIn("양산", note["text"])

    def test_catalogue_summary(self):
        summary = catalogue_summary(self.catalogue)
        self.assertEqual(summary["catalogue_id"], EXPECTED_CATALOGUE_ID)
        self.assertEqual(summary["fingerprint"], EXPECTED_FINGERPRINT)
        self.assertEqual((summary["clause_count"], summary["item_count"], summary["note_count"]), (571, 507, 64))
        self.assertEqual(summary["numeric_leaf_count"], 57)
        self.assertEqual(summary["file_count"], 24)
        self.assertEqual(summary["family_item_counts"], {"advanced": 19, "core": 79, "dual_use": 387, "military": 22})
        notices = {n["notice_number"]: n for n in summary["notices"]}
        self.assertEqual(notices["산업통상자원부고시 제2025-71호"]["announcement_date"], "2025-05-12")
        self.assertEqual(notices["산업통상자원부고시 제2025-71호"]["effective_date"], "2025-05-18")
        self.assertEqual(notices["산업통상부고시 제2025-2호"]["effective_date"], "2025-10-02")
        self.assertEqual(notices["산업통상부고시 제2026-101호"]["announcement_date"], "2026-08-31")
        self.assertEqual(notices["산업통상부고시 제2026-101호"]["effective_date"], "2026-09-01")
        self.assertEqual(notices["산업통상부고시 제2026-101호"]["title"], "전략물자수출입고시")
        self.assertEqual(set(notices["산업통상부고시 제2026-101호"]["families"]), {"dual_use", "military"})
        self.assertEqual(len(summary["sources"]), 9)
        json.dumps(summary, ensure_ascii=False)

    def test_copied_bundle_with_one_changed_file_fails(self):
        """실제 복사본을 임시 폴더에 옮기고 파일 하나를 바꾸면 불러오기가 실패한다."""
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "notices"
            shutil.copytree(self.root, copied, copy_function=shutil.copyfile)
            target = copied / "review/numeric-evidence.json"
            target.write_bytes(target.read_bytes() + b"\n")
            with self.assertRaisesRegex(CatalogueError, "review/numeric-evidence.json"):
                load_catalogue(copied)


class LoaderSourceTests(unittest.TestCase):
    """로더가 표준 라이브러리와 paths만 쓰고 시뮬레이터 폴더를 가리키지 않는지 소스에서 확인한다."""

    def test_loader_imports_only_stdlib_and_paths(self):
        source = (PROGRAM / "notice_catalogue.py").read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        local = {path.stem for path in PROGRAM.glob("*.py")}
        self.assertEqual(imported & local, {"paths"})
        for forbidden in ("v17_domain", "notice_catalogue_v17", "resources_v16", "보안등급분류", "_MEIPASS"):
            self.assertNotIn(forbidden, source)
        self.assertIn("paths.notices_root()", source)


if __name__ == "__main__":
    unittest.main()
