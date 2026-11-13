"""기준값 표(resources/thresholds.json) 실행용 로더. 지문이 맞지 않으면 예외로 끝낸다(fail-closed).

표는 개발 때 `tools/build_threshold_table.py`가 한 번 만들어 고정한 것이다. 손으로 고치지 않는다.
파일 형식:
    {"catalogue_id": ..., "catalogue_fingerprint": ..., "near_percent": 10,
     "records": [항목 기록 ...], "fingerprint": <fingerprint를 뺀 나머지의 canonical SHA256>}
항목 기록(spec 4.1):
    clause_id, family, numeric_status, title,
    branches[{branch_id, label, thresholds[{threshold_id, subject, operator, value, unit, quote, quote_source, origin}], text}],
    rejected[{branch_id, subject, quote, reason}], checks[{quote, source}]

불러올 때 확인하는 것: 필드 구성, 값의 종류, operator·origin·numeric_status 값, value가 유한한 10진수,
unit이 표준 표기, numeric_status가 내용과 맞음, clause_id·branch_id·threshold_id가 전역으로 유일함, 지문.
`catalogue`를 주면 기준본 지문도 대조한다.
"""
import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

import paths
from notice_catalogue import FAMILIES, canonical_hash
from units import normalize_unit

STATUS_HAS = "기준값 있음"
STATUS_NONE = "숫자 기준 없음"
STATUS_FAILED = "기준값 채택 실패"
STATUSES = (STATUS_HAS, STATUS_NONE, STATUS_FAILED)
OPERATORS = ("ge", "gt", "le", "lt")
ORIGINS = ("structured", "extracted")
# quote_source·source가 항목 자신의 본문임을 뜻하는 값. 그 밖의 값은 연결된 조항 ID이다.
BODY_SOURCE = "항목 본문"
TABLE_KEYS = frozenset(("catalogue_id", "catalogue_fingerprint", "near_percent", "records", "fingerprint"))
RECORD_KEYS = frozenset(("clause_id", "family", "numeric_status", "title", "branches", "rejected", "checks"))
BRANCH_KEYS = frozenset(("branch_id", "label", "thresholds", "text"))
THRESHOLD_KEYS = frozenset(("threshold_id", "subject", "operator", "value", "unit", "quote", "quote_source", "origin"))
REJECTED_KEYS = frozenset(("branch_id", "subject", "quote", "reason"))
CHECK_KEYS = frozenset(("quote", "source"))


class ThresholdTableError(ValueError):
    """기준값 표가 없거나 형식이 틀리거나 지문이 맞지 않는다."""


def _require(condition, message):
    if not condition:
        raise ThresholdTableError(message)


def _pairs(pairs):
    output = {}
    for key, value in pairs:
        _require(key not in output, f"JSON 키 중복: {key}")
        output[key] = value
    return output


def _reject_constant(value):
    raise ThresholdTableError("JSON에 유한하지 않은 수가 있다")


def _text(value, label, allow_empty=False):
    _require(isinstance(value, str) and (allow_empty or bool(value.strip())), f"{label} 값이 글이 아니거나 비어 있다")


def _keys(value, keys, label):
    _require(isinstance(value, dict) and set(value) == keys, f"{label} 필드 구성이 다르다: {sorted(value) if isinstance(value, dict) else type(value).__name__}")


def table_fingerprint(payload):
    """fingerprint를 뺀 나머지(catalogue_id·catalogue_fingerprint·near_percent·records)의 canonical SHA256."""
    return canonical_hash({key: value for key, value in payload.items() if key != "fingerprint"})


def expected_status(record):
    """기록 내용으로 계산한 numeric_status(spec 4.1)."""
    if any(branch["thresholds"] for branch in record["branches"]):
        return STATUS_HAS
    if record["rejected"]:
        return STATUS_FAILED
    return STATUS_NONE


def validate_record(record, label=None):
    """항목 기록 하나의 형식을 검사한다. 어긋나면 ThresholdTableError."""
    label = label or (record.get("clause_id") if isinstance(record, dict) else "기록")
    _keys(record, RECORD_KEYS, f"{label} 기록")
    _text(record["clause_id"], "clause_id")
    _require(record["family"] in FAMILIES, f"{label}: family 값이 아니다: {record['family']!r}")
    _require(record["numeric_status"] in STATUSES, f"{label}: numeric_status 값이 아니다: {record['numeric_status']!r}")
    _text(record["title"], f"{label} title", allow_empty=True)
    _require(isinstance(record["branches"], list), f"{label}: branches가 목록이 아니다")
    for branch in record["branches"]:
        _keys(branch, BRANCH_KEYS, f"{label} 갈래")
        _text(branch["branch_id"], f"{label} branch_id")
        _text(branch["label"], f"{label} label", allow_empty=True)
        _text(branch["text"], f"{label} text", allow_empty=True)
        _require(isinstance(branch["thresholds"], list), f"{label}: thresholds가 목록이 아니다")
        _require(branch["thresholds"] or branch["text"], f"{label} {branch['branch_id']}: 기준값도 원문도 없는 갈래")
        _require(not (branch["thresholds"] and branch["text"]), f"{label} {branch['branch_id']}: 숫자 갈래에 text가 있다")
        for threshold in branch["thresholds"]:
            _keys(threshold, THRESHOLD_KEYS, f"{label} 기준값")
            for key in ("threshold_id", "subject", "quote", "quote_source"):
                _text(threshold[key], f"{label} {key}")
            _text(threshold["unit"], f"{label} unit", allow_empty=True)
            _require(threshold["operator"] in OPERATORS, f"{label}: operator 값이 아니다: {threshold['operator']!r}")
            _require(threshold["origin"] in ORIGINS, f"{label}: origin 값이 아니다: {threshold['origin']!r}")
            _require(isinstance(threshold["value"], str), f"{label}: value는 10진수 문자열이어야 한다")
            try:
                _require(Decimal(threshold["value"]).is_finite(), f"{label}: value가 유한한 수가 아니다")
            except InvalidOperation as error:
                raise ThresholdTableError(f"{label}: value가 10진수가 아니다: {threshold['value']!r}") from error
            _require(normalize_unit(threshold["unit"]) == threshold["unit"],
                     f"{label}: unit이 표준 표기가 아니다: {threshold['unit']!r}")
    _require(isinstance(record["rejected"], list), f"{label}: rejected가 목록이 아니다")
    for rejected in record["rejected"]:
        _keys(rejected, REJECTED_KEYS, f"{label} 채택 실패")
        _text(rejected["branch_id"], f"{label} rejected branch_id", allow_empty=True)
        _text(rejected["subject"], f"{label} rejected subject", allow_empty=True)
        _text(rejected["quote"], f"{label} rejected quote", allow_empty=True)
        _text(rejected["reason"], f"{label} rejected reason")
    _require(isinstance(record["checks"], list), f"{label}: checks가 목록이 아니다")
    for check in record["checks"]:
        _keys(check, CHECK_KEYS, f"{label} 확인 조건")
        _text(check["quote"], f"{label} check quote")
        _text(check["source"], f"{label} check source")
    _require(record["numeric_status"] == expected_status(record),
             f"{label}: numeric_status가 내용과 다르다({record['numeric_status']} ≠ {expected_status(record)})")


@dataclass(frozen=True)
class ThresholdTable:
    """검증을 통과한 기준값 표. 조회 함수는 복사본을 돌려준다."""
    catalogue_id: str
    catalogue_fingerprint: str
    near_percent: int
    fingerprint: str
    records: tuple

    def record(self, clause_id):
        """항목 기록 하나(복사본). 없으면 KeyError."""
        for record in self.records:
            if record["clause_id"] == clause_id:
                return copy.deepcopy(record)
        raise KeyError(clause_id)

    def records_for_family(self, family):
        return [copy.deepcopy(r) for r in self.records if r["family"] == family]

    def all_records(self):
        return [copy.deepcopy(r) for r in self.records]


def load_threshold_table(path=None, catalogue=None):
    """표를 읽고 형식·유일성·지문을 확인한 뒤 ThresholdTable을 돌려준다. 어긋나면 ThresholdTableError.

    path를 주지 않으면 `paths.threshold_table_path()`를 읽는다. catalogue를 주면 catalogue_fingerprint를 대조한다.
    """
    if path is None:
        path = paths.threshold_table_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ThresholdTableError(f"기준값 표를 읽을 수 없다: {path}: {error}") from error
    _keys(payload, TABLE_KEYS, "기준값 표")
    _text(payload["catalogue_id"], "catalogue_id")
    _require(isinstance(payload["catalogue_fingerprint"], str) and re.fullmatch(r"[0-9a-f]{64}", payload["catalogue_fingerprint"]),
             "catalogue_fingerprint가 SHA256이 아니다")
    _require(type(payload["near_percent"]) is int and payload["near_percent"] >= 0, "near_percent가 0 이상 정수가 아니다")
    _require(isinstance(payload["fingerprint"], str) and payload["fingerprint"] == table_fingerprint(payload),
             "기준값 표 지문이 맞지 않는다. 표를 다시 만들어야 한다")
    _require(isinstance(payload["records"], list) and payload["records"], "records가 비어 있다")
    clause_ids = set()
    branch_ids = set()
    threshold_ids = set()
    for record in payload["records"]:
        validate_record(record)
        _require(record["clause_id"] not in clause_ids, f"clause_id 중복: {record['clause_id']}")
        clause_ids.add(record["clause_id"])
        for branch in record["branches"]:
            _require(branch["branch_id"] not in branch_ids, f"branch_id 중복: {branch['branch_id']}")
            branch_ids.add(branch["branch_id"])
            for threshold in branch["thresholds"]:
                _require(threshold["threshold_id"] not in threshold_ids, f"threshold_id 중복: {threshold['threshold_id']}")
                threshold_ids.add(threshold["threshold_id"])
    if catalogue is not None:
        _require(getattr(catalogue, "fingerprint", None) == payload["catalogue_fingerprint"],
                 "기준값 표가 다른 기준본으로 만들어졌다(기준본 지문 불일치)")
    return ThresholdTable(catalogue_id=payload["catalogue_id"], catalogue_fingerprint=payload["catalogue_fingerprint"],
                          near_percent=payload["near_percent"], fingerprint=payload["fingerprint"],
                          records=tuple(copy.deepcopy(r) for r in payload["records"]))
