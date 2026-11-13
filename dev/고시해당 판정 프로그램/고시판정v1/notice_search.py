"""고시 검색 엔진(spec 3·4·5). AI 없이 PC 안에서만 돈다.

찾는 방법
  - 통제번호 검색(4.1): 검색어가 통제번호 모양이면 그 번호와 정확히 같은 조항(`통제번호 일치`)과 원문에서 그 번호를
    언급하는 다른 조항(`본문에서 언급`)만 보인다. 관련어·글자 유사·의미 유사를 쓰지 않는다.
  - 낱말 검색(4.3): 검색어(여러 낱말이면 낱말마다)를 관련어 사전으로 넓힌다(같은 말 → 한 단계 → 두 단계).
    글자 조각(한글은 자모로 풀어 3글자 조각) 비교로 오타·띄어쓰기·조사 차이를 흡수한다.
  - 의미 유사(4.5): 정적 단어 벡터 모델(resources/search_model)로 검색어만 벡터로 바꾸고, 미리 계산한 조항 조각 벡터
    (resources/search_vectors.*)와 비교한다. 처음 검색할 때 불러오며, 불러오지 못하면 꺼짐 상태로 계속 검색한다.
  - 과제 글 의미 순위(1.3.0 spec 5.2, `SearchEngine.semantic_ranking`): 과제 글 하나를 같은 모델·조항 벡터로 비교해
    고시별 실제 검토 항목 전체를 유사도 순으로 돌려준다(점수 없이 순서만). 관련어 사전·검색어 길이 상한은 쓰지 않는다.
    처리내역용 지문은 `semantic_model_fingerprint`·`semantic_vectors_fingerprint`.

지키는 것
  - 네트워크에 접속하지 않는다(파일만 읽는다). tokenizers는 `Tokenizer.from_file`만, numpy는 `np.load`만 쓴다.
  - 검색어를 어디에도 저장·기록하지 않는다(로그·파일·임시 파일 없음. 낱말 정규식 캐시(`term_pattern`의 lru_cache)가 프로세스 메모리 안에만 낱말을 잠시 두며, 파일로 남지 않고 프로그램을 끄면 사라진다).
  - 관련어 사전·모델·조항 벡터는 실행 중 바꾸지 않고 파일 안의 지문으로 검증한다(코드 상수 없음).
  - 숫자 점수는 결과에 넣지 않는다(내부 정렬에만). 결과는 JSON으로 그대로 넘길 수 있는 dict/list다.
  - `tools/`를 import하지 않는다(tools는 exe에 들어가지 않는다). 사전 불러오기·검증·낱말 맞추기 규칙은
    `tools/build_search_dictionary.py`와 같게 옮겨 두었고, 같은 결과를 내는지 시험(tests/test_notice_search.py)이 본다.
"""
from bisect import bisect_right
import datetime
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading

import paths
from judge_engine import FLAG_EXTRACTED, FLAG_REJECTED
from notice_catalogue import canonical_hash, clause_index, clause_record, load_catalogue
from pipeline import FAMILY_LABELS, FAMILY_ORDER
from threshold_table import BODY_SOURCE, STATUS_NONE, load_threshold_table

# ---------------------------------------------------------------------------
# 상수(조정할 자리)
# ---------------------------------------------------------------------------

MAX_QUERY_CHARS = 100        # 검색어 길이 상한(글자 수). 넘으면 SearchQueryError.
DEFAULT_LIMIT = 20           # 묶음마다 처음 보이는 건수
MAX_LIMIT = 600              # 한 번에 받을 수 있는 최대 건수(507개 전체가 한 번에 들어가는 값)
SNIPPET_BEFORE = 40          # 원문 일부: 찾은 낱말 앞쪽 글자 수
SNIPPET_CHARS = 160          # 원문 일부: 전체 글자 수(공백 정리 전 원문 기준)

# 검색 결과 묶음의 등급(spec 4.3). 작을수록 앞선다. 단계가 멀수록 순위를 낮춘다.
GRADE_QUERY = 0              # 검색어 그대로 일치
GRADE_SYNONYM = 1            # 같은 말 일치
GRADE_ONE_STEP = 2           # 한 단계 관련어(바로 위·아래 묶음)
GRADE_TWO_STEP = 3           # 두 단계 관련어(한 단계 묶음의 위·아래, 형제 묶음 포함)
GRADE_FUZZY = 4              # 글자 유사

# 글자 유사(spec 4.3): 한글은 자모로 풀고 영문은 소문자로 바꾼 뒤 3글자 조각의 Dice 계수로 비교한다.
# 0.7: '디스프레이'→'디스플레이'(0.82)는 잡고, 3글자 낱말의 한 글자 차이('레이저'↔'레이더' 0.5)는 잡지 않는 값.
FUZZY_MIN_DICE = 0.7
FUZZY_MIN_JAMO = 6           # 자모(영문은 글자)가 이보다 짧은 낱말은 글자 유사를 쓰지 않는다(짧은 말의 오탐 방지)
FUZZY_MAX_WORDS = 5          # 검색 낱말 하나에 붙이는 글자 유사 낱말 수 상한

# 의미 유사 최소 유사도(spec 4.5). 코드 상수이며 화면 설정은 없다.
# 0.32 근거(이 엔진의 조항 벡터 = resources/search_vectors.*로 잰 값, tests/test_notice_search가 지킨다):
#   - '김치찌개'의 최고 유사도 0.302 → 0.32 밑이라 비슷한 뜻 0건(spec 5).
#   - spec 4.5 여섯 질의(DRAM·디스플레이·이차전지·드론·암호·레이저)의 기대 조항 최고 유사도 중 가장 낮은 값 0.338
#     (디스플레이 → advanced:item:009) → 0.32 위라 모두 걸린다.
#   - 두 값 사이(0.302~0.338)의 가운데 근처이며, 모델 비교(tools/output/모델_비교.md)의 제안값과 같다.
MIN_SIMILARITY = 0.32

FILTER_ALL = "전체"
FILTERS = (FILTER_ALL,) + FAMILY_ORDER

# 찾은 이유 값 집합(spec 4.4). 글자 그대로 화면에 보인다.
REASON_QUERY = "검색어 일치"
REASON_SYNONYM = "같은 말"
REASON_ONE_STEP = "관련어(한 단계)"
REASON_TWO_STEP = "관련어(두 단계)"
REASON_FUZZY = "글자 비슷"
REASON_SEMANTIC = "뜻 비슷"
REASON_CODE = "통제번호 일치"
REASON_MENTION = "본문에서 언급"
REASON_ALL = "전체 목록"
REASON_WITH_TERM = (REASON_SYNONYM, REASON_ONE_STEP, REASON_TWO_STEP, REASON_FUZZY)   # '이유: 낱말' 꼴
REASON_PLAIN = (REASON_QUERY, REASON_SEMANTIC, REASON_CODE, REASON_MENTION, REASON_ALL)
GRADE_REASONS = {GRADE_QUERY: REASON_QUERY, GRADE_SYNONYM: REASON_SYNONYM, GRADE_ONE_STEP: REASON_ONE_STEP,
                 GRADE_TWO_STEP: REASON_TWO_STEP, GRADE_FUZZY: REASON_FUZZY}

MODE_KEYWORD = "keyword"     # 낱말 검색
MODE_CODE = "code"           # 통제번호 검색
MODE_ALL = "all"             # 빈 검색어 = 고른 고시 전체

# 화면 안내 문구(spec 2). Python 쪽이 완성해 넘긴다.
NOTICE_NO_RESULTS = "검색 결과 없음"
NOTICE_SIMILAR = "뜻이 비슷해 보이는 조항이며 맞지 않는 것이 섞일 수 있음"
NOTICE_SEMANTIC_OFF = "의미 유사 검색 꺼짐 — 관련어·글자 유사로만 검색"
NOTICE_DICTIONARY_OFF = "관련어 사전을 쓸 수 없음 — 검색어·글자 유사로만 검색"
NOTICE_FOOTER = "관련어 사전과 의미 유사 검색은 참고용이며, 고시 해당 여부는 원문으로 확인해야 함."
NO_NUMERIC_MESSAGE = "수치 기준 없음"
OPERATOR_LABELS = {"ge": "이상", "gt": "초과", "le": "이하", "lt": "미만"}        # excel_report와 같은 값
ORIGIN_LABELS = {"structured": "정리된 기준", "extracted": "AI가 읽은 기준값"}   # excel_report와 같은 값

SEMANTIC_READY = "ready"         # 불러옴
SEMANTIC_PENDING = "pending"     # 아직 검색하지 않아 불러오지 않음
SEMANTIC_OFF = "off"             # 불러오지 못함(사유를 함께 보인다)

# 과제 글 의미 순위(SearchEngine.semantic_ranking)를 쓸 수 없는 사유. 모델·벡터를 불러오지 못한 경우는 불러올 때의 사유.
RANKING_EMPTY_TEXT = "검색 글이 비어 있다"
RANKING_NO_WORDS = "검색 글에 의미 모델이 아는 낱말이 없다"
RANKING_ERROR = "의미 유사 계산 중 오류"

DOC_SEPARATOR = "\x00"           # 색인 글 조각을 잇는 자리. 공백이 아니어서 낱말이 경계를 넘어 맞지 않는다.

# 통제번호 모양(spec 4.1): 공백을 빼고 대문자로 바꾼 뒤 전체가 맞아야 한다. 하위 표기(.a, .1, .a.2 …)는 떼어 낸다.
CONTROL_NUMBER_RE = re.compile(r"(\d[A-E]\d{3}|ML\d{1,2})((?:\.[A-Z0-9]+)*)\.?")


class SearchError(ValueError):
    """검색 요청이 틀리다(화면 경계에서 거부할 것)."""


class SearchQueryError(SearchError):
    """검색어가 글이 아니거나 길이 상한을 넘는다."""


class SearchFilterError(SearchError):
    """고시 필터 값이 아니다."""


class UnknownClauseError(SearchError):
    """검색 대상(실제 검토 항목 507개)에 없는 조항 ID."""


# ---------------------------------------------------------------------------
# 관련어 사전: 불러오기·검증·낱말 맞추기 (tools/build_search_dictionary.py와 같은 규칙)
# ---------------------------------------------------------------------------

DICTIONARY_FORMAT = "search_dictionary/1"
GROUP_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
MAX_TERM_LENGTH = 80
DICTIONARY_KEYS = frozenset(("format", "catalogue_id", "catalogue_fingerprint", "generated_at", "reviewed_on",
                             "sources", "groups", "relations", "fingerprint"))
GROUP_KEYS = frozenset(("id", "terms", "note", "sources"))
TERM_KEYS = frozenset(("term", "count", "clauses"))
RELATION_KEYS = frozenset(("narrow", "broad", "note", "sources"))


class SearchDictionaryError(ValueError):
    """사전 파일이 없거나 형식이 틀리거나 지문이 맞지 않는다."""


def normalize_term(term):
    """같은 낱말인지 가리는 열쇠: 공백을 모두 빼고 대소문자를 무시한다."""
    return "".join(str(term).split()).casefold()


def _is_ascii_letter(char):
    return char.isascii() and char.isalpha()


def _is_ascii_alnum(char):
    return char.isascii() and char.isalnum()


@functools.lru_cache(maxsize=4096)
def term_pattern(term):
    """원문에서 낱말을 찾는 정규식(생성 도구와 같은 규칙).

    공백·대소문자 무시, 영문·숫자로 시작하면 앞이 영문·숫자가 아니어야 함, 영문으로 끝나면 복수형 s·es(y는 ies)까지
    받고 뒤가 영문이 아니어야 함, 숫자로 끝나면 뒤가 숫자가 아니어야 함. 한글은 경계를 보지 않는다(부분 일치).
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


def _read_json(path, error_class):
    """JSON 파일을 읽는다(키 중복·NaN 거부). 실패하면 error_class."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
        return json.loads(text, object_pairs_hook=_pairs_hook(error_class), parse_constant=_reject_constant)
    except error_class:
        raise
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as error:
        raise error_class(f"{path.name}: 읽지 못했다: {error}") from error


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


def dictionary_fingerprint(data):
    """사전 지문: fingerprint를 뺀 나머지 전부의 canonical SHA256."""
    return canonical_hash({key: value for key, value in data.items() if key != "fingerprint"})


def _dict_require(condition, message):
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
    """사전 내용(dict)을 검사한다. 틀리면 SearchDictionaryError(생성 도구의 validate_dictionary와 같은 규칙)."""
    _dict_require(isinstance(data, dict) and set(data) == DICTIONARY_KEYS,
                  f"사전 최상위 필드 구성이 다르다: {sorted(data) if isinstance(data, dict) else type(data).__name__}")
    _dict_require(data["format"] == DICTIONARY_FORMAT, f"사전 형식이 다르다: {data['format']!r}")
    for key in ("catalogue_id", "catalogue_fingerprint", "generated_at", "fingerprint"):
        _dict_require(isinstance(data[key], str) and data[key], f"{key} 값이 비어 있거나 글이 아니다")
    _dict_require(data["reviewed_on"] is None or valid_date(data["reviewed_on"]), "reviewed_on은 null 또는 YYYY-MM-DD")
    _dict_require(_string_list(data["sources"]), "sources는 글 목록이어야 한다")
    _dict_require(isinstance(data["groups"], list) and isinstance(data["relations"], list),
                  "groups·relations는 목록이어야 한다")
    ids = set()
    owners = {}
    for group in data["groups"]:
        _dict_require(isinstance(group, dict) and set(group) == GROUP_KEYS, "묶음 필드 구성이 다르다")
        group_id = group["id"]
        _dict_require(isinstance(group_id, str) and GROUP_ID_RE.match(group_id), f"묶음 id 모양이 아니다: {group_id!r}")
        _dict_require(group_id not in ids, f"묶음 id 중복: {group_id}")
        ids.add(group_id)
        _dict_require(isinstance(group["note"], str) and _string_list(group["sources"]),
                      f"묶음 '{group_id}' note·sources 형식")
        _dict_require(isinstance(group["terms"], list) and group["terms"], f"묶음 '{group_id}'에 낱말이 없다")
        for term in group["terms"]:
            _dict_require(isinstance(term, dict) and set(term) == TERM_KEYS, f"묶음 '{group_id}' 낱말 필드 구성이 다르다")
            _dict_require(term_problem(term["term"]) is None, f"묶음 '{group_id}' 낱말 모양이 틀리다: {term['term']!r}")
            _dict_require(_is_count(term["count"]) and _is_count(term["clauses"]) and term["clauses"] <= term["count"],
                          f"묶음 '{group_id}' 낱말 '{term['term']}' 건수가 틀리다")
            key = normalize_term(term["term"])
            _dict_require(key not in owners, f"낱말 '{term['term']}'이 두 번 있다({owners.get(key)}, {group_id})")
            owners[key] = group_id
        _dict_require(any(term["count"] for term in group["terms"]), f"묶음 '{group_id}'의 낱말이 하나도 원문에 없다")
    pairs = set()
    for relation in data["relations"]:
        _dict_require(isinstance(relation, dict) and set(relation) == RELATION_KEYS, "관계 필드 구성이 다르다")
        narrow, broad = relation["narrow"], relation["broad"]
        _dict_require(narrow in ids and broad in ids, f"관계 {narrow} → {broad}의 묶음이 없다")
        _dict_require(narrow != broad and (narrow, broad) not in pairs, f"관계 {narrow} → {broad}가 틀리거나 두 번 있다")
        _dict_require(isinstance(relation["note"], str) and _string_list(relation["sources"]), "관계 note·sources 형식")
        pairs.add((narrow, broad))
    cycles = find_cycles(sorted(pairs))
    _dict_require(not cycles, f"관계에 순환이 있다: {' → '.join(cycles[0]) if cycles else ''}")
    _dict_require(dictionary_fingerprint(data) == data["fingerprint"], "사전 지문이 맞지 않는다(파일이 바뀌었다)")
    if catalogue is not None:
        _dict_require(data["catalogue_fingerprint"] == catalogue.fingerprint,
                      "사전을 만든 고시 기준본과 지금 기준본이 다르다")
    return data


def load_dictionary(path, catalogue=None):
    """사전 파일을 읽어 검사한다(지문 포함). 틀리면 SearchDictionaryError(fail-closed)."""
    return validate_dictionary(_read_json(path, SearchDictionaryError), catalogue)


def dictionary_path():
    return paths.resource_path("search_dictionary.json")


# ---------------------------------------------------------------------------
# 조항 조각(의미 벡터용). tools/compare_search_models.clause_chunks와 같은 결과를 낸다.
# ---------------------------------------------------------------------------

CHUNK_CHARS = 300
# 조각 규칙. 조항 벡터 파일에 그대로 적고, 불러올 때 이 값과 같은지 본다(규칙을 바꾸면 벡터를 다시 만든다).
CHUNK_RULE = {
    "version": 1,
    "max_chars": CHUNK_CHARS,
    "split": "줄 단위로 모으고, 한 줄이 최대 글자 수보다 길면 잘라 나눈다(공백은 하나로 정리)",
    "header": "조각마다 첫 줄에 '통제번호 제목 분야'(기준본 clause_index의 code·title·field)",
    "clause_score": "가장 비슷한 조각의 코사인 유사도",
}


def _clean(value):
    return " ".join(str(value).split())


def clause_chunks(catalogue, chunk_chars=CHUNK_CHARS):
    """(clause_id 목록, 조각 글 목록, 조항마다 조각 수). 조항 순서는 clause_index 순서, 조각은 조항 순서대로 이어진다."""
    ids, texts, counts = [], [], []
    for entry in clause_index(catalogue):
        ids.append(entry["clause_id"])
        header = _clean(" ".join(x for x in (entry["code"], entry["title"], entry["field"]) if x))
        body = clause_record(catalogue, entry["clause_id"])["text"]
        pieces, current = [], ""
        for line in (_clean(x) for x in body.splitlines()):
            if not line:
                continue
            while len(line) > chunk_chars:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(line[:chunk_chars])
                line = line[chunk_chars:]
            if current and len(current) + 1 + len(line) > chunk_chars:
                pieces.append(current)
                current = line
            else:
                current = f"{current} {line}".strip()
        if current:
            pieces.append(current)
        if not pieces:
            pieces = [""]
        for piece in pieces:
            texts.append(f"{header}\n{piece}".strip())
        counts.append(len(pieces))
    return ids, texts, counts


def chunk_content_fingerprint(ids, texts, counts):
    """조각 내용 지문: 조항 ID 순서·조항별 조각 수·조각 글 전부의 canonical SHA256."""
    return canonical_hash({"clause_ids": list(ids), "chunk_counts": list(counts), "chunks": list(texts)})


# ---------------------------------------------------------------------------
# 의미 벡터 모델(정적 단어 벡터)과 조항 벡터 파일
# ---------------------------------------------------------------------------

MODEL_INFO_NAME = "MODEL_INFO.json"
MODEL_RUNTIME_FILES = ("embeddings_int8.npy", "scales_float32.npy", "token_ids_int32.npy", "tokenizer.json")
VECTORS_FORMAT = "search_vectors/1"
VECTORS_JSON = "search_vectors.json"
VECTORS_NPY = "search_vectors.npy"
VECTORS_KEYS = frozenset(("format", "catalogue_id", "catalogue_fingerprint", "model", "chunk_rule", "clause_ids",
                          "chunk_counts", "content_fingerprint", "vectors", "generated_at", "fingerprint"))
VECTORS_MODEL_KEYS = frozenset(("name", "fingerprint", "files"))
VECTORS_ARRAY_KEYS = frozenset(("file", "dtype", "shape", "sha256", "normalized"))
_HASH_BLOCK = 1 << 20


class SearchModelError(RuntimeError):
    """모델 파일이 없거나 지문이 맞지 않거나 라이브러리가 동작하지 않는다(의미 유사를 끈다)."""


class SearchVectorsError(RuntimeError):
    """조항 벡터 파일이 없거나 형식·지문이 맞지 않는다(의미 유사를 끈다)."""


def model_dir():
    return paths.resource_path("search_model")


def vectors_path():
    return paths.resource_path(VECTORS_JSON)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def model_fingerprint(file_hashes):
    """모델 지문: 실행에 쓰는 모델 파일 네 개의 {이름: SHA256}의 canonical SHA256."""
    return canonical_hash({name: file_hashes[name] for name in MODEL_RUNTIME_FILES})


def _offline_environment():
    """모델 라이브러리의 온라인 확인·사용 통계를 끈다. tokenizers를 import하기 전에 부른다."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"


class StaticEmbeddingModel:
    """배포 형식(resources/search_model)의 정적 단어 벡터 모델. MODEL_INFO.json의 파일 SHA256을 확인한 뒤에만 쓴다.

    벡터 = 낱말 벡터(int8 × 행별 축척)의 평균을 L2 정규화한 것. [UNK]와 벡터가 없는 낱말은 건너뛴다.
    """

    def __init__(self, folder=None):
        folder = Path(folder) if folder is not None else model_dir()
        try:
            info = _read_json(folder / MODEL_INFO_NAME, SearchModelError)
            files = info.get("files") if isinstance(info, dict) else None
            if not isinstance(files, dict):
                raise SearchModelError("MODEL_INFO.json에 files가 없다")
            hashes = {}
            for name in MODEL_RUNTIME_FILES:
                entry = files.get(name)
                if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
                    raise SearchModelError(f"MODEL_INFO.json에 {name} 지문이 없다")
                path = folder / name
                if not path.is_file():
                    raise SearchModelError(f"모델 파일이 없다: {name}")
                actual = file_sha256(path)
                if actual != entry["sha256"]:
                    raise SearchModelError(f"모델 파일 지문이 맞지 않는다: {name}")
                hashes[name] = actual
            dims = info.get("runtime", {}).get("embedding_dim") if isinstance(info.get("runtime"), dict) else None
            _offline_environment()
            import numpy as np
            from tokenizers import Tokenizer
            tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
            tokenizer.no_truncation()
            tokenizer.no_padding()
            embeddings = np.load(folder / "embeddings_int8.npy", allow_pickle=False)
            scales = np.load(folder / "scales_float32.npy", allow_pickle=False)
            token_ids = np.load(folder / "token_ids_int32.npy", allow_pickle=False)
            if (embeddings.ndim != 2 or embeddings.dtype != np.int8 or scales.shape != (embeddings.shape[0],)
                    or token_ids.shape != (embeddings.shape[0],) or (dims is not None and embeddings.shape[1] != dims)):
                raise SearchModelError("모델 배열 모양이 맞지 않는다")
            vocab = tokenizer.get_vocab_size(with_added_tokens=True)
            if token_ids.size and (int(token_ids.min()) < 0 or int(token_ids.max()) >= vocab):
                raise SearchModelError("모델 낱말 번호가 토크나이저 범위 밖이다")
            row_of = np.full(vocab, -1, dtype=np.int64)
            row_of[token_ids] = np.arange(len(token_ids))
            unk = tokenizer.token_to_id("[UNK]")
            if unk is not None:
                row_of[unk] = -1
        except SearchModelError:
            raise
        except Exception as error:   # 라이브러리 import·파일 읽기 실패 모두 꺼짐 사유로 돌린다.
            raise SearchModelError(f"모델을 불러오지 못했다: {type(error).__name__}: {error}") from error
        self.np = np
        self.tokenizer = tokenizer
        self.embeddings = embeddings
        self.scales = scales
        self.row_of = row_of
        self.dims = int(embeddings.shape[1])
        self.name = str(info.get("name", ""))
        self.file_hashes = hashes
        self.fingerprint = model_fingerprint(hashes)

    def encode(self, texts):
        """글 목록 → (글 수 × 차원) float32, 행마다 L2 정규화(낱말이 하나도 없으면 영벡터)."""
        np = self.np
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for row, encoding in enumerate(self.tokenizer.encode_batch(list(texts), add_special_tokens=False)):
            rows = self.row_of[np.asarray(encoding.ids, dtype=np.int64)]
            rows = rows[rows >= 0]
            if rows.size:
                out[row] = (self.embeddings[rows].astype(np.float32) * self.scales[rows, None]).mean(axis=0)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


def vectors_fingerprint(payload):
    """조항 벡터 파일(JSON) 지문: fingerprint를 뺀 나머지 전부의 canonical SHA256."""
    return canonical_hash({key: value for key, value in payload.items() if key != "fingerprint"})


def _vec_require(condition, message):
    if not condition:
        raise SearchVectorsError(message)


def load_vectors(path, catalogue, model, chunks=None):
    """조항 벡터를 읽고 검증한다. 돌려주는 값: (조각 벡터 float32 행렬, 조항별 첫 조각 위치, 조각 글 목록).

    확인: 필드 구성·형식, 파일 지문, 기준본 지문, 모델 지문, 조각 규칙, 조항 ID 순서, 조각 내용 지문(기준본에서 다시
    계산), .npy 파일 SHA256·모양·자료형. 하나라도 틀리면 SearchVectorsError.
    """
    matrix, starts, texts, _ = load_vectors_with_fingerprint(path, catalogue, model, chunks)
    return matrix, starts, texts


def load_vectors_with_fingerprint(path, catalogue, model, chunks=None):
    """load_vectors와 같은 검증을 하고, 검증한 조항 벡터 파일 지문(JSON의 fingerprint)까지 돌려준다(처리내역용).

    돌려주는 값: (조각 벡터 float32 행렬, 조항별 첫 조각 위치, 조각 글 목록, 조항 벡터 파일 지문).
    """
    import numpy as np
    path = Path(path)
    payload = _read_json(path, SearchVectorsError)
    _vec_require(isinstance(payload, dict) and set(payload) == VECTORS_KEYS, "조항 벡터 파일 필드 구성이 다르다")
    _vec_require(payload["format"] == VECTORS_FORMAT, "조항 벡터 파일 형식이 다르다")
    _vec_require(payload["fingerprint"] == vectors_fingerprint(payload), "조항 벡터 파일 지문이 맞지 않는다")
    _vec_require(payload["catalogue_fingerprint"] == catalogue.fingerprint, "조항 벡터를 만든 고시 기준본과 지금 기준본이 다르다")
    model_entry = payload["model"]
    _vec_require(isinstance(model_entry, dict) and set(model_entry) == VECTORS_MODEL_KEYS, "조항 벡터의 모델 기록 형식")
    _vec_require(model_entry["fingerprint"] == model.fingerprint, "조항 벡터를 만든 모델과 지금 모델이 다르다(모델 지문 불일치)")
    _vec_require(payload["chunk_rule"] == CHUNK_RULE, "조항 벡터의 조각 규칙이 지금 규칙과 다르다")
    ids, texts, counts = chunks if chunks is not None else clause_chunks(catalogue)
    _vec_require(payload["clause_ids"] == list(ids), "조항 벡터의 조항 목록이 기준본과 다르다")
    _vec_require(payload["chunk_counts"] == list(counts), "조항 벡터의 조각 수가 기준본과 다르다")
    _vec_require(payload["content_fingerprint"] == chunk_content_fingerprint(ids, texts, counts),
                 "조항 벡터의 조각 내용 지문이 맞지 않는다")
    array = payload["vectors"]
    _vec_require(isinstance(array, dict) and set(array) == VECTORS_ARRAY_KEYS, "조항 벡터 배열 기록 형식")
    _vec_require(array["file"] == VECTORS_NPY and array["dtype"] == "float16" and array["normalized"] is True,
                 "조항 벡터 배열 기록 값")
    npy = path.with_name(array["file"])
    _vec_require(npy.is_file(), f"조항 벡터 배열 파일이 없다: {array['file']}")
    _vec_require(file_sha256(npy) == array["sha256"], "조항 벡터 배열 파일 지문이 맞지 않는다")
    try:
        matrix = np.load(npy, allow_pickle=False)
    except Exception as error:
        raise SearchVectorsError(f"조항 벡터 배열을 읽지 못했다: {type(error).__name__}") from error
    _vec_require(matrix.dtype == np.float16 and list(matrix.shape) == array["shape"]
                 and matrix.shape == (len(texts), model.dims), "조항 벡터 배열 모양이 맞지 않는다")
    starts = np.zeros(len(counts), dtype=np.int64)
    if len(counts) > 1:
        starts[1:] = np.cumsum(np.asarray(counts[:-1], dtype=np.int64))
    return matrix.astype(np.float32), starts, texts, payload["fingerprint"]


def vectors_payload(catalogue, model, chunks, npy_sha256, shape, generated_at):
    """조항 벡터 파일(JSON) 내용을 만든다(tools/build_search_vectors.py가 쓴다)."""
    ids, texts, counts = chunks
    payload = {
        "format": VECTORS_FORMAT,
        "catalogue_id": catalogue.manifest["catalogue_id"],
        "catalogue_fingerprint": catalogue.fingerprint,
        "model": {"name": model.name, "fingerprint": model.fingerprint,
                  "files": {name: model.file_hashes[name] for name in MODEL_RUNTIME_FILES}},
        "chunk_rule": dict(CHUNK_RULE),
        "clause_ids": list(ids),
        "chunk_counts": list(counts),
        "content_fingerprint": chunk_content_fingerprint(ids, texts, counts),
        "vectors": {"file": VECTORS_NPY, "dtype": "float16", "shape": list(shape), "sha256": npy_sha256,
                    "normalized": True},
        "generated_at": generated_at,
    }
    payload["fingerprint"] = vectors_fingerprint(payload)
    return payload


# ---------------------------------------------------------------------------
# 글자 유사(자모 3글자 조각)
# ---------------------------------------------------------------------------

_CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNGSEONG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONGSEONG = ("", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ",
              "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _is_hangul(char):
    return "가" <= char <= "힣"


def jamo_string(word):
    """한글 음절은 자모로 풀고 영문은 소문자로 바꾼다(글자 조각 비교용)."""
    out = []
    for char in normalize_term(word):
        if _is_hangul(char):
            code = ord(char) - 0xAC00
            out.append(_CHOSEONG[code // 588])
            out.append(_JUNGSEONG[(code // 28) % 21])
            out.append(_JONGSEONG[code % 28])
        else:
            out.append(char)
    return "".join(out)


def trigrams(text):
    if len(text) < 3:
        return {text} if text else set()
    return {text[i:i + 3] for i in range(len(text) - 2)}


def dice(a, b):
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


# ---------------------------------------------------------------------------
# 결과 글 다듬기
# ---------------------------------------------------------------------------

def _merge_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def excerpt(text, start, end, spans):
    """text[start:end]를 공백 정리한 원문 일부와, 그 안의 강조 위치([시작, 끝) 문자 범위 목록).

    줄바꿈·연속 공백은 공백 하나로 줄이고 앞뒤 공백은 뗀다. 잘린 쪽에는 '…'를 붙인다.
    강조 위치는 돌려준 글의 글자 위치(Python 문자열 색인)다.
    """
    start, end = max(0, start), min(len(text), end)
    out = []
    position = {}     # 원문 위치 → 결과 위치
    pending_space = False
    for index in range(start, end):
        char = text[index]
        if char.isspace():
            pending_space = bool(out)
            position[index] = len(out)
            continue
        if pending_space:
            out.append(" ")
            pending_space = False
        position[index] = len(out)
        out.append(char)
    body = "".join(out)
    lead = "…" if start > 0 else ""
    tail = "…" if end < len(text) else ""
    shift = len(lead)
    highlights = []
    for span_start, span_end in _merge_spans(spans):
        span_start, span_end = max(span_start, start), min(span_end, end)
        if span_start >= span_end:
            continue
        # 강조 범위 안의 첫·마지막 공백 아닌 글자 위치를 쓴다.
        inner = [i for i in range(span_start, span_end) if not text[i].isspace()]
        if not inner:
            continue
        highlights.append([position[inner[0]] + shift, position[inner[-1]] + 1 + shift])
    return lead + body + tail, highlights


def _code_key(code):
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", code) if part)


def parse_control_number(query):
    """통제번호 모양이면 하위 표기를 뗀 번호(대문자), 아니면 None(spec 4.1)."""
    if not isinstance(query, str):
        return None
    squeezed = "".join(query.split()).upper()
    match = CONTROL_NUMBER_RE.fullmatch(squeezed)
    return match.group(1) if match else None


def mention_pattern(code):
    """원문에서 통제번호 언급을 찾는 정규식. 앞뒤 경계를 보며(ML1이 ML10 안에서 맞지 않게) 대소문자를 가린다.

    군용은 'ML 11'처럼 ML과 숫자 사이 공백이 원문에 있어 공백을 허용한다.
    """
    if code.startswith("ML"):
        return re.compile(r"(?<![A-Za-z0-9])ML\s*" + re.escape(code[2:]) + r"(?![0-9])")
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![0-9])")


def format_reason(reasons):
    """찾은 이유 목록 → 화면 표기: 가장 앞선 것 하나와 '외 N'."""
    if not reasons:
        return ""
    if len(reasons) == 1:
        return reasons[0]
    return f"{reasons[0]} 외 {len(reasons) - 1}"


# ---------------------------------------------------------------------------
# 검색 엔진
# ---------------------------------------------------------------------------

class _Doc:
    __slots__ = ("number", "clause_id", "family", "code", "title", "field", "text", "search_text", "title_text",
                 "order_key", "subjects")

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class SearchEngine:
    """고시 검색. 만들 때 기준본·기준값 표·관련어 사전을 읽고, 의미 유사 모델·조항 벡터는 처음 검색할 때 읽는다.

    catalogue·table을 주지 않으면 프로그램 자원에서 읽는다(검증 실패는 예외 — 검토 기능과 같은 fail-closed).
    관련어 사전·모델·조항 벡터는 실패해도 예외를 내지 않고 상태(status)에 사유를 싣는다.
    여러 스레드에서 불러도 된다(읽기만 하며, 지연 로딩은 잠금으로 한 번만 한다).
    """

    def __init__(self, catalogue=None, table=None, *, dictionary_file=None, model_folder=None, vectors_file=None):
        self.catalogue = catalogue if catalogue is not None else load_catalogue()
        self.table = table if table is not None else load_threshold_table(catalogue=self.catalogue)
        self._model_folder = Path(model_folder) if model_folder is not None else model_dir()
        self._vectors_file = Path(vectors_file) if vectors_file is not None else vectors_path()
        self._lock = threading.Lock()
        self._semantic_state = SEMANTIC_PENDING
        self._semantic_reason = ""
        self._model = None
        self._chunk_vectors = None
        self._chunk_starts = None
        self._chunk_texts = None
        # 과제 글 순위가 쓰는 묶음 (모델, 조각 벡터, 조항별 첫 조각 위치, 조항 벡터 파일 지문). 불러오기에 성공했을 때
        # 잠금 안에서 한 번에 바꿔 넣으므로, 읽는 쪽은 잠금 없이 한 번 읽어 서로 맞는 값을 얻는다.
        self._semantic_parts = None
        self._fuzzy_index = None
        self._build_docs()
        self._load_dictionary(Path(dictionary_file) if dictionary_file is not None else dictionary_path())

    # ── 색인 ───────────────────────────────────────────────────────────

    def _build_docs(self):
        records = {record["clause_id"]: record for record in self.table.all_records()}
        self.records = records
        docs = []
        family_rank = {family: rank for rank, family in enumerate(FAMILY_ORDER)}
        for number, entry in enumerate(clause_index(self.catalogue)):
            record = clause_record(self.catalogue, entry["clause_id"])
            table_record = records.get(entry["clause_id"])
            title = _clean(table_record["title"]) if table_record and table_record["title"].strip() else _clean(entry["title"])
            subjects = []
            if table_record:
                for branch in table_record["branches"]:
                    for threshold in branch["thresholds"]:
                        if threshold["subject"] not in subjects:
                            subjects.append(threshold["subject"])
            text = record["text"]
            squeezed = normalize_term(text)
            pieces = [text]
            for extra in [title, entry["code"], entry["field"]] + subjects:
                if extra and normalize_term(extra) not in squeezed:
                    pieces.append(extra)
            docs.append(_Doc(
                number=number, clause_id=entry["clause_id"], family=entry["family"], code=entry["code"], title=title,
                field=entry["field"], text=text, search_text=DOC_SEPARATOR.join(pieces),
                title_text=DOC_SEPARATOR.join(x for x in (title, entry["code"]) if x), subjects=subjects,
                order_key=(family_rank[entry["family"]], _code_key(entry["code"]), number)))
        self.docs = docs
        self.by_id = {doc.clause_id: doc for doc in docs}
        # 낱말 후보를 빨리 거르는 글: 모든 색인 글을 공백 없이·소문자로 이어 둔 것과 각 글의 시작 위치.
        squeezed_docs = [normalize_term(doc.search_text) for doc in docs]
        self._starts = []
        position = 0
        for squeezed in squeezed_docs:
            self._starts.append(position)
            position += len(squeezed) + 1
        self._squeezed_all = DOC_SEPARATOR.join(squeezed_docs)

    def _load_dictionary(self, path):
        self.dictionary_reviewed_on = None
        self._owner = {}
        self._group_terms = {}
        self._neighbours = {}
        try:
            data = load_dictionary(path, self.catalogue)
        except SearchDictionaryError as error:
            self.dictionary_ok = False
            self.dictionary_reason = str(error)
            return
        self.dictionary_ok = True
        self.dictionary_reason = ""
        self.dictionary_reviewed_on = data["reviewed_on"]
        for group in data["groups"]:
            self._group_terms[group["id"]] = [term["term"] for term in group["terms"]]
            for term in group["terms"]:
                self._owner[normalize_term(term["term"])] = group["id"]
        for relation in data["relations"]:
            self._neighbours.setdefault(relation["narrow"], []).append(relation["broad"])
            self._neighbours.setdefault(relation["broad"], []).append(relation["narrow"])

    # ── 상태 ───────────────────────────────────────────────────────────

    def status(self):
        """관련어 사전·의미 유사의 상태. 화면은 notice가 비어 있지 않으면 안내를 띄운다."""
        semantic_off = self._semantic_state == SEMANTIC_OFF
        return dict(
            dictionary=dict(available=self.dictionary_ok, reason=self.dictionary_reason,
                            reviewed_on=self.dictionary_reviewed_on,
                            notice="" if self.dictionary_ok else NOTICE_DICTIONARY_OFF),
            semantic=dict(state=self._semantic_state, available=self._semantic_state == SEMANTIC_READY,
                          reason=self._semantic_reason, notice=NOTICE_SEMANTIC_OFF if semantic_off else ""),
        )

    def ensure_semantic(self):
        """의미 유사 모델과 조항 벡터를 (아직이면) 불러온다. 실패하면 꺼짐 상태와 사유를 남긴다. 상태를 돌려준다."""
        with self._lock:
            if self._semantic_state == SEMANTIC_PENDING:
                try:
                    model = StaticEmbeddingModel(self._model_folder)
                    vectors, starts, texts, vectors_fp = load_vectors_with_fingerprint(self._vectors_file,
                                                                                      self.catalogue, model)
                except (SearchModelError, SearchVectorsError) as error:
                    self._semantic_state = SEMANTIC_OFF
                    self._semantic_reason = str(error)
                except Exception as error:   # 예상하지 못한 실패도 검색은 계속한다.
                    self._semantic_state = SEMANTIC_OFF
                    self._semantic_reason = f"의미 유사 검색을 준비하지 못했다: {type(error).__name__}"
                else:
                    self._model, self._chunk_vectors, self._chunk_starts, self._chunk_texts = model, vectors, starts, texts
                    self._semantic_parts = (model, vectors, starts, vectors_fp)
                    self._semantic_state = SEMANTIC_READY
        return self.status()["semantic"]

    @property
    def semantic_model_fingerprint(self):
        """처리내역용 의미 모델 지문(model_fingerprint: MODEL_INFO.json에 적힌 실행 파일 네 개 SHA256의 canonical SHA256).

        불러오기 전이거나 불러오지 못했으면 빈 글. 이 속성은 모델을 불러오지 않는다.
        """
        parts = self._semantic_parts
        return parts[0].fingerprint if parts is not None else ""

    @property
    def semantic_vectors_fingerprint(self):
        """처리내역용 조항 벡터 지문(resources/search_vectors.json의 fingerprint, 불러올 때 검증한 값).

        불러오기 전이거나 불러오지 못했으면 빈 글. 이 속성은 벡터를 불러오지 않는다.
        """
        parts = self._semantic_parts
        return parts[3] if parts is not None else ""

    # ── 검색어 넓히기 ───────────────────────────────────────────────────

    def expand(self, unit):
        """검색 단위 하나 → [(낱말, 등급)]. 같은 말 → 한 단계 → 두 단계(사전이 없으면 검색어만)."""
        terms = [(unit, GRADE_QUERY)]
        if not self.dictionary_ok:
            return terms
        key = normalize_term(unit)
        group = self._owner.get(key)
        if group is None:
            return terms
        terms += [(term, GRADE_SYNONYM) for term in self._group_terms[group] if normalize_term(term) != key]
        seen = {group}
        frontier = [group]
        for grade in (GRADE_ONE_STEP, GRADE_TWO_STEP):
            next_frontier = []
            for current in frontier:
                for neighbour in self._neighbours.get(current, ()):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        next_frontier.append(neighbour)
            terms += [(term, grade) for neighbour in next_frontier for term in self._group_terms[neighbour]]
            frontier = next_frontier
        return terms

    def _fuzzy_vocabulary(self):
        if self._fuzzy_index is None:
            words = {}
            for doc in self.docs:
                for token in TOKEN_RE.findall(doc.search_text):
                    words.setdefault(normalize_term(token), token)
            grams = {}
            entries = []
            for key, token in words.items():
                jamo = jamo_string(key)
                number = len(entries)
                entries.append((key, token, jamo))
                for gram in trigrams(jamo):
                    grams.setdefault(gram, []).append(number)
            self._fuzzy_index = (entries, grams)
        return self._fuzzy_index

    def fuzzy_words(self, word, exclude=()):
        """글자가 비슷한 원문 낱말(최대 FUZZY_MAX_WORDS개). 한글 낱말은 조사가 붙은 꼴도 앞부분으로 비교한다."""
        jamo = jamo_string(word)
        if len(jamo) < FUZZY_MIN_JAMO:
            return []
        query_grams = trigrams(jamo)
        entries, grams = self._fuzzy_vocabulary()
        shared = {}
        for gram in query_grams:
            for number in grams.get(gram, ()):
                shared[number] = shared.get(number, 0) + 1
        need = max(1, math.ceil(len(query_grams) * FUZZY_MIN_DICE / 2))
        query_key = normalize_term(word)
        excluded = {normalize_term(x) for x in exclude} | {query_key}
        length = len(query_key)
        found = {}
        for number, count in shared.items():
            if count < need:
                continue
            key, token, _ = entries[number]
            variants = [(token, False)]
            if any(_is_hangul(char) for char in token):
                variants += [(token[:size], True) for size in range(max(1, length - 1), length + 2) if size < len(token)]
            for variant, truncated in variants:
                variant_key = normalize_term(variant)
                if variant_key in excluded or not variant_key:
                    continue
                if truncated and variant_key in query_key:
                    continue   # 잘라 낸 앞부분이 검색 낱말의 일부일 뿐이면('반도체' → '반도') 뺀다

                score = dice(query_grams, trigrams(jamo_string(variant)))
                if score >= FUZZY_MIN_DICE and score > found.get(variant_key, (0.0, ""))[0]:
                    found[variant_key] = (score, variant)
        # 검색 낱말을 품은 낱말(이미 검색어 일치로 잡힘)과, 다른 후보를 품은 낱말(조사가 붙은 꼴 — 한글은 부분 일치라
        # 짧은 쪽이 이미 잡음)은 뺀다.
        keys = [key for key in found if query_key not in key]
        keys = [key for key in keys if not any(other != key and other in key for other in keys)]
        ranked = sorted((found[key] for key in keys), key=lambda item: (-item[0], item[1]))
        return [variant for _, variant in ranked[:FUZZY_MAX_WORDS]]

    def _candidate_docs(self, term):
        """공백 없는·소문자 글에서 낱말이 들어 있을 수 있는 색인 글 번호(정규식으로 다시 확인할 후보)."""
        key = normalize_term(term)
        if len(key) > 1 and key[-1] == "y" and _is_ascii_letter(key[-2]):
            key = key[:-1]
        found = []
        haystack = self._squeezed_all
        position = haystack.find(key)
        while position >= 0:
            number = bisect_right(self._starts, position) - 1
            found.append(number)
            next_start = self._starts[number + 1] if number + 1 < len(self._starts) else len(haystack)
            position = haystack.find(key, next_start)
        return found

    def term_hits(self, term, allowed=None):
        """낱말 → {글 번호: (본문·제목 등 전체 건수, 제목·통제번호 건수)}."""
        pattern = term_pattern(term)
        hits = {}
        for number in self._candidate_docs(term):
            if allowed is not None and number not in allowed:
                continue
            doc = self.docs[number]
            count = len(pattern.findall(doc.search_text))
            if count:
                hits[number] = (count, len(pattern.findall(doc.title_text)))
        return hits

    # ── 검색 ───────────────────────────────────────────────────────────

    @staticmethod
    def _check_query(query):
        if query is None:
            query = ""
        if not isinstance(query, str):
            raise SearchQueryError("검색어가 글이 아니다")
        if len(query) > MAX_QUERY_CHARS:
            raise SearchQueryError(f"검색어는 {MAX_QUERY_CHARS}자까지 쓸 수 있다")
        return " ".join(query.split())

    @staticmethod
    def _check_filter(family):
        if family is None:
            return FILTER_ALL
        if family not in FILTERS:
            raise SearchFilterError(f"고시 필터 값이 아니다: {family!r}")
        return family

    @staticmethod
    def _check_page(offset, limit):
        for value in (offset, limit):
            if isinstance(value, bool) or not isinstance(value, int):
                raise SearchError("offset·limit은 정수여야 한다")
        if offset < 0 or not 1 <= limit <= MAX_LIMIT:
            raise SearchError(f"offset은 0 이상, limit은 1~{MAX_LIMIT}")

    def _allowed(self, family):
        if family == FILTER_ALL:
            return set(range(len(self.docs)))
        return {doc.number for doc in self.docs if doc.family == family}

    def search(self, query, family=FILTER_ALL, limit=DEFAULT_LIMIT, offset=0, similar_offset=0):
        """검색. 두 묶음(results: 검색 결과, similar: 비슷한 뜻)을 묶음마다 offset부터 limit건 돌려준다.

        검색어 길이 상한(MAX_QUERY_CHARS)을 넘거나 필터·쪽 값이 틀리면 SearchError. 검색어는 어디에도 남기지 않는다.
        """
        query = self._check_query(query)
        family = self._check_filter(family)
        self._check_page(offset, limit)
        self._check_page(similar_offset, limit)
        allowed = self._allowed(family)
        semantic = self.ensure_semantic()
        code = parse_control_number(query) if query else None
        similar_rows = []
        similar_visible = semantic["available"]
        if not query:
            mode = MODE_ALL
            rows = [(doc, [REASON_ALL], [], None) for doc in sorted((self.docs[n] for n in allowed),
                                                                       key=lambda d: d.order_key)]
            similar_visible = False
        elif code is not None:
            mode = MODE_CODE
            rows = self._code_rows(code, allowed)
        else:
            mode = MODE_KEYWORD
            rows = self._keyword_rows(query, allowed)
            if semantic["available"]:
                taken = {doc.number for doc, *_ in rows}
                try:
                    similar_rows = self._semantic_rows(query, allowed - taken)
                except Exception as error:  # noqa: BLE001 — 실행 중 실패도 꺼짐으로 돌리고 검색은 계속한다(spec 4.5)
                    with self._lock:
                        self._semantic_state = SEMANTIC_OFF
                        self._semantic_reason = f"의미 유사 검색 중 오류: {type(error).__name__}"
                    similar_rows = []
        return dict(
            mode=mode, family=family, family_label=FAMILY_LABELS.get(family, FILTER_ALL),
            results=self._page(rows, offset, limit, visible=True),
            similar=dict(self._page(similar_rows, similar_offset, limit, visible=similar_visible),
                         notice=NOTICE_SIMILAR),
            status=self.status(), footer=NOTICE_FOOTER,
            empty_message=NOTICE_NO_RESULTS if not rows and not similar_rows else "",
        )

    def _page(self, rows, offset, limit, visible):
        page = rows[offset:offset + limit]
        items = [self._item(*row) for row in page]
        remaining = max(0, len(rows) - offset - len(page))
        return dict(items=items, total=len(rows), offset=offset, limit=limit, remaining=remaining,
                    has_more=remaining > 0, visible=visible,
                    empty_message=NOTICE_NO_RESULTS if not rows else "")

    def _item(self, doc, reasons, terms, snippet_hint):
        snippet, highlights = self._snippet(doc, terms, snippet_hint)
        return dict(clause_id=doc.clause_id, family=doc.family, family_label=FAMILY_LABELS[doc.family],
                    code=doc.code, title=doc.title, field=doc.field, reason=format_reason(reasons),
                    reasons=list(reasons), snippet=snippet, highlights=highlights)

    def _code_rows(self, code, allowed):
        exact = [doc for doc in self.docs if doc.number in allowed and doc.code.upper() == code]
        pattern = mention_pattern(code)
        mentions = []
        for doc in self.docs:
            if doc.number not in allowed or doc in exact:
                continue
            count = len(pattern.findall(doc.text))
            if count:
                mentions.append((-count, doc.order_key, doc))
        rows = [(doc, [REASON_CODE], [], None) for doc in sorted(exact, key=lambda d: d.order_key)]
        rows += [(doc, [REASON_MENTION], [pattern], None) for _, _, doc in sorted(mentions, key=lambda x: x[:2])]
        return rows

    def query_units(self, query):
        """검색어 → 검색 단위 [(글, 맞으면 맞은 것으로 치는 낱말 번호 집합)]. 여러 낱말이면 전체 구절도 단위로 둔다."""
        words = [word for word in query.split() if term_problem(word) is None]
        units = [(word, {index}) for index, word in enumerate(words)]
        if len(words) > 1:
            units.append((" ".join(words), set(range(len(words)))))
        return words, units

    def _keyword_rows(self, query, allowed):
        words, units = self.query_units(query)
        found = {}   # 글 번호 → {"words": set, "grade": 최고 등급, "hits": [(등급, 낱말, 건수, 제목 건수)]}
        for unit, indexes in units:
            expansion = self.expand(unit)
            if " " not in unit:
                expansion += [(word, GRADE_FUZZY) for word in self.fuzzy_words(unit, exclude=[t for t, _ in expansion])]
            for term, grade in expansion:
                for number, (count, title_count) in self.term_hits(term, allowed).items():
                    entry = found.setdefault(number, {"words": set(), "hits": []})
                    entry["words"] |= indexes
                    entry["hits"].append((grade, term, count, title_count))
        rows = []
        for number, entry in found.items():
            doc = self.docs[number]
            best = min(hit[0] for hit in entry["hits"])
            best_hits = [hit for hit in entry["hits"] if hit[0] == best]
            title_hit = any(hit[3] for hit in best_hits)
            occurrences = sum(hit[2] for hit in best_hits)
            key = (-len(entry["words"]), best, 0 if title_hit else 1, -occurrences, doc.order_key)
            reasons = []
            for grade, term, count, _ in sorted(entry["hits"], key=lambda h: (h[0], -h[3], -h[2], normalize_term(h[1]))):
                reason = GRADE_REASONS[grade] if grade == GRADE_QUERY else f"{GRADE_REASONS[grade]}: {term}"
                if reason not in reasons:
                    reasons.append(reason)
            ordered_terms = [term for _, term, _, _ in sorted(entry["hits"], key=lambda h: (h[0], -h[2]))]
            rows.append((key, doc, reasons, ordered_terms))
        rows.sort(key=lambda row: row[0])
        return [(doc, reasons, [term_pattern(t) for t in terms], None) for _, doc, reasons, terms in rows]

    def _semantic_rows(self, query, allowed):
        np = self._model.np
        vector = self._model.encode([query])[0]
        if not np.any(vector):
            return []
        sims = self._chunk_vectors @ vector
        best_chunk = np.maximum.reduceat(sims, self._chunk_starts)
        rows = []
        for number in allowed:
            score = float(best_chunk[number])
            if score >= MIN_SIMILARITY:
                rows.append((-score, self.docs[number].order_key, number))
        rows.sort()
        result = []
        for _, _, number in rows:
            start = int(self._chunk_starts[number])
            end = int(self._chunk_starts[number + 1]) if number + 1 < len(self._chunk_starts) else len(sims)
            chunk = start + int(np.argmax(sims[start:end]))
            result.append((self.docs[number], [REASON_SEMANTIC], [], chunk))
        return result

    @staticmethod
    def _clause_similarities(model, vectors, starts, vector):
        """글 벡터 하나 → 조항마다(조항 순서 = docs 순서) 가장 비슷한 조각의 코사인 유사도('뜻 비슷'과 같은 계산)."""
        return model.np.maximum.reduceat(vectors @ vector, starts)

    def semantic_scores(self, query):
        """시험·자체 확인용: 검색어 → {clause_id: 유사도}(의미 유사를 쓸 수 없으면 빈 dict). 결과에는 싣지 않는다."""
        if not self.ensure_semantic()["available"]:
            return {}
        vector = self._model.encode([query])[0]
        best = self._clause_similarities(self._model, self._chunk_vectors, self._chunk_starts, vector)
        return {doc.clause_id: float(best[doc.number]) for doc in self.docs}

    def semantic_ranking(self, text):
        """과제 글(연구개발과제명·최종목표·연구개발내용을 이은 글) 하나 → 고시별 실제 검토 항목의 뜻 유사도 순위.

        돌려주는 값(JSON으로 넘길 수 있는 dict, 숫자 점수 없음):
          - 쓸 수 있음: {"available": True, "reason": "", "ranking": {고시: [clause_id, …]}}
            고시 키는 FAMILY_ORDER 네 개 전부, 목록은 그 고시의 실제 검토 항목(공통 정의·주석 제외) 전부를
            유사도 높은 순으로(같은 값이면 엔진 order_key = 고시·통제번호 순) 담는다. 관련어 사전은 쓰지 않는다.
          - 쓸 수 없음: {"available": False, "reason": 사유, "ranking": None}. 예외를 내지 않는다.
            사유: 빈 글·공백만인 글(None 포함)은 RANKING_EMPTY_TEXT(모델을 불러오지 않는다), 모델이 아는 낱말이 하나도
            없으면 RANKING_NO_WORDS, 모델·조항 벡터를 불러오지 못했으면 불러올 때의 사유, 계산 중 오류는
            'RANKING_ERROR: 오류 종류'(오류 문구는 싣지 않는다).
        글이 아닌 값(None 제외)은 SearchQueryError. 03 고시 검색의 검색어 길이 상한(MAX_QUERY_CHARS)은 쓰지 않는다.
        글은 공백을 하나로 정리해 벡터로만 바꾸며, 어디에도 저장·기록하지 않는다(PC 밖으로 보내지 않는다).
        계산 중 오류가 나도 03 탭의 의미 유사 상태는 바꾸지 않는다(한 과제의 오류가 다른 과제 결과를 바꾸지 않게).
        모델 준비는 ensure_semantic의 잠금으로 한 번만 하고, 계산은 읽기만 하므로 여러 스레드에서 동시에 불러도 된다.
        """
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise SearchQueryError("검색 글이 글이 아니다")
        text = " ".join(text.split())
        if not text:
            return self._ranking_unavailable(RANKING_EMPTY_TEXT)
        self.ensure_semantic()
        parts = self._semantic_parts
        if parts is None:
            return self._ranking_unavailable(self._semantic_reason or "의미 유사 검색을 준비하지 못했다")
        model, vectors, starts, _ = parts
        try:
            np = model.np
            vector = model.encode([text])[0]
            if not np.any(vector):
                return self._ranking_unavailable(RANKING_NO_WORDS)
            best = self._clause_similarities(model, vectors, starts, vector)
            if best.shape != (len(self.docs),) or not np.all(np.isfinite(best)):
                raise ValueError("유사도 배열 모양·값이 맞지 않는다")
            scores = best.tolist()
            ranking = {family: [] for family in FAMILY_ORDER}
            for doc in sorted(self.docs, key=lambda d: (-scores[d.number], d.order_key)):
                ranking[doc.family].append(doc.clause_id)
        except Exception as error:   # noqa: BLE001 — 계산 중 실패는 그 글만 '쓸 수 없음'으로 알린다(spec 5.2)
            return self._ranking_unavailable(f"{RANKING_ERROR}: {type(error).__name__}")
        return dict(available=True, reason="", ranking=ranking)

    @staticmethod
    def _ranking_unavailable(reason):
        return dict(available=False, reason=reason, ranking=None)

    # ── 원문 일부·강조 ─────────────────────────────────────────────────

    @staticmethod
    def _spans(text, patterns):
        spans = []
        for pattern in patterns:
            spans += [(m.start(), m.end()) for m in pattern.finditer(text) if m.end() > m.start()]
        return spans

    @staticmethod
    def _body_start(text):
        """원문 일부를 보일 처음 자리: 국문 원문 머리 줄이 있으면 그 다음, 없으면 처음."""
        marker = "[국문 원문]"
        index = text.find(marker)
        return index + len(marker) if index >= 0 else 0

    def _snippet(self, doc, patterns, chunk):
        text = doc.text
        body_start = self._body_start(text)
        if chunk is not None:   # 뜻 비슷: 가장 비슷한 조각의 원문 쪽(머리 줄 뺌)
            piece = self._chunk_texts[chunk].split("\n", 1)[-1]
            if "[국문 원문]" in piece:   # 첫 조각(통제번호 메타정보가 앞에 있음)이면 국문 원문 처음부터
                return excerpt(text, body_start, body_start + SNIPPET_CHARS, [])[0], []
            snippet, _ = excerpt(piece.replace("[영문 원문]", " "), 0, SNIPPET_CHARS, [])
            return snippet, []
        spans = self._spans(text, patterns)
        if spans:
            # 등급이 가장 앞선 낱말(patterns의 앞쪽)이 처음 나온 자리 둘레. 국문 원문 안이면 메타정보를 넘지 않는다.
            first = None
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    first = match.start()
                    break
            start = max(0, first - SNIPPET_BEFORE)
            if first >= body_start:
                start = max(start, body_start)
        else:
            start = body_start
        return excerpt(text, start, start + SNIPPET_CHARS, spans)

    # ── 조항 상세 ───────────────────────────────────────────────────────

    def highlight_patterns(self, query):
        """상세 강조에 쓸 정규식: 검색어·같은 말·관련어(두 단계까지)·글자 유사 낱말, 통제번호면 언급 모양."""
        query = self._check_query(query)
        if not query:
            return []
        code = parse_control_number(query)
        if code is not None:
            return [mention_pattern(code)]
        terms = []
        _, units = self.query_units(query)
        for unit, _ in units:
            expansion = self.expand(unit)
            terms += [term for term, _ in expansion]
            if " " not in unit:
                terms += self.fuzzy_words(unit, exclude=[t for t, _ in expansion])
        return [term_pattern(term) for term in dict.fromkeys(terms)]

    def detail(self, clause_id, query=""):
        """조항 상세: 원문 전체(국문·영문)와 강조 위치, 고시 기준 사양 목록. 모르는 조항 ID면 UnknownClauseError."""
        if not isinstance(clause_id, str) or clause_id not in self.by_id:
            raise UnknownClauseError("검색 대상에 없는 조항 ID")
        doc = self.by_id[clause_id]
        patterns = self.highlight_patterns(query)
        highlights = _merge_spans(self._spans(doc.text, patterns))
        record = clause_record(self.catalogue, clause_id)
        return dict(clause_id=doc.clause_id, family=doc.family, family_label=FAMILY_LABELS[doc.family], code=doc.code,
                    title=doc.title, field=doc.field, source_anchor=record["source_anchor"], text=doc.text,
                    highlights=highlights, criteria=criteria_list(self.records.get(clause_id)))


def criteria_list(record):
    """기준값 표 기록 하나 → 고시 기준 사양 목록(화면에 그대로 보일 값). 기록이 없으면 숫자 기준 없음."""
    if record is None:
        return dict(numeric_status=STATUS_NONE, message=NO_NUMERIC_MESSAGE, has_numeric=False, branches=[],
                    checks=[], rejected=[])
    branches = []
    for branch in record["branches"]:
        thresholds = [dict(threshold_id=t["threshold_id"], subject=t["subject"], operator=t["operator"],
                           operator_label=OPERATOR_LABELS[t["operator"]], value=t["value"], unit=t["unit"],
                           quote=t["quote"], quote_source=t["quote_source"],
                           quote_from_body=t["quote_source"] == BODY_SOURCE, origin=t["origin"],
                           origin_label=ORIGIN_LABELS[t["origin"]],
                           flag=FLAG_EXTRACTED if t["origin"] == "extracted" else "")
                      for t in branch["thresholds"]]
        branches.append(dict(branch_id=branch["branch_id"], label=branch["label"], numeric=bool(thresholds),
                             thresholds=thresholds, text=branch["text"]))
    has_numeric = any(branch["numeric"] for branch in branches)
    return dict(
        numeric_status=record["numeric_status"], has_numeric=has_numeric,
        message="" if has_numeric else NO_NUMERIC_MESSAGE, branches=branches,
        checks=[dict(quote=c["quote"], source=c["source"], from_body=c["source"] == BODY_SOURCE) for c in record["checks"]],
        rejected=[dict(branch_id=r["branch_id"], subject=r["subject"], quote=r["quote"], reason=r["reason"],
                       flag=FLAG_REJECTED) for r in record["rejected"]],
    )
