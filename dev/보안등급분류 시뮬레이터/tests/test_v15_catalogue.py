"""Offline integrity tests; fixture text is synthetic, never a real project."""
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree
import zipfile

from notice_catalogue_v15 import CatalogueError, canonical_hash, load_catalogue


def fixture_bundle(root):
    clauses = []
    sources = []
    for family in ("advanced", "core", "dual_use", "military"):
        source_id = family + "-source"
        path = "raw/" + family + (".hwpx"if family in("dual_use","military")else".txt")
        (root / path).parent.mkdir(exist_ok=True)
        (root / path).write_text("synthetic public-source fixture", encoding="utf-8")
        digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
        sources.append(dict(source_id=source_id, families=[family], title="synthetic",
            notice_number="test-1", announcement_version="test", effective_date="2026-01-01",
            official_url=f"https://www.law.go.kr/example?flSeq={len(sources)+1}", retrieved_at="2026-10-20T00:00:00+09:00",
            relative_path=path, sha256=digest, review_status="reviewed", coverage="full", review_note="fixture"))
        clause_id = family + ":001"
        anchor=path+"#page=1&row=1"
        condition=dict(type="unsupported",predicate_id=clause_id+":p1",text="synthetic criterion",
            source_anchor=anchor,subject="criterion",reason="synthetic")
        if family=="advanced":
            condition={key:value for key,value in condition.items()if key!="reason"}
            condition.update(type="numeric",operator="ge",threshold="1",unit="nm")
        clauses.append(dict(clause_id=clause_id, source_id=source_id, family=family,
            code="SYN-"+family if family in("dual_use","military")else"",
            title="synthetic clause", field="test", source_anchor=anchor, text="synthetic criterion",
            qualifier_refs=[], condition=condition))
    (root / "normalized").mkdir()
    (root / "normalized/clauses.json").write_text(json.dumps(clauses,ensure_ascii=False),encoding="utf-8")
    fixture_review(root,sources,clauses)
    files = [dict(relative_path=p.relative_to(root).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(root.rglob("*")) if p.is_file()]
    manifest = dict(catalogue_schema_version=1, catalogue_id="synthetic", sources=sources, files=files,
        clause_inventory=[dict(clause_id=c["clause_id"],family=c["family"],sha256=canonical_hash(c)) for c in clauses])
    save_manifest(root, manifest)
    return manifest, clauses


def fixture_review(root,sources,clauses):
    """Small public-source-shaped evidence using the existing official review fields."""
    def write(path,value):
        target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
    positions={};audits={};pairs=[]
    for clause in clauses:
        family=clause["family"]
        write("extracted/"+family.replace("_","-")+".pages.json",[dict(page=1,text="synthetic public source")])
        if family not in("dual_use","military"):continue
        position=dict(code=clause["code"],root_code=clause["code"],page=1,bbox=[0,0,1,1])
        positions[family]=[position]
        audit=dict(root_code_count=1,code_position_count=1,missing_from_normalized=[],unexpected_normalized=[],
            checked_boundaries=1,boundary_failures=[],checked_category_transitions=0,category_assignment_failures=[])
        audits[family]={**audit,"independent_source_positions":[position],"paragraph_count":2,
            "whole_paragraph_assignments":[dict(paragraph_id=family+":"+language,owner=clause["clause_id"],
                language=language,source_anchor=clause["source_anchor"],text_sha256=hashlib.sha256(clause["text"].encode()).hexdigest())
                for language in("ko","en")],"whole_paragraph_assignment_failures":[]}
        source=next(s for s in sources if s["source_id"]==clause["source_id"])
        pdf_path="raw/"+family+".pdf";pdf_url=source["official_url"]+"00"
        (root/pdf_path).write_text("synthetic paired public source",encoding="utf-8")
        pairs.append(dict(source_id=source["source_id"],original_relative_path=source["relative_path"],
            original_url=source["official_url"],original_sha256=source["sha256"],retrieved_at=source["retrieved_at"],
            paired_pdf=pdf_path,paired_pdf_sha256=hashlib.sha256((root/pdf_path).read_bytes()).hexdigest(),
            paired_pdf_url=pdf_url,same_final_notice_links_present=True))
    body_path="raw/shared-body.html"
    (root/body_path).write_text("\n".join(pair[key]for pair in pairs for key in("original_url","paired_pdf_url")),encoding="utf-8")
    sources.append({**sources[0],"source_id":"shared-body","families":["dual_use","military"],
        "relative_path":body_path,"sha256":hashlib.sha256((root/body_path).read_bytes()).hexdigest()})
    write("review/structured-source-verification.json",dict(notice_number="test-1",effective_date="2026-01-01",
        captured_body=body_path,captured_body_sha256=sources[-1]["sha256"],pairs=pairs))
    write("review/source-positions.json",dict(control_positions=positions,table_positions=[
        dict(clause_id=c["clause_id"],page=1,table=1,row=1,item=1,bbox=[0,0,1,1],
            text_sha256=hashlib.sha256(c["text"].encode()).hexdigest())for c in clauses if c["family"]in("advanced","core")]))
    write("review/control-boundaries.json",audits)
    numeric=[dict(clause_id=clauses[0]["clause_id"],source_anchor=clauses[0]["source_anchor"],
        literal="synthetic criterion",operator="ge",threshold="1",unit="nm")]
    write("review/numeric-evidence.json",numeric)
    write("review/review.json",dict(review_kind="source-coverage-and-conservative-normalization",
        source_page_counts={f.replace("_","-"):1 for f in("advanced","core","dual_use","military")},
        family_clause_counts={f:1 for f in("advanced","core","dual_use","military")},
        designated_technology_counts={f:1 for f in("advanced","core")},
        control_root_counts={f:1 for f in("dual_use","military")},
        designated_field_counts={f:{"test":1}for f in("advanced","core")},
        code_position_counts={f:1 for f in positions},
        independent_control_audit={f:{key:value for key,value in audits[f].items()if key in(
            "root_code_count","code_position_count","missing_from_normalized","unexpected_normalized", "checked_boundaries",
            "boundary_failures","checked_category_transitions","category_assignment_failures")}for f in audits},
        condition_node_counts=dict(numeric=1,unsupported=3),numeric_examples=numeric,
        support_counts=dict(designation_or_control_items=4,complete_numeric_and_qualitative_ast=1,
            complete_qualitative_ast=0,partially_structured_with_unsupported=0,uninterpreted_original=3)))


def save_manifest(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest, self.clauses = fixture_bundle(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_immutable_bundle_and_fingerprint(self):
        catalogue = load_catalogue(self.root)
        self.assertEqual(catalogue.fingerprint,canonical_hash(self.manifest))
        self.assertEqual(catalogue.fingerprint,canonical_hash(catalogue.manifest))
        self.assertEqual(set(catalogue.by_family),{"advanced","core","dual_use","military"})
        with self.assertRaises(TypeError):
            catalogue.manifest["catalogue_id"]="mutated"
        with self.assertRaises(TypeError):
            catalogue.clauses[0]["title"]="mutated"
        independent = catalogue.to_dict()
        independent["clauses"][0]["title"]="copy"
        self.assertNotEqual(catalogue.clauses[0]["title"],"copy")

    def test_missing_and_corrupt_file(self):
        (self.root/"raw/core.txt").unlink()
        with self.assertRaises(CatalogueError):load_catalogue(self.root)
        (self.root/"raw/core.txt").write_text("changed",encoding="utf-8")
        with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_review_and_coverage_gate(self):
        for field,value in (("review_status","pending"),("coverage","partial"),("coverage","unavailable")):
            manifest=copy.deepcopy(self.manifest);manifest["sources"][0][field]=value
            save_manifest(self.root,manifest)
            with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_missing_family_and_duplicate_source(self):
        self.manifest["sources"]=self.manifest["sources"][:3]
        save_manifest(self.root,self.manifest)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_path_traversal_absolute_and_windows_path(self):
        for path in ("../escape.txt","/absolute.txt","C:/absolute.txt","raw\\..\\escape.txt"):
            manifest=copy.deepcopy(self.manifest);manifest["files"][0]["relative_path"]=path
            save_manifest(self.root,manifest)
            with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def rewrite_clauses(self, clauses):
        path=self.root/"normalized/clauses.json"
        path.write_text(json.dumps(clauses,ensure_ascii=False),encoding="utf-8")
        for record in self.manifest["files"]:
            if record["relative_path"]=="normalized/clauses.json":record["sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest["clause_inventory"]=[dict(clause_id=c["clause_id"],family=c["family"],sha256=canonical_hash(c)) for c in clauses]
        save_manifest(self.root,self.manifest)

    def test_unresolved_and_cyclic_qualifier_references(self):
        self.clauses[0]["qualifier_refs"]=["missing"]
        self.rewrite_clauses(self.clauses)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)
        self.clauses[0]["qualifier_refs"]=[self.clauses[1]["clause_id"]]
        self.clauses[1]["qualifier_refs"]=[self.clauses[0]["clause_id"]]
        self.rewrite_clauses(self.clauses)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_duplicate_clause_and_inventory_tamper(self):
        self.manifest["clause_inventory"][0]["sha256"]="0"*64
        save_manifest(self.root,self.manifest)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)
        self.clauses.append(copy.deepcopy(self.clauses[0]))
        self.rewrite_clauses(self.clauses)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_bad_ast_and_nonfinite_json(self):
        for condition in ({"type":"all","children":[]},{"type":"not","child":{}},
            {"type":"numeric","predicate_id":"p","text":"x","source_anchor":"p1","subject":"x","operator":"ge","threshold":"NaN","unit":"nm"}):
            self.clauses[0]["condition"]=condition
            self.rewrite_clauses(self.clauses)
            with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_missing_manifest_is_actionable(self):
        (self.root/"manifest.json").unlink()
        with self.assertRaisesRegex(CatalogueError,"manifest"):load_catalogue(self.root)

    def test_canonical_order_unicode_stability(self):
        self.assertEqual(canonical_hash({"나":2,"a":1}),canonical_hash({"a":1,"나":2}))

    def test_duplicate_source_is_rejected(self):
        self.manifest["sources"].append(copy.deepcopy(self.manifest["sources"][0]))
        save_manifest(self.root,self.manifest)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def rewrite_review(self,path,value):
        target=self.root/path
        target.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
        for record in self.manifest["files"]:
            if record["relative_path"]==path:record["sha256"]=hashlib.sha256(target.read_bytes()).hexdigest()
        save_manifest(self.root,self.manifest)

    def test_review_files_must_exist_and_be_bound_by_manifest(self):
        original=copy.deepcopy(self.manifest)
        reviews=[r["relative_path"]for r in original["files"]if r["relative_path"].startswith("review/")]
        self.assertEqual(len(reviews),5)
        for path in reviews:
            with self.subTest(path=path):
                data=(self.root/path).read_bytes()
                self.manifest=copy.deepcopy(original)
                self.manifest["files"]=[r for r in self.manifest["files"]if r["relative_path"]!=path]
                save_manifest(self.root,self.manifest)
                with self.assertRaises(CatalogueError):load_catalogue(self.root)
                (self.root/path).unlink()
                with self.assertRaises(CatalogueError):load_catalogue(self.root)
                self.manifest=copy.deepcopy(original);save_manifest(self.root,self.manifest)
                with self.assertRaises(CatalogueError):load_catalogue(self.root)
                (self.root/path).write_bytes(data+b" ")
                with self.assertRaises(CatalogueError):load_catalogue(self.root)
                (self.root/path).write_bytes(data)

    def test_review_summary_rejects_empty_mismatched_and_unfinished_records(self):
        path="review/review.json"
        original=json.loads((self.root/path).read_text(encoding="utf-8"))
        mutations=[[],{}, {**original,"review_kind":"pending"}]
        for field in("family_clause_counts","designated_technology_counts","control_root_counts",
                "designated_field_counts","source_page_counts","condition_node_counts","support_counts"):
            mutations.append({**original,field:{}})
        bad=copy.deepcopy(original);bad["family_clause_counts"]["advanced"]=True;mutations.append(bad)
        for field in("missing_from_normalized","unexpected_normalized","boundary_failures","category_assignment_failures"):
            bad=copy.deepcopy(original);bad["independent_control_audit"]["dual_use"][field]=["unreviewed"]
            mutations.append(bad)
        for value in mutations:
            with self.subTest(value=value):
                self.rewrite_review(path,value)
                with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_review_source_pairs_reject_stale_identity_hash_dates_and_status(self):
        path="review/structured-source-verification.json"
        original=json.loads((self.root/path).read_text(encoding="utf-8"))
        mutations=[{}, {**original,"pairs":[]}, {**original,"notice_number":"old-notice"},
            {**original,"effective_date":"2025-01-01"},{**original,"captured_body_sha256":"0"*64}]
        for field,value in(("source_id","previous-source"),("original_relative_path","raw/old.hwpx"),
                ("original_sha256","0"*64),("original_url","https://www.law.go.kr/old"),
                ("retrieved_at","2025-01-01T00:00:00+09:00"),("paired_pdf_sha256","0"*64),
                ("paired_pdf_url","https://www.law.go.kr/example?flSeq=999"),("same_final_notice_links_present",False)):
            bad=copy.deepcopy(original);bad["pairs"][0][field]=value;mutations.append(bad)
        for value in mutations:
            with self.subTest(value=value):
                self.rewrite_review(path,value)
                with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_review_evidence_requires_usable_types_and_connected_clause_ids(self):
        for path in("review/source-positions.json","review/control-boundaries.json","review/numeric-evidence.json"):
            original=json.loads((self.root/path).read_text(encoding="utf-8"))
            for value in({},[]):
                self.rewrite_review(path,value)
                with self.assertRaises(CatalogueError):load_catalogue(self.root)
            self.rewrite_review(path,original)
        path="review/source-positions.json"
        bad=json.loads((self.root/path).read_text(encoding="utf-8"));bad["table_positions"][0]["clause_id"]="old-clause"
        self.rewrite_review(path,bad)
        with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_malformed_review_identifiers_raise_catalogue_error(self):
        cases=("table_clause", "control_code", "paragraph_owner", "numeric_clause", "paired_source")
        originals={path:json.loads((self.root/path).read_text(encoding="utf-8"))for path in(
            "review/source-positions.json","review/control-boundaries.json","review/numeric-evidence.json",
            "review/structured-source-verification.json")}
        for case in cases:
            for path,value in originals.items():self.rewrite_review(path,value)
            if case=="table_clause":
                path="review/source-positions.json";value=copy.deepcopy(originals[path]);value["table_positions"][0]["clause_id"]=[]
            elif case=="control_code":
                path="review/source-positions.json";value=copy.deepcopy(originals[path]);value["control_positions"]["dual_use"][0]["root_code"]={}
            elif case=="paragraph_owner":
                path="review/control-boundaries.json";value=copy.deepcopy(originals[path]);value["dual_use"]["whole_paragraph_assignments"][0]["owner"]=[]
            elif case=="numeric_clause":
                path="review/numeric-evidence.json";value=copy.deepcopy(originals[path]);value[0]["clause_id"]={}
            else:
                path="review/structured-source-verification.json";value=copy.deepcopy(originals[path]);value["pairs"][0]["source_id"]=[]
            self.rewrite_review(path,value)
            with self.subTest(case=case):
                with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_numeric_review_fields_reject_invalid_types_and_nonfinite_thresholds(self):
        path="review/numeric-evidence.json"
        original=json.loads((self.root/path).read_text(encoding="utf-8"))
        report=json.loads((self.root/"review/review.json").read_text(encoding="utf-8"))
        mutations=[]
        for field,values in(("literal",("",[],None)),("unit",("",{},None)),
                ("threshold",([],{},1,None,"", "NaN","sNaN","Infinity","-Infinity","invalid")),
                ("operator",({},[],None,"invalid"))):
            for value in values:
                record={**original[0],field:value};mutations.append(record)
        mutations.append({**original[0],"extra":"invalid"})
        mutations.append({key:value for key,value in original[0].items()if key!="unit"})
        for record in mutations:
            with self.subTest(record=record):
                self.rewrite_review(path,[record])
                self.rewrite_review("review/review.json",{**report,"numeric_examples":[record]})
                with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_numeric_review_can_document_an_unparsed_source_condition(self):
        clause=self.clauses[1]
        self.assertEqual(clause["condition"]["type"],"unsupported")
        record=dict(clause_id=clause["clause_id"],source_anchor=clause["source_anchor"],
            literal="synthetic original-source numeric review",operator="lt",threshold="2.5",unit="mm")
        report=json.loads((self.root/"review/review.json").read_text(encoding="utf-8"))
        self.rewrite_review("review/numeric-evidence.json",[record])
        self.rewrite_review("review/review.json",{**report,"numeric_examples":[record]})
        self.assertEqual(len(load_catalogue(self.root).clauses),4)


def leaves(node):
    if node["type"]in("all","any"):
        return [leaf for child in node["children"]for leaf in leaves(child)]
    if node["type"]=="not":return leaves(node["child"])
    return [node]


class OfficialBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]/"resources_v15/notices"
        cls.catalogue=load_catalogue(cls.root)
        cls.by_id={item["clause_id"]:item for item in cls.catalogue.clauses}
        cls.report=json.loads((cls.root/"review/review.json").read_text(encoding="utf-8"))
        cls.audits=json.loads((cls.root/"review/control-boundaries.json").read_text(encoding="utf-8"))

    def test_official_review_inventory_cannot_be_removed_to_bypass_missing_files(self):
        import notice_catalogue_v15
        original=notice_catalogue_v15._read_json
        def without_review(path):
            value=original(path)
            if path.name=="manifest.json":
                value["files"]=[r for r in value["files"]if not r["relative_path"].startswith("review/")]
            return value
        read_bytes=Path.read_bytes
        def missing_review(path):
            if path.parent.name=="review":raise FileNotFoundError(path)
            return read_bytes(path)
        with mock.patch.object(notice_catalogue_v15,"_read_json",side_effect=without_review),\
                mock.patch.object(Path,"read_bytes",missing_review):
            with self.assertRaises(CatalogueError):load_catalogue(self.root)

    def test_fixed_source_versions_bytes_and_full_scope(self):
        expected={"advanced-annex.pdf":"7a4fa18367a0cafa47303ef7424eb5d081e8be907f3404832e9fadebca5c0329",
            "core-annex.pdf":"6f3ee0649eff1fc96e6b19010d27773cdc593bde353965a2654a3c5d0fda8dae",
            "dual-use-annex.pdf":"2972bbcc31111826367d82416bf405f0b15c9fa162a614d70fd363acbbc483de",
            "military-annex.pdf":"d66928906b90d624bfd90b9c678e9137f2d4bdc89e843c51f680de50661ea639",
            "dual-use-annex.hwpx":"2846c07fbd80cba9ff55fc3bad2fd84a1ad6cbc06492daa70bf4476bb176cbe5",
            "military-annex.hwpx":"30d0ee2bbccda1df193fb115c950e685a8ff350fb8b5a5a5873c17391237804c"}
        for name,digest in expected.items():self.assertEqual(hashlib.sha256((self.root/"raw"/name).read_bytes()).hexdigest(),digest)
        sources={s["source_id"]:s for s in self.catalogue.manifest["sources"]}
        self.assertEqual(sources["advanced-annex"]["effective_date"],"2025-05-18")
        self.assertEqual(sources["core-annex"]["notice_number"],"산업통상부고시 제2025-2호")
        self.assertEqual(sources["dual-use-annex"]["notice_number"],"산업통상부고시 제2026-101호")
        self.assertEqual(sources["dual-use-annex"]["effective_date"],"2026-09-01")
        self.assertTrue(all(s["review_status"]=="reviewed" and s["coverage"]=="full"for s in sources.values()))

    def test_official_designation_and_control_counts(self):
        self.assertEqual(sum(c["clause_id"].startswith("advanced:item:")for c in self.catalogue.clauses),19)
        self.assertEqual(sum(c["clause_id"].startswith("core:item:")for c in self.catalogue.clauses),79)
        self.assertEqual(sum(c["clause_id"].startswith("dual_use:control:")for c in self.catalogue.clauses),387)
        self.assertEqual({c["code"]for c in self.catalogue.by_family["military"] if c["code"]},{f"ML{i}"for i in range(1,23)})
        self.assertEqual(self.report["code_position_counts"],{"dual_use":2601,"military":22})

    def test_all_667_pages_have_complete_extraction_records(self):
        counts={"advanced":2,"core":3,"dual-use":614,"military":48}
        for name,count in counts.items():
            pages=json.loads((self.root/"extracted"/(name+".pages.json")).read_text(encoding="utf-8"))
            self.assertEqual([page["page"]for page in pages],list(range(1,count+1)))
            self.assertTrue(all(page["text"].strip() and page["lines"]for page in pages))
            self.assertTrue(all("\ufffd"not in page["text"]for page in pages))

    def test_advanced_continued_row_is_one_item_with_two_anchors(self):
        item=self.by_id["advanced:item:015"]
        self.assertIn("continued_page=2",item["source_anchor"])
        self.assertIn("리튬금속전지",item["text"])
        self.assertEqual(item["condition"]["type"],"unsupported")

    def test_advanced_scope_korean_and_all_designations_reference_it(self):
        scope=self.by_id["advanced:article:4"]
        self.assertIn("각 기술에 특화되어 양산을 목적으로 개발되거나 양산에 사용되는 기술",scope["text"])
        self.assertNotIn("ì",scope["text"])
        for item in self.catalogue.by_family["advanced"]:
            if item["field"]!="공통정의·주석":self.assertIn("advanced:article:4",item["qualifier_refs"])

    def test_real_strict_and_inclusive_numeric_boundaries(self):
        cases={"advanced:item:014":("gt","80","%"),"advanced:item:005":("le","0.8","um"),
            "core:item:008":("ge","300","mm"),"dual_use:control:3A102":("gt","300","km")}
        for identifier,expected in cases.items():
            values=[(x["operator"],x["threshold"],x["unit"])for x in leaves(self.by_id[identifier]["condition"])if x["type"]=="numeric"]
            self.assertIn(expected,values)

    def test_battery_four_branches_preserve_diameter_boundary(self):
        condition=self.by_id["advanced:item:013"]["condition"]
        any_node=next(child for child in condition["children"]if child["type"]=="any")
        self.assertEqual(len(any_node["children"]),4)
        cylinders=any_node["children"][2:]
        self.assertEqual([(x["children"][1]["operator"],x["children"][2]["threshold"])for x in cylinders],[("le","280"),("gt","260")])
        self.assertTrue(all(x["children"][1]["threshold"]=="21"for x in cylinders))

    def test_export_numeric_or_and_exception_are_not_flattened(self):
        item=self.by_id["dual_use:control:1A003"]
        self.assertEqual(item["condition"]["type"],"all")
        self.assertEqual([child["type"]for child in item["condition"]["children"]],["qualitative","any","not"])
        self.assertEqual(item["condition"]["children"][1]["children"][0]["threshold"],"0.254")
        self.assertEqual(item["condition"]["children"][2]["child"]["type"],"all")
        self.assertIn("dual_use:control:1C008",item["qualifier_refs"])

    def test_unparsed_cross_reference_and_military_exemption_stay_visible(self):
        item=self.by_id["dual_use:control:1A002"]
        self.assertIn("1C010",item["text"])
        self.assertEqual(item["condition"]["type"],"unsupported")
        item=self.by_id["military:control:ML22"]
        self.assertIn("기초과학연구",item["text"])
        self.assertEqual(item["condition"]["children"][0]["type"],"unsupported")
        self.assertEqual(item["condition"]["children"][1]["type"],"not")
        self.assertEqual(len(item["condition"]["children"][1]["child"]["children"]),3)

    def test_bilingual_identity_and_notes_are_preserved(self):
        item=self.by_id["dual_use:control:1C354"]
        self.assertIn("[영문 원문]",item["text"])
        self.assertIn("Pseudocercospora",item["text"])
        self.assertEqual(item["condition"]["type"],"qualitative")
        self.assertIn("일반 기술 해설",self.by_id["dual_use:notes:t01:r02"]["text"])
        self.assertTrue(all(self.by_id[reference]["field"]=="공통정의·주석"for reference in self.by_id["military:control:ML1"]["qualifier_refs"]))

    def test_draft_is_excluded_and_support_limits_are_machine_counted(self):
        self.assertFalse(any("38-body"in file["relative_path"]or "38-annex"in file["relative_path"]for file in self.catalogue.manifest["files"]))
        self.assertIn("행정예고",self.report["excluded_draft"]["actual_content"])
        supported=self.report["support_counts"]
        self.assertEqual(sum(supported[k]for k in ("complete_numeric_and_qualitative_ast","complete_qualitative_ast","partially_structured_with_unsupported","uninterpreted_original")),507)
        self.assertGreater(supported["uninterpreted_original"],0)

    def test_inline_nuclear_software_control_is_independent(self):
        item=self.by_id["dual_use:control:0D001"]
        self.assertIn("pages=552-552",item["source_anchor"])
        self.assertIn("0D001 소프트웨어",item["text"])
        self.assertIn("소프트웨어",item["text"])
        self.assertNotIn("0D001 소프트웨어",self.by_id["dual_use:control:0C004"]["text"])
        self.assertIn("Technology",self.by_id["dual_use:control:0E001"]["text"])
        self.assertNotIn("Technology",item["text"])

    def test_military_first_header_line_stays_with_its_logical_row(self):
        ml1="구경이 20mm 미만인 활강무기 (smooth-bore weapon)와 구경 12.7mm (0.50 in.) 이하의"
        ml6="지상차량과, 이의 구성품으로 다음의 것:"
        self.assertIn(ml1,self.by_id["military:control:ML1"]["text"])
        self.assertNotIn(ml1,self.by_id["military:notes:t01:r02"]["text"])
        self.assertIn(ml6,self.by_id["military:control:ML6"]["text"])
        self.assertNotIn(ml6,self.by_id["military:control:ML5"]["text"])

    def test_isotope_first_lines_are_not_attached_to_previous_controls(self):
        cases=(("1C225","1C216","보론(붕소)-10(10B) 동위원소의 농도가 천연상태에서의 농도보다 높은"),
            ("1C232","1C231","헬륨-3(3He), 헬륨-3을 포함하는 혼합물 및 이들을 포함하는 제품이나"),
            ("1C233","1C232","자연에 존재하는 리튬-6(6Li) 동위원소보다 초과하여 농축한 리튬 및"),
            ("1C237","1C236","라듐-226(226Ra), 라듐-226 합금, 라듐-226 화합물, 또는 라듐-226을"))
        for code,previous,first_line in cases:
            self.assertIn(first_line,self.by_id["dual_use:control:"+code]["text"])
            self.assertNotIn(first_line,self.by_id["dual_use:control:"+previous]["text"])

    def test_ied_dedicated_component_is_not_rejected_as_non_equipment(self):
        condition=self.by_id["dual_use:control:1A006"]["condition"]
        def evaluate(node):
            if node["type"]=="unsupported":return None
            if node["type"]in("numeric","qualitative"):
                return {"dual_use:control:1A006:dedicated":True,"dual_use:control:1A006:remote":False,
                    "dual_use:control:1A006:disruptor":False,"dual_use:control:1A006:accompanies":False,
                    "dual_use:control:1A006:component-dedicated":True}.get(node["predicate_id"])
            if node["type"]=="not":
                value=evaluate(node["child"]);return None if value is None else not value
            values=[evaluate(child)for child in node["children"]]
            if node["type"]=="all":return False if False in values else (None if None in values else True)
            return True if True in values else (None if None in values else False)
        self.assertIsNone(evaluate(condition),"A dedicated PCB with unresolved parent-equipment scope must require review, not be excluded")

    def test_independent_pdf_inventory_and_all_boundary_audits(self):
        review=self.report["independent_control_audit"]
        self.assertEqual(review["dual_use"]["root_code_count"],387)
        self.assertEqual(review["military"]["root_code_count"],22)
        self.assertEqual(review["dual_use"]["missing_from_normalized"],[])
        self.assertEqual(review["dual_use"]["unexpected_normalized"],[])
        self.assertEqual(review["military"]["missing_from_normalized"],[])
        self.assertEqual(review["military"]["unexpected_normalized"],[])
        self.assertGreater(review["dual_use"]["checked_boundaries"],380)
        self.assertEqual(review["dual_use"]["boundary_failures"],[])
        self.assertEqual(review["military"]["boundary_failures"],[])

    def test_category_code_does_not_move_previous_column_tail(self):
        cases=(("2D352","2E001","구축할 수 있는 것"),
            ("2D352","2E001","genetic elements from digital sequence data."),
            ("3D507","3E001",'다층 "GDSII" 데이터 또는 회로 넷리스트(netlist)를 생성하도록 설계된 "소프트웨어"'),
            ("5D002","5E002","주의 5D002.d에서 통제되던 품목은 5D002.b를 참조"))
        for previous,following,line in cases:
            with self.subTest(previous=previous,line=line):
                self.assertIn(line,self.by_id["dual_use:control:"+previous]["text"])
                self.assertNotIn(line,self.by_id["dual_use:control:"+following]["text"])

    def test_numbered_control_keeps_previous_language_paragraph_tail(self):
        cases=(("2D351","2D352",'장치의 "사용"을 위하여 특별히 설계된 것'),
            ("2D351","2D352",'"use" of equipment specified in 2B351.'),
            ("3D203","3D507",'해 전용 설계된 "소프트웨어"'))
        for previous,following,line in cases:
            with self.subTest(previous=previous,line=line):
                self.assertIn(line,self.by_id["dual_use:control:"+previous]["text"])
                self.assertNotIn(line,self.by_id["dual_use:control:"+following]["text"])

    def test_category_audit_preserves_both_language_start_positions(self):
        report=json.loads((self.root/"review/control-boundaries.json").read_text(encoding="utf-8"))["dual_use"]
        self.assertEqual(report["checked_category_transitions"],110)
        self.assertEqual(report["category_assignment_failures"],[])
        checks=report["category_transition_checks"]
        self.assertEqual(Counter(check["language"]for check in checks),{"ko":55,"en":55})
        self.assertEqual([(c["category"],c["first_control"])for c in checks if c["language"]=="ko"],
            [(c["category"],c["first_control"])for c in checks if c["language"]=="en"])
        for language in("ko","en"):
            self.assertTrue(all(check["source_anchor"] and check["paragraph_id"]for check in checks if check["language"]==language))
        for page in(253,309):
            starts=[check["position"]for check in checks if check["position"][0]==page]
            self.assertEqual(len(starts),2)
            self.assertNotEqual(starts[0],starts[1])

    def test_coating_table_and_technical_notes_belong_to_2e003(self):
        owner=self.by_id["dual_use:control:2E003"]
        following=self.by_id["dual_use:control:2E503"]
        for text in("소재공정 표", "1. 코팅공정(1)", "표- 증착기술 - [주]",
                "Processes specified in Column 1 of the Table are defined as follows:",
                "g. Ion Implantation is a surface modification coating"):
            self.assertIn(text,owner["text"])
            self.assertNotIn(text,following["text"])
        self.assertIn("2E503.g 이후",owner["text"])
        self.assertIn("2E503.g에서",following["text"])
        self.assertEqual(owner["condition"]["type"],"unsupported")

    def structured_source(self,family):
        name="dual-use"if family=="dual_use"else"military"
        source=json.loads((self.root/"extracted"/f"{name}.paragraphs.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(self.root/"raw"/f"{name}-annex.hwpx")as archive:
            document=ElementTree.fromstring(archive.read("Contents/section0.xml"))
        return source,document

    def test_every_original_xml_body_paragraph_is_preserved_without_text_substitution(self):
        ns={"hp":"http://www.hancom.co.kr/hwpml/2011/paragraph"}
        for family in("dual_use","military"):
            source,document=self.structured_source(family)
            parents={child:parent for parent in document.iter()for child in parent}
            def body_text(paragraph):
                values=[]
                for node in paragraph.iter("{"+ns["hp"]+"}t"):
                    ancestor=parents.get(node);drawing=False
                    while ancestor is not None and ancestor is not paragraph:
                        drawing|=ancestor.tag=="{"+ns["hp"]+"}drawText"
                        ancestor=parents.get(ancestor)
                    if not drawing:values.append("".join(node.itertext()))
                return values
            expected_count=0
            for ti,table in enumerate(document.findall("hp:p/hp:run/hp:tbl",ns),1):
                for ri,row in enumerate(table.findall("hp:tr",ns),1):
                    actual=next(r for r in source["rows"]if r["table"]==ti and r["row"]==ri)
                    for ci,cell in enumerate(row.findall("hp:tc",ns),1):
                        originals=cell.findall("hp:subList/hp:p",ns)
                        exported=actual["cells"][ci-1]
                        records={p["paragraph"]:p for p in exported["paragraphs"]}
                        self.assertEqual(exported["paragraph_count"],len(originals))
                        self.assertEqual(set(records)|set(exported["blank_paragraphs"]),set(range(1,len(originals)+1)))
                        self.assertFalse(set(records)&set(exported["blank_paragraphs"]))
                        for pi,paragraph in enumerate(originals,1):
                            expected_count+=1
                            values=body_text(paragraph)
                            if pi not in records:
                                self.assertFalse("".join(values).strip())
                                self.assertFalse(paragraph.findall(".//hp:equation",ns))
                                continue
                            record=records[pi]
                            self.assertEqual(record["paragraph_id"],f"{family}:t{ti}:r{ri}:c{ci}:p{pi}")
                            self.assertEqual(record["raw_text"],"".join(values))
                            offset=0
                            for value in values:
                                at=record["text"].find(value,offset)
                                self.assertGreaterEqual(at,offset,record["paragraph_id"])
                                offset=at+len(value)
            self.assertEqual(expected_count,source["xml_paragraph_partition"]["outer_table_cell"])
            self.assertEqual(sum(source["xml_paragraph_partition"].values()),len(document.findall(".//hp:p",ns)))
            preface={p["paragraph"]:p for p in source["preface"]}
            for pi,p in enumerate(document.findall("hp:p",ns),1):
                text="".join("".join(t.itertext())for t in p.findall("hp:run/hp:t",ns))
                if text.strip():self.assertEqual(preface[pi]["raw_text"],text)

    def test_whole_bilingual_paragraphs_have_one_owner_and_exact_clause_slices(self):
        for family in("dual_use","military"):
            source,_=self.structured_source(family)
            originals=source["preface"]+[p for row in source["rows"]for cell in row["cells"]for p in cell["paragraphs"]if p["text"].strip()]
            by_id={p["paragraph_id"]:p for p in originals}
            assignments=self.audits[family]["whole_paragraph_assignments"]
            self.assertEqual(Counter(a["paragraph_id"]for a in assignments),Counter(by_id.keys()))
            self.assertEqual(self.audits[family]["paragraph_count"],len(originals))
            self.assertEqual(len(originals),17058 if family=="dual_use"else 2283)
            for assignment in assignments:
                original=by_id[assignment["paragraph_id"]]
                owner=self.by_id[assignment["owner"]]
                preserved=owner["text"][assignment["clause_text_start"]:assignment["clause_text_end"]]
                self.assertEqual(preserved,original["text"])
                self.assertEqual(hashlib.sha256(preserved.encode("utf-8")).hexdigest(),assignment["text_sha256"])
                self.assertIn(assignment["paragraph_id"],owner["source_anchor"])
            controls=[c for c in self.catalogue.by_family[family]if c["code"]]
            for control in controls:
                self.assertEqual({a["language"]for a in assignments if a["owner"]==control["clause_id"]}&{"ko","en"},{"ko","en"})
            checks=self.audits[family]["boundary_checks"]
            self.assertEqual({check["code"]for check in checks},{c["code"]for c in controls})
            self.assertTrue(all(set(check["language_starts"])=={"ko","en"}for check in checks))

    def test_original_equations_nested_cells_and_private_use_symbols_are_retained(self):
        ns={"hp":"http://www.hancom.co.kr/hwpml/2011/paragraph"}
        for family in("dual_use","military"):
            source,document=self.structured_source(family)
            ps=source["preface"]+[p for r in source["rows"]for c in r["cells"]for p in c["paragraphs"]if p["text"].strip()]
            expected=Counter("".join(node.itertext())for node in document.findall(".//hp:equation/hp:script",ns))
            actual=Counter(e["script"]for p in ps for e in p["equations"])
            self.assertEqual(actual,expected)
            self.assertEqual(sum(actual.values()),self.audits[family]["original_equation_count"])
            drawings=Counter("".join("".join(t.itertext())for t in draw.findall(".//hp:t",ns))
                for draw in document.findall(".//hp:drawText",ns))
            preserved=Counter(d["text"]for row in source["rows"]for cell in row["cells"]for p in cell["paragraphs"]for d in p["drawings"])
            audited=Counter(d["text"]for p in self.audits[family]["decorative_shape_labels"]for d in p["drawings"])
            self.assertEqual(drawings,preserved)
            self.assertEqual(preserved,audited)
            self.assertEqual(sum(drawings.values()),0 if family=="dual_use"else 108)
            for p in ps:
                for equation in p["equations"]:self.assertIn(equation["script"],p["text"])
                self.assertEqual(Counter(c for c in p["raw_text"]if 0xE000<=ord(c)<=0xF8FF),
                    Counter(c for c in p["text"]if 0xE000<=ord(c)<=0xF8FF))
            nested=self.audits[family]["nested_paragraph_assignments"]
            self.assertEqual(len(nested),source["xml_paragraph_partition"].get("nested_table_cell",0))
            self.assertEqual(len(nested),len({p["source_anchor"]for p in nested}))
            for paragraph in nested:
                self.assertEqual(paragraph["owner"],"dual_use:control:2E003")
                self.assertIn(paragraph["text"],self.by_id[paragraph["owner"]]["text"])
                self.assertEqual(hashlib.sha256(paragraph["text"].encode("utf-8")).hexdigest(),paragraph["sha256"])
        self.assertEqual(self.audits["dual_use"]["original_equation_count"],28)
        self.assertEqual(self.audits["dual_use"]["nested_table_count"],2)

    def test_all_expression_differences_are_classified_anchored_and_source_exact(self):
        expected={"equation_script_rendering":19,"nested_table_cell_flow":2,
            "private_use_symbol_rendering":4,"floating_military_code_overlay":22}
        actual=Counter()
        for family in("dual_use","military"):
            source,_=self.structured_source(family)
            by_id={p["paragraph_id"]:p for r in source["rows"]for c in r["cells"]for p in c["paragraphs"]}
            for difference in self.audits[family]["source_expression_differences"]:
                actual.update(difference["difference_kinds"])
                self.assertEqual(difference["original_text"],by_id[difference["paragraph_id"]]["text"])
                self.assertEqual(difference["source_anchor"],by_id[difference["paragraph_id"]]["source_anchor"])
                self.assertIn(difference["original_text"],self.by_id[difference["owner"]]["text"])
                self.assertEqual(hashlib.sha256(difference["original_text"].encode("utf-8")).hexdigest(),difference["original_text_sha256"])
                self.assertEqual(hashlib.sha256(by_id[difference["paragraph_id"]]["raw_text"].encode("utf-8")).hexdigest(),difference["raw_text_sha256"])
                self.assertEqual(hashlib.sha256(difference["pdf_window"].encode("utf-8")).hexdigest(),difference["pdf_window_sha256"])
                self.assertTrue(difference["alignment_operations"])
                self.assertGreaterEqual(difference["projection"]["end_page"],difference["projection"]["page"])
        self.assertEqual(actual,expected)

    def test_main_control_inventory_is_independent_of_appendix_repeated_codes(self):
        for family in("dual_use","military"):
            source,document=self.structured_source(family)
            ns={"hp":"http://www.hancom.co.kr/hwpml/2011/paragraph"}
            table=document.findall("hp:p/hp:run/hp:tbl",ns)[0]
            roots=set()
            for ri,row in enumerate(table.findall("hp:tr",ns),1):
                if family=="dual_use"and ri not in(3,*range(5,14)):continue
                if family=="military"and not 3<=ri<=24:continue
                cell=row.findall("hp:tc",ns)[0]
                for p in cell.findall("hp:subList/hp:p",ns):
                    text="".join(p.itertext()).strip()
                    if re.fullmatch(r"[0-9][ABCDE]\d{3}(?:\.[a-z0-9]+)*\.?",text):roots.add(text[:5])
                    elif re.fullmatch(r"ML\d+",text):roots.add(text)
            if family=="dual_use":
                self.assertEqual(len(roots),386)
                self.assertNotIn("0D001",roots)
                roots.add("0D001")
            self.assertEqual(roots,{c["code"]for c in self.catalogue.by_family[family]if c["code"]})

    def test_structured_originals_are_final_notice_pairs_with_fixed_retrieval_dates(self):
        review=json.loads((self.root/"review/structured-source-verification.json").read_text(encoding="utf-8"))
        sources={s["source_id"]:s for s in self.catalogue.manifest["sources"]}
        body=(self.root/review["captured_body"]).read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(),review["captured_body_sha256"])
        for pair in review["pairs"]:
            source=sources[pair["source_id"]]
            self.assertTrue(source["retrieved_at"].startswith("2026-10-21"))
            self.assertEqual(source["notice_number"],"산업통상부고시 제2026-101호")
            self.assertEqual(source["effective_date"],"2026-09-01")
            self.assertEqual(source["sha256"],pair["original_sha256"])
            self.assertEqual(source["official_url"],pair["original_url"])
            self.assertEqual(source["retrieved_at"],pair["retrieved_at"])
            for field in("original_url","paired_pdf_url"):
                self.assertIn(re.search(r"flSeq=(\d+)",pair[field])[1].encode(),body)
        self.assertTrue(sources["dual-use-annex"]["retrieved_at"].startswith("2026-10-20"))
        self.assertEqual(self.report["support_counts"],dict(designation_or_control_items=507,
            complete_numeric_and_qualitative_ast=41,complete_qualitative_ast=49,
            partially_structured_with_unsupported=3,uninterpreted_original=414))


if __name__=="__main__":unittest.main()
