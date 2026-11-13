"""기준값 표 생성 도구(개발 전용, exe에 넣지 않는다). spec 4장.

하는 일
  ① 고시 기준본의 숫자 조건(structured, 41개 항목 57개 잎)을 조건 트리에서 갈래(OR)·기준(AND)으로 옮긴다.
     - all = 갈래 안 AND, any = 갈래. any 아래 숫자 없는 대안은 숫자 없는 갈래(text)가 된다.
     - 모든 갈래에 공통인 정성 조건과 not 아래 조건은 checks로, 갈래마다 다른 정성 조건은 그 갈래의 label로 간다.
     - operator eq는 ge로 옮기고 그 잎 원문을 checks에 함께 둔다(기준을 넘는 쪽을 놓치지 않는 원칙).
     - 이미 검수된 것이므로 4.2 검증은 적용하지 않고 잎의 text를 quote로 쓴다. unit은 표준 표기로 바꾼다.
  ② tools/extracted/*.json(추출 파일, 형식은 tools/extracted/README.md)을 읽어 합친다.
  ③ 추출 기준값마다 4.2 검증을 하고, 어긋나면 rejected에 사유와 함께 옮긴다(조용히 버리지 않는다).
  ④ 507개 실제 검토 항목이 모두 있는지 확인한다. structured도 추출도 없는 항목은 누락이며 표를 만들지 않는다.
     첨단 항목에는 본문 제4조(advanced:article:4)의 양산 목적 조건을 checks에 항상 넣는다.
  ⑤ resources/thresholds.json과 tools/output/기준값_검수.xlsx를 쓴다. 범위별 건수를 콘솔에도 낸다.

`--check <추출 파일>`: 그 파일만 검증하고 누락 검사는 그 파일의 범위로만 한다. 아무 파일도 쓰지 않는다.
문제(누락·채택 실패·파일 오류)가 있으면 종료 코드 ≠ 0.

사용:  python tools/build_threshold_table.py [--check 파일] [--notices-root 폴더] [--extracted-dir 폴더]
                                              [--output thresholds.json] [--review-xlsx 검수.xlsx]
"""
import argparse
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

PROGRAM_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import paths  # noqa: E402
from notice_catalogue import FAMILIES, NOTE_FIELD, canonical_hash, clause_index, clause_record, load_catalogue  # noqa: E402
from threshold_table import (  # noqa: E402
    BODY_SOURCE,
    OPERATORS,
    STATUS_FAILED,
    STATUS_HAS,
    STATUS_NONE,
    expected_status,
    table_fingerprint,
    validate_record,
)
from units import aliases_of, normalize_unit  # noqa: E402

NEAR_PERCENT = 10  # 참고용. 판정 엔진이 '근접' 폭으로 쓴다.
ADVANCED_ARTICLE_4 = "advanced:article:4"
KO_MARKER = "[국문 원문]"
DEFAULT_EXTRACTED_DIR = PROGRAM_ROOT / "tools" / "extracted"
DEFAULT_REVIEW_PATH = PROGRAM_ROOT / "tools" / "output" / "기준값_검수.xlsx"
CODE_PREFIXES = frozenset("0123456789")
# 비교어 → operator. 긴 어구부터 맞추고 맞춘 자리는 가려서 짧은 어구가 겹쳐 잡히지 않게 한다.
COMPARATORS = (
    ("greater than or equal to", "ge"), ("less than or equal to", "le"), ("equal to or greater than", "ge"),
    ("equal to or less than", "le"), ("not exceeding", "le"), ("not more than", "le"), ("no more than", "le"),
    ("not less than", "ge"), ("no less than", "ge"), ("does not exceed", "le"), ("do not exceed", "le"),
    ("exceeding", "gt"), ("exceeds", "gt"), ("exceed", "gt"), ("more than", "gt"), ("greater than", "gt"),
    ("larger than", "gt"), ("higher than", "gt"), ("above", "gt"), ("in excess of", "gt"),
    ("less than", "lt"), ("smaller than", "lt"), ("lower than", "lt"), ("below", "lt"), ("under", "lt"),
    ("or more", "ge"), ("or greater", "ge"), ("or higher", "ge"), ("or larger", "ge"), ("or better", "ge"),
    ("at least", "ge"), ("minimum of", "ge"), ("or less", "le"), ("or smaller", "le"), ("or lower", "le"),
    ("at most", "le"), ("up to", "le"), ("maximum of", "le"),
    ("넘지 않는", "le"), ("넘지 못하는", "le"), ("넘지않는", "le"), ("넘는", "gt"), ("넘어서는", "gt"), ("초과", "gt"),
    ("이상", "ge"), ("이하", "le"), ("미만", "lt"), ("못 미치는", "lt"), ("못미치는", "lt"), ("미치지 못하는", "lt"),
    ("이내", "le"), ("보다 큰", "gt"), ("보다 높은", "gt"), ("보다 많은", "gt"), ("보다 작은", "lt"), ("보다 낮은", "lt"),
    ("보다 적은", "lt"),
    ("≥", "ge"), ("≧", "ge"), ("≤", "le"), ("≦", "le"), (">=", "ge"), ("<=", "le"), (">", "gt"), ("<", "lt"),
)
_COMPARATORS_BY_LENGTH = sorted(COMPARATORS, key=lambda pair: -len(pair[0]))
OPERATOR_WORDS = {"ge": "이상", "gt": "초과", "le": "이하", "lt": "미만"}
KOREAN_MULTIPLIERS = {"억": Decimal(100000000), "만": Decimal(10000), "천": Decimal(1000), "백": Decimal(100)}
NUMBER_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(억|만|천|백)?")


class ExtractionFileError(ValueError):
    """추출 파일의 형식이 틀리다(내용 검증 실패와 구분한다)."""


# ---------------------------------------------------------------------------
# 입력 보기
# ---------------------------------------------------------------------------

@dataclass
class CatalogueView:
    """도구가 쓰는 기준본 보기. 시험에서는 합성 자료로 직접 만든다."""
    catalogue_id: str
    fingerprint: str
    items: list          # clause_index 결과(실제 검토 항목, 기준본 순서)
    clauses: dict        # clause_id → clause_record 결과(공통 정의·주석 포함)

    @classmethod
    def from_catalogue(cls, catalogue):
        items = clause_index(catalogue)
        clauses = {c["clause_id"]: clause_record(catalogue, c["clause_id"]) for c in catalogue.clauses}
        return cls(catalogue_id=catalogue.manifest["catalogue_id"], fingerprint=catalogue.fingerprint, items=items,
                   clauses=clauses)


@dataclass
class ExtractedFile:
    path: str
    families: frozenset
    code_prefixes: frozenset   # 빈 집합이면 통제번호 제한 없음
    items: dict                # clause_id → 항목(파일 순서 유지)

    def covers(self, item):
        if item["family"] not in self.families:
            return False
        if item["family"] == "dual_use" and self.code_prefixes:
            return bool(item["code"]) and item["code"][0] in self.code_prefixes
        return True


def _fail(condition, message):
    if not condition:
        raise ExtractionFileError(message)


def _is_text(value):
    return isinstance(value, str)


def read_extracted(payload, path):
    """추출 파일 내용(dict)을 검사해 ExtractedFile로 만든다. 형식이 틀리면 ExtractionFileError(ValueError)."""
    label = str(path)
    _fail(isinstance(payload, dict) and set(payload) == {"scope", "items"}, f"{label}: 최상위는 scope·items 두 키여야 한다")
    scope = payload["scope"]
    _fail(isinstance(scope, dict) and "families" in scope and set(scope) <= {"families", "code_prefixes"},
          f"{label}: scope는 families(필수)·code_prefixes만 가진다")
    families = scope["families"]
    _fail(isinstance(families, list) and families and all(f in FAMILIES for f in families)
          and len(set(families)) == len(families), f"{label}: scope.families 값이 틀리다: {families!r}")
    prefixes = scope.get("code_prefixes", [])
    _fail(isinstance(prefixes, list) and all(_is_text(p) and p in CODE_PREFIXES for p in prefixes)
          and len(set(prefixes)) == len(prefixes), f"{label}: scope.code_prefixes는 '0'~'9' 한 글자 목록이어야 한다")
    _fail(not prefixes or "dual_use" in families, f"{label}: code_prefixes는 dual_use 범위에만 쓴다")
    _fail(isinstance(payload["items"], list), f"{label}: items가 목록이 아니다")
    items = {}
    for position, item in enumerate(payload["items"], 1):
        where = f"{label} items[{position}]"
        _fail(isinstance(item, dict) and {"clause_id", "branches", "checks"} <= set(item)
              and set(item) <= {"clause_id", "title", "branches", "checks"},
              f"{where}: clause_id·branches·checks(필수)·title(선택)만 가진다")
        clause_id = item["clause_id"]
        _fail(_is_text(clause_id) and clause_id.strip(), f"{where}: clause_id가 비어 있다")
        _fail(clause_id not in items, f"{label}: 같은 항목이 두 번 있다: {clause_id}")
        _fail("title" not in item or _is_text(item["title"]), f"{where}: title은 글이어야 한다")
        _fail(isinstance(item["branches"], list) and isinstance(item["checks"], list),
              f"{where}: branches·checks는 목록이어야 한다")
        for b, branch in enumerate(item["branches"], 1):
            bwhere = f"{where} branches[{b}]"
            _fail(isinstance(branch, dict) and {"thresholds"} <= set(branch)
                  and set(branch) <= {"branch_id", "label", "thresholds", "text"}, f"{bwhere}: 갈래 필드가 틀리다")
            _fail(all(_is_text(branch.get(key, "")) for key in ("branch_id", "label", "text")),
                  f"{bwhere}: branch_id·label·text는 글이어야 한다")
            _fail(isinstance(branch["thresholds"], list) and all(isinstance(t, dict) for t in branch["thresholds"]),
                  f"{bwhere}: thresholds는 기준값 목록이어야 한다")
            text = branch.get("text", "")
            _fail(branch["thresholds"] or text.strip(), f"{bwhere}: 기준값도 원문(text)도 없는 갈래")
            _fail(not (branch["thresholds"] and text.strip()), f"{bwhere}: 숫자 갈래에는 text를 쓰지 않는다")
            for t, threshold in enumerate(branch["thresholds"], 1):
                _fail(set(threshold) == {"subject", "operator", "value", "unit", "quote", "quote_source"},
                      f"{bwhere} thresholds[{t}]: subject·operator·value·unit·quote·quote_source 여섯 필드여야 한다")
                _fail(all(_is_text(threshold[key]) for key in ("subject", "operator", "unit", "quote", "quote_source")),
                      f"{bwhere} thresholds[{t}]: 필드 값은 글이어야 한다(value는 10진수 문자열)")
        for k, check in enumerate(item["checks"], 1):
            _fail(isinstance(check, dict) and set(check) == {"quote", "source"} and _is_text(check["quote"])
                  and _is_text(check["source"]), f"{where} checks[{k}]: quote·source 두 글 필드여야 한다")
        items[clause_id] = item
    return ExtractedFile(path=label, families=frozenset(families), code_prefixes=frozenset(prefixes), items=items)


def read_extracted_path(path):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExtractionFileError(f"{path}: 읽을 수 없다: {error}") from error
    return read_extracted(payload, path.name)


# ---------------------------------------------------------------------------
# 4.2 검증 도우미
# ---------------------------------------------------------------------------

def squeeze(text):
    """공백·줄바꿈을 연속 공백 하나로 맞춘다. 그 밖의 글자는 그대로."""
    return " ".join(str(text).split())


def numbers_in(text):
    """글 안의 수(Decimal 집합). 쉼표 자리 구분과 만·천·억·백 수사를 같은 수로 본다(예: 1만5천 = 15000)."""
    found = set()
    run_total = Decimal(0)
    run_end = None
    run_rank = None
    ranks = {"억": 4, "만": 3, "천": 2, "백": 1}
    for match in NUMBER_RE.finditer(text):
        digits = match.group(1).rstrip(",").replace(",", "")
        try:
            number = Decimal(digits)
        except InvalidOperation:
            continue
        suffix = match.group(2)
        if suffix:
            number *= KOREAN_MULTIPLIERS[suffix]
            rank = ranks[suffix]
            if run_end == match.start() and run_rank is not None and rank < run_rank:
                run_total += number
                found.add(run_total)
            else:
                run_total = number
            run_end, run_rank = match.end(), rank
        else:
            run_end = run_rank = None
        found.add(number)
    return found


def comparators_in(text):
    """글 안의 비교어가 뜻하는 operator 집합."""
    lowered = text.lower()
    found = set()
    for phrase, operator in _COMPARATORS_BY_LENGTH:
        start = 0
        while True:
            index = lowered.find(phrase, start)
            if index < 0:
                break
            found.add(operator)
            lowered = lowered[:index] + "\x00" * len(phrase) + lowered[index + len(phrase):]
            start = index + len(phrase)
    return found


def unit_mentioned(unit, quote):
    """quote 안에 unit의 표준 표기나 별칭이 있는가. 영문 한 글자 별칭(s·h·d 등)은 너무 흔해 인정하지 않는다."""
    raw = unit.strip()
    candidates = [name for name in aliases_of(unit) if len(name) >= 2 or not name.isascii()]
    if raw:
        candidates.append(raw)
    return any(name in quote for name in candidates)


# ---------------------------------------------------------------------------
# structured 조건 트리 → 갈래
# ---------------------------------------------------------------------------

def _leaves_under(node):
    if node["type"] in ("all", "any"):
        for child in node["children"]:
            yield from _leaves_under(child)
    elif node["type"] == "not":
        yield from _leaves_under(node["child"])
    else:
        yield node


def _flatten(node):
    """(갈래 목록, checks 잎 목록). 갈래 = {'numeric': [잎], 'quals': [잎]}."""
    kind = node["type"]
    if kind == "numeric":
        return [dict(numeric=[node], quals=[])], []
    if kind in ("qualitative", "unsupported"):
        return [dict(numeric=[], quals=[node])], []
    if kind == "not":
        return [dict(numeric=[], quals=[])], list(_leaves_under(node["child"]))
    branches = [] if kind == "any" else [dict(numeric=[], quals=[])]
    checks = []
    for child in node["children"]:
        child_branches, child_checks = _flatten(child)
        checks.extend(child_checks)
        if kind == "any":
            branches.extend(child_branches)
        else:
            branches = [dict(numeric=a["numeric"] + b["numeric"], quals=a["quals"] + b["quals"])
                        for a in branches for b in child_branches]
    return branches, checks


def structured_branches(clause):
    """숫자 잎이 있는 항목의 조건 트리를 갈래로 옮긴다. 숫자 잎이 없으면 None."""
    if not any(leaf["type"] == "numeric" for leaf in _leaves_under(clause["condition"])):
        return None
    branches, checks = _flatten(clause["condition"])
    if len(branches) > 1:
        common = [q["predicate_id"] for q in branches[0]["quals"]
                  if all(q["predicate_id"] in {x["predicate_id"] for x in b["quals"]} for b in branches[1:])]
        shared = [q for q in branches[0]["quals"] if q["predicate_id"] in common]
        for branch in branches:
            branch["quals"] = [q for q in branch["quals"] if q["predicate_id"] not in common]
        checks = shared + checks
    else:
        checks = branches[0]["quals"] + checks
        branches[0]["quals"] = []
    return branches, checks


# ---------------------------------------------------------------------------
# 기록 만들기
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    records: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    rejected: list = field(default_factory=list)   # (clause_id, family, title, rejected 기록)
    counts: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.errors and not self.missing


class _RecordBuilder:
    def __init__(self, view, item, clause):
        self.view = view
        self.item = item
        self.clause = clause
        self.clause_id = item["clause_id"]
        self.branch_count = 0
        self.branches = []
        self.rejected = []
        self.checks = []
        self.errors = []

    # --- 출처 ---------------------------------------------------------
    def source_text(self, source):
        """quote_source/source → 원문. 항목 본문이거나 qualifier_refs에 있는 조항만 허용. 아니면 None."""
        if source == BODY_SOURCE or source == self.clause_id:
            return self.clause["text"]
        if source in self.clause["qualifier_refs"] and source in self.view.clauses:
            return self.view.clauses[source]["text"]
        return None

    def resolve_leaf_source(self, leaf):
        """structured 잎의 출처: 항목 본문이면 BODY_SOURCE, 연결된 조항의 원문이면 그 ID, 못 정하면 None."""
        if leaf["source_anchor"] == self.clause["source_anchor"]:
            return BODY_SOURCE
        for ref in self.clause["qualifier_refs"]:
            linked = self.view.clauses.get(ref)
            if linked is not None and linked["source_anchor"] == leaf["source_anchor"]:
                return ref
        if squeeze(leaf["text"]) in squeeze(self.clause["text"]):
            return BODY_SOURCE
        for ref in self.clause["qualifier_refs"]:
            linked = self.view.clauses.get(ref)
            if linked is not None and squeeze(leaf["text"]) in squeeze(linked["text"]):
                return ref
        return None

    def add_check(self, quote, source):
        entry = dict(quote=quote, source=source)
        if entry not in self.checks:
            self.checks.append(entry)

    def reject(self, branch_id, subject, quote, reason):
        self.rejected.append(dict(branch_id=branch_id, subject=subject, quote=quote, reason=reason))

    def new_branch_id(self):
        self.branch_count += 1
        return f"{self.clause_id}:b{self.branch_count}"

    # --- structured ----------------------------------------------------
    def add_structured(self, structured):
        branches, check_leaves = structured
        for branch in branches:
            branch_id = self.new_branch_id()
            thresholds = []
            for leaf in branch["numeric"]:
                operator = leaf["operator"]
                if operator == "eq":
                    operator = "ge"
                    source = self.resolve_leaf_source(leaf) or BODY_SOURCE
                    self.add_check(leaf["text"], source)
                thresholds.append(dict(
                    threshold_id=f"{branch_id}:t{len(thresholds) + 1}", subject=leaf["subject"], operator=operator,
                    value=leaf["threshold"], unit=normalize_unit(leaf["unit"]), quote=leaf["text"],
                    quote_source=self.resolve_leaf_source(leaf) or BODY_SOURCE, origin="structured"))
            texts = "\n".join(q["text"] for q in branch["quals"])
            if thresholds:
                self.branches.append(dict(branch_id=branch_id, label=texts, thresholds=thresholds, text=""))
            elif texts:
                self.branches.append(dict(branch_id=branch_id, label="", thresholds=[], text=texts))
            else:
                self.branch_count -= 1  # 비어 있는 갈래(not만 있던 자리)는 두지 않는다
        for leaf in check_leaves:
            source = self.resolve_leaf_source(leaf)
            if source is None:
                self.reject("", leaf["subject"], leaf["text"], "structured 정성 조건의 출처를 항목 본문·연결 조항에서 찾지 못함")
            else:
                self.add_check(leaf["text"], source)

    # --- extracted -----------------------------------------------------
    def validate_threshold(self, threshold, structured_keys):
        """4.2 규칙을 모두 적용해 채택 가능한 기록 또는 사유 목록을 돌려준다."""
        reasons = []
        operator = threshold["operator"]
        unit = normalize_unit(threshold["unit"])
        quote = threshold["quote"]
        squeezed = squeeze(quote)
        value = None
        try:
            if isinstance(threshold["value"], str) and Decimal(threshold["value"]).is_finite():
                value = Decimal(threshold["value"])
        except InvalidOperation:
            value = None
        if value is None:
            reasons.append(f"value가 10진수 문자열이 아님: {threshold['value']!r}")
        if operator not in OPERATORS:
            reasons.append(f"operator 값이 아님(ge|gt|le|lt): {operator!r}")
        source_text = self.source_text(threshold["quote_source"])
        if source_text is None:
            reasons.append(f"quote_source {threshold['quote_source']!r}가 항목 본문도 아니고 항목의 qualifier_refs에도 없음")
        if not squeezed:
            reasons.append("quote가 비어 있음")
        elif source_text is not None and squeezed not in squeeze(source_text):
            reasons.append("quote가 출처 원문에 이어진 구간으로 없음(인용 불일치)")
        if value is not None and value not in numbers_in(squeezed):
            reasons.append(f"quote 안에 value와 같은 수가 없음: {threshold['value']}")
        if unit and not unit_mentioned(threshold["unit"], squeezed):
            reasons.append(f"quote 안에 단위 {threshold['unit']!r}(표준 {unit!r})나 그 별칭이 없음")
        if operator in OPERATORS:
            found = comparators_in(squeezed)
            if not found:
                reasons.append("quote 안에 비교어(이상·초과·이하·미만 등)가 없음")
            elif operator not in found:
                reasons.append(f"quote의 비교어 방향({'·'.join(OPERATOR_WORDS[o] for o in sorted(found))})이 "
                               f"operator {operator}({OPERATOR_WORDS[operator]})와 다름")
        if value is not None and operator in OPERATORS and (operator, value, unit) in structured_keys:
            reasons.append("고시 자료의 structured 기준과 같은 값이라 중복(structured 쪽만 둔다)")
        if reasons:
            return None, reasons
        return dict(subject=threshold["subject"], operator=operator, value=str(value), unit=unit, quote=quote,
                    quote_source=BODY_SOURCE if threshold["quote_source"] == self.clause_id else threshold["quote_source"],
                    origin="extracted"), []

    def add_extracted(self, item):
        structured_keys = {(t["operator"], Decimal(t["value"]), t["unit"])
                           for b in self.branches for t in b["thresholds"]}
        for branch in item["branches"]:
            given = branch.get("branch_id", "").strip()
            branch_id = given or self.new_branch_id()
            label = branch.get("label", "")
            thresholds = []
            for threshold in branch["thresholds"]:
                accepted, reasons = self.validate_threshold(threshold, structured_keys)
                if accepted is None:
                    self.reject(branch_id, str(threshold["subject"]), str(threshold["quote"]), "; ".join(reasons))
                    continue
                thresholds.append(dict(threshold_id=f"{branch_id}:t{len(thresholds) + 1}", **accepted))
            if thresholds:
                self.branches.append(dict(branch_id=branch_id, label=label, thresholds=thresholds, text=""))
            elif not branch["thresholds"]:
                self.branches.append(dict(branch_id=branch_id, label=label, thresholds=[], text=branch.get("text", "")))
            elif not given:
                self.branch_count -= 1  # 전부 채택 실패한 갈래는 두지 않는다(rejected에 남는다)
        for check in item["checks"]:
            source_text = self.source_text(check["source"])
            if source_text is None:
                self.reject("", "확인 조건", check["quote"],
                            f"source {check['source']!r}가 항목 본문도 아니고 항목의 qualifier_refs에도 없음")
            elif not squeeze(check["quote"]) or squeeze(check["quote"]) not in squeeze(source_text):
                self.reject("", "확인 조건", check["quote"], "인용이 출처 원문에 이어진 구간으로 없음")
            else:
                self.add_check(check["quote"], BODY_SOURCE if check["source"] == self.clause_id else check["source"])

    # --- 공통 --------------------------------------------------------------
    def add_advanced_article_4(self):
        if self.item["family"] != "advanced":
            return
        linked = self.view.clauses.get(ADVANCED_ARTICLE_4)
        if linked is None or ADVANCED_ARTICLE_4 not in self.clause["qualifier_refs"]:
            self.errors.append(f"{self.clause_id}: 첨단 항목인데 {ADVANCED_ARTICLE_4}가 qualifier_refs에 없다")
            return
        self.add_check(linked["text"], ADVANCED_ARTICLE_4)

    def title(self, extracted_item):
        if extracted_item is not None and extracted_item.get("title", "").strip():
            return extracted_item["title"].strip()
        if self.item["family"] in ("advanced", "core"):
            return squeeze(self.item["title"])
        lines = [line.strip() for line in self.clause["text"].splitlines()]
        start = 0
        if KO_MARKER in lines:
            start = lines.index(KO_MARKER) + 1
        elif self.item["code"] in lines:
            start = lines.index(self.item["code"]) + 1
        for line in lines[start:]:
            if line:
                return line
        return squeeze(self.item["title"])

    def record(self, extracted_item):
        record = dict(clause_id=self.clause_id, family=self.item["family"], numeric_status="",
                      title=self.title(extracted_item), branches=self.branches, rejected=self.rejected, checks=self.checks)
        record["numeric_status"] = expected_status(record)
        return record


def build(view, files, scope_only=False):
    """기준본 보기와 추출 파일 목록으로 항목 기록을 만든다. scope_only이면 파일 범위 안 항목만 다룬다(--check)."""
    result = BuildResult()
    owners = {}
    index = {item["clause_id"]: item for item in view.items}
    for file in files:
        for clause_id, item in file.items.items():
            if clause_id not in index:
                result.errors.append(f"{file.path}: 실제 검토 항목이 아닌 clause_id: {clause_id}")
            elif not file.covers(index[clause_id]):
                result.errors.append(f"{file.path}: 파일의 범위(scope) 밖 항목: {clause_id}")
            elif clause_id in owners:
                result.errors.append(f"항목 중복: {clause_id} ({owners[clause_id][0].path}, {file.path})")
            else:
                owners[clause_id] = (file, item)
    items = view.items if not scope_only else [i for i in view.items if any(f.covers(i) for f in files)]
    branch_ids = {}
    for item in items:
        clause_id = item["clause_id"]
        clause = view.clauses[clause_id]
        structured = structured_branches(clause)
        owner = owners.get(clause_id)
        if structured is None and owner is None:
            result.missing.append(clause_id)
            continue
        builder = _RecordBuilder(view, item, clause)
        if structured is not None:
            builder.add_structured(structured)
        if owner is not None:
            builder.add_extracted(owner[1])
        builder.add_advanced_article_4()
        result.errors.extend(builder.errors)
        record = builder.record(owner[1] if owner else None)
        for branch in record["branches"]:
            if branch["branch_id"] in branch_ids:
                result.errors.append(f"branch_id 중복: {branch['branch_id']} ({branch_ids[branch['branch_id']]}, {clause_id})")
            branch_ids[branch["branch_id"]] = clause_id
        try:
            validate_record(record)
        except ValueError as error:
            result.errors.append(f"{clause_id}: 만든 기록이 표 형식에 맞지 않음: {error}")
        result.records.append(record)
        for rejected in record["rejected"]:
            result.rejected.append((clause_id, item["family"], record["title"], rejected))
    result.counts = summarize(result, items)
    return result


def summarize(result, items):
    families = {}
    for family in sorted(FAMILIES):
        families[family] = dict(items=0, **{s: 0 for s in (STATUS_HAS, STATUS_NONE, STATUS_FAILED)},
                                thresholds=0, structured=0, extracted=0, rejected=0, missing=0, checks=0)
    for item in items:
        families[item["family"]]["items"] += 1
    for record in result.records:
        entry = families[record["family"]]
        entry[record["numeric_status"]] += 1
        entry["rejected"] += len(record["rejected"])
        entry["checks"] += len(record["checks"])
        for branch in record["branches"]:
            for threshold in branch["thresholds"]:
                entry["thresholds"] += 1
                entry[threshold["origin"]] += 1
    missing_index = {item["clause_id"]: item["family"] for item in items}
    for clause_id in result.missing:
        families[missing_index[clause_id]]["missing"] += 1
    total = {key: sum(entry[key] for entry in families.values()) for key in next(iter(families.values()))}
    return dict(families=families, total=total, status={s: total[s] for s in (STATUS_HAS, STATUS_NONE, STATUS_FAILED)},
                errors=len(result.errors))


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def table_payload(result, view):
    payload = dict(catalogue_id=view.catalogue_id, catalogue_fingerprint=view.fingerprint, near_percent=NEAR_PERCENT,
                   records=result.records)
    payload["fingerprint"] = table_fingerprint(payload)
    return payload


def write_table(result, view, path):
    """resources/thresholds.json. 누락·오류가 있으면 쓰지 않는다."""
    if not result.ok:
        raise ValueError("누락·오류가 있어 표를 쓰지 않는다")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(table_payload(result, view), ensure_ascii=False, indent=1, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return canonical_hash(table_payload(result, view))


def write_review(result, path, view=None):
    """검수용 엑셀(기준값·확인 조건·숫자 기준 없음·채택 실패·누락·범위별 건수)."""
    import openpyxl
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "기준값"
    sheet.append(["clause_id", "family", "title", "numeric_status", "branch_id", "label", "threshold_id", "subject",
                  "operator", "value", "unit", "quote", "quote_source", "origin"])
    for record in result.records:
        for branch in record["branches"]:
            if not branch["thresholds"]:
                sheet.append([record["clause_id"], record["family"], record["title"], record["numeric_status"],
                              branch["branch_id"], branch["label"], "", "(숫자 없는 갈래)", "", "", "", branch["text"], "", ""])
            for threshold in branch["thresholds"]:
                sheet.append([record["clause_id"], record["family"], record["title"], record["numeric_status"],
                              branch["branch_id"], branch["label"], threshold["threshold_id"], threshold["subject"],
                              threshold["operator"], threshold["value"], threshold["unit"], threshold["quote"],
                              threshold["quote_source"], threshold["origin"]])
    sheet = workbook.create_sheet("확인 조건")
    sheet.append(["clause_id", "family", "title", "quote", "source"])
    for record in result.records:
        for check in record["checks"]:
            sheet.append([record["clause_id"], record["family"], record["title"], check["quote"], check["source"]])
    sheet = workbook.create_sheet("숫자 기준 없음")
    sheet.append(["clause_id", "family", "title", "숫자 없는 갈래 수", "확인 조건 수"])
    for record in result.records:
        if record["numeric_status"] == STATUS_NONE:
            sheet.append([record["clause_id"], record["family"], record["title"], len(record["branches"]),
                          len(record["checks"])])
    sheet = workbook.create_sheet("채택 실패")
    sheet.append(["clause_id", "family", "title", "branch_id", "subject", "quote", "사유"])
    for clause_id, family, title, rejected in result.rejected:
        sheet.append([clause_id, family, title, rejected["branch_id"], rejected["subject"], rejected["quote"],
                      rejected["reason"]])
    sheet = workbook.create_sheet("누락")
    sheet.append(["clause_id", "family", "code", "title"])
    index = {item["clause_id"]: item for item in (view.items if view is not None else [])}
    for clause_id in result.missing:
        item = index.get(clause_id, {})
        sheet.append([clause_id, item.get("family", clause_id.split(":")[0]), item.get("code", ""),
                      squeeze(item.get("title", ""))])
    sheet = workbook.create_sheet("범위별 건수")
    keys = ["items", STATUS_HAS, STATUS_NONE, STATUS_FAILED, "thresholds", "structured", "extracted", "rejected",
            "checks", "missing"]
    sheet.append(["범위", "항목 수", STATUS_HAS, STATUS_NONE, STATUS_FAILED, "기준값 수", "structured", "extracted",
                  "채택 실패 수", "확인 조건 수", "누락"])
    for family, entry in result.counts["families"].items():
        sheet.append([family, *[entry[k] for k in keys]])
    sheet.append(["합계", *[result.counts["total"][k] for k in keys]])
    if result.errors:
        sheet = workbook.create_sheet("오류")
        sheet.append(["오류"])
        for error in result.errors:
            sheet.append([error])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def report_lines(result):
    lines = []
    counts = result.counts
    lines.append("범위       항목  기준값있음  숫자기준없음  채택실패  기준값수  structured  extracted  채택실패수  누락")
    for family, entry in counts["families"].items():
        lines.append(f"{family:<10} {entry['items']:>4}  {entry[STATUS_HAS]:>9}  {entry[STATUS_NONE]:>11}  "
                     f"{entry[STATUS_FAILED]:>7}  {entry['thresholds']:>7}  {entry['structured']:>10}  "
                     f"{entry['extracted']:>9}  {entry['rejected']:>9}  {entry['missing']:>4}")
    total = counts["total"]
    lines.append(f"{'합계':<10} {total['items']:>4}  {total[STATUS_HAS]:>9}  {total[STATUS_NONE]:>11}  "
                 f"{total[STATUS_FAILED]:>7}  {total['thresholds']:>7}  {total['structured']:>10}  "
                 f"{total['extracted']:>9}  {total['rejected']:>9}  {total['missing']:>4}")
    if result.rejected:
        lines.append(f"\n채택 실패 {len(result.rejected)}건:")
        for clause_id, family, title, rejected in result.rejected:
            lines.append(f"  - {clause_id} [{rejected['branch_id'] or '-'}] {rejected['subject']}: {rejected['reason']}")
            lines.append(f"      인용: {squeeze(rejected['quote'])[:120]}")
    if result.missing:
        lines.append(f"\n누락 {len(result.missing)}개 항목(structured도 추출도 없음):")
        for clause_id in result.missing:
            lines.append(f"  - {clause_id}")
    if result.errors:
        lines.append(f"\n오류 {len(result.errors)}건:")
        for error in result.errors:
            lines.append(f"  - {error}")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="기준값 표 생성·검증(개발 전용)")
    parser.add_argument("--check", metavar="추출파일", help="그 파일만 검증한다. 아무 파일도 쓰지 않는다")
    parser.add_argument("--notices-root", default=None, help="고시 기준본 폴더(기본: resources/notices)")
    parser.add_argument("--extracted-dir", default=str(DEFAULT_EXTRACTED_DIR), help="추출 파일 폴더(*.json)")
    parser.add_argument("--output", default=str(paths.threshold_table_path()), help="기준값 표 출력 경로")
    parser.add_argument("--review-xlsx", default=str(DEFAULT_REVIEW_PATH), help="검수용 엑셀 출력 경로")
    args = parser.parse_args(argv)
    try:
        catalogue = load_catalogue(args.notices_root)
    except ValueError as error:
        print(f"고시 기준본을 불러오지 못했다: {error}")
        return 2
    view = CatalogueView.from_catalogue(catalogue)
    print(f"기준본 {view.catalogue_id} 지문 {view.fingerprint[:12]}… 항목 {len(view.items)}개")
    if args.check:
        try:
            file = read_extracted_path(args.check)
        except ExtractionFileError as error:
            print(f"추출 파일 형식 오류: {error}")
            return 2
        result = build(view, [file], scope_only=True)
        print(f"검증 대상 {file.path}: 범위 families={sorted(file.families)} "
              f"code_prefixes={sorted(file.code_prefixes) or '전체'}, 항목 {len(file.items)}개")
        print("\n".join(report_lines(result)))
        problems = bool(result.errors or result.missing or result.rejected)
        print("\n결과: " + ("문제 없음" if not problems else "문제 있음(위 목록을 고친 뒤 다시 검증)"))
        return 1 if problems else 0
    files = []
    failures = []
    for path in sorted(Path(args.extracted_dir).glob("*.json")):
        try:
            files.append(read_extracted_path(path))
        except ExtractionFileError as error:
            failures.append(str(error))
    if failures:
        print("추출 파일 형식 오류 %d건:" % len(failures))
        for failure in failures:
            print("  - " + failure)
        return 2
    print(f"추출 파일 {len(files)}개: {', '.join(f.path for f in files) or '(없음)'}")
    result = build(view, files)
    print("\n".join(report_lines(result)))
    write_review(result, args.review_xlsx, view)
    print(f"\n검수 엑셀: {args.review_xlsx}")
    if not result.ok:
        print("표를 만들지 않았다(누락·오류가 있음).")
        return 1
    write_table(result, view, args.output)
    print(f"기준값 표: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
