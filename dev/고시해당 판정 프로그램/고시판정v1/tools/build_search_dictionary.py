"""관련어 사전 생성 도구(개발 전용, exe에 넣지 않는다). spec 4.2·4.3, 형식은 tools/synonyms/README.md.

하는 일
  ① tools/synonyms/*.json(관련어 파일)을 모두 읽어 합친다. 같은 id 묶음은 낱말을 합집합으로 모으고,
     같은 낱말(공백·대소문자 무시)이 서로 다른 묶음에 있으면 오류다.
  ② 낱말마다 고시 원문(실제 검토 항목 507개의 원문 국문·영문·제목·분야)에 몇 번, 몇 항목에 나오는지 센다.
     묶음 안 낱말이 하나도 원문에 없으면 그 묶음은 오류(원문에 근거 없는 묶음 금지)이고, 일부 낱말만 없는 것은
     같은 말(음차·약어)로 허용하되 검수 엑셀에 '원문에 없음'으로 표시한다.
  ③ 위·아래 관계의 양쪽 묶음이 모두 있어야 하고, 관계에 순환이 있으면 오류다.
  ④ resources/search_dictionary.json(지문 포함)과 tools/output/관련어_검수.xlsx를 쓴다. 오류가 있으면 사전은 쓰지 않고
     검수 엑셀(오류 시트 포함)만 쓴다.

`--check <파일>`: 그 파일을 검증한다(관계의 상대 묶음과 낱말 중복은 같은 폴더의 다른 파일을 맥락으로 함께 본다).
    아무 파일도 쓰지 않는다. 그 파일이 관련된 오류가 있으면 종료 코드 1.
`--apply-review <엑셀>`: 검수 엑셀의 '검수 결과' 칸(빈칸=유지, '삭제', 고친 값)을 관련어 파일에 반영하고 다시 생성한다.
    반영한 결과가 검증을 통과하지 못하면 아무 파일도 고치지 않는다.
`--reviewed-on YYYY-MM-DD`: 사전에 검수 일자를 적는다. 주지 않으면, 묶음·낱말·관계가 이전 사전과 같을 때만 이전 검수
    일자를 이어 쓰고 아니면 비운다(null).

종료 코드: 0 성공, 1 검증 실패(오류 목록 출력), 2 파일 형식·인자 오류.

사용:  python tools/build_search_dictionary.py [--check 파일 | --apply-review 엑셀] [--reviewed-on YYYY-MM-DD]
                                                [--synonyms-dir 폴더] [--notices-root 폴더]
                                                [--output search_dictionary.json] [--review-xlsx 검수.xlsx]
"""
import argparse
import copy
from dataclasses import dataclass, field
import datetime
import functools
import json
from pathlib import Path
import re
import sys

PROGRAM_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

from notice_catalogue import canonical_hash, clause_index, clause_record, load_catalogue  # noqa: E402

FORMAT = "search_dictionary/1"
DEFAULT_SYNONYMS_DIR = PROGRAM_ROOT / "tools" / "synonyms"
DEFAULT_OUTPUT = PROGRAM_ROOT / "resources" / "search_dictionary.json"
DEFAULT_REVIEW_PATH = PROGRAM_ROOT / "tools" / "output" / "관련어_검수.xlsx"

GROUP_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
MAX_TERM_LENGTH = 80
DOC_SEPARATOR = "\x00"   # 원문·제목·분야를 잇는 자리. 공백이 아니어서 낱말이 경계를 넘어 맞지 않는다.

FILE_KEYS = frozenset(("scope", "groups", "relations"))
FILE_GROUP_KEYS = frozenset(("id", "terms", "note"))
FILE_RELATION_KEYS = frozenset(("narrow", "broad", "note"))
DICTIONARY_KEYS = frozenset(("format", "catalogue_id", "catalogue_fingerprint", "generated_at", "reviewed_on",
                             "sources", "groups", "relations", "fingerprint"))
GROUP_KEYS = frozenset(("id", "terms", "note", "sources"))
TERM_KEYS = frozenset(("term", "count", "clauses"))
RELATION_KEYS = frozenset(("narrow", "broad", "note", "sources"))

REVIEW_COLUMN = "검수 결과"
REVIEW_DELETE = "삭제"
IN_TEXT = "원문에 있음"
NOT_IN_TEXT = "원문에 없음"
SHEET_GROUPS = "같은 말 묶음"
SHEET_RELATIONS = "위·아래 관계"
SHEET_SUMMARY = "요약"
SHEET_ERRORS = "오류"
GROUP_COLUMNS = ("묶음 id", "낱말", "원문 등장 건수", "등장 항목 수", "원문 확인", "묶음 메모", "출처 파일", REVIEW_COLUMN)
RELATION_COLUMNS = ("아래 묶음", "아래 낱말", "위 묶음", "위 낱말", "메모", "출처 파일", REVIEW_COLUMN)
RELATION_ARROW_RE = re.compile(r"\s*(?:→|->)\s*")


class SynonymFileError(ValueError):
    """관련어 파일의 형식이 틀리다(내용 검증 실패와 구분한다)."""


class ReviewFileError(ValueError):
    """검수 엑셀을 읽지 못했거나 시트·머리글이 틀리다."""


class SearchDictionaryError(ValueError):
    """사전 파일이 없거나 형식이 틀리거나 지문이 맞지 않는다."""


# ---------------------------------------------------------------------------
# 낱말 맞추기
# ---------------------------------------------------------------------------

def normalize_term(term):
    """같은 낱말인지 가리는 열쇠: 공백을 모두 빼고 대소문자를 무시한다."""
    return "".join(str(term).split()).casefold()


def _is_ascii_letter(char):
    return char.isascii() and char.isalpha()


def _is_ascii_alnum(char):
    return char.isascii() and char.isalnum()


@functools.lru_cache(maxsize=None)
def term_pattern(term):
    """원문에서 낱말을 찾는 정규식.

    - 공백 무시: 낱말의 글자 사이에 공백·줄바꿈이 있어도 맞는다('마이크로LED' = '마이크로 LED').
    - 대소문자 무시.
    - 영문·숫자로 시작하는 낱말은 앞 글자가 영문·숫자가 아니어야 한다('OLED'가 'cooled' 안에서 맞지 않게).
    - 영문으로 끝나는 낱말은 복수형 s·es(y로 끝나면 ies)까지 받고, 그 뒤가 영문이 아니어야 한다
      ('UAV' = 'UAVs', 'memory' = 'memories').
    - 숫자로 끝나는 낱말은 뒤가 숫자가 아니어야 한다.
    한글은 경계를 보지 않는다('전지'는 '이차전지' 안에서도 맞는다).
    """
    chars = [char for char in str(term) if not char.isspace()]
    if not chars:
        raise ValueError("빈 낱말")
    if len(chars) > 1 and chars[-1] in "yY" and _is_ascii_letter(chars[-2]):
        body = r"\s*".join(re.escape(char) for char in chars[:-1]) + r"\s*(?:y|ie)"
    else:
        body = r"\s*".join(re.escape(char) for char in chars)
    prefix = r"(?<![A-Za-z0-9])" if _is_ascii_alnum(chars[0]) else ""
    if _is_ascii_letter(chars[-1]):
        suffix = r"(?:e?s)?(?![A-Za-z])"
    elif chars[-1].isascii() and chars[-1].isdigit():
        suffix = r"(?![0-9])"
    else:
        suffix = ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


def count_term(term, text):
    """text 안에서 term이 나온 횟수(term_pattern 규칙)."""
    return len(term_pattern(term).findall(text or ""))


# ---------------------------------------------------------------------------
# 원문
# ---------------------------------------------------------------------------

def searchable_text(text, title, field_name):
    """한 항목에서 낱말을 세는 글: 원문(국문·영문) + 제목 + 분야. 제목·분야가 원문에 이미 그대로 있으면 한 번만 센다."""
    text = text or ""
    squeezed = normalize_term(text)
    pieces = [text]
    for extra in (title, field_name):
        if extra and normalize_term(extra) not in squeezed:
            pieces.append(extra)
    return DOC_SEPARATOR.join(pieces)


@dataclass
class Corpus:
    """도구가 쓰는 고시 원문 보기. 시험에서는 합성 자료로 직접 만든다."""
    catalogue_id: str
    fingerprint: str
    docs: list   # [(clause_id, 낱말을 세는 글)] — 실제 검토 항목(공통 정의·주석 제외)

    @classmethod
    def from_catalogue(cls, catalogue):
        docs = []
        for item in clause_index(catalogue):
            record = clause_record(catalogue, item["clause_id"])
            docs.append((item["clause_id"], searchable_text(record["text"], item["title"], item["field"])))
        return cls(catalogue_id=catalogue.manifest["catalogue_id"], fingerprint=catalogue.fingerprint, docs=docs)


# ---------------------------------------------------------------------------
# 관련어 파일 읽기
# ---------------------------------------------------------------------------

@dataclass
class SynonymFile:
    path: str          # 파일 이름(출처 표시·--check 대상 구분에 쓴다)
    scope: str
    groups: list       # [{"id", "terms", "note"}]
    relations: list    # [{"narrow", "broad", "note"}]


def _fail(condition, message):
    if not condition:
        raise SynonymFileError(message)


def term_problem(term):
    """낱말 모양이 틀린 까닭. 맞으면 None."""
    if not isinstance(term, str) or not term:
        return "빈 낱말이거나 글이 아니다"
    if term != term.strip():
        return "앞뒤에 공백이 있다"
    if len(term) > MAX_TERM_LENGTH:
        return f"{MAX_TERM_LENGTH}자보다 길다"
    if any(ord(char) < 32 for char in term):
        return "제어 문자가 있다"
    if not any(char.isalnum() for char in term):
        return "글자·숫자가 없다"
    return None


def _note(value, label):
    _fail(isinstance(value, str), f"{label}: note는 글이어야 한다")
    return value


def read_synonym_file(payload, path):
    """관련어 파일 내용(dict)을 검사해 SynonymFile로 만든다. 형식이 틀리면 SynonymFileError."""
    label = str(path)
    _fail(isinstance(payload, dict), f"{label}: 최상위가 객체가 아니다")
    _fail(set(payload) <= FILE_KEYS and {"scope", "groups"} <= set(payload),
          f"{label}: 최상위는 scope·groups(필수)·relations만 가진다: {sorted(payload)}")
    scope = payload["scope"]
    _fail(isinstance(scope, str) and scope.strip(), f"{label}: scope는 비어 있지 않은 글이어야 한다")
    _fail(isinstance(payload["groups"], list), f"{label}: groups가 목록이 아니다")
    relations_raw = payload.get("relations", [])
    _fail(isinstance(relations_raw, list), f"{label}: relations가 목록이 아니다")
    groups = []
    seen_ids = set()
    for position, entry in enumerate(payload["groups"], 1):
        where = f"{label}: groups[{position}]"
        _fail(isinstance(entry, dict) and set(entry) <= FILE_GROUP_KEYS and {"id", "terms"} <= set(entry),
              f"{where}: 필드는 id·terms(필수)·note만")
        group_id = entry["id"]
        _fail(isinstance(group_id, str) and GROUP_ID_RE.match(group_id),
              f"{where}: id는 영문 소문자로 시작하고 영문 소문자·숫자·밑줄만 쓴다: {group_id!r}")
        where = f"{label}: 묶음 '{group_id}'"
        _fail(group_id not in seen_ids, f"{where}: 한 파일 안에 같은 id가 두 번 있다")
        seen_ids.add(group_id)
        terms = entry["terms"]
        _fail(isinstance(terms, list) and terms, f"{where}: terms는 비어 있지 않은 목록이어야 한다")
        keys = {}
        for term in terms:
            problem = term_problem(term)
            _fail(problem is None, f"{where}: 낱말 {term!r}: {problem}")
            key = normalize_term(term)
            _fail(key not in keys, f"{where}: '{keys.get(key)}'와 '{term}'은 공백·대소문자만 다르다(하나만 둔다)")
            keys[key] = term
        note = _note(entry.get("note", ""), where)
        groups.append(dict(id=group_id, terms=list(terms), note=note))
    relations = []
    seen_pairs = set()
    for position, entry in enumerate(relations_raw, 1):
        where = f"{label}: relations[{position}]"
        _fail(isinstance(entry, dict) and set(entry) <= FILE_RELATION_KEYS and {"narrow", "broad"} <= set(entry),
              f"{where}: 필드는 narrow·broad(필수)·note만")
        narrow, broad = entry["narrow"], entry["broad"]
        for value in (narrow, broad):
            _fail(isinstance(value, str) and GROUP_ID_RE.match(value), f"{where}: 묶음 id 모양이 아니다: {value!r}")
        _fail(narrow != broad, f"{where}: 아래와 위가 같은 묶음이다: {narrow}")
        _fail((narrow, broad) not in seen_pairs, f"{where}: 같은 관계가 두 번 있다: {narrow} → {broad}")
        seen_pairs.add((narrow, broad))
        relations.append(dict(narrow=narrow, broad=broad, note=_note(entry.get("note", ""), where)))
    return SynonymFile(path=label, scope=scope, groups=groups, relations=relations)


def _pairs_hook(error_class):
    def hook(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise error_class(f"JSON 키 중복: {key}")
            output[key] = value
        return output
    return hook


def _reject_constant(value):
    raise ValueError(f"JSON에 유한하지 않은 수가 있다: {value}")


def read_raw(path, error_class=SynonymFileError):
    """JSON 파일을 dict로 읽는다(키 중복·NaN 거부). 실패하면 error_class."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
        return json.loads(text, object_pairs_hook=_pairs_hook(error_class), parse_constant=_reject_constant)
    except error_class:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise error_class(f"{path.name}: 읽지 못했다: {error}") from error


def read_synonym_path(path):
    return read_synonym_file(read_raw(path), Path(path).name)


# ---------------------------------------------------------------------------
# 합치기·검증
# ---------------------------------------------------------------------------

@dataclass
class Problem:
    message: str
    files: tuple       # 관련된 관련어 파일 이름


@dataclass
class BuildResult:
    groups: dict                     # id → {"id", "terms": [{"term", "count", "clauses", "source"}], "note", "sources"}
    relations: list                  # [{"narrow", "broad", "note", "sources"}]
    sources: list                    # 읽은 관련어 파일 이름
    errors: list = field(default_factory=list)     # [Problem]
    notices: list = field(default_factory=list)    # 오류는 아니지만 알릴 것(합친 낱말 등)
    focus: str = None

    @property
    def ok(self):
        return not self.errors

    def focus_errors(self):
        if self.focus is None:
            return list(self.errors)
        return [problem for problem in self.errors if self.focus in problem.files]

    def focus_groups(self):
        return [g for g in self.groups.values() if self.focus is None or self.focus in g["sources"]]

    def focus_relations(self):
        return [r for r in self.relations if self.focus is None or self.focus in r["sources"]]

    def terms_not_in_text(self):
        return [dict(group=g["id"], term=t["term"], source=t["source"])
                for g in self.focus_groups() for t in g["terms"] if t["count"] == 0
                and (self.focus is None or t["source"] == self.focus)]


def find_cycles(edges):
    """(아래, 위) 간선 목록에서 순환을 찾는다. 각 순환은 [a, b, …, a] 꼴."""
    graph = {}
    for narrow, broad in edges:
        graph.setdefault(narrow, []).append(broad)
    state = {}
    stack = []
    cycles = []
    seen = set()

    def visit(node):
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):] + [nxt]
                key = frozenset(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif nxt not in state:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for node in list(graph):
        if node not in state:
            visit(node)
    return cycles


def build(files, corpus, focus=None):
    """관련어 파일들을 합치고 원문 등장 건수를 세고 검증한다. 파일은 주어진 순서대로 합친다."""
    errors = []
    notices = []
    merged = {}     # id → {"id", "terms", "keys": {열쇠: 낱말}, "term_sources", "notes", "sources"}
    owner = {}      # 낱말 열쇠 → (묶음 id, 파일)
    for file in files:
        for entry in file.groups:
            group_id = entry["id"]
            group = merged.setdefault(group_id, dict(id=group_id, terms=[], keys={}, term_sources={}, notes=[],
                                                     sources=[]))
            if file.path not in group["sources"]:
                group["sources"].append(file.path)
            if entry["note"] and entry["note"] not in group["notes"]:
                group["notes"].append(entry["note"])
            for term in entry["terms"]:
                key = normalize_term(term)
                if key in owner and owner[key][0] != group_id:
                    other_id, other_file = owner[key]
                    errors.append(Problem(
                        f"낱말 '{term}'이 묶음 '{other_id}'({other_file})와 묶음 '{group_id}'({file.path})에 함께 있다"
                        " — 한 낱말은 한 묶음에만 둔다", tuple(dict.fromkeys((other_file, file.path)))))
                    continue
                if key in group["keys"]:
                    if group["keys"][key] != term:
                        notices.append(f"묶음 '{group_id}': '{term}'({file.path})은 '{group['keys'][key]}'과 "
                                       "공백·대소문자만 달라 하나로 합쳤다")
                    continue
                owner[key] = (group_id, file.path)
                group["keys"][key] = term
                group["term_sources"][key] = file.path
                group["terms"].append(term)
    groups = {}
    for group_id, group in merged.items():
        terms = []
        for term in group["terms"]:
            pattern = term_pattern(term)
            count = clauses = 0
            for _, text in corpus.docs:
                found = len(pattern.findall(text))
                if found:
                    count += found
                    clauses += 1
            terms.append(dict(term=term, count=count, clauses=clauses,
                              source=group["term_sources"][normalize_term(term)]))
        if not any(term["count"] for term in terms):
            errors.append(Problem(
                f"묶음 '{group_id}'의 낱말이 하나도 원문에 없다({', '.join(group['terms']) or '낱말 없음'})"
                " — 원문에 근거 없는 묶음은 둘 수 없다", tuple(group["sources"])))
        groups[group_id] = dict(id=group_id, terms=terms, note=" / ".join(group["notes"]), sources=group["sources"])
    relation_index = {}
    for file in files:
        for entry in file.relations:
            pair = (entry["narrow"], entry["broad"])
            relation = relation_index.setdefault(pair, dict(narrow=pair[0], broad=pair[1], notes=[], sources=[]))
            if file.path not in relation["sources"]:
                relation["sources"].append(file.path)
            if entry["note"] and entry["note"] not in relation["notes"]:
                relation["notes"].append(entry["note"])
    relations = [dict(narrow=r["narrow"], broad=r["broad"], note=" / ".join(r["notes"]), sources=r["sources"])
                 for r in relation_index.values()]
    for relation in relations:
        for end in (relation["narrow"], relation["broad"]):
            if end not in groups:
                errors.append(Problem(f"관계 {relation['narrow']} → {relation['broad']}: 묶음 '{end}'이 어느 파일에도 없다",
                                      tuple(relation["sources"])))
    for cycle in find_cycles([(r["narrow"], r["broad"]) for r in relations]):
        involved = []
        for narrow, broad in zip(cycle, cycle[1:]):
            involved.extend(relation_index[(narrow, broad)]["sources"])
        errors.append(Problem(f"관계에 순환이 있다: {' → '.join(cycle)}", tuple(dict.fromkeys(involved))))
    return BuildResult(groups=groups, relations=relations, sources=[file.path for file in files], errors=errors,
                       notices=notices, focus=focus)


# ---------------------------------------------------------------------------
# 사전 파일
# ---------------------------------------------------------------------------

def dictionary_fingerprint(data):
    """사전 지문: fingerprint를 뺀 나머지 전부의 canonical SHA256(키 정렬·구분자 고정 JSON, UTF-8).

    실행용 모듈은 불러올 때 이 값을 다시 계산해 파일의 fingerprint와 대조한다(코드 상수 없음).
    """
    return canonical_hash({key: value for key, value in data.items() if key != "fingerprint"})


def content_signature(data):
    """검수 일자를 이어 쓸지 가리는 열쇠: 묶음 id·낱말·관계만(건수·일시·출처 제외)."""
    return canonical_hash(dict(
        groups=[[g["id"], [t["term"] for t in g["terms"]]] for g in data["groups"]],
        relations=[[r["narrow"], r["broad"]] for r in data["relations"]]))


def dictionary_payload(result, corpus, generated_at, reviewed_on):
    data = dict(
        format=FORMAT,
        catalogue_id=corpus.catalogue_id,
        catalogue_fingerprint=corpus.fingerprint,
        generated_at=generated_at,
        reviewed_on=reviewed_on,
        sources=list(result.sources),
        groups=[dict(id=g["id"], terms=[dict(term=t["term"], count=t["count"], clauses=t["clauses"]) for t in g["terms"]],
                     note=g["note"], sources=list(g["sources"])) for g in result.groups.values()],
        relations=[dict(narrow=r["narrow"], broad=r["broad"], note=r["note"], sources=list(r["sources"]))
                   for r in result.relations],
    )
    data["fingerprint"] = dictionary_fingerprint(data)
    return data


def _require(condition, message):
    if not condition:
        raise SearchDictionaryError(message)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _string_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def valid_date(text):
    if not isinstance(text, str) or not DATE_RE.match(text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def validate_dictionary(data, catalogue=None):
    """사전 내용(dict)을 검사한다. 틀리면 SearchDictionaryError. 실행용 모듈도 같은 규칙으로 검사한다."""
    _require(isinstance(data, dict) and set(data) == DICTIONARY_KEYS,
             f"사전 최상위 필드 구성이 다르다: {sorted(data) if isinstance(data, dict) else type(data).__name__}")
    _require(data["format"] == FORMAT, f"사전 형식이 다르다: {data['format']!r}")
    for key in ("catalogue_id", "catalogue_fingerprint", "generated_at", "fingerprint"):
        _require(isinstance(data[key], str) and data[key], f"{key} 값이 비어 있거나 글이 아니다")
    _require(data["reviewed_on"] is None or valid_date(data["reviewed_on"]), "reviewed_on은 null 또는 YYYY-MM-DD")
    _require(_string_list(data["sources"]), "sources는 글 목록이어야 한다")
    _require(isinstance(data["groups"], list) and isinstance(data["relations"], list), "groups·relations는 목록이어야 한다")
    ids = set()
    owners = {}
    for group in data["groups"]:
        _require(isinstance(group, dict) and set(group) == GROUP_KEYS, "묶음 필드 구성이 다르다")
        group_id = group["id"]
        _require(isinstance(group_id, str) and GROUP_ID_RE.match(group_id), f"묶음 id 모양이 아니다: {group_id!r}")
        _require(group_id not in ids, f"묶음 id 중복: {group_id}")
        ids.add(group_id)
        _require(isinstance(group["note"], str) and _string_list(group["sources"]), f"묶음 '{group_id}' note·sources 형식")
        _require(isinstance(group["terms"], list) and group["terms"], f"묶음 '{group_id}'에 낱말이 없다")
        for term in group["terms"]:
            _require(isinstance(term, dict) and set(term) == TERM_KEYS, f"묶음 '{group_id}' 낱말 필드 구성이 다르다")
            _require(term_problem(term["term"]) is None, f"묶음 '{group_id}' 낱말 모양이 틀리다: {term['term']!r}")
            _require(_is_count(term["count"]) and _is_count(term["clauses"]) and term["clauses"] <= term["count"],
                     f"묶음 '{group_id}' 낱말 '{term['term']}' 건수가 틀리다")
            key = normalize_term(term["term"])
            _require(key not in owners, f"낱말 '{term['term']}'이 두 번 있다({owners.get(key)}, {group_id})")
            owners[key] = group_id
        _require(any(term["count"] for term in group["terms"]), f"묶음 '{group_id}'의 낱말이 하나도 원문에 없다")
    pairs = set()
    for relation in data["relations"]:
        _require(isinstance(relation, dict) and set(relation) == RELATION_KEYS, "관계 필드 구성이 다르다")
        narrow, broad = relation["narrow"], relation["broad"]
        _require(narrow in ids and broad in ids, f"관계 {narrow} → {broad}의 묶음이 없다")
        _require(narrow != broad and (narrow, broad) not in pairs, f"관계 {narrow} → {broad}가 틀리거나 두 번 있다")
        _require(isinstance(relation["note"], str) and _string_list(relation["sources"]), "관계 note·sources 형식")
        pairs.add((narrow, broad))
    cycles = find_cycles(sorted(pairs))
    _require(not cycles, f"관계에 순환이 있다: {' → '.join(cycles[0]) if cycles else ''}")
    _require(dictionary_fingerprint(data) == data["fingerprint"], "사전 지문이 맞지 않는다(파일이 바뀌었다)")
    if catalogue is not None:
        _require(data["catalogue_fingerprint"] == catalogue.fingerprint, "사전을 만든 고시 기준본과 지금 기준본이 다르다")
    return data


def load_dictionary(path, catalogue=None):
    """사전 파일을 읽어 검사한다(지문 포함). 틀리면 SearchDictionaryError(fail-closed)."""
    data = read_raw(path, SearchDictionaryError)
    return validate_dictionary(data, catalogue)


def write_dictionary(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4, allow_nan=False) + "\n", encoding="utf-8",
                    newline="\n")


# ---------------------------------------------------------------------------
# 검수 엑셀
# ---------------------------------------------------------------------------

def _terms_label(group):
    return "·".join(t["term"] for t in group["terms"]) if group else "(묶음 없음)"


def write_review(result, path, corpus, data=None, generated_at=None):
    """검수 엑셀: 같은 말 묶음 · 위·아래 관계 · 요약 (+ 오류가 있으면 오류)."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    bold = Font(bold=True)
    review_fill = PatternFill("solid", fgColor="DDEBF7")
    missing_fill = PatternFill("solid", fgColor="FFF2CC")
    workbook = openpyxl.Workbook()

    def header(sheet, columns, widths):
        sheet.append(list(columns))
        for index, cell in enumerate(sheet[1]):
            cell.font = bold
            sheet.column_dimensions[cell.column_letter].width = widths[index]
            if cell.value == REVIEW_COLUMN:
                cell.fill = review_fill
        sheet.freeze_panes = "A2"

    sheet = workbook.active
    sheet.title = SHEET_GROUPS
    header(sheet, GROUP_COLUMNS, (20, 28, 14, 12, 12, 40, 18, 22))
    for group in result.groups.values():
        for term in group["terms"]:
            mark = IN_TEXT if term["count"] else NOT_IN_TEXT
            sheet.append([group["id"], term["term"], term["count"], term["clauses"], mark, group["note"],
                          term["source"], None])
            row = sheet.max_row
            sheet.cell(row, len(GROUP_COLUMNS)).fill = review_fill
            if not term["count"]:
                sheet.cell(row, GROUP_COLUMNS.index("원문 확인") + 1).fill = missing_fill
    sheet = workbook.create_sheet(SHEET_RELATIONS)
    header(sheet, RELATION_COLUMNS, (20, 36, 20, 36, 30, 18, 22))
    for relation in result.relations:
        sheet.append([relation["narrow"], _terms_label(result.groups.get(relation["narrow"])), relation["broad"],
                      _terms_label(result.groups.get(relation["broad"])), relation["note"],
                      ", ".join(relation["sources"]), None])
        sheet.cell(sheet.max_row, len(RELATION_COLUMNS)).fill = review_fill
    sheet = workbook.create_sheet(SHEET_SUMMARY)
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 100
    term_total = sum(len(g["terms"]) for g in result.groups.values())
    missing_total = sum(1 for g in result.groups.values() for t in g["terms"] if not t["count"])
    rows = [
        ("생성 일시", generated_at or ""),
        ("검수 일자", (data or {}).get("reviewed_on") or "(검수 전)"),
        ("사전 지문", data["fingerprint"] if data else "(오류가 있어 사전을 만들지 않음)"),
        ("고시 기준본", corpus.catalogue_id),
        ("고시 기준본 지문", corpus.fingerprint),
        ("원문 항목 수", len(corpus.docs)),
        ("관련어 파일", ", ".join(result.sources)),
        ("같은 말 묶음 수", len(result.groups)),
        ("낱말 수", term_total),
        ("원문에 없는 낱말 수", missing_total),
        ("위·아래 관계 수", len(result.relations)),
        ("오류 수", len(result.errors)),
        ("", ""),
        ("검수 방법", f"'{SHEET_GROUPS}'·'{SHEET_RELATIONS}' 시트의 '{REVIEW_COLUMN}' 칸만 채운다."),
        ("", f"빈칸 = 그대로 둔다. '{REVIEW_DELETE}' = 그 낱말·관계를 지운다."),
        ("", "같은 말 묶음: 고친 낱말을 적으면 그 낱말로 바꾼다(예: '디램' → '디-램')."),
        ("", "위·아래 관계: 다른 위 묶음 id 하나를 적으면 위 묶음을 바꾸고, '아래 id → 위 id'로 적으면 관계를 그것으로 바꾼다."),
        ("", f"'{NOT_IN_TEXT}' 낱말은 원문 낱말의 같은 말(음차·약어·영문)일 때만 남긴다. 묶음마다 원문에 있는 낱말이 하나 이상 있어야 한다."),
        ("", "반영: python tools/build_search_dictionary.py --apply-review <이 엑셀> --reviewed-on YYYY-MM-DD"),
    ]
    for key, value in rows:
        sheet.append([key, value])
        sheet.cell(sheet.max_row, 1).font = bold
        sheet.cell(sheet.max_row, 2).alignment = Alignment(wrap_text=False)
    if result.errors:
        sheet = workbook.create_sheet(SHEET_ERRORS)
        header(sheet, ("오류", "관련 파일"), (100, 30))
        for problem in result.errors:
            sheet.append([problem.message, ", ".join(problem.files)])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


@dataclass
class ReviewAction:
    sheet: str
    row: int
    first: str      # 같은 말: 묶음 id / 관계: 아래 묶음
    second: str     # 같은 말: 낱말 / 관계: 위 묶음
    value: str      # '삭제' 또는 고친 값


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_review(path):
    """검수 엑셀에서 '검수 결과'가 채워진 줄만 읽는다. → (같은 말 동작 목록, 관계 동작 목록)."""
    try:
        import openpyxl
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as error:  # openpyxl은 여러 종류의 예외를 낸다
        raise ReviewFileError(f"검수 엑셀을 열지 못했다: {path}: {error}") from error
    try:
        found = {}
        for sheet_name, columns in ((SHEET_GROUPS, ("묶음 id", "낱말")), (SHEET_RELATIONS, ("아래 묶음", "위 묶음"))):
            if sheet_name not in workbook.sheetnames:
                raise ReviewFileError(f"검수 엑셀에 '{sheet_name}' 시트가 없다")
            rows = list(workbook[sheet_name].iter_rows(values_only=True))
            head = [_cell_text(value) for value in (rows[0] if rows else ())]
            for name in (*columns, REVIEW_COLUMN):
                if name not in head:
                    raise ReviewFileError(f"'{sheet_name}' 시트에 '{name}' 머리글이 없다")
            first, second, review = (head.index(name) for name in (*columns, REVIEW_COLUMN))
            actions = []
            for number, row in enumerate(rows[1:], 2):
                row = list(row) + [None] * (len(head) - len(row))
                value = _cell_text(row[review])
                if not value:
                    continue
                actions.append(ReviewAction(sheet_name, number, _cell_text(row[first]), _cell_text(row[second]), value))
            found[sheet_name] = actions
        return found[SHEET_GROUPS], found[SHEET_RELATIONS]
    finally:
        workbook.close()


def apply_review(raw_files, term_actions, relation_actions):
    """검수 결과를 관련어 파일 내용(dict, 이름 → 내용)에 그 자리에서 반영한다. → (반영 내역, 오류 목록)."""
    log = []
    errors = []
    before_ids = {g["id"] for data in raw_files.values() for g in data.get("groups", [])}
    for action in term_actions:
        where = f"{action.sheet} {action.row}행"
        if not action.first or not action.second:
            errors.append(f"{where}: 묶음 id·낱말 칸이 비어 있다")
            continue
        key = normalize_term(action.second)
        hits = [(name, g) for name, data in raw_files.items() for g in data.get("groups", [])
                if g["id"] == action.first and any(normalize_term(t) == key for t in g["terms"])]
        if not hits:
            errors.append(f"{where}: 묶음 '{action.first}'에 낱말 '{action.second}'이 관련어 파일에 없다")
            continue
        names = ", ".join(dict.fromkeys(name for name, _ in hits))
        if action.value == REVIEW_DELETE:
            for _, group in hits:
                group["terms"] = [t for t in group["terms"] if normalize_term(t) != key]
            log.append(f"낱말 삭제: [{action.first}] {action.second} ({names})")
            continue
        problem = term_problem(action.value)
        if problem:
            errors.append(f"{where}: 고친 낱말 {action.value!r}: {problem}")
            continue
        for _, group in hits:
            replaced = []
            seen = set()
            for term in group["terms"]:
                if normalize_term(term) == key:
                    term = action.value
                if normalize_term(term) in seen:
                    continue
                seen.add(normalize_term(term))
                replaced.append(term)
            group["terms"] = replaced
        log.append(f"낱말 고침: [{action.first}] {action.second} → {action.value} ({names})")
    for action in relation_actions:
        where = f"{action.sheet} {action.row}행"
        pair = (action.first, action.second)
        hits = [(name, data) for name, data in raw_files.items()
                if any((r["narrow"], r["broad"]) == pair for r in data.get("relations", []))]
        if not hits:
            errors.append(f"{where}: 관계 {pair[0]} → {pair[1]}이 관련어 파일에 없다")
            continue
        names = ", ".join(name for name, _ in hits)
        if action.value == REVIEW_DELETE:
            for _, data in hits:
                data["relations"] = [r for r in data["relations"] if (r["narrow"], r["broad"]) != pair]
            log.append(f"관계 삭제: {pair[0]} → {pair[1]} ({names})")
            continue
        parts = RELATION_ARROW_RE.split(action.value)
        new_pair = (parts[0], parts[1]) if len(parts) == 2 else (pair[0], action.value) if len(parts) == 1 else None
        if new_pair is None or not all(GROUP_ID_RE.match(part) for part in new_pair) or new_pair[0] == new_pair[1]:
            errors.append(f"{where}: 고친 관계 {action.value!r}를 읽지 못했다('위 id' 또는 '아래 id → 위 id')")
            continue
        if new_pair == pair:
            log.append(f"관계 유지(같은 값): {pair[0]} → {pair[1]}")
            continue
        for _, data in hits:
            updated = []
            for relation in data["relations"]:
                if (relation["narrow"], relation["broad"]) == pair:
                    relation = {**relation, "narrow": new_pair[0], "broad": new_pair[1]}
                if any((r["narrow"], r["broad"]) == new_pair for r in updated):
                    continue
                updated.append(relation)
            data["relations"] = updated
        log.append(f"관계 고침: {pair[0]} → {pair[1]} ⇒ {new_pair[0]} → {new_pair[1]} ({names})")
    for name, data in raw_files.items():
        kept = []
        for group in data.get("groups", []):
            if group["terms"]:
                kept.append(group)
            else:
                log.append(f"묶음 삭제(낱말이 모두 지워짐): {group['id']} ({name})")
        data["groups"] = kept
    after_ids = {g["id"] for data in raw_files.values() for g in data.get("groups", [])}
    vanished = before_ids - after_ids
    if vanished:
        for name, data in raw_files.items():
            kept = []
            for relation in data.get("relations", []):
                if relation["narrow"] in vanished or relation["broad"] in vanished:
                    log.append(f"관계 삭제(묶음이 없어짐): {relation['narrow']} → {relation['broad']} ({name})")
                else:
                    kept.append(relation)
            if "relations" in data:
                data["relations"] = kept
    return log, errors


def format_synonym_payload(data):
    """관련어 파일을 사람이 읽기 좋은 꼴로 쓴다: 묶음·관계 하나가 한 줄."""
    def one(value):
        return json.dumps(value, ensure_ascii=False)

    lines = ["{", f"    \"scope\": {one(data['scope'])},", "    \"groups\": ["]
    groups = data.get("groups", [])
    for index, group in enumerate(groups):
        lines.append("        " + one(group) + ("," if index < len(groups) - 1 else ""))
    lines.append("    ],")
    lines.append("    \"relations\": [")
    relations = data.get("relations", [])
    for index, relation in enumerate(relations):
        lines.append("        " + one(relation) + ("," if index < len(relations) - 1 else ""))
    lines.append("    ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def report_lines(result):
    lines = []
    groups = result.focus_groups()
    relations = result.focus_relations()
    term_total = sum(len(g["terms"]) for g in groups)
    missing = result.terms_not_in_text()
    lines.append(f"같은 말 묶음 {len(groups)}개 · 낱말 {term_total}개(원문에 없음 {len(missing)}개) · 위·아래 관계 {len(relations)}개")
    if missing:
        lines.append(f"\n원문에 없는 낱말 {len(missing)}개(같은 말로 허용, 검수 엑셀에 '{NOT_IN_TEXT}' 표시):")
        for entry in missing:
            lines.append(f"  - [{entry['group']}] {entry['term']} ({entry['source']})")
    if result.notices:
        lines.append(f"\n알림 {len(result.notices)}건:")
        lines.extend(f"  - {notice}" for notice in result.notices)
    focus_errors = result.focus_errors()
    if focus_errors:
        lines.append(f"\n오류 {len(focus_errors)}건:")
        for problem in focus_errors:
            lines.append(f"  - {problem.message} [{', '.join(problem.files)}]")
    others = [problem for problem in result.errors if problem not in focus_errors]
    if others:
        lines.append(f"\n다른 파일의 오류 {len(others)}건(이 파일 검증 결과에는 넣지 않음):")
        for problem in others:
            lines.append(f"  - {problem.message} [{', '.join(problem.files)}]")
    return lines


def _read_all(synonyms_dir):
    """폴더의 *.json을 이름 순서로 읽는다. → ({이름: 내용}, [SynonymFile], [형식 오류])."""
    raws = {}
    files = []
    failures = []
    for path in sorted(Path(synonyms_dir).glob("*.json")):
        try:
            raw = read_raw(path)
            files.append(read_synonym_file(raw, path.name))
            raws[path.name] = raw
        except SynonymFileError as error:
            failures.append(str(error))
    return raws, files, failures


def _run_check(args, corpus):
    focus_path = Path(args.check)
    try:
        focus_file = read_synonym_file(read_raw(focus_path), focus_path.name)
    except SynonymFileError as error:
        print(f"관련어 파일 형식 오류: {error}")
        return 2
    context = []
    for path in sorted(Path(args.synonyms_dir).glob("*.json")):
        if path.name == focus_path.name:
            continue
        try:
            context.append(read_synonym_path(path))
        except SynonymFileError as error:
            print(f"참고: 맥락 파일 형식 오류(맥락에서 뺌): {error}")
    print(f"검증 대상 {focus_path.name}: 범위 '{focus_file.scope}', 묶음 {len(focus_file.groups)}개, "
          f"관계 {len(focus_file.relations)}개 (맥락 파일 {len(context)}개)")
    result = build(context + [focus_file], corpus, focus=focus_file.path)
    print("\n".join(report_lines(result)))
    problems = result.focus_errors()
    print("\n결과: " + ("문제 없음" if not problems else "문제 있음(위 목록을 고친 뒤 다시 검증)"))
    return 1 if problems else 0


def _previous_review_date(output, data):
    """내용(묶음·낱말·관계)이 이전 사전과 같으면 이전 검수 일자. 아니면 None."""
    try:
        previous = load_dictionary(output)
    except SearchDictionaryError:
        return None
    if previous["reviewed_on"] and content_signature(previous) == content_signature(data):
        return previous["reviewed_on"]
    if previous["reviewed_on"]:
        print(f"참고: 이전 사전의 검수 일자 {previous['reviewed_on']}는 내용이 바뀌어 이어 쓰지 않는다(다시 검수 필요).")
    return None


def main(argv=None, corpus=None):
    parser = argparse.ArgumentParser(description="관련어 사전 생성·검증(개발 전용)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", metavar="관련어파일", help="그 파일만 검증한다. 아무 파일도 쓰지 않는다")
    mode.add_argument("--apply-review", metavar="검수엑셀", help="검수 엑셀의 '검수 결과'를 관련어 파일에 반영하고 다시 생성한다")
    parser.add_argument("--reviewed-on", metavar="YYYY-MM-DD", help="사전에 적을 검수 일자")
    parser.add_argument("--synonyms-dir", default=str(DEFAULT_SYNONYMS_DIR), help="관련어 파일 폴더(*.json)")
    parser.add_argument("--notices-root", default=None, help="고시 기준본 폴더(기본: resources/notices)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="사전 출력 경로")
    parser.add_argument("--review-xlsx", default=str(DEFAULT_REVIEW_PATH), help="검수 엑셀 출력 경로")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 2
    if args.reviewed_on is not None and (args.check or not valid_date(args.reviewed_on)):
        print("--reviewed-on은 YYYY-MM-DD 꼴의 실제 날짜여야 하고 --check와 함께 쓰지 않는다")
        return 2
    if corpus is None:
        try:
            catalogue = load_catalogue(args.notices_root)
        except ValueError as error:
            print(f"고시 기준본을 불러오지 못했다: {error}")
            return 2
        corpus = Corpus.from_catalogue(catalogue)
    print(f"기준본 {corpus.catalogue_id} 지문 {corpus.fingerprint[:12]}… 항목 {len(corpus.docs)}개")
    if args.check:
        return _run_check(args, corpus)
    raws, files, failures = _read_all(args.synonyms_dir)
    if failures:
        print(f"관련어 파일 형식 오류 {len(failures)}건:")
        for failure in failures:
            print("  - " + failure)
        return 2
    if not files:
        print(f"관련어 파일이 없다: {args.synonyms_dir}")
        return 2
    print(f"관련어 파일 {len(files)}개: {', '.join(f.path for f in files)}")
    changed = {}
    if args.apply_review:
        try:
            term_actions, relation_actions = read_review(args.apply_review)
        except ReviewFileError as error:
            print(str(error))
            return 2
        modified = copy.deepcopy(raws)
        log, errors = apply_review(modified, term_actions, relation_actions)
        print(f"\n검수 결과 {len(term_actions) + len(relation_actions)}줄 읽음(같은 말 {len(term_actions)}, 관계 {len(relation_actions)})")
        if log:
            print("반영 내역:")
            print("\n".join("  - " + line for line in log))
        if errors:
            print(f"\n검수 결과를 반영하지 못했다(아무 파일도 고치지 않음) — 오류 {len(errors)}건:")
            print("\n".join("  - " + error for error in errors))
            return 1
        try:
            files = [read_synonym_file(modified[name], name) for name in modified]
        except SynonymFileError as error:
            print(f"\n반영한 결과의 형식이 틀리다(아무 파일도 고치지 않음): {error}")
            return 1
        changed = {name: data for name, data in modified.items() if data != raws[name]}
    result = build(files, corpus)
    print("\n" + "\n".join(report_lines(result)))
    if args.apply_review and not result.ok:
        print("\n반영한 결과가 검증을 통과하지 못했다. 아무 파일도 고치지 않았다.")
        return 1
    for name, data in changed.items():
        (Path(args.synonyms_dir) / name).write_text(format_synonym_payload(data), encoding="utf-8", newline="\n")
        print(f"관련어 파일 고침: {name}")
    generated_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    data = None
    if result.ok:
        data = dictionary_payload(result, corpus, generated_at, args.reviewed_on)
        if args.reviewed_on is None:
            data["reviewed_on"] = _previous_review_date(args.output, data)
            data["fingerprint"] = dictionary_fingerprint(data)
    write_review(result, args.review_xlsx, corpus, data, generated_at)
    print(f"\n검수 엑셀: {args.review_xlsx}")
    if not result.ok:
        print("사전을 만들지 않았다(오류가 있음).")
        return 1
    write_dictionary(data, args.output)
    load_dictionary(args.output)
    print(f"관련어 사전: {args.output}")
    print(f"사전 지문: {data['fingerprint']}  검수 일자: {data['reviewed_on'] or '(검수 전)'}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
