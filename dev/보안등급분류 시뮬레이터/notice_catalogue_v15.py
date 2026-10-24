"""Offline, fail-closed loader for reviewed official notice catalogues.

No source is fetched at runtime. Raw documents, extraction records, conditions and
review reports are bound by one canonical manifest fingerprint.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from types import MappingProxyType
from collections.abc import Mapping
from collections import Counter

FAMILIES = frozenset(("advanced", "core", "dual_use", "military"))
MANIFEST_KEYS = frozenset(("catalogue_schema_version", "catalogue_id", "sources", "files", "clause_inventory"))
SOURCE_KEYS = frozenset(("source_id", "families", "title", "notice_number", "announcement_version", "effective_date", "official_url", "retrieved_at", "relative_path", "sha256", "review_status", "coverage", "review_note"))
CLAUSE_KEYS = frozenset(("clause_id", "source_id", "family", "code", "title", "field", "source_anchor", "text", "qualifier_refs", "condition"))
REVIEW_PATHS = ("review/review.json", "review/structured-source-verification.json",
    "review/source-positions.json", "review/control-boundaries.json", "review/numeric-evidence.json")


class CatalogueError(ValueError):
    """The local notice bundle is missing, incomplete or untrustworthy."""


def canonical_hash(value):
    return hashlib.sha256(json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _freeze(value):
    if isinstance(value, dict):return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if isinstance(value, list):return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):return {k:_thaw(v) for k,v in value.items()}
    if isinstance(value, tuple):return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class Catalogue:
    manifest: Mapping
    fingerprint: str
    clauses: tuple
    by_family: Mapping

    def to_dict(self):
        return {"manifest":_thaw(self.manifest), "fingerprint":self.fingerprint,
            "clauses":_thaw(self.clauses), "by_family":_thaw(self.by_family)}


def _require(condition, message):
    if not condition:raise CatalogueError(message)


def _text(value, label, allow_empty=False):
    _require(isinstance(value,str) and (allow_empty or bool(value.strip())), f"Invalid {label}")


def _digest(value):
    _require(isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value), "Invalid SHA256")


def _path(root, relative):
    _text(relative,"relative_path")
    path = PurePosixPath(relative)
    _require("\\" not in relative and ":" not in relative and not path.is_absolute()
        and ".." not in path.parts and relative==path.as_posix(), "Unsafe catalogue relative_path")
    target = root.joinpath(*path.parts).resolve()
    _require(target.is_relative_to(root), "Catalogue path escapes bundle root")
    return target


def _pairs(pairs):
    output={}
    for key,value in pairs:
        _require(key not in output, f"Duplicate JSON key: {key}")
        output[key]=value
    return output


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(CatalogueError("Non-finite JSON")))
    except (OSError,UnicodeError,json.JSONDecodeError,RecursionError) as error:
        raise CatalogueError(f"Cannot read catalogue JSON: {path.name}: {error}") from error


def _ast(node, predicate_ids, depth=0):
    _require(depth<128,"Condition AST nesting is too deep")
    _require(isinstance(node,dict),"Invalid condition AST")
    kind=node.get("type")
    if kind in ("all","any"):
        _require(set(node)=={"type","children"} and isinstance(node["children"],list) and node["children"],"Empty/invalid AST children")
        for child in node["children"]:_ast(child,predicate_ids,depth+1)
    elif kind=="not":
        _require(set(node)=={"type","child"},"Invalid AST not")
        _ast(node["child"],predicate_ids,depth+1)
    elif kind in ("numeric","qualitative","unsupported"):
        keys={"type","predicate_id","text","source_anchor","subject"}
        keys |= {"operator","threshold","unit"} if kind=="numeric" else {"reason"}
        _require(set(node)==keys,"Invalid AST leaf fields")
        for key in keys-{"type"}:_text(node[key],key)
        _require(node["predicate_id"] not in predicate_ids,"Duplicate predicate_id")
        predicate_ids.add(node["predicate_id"])
        if kind=="numeric":
            _require(node["operator"] in ("lt","le","eq","ge","gt"),"Invalid numeric operator")
            try:_require(Decimal(node["threshold"]).is_finite(),"Non-finite numeric threshold")
            except InvalidOperation as error:raise CatalogueError("Invalid numeric threshold") from error
    else:raise CatalogueError("Unknown condition AST type")


def _condition_kinds(node):
    yield node["type"]
    for child in node.get("children",[]):yield from _condition_kinds(child)
    if "child"in node:yield from _condition_kinds(node["child"])


def _review_counts(actual,expected,label):
    _require(isinstance(actual,dict)and set(actual)==set(expected)
        and all(type(value)is int and value>=0 for value in actual.values())and actual==expected,
        f"Review count mismatch: {label}")


def _validate_review(root,file_hashes,sources,clauses,by_id):
    """Validate the existing, hash-bound review results; do not repeat extraction."""
    report,pairs_report,positions,boundaries,numeric=(_read_json(root/path)for path in REVIEW_PATHS)
    _require(isinstance(report,dict)and report.get("review_kind")=="source-coverage-and-conservative-normalization",
        "Missing or unfinished catalogue review")
    decisions=[c for c in clauses if c["field"]!="공통정의·주석"]
    designated={family:[c for c in decisions if c["family"]==family]for family in("advanced","core")}
    codes={family:{c["code"]for c in clauses if c["family"]==family and c["code"]}for family in("dual_use","military")}
    _review_counts(report.get("family_clause_counts"),dict(Counter(c["family"]for c in clauses)),"family clauses")
    _review_counts(report.get("designated_technology_counts"),{f:len(cs)for f,cs in designated.items()},"designations")
    _review_counts(report.get("control_root_counts"),{f:len(cs)for f,cs in codes.items()},"control roots")
    fields=report.get("designated_field_counts")
    _require(isinstance(fields,dict)and set(fields)==set(designated),"Missing reviewed designation fields")
    for family,items in designated.items():
        _review_counts(fields[family],dict(Counter(c["field"]for c in items)),family+" fields")
    kinds=[list(_condition_kinds(c["condition"]))for c in decisions]
    _review_counts(report.get("condition_node_counts"),dict(Counter(k for c in clauses for k in _condition_kinds(c["condition"]))),"AST nodes")
    _review_counts(report.get("support_counts"),dict(designation_or_control_items=len(decisions),
        complete_numeric_and_qualitative_ast=sum("numeric"in k and "unsupported"not in k for k in kinds),
        complete_qualitative_ast=sum("numeric"not in k and "unsupported"not in k for k in kinds),
        partially_structured_with_unsupported=sum("unsupported"in k and len(k)>1 for k in kinds),
        uninterpreted_original=sum(c["condition"]["type"]=="unsupported"for c in decisions)),"support")
    pages={}
    for family in sorted(FAMILIES):
        name=family.replace("_","-");path=f"extracted/{name}.pages.json"
        _require(path in file_hashes,"Review page evidence is not bound by manifest")
        records=_read_json(root/path)
        _require(isinstance(records,list)and records and all(isinstance(p,dict)and type(p.get("page"))is int
            and p["page"]==i for i,p in enumerate(records,1)),"Invalid reviewed page inventory")
        pages[name]=len(records)
    _review_counts(report.get("source_page_counts"),pages,"source pages")
    _require(isinstance(positions,dict)and isinstance(positions.get("table_positions"),list)
        and positions["table_positions"]and isinstance(positions.get("control_positions"),dict),"Empty review position evidence")
    table_ids=set()
    for record in positions["table_positions"]:
        _require(isinstance(record,dict)and isinstance(record.get("clause_id"),str)
            and record["clause_id"]in by_id,"Unknown reviewed table clause")
        clause=by_id[record["clause_id"]]
        _require(clause["family"]in designated and clause["field"]!="공통정의·주석","Reviewed table family mismatch")
        _digest(record.get("text_sha256"));table_ids.add(clause["clause_id"])
    _require(table_ids=={c["clause_id"]for cs in designated.values()for c in cs},"Incomplete reviewed table clauses")
    _require(isinstance(boundaries,dict)and set(boundaries)==set(codes)
        and set(positions["control_positions"])==set(codes),"Missing control review families")
    audits=report.get("independent_control_audit");position_counts={}
    _require(isinstance(audits,dict)and set(audits)==set(codes),"Missing independent control review")
    for family,expected_codes in codes.items():
        records=positions["control_positions"][family];audit=audits[family];evidence=boundaries[family]
        _require(expected_codes and isinstance(records,list)and records and all(isinstance(r,dict)
            and isinstance(r.get("code"),str)and isinstance(r.get("root_code"),str)
            and r["root_code"]in expected_codes for r in records),"Invalid reviewed control positions")
        _require({r["root_code"]for r in records}==expected_codes,"Incomplete reviewed control positions")
        position_counts[family]=len(records)
        _require(isinstance(audit,dict)and isinstance(evidence,dict),"Invalid control review record")
        for key,value in(("root_code_count",len(expected_codes)),("code_position_count",len(records)),("checked_boundaries",len(expected_codes))):
            _require(type(audit.get(key))is int and audit[key]==value,f"Control review count mismatch: {key}")
        _require(type(audit.get("checked_category_transitions"))is int and audit["checked_category_transitions"]>=0,"Invalid category review count")
        for key in("missing_from_normalized","unexpected_normalized","boundary_failures","category_assignment_failures"):
            _require(audit.get(key)==[],"Control review is incomplete")
        _require(all(evidence.get(key)==value for key,value in audit.items()),"Control review evidence differs from summary")
        _require(isinstance(evidence.get("independent_source_positions"),list)and evidence["independent_source_positions"]
            and isinstance(evidence.get("whole_paragraph_assignments"),list)and evidence["whole_paragraph_assignments"]
            and evidence.get("whole_paragraph_assignment_failures")==[],"Empty or unfinished control review evidence")
        _require(len(evidence["independent_source_positions"])==len(records)and all(isinstance(r,dict)
            and isinstance(r.get("root_code"),str)and r["root_code"]in expected_codes
            for r in evidence["independent_source_positions"]),"Independent review control identity mismatch")
        _require(type(evidence.get("paragraph_count"))is int
            and evidence["paragraph_count"]==len(evidence["whole_paragraph_assignments"]),"Review paragraph count mismatch")
        owners=set()
        for assignment in evidence["whole_paragraph_assignments"]:
            _require(isinstance(assignment,dict)and isinstance(assignment.get("owner"),str)and assignment["owner"]in by_id
                and by_id[assignment["owner"]]["family"]==family,"Unknown reviewed paragraph owner")
            _text(assignment.get("paragraph_id"),"review paragraph_id")
            owners.add(assignment["owner"])
        _require({c["clause_id"]for c in clauses if c["family"]==family and c["code"]}<=owners,"Incomplete reviewed control owners")
    _review_counts(report.get("code_position_counts"),position_counts,"code positions")
    _require(isinstance(numeric,list)and (numeric or not any("numeric"in k for k in kinds)),"Empty numeric review evidence")
    for record in numeric:
        _require(isinstance(record,dict)and set(record)=={"clause_id","source_anchor","literal","operator","threshold","unit"},
            "Invalid numeric review fields")
        for key,value in record.items():_text(value,"numeric review "+key)
        _require(record["clause_id"]in by_id,"Unknown numeric review clause")
        _require(record["operator"]in("lt","le","eq","ge","gt"),"Invalid numeric review operator")
        try:_require(Decimal(record["threshold"]).is_finite(),"Non-finite numeric review threshold")
        except InvalidOperation as error:raise CatalogueError("Invalid numeric review threshold")from error
        _require(record["source_anchor"]==by_id[record["clause_id"]]["source_anchor"],"Numeric review source mismatch")
    _require(report.get("numeric_examples")==numeric,"Numeric review differs from summary")
    _require(isinstance(pairs_report,dict)and isinstance(pairs_report.get("pairs"),list)
        and pairs_report["pairs"],"Empty structured source review")
    body_path=pairs_report.get("captured_body");_text(body_path,"review captured_body")
    body_source=next((s for s in sources.values()if s["relative_path"]==body_path),None)
    _require(body_source is not None and pairs_report.get("captured_body_sha256")==file_hashes.get(body_path),"Reviewed body source/hash mismatch")
    try:body=(root/body_path).read_text(encoding="utf-8")
    except (OSError,UnicodeError)as error:raise CatalogueError("Cannot read reviewed notice body")from error
    seen=set()
    for pair in pairs_report["pairs"]:
        _require(isinstance(pair,dict)and isinstance(pair.get("source_id"),str)
            and pair["source_id"]in sources and pair["source_id"]not in seen,"Unknown/duplicate reviewed source")
        source=sources[pair["source_id"]];seen.add(pair["source_id"])
        for key,source_key in(("original_relative_path","relative_path"),("original_url","official_url"),
                ("original_sha256","sha256"),("retrieved_at","retrieved_at")):
            _require(pair.get(key)==source[source_key],f"Reviewed source mismatch: {key}")
        _require(set(source["families"])<=set(body_source["families"]),"Reviewed notice family mismatch")
        for key in("notice_number","effective_date"):
            _require(pairs_report.get(key)==source[key]==body_source[key],f"Reviewed notice mismatch: {key}")
        pdf=pair.get("paired_pdf");_text(pdf,"review paired_pdf")
        _require(pdf in file_hashes and pair.get("paired_pdf_sha256")==file_hashes[pdf]
            and pair.get("same_final_notice_links_present")is True,"Reviewed attachment hash/status mismatch")
        for key in("original_url","paired_pdf_url"):
            url=pair.get(key);_text(url,"review attachment URL")
            _require(url.startswith(("https://www.law.go.kr/","https://law.go.kr/","https://www.yestrade.go.kr/","https://www.motie.go.kr/")),"Non-official reviewed attachment URL")
            attachment=re.search(r"[?&]flSeq=(\d+)(?:&|$)",url)
            _require(attachment is not None and attachment[1]in body,"Reviewed attachment absent from captured notice")
        pdf_source=next((s for s in sources.values()if s["relative_path"]==pdf),None)
        if pdf_source is not None:
            _require(pair.get("paired_pdf_url")==pdf_source["official_url"]and pdf_source["notice_number"]==source["notice_number"]
                and pdf_source["effective_date"]==source["effective_date"]and pdf_source["families"]==source["families"],"Reviewed PDF source mismatch")
    _require(seen=={s["source_id"]for s in sources.values()if s["relative_path"].lower().endswith(".hwpx")},"Incomplete structured source review")


def load_catalogue(root=None):
    """Load and freeze all four scopes only after provenance/integrity validation."""
    if root is None:
        base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))
        root=base/"resources_v15"/"notices"
    root=Path(root).resolve()
    manifest=_read_json(root/"manifest.json")
    _require(isinstance(manifest,dict) and set(manifest)==MANIFEST_KEYS,"Invalid manifest fields")
    _require(type(manifest["catalogue_schema_version"]) is int and manifest["catalogue_schema_version"]==1,"Unsupported catalogue schema")
    _text(manifest["catalogue_id"],"catalogue_id")
    _require(isinstance(manifest["files"],list) and manifest["files"],"Missing file inventory")
    file_hashes={}
    for record in manifest["files"]:
        _require(isinstance(record,dict) and set(record)=={"relative_path","sha256"},"Invalid file record")
        target=_path(root,record["relative_path"]);_digest(record["sha256"])
        _require(record["relative_path"] not in file_hashes and target!=root/"manifest.json","Duplicate/self-referential file record")
        try:actual=hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as error:raise CatalogueError(f"Missing catalogue file: {record['relative_path']}") from error
        _require(actual==record["sha256"],f"Catalogue file hash mismatch: {record['relative_path']}")
        file_hashes[record["relative_path"]]=actual
    _require("normalized/clauses.json" in file_hashes,"Missing normalized clause inventory")
    _require(all(path in file_hashes for path in REVIEW_PATHS),"Missing manifest-bound catalogue review records")
    sources={};families=set()
    _require(isinstance(manifest["sources"],list) and manifest["sources"],"Missing sources")
    for source in manifest["sources"]:
        _require(isinstance(source,dict) and set(source)==SOURCE_KEYS,"Invalid source fields")
        for key in SOURCE_KEYS-{"families"}:_text(source[key],key)
        _require(source["source_id"] not in sources,"Duplicate source_id")
        _require(isinstance(source["families"],list) and source["families"] and all(isinstance(value,str)for value in source["families"]) and len(set(source["families"]))==len(source["families"])
            and set(source["families"])<=FAMILIES,"Invalid source families")
        _require(source["review_status"]=="reviewed" and source["coverage"]=="full","Catalogue source is not reviewed/full")
        try:
            _require(date.fromisoformat(source["effective_date"]).isoformat()==source["effective_date"],"Invalid effective_date")
            retrieved=datetime.fromisoformat(source["retrieved_at"])
            _require(retrieved.utcoffset() is not None,"retrieved_at requires timezone")
        except ValueError as error:raise CatalogueError("Invalid source date") from error
        _require(source["official_url"].startswith(("https://www.law.go.kr/","https://law.go.kr/","https://www.yestrade.go.kr/","https://www.motie.go.kr/")),"Non-official source URL")
        _require(file_hashes.get(source["relative_path"])==source["sha256"],"Source file not bound by manifest")
        sources[source["source_id"]]=source;families.update(source["families"])
    _require(families==FAMILIES,"All four notice families must be reviewed/full")
    clauses=_read_json(root/"normalized/clauses.json")
    _require(isinstance(clauses,list) and clauses,"Empty clauses")
    by_id={};predicates=set();by_family={family:[] for family in sorted(FAMILIES)}
    for clause in clauses:
        _require(isinstance(clause,dict) and set(clause)==CLAUSE_KEYS,"Invalid clause fields")
        for key in CLAUSE_KEYS-{"qualifier_refs","condition"}:_text(clause[key],key,allow_empty=key=="code")
        _require(clause["clause_id"] not in by_id,"Duplicate clause_id")
        source=sources.get(clause["source_id"])
        _require(source is not None and clause["family"] in source["families"],"Clause/source family mismatch")
        _require(clause["source_anchor"].startswith(source["relative_path"]+"#"),"Clause/source anchor mismatch")
        _require(isinstance(clause["qualifier_refs"],list) and all(isinstance(x,str) and x for x in clause["qualifier_refs"])
            and len(set(clause["qualifier_refs"]))==len(clause["qualifier_refs"]),"Invalid qualifier_refs")
        _ast(clause["condition"],predicates)
        by_id[clause["clause_id"]]=clause;by_family[clause["family"]].append(clause)
    _require(all(by_family.values()),"Missing normalized family clauses")
    visited=set();visiting=set()
    def visit(identifier):
        _require(identifier in by_id,"Unresolved qualifier reference")
        _require(identifier not in visiting,"Cyclic qualifier reference")
        if identifier in visited:return
        visiting.add(identifier)
        for reference in by_id[identifier]["qualifier_refs"]:visit(reference)
        visiting.remove(identifier);visited.add(identifier)
    for identifier in by_id:visit(identifier)
    _require(isinstance(manifest["clause_inventory"],list),"Invalid clause_inventory")
    inventory={}
    for record in manifest["clause_inventory"]:
        _require(isinstance(record,dict) and set(record)=={"clause_id","family","sha256"},"Invalid clause inventory record")
        _text(record["clause_id"],"inventory clause_id");_text(record["family"],"inventory family")
        _digest(record["sha256"]);identifier=record["clause_id"]
        _require(identifier not in inventory and identifier in by_id,"Duplicate/unknown inventory clause")
        _require(record["family"]==by_id[identifier]["family"] and record["sha256"]==canonical_hash(by_id[identifier]),"Clause inventory hash mismatch")
        inventory[identifier]=record
    _require(set(inventory)==set(by_id),"Incomplete clause inventory")
    _validate_review(root,file_hashes,sources,clauses,by_id)
    return Catalogue(_freeze(manifest),canonical_hash(manifest),tuple(_freeze(c) for c in clauses),
        MappingProxyType({family:tuple(_freeze(c) for c in entries) for family,entries in by_family.items()}))
