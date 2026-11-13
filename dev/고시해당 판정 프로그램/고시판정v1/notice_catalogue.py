"""고정 고시 기준본(kr-notices-v16-1) 오프라인 로더. 검증에 실패하면 예외로 끝낸다(fail-closed).

`resources/notices`(paths.notices_root())에 둔 원문·추출 기록·정규화 조건·검수 기록을 읽는다.
실행 중 웹에서 아무것도 받지 않는다. manifest에 적힌 파일 해시, 조항 정규 해시, 출처 날짜, 네 범위의
검수 완료(reviewed/full), 참조 무결성, 검수 집계를 모두 확인한 뒤에만 불변 객체를 돌려준다.

시뮬레이터 v17의 고시 로더를 옮겨 쓴 것이며 검증 방식은 같다. 표준 라이브러리와 이 프로그램의
`paths`만 쓴다. 시뮬레이터 모듈은 들여오지 않는다(고시 제목표는 이 안에 둔다).

조건 트리 구조:
    {"type": "all"|"any", "children": [...]}
    {"type": "not", "child": {...}}
    {"type": "numeric", "predicate_id", "text", "source_anchor", "subject", "operator", "threshold", "unit"}
    {"type": "qualitative"|"unsupported", "predicate_id", "text", "source_anchor", "subject", "reason"}
"""
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType

import paths

FAMILIES = frozenset(("advanced", "core", "dual_use", "military"))
# 공통 정의·주석 기록의 field 값. 이 값을 가진 기록은 참조 자료이며 독립 검토 항목이 아니다.
NOTE_FIELD = "공통정의·주석"
NUMERIC_OPERATORS = ("lt", "le", "eq", "ge", "gt")
MANIFEST_KEYS = frozenset(("catalogue_schema_version", "catalogue_id", "sources", "files", "clause_inventory"))
SOURCE_KEYS = frozenset((
    "source_id", "families", "title", "notice_number", "announcement_version", "announcement_date",
    "effective_date", "official_url", "retrieved_at", "relative_path", "sha256", "review_status", "coverage",
    "review_note"))
# 고시번호 → 고시 제목. 시뮬레이터 v17 영역 모듈의 제목표와 같은 내용을 이 모듈 안에 둔다.
NOTICE_TITLES = MappingProxyType({
    "산업통상자원부고시 제2025-71호": "국가첨단전략기술 지정 등에 관한 고시",
    "산업통상부고시 제2025-2호": "국가핵심기술 지정 등에 관한 고시",
    "산업통상부고시 제2026-101호": "전략물자수출입고시",
})
BODY_SOURCE_SUFFIX = "-body"
OFFICIAL_URL_PREFIXES = ("https://www.law.go.kr/", "https://law.go.kr/", "https://www.yestrade.go.kr/",
                         "https://www.motie.go.kr/")
CLAUSE_KEYS = frozenset(("clause_id", "source_id", "family", "code", "title", "field", "source_anchor", "text",
                         "qualifier_refs", "condition"))
REVIEW_PATHS = ("review/review.json", "review/structured-source-verification.json",
                "review/source-positions.json", "review/control-boundaries.json", "review/numeric-evidence.json")


class CatalogueError(ValueError):
    """로컬 고시 기준본이 없거나 불완전하거나 신뢰할 수 없다."""


def canonical_hash(value):
    """키 정렬·구분자 고정 JSON의 SHA256. manifest 지문과 조항 지문에 쓴다."""
    return hashlib.sha256(json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class Catalogue:
    """검증을 통과한 불변 기준본. manifest·조항은 MappingProxyType/tuple로 얼려 둔다."""
    manifest: Mapping
    fingerprint: str
    clauses: tuple
    by_family: Mapping

    def to_dict(self):
        """수정 가능한 깊은 복사본(JSON 직렬화용)."""
        return {"manifest": _thaw(self.manifest), "fingerprint": self.fingerprint,
                "clauses": _thaw(self.clauses), "by_family": _thaw(self.by_family)}


def _require(condition, message):
    if not condition:
        raise CatalogueError(message)


def _text(value, label, allow_empty=False):
    _require(isinstance(value, str) and (allow_empty or bool(value.strip())), f"Invalid {label}")


def _digest(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid SHA256")


def _path(root, relative):
    """manifest의 relative_path를 번들 안의 절대 경로로 바꾼다. 번들 밖으로 나가는 경로는 거부한다."""
    _text(relative, "relative_path")
    path = PurePosixPath(relative)
    _require("\\" not in relative and ":" not in relative and not path.is_absolute()
             and ".." not in path.parts and relative == path.as_posix(), "Unsafe catalogue relative_path")
    target = root.joinpath(*path.parts).resolve()
    _require(target.is_relative_to(root), "Catalogue path escapes bundle root")
    return target


def _pairs(pairs):
    output = {}
    for key, value in pairs:
        _require(key not in output, f"Duplicate JSON key: {key}")
        output[key] = value
    return output


def _reject_constant(value):
    raise CatalogueError("Non-finite JSON")


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CatalogueError(f"Cannot read catalogue JSON: {path.name}: {error}") from error


def _ast(node, predicate_ids, depth=0):
    """조건 트리의 구조를 검사하고 predicate_id 중복을 잡는다."""
    _require(depth < 128, "Condition AST nesting is too deep")
    _require(isinstance(node, dict), "Invalid condition AST")
    kind = node.get("type")
    if kind in ("all", "any"):
        _require(set(node) == {"type", "children"} and isinstance(node["children"], list) and node["children"],
                 "Empty/invalid AST children")
        for child in node["children"]:
            _ast(child, predicate_ids, depth + 1)
    elif kind == "not":
        _require(set(node) == {"type", "child"}, "Invalid AST not")
        _ast(node["child"], predicate_ids, depth + 1)
    elif kind in ("numeric", "qualitative", "unsupported"):
        keys = {"type", "predicate_id", "text", "source_anchor", "subject"}
        keys |= {"operator", "threshold", "unit"} if kind == "numeric" else {"reason"}
        _require(set(node) == keys, "Invalid AST leaf fields")
        for key in keys - {"type"}:
            _text(node[key], key)
        _require(node["predicate_id"] not in predicate_ids, "Duplicate predicate_id")
        predicate_ids.add(node["predicate_id"])
        if kind == "numeric":
            _require(node["operator"] in NUMERIC_OPERATORS, "Invalid numeric operator")
            try:
                _require(Decimal(node["threshold"]).is_finite(), "Non-finite numeric threshold")
            except InvalidOperation as error:
                raise CatalogueError("Invalid numeric threshold") from error
    else:
        raise CatalogueError("Unknown condition AST type")


def _condition_kinds(node):
    yield node["type"]
    for child in node.get("children", []):
        yield from _condition_kinds(child)
    if "child" in node:
        yield from _condition_kinds(node["child"])


def _review_counts(actual, expected, label):
    _require(isinstance(actual, dict) and set(actual) == set(expected)
             and all(type(value) is int and value >= 0 for value in actual.values()) and actual == expected,
             f"Review count mismatch: {label}")


def _validate_review(root, file_hashes, sources, clauses, by_id):
    """해시로 묶인 기존 검수 기록을 검증한다. 추출을 다시 하지는 않는다."""
    report, pairs_report, positions, boundaries, numeric = (_read_json(root / path) for path in REVIEW_PATHS)
    _require(isinstance(report, dict) and report.get("review_kind") == "source-coverage-and-conservative-normalization",
             "Missing or unfinished catalogue review")
    decisions = [c for c in clauses if c["field"] != NOTE_FIELD]
    designated = {family: [c for c in decisions if c["family"] == family] for family in ("advanced", "core")}
    codes = {family: {c["code"] for c in clauses if c["family"] == family and c["code"]}
             for family in ("dual_use", "military")}
    _review_counts(report.get("family_clause_counts"), dict(Counter(c["family"] for c in clauses)), "family clauses")
    _review_counts(report.get("designated_technology_counts"), {f: len(cs) for f, cs in designated.items()},
                   "designations")
    _review_counts(report.get("control_root_counts"), {f: len(cs) for f, cs in codes.items()}, "control roots")
    fields = report.get("designated_field_counts")
    _require(isinstance(fields, dict) and set(fields) == set(designated), "Missing reviewed designation fields")
    for family, items in designated.items():
        _review_counts(fields[family], dict(Counter(c["field"] for c in items)), family + " fields")
    kinds = [list(_condition_kinds(c["condition"])) for c in decisions]
    _review_counts(report.get("condition_node_counts"),
                   dict(Counter(k for c in clauses for k in _condition_kinds(c["condition"]))), "AST nodes")
    _review_counts(report.get("support_counts"), dict(
        designation_or_control_items=len(decisions),
        complete_numeric_and_qualitative_ast=sum("numeric" in k and "unsupported" not in k for k in kinds),
        complete_qualitative_ast=sum("numeric" not in k and "unsupported" not in k for k in kinds),
        partially_structured_with_unsupported=sum("unsupported" in k and len(k) > 1 for k in kinds),
        uninterpreted_original=sum(c["condition"]["type"] == "unsupported" for c in decisions)), "support")
    pages = {}
    for family in sorted(FAMILIES):
        name = family.replace("_", "-")
        path = f"extracted/{name}.pages.json"
        _require(path in file_hashes, "Review page evidence is not bound by manifest")
        records = _read_json(root / path)
        _require(isinstance(records, list) and records
                 and all(isinstance(p, dict) and type(p.get("page")) is int and p["page"] == i
                         for i, p in enumerate(records, 1)), "Invalid reviewed page inventory")
        pages[name] = len(records)
    _review_counts(report.get("source_page_counts"), pages, "source pages")
    _require(isinstance(positions, dict) and isinstance(positions.get("table_positions"), list)
             and positions["table_positions"] and isinstance(positions.get("control_positions"), dict),
             "Empty review position evidence")
    table_ids = set()
    for record in positions["table_positions"]:
        _require(isinstance(record, dict) and isinstance(record.get("clause_id"), str) and record["clause_id"] in by_id,
                 "Unknown reviewed table clause")
        clause = by_id[record["clause_id"]]
        _require(clause["family"] in designated and clause["field"] != NOTE_FIELD, "Reviewed table family mismatch")
        _digest(record.get("text_sha256"))
        table_ids.add(clause["clause_id"])
    _require(table_ids == {c["clause_id"] for cs in designated.values() for c in cs}, "Incomplete reviewed table clauses")
    _require(isinstance(boundaries, dict) and set(boundaries) == set(codes)
             and set(positions["control_positions"]) == set(codes), "Missing control review families")
    audits = report.get("independent_control_audit")
    position_counts = {}
    _require(isinstance(audits, dict) and set(audits) == set(codes), "Missing independent control review")
    for family, expected_codes in codes.items():
        records = positions["control_positions"][family]
        audit = audits[family]
        evidence = boundaries[family]
        _require(expected_codes and isinstance(records, list) and records
                 and all(isinstance(r, dict) and isinstance(r.get("code"), str) and isinstance(r.get("root_code"), str)
                         and r["root_code"] in expected_codes for r in records), "Invalid reviewed control positions")
        _require({r["root_code"] for r in records} == expected_codes, "Incomplete reviewed control positions")
        position_counts[family] = len(records)
        _require(isinstance(audit, dict) and isinstance(evidence, dict), "Invalid control review record")
        for key, value in (("root_code_count", len(expected_codes)), ("code_position_count", len(records)),
                           ("checked_boundaries", len(expected_codes))):
            _require(type(audit.get(key)) is int and audit[key] == value, f"Control review count mismatch: {key}")
        _require(type(audit.get("checked_category_transitions")) is int and audit["checked_category_transitions"] >= 0,
                 "Invalid category review count")
        for key in ("missing_from_normalized", "unexpected_normalized", "boundary_failures",
                    "category_assignment_failures"):
            _require(audit.get(key) == [], "Control review is incomplete")
        _require(all(evidence.get(key) == value for key, value in audit.items()),
                 "Control review evidence differs from summary")
        _require(isinstance(evidence.get("independent_source_positions"), list) and evidence["independent_source_positions"]
                 and isinstance(evidence.get("whole_paragraph_assignments"), list)
                 and evidence["whole_paragraph_assignments"]
                 and evidence.get("whole_paragraph_assignment_failures") == [],
                 "Empty or unfinished control review evidence")
        _require(len(evidence["independent_source_positions"]) == len(records)
                 and all(isinstance(r, dict) and isinstance(r.get("root_code"), str) and r["root_code"] in expected_codes
                         for r in evidence["independent_source_positions"]),
                 "Independent review control identity mismatch")
        _require(type(evidence.get("paragraph_count")) is int
                 and evidence["paragraph_count"] == len(evidence["whole_paragraph_assignments"]),
                 "Review paragraph count mismatch")
        owners = set()
        for assignment in evidence["whole_paragraph_assignments"]:
            _require(isinstance(assignment, dict) and isinstance(assignment.get("owner"), str)
                     and assignment["owner"] in by_id and by_id[assignment["owner"]]["family"] == family,
                     "Unknown reviewed paragraph owner")
            _text(assignment.get("paragraph_id"), "review paragraph_id")
            owners.add(assignment["owner"])
        _require({c["clause_id"] for c in clauses if c["family"] == family and c["code"]} <= owners,
                 "Incomplete reviewed control owners")
    _review_counts(report.get("code_position_counts"), position_counts, "code positions")
    _require(isinstance(numeric, list) and (numeric or not any("numeric" in k for k in kinds)),
             "Empty numeric review evidence")
    for record in numeric:
        _require(isinstance(record, dict)
                 and set(record) == {"clause_id", "source_anchor", "literal", "operator", "threshold", "unit"},
                 "Invalid numeric review fields")
        for key, value in record.items():
            _text(value, "numeric review " + key)
        _require(record["clause_id"] in by_id, "Unknown numeric review clause")
        _require(record["operator"] in NUMERIC_OPERATORS, "Invalid numeric review operator")
        try:
            _require(Decimal(record["threshold"]).is_finite(), "Non-finite numeric review threshold")
        except InvalidOperation as error:
            raise CatalogueError("Invalid numeric review threshold") from error
        _require(record["source_anchor"] == by_id[record["clause_id"]]["source_anchor"], "Numeric review source mismatch")
    _require(report.get("numeric_examples") == numeric, "Numeric review differs from summary")
    _require(isinstance(pairs_report, dict) and isinstance(pairs_report.get("pairs"), list) and pairs_report["pairs"],
             "Empty structured source review")
    body_path = pairs_report.get("captured_body")
    _text(body_path, "review captured_body")
    body_source = next((s for s in sources.values() if s["relative_path"] == body_path), None)
    _require(body_source is not None and pairs_report.get("captured_body_sha256") == file_hashes.get(body_path),
             "Reviewed body source/hash mismatch")
    try:
        body = (root / body_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CatalogueError("Cannot read reviewed notice body") from error
    seen = set()
    for pair in pairs_report["pairs"]:
        _require(isinstance(pair, dict) and isinstance(pair.get("source_id"), str)
                 and pair["source_id"] in sources and pair["source_id"] not in seen, "Unknown/duplicate reviewed source")
        source = sources[pair["source_id"]]
        seen.add(pair["source_id"])
        for key, source_key in (("original_relative_path", "relative_path"), ("original_url", "official_url"),
                                ("original_sha256", "sha256"), ("retrieved_at", "retrieved_at")):
            _require(pair.get(key) == source[source_key], f"Reviewed source mismatch: {key}")
        _require(set(source["families"]) <= set(body_source["families"]), "Reviewed notice family mismatch")
        for key in ("notice_number", "effective_date"):
            _require(pairs_report.get(key) == source[key] == body_source[key], f"Reviewed notice mismatch: {key}")
        pdf = pair.get("paired_pdf")
        _text(pdf, "review paired_pdf")
        _require(pdf in file_hashes and pair.get("paired_pdf_sha256") == file_hashes[pdf]
                 and pair.get("same_final_notice_links_present") is True, "Reviewed attachment hash/status mismatch")
        for key in ("original_url", "paired_pdf_url"):
            url = pair.get(key)
            _text(url, "review attachment URL")
            _require(url.startswith(OFFICIAL_URL_PREFIXES), "Non-official reviewed attachment URL")
            attachment = re.search(r"[?&]flSeq=(\d+)(?:&|$)", url)
            _require(attachment is not None and attachment[1] in body, "Reviewed attachment absent from captured notice")
        pdf_source = next((s for s in sources.values() if s["relative_path"] == pdf), None)
        if pdf_source is not None:
            _require(pair.get("paired_pdf_url") == pdf_source["official_url"]
                     and pdf_source["notice_number"] == source["notice_number"]
                     and pdf_source["effective_date"] == source["effective_date"]
                     and pdf_source["families"] == source["families"], "Reviewed PDF source mismatch")
    _require(seen == {s["source_id"] for s in sources.values() if s["relative_path"].lower().endswith(".hwpx")},
             "Incomplete structured source review")


def _validate_sources(manifest, file_hashes):
    """출처 필드·날짜·공식 URL·검수 상태를 검사하고 source_id → 출처 사전을 돌려준다."""
    sources = {}
    families = set()
    notices = {}
    _require(isinstance(manifest["sources"], list) and manifest["sources"], "Missing sources")
    for source in manifest["sources"]:
        _require(isinstance(source, dict) and set(source) == SOURCE_KEYS, "Invalid source fields")
        for key in SOURCE_KEYS - {"families"}:
            _text(source[key], key)
        _require(source["source_id"] not in sources, "Duplicate source_id")
        _require(isinstance(source["families"], list) and source["families"]
                 and all(isinstance(value, str) for value in source["families"])
                 and len(set(source["families"])) == len(source["families"])
                 and set(source["families"]) <= FAMILIES, "Invalid source families")
        _require(source["review_status"] == "reviewed" and source["coverage"] == "full",
                 "Catalogue source is not reviewed/full")
        try:
            _require(date.fromisoformat(source["effective_date"]).isoformat() == source["effective_date"],
                     "Invalid effective_date")
            retrieved = datetime.fromisoformat(source["retrieved_at"])
            _require(retrieved.utcoffset() is not None, "retrieved_at requires timezone")
        except ValueError as error:
            raise CatalogueError("Invalid source date") from error
        try:
            announced = date.fromisoformat(source["announcement_date"])
        except ValueError:
            announced = None
        _require(announced is not None and announced.isoformat() == source["announcement_date"],
                 "Invalid announcement_date")
        _require(announced <= date.fromisoformat(source["effective_date"]), "announcement_date is after effective_date")
        _require(source["notice_number"] in NOTICE_TITLES, "Unknown notice number")
        dates = (source["announcement_date"], source["effective_date"])
        notice = notices.setdefault(source["notice_number"], {"dates": dates, "bodies": 0})
        _require(notice["dates"] == dates, "Inconsistent notice dates")
        notice["bodies"] += source["source_id"].endswith(BODY_SOURCE_SUFFIX)
        _require(source["official_url"].startswith(OFFICIAL_URL_PREFIXES), "Non-official source URL")
        _require(file_hashes.get(source["relative_path"]) == source["sha256"], "Source file not bound by manifest")
        sources[source["source_id"]] = source
        families.update(source["families"])
    _require(all(notice["bodies"] == 1 for notice in notices.values()), "Each notice requires exactly one body source")
    _require(families == FAMILIES, "All four notice families must be reviewed/full")
    return sources


def _validate_files(root, manifest):
    """manifest의 파일 목록마다 실제 파일의 SHA256을 대조한다. 하나라도 다르면 경로를 담아 예외."""
    _require(isinstance(manifest["files"], list) and manifest["files"], "Missing file inventory")
    file_hashes = {}
    for record in manifest["files"]:
        _require(isinstance(record, dict) and set(record) == {"relative_path", "sha256"}, "Invalid file record")
        target = _path(root, record["relative_path"])
        _digest(record["sha256"])
        _require(record["relative_path"] not in file_hashes and target != root / "manifest.json",
                 "Duplicate/self-referential file record")
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as error:
            raise CatalogueError(f"Missing catalogue file: {record['relative_path']}") from error
        _require(actual == record["sha256"], f"Catalogue file hash mismatch: {record['relative_path']}")
        file_hashes[record["relative_path"]] = actual
    _require("normalized/clauses.json" in file_hashes, "Missing normalized clause inventory")
    _require(all(path in file_hashes for path in REVIEW_PATHS), "Missing manifest-bound catalogue review records")
    return file_hashes


def load_catalogue(root=None):
    """출처·무결성 검증을 모두 통과한 뒤에만 네 범위를 얼려서 돌려준다.

    root를 주지 않으면 `paths.notices_root()`(프로그램 자원 폴더의 복사본)를 읽는다.
    """
    if root is None:
        root = paths.notices_root()
    root = Path(root).resolve()
    manifest = _read_json(root / "manifest.json")
    _require(isinstance(manifest, dict) and set(manifest) == MANIFEST_KEYS, "Invalid manifest fields")
    _require(type(manifest["catalogue_schema_version"]) is int and manifest["catalogue_schema_version"] == 1,
             "Unsupported catalogue schema")
    _text(manifest["catalogue_id"], "catalogue_id")
    file_hashes = _validate_files(root, manifest)
    sources = _validate_sources(manifest, file_hashes)
    clauses = _read_json(root / "normalized/clauses.json")
    _require(isinstance(clauses, list) and clauses, "Empty clauses")
    by_id = {}
    predicates = set()
    by_family = {family: [] for family in sorted(FAMILIES)}
    for clause in clauses:
        _require(isinstance(clause, dict) and set(clause) == CLAUSE_KEYS, "Invalid clause fields")
        for key in CLAUSE_KEYS - {"qualifier_refs", "condition"}:
            _text(clause[key], key, allow_empty=key == "code")
        _require(clause["clause_id"] not in by_id, "Duplicate clause_id")
        source = sources.get(clause["source_id"])
        _require(source is not None and clause["family"] in source["families"], "Clause/source family mismatch")
        _require(clause["source_anchor"].startswith(source["relative_path"] + "#"), "Clause/source anchor mismatch")
        _require(isinstance(clause["qualifier_refs"], list)
                 and all(isinstance(x, str) and x for x in clause["qualifier_refs"])
                 and len(set(clause["qualifier_refs"])) == len(clause["qualifier_refs"]), "Invalid qualifier_refs")
        _ast(clause["condition"], predicates)
        by_id[clause["clause_id"]] = clause
        by_family[clause["family"]].append(clause)
    _require(all(by_family.values()), "Missing normalized family clauses")
    visited = set()
    visiting = set()

    def visit(identifier):
        _require(identifier in by_id, "Unresolved qualifier reference")
        _require(identifier not in visiting, "Cyclic qualifier reference")
        if identifier in visited:
            return
        visiting.add(identifier)
        for reference in by_id[identifier]["qualifier_refs"]:
            visit(reference)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in by_id:
        visit(identifier)
    _require(isinstance(manifest["clause_inventory"], list), "Invalid clause_inventory")
    inventory = {}
    for record in manifest["clause_inventory"]:
        _require(isinstance(record, dict) and set(record) == {"clause_id", "family", "sha256"},
                 "Invalid clause inventory record")
        _text(record["clause_id"], "inventory clause_id")
        _text(record["family"], "inventory family")
        _digest(record["sha256"])
        identifier = record["clause_id"]
        _require(identifier not in inventory and identifier in by_id, "Duplicate/unknown inventory clause")
        _require(record["family"] == by_id[identifier]["family"] and record["sha256"] == canonical_hash(by_id[identifier]),
                 "Clause inventory hash mismatch")
        inventory[identifier] = record
    _require(set(inventory) == set(by_id), "Incomplete clause inventory")
    _validate_review(root, file_hashes, sources, clauses, by_id)
    return Catalogue(_freeze(manifest), canonical_hash(manifest), tuple(_freeze(c) for c in clauses),
                     MappingProxyType({family: tuple(_freeze(c) for c in entries)
                                       for family, entries in by_family.items()}))


# ---------------------------------------------------------------------------
# 조회 함수. 모두 수정 가능한 복사본(dict/list)을 돌려주며 기준본 자체는 바뀌지 않는다.
# ---------------------------------------------------------------------------

def _find_clause(catalogue, clause_id):
    for clause in catalogue.clauses:
        if clause["clause_id"] == clause_id:
            return clause
    raise KeyError(clause_id)


def clause_index(catalogue):
    """실제 검토 항목(공통 정의·주석 제외)의 목록. 기준본 순서를 유지한다.

    원소: clause_id, family(advanced|core|dual_use|military), code(통제번호, 없으면 빈 글), title, field.
    """
    return [dict(clause_id=c["clause_id"], family=c["family"], code=c["code"], title=c["title"], field=c["field"])
            for c in catalogue.clauses if c["field"] != NOTE_FIELD]


def clause_record(catalogue, clause_id):
    """조항 하나의 원문·참조·조건 트리. 없으면 KeyError. 공통 정의·주석도 조회할 수 있다."""
    clause = _find_clause(catalogue, clause_id)
    return dict(clause_id=clause["clause_id"], text=clause["text"], qualifier_refs=_thaw(clause["qualifier_refs"]),
                condition=_thaw(clause["condition"]), family=clause["family"], code=clause["code"],
                title=clause["title"], field=clause["field"], source_anchor=clause["source_anchor"])


def note_records(catalogue):
    """공통 정의·주석 기록(field가 NOTE_FIELD인 것). 참조 자료이며 독립 검토 항목이 아니다."""
    return [dict(clause_id=c["clause_id"], text=c["text"], family=c["family"], title=c["title"])
            for c in catalogue.clauses if c["field"] == NOTE_FIELD]


def _walk_leaves(node, path):
    kind = node["type"]
    if kind in ("all", "any"):
        for child in node["children"]:
            yield from _walk_leaves(child, path + [kind])
    elif kind == "not":
        yield from _walk_leaves(node["child"], path + [kind])
    else:
        yield node, path


def numeric_leaves(catalogue):
    """모든 조항의 조건 트리에서 숫자 잎(type=numeric)을 모은다.

    원소: clause_id, predicate_id, subject, operator(lt|le|eq|ge|gt), threshold(문자열 그대로), unit, text,
    source_anchor, path(뿌리에서 잎까지 거친 all/any/not 목록, 뿌리가 잎이면 빈 목록).
    """
    leaves = []
    for clause in catalogue.clauses:
        for node, path in _walk_leaves(clause["condition"], []):
            if node["type"] != "numeric":
                continue
            leaves.append(dict(clause_id=clause["clause_id"], predicate_id=node["predicate_id"], subject=node["subject"],
                               operator=node["operator"], threshold=node["threshold"], unit=node["unit"],
                               text=node["text"], source_anchor=node["source_anchor"], path=list(path)))
    return leaves


def catalogue_summary(catalogue):
    """기준본 이름·지문·고시별 날짜·건수 요약(JSON 직렬화 가능)."""
    manifest = catalogue.manifest
    sources = []
    notices = {}
    for source in manifest["sources"]:
        sources.append(dict(
            source_id=source["source_id"], families=list(source["families"]), title=source["title"],
            notice_number=source["notice_number"], notice_title=NOTICE_TITLES[source["notice_number"]],
            announcement_version=source["announcement_version"], announcement_date=source["announcement_date"],
            effective_date=source["effective_date"], official_url=source["official_url"],
            retrieved_at=source["retrieved_at"], relative_path=source["relative_path"], sha256=source["sha256"]))
        notice = notices.setdefault(source["notice_number"], dict(
            notice_number=source["notice_number"], title=NOTICE_TITLES[source["notice_number"]],
            announcement_date=source["announcement_date"], effective_date=source["effective_date"], families=[]))
        for family in source["families"]:
            if family not in notice["families"]:
                notice["families"].append(family)
    items = clause_index(catalogue)
    notes = note_records(catalogue)
    return dict(
        catalogue_id=manifest["catalogue_id"], catalogue_schema_version=manifest["catalogue_schema_version"],
        fingerprint=catalogue.fingerprint, file_count=len(manifest["files"]),
        clause_count=len(catalogue.clauses), item_count=len(items), note_count=len(notes),
        numeric_leaf_count=len(numeric_leaves(catalogue)),
        family_item_counts={family: sum(1 for entry in items if entry["family"] == family) for family in sorted(FAMILIES)},
        family_note_counts={family: sum(1 for entry in notes if entry["family"] == family) for family in sorted(FAMILIES)},
        notices=list(notices.values()), sources=sources)
