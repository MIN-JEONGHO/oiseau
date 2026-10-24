"""v15 immutable guideline rules and source-bound result contracts.

The source is the user-supplied final guideline. Numerical bands are reference
opinions; the legal definition and the need to protect against disclosure govern
the final opinion. Unavailable evidence never becomes a score or ordinary grade.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from urllib.parse import urlsplit
from pathlib import PurePosixPath
from functools import wraps
import math
import re
import unicodedata


GUIDELINE_ID = "research-security-final-a67e47f5ac8ee07d"
SCHEMA_VERSION = 2
COMPARISON_RULES_VERSION = "1"
FAMILIES = ("advanced", "core", "dual_use", "military")
ASSESSMENTS = ("satisfied", "not_satisfied", "insufficient_info")
PERSONAS = ("AI 기술분야 전문가", "AI 연구보안 전문가", "AI 기술사업화 전문가")
_RESULT_KEYS = {
    "schema_version", "guideline_id", "catalogue_fingerprint", "task_snapshot", "task_fingerprint", "options_fingerprint",
    "task_name", "method", "provider", "model", "status", "candidate", "criteria", "selected_items",
    "weights", "reviewers", "overall_avg", "rule_grade", "final_grade", "confidence", "rationale",
    "discussion_points", "unresolved_reasons", "documents", "notice_review",
}
_REVIEWER_KEYS = {"reviewer_id", "persona", "status", "item_reviews", "scores", "reviewer_score", "grade",
                  "confidence", "rationale", "discussion_points", "unresolved_reasons", "notice_comments"}
GRADES = ("보안과제", "민감과제", "일반과제")
LEVELS = ("해당", "일부", "미해당", "판단곤란", "미검토")
CONFIDENCES = ("높음", "보통", "낮음")
STATUSES = ("완료", "검토필요", "후보제외", "오류")
TASK_COLUMNS = ("세부사업명", "과제명", "연구목표", "연구내용", "기대효과")
OPTIONAL_TASK_COLUMNS = ("추가 검토정보", "부처 세부기준", "현재 기술사양", "개발목표 사양")
DEFAULT_MODELS = MappingProxyType({
    "claude": "claude-sonnet-5-5", "openai": "gpt-6-luna",
    "ollama": "", "lmstudio": "",
})
LEGAL_DEFINITIONS = MappingProxyType({
    "보안과제": "외부로 유출될 경우 기술적·재산적 가치에 상당한 손실이 예상되거나, 국가안보를 위하여 별도로 높은 수준의 보안관리가 필요한 연구개발과제(법 제21조제4항).",
    "민감과제": "보안과제로 분류하지 아니하였으나 유출 시 국가에 미치는 영향을 고려하여 추가적인 관리가 필요하다고 인정하는 연구개발과제(법 제21조제5항).",
    "일반과제": "충분한 검토 결과 보안과제·민감과제로 분류할 보호 필요성이 확인되지 않은 연구개발과제. 정보 부족이나 판단곤란의 대체값으로 사용하지 않는다.",
})
CLASSIFICATION_PRINCIPLES = (
    "기술의 우수성 자체가 아니라 유출 시 국가영향과 보호 필요성을 판단한다.",
    "기술명, 항목 수, 국제공동연구 여부만으로 등급을 자동 확정하지 않는다.",
    "체크리스트와 국가영향 지표는 양자택일하며 수치 구간은 우선 검토 참고 기준이다.",
    "가이드라인 본문 법령·정의·산식을 사례의 상충하는 숫자·조항보다 우선한다.",
)

# Rubric tuple order is scores 1 through 5, matching the final guide table 5.
_DEFINITIONS = (
    ("군사·안보 활용성", ("제45조제1항제1호",), "제45조제2항제1호", (
        "군사·안보에 미치는 영향 거의 없음",
        "군사적 영향이 기술 특성상 일부에 그치는 수준",
        "이중용도 기술이나 기술적 한계·범위로 인해 군사적 전용 가능성이 제한적",
        "무기체계 또는 국가 중요시설·방위산업에 활용되어 국가안보에 손실",
        "무기체계·군사작전에 즉시 활용되어 국가안보에 직접 위협")),
    ("외교·경제안보 관련성", ("제45조제1항제2호가목", "제45조제1항제3호"), "제45조제2항제1호", (
        "외교·경제안보 전략, 국제협력, 공급망 안정성 또는 핵심 산업 경쟁력에 미치는 영향이 거의 없음",
        "외교·경제안보 전략, 국제협력, 공급망 안정성 또는 핵심 산업 경쟁력에 미치는 영향이 경미",
        "외교·경제안보 전략, 국제협력, 공급망 안정성 또는 핵심 산업 경쟁력에 일부 영향, 직접적인 손실은 제한적",
        "외교·경제안보 전략, 국제협력, 공급망 안정성 또는 핵심 산업 경쟁력에 직접적인 파급효과",
        "외교·경제안보 전략, 국제협력, 공급망 안정성 또는 핵심 산업 경쟁력에 상당한 영향")),
    ("국가핵심기술", ("제45조제1항제2호다목", "제45조제1항제3호"), "제45조제2항제1호", (
        "국가핵심기술과의 관련성이 낮거나 유출 시 국가경쟁력에 부정적 영향이 거의 없는 경우",
        "국가핵심기술과 유사 기술 분야이나 기술적 격차가 상당하여 유출 시 국가경쟁력 저해 우려가 경미",
        "국가핵심기술과 격차가 있으나, 해당 기술과 결합되어 활용될 수 있어 일정 수준 관리 필요",
        "국가핵심기술의 수준에 근접하며 유출 시 국가경쟁력에 직접적 손실 가능",
        "국가핵심기술로 판정되며, 유출 시에 국가경쟁력에 상당한 피해 초래 가능")),
    ("전략물자", ("제45조제1항제2호라목", "제45조제1항제3호"), "제45조제2항제1호", (
        "일반 상용 품목·기술로, 해외 이전에 따른 수출통제 측면의 영향이 미미한 수준",
        "전략물자 연관분야에 속하나, 범용 기술이거나 해외 이전으로 인한 안보적 위험성이 제한적인 수준",
        "국제 통제 동향이나 기술 트렌드상 향후 전략물자로 지정될 가능성이 있어 지속적인 모니터링이 필요한 수준",
        "전략물자에 근접한 수준이거나 이중용도 품목 등으로 민감 지역·기관 이전 시 안보·외교적 파급효과 발생 가능",
        "전략물자 기술로 판정되며 무단 해외 이전 시 국가 안보 및 외교 관계에 심각한 위협을 초래하는 수준")),
    ("기술 수준 및 희소성", ("제45조제1항제2호나목", "제45조제1항제3호"), "제45조제2항제2호", (
        "보편화된 기술 수준으로, 유출되더라도 국가간 기술격차에 미치는 영향이 거의 없는 수준",
        "유사·대체 기술이 많아 영향이 경미",
        "추격·발전 단계의 기술로 유사·대체 기술이 있어 유출 영향이 제한적인 수준",
        "세계 선도그룹 수준 기술로 유출 시에 국제 경쟁력에 직접 손실",
        "세계 최고 수준·전략적 희소성이 있는 기술로 유출 시 국가 우위에 막대한 피해")),
    ("산업·경제적 파급력", ("제45조제1항제2호나목", "제45조제1항제3호"), "제45조제2항제2호", (
        "공개·확산되더라도 국가 경제 및 산업 전반에 미치는 손실이 거의 없는 수준",
        "파급효과가 개별 기업의 경영상 타격 수준에 그치며, 국가 및 산업 전반에 미치는 손실은 경미한 수준",
        "파급효과가 일부 선도기업에 영향을 주며 국가 경제 전반으로의 직접적인 손실은 제한적인 수준",
        "국가 주력산업 및 미래 신산업의 핵심 성장 기반·원천기술 확보 등 경쟁력에 직접적 손실",
        "국가 주력·전략 산업의 근간이 흔들리거나, 시장 구조 전반에 심각한 타격 및 지각변동을 초래")),
    ("연구수행 과정·결과 관리 필요성", ("제45조제1항제3호",), "제45조제2항제3호", (
        "학술·인력교류, 공동세미나 등 일반적인 국제협력이거나 연구성과·산출물의 공개·공유가 통상 허용되어 국가안보·외교·산업 영향이 미미",
        "외국 기관과의 공동연구 또는 연구성과·산출물에 일정한 관리 필요성이 있으나, 공유·이전 범위가 제한적이며 일반적인 관리체계로 충분히 관리 가능",
        "외국 연구기관과의 공동연구 또는 연구성과·산출물의 공유·이전 과정에서 기술·정보의 유출·악용위험이 존재하여 추가적인 예방 관리 필요",
        "국제공동연구 또는 연구성과·산출물에 국가안보·외교·산업 등에 영향을 미칠 수 있는 기술·정보가 포함되어 있어 중앙행정기관 차원 별도 관리 필요",
        "국가 간 협정 등에 따라 높은 수준의 보안관리가 의무화되어 있거나, 연구성과·산출물의 이전·유출·악용 시 국가안보에 중대 피해")),
    ("부처 정책상 관리 필요성", ("제45조제1항제3호",), "제45조제2항제3호", ()),
)
CRITERIA = tuple(MappingProxyType({
    "id": index, "name": name, "security_refs": security,
    "sensitive_refs": (sensitive,), "rubric": MappingProxyType(dict(enumerate(rubric, 1))),
}) for index, (name, security, sensitive, rubric) in enumerate(_DEFINITIONS, 1))
ITEM_NAMES = tuple(criterion["name"] for criterion in CRITERIA)


def resolve_item(value) -> str:
    """Resolve only an exact canonical name or numeric identifier (1..8)."""
    if isinstance(value, bool):
        raise ValueError("검토항목 식별자가 올바르지 않습니다.")
    if isinstance(value, int) and 1 <= value <= len(ITEM_NAMES):
        return ITEM_NAMES[value - 1]
    if isinstance(value, str):
        text = value.strip()
        if text in ITEM_NAMES:
            return text
        if text in tuple(str(i) for i in range(1, 9)):
            return ITEM_NAMES[int(text) - 1]
    raise ValueError("알 수 없는 검토항목입니다.")


def canonical_items(items) -> tuple[str, ...]:
    if isinstance(items, (str, bytes)) or items is None:
        raise ValueError("검토항목은 목록이어야 합니다.")
    names = [resolve_item(item) for item in items]
    if len(set(names)) != len(names):
        raise ValueError("검토항목이 중복되었습니다.")
    return tuple(name for name in ITEM_NAMES if name in names)


def _decimal(value, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label}은 유한한 숫자여야 합니다.")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}은 유한한 숫자여야 합니다.") from None
    if not number.is_finite():
        raise ValueError(f"{label}은 유한한 숫자여야 합니다.")
    return number


def parse_score(value) -> int:
    number = _decimal(value, "점수")
    if number != number.to_integral_value() or not 1 <= number <= 5:
        raise ValueError("점수는 1~5의 정수여야 합니다.")
    return int(number)


def validate_weights(selected_items, weights=None, tolerance=1e-6) -> dict[str, float]:
    names = canonical_items(selected_items)
    if not names:
        raise ValueError("선택된 검토항목이 없습니다.")
    tol = _decimal(tolerance, "허용오차")
    if not 0 <= tol <= Decimal("0.000001"):
        raise ValueError("허용오차는 0~0.000001이어야 합니다.")
    supplied = {} if weights is None else dict(weights)
    normalized = {}
    for key, value in supplied.items():
        name = resolve_item(key)
        if name in normalized:
            raise ValueError("가중치 항목이 중복되었습니다.")
        normalized[name] = _decimal(value, "가중치")
    numbers = {name: normalized.get(name, Decimal(1)) for name in names}
    if any(not Decimal("0.8") <= number <= Decimal("1.2") for number in numbers.values()):
        raise ValueError("선택 항목별 가중치는 0.8~1.2여야 합니다.")
    if abs(sum(numbers.values()) / Decimal(len(names)) - 1) > tol:
        raise ValueError("선택 항목의 가중치 평균은 1.0이어야 합니다.")
    return {name: float(number) for name, number in numbers.items()}


def calculate_reviewer_score(scores: Mapping, selected_items, weights=None, *, tolerance=1e-6) -> float:
    names = canonical_items(selected_items)
    checked_weights = validate_weights(names, weights, tolerance)
    normalized = {}
    for key, value in scores.items():
        name = resolve_item(key)
        if name in normalized:
            raise ValueError("점수 항목이 중복되었습니다.")
        normalized[name] = parse_score(value)
    if set(normalized) != set(names):
        raise ValueError("선택 항목별 점수가 모두 있어야 하며 추가 점수를 넣을 수 없습니다.")
    total = sum(Decimal(str(checked_weights[name])) * normalized[name] for name in names)
    return float(total / Decimal(len(names)))


def calculate_committee_average(reviewers: Sequence[Mapping], expected_count: int) -> float | None:
    """Missing/invalid/incomplete reviewers never form a smaller denominator."""
    if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count not in (1, 3):
        raise ValueError("AI 에이전트 수는 1개 또는 3개여야 합니다.")
    if len(reviewers) != expected_count:
        return None
    ids = [reviewer.get("reviewer_id") for reviewer in reviewers]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != expected_count:
        return None
    values = []
    for reviewer in reviewers:
        if reviewer.get("status") != "완료":
            return None
        try:
            value = _decimal(reviewer.get("reviewer_score"), "에이전트 점수")
        except ValueError:
            return None
        # The permitted tiny weight-mean tolerance can produce a value just
        # outside 1..5. Preserve it instead of clipping or discarding a review.
        if not Decimal("0.999999") <= value <= Decimal("5.000005"):
            return None
        values.append(value)
    return float(sum(values) / Decimal(expected_count))


def rule_grade(score) -> str | None:
    if score is None:
        return None
    value = _decimal(score, "평균")
    if not Decimal("0.999999") <= value <= Decimal("5.000005"):
        raise ValueError("평균이 국가영향 점수의 유효 범위를 벗어났습니다.")
    return GRADES[0] if value >= Decimal("4.5") else GRADES[1] if value >= Decimal("3.5") else GRADES[2]


def format_score(score) -> str:
    if score is None:
        return "해당 없음"
    value = _decimal(score, "점수")
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Avoid a below-threshold value looking identical to the boundary.
    if any(value < boundary <= rounded for boundary in (Decimal("3.5"), Decimal("4.5"))):
        return format(value, "f")
    return format(rounded, ".2f")


@dataclass(frozen=True)
class RunOptions:
    method: str = "impact"
    provider: str = "claude"
    model: str = "claude-sonnet-5-5"
    num_reviewers: int = 3
    strictness: str = "표준"
    selection_mode: str = "auto"
    selected_items: tuple = ()
    weights: tuple = ()
    weight_tolerance: float = 1e-6
    ministry_policy: str = ""
    guideline_id: str = GUIDELINE_ID
    local_base_url: str = ""
    catalogue_fingerprint: str = ""
    comparison_rules_version: str = COMPARISON_RULES_VERSION

    def to_dict(self) -> dict:
        return {
            "method": self.method, "provider": self.provider, "model": self.model,
            "num_reviewers": self.num_reviewers, "strictness": self.strictness,
            "selection_mode": self.selection_mode, "selected_items": list(self.selected_items),
            "weights": dict(self.weights), "weight_tolerance": self.weight_tolerance,
            "ministry_policy": self.ministry_policy, "guideline_id": self.guideline_id,
            "local_base_url": self.local_base_url,
            "catalogue_fingerprint": self.catalogue_fingerprint,
            "comparison_rules_version": self.comparison_rules_version,
        }


def normalize_options(options=None, *, ministry_policy_context="", allow_row_policy=False) -> RunOptions:
    """Freeze public options, validating item 8 against the effective policy.

    A single-task caller supplies the row policy as ``ministry_policy_context``.
    A batch caller can defer this one check with ``allow_row_policy=True`` before
    reading rows, but each task must then pass through ``make_result`` or this
    function with its actual context. Context never changes the frozen options:
    run settings and row contents retain separate stable fingerprints.
    """
    # Read frozen fields without to_dict() coercions: stale auto-mode values in
    # a directly constructed RunOptions must be discarded just like dict input.
    raw = {field.name: getattr(options, field.name) for field in fields(options)} if isinstance(options, RunOptions) else dict(options or {})
    provider = raw.get("provider", "claude")
    if provider not in DEFAULT_MODELS:
        raise ValueError("지원하지 않는 모델 제공자입니다.")
    method = raw.get("method", "impact")
    if method not in ("checklist", "impact"):
        raise ValueError("분류 방식은 체크리스트 또는 국가영향 지표여야 합니다.")
    model = str(raw.get("model", DEFAULT_MODELS[provider])).strip()
    if provider in ("claude", "openai") and model != DEFAULT_MODELS[provider]:
        raise ValueError("선택 제공자의 지정 모델과 일치하지 않습니다.")
    count = raw.get("num_reviewers", 3)
    if isinstance(count, bool) or not isinstance(count, int) or count not in (1, 3):
        raise ValueError("AI 에이전트 수는 1개 또는 3개여야 합니다.")
    strictness = raw.get("strictness", "표준")
    if strictness != "표준":
        raise ValueError("v15의 마지막 의견은 표준만 지원합니다.")
    selection = raw.get("selection_mode", "auto")
    if selection not in ("auto", "manual"):
        raise ValueError("항목 선택 방식이 올바르지 않습니다.")
    # Discard stale manual settings BEFORE even attempting to parse them.
    names = () if selection == "auto" else canonical_items(raw.get("selected_items", ()))
    if selection == "manual" and not names:
        raise ValueError("직접 선택할 검토항목이 필요합니다.")
    policy = str(raw.get("ministry_policy", "") or "").strip()
    context_policy = str(ministry_policy_context or "").strip()
    if ITEM_NAMES[7] in names and not (policy or context_policy or allow_row_policy):
        raise ValueError("8번 항목을 선택하려면 부처 세부기준을 입력해야 합니다.")
    tol = _decimal(raw.get("weight_tolerance", 1e-6), "허용오차") if method == "impact" and selection == "manual" else Decimal("0.000001")
    if not 0 <= tol <= Decimal("0.000001"):
        raise ValueError("허용오차는 0~0.000001이어야 합니다.")
    weight_map = {}
    if method == "impact" and selection == "manual":
        for key, value in dict(raw.get("weights", {}) or {}).items():
            name = resolve_item(key)
            if name in weight_map:
                raise ValueError("가중치 항목이 중복되었습니다.")
            number = _decimal(value, "가중치")
            if not Decimal("0.8") <= number <= Decimal("1.2"):
                raise ValueError("가중치는 0.8~1.2여야 합니다.")
            weight_map[name] = float(number)
        weight_map = validate_weights(names, weight_map, tol)
    guideline = str(raw.get("guideline_id", GUIDELINE_ID))
    if guideline != GUIDELINE_ID:
        raise ValueError("가이드라인 식별값이 일치하지 않습니다.")
    base_url = str(raw.get("local_base_url", "") or "").strip()
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("로컬 서버 주소는 인증정보·쿼리 없는 HTTP(S) 주소여야 합니다.")
    catalogue = raw.get("catalogue_fingerprint", "")
    if not isinstance(catalogue, str) or catalogue and re.fullmatch(r"[0-9a-f]{64}", catalogue) is None:
        raise ValueError("고시 기준 지문이 올바르지 않습니다.")
    comparison_rules = raw.get("comparison_rules_version", COMPARISON_RULES_VERSION)
    if comparison_rules != COMPARISON_RULES_VERSION:
        raise ValueError("고시 대조 규칙 버전이 일치하지 않습니다.")
    return RunOptions(method, provider, model, count, strictness, selection,
                      names, tuple((name, weight_map[name]) for name in ITEM_NAMES if name in weight_map),
                      float(tol), policy, guideline, base_url, catalogue, comparison_rules)


def task_snapshot(task: Mapping) -> dict[str, str]:
    result = {column: "" if task.get(column) is None else str(task.get(column, "")).strip()
              for column in TASK_COLUMNS + OPTIONAL_TASK_COLUMNS}
    if not result["과제명"]:
        raise ValueError("과제명은 필수입니다.")
    return result


def _fingerprint(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


canonical_hash = _fingerprint


def comparison_id(catalogue_fingerprint: str, clause_id: str) -> str:
    """Stable ID bound to the full reviewed catalogue and canonical clause ID."""
    return canonical_hash({"catalogue_fingerprint": catalogue_fingerprint, "clause_id": clause_id})


def effective_weights(options, selected_items) -> dict[str, float]:
    opts = normalize_options(options, allow_row_policy=True)
    if opts.method == "checklist":
        return {}
    names = canonical_items(selected_items)
    if not names:
        raise ValueError("선택된 검토항목이 없습니다.")
    if opts.selection_mode == "auto":
        return {name: 1.0 for name in names}
    if names != opts.selected_items:
        raise ValueError("실제 검토항목과 직접 선택 항목이 일치하지 않습니다.")
    return validate_weights(names, dict(opts.weights), opts.weight_tolerance)


def task_fingerprint(task: Mapping) -> str:
    return _fingerprint(task_snapshot(task))


def options_fingerprint(options=None) -> str:
    # A run can select item 8 and rely on each row's policy. The options hash is
    # independent of that row; task validation remains mandatory at evaluation.
    return _fingerprint(normalize_options(options, allow_row_policy=True).to_dict())


def eligible_items(ministry_policy="") -> tuple[str, ...]:
    return ITEM_NAMES if str(ministry_policy or "").strip() else ITEM_NAMES[:7]


def make_reviewer(reviewer_id: str, persona: str = "") -> dict:
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise ValueError("AI 에이전트 식별자가 필요합니다.")
    return {"reviewer_id": reviewer_id, "persona": persona, "status": "미실시",
            "item_reviews": [], "scores": {}, "reviewer_score": None, "grade": None,
            "confidence": None, "rationale": "", "discussion_points": "", "unresolved_reasons": [],
            "notice_comments": []}


def _initial_criteria(policy):
    return [{"item": name, "level": "판단곤란" if name in eligible_items(policy) else "미검토",
             "note": "" if name in eligible_items(policy) else "부처 세부기준 미제공",
             "law_refs": list(CRITERIA[index]["security_refs"] + CRITERIA[index]["sensitive_refs"]),
             "matched_reference": "", "needs_expert_review": True}
            for index, name in enumerate(ITEM_NAMES)]


def make_result(task: Mapping, options=None, *, catalogue_fingerprint="", catalogue_manifest=None) -> dict:
    snapshot = task_snapshot(task)
    if catalogue_manifest is not None:
        validate_manifest(catalogue_manifest)
        manifest_fingerprint = canonical_hash(catalogue_manifest)
        if catalogue_fingerprint and catalogue_fingerprint != manifest_fingerprint:
            raise ValueError("고시 기준과 지문이 일치하지 않습니다.")
        catalogue_fingerprint = manifest_fingerprint
    opts = normalize_options(options, ministry_policy_context=snapshot["부처 세부기준"])
    if catalogue_fingerprint:
        if opts.catalogue_fingerprint and opts.catalogue_fingerprint != catalogue_fingerprint:
            raise ValueError("실행 옵션과 고시 기준이 일치하지 않습니다.")
        opts = normalize_options(opts.to_dict() | {"catalogue_fingerprint": catalogue_fingerprint},
                                 ministry_policy_context=snapshot["부처 세부기준"])
    catalogue_fingerprint = opts.catalogue_fingerprint
    # A row-specific policy is part of task_fingerprint; run-level policy is part
    # of options_fingerprint. Either permits considering item 8.
    policy = snapshot["부처 세부기준"] or opts.ministry_policy
    return {
        "schema_version": SCHEMA_VERSION, "guideline_id": GUIDELINE_ID,
        "catalogue_fingerprint": catalogue_fingerprint,
        "task_snapshot": snapshot, "task_fingerprint": task_fingerprint(snapshot),
        "options_fingerprint": options_fingerprint(opts), "task_name": snapshot["과제명"],
        "method": opts.method, "provider": opts.provider, "model": opts.model,
        "status": "검토필요", "candidate": {"is_candidate": None, "reason": "", "uncertainty": ""},
        "criteria": _initial_criteria(policy),
        "selected_items": list(opts.selected_items),
        "weights": dict(opts.weights) if opts.method == "impact" else {},
        "reviewers": [], "overall_avg": None, "rule_grade": None, "final_grade": None,
        "confidence": None, "rationale": "", "discussion_points": "", "unresolved_reasons": [],
        "documents": {"status": "미생성", "expected_files": opts.num_reviewers + 1, "files": [], "errors": []},
        "notice_review": make_notice_review(catalogue_manifest, catalogue_fingerprint),
    }


def _require(condition, message="저장 결과의 구조 또는 일치 검증에 실패했습니다."):
    if not condition:
        raise ValueError(message)


def _contract_validator(function):
    """Malformed public JSON fails with a safe ValueError, never input values."""
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (TypeError, KeyError, IndexError, RecursionError, InvalidOperation, OverflowError):
            raise ValueError("저장 결과의 구조 또는 일치 검증에 실패했습니다.") from None
    return checked


def _object(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _text(value, *, nonempty=False):
    _require(type(value) is str and (not nonempty or bool(value.strip())))


def _strings(value, *, unique=False, nonempty=False):
    _require(type(value) is list)
    for item in value:
        _text(item, nonempty=nonempty)
    if unique:
        _require(len(set(value)) == len(value))


def _digest(value, *, allow_empty=False):
    _require(type(value) is str and ((allow_empty and value == "") or re.fullmatch(r"[0-9a-f]{64}", value) is not None))


def _relative_path(value):
    _text(value, nonempty=True)
    path = PurePosixPath(value)
    _require(not path.is_absolute() and ".." not in path.parts and "\\" not in value and ":" not in value)
    _require(str(path) == value and value != ".")


def _decimal_string(value, *, nullable=False):
    if nullable and value is None:
        return None
    _text(value, nonempty=True)
    return _decimal(value, "수치")


def _finite_json(value):
    # Reject non-JSON values too, avoiding bool/int aliases and hidden objects.
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        _require(math.isfinite(value))
    elif type(value) is list:
        for item in value:
            _finite_json(item)
    elif type(value) is dict:
        _require(all(type(key) is str for key in value))
        for item in value.values():
            _finite_json(item)
    else:
        _require(False)


@_contract_validator
def validate_manifest(manifest, *, require_executable=False):
    """Validate a portable frozen manifest; file bytes are the loader's duty."""
    _object(manifest, {"catalogue_schema_version", "catalogue_id", "sources", "files", "clause_inventory"})
    _require(type(manifest["catalogue_schema_version"]) is int and manifest["catalogue_schema_version"] == 1)
    _text(manifest["catalogue_id"], nonempty=True)
    _require(type(manifest["files"]) is list and bool(manifest["files"]))
    files = {}
    for entry in manifest["files"]:
        _object(entry, {"relative_path", "sha256"})
        _relative_path(entry["relative_path"])
        _digest(entry["sha256"])
        _require(entry["relative_path"] not in files)
        files[entry["relative_path"]] = entry["sha256"]
    _require(type(manifest["sources"]) is list and bool(manifest["sources"]))
    ids, families = set(), set()
    for source in manifest["sources"]:
        _object(source, {"source_id", "families", "title", "notice_number", "announcement_version", "effective_date",
                         "retrieved_at", "official_url", "relative_path", "sha256", "review_status", "coverage", "review_note"})
        for key in ("source_id", "title", "notice_number", "announcement_version", "effective_date", "retrieved_at", "official_url", "review_note"):
            _text(source[key], nonempty=key in ("source_id", "title", "official_url"))
        parsed = urlsplit(source["official_url"])
        _require(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password)
        _require(source["source_id"] not in ids)
        ids.add(source["source_id"])
        _strings(source["families"], unique=True, nonempty=True)
        _require(bool(source["families"]) and set(source["families"]) <= set(FAMILIES))
        families.update(source["families"])
        _relative_path(source["relative_path"])
        _digest(source["sha256"])
        _require(files.get(source["relative_path"]) == source["sha256"])
        _require(source["review_status"] in ("pending", "reviewed") and source["coverage"] in ("full", "partial", "unavailable"))
        if require_executable:
            _require(source["review_status"] == "reviewed" and source["coverage"] == "full")
    _require(families == set(FAMILIES))
    _require(type(manifest["clause_inventory"]) is list)
    inventory = set()
    for entry in manifest["clause_inventory"]:
        _object(entry, {"clause_id", "family", "sha256"})
        _text(entry["clause_id"], nonempty=True)
        _require(entry["family"] in FAMILIES and entry["clause_id"] not in inventory)
        inventory.add(entry["clause_id"])
        _digest(entry["sha256"])
    if require_executable:
        _require({entry["family"] for entry in manifest["clause_inventory"]} == set(FAMILIES))
    canonical_hash(manifest)
    return manifest


def condition_leaves(condition):
    """Validate an exact condition AST and return its canonical leaf sequence."""
    leaves = []

    def visit(node, depth=0):
        _require(type(node) is dict and depth < 64)
        kind = node.get("type")
        if kind in ("all", "any"):
            _object(node, {"type", "children"})
            _require(type(node["children"]) is list and bool(node["children"]))
            for child in node["children"]:
                visit(child, depth + 1)
        elif kind == "not":
            _object(node, {"type", "child"})
            visit(node["child"], depth + 1)
        else:
            _require(kind in ("numeric", "qualitative", "unsupported"))
            keys = {"type", "predicate_id", "text", "source_anchor", "subject"}
            keys |= {"operator", "threshold", "unit"} if kind == "numeric" else {"reason"}
            _object(node, keys)
            for key in ("predicate_id", "text", "source_anchor", "subject"):
                _text(node[key], nonempty=True)
            if kind == "numeric":
                _require(node["operator"] in ("lt", "le", "eq", "ge", "gt"))
                _decimal_string(node["threshold"])
                _text(node["unit"], nonempty=True)
            else:
                _text(node["reason"], nonempty=True)
            leaves.append(node)

    visit(condition)
    _require(len({leaf["predicate_id"] for leaf in leaves}) == len(leaves))
    return tuple(leaves)


@_contract_validator
def validate_clause(clause, *, manifest=None):
    _object(clause, {"clause_id", "source_id", "family", "code", "title", "field", "source_anchor", "text", "qualifier_refs", "condition"})
    for key in ("clause_id", "source_id", "title", "field", "source_anchor", "text"):
        _text(clause[key], nonempty=True)
    _text(clause["code"])
    _require(clause["family"] in FAMILIES)
    _strings(clause["qualifier_refs"], unique=True, nonempty=True)
    _require(clause["clause_id"] not in clause["qualifier_refs"])
    condition_leaves(clause["condition"])
    if manifest is not None:
        inventory = {entry["clause_id"]: entry for entry in manifest["clause_inventory"]}
        sources = {entry["source_id"]: entry for entry in manifest["sources"]}
        _require(clause["clause_id"] in inventory and clause["source_id"] in sources)
        _require(inventory[clause["clause_id"]]["family"] == clause["family"])
        _require(clause["family"] in sources[clause["source_id"]]["families"])
        _require(inventory[clause["clause_id"]]["sha256"] == canonical_hash(clause))
        _require(set(clause["qualifier_refs"]) <= set(inventory))
    return clause


# Only declared, dimensionally consistent units are converted. A unit spelling
# outside this table never gets an inferred scale or an approximate conversion.
_UNITS = {
    "Hz": ("frequency", "1"), "kHz": ("frequency", "1000"), "MHz": ("frequency", "1000000"), "GHz": ("frequency", "1000000000"),
    "m": ("length", "1"), "cm": ("length", ".01"), "mm": ("length", ".001"), "um": ("length", ".000001"),
    "µm": ("length", ".000001"), "μm": ("length", ".000001"), "nm": ("length", ".000000001"),
    "s": ("time", "1"), "ms": ("time", ".001"), "us": ("time", ".000001"), "µs": ("time", ".000001"), "μs": ("time", ".000001"), "ns": ("time", ".000000001"),
    "W": ("power", "1"), "mW": ("power", ".001"), "kW": ("power", "1000"), "MW": ("power", "1000000"),
    "g": ("mass", ".001"), "kg": ("mass", "1"), "mg": ("mass", ".000001"),
    "bit/s": ("data_rate", "1"), "kbit/s": ("data_rate", "1000"), "Mbit/s": ("data_rate", "1000000"), "Gbit/s": ("data_rate", "1000000000"),
}


def _decimal_text(number):
    text = format(number, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) if number else "0"


def normalize_measurement(number, unit, target_unit):
    """Return an exact decimal string, or None for an undeclared conversion."""
    value = _decimal_string(number)
    _text(unit, nonempty=True)
    _text(target_unit, nonempty=True)
    if unit == target_unit:
        return _decimal_text(value)
    source, target = _UNITS.get(unit), _UNITS.get(target_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + 32)
        return _decimal_text(value * Decimal(source[1]) / Decimal(target[1]))


def evaluate_condition(condition, predicate_assessments):
    """Evaluate all/any/not with three-valued logic (no missing→false cast)."""
    kind = condition["type"]
    if kind in ("all", "any"):
        values = [evaluate_condition(child, predicate_assessments) for child in condition["children"]]
        _require(bool(values))
        if kind == "all":
            return "not_satisfied" if "not_satisfied" in values else "insufficient_info" if "insufficient_info" in values else "satisfied"
        return "satisfied" if "satisfied" in values else "insufficient_info" if "insufficient_info" in values else "not_satisfied"
    if kind == "not":
        return {"satisfied": "not_satisfied", "not_satisfied": "satisfied", "insufficient_info": "insufficient_info"}[evaluate_condition(condition["child"], predicate_assessments)]
    value = predicate_assessments.get(condition["predicate_id"], "insufficient_info")
    _require(value in ASSESSMENTS)
    return value


def assess_numeric(predicate, facts):
    """Return (assessment, normalized_value, normalized_unit) from quoted facts.

    Explicit upper/lower bounds retain interval semantics. A comparison is
    decisive only when every value in the interval implies it or its negation.
    Uncertain/range expressions outside this grammar remain unknown; they never
    become an endpoint score. Conflicting evidence remains unknown too.
    """
    _require(predicate["type"] == "numeric")
    intervals = []
    for fact in facts:
        if fact["subject"] != predicate["subject"] or fact["number"] is None or fact["unit"] is None:
            return "insufficient_info", None, None
        interval = _fact_interval(fact, predicate["unit"])
        if interval is None:
            return "insufficient_info", None, None
        intervals.append(interval)
    if not intervals:
        return "insufficient_info", None, None
    lower, lower_closed, upper, upper_closed = intervals[0]
    for low, low_closed, high, high_closed in intervals[1:]:
        if low is not None and (lower is None or low > lower):
            lower, lower_closed = low, low_closed
        elif low is not None and low == lower:
            lower_closed = lower_closed and low_closed
        if high is not None and (upper is None or high < upper):
            upper, upper_closed = high, high_closed
        elif high is not None and high == upper:
            upper_closed = upper_closed and high_closed
    if lower is not None and upper is not None and (lower > upper or lower == upper and not (lower_closed and upper_closed)):
        return "insufficient_info", None, None
    threshold = _decimal_string(predicate["threshold"])
    point = lower is not None and lower == upper and lower_closed and upper_closed
    operation = predicate["operator"]
    if operation == "lt":
        passed = upper is not None and (upper < threshold or upper == threshold and not upper_closed)
        failed = lower is not None and lower >= threshold
    elif operation == "le":
        passed = upper is not None and upper <= threshold
        failed = lower is not None and (lower > threshold or lower == threshold and not lower_closed)
    elif operation == "gt":
        passed = lower is not None and (lower > threshold or lower == threshold and not lower_closed)
        failed = upper is not None and upper <= threshold
    elif operation == "ge":
        passed = lower is not None and lower >= threshold
        failed = upper is not None and (upper < threshold or upper == threshold and not upper_closed)
    else:
        _require(operation == "eq")
        passed = point and lower == threshold
        failed = ((lower is not None and (threshold < lower or threshold == lower and not lower_closed))
                  or (upper is not None and (threshold > upper or threshold == upper and not upper_closed)))
    outcome = "satisfied" if passed else "not_satisfied" if failed else "insufficient_info"
    return outcome, _decimal_text(lower) if point else None, predicate["unit"]


def has_target_information(snapshot, facts):
    """A failed extraction never turns explicitly supplied goals into absence."""
    return bool(snapshot.get("개발목표 사양", "").strip() or snapshot.get("연구목표", "").strip()
                or any(fact["basis"] in ("target", "both") for fact in facts))


def make_notice_review(manifest=None, fingerprint=""):
    from copy import deepcopy
    return {"catalogue_id": manifest["catalogue_id"] if manifest else "", "catalogue_fingerprint": fingerprint,
            "catalogue_manifest": deepcopy(manifest), "sources": deepcopy(manifest["sources"]) if manifest else [],
            "clause_snapshots": [], "facts": [],
            "families": [{"family": family, "status": "not_run", "screened_ids": [], "excluded": [], "candidate_ids": [], "errors": []} for family in FAMILIES],
            "comparisons": [], "status": "needs_info", "blocking_reasons": []}


_MEASUREMENT_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.,+\-−])[+\-−]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+\-−]?\d+)?"
)
_UNIT_ALIASES = (frozenset(("um", "µm", "μm")), frozenset(("us", "µs", "μs")))
_KOREAN_UNIT_SUFFIXES = ("이상", "이하", "미만", "초과", "이내", "이외", "이다", "이고", "이며", "에서", "까지", "사이", "으로", "의", "인", "로", "를", "은", "는", "임", "급")
_RANGE_LINK = re.compile(r"\b(?:to|through|thru|until|and|or)\b|에서|부터|까지|내지|사이|[~〜～–—]", re.IGNORECASE)
_EXPRESSION_BOUNDARY = re.compile(r"[;\n。!?]|\.(?=\s+[A-Z가-힣])")
_PROPERTY_LINK = re.compile(r"\s*(?:and\b|while\b|with\b|during\b|이고|이며|및|그리고|하고)\s*", re.IGNORECASE)
_PROSE_UNIT_TAIL = re.compile(r"(?:and|or|while|with|during|at|in|for)\b", re.IGNORECASE)
_STRONG_RANGE_LINK = re.compile(r"\b(?:to|through|thru|until)\b|에서|부터|까지|내지|사이|[~〜～–—]", re.IGNORECASE)


def _worded_range_tail(tail):
    match = re.match(r"\s*(?:to|through|thru|until|and|or)\b", tail, re.IGNORECASE)
    return match is not None and _MEASUREMENT_NUMBER.search(tail, match.end()) is not None


def _unit_pattern(unit):
    aliases = next((group for group in _UNIT_ALIASES if unit in group), (unit,))
    patterns = []
    for alias in sorted(aliases, key=len, reverse=True):
        # Spacing around an explicitly written compound-unit operator does not
        # change its meaning; no missing denominator or factor is inferred.
        parts = re.split(r"([/·⋅*])", alias)
        patterns.append("".join(r"\s*" + re.escape(part) + r"\s*" if part in ("/", "·", "⋅", "*") else re.escape(part)
                                for part in parts if part))
    return re.compile("(?:" + "|".join(patterns) + ")")


def _complete_unit_end(source, end):
    """Recognize a terminal unit token; unknown mathematical tails are unsafe.

    Unicode categories, rather than selected operator spellings, govern this
    boundary. Whitespace cannot terminate an exponent, factor, or grouped unit.
    """
    tail = source[end:]
    if not tail:
        return True
    spaced = tail[0].isspace()
    tail = unicodedata.normalize("NFKC", tail.lstrip())
    if not tail or tail.startswith(_KOREAN_UNIT_SUFFIXES) or _worded_range_tail(tail):
        return True
    if spaced and _PROSE_UNIT_TAIL.match(tail):
        return True
    first, category = tail[0], unicodedata.category(tail[0])
    if category.startswith("L"):
        return spaced and "가" <= first <= "힣"
    if category.startswith(("N", "S", "M", "C")) or category in ("Ps", "Pi", "Pd", "Pc"):
        return False
    if first == ".":
        # A dot followed by another factor is multiplication, not sentence end.
        return _complete_unit_end(tail, 1)
    if category in ("Pe", "Pf") or first in ("'", '"'):
        return _complete_unit_end(tail, 1)
    # Only explicit sentence/list separators close an otherwise unknown tail.
    return first in ",;:!?。…"


_BOUND_PREFIX = re.compile(r"(?:<=|>=|<|>|≤|≥|최대|최소|이하|이상|미만|초과|약|대략|대강|거의|±|∓|\b(?:about|approximately|roughly|nearly|maximum|minimum|at most|at least))\s*$", re.IGNORECASE)
_BOUND_SUFFIX = re.compile(r"\s*(이하|이상|미만|초과|까지|사이|정도|내외|전후)")
_BOUND_KINDS = {"<=": ("upper", True), "≤": ("upper", True), "최대": ("upper", True), "이하": ("upper", True),
                "<": ("upper", False), "미만": ("upper", False), ">=": ("lower", True), "≥": ("lower", True),
                "최소": ("lower", True), "이상": ("lower", True), ">": ("lower", False), "초과": ("lower", False),
                "까지": ("upper", True)}


def _known_quantity(source, token):
    """Read only an explicitly complete unit, without inferring unknown units."""
    unit_start = token.end()
    while unit_start < len(source) and source[unit_start].isspace():
        unit_start += 1
    for unit in sorted(_UNITS, key=len, reverse=True):
        matched = _unit_pattern(unit).match(source, unit_start)
        if matched is not None and _complete_unit_end(source, matched.end()):
            return matched.end(), _UNITS[unit][0]
    return token.end(), None


def _calendar_number(source, token):
    # A calendar role comes from syntax, never from a special year value. A
    # number with a written physical unit remains a measurement instead.
    if not re.fullmatch(r"\d{4}", token.group()) or _known_quantity(source, token)[1] is not None:
        return False
    return (re.match(r"년(?:에|도|의)?(?:\s|$)", source[token.end():]) is not None
            or re.search(r"\b(?:in|during|since)\s*$", source[:token.start()], re.IGNORECASE) is not None)


def _property_label(text):
    text = text.strip()
    while (modifier := _BOUND_PREFIX.search(text)) is not None:
        text = text[:modifier.start()].rstrip()
    text = re.sub(r"\s*(?:\b(?:is|was|equals)|[=:])\s*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"(?:은|는|이|가)$", "", text).strip()
    return text.casefold() if re.fullmatch(r"[A-Za-z가-힣]+(?:\s+[A-Za-z가-힣]+)*", text) else None


def _source_property_role(source, target, numbers):
    """Assign numeric range members to their original property clause.

    Only a conjunction followed by an explicit label starts another property.
    Bare range endpoints inherit the previous role, including its uncertainty.
    """
    previous, role = None, (None, 0)
    for token in numbers:
        start = _known_quantity(source, previous)[0] if previous is not None else 0
        text = source[start:token.start()]
        links = list(_PROPERTY_LINK.finditer(text))
        if links:
            link = links[-1]
            before_link = text[:link.start()]
            while (bound := _BOUND_SUFFIX.match(before_link)) is not None:
                before_link = before_link[bound.end():]
            open_range = previous is not None and re.search(r"\b(?:from|between)\s*$", source[:previous.start()], re.IGNORECASE)
            label = _property_label(text[link.end():])
            if label is not None and not open_range and not _STRONG_RANGE_LINK.search(before_link):
                role = label, start + link.start()
        elif previous is None or _calendar_number(source, previous):
            label = _property_label(text)
            if label is not None:
                role = label, start
        if token.start() == target.start():
            return role
        previous = token
    return role


def _independent_quantities(source, first, second, numbers):
    first_end, first_dimension = _known_quantity(source, first)
    _, second_dimension = _known_quantity(source, second)
    gap = source[first_end:second.start()]
    leading = re.search(r"\b(?:from|between)\s*$", source[:first.start()], re.IGNORECASE)
    if _calendar_number(source, first) or _calendar_number(source, second):
        return not leading and _STRONG_RANGE_LINK.search(gap) is None
    first_label, first_clause = _source_property_role(source, first, numbers)
    second_label, second_clause = _source_property_role(source, second, numbers)
    if first_clause != second_clause and first_label is not None and second_label is not None:
        return first_label != second_label
    if leading or _STRONG_RANGE_LINK.search(gap):
        return False
    # A conjunction followed by a different named property starts another
    # quantity clause. Bare alternatives or repeated labels remain unresolved.
    separator = _PROPERTY_LINK.match(gap)
    if separator is None:
        return False
    return (first_dimension is not None and second_dimension is not None
            and first_dimension != second_dimension)


def _multiple_quantity_context(source, number_start, unit_end):
    """Return the extent of an unresolved numeric expression, if it has peers.

    Explicit ranges and unresolved peers retain their complete context. Separate
    source property clauses and calendar roles do not turn a measurement into a
    range. Digits inside the complete unit are not separate quantity values.
    """
    numbers = list(_MEASUREMENT_NUMBER.finditer(source))
    current = next(token for token in numbers if token.start() == number_start)
    peers = []
    for other in numbers:
        if number_start <= other.start() and other.end() <= unit_end:
            continue
        left, right = (other.end(), number_start) if other.end() <= number_start else (unit_end, other.start())
        if left > right:
            continue
        gap = source[left:right]
        if _EXPRESSION_BOUNDARY.search(gap):
            continue
        linked = _RANGE_LINK.search(gap) is not None
        if not linked and "," in gap:
            continue
        first, second = (other, current) if other.start() < number_start else (current, other)
        if _independent_quantities(source, first, second, numbers):
            continue
        peers.append(other)
    if not peers:
        return None
    start = min([number_start] + [token.start() for token in peers])
    end = max([unit_end] + [token.end() for token in peers])
    leading = re.search(r"\b(?:from|between)\s*$", source[:start], re.IGNORECASE)
    if leading:
        start = leading.start()
    return start, end


def _measurement_context(source, number_start, unit_end):
    """Include adjacent bounds/uncertainty so cropped quotes cannot erase them."""
    start, end, modifiers = number_start, unit_end, []
    while True:
        match = _BOUND_PREFIX.search(source[:start])
        if match is None:
            break
        modifier = match.group().strip()
        modifiers.append(_BOUND_KINDS.get(modifier, ("unknown", False)))
        start = match.start()
    prefix = source[:start].rstrip()
    if prefix.endswith("="):
        # A separated ``> =`` is not a plain assignment. Preserve its unparsed
        # mathematical context instead of accepting the right endpoint as exact.
        before_equal = prefix[:-1].rstrip()
        if before_equal and unicodedata.category(before_equal[-1]).startswith(("S", "N", "M")):
            modifiers.append(("unknown", False))
            start = len(before_equal) - 1
            prefix = source[:start].rstrip()
    if prefix:
        previous = unicodedata.normalize("NFKC", prefix[-1])
        category = unicodedata.category(previous[0])
        # Unparsed signs, ranges, arithmetic, numeric coefficients, and grouping
        # expressions cannot be silently discarded to obtain a positive point.
        safe_punctuation = previous in "=,:;([{\"'"
        if (category.startswith(("S", "N", "M", "C")) or category.startswith("P") and not safe_punctuation) and previous != "=":
            modifiers.append(("unknown", False))
            start = len(prefix) - 1
    suffix = _BOUND_SUFFIX.match(source[end:])
    while suffix:
        modifiers.append(_BOUND_KINDS.get(suffix.group(1), ("unknown", False)))
        end += suffix.end()
        suffix = _BOUND_SUFFIX.match(source[end:])
    multiple = _multiple_quantity_context(source, number_start, unit_end)
    if multiple is not None:
        start, end = min(start, multiple[0]), max(end, multiple[1])
        modifiers.append(("unknown", False))
    kind, closed = modifiers[0] if len(modifiers) == 1 else ("point", True) if not modifiers else ("unknown", False)
    return start, end, kind, closed


def _source_decimal(value):
    return _decimal(value.replace(",", "").replace("−", "-"), "근거 수치")


def _measurement_candidates(source, number, unit):
    expression = _unit_pattern(unit) if unit is not None else None
    for token in _MEASUREMENT_NUMBER.finditer(source):
        if token.start() and re.match(r"[A-Za-z0-9_.,+\-]", unicodedata.normalize("NFKC", source[token.start() - 1])):
            continue
        if _source_decimal(token.group()) != number:
            continue
        unit_start = token.end()
        while unit_start < len(source) and source[unit_start].isspace():
            unit_start += 1
        matched = expression.match(source, unit_start) if expression is not None else None
        if expression is not None and (matched is None or not _complete_unit_end(source, matched.end())):
            continue
        unit_end = matched.end() if matched is not None else token.end()
        context = _measurement_context(source, token.start(), unit_end)
        yield token.start(), unit_end, context


def _fact_interval(fact, target_unit):
    number = _decimal_string(fact["number"])
    converted = normalize_measurement(fact["number"], fact["unit"], target_unit)
    if converted is None:
        return None
    bound = _decimal_string(converted)
    intervals = set()
    source = fact["quote"]
    spans = _quoted_value_spans(source, 0, len(source), fact["value_text"])
    for left, right, (_, _, kind, closed) in _measurement_candidates(source, number, fact["unit"]):
        if not any(start <= left and right <= end for start, end in spans):
            continue
        if kind == "unknown":
            return None
        intervals.add((bound, True, bound, True) if kind == "point" else
                      (bound, closed, None, False) if kind == "lower" else (None, False, bound, closed))
    return next(iter(intervals)) if len(intervals) == 1 else None


def _quoted_value_spans(source, start, end, value_text):
    quote = source[start:end]
    spans = []
    position = quote.find(value_text)
    while position >= 0:
        spans.append((start + position, start + position + len(value_text)))
        position = quote.find(value_text, position + 1)
    return spans


def _quoted_measurement_pair(source, start, end, value_text, number, unit):
    """Find the same connected number/unit span in the *original* field.

    Looking at the original field also rejects a quote or value_text cropped
    from ``20 m/s`` to ``20 m``. Separate occurrences cannot form a new pair.
    """
    value_spans = _quoted_value_spans(source, start, end, value_text)
    for token_start, unit_end, (context_start, context_end, _, _) in _measurement_candidates(source, number, unit):
        if context_start < start or context_end > end:
            continue
        if any(left <= token_start and unit_end <= right for left, right in value_spans):
            return True
    return False


def _quoted_unit(source, start, end, value_text, unit):
    spans = _quoted_value_spans(source, start, end, value_text)
    for token in _unit_pattern(unit).finditer(source):
        if token.start() and source[token.start() - 1].isalpha():
            continue
        if _complete_unit_end(source, token.end()) and any(left <= token.start() and token.end() <= right for left, right in spans):
            return True
    return False


@_contract_validator
def validate_fact(fact, snapshot):
    _object(fact, {"fact_id", "basis", "subject", "value_text", "number", "unit", "source_field", "start", "end", "quote"})
    for key in ("fact_id", "subject", "value_text", "quote"):
        _text(fact[key], nonempty=True)
    _require(fact["basis"] in ("current", "target", "both", "unspecified"))
    _require(fact["source_field"] in snapshot)
    start, end = fact["start"], fact["end"]
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(snapshot[fact["source_field"]]))
    _require(snapshot[fact["source_field"]][start:end] == fact["quote"])
    _require(fact["value_text"] in fact["quote"])
    number = _decimal_string(fact["number"], nullable=True)
    _require(fact["unit"] is None or type(fact["unit"]) is str and bool(fact["unit"].strip()))
    if number is not None:
        _require(_quoted_measurement_pair(snapshot[fact["source_field"]], start, end,
                                          fact["value_text"], number, fact["unit"]))
    elif fact["unit"] is not None:
        _require(_quoted_unit(snapshot[fact["source_field"]], start, end, fact["value_text"], fact["unit"]))
    if fact["source_field"] == "현재 기술사양":
        _require(fact["basis"] == "current")
    if fact["source_field"] == "개발목표 사양":
        _require(fact["basis"] == "target")
    return fact


@_contract_validator
def validate_notice_review(notice, snapshot, *, catalogue_fingerprint=None):
    """Verify saved evidence against its own frozen source inventory.

    It requires no live files, API, or current catalogue. Passing an explicit
    current fingerprint additionally binds a resume to that installed baseline.
    """
    _finite_json(notice)
    snapshot = task_snapshot(snapshot)
    _object(notice, {"catalogue_id", "catalogue_fingerprint", "catalogue_manifest", "sources", "clause_snapshots", "facts", "families", "comparisons", "status", "blocking_reasons"})
    _text(notice["catalogue_id"])
    _digest(notice["catalogue_fingerprint"], allow_empty=True)
    _require(notice["status"] in ("complete", "needs_info", "error"))
    _strings(notice["blocking_reasons"], nonempty=True)
    if catalogue_fingerprint is not None:
        _require(notice["catalogue_fingerprint"] == catalogue_fingerprint)
    manifest = notice["catalogue_manifest"]
    if manifest is None:
        _require(notice["status"] != "complete" and not notice["catalogue_id"] and not notice["sources"]
                 and not notice["clause_snapshots"] and not notice["comparisons"] and not notice["facts"])
        inventory, sources = {}, {}
    else:
        validate_manifest(manifest)
        _require(notice["catalogue_fingerprint"] == canonical_hash(manifest) and notice["catalogue_id"] == manifest["catalogue_id"])
        _require(notice["sources"] == manifest["sources"])
        inventory = {entry["clause_id"]: entry for entry in manifest["clause_inventory"]}
        sources = {entry["source_id"]: entry for entry in manifest["sources"]}
    _require(type(notice["clause_snapshots"]) is list)
    clauses = {}
    for clause in notice["clause_snapshots"]:
        validate_clause(clause, manifest=manifest)
        _require(clause["clause_id"] not in clauses)
        clauses[clause["clause_id"]] = clause
    _require(type(notice["facts"]) is list)
    facts = {}
    for fact in notice["facts"]:
        validate_fact(fact, snapshot)
        _require(fact["fact_id"] not in facts)
        facts[fact["fact_id"]] = fact
    _require(type(notice["families"]) is list and len(notice["families"]) == len(FAMILIES))
    family_entries, candidate_ids = {}, set()
    for entry in notice["families"]:
        _object(entry, {"family", "status", "screened_ids", "excluded", "candidate_ids", "errors"})
        family = entry["family"]
        _require(family in FAMILIES and family not in family_entries)
        family_entries[family] = entry
        _require(entry["status"] in ("complete", "partial", "not_run", "error"))
        _strings(entry["screened_ids"], unique=True, nonempty=True)
        _strings(entry["candidate_ids"], unique=True, nonempty=True)
        _strings(entry["errors"], nonempty=True)
        expected = {identity for identity, info in inventory.items() if info["family"] == family}
        _require(set(entry["screened_ids"]) <= expected)
        _require(type(entry["excluded"]) is list)
        excluded = set()
        for item in entry["excluded"]:
            _object(item, {"clause_id", "reason"})
            _text(item["clause_id"], nonempty=True)
            _text(item["reason"], nonempty=True)
            _require(item["clause_id"] not in excluded)
            excluded.add(item["clause_id"])
        selected = set(entry["candidate_ids"])
        _require(not excluded & selected and excluded | selected == set(entry["screened_ids"]))
        candidate_ids.update(selected)
        if entry["status"] == "complete":
            _require(set(entry["screened_ids"]) == expected and not entry["errors"] and manifest is not None)
            relevant = [source for source in sources.values() if family in source["families"]]
            _require(bool(relevant) and all(source["coverage"] == "full" and source["review_status"] == "reviewed" for source in relevant))
        if entry["status"] == "not_run":
            _require(not entry["screened_ids"] and not entry["errors"])
        if entry["status"] == "error":
            _require(bool(entry["errors"]))
    # Candidate plus its complete transitive reference closure, with no dangling
    # definitions. Condition AST already expresses how definitions/notes apply.
    required, visiting = set(), set()

    def include(identity):
        _require(identity in clauses and identity not in visiting)
        if identity in required:
            return
        visiting.add(identity)
        for reference in clauses[identity]["qualifier_refs"]:
            include(reference)
        visiting.remove(identity)
        required.add(identity)

    for identity in candidate_ids:
        include(identity)
    _require(set(clauses) == required)
    _require(type(notice["comparisons"]) is list)
    comparison_ids, compared = set(), set()
    unresolved = False
    for comparison in notice["comparisons"]:
        _object(comparison, {"comparison_id", "family", "clause_id", "source_id", "current_assessment", "target_assessment", "conditions", "missing_information", "rationale", "affected_items"})
        identity = comparison["clause_id"]
        _require(identity in candidate_ids and identity not in compared)
        compared.add(identity)
        clause = clauses[identity]
        _require(comparison["family"] == clause["family"] and comparison["source_id"] == clause["source_id"])
        _require(comparison["comparison_id"] == comparison_id(notice["catalogue_fingerprint"], identity) and comparison["comparison_id"] not in comparison_ids)
        comparison_ids.add(comparison["comparison_id"])
        _text(comparison["rationale"], nonempty=True)
        _require(type(comparison["affected_items"]) is list and all(type(item) is int and 1 <= item <= 8 for item in comparison["affected_items"]))
        _require(len(set(comparison["affected_items"])) == len(comparison["affected_items"]))
        leaves = {leaf["predicate_id"]: leaf for leaf in condition_leaves(clause["condition"])}
        _require(type(comparison["conditions"]) is list)
        checked = {}
        has_target = has_target_information(snapshot, facts.values())
        for condition in comparison["conditions"]:
            _object(condition, {"predicate_id", "basis", "condition_text", "fact_ids", "normalized_value", "normalized_unit", "assessment", "reason", "source_anchor"})
            predicate_id, basis = condition["predicate_id"], condition["basis"]
            _require(predicate_id in leaves and basis in ("current", "target") and (predicate_id, basis) not in checked)
            predicate = leaves[predicate_id]
            _require(condition["condition_text"] == predicate["text"] and condition["source_anchor"] == predicate["source_anchor"])
            _strings(condition["fact_ids"], unique=True, nonempty=True)
            _require(set(condition["fact_ids"]) <= set(facts))
            references = [facts[fact_id] for fact_id in condition["fact_ids"]]
            _require(all(fact["basis"] in (basis, "both") and fact["subject"] == predicate["subject"] for fact in references))
            _require(condition["assessment"] in ASSESSMENTS)
            _text(condition["reason"], nonempty=True)
            _decimal_string(condition["normalized_value"], nullable=True)
            _require(condition["normalized_unit"] is None or type(condition["normalized_unit"]) is str)
            if predicate["type"] == "numeric":
                assessment, value, unit = assess_numeric(predicate, references)
                _require(condition["assessment"] == assessment and condition["normalized_unit"] == unit)
                _require((value is None and condition["normalized_value"] is None) or (value is not None and condition["normalized_value"] is not None and Decimal(value) == Decimal(condition["normalized_value"])))
            else:
                _require(condition["normalized_value"] is None and condition["normalized_unit"] is None)
                if predicate["type"] == "unsupported" or not references:
                    _require(condition["assessment"] == "insufficient_info")
            checked[(predicate_id, basis)] = condition["assessment"]
        expected_current = {(predicate, "current") for predicate in leaves}
        expected_target = {(predicate, "target") for predicate in leaves}
        _require(expected_current <= set(checked) and set(checked) <= expected_current | expected_target)
        _require(not has_target or expected_target <= set(checked))
        current = evaluate_condition(clause["condition"], {predicate: checked[(predicate, "current")] for predicate in leaves})
        target = evaluate_condition(clause["condition"], {predicate: checked[(predicate, "target")] for predicate in leaves}) if has_target else "not_provided"
        _require(comparison["current_assessment"] == current and comparison["target_assessment"] == target)
        _require(type(comparison["missing_information"]) is list)
        missing = set()
        for item in comparison["missing_information"]:
            _object(item, {"basis", "predicate_id", "question"})
            key = (item["predicate_id"], item["basis"])
            _require(key in checked and key not in missing and checked[key] == "insufficient_info")
            _text(item["question"], nonempty=True)
            missing.add(key)
        active_missing = {key for key, assessment in checked.items() if assessment == "insufficient_info" and (key[1] == "current" or has_target)}
        _require(active_missing <= missing)
        if comparison["affected_items"] and (current == "insufficient_info" or target == "insufficient_info"):
            unresolved = True
    _require(compared == candidate_ids)
    family_errors = any(entry["status"] == "error" for entry in family_entries.values())
    incomplete = any(entry["status"] != "complete" for entry in family_entries.values())
    if notice["status"] == "complete":
        _require(not incomplete and not unresolved and not notice["blocking_reasons"])
        validate_manifest(manifest, require_executable=True)
    elif notice["status"] == "error":
        _require(bool(notice["blocking_reasons"]) or family_errors)
    else:
        _require(incomplete or unresolved or bool(notice["blocking_reasons"]))
    if family_errors:
        _require(notice["status"] == "error")
    return notice


def _number(value, nullable=False):
    _require((nullable and value is None) or (type(value) in (int, float) and math.isfinite(value)))


@_contract_validator
def validate_reference_links(text, required, comparisons):
    """Validate exact notice/source pairs in the persisted string field.

    Non-notice criteria may retain prose. Structured links always identify the
    entire comparison set for this criterion, including on partial/error DTOs.
    Duplicate JSON keys are rejected rather than silently taking the last value.
    """
    _text(text)
    if not required and not text.lstrip().startswith(("[", "{")):
        _require("comparison_id" not in text and "source_id" not in text)
        return

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    try:
        links = json.loads(text, object_pairs_hook=unique_object)
    except (ValueError, TypeError):
        raise ValueError("저장 결과의 구조 또는 일치 검증에 실패했습니다.") from None
    _require(type(links) is list)
    identities = set()
    for link in links:
        _object(link, {"comparison_id", "source_id"})
        identity = link["comparison_id"]
        _require(type(identity) is str and identity in comparisons and identity not in identities)
        _require(type(link["source_id"]) is str and link["source_id"] == comparisons[identity]["source_id"])
        identities.add(identity)
    _require(set(required) == identities)


def _criteria_before_review(result, opts):
    """Recognize only the engine's complete, unreviewed placeholder shapes.

    A final-status change alone cannot discard evidence from reviewed criteria.
    Common policy text is intentionally absent from saved DTOs; without options,
    item 8 can therefore have either legitimate initial policy shape.
    """
    if (result["status"] == "완료" or result["reviewers"]
            or any(result[key] is not None for key in ("overall_avg", "rule_grade", "final_grade", "confidence"))):
        return False
    policy = result["task_snapshot"]["부처 세부기준"]
    policies = (policy or opts.ministry_policy,) if opts is not None else ((policy,) if policy else ("", "provided"))
    if (not result["rationale"] and not result["discussion_points"]
            and any(result["criteria"] == _initial_criteria(value) for value in policies)):
        return True
    candidate = result["candidate"]
    ended = [{"item": name, "level": "미검토", "note": "후보 단계 종료: 항목 검토 미실시",
              "law_refs": [], "matched_reference": "", "needs_expert_review": False} for name in ITEM_NAMES]
    return (result["criteria"] == ended
            and (candidate["is_candidate"] is not True or bool(candidate["uncertainty"]))
            and not result["selected_items"] and not result["weights"]
            and result["documents"]["expected_files"] == 1)


def _items(value, detailed=False):
    _require(type(value) is list and len(value) == len(ITEM_NAMES))
    for index, entry in enumerate(value):
        keys = {"item", "level", "note", "law_refs"}
        if detailed:
            keys |= {"matched_reference", "needs_expert_review"}
        _require(type(entry) is dict and set(entry) == keys)
        _require(entry["item"] == ITEM_NAMES[index] and entry["level"] in LEVELS)
        _require(type(entry["note"]) is str)
        _strings(entry["law_refs"])
        allowed = set(CRITERIA[index]["security_refs"] + CRITERIA[index]["sensitive_refs"])
        _require(len(set(entry["law_refs"])) == len(entry["law_refs"]) and set(entry["law_refs"]) <= allowed)
        if detailed:
            _require(type(entry["matched_reference"]) is str and type(entry["needs_expert_review"]) is bool)


def _validate_documents(documents, reviewers):
    _require(type(documents) is dict and set(documents) == {"status", "expected_files", "files", "errors"})
    _require(documents["status"] in ("미생성", "완료", "일부실패", "실패"))
    expected = documents["expected_files"]
    _require(type(expected) is int and expected >= 1)
    expected_identities = {("reviewer", reviewer["reviewer_id"]) for reviewer in reviewers} | {("summary", None)}
    if reviewers or documents["status"] != "미생성":
        _require(expected == len(expected_identities))
    else:
        # Before any reviewer is evaluated, the engine's ungenerated result can
        # retain the intended panel+summary count. Actual exports must contain
        # only the summary; invented individual opinions are never permitted.
        _require(expected in (1, 2, 4))
    _strings(documents["errors"])
    _require(type(documents["files"]) is list and len(documents["files"]) <= expected)
    identities = set()
    for entry in documents["files"]:
        _require(type(entry) is dict and set(entry) == {"kind", "reviewer_id", "path", "status", "error"})
        _require(entry["kind"] in ("summary", "reviewer") and entry["status"] in ("완료", "오류"))
        _require(type(entry["path"]) is str and bool(entry["path"]) and type(entry["error"]) is str)
        _require((entry["kind"] == "summary" and entry["reviewer_id"] is None)
                 or (entry["kind"] == "reviewer" and type(entry["reviewer_id"]) is str and bool(entry["reviewer_id"])))
        identity = (entry["kind"], entry["reviewer_id"])
        _require(identity in expected_identities and identity not in identities)
        identities.add(identity)
    completed = sum(entry["status"] == "완료" for entry in documents["files"])
    if documents["status"] == "미생성":
        _require(not documents["files"] and not documents["errors"])
    elif documents["status"] == "완료":
        _require(completed == expected and identities == expected_identities and not documents["errors"])
    elif documents["status"] == "일부실패":
        _require(0 < completed < expected and bool(documents["errors"]))
    else:
        _require(completed == 0 and bool(documents["errors"]))


@_contract_validator
def validate_result(result, opts=None, task=None, *, catalogue_fingerprint=None):
    """Validate the entire saved contract, including complete reviewer evidence.

    This is structural/integrity validation, not cryptographic authenticity.
    Fingerprints identify inputs/settings; they do not authenticate local files.
    Public run options are deliberately absent from persisted records.
    """
    _finite_json(result)
    _require(type(result) is dict and set(result) == _RESULT_KEYS)
    _require(type(result["schema_version"]) is int and result["schema_version"] == SCHEMA_VERSION)
    _require(result["guideline_id"] == GUIDELINE_ID)
    snapshot = result["task_snapshot"]
    _require(type(snapshot) is dict and set(snapshot) == set(TASK_COLUMNS + OPTIONAL_TASK_COLUMNS))
    _require(all(type(value) is str for value in snapshot.values()) and snapshot == task_snapshot(snapshot))
    _require(result["task_name"] == snapshot["과제명"])
    _digest(result["catalogue_fingerprint"], allow_empty=True)
    notice = validate_notice_review(result["notice_review"], snapshot, catalogue_fingerprint=catalogue_fingerprint)
    _require(result["catalogue_fingerprint"] == notice["catalogue_fingerprint"])
    for key in ("task_fingerprint", "options_fingerprint"):
        _require(type(result[key]) is str and re.fullmatch(r"[0-9a-f]{64}", result[key]) is not None)
    _require(result["task_fingerprint"] == task_fingerprint(snapshot))
    _require(result["method"] in ("impact", "checklist") and result["provider"] in DEFAULT_MODELS)
    _require(type(result["model"]) is str)
    if result["provider"] in ("claude", "openai"):
        _require(result["model"] == DEFAULT_MODELS[result["provider"]])
    _require(result["status"] in STATUSES)
    for key in ("rationale", "discussion_points"):
        _require(type(result[key]) is str)
    _strings(result["unresolved_reasons"])
    _require(result["final_grade"] in GRADES + (None,) and result["rule_grade"] in GRADES + (None,))
    _require(result["confidence"] in CONFIDENCES + (None,))
    _number(result["overall_avg"], nullable=True)
    candidate = result["candidate"]
    _require(type(candidate) is dict and set(candidate) == {"is_candidate", "reason", "uncertainty"})
    _require(candidate["is_candidate"] is None or type(candidate["is_candidate"]) is bool)
    _require(type(candidate["reason"]) is str and type(candidate["uncertainty"]) is str)
    _items(result["criteria"], detailed=True)
    checked_opts = normalize_options(opts, ministry_policy_context=snapshot["부처 세부기준"]) if opts is not None else None
    unreviewed = _criteria_before_review(result, checked_opts)
    comparisons = {entry["comparison_id"]: entry for entry in notice["comparisons"]}
    for index, criterion in enumerate(result["criteria"], 1):
        reference = criterion["matched_reference"]
        # The optional policy item is explicitly unreviewed when no applicable
        # policy was supplied. It must never invent a notice relation.
        omitted_policy = (index == 8 and not snapshot["부처 세부기준"]
            and (checked_opts is None or not checked_opts.ministry_policy)
            and criterion == {"item": ITEM_NAMES[7], "level": "미검토", "note": "부처 세부기준 미제공",
                              "law_refs": [], "matched_reference": "", "needs_expert_review": False})
        if not (reference == "" and (unreviewed or omitted_policy)):
            required = [identity for identity, entry in comparisons.items() if index in entry["affected_items"]]
            validate_reference_links(reference, required, comparisons)
    selected = result["selected_items"]
    _strings(selected)
    _require(list(canonical_items(selected)) == selected and len(set(selected)) == len(selected))
    _require(type(result["weights"]) is dict)
    for name, value in result["weights"].items():
        _require(name in selected)
        _number(value)
        _require(.8 <= value <= 1.2)
    reviewers = result["reviewers"]
    _require(type(reviewers) is list and len(reviewers) in (0, 1, 3))
    for index, reviewer in enumerate(reviewers):
        _require(type(reviewer) is dict and set(reviewer) == _REVIEWER_KEYS)
        _require(reviewer["reviewer_id"] == f"reviewer-{index + 1}")
        _require(reviewer["persona"] == PERSONAS[index] and reviewer["status"] in ("완료", "검토필요", "미실시"))
        for key in ("rationale", "discussion_points"):
            _require(type(reviewer[key]) is str)
        _strings(reviewer["unresolved_reasons"])
        _require(reviewer["grade"] in GRADES + (None,) and reviewer["confidence"] in CONFIDENCES + (None,))
        _number(reviewer["reviewer_score"], nullable=True)
        _require(type(reviewer["notice_comments"]) is list)
        comparison_ids = {entry["comparison_id"] for entry in notice["comparisons"]}
        comment_ids = set()
        for comment in reviewer["notice_comments"]:
            _object(comment, {"comparison_id", "comment"})
            _require(comment["comparison_id"] in comparison_ids and comment["comparison_id"] not in comment_ids)
            comment_ids.add(comment["comparison_id"])
            _text(comment["comment"], nonempty=True)
        if reviewer["status"] == "완료":
            _require(comment_ids == comparison_ids)
        _require(type(reviewer["scores"]) is dict)
        for name, score in reviewer["scores"].items():
            _require(name in selected and type(score) is int and parse_score(score) == score)
        if reviewer["item_reviews"]:
            _items(reviewer["item_reviews"])
        else:
            _require(type(reviewer["item_reviews"]) is list and reviewer["status"] != "완료")
        if result["method"] == "checklist":
            _require(not reviewer["scores"] and reviewer["reviewer_score"] is None)
        if reviewer["status"] == "완료":
            _require(not reviewer["unresolved_reasons"] and reviewer["grade"] in GRADES
                     and reviewer["confidence"] in CONFIDENCES and bool(reviewer["rationale"].strip()))
            _require(all(item["note"].strip() for item in reviewer["item_reviews"]))
            if result["method"] == "impact":
                _require(bool(selected) and set(reviewer["scores"]) == set(selected))
                score = calculate_reviewer_score(reviewer["scores"], selected, result["weights"])
                _require(reviewer["reviewer_score"] is not None and abs(score - reviewer["reviewer_score"]) < 1e-12)
        else:
            _require(reviewer["grade"] is None)
        if reviewer["status"] == "미실시":
            _require(not reviewer["scores"] and reviewer["reviewer_score"] is None and not reviewer["item_reviews"])
    _validate_documents(result["documents"], reviewers)
    if result["method"] == "checklist":
        _require(not result["weights"] and result["overall_avg"] is None and result["rule_grade"] is None)
    elif result["overall_avg"] is not None or result["rule_grade"] is not None:
        _require(bool(reviewers) and all(reviewer["status"] == "완료" for reviewer in reviewers))
        average = calculate_committee_average(reviewers, len(reviewers))
        _require(average is not None and result["overall_avg"] is not None
                 and abs(result["overall_avg"] - average) < 1e-12 and result["rule_grade"] == rule_grade(average))
    if result["status"] == "완료":
        _require(notice["status"] == "complete")
        _require(bool(selected))
        _require(candidate["is_candidate"] is True and bool(candidate["reason"].strip()) and not candidate["uncertainty"])
        _require(not result["unresolved_reasons"] and bool(result["rationale"].strip()))
        _require(result["final_grade"] in GRADES and result["confidence"] in CONFIDENCES)
        _require(len(reviewers) in (1, 3))
        for index, criterion in enumerate(result["criteria"]):
            if index < 7 or criterion["level"] != "미검토":
                _require(criterion["level"] not in ("판단곤란", "미검토")
                         and not criterion["needs_expert_review"] and bool(criterion["note"].strip()))
                if criterion["level"] in ("해당", "일부"):
                    _require(bool(criterion["law_refs"]))
        for reviewer in reviewers:
            _require(reviewer["status"] == "완료" and not reviewer["unresolved_reasons"])
            _require(reviewer["grade"] in GRADES and reviewer["confidence"] in CONFIDENCES and bool(reviewer["rationale"].strip()))
            _require(all(entry["note"].strip() for entry in reviewer["item_reviews"]))
            for index, item in enumerate(reviewer["item_reviews"]):
                if index < 7 or result["criteria"][index]["level"] != "미검토":
                    _require(item["level"] not in ("판단곤란", "미검토"))
                    if item["level"] in ("해당", "일부"):
                        _require(bool(item["law_refs"]))
            if result["method"] == "impact":
                _require(bool(selected) and set(reviewer["scores"]) == set(selected))
                score = calculate_reviewer_score(reviewer["scores"], selected, result["weights"])
                _require(reviewer["reviewer_score"] is not None and abs(score - reviewer["reviewer_score"]) < 1e-12)
        if result["method"] == "impact":
            _require(validate_weights(selected, result["weights"]) == result["weights"])
            average = calculate_committee_average(reviewers, len(reviewers))
            _require(result["overall_avg"] is not None and abs(average - result["overall_avg"]) < 1e-12)
            _require(result["rule_grade"] == rule_grade(average))
        if result["rule_grade"] is not None and result["final_grade"] != result["rule_grade"]:
            legal_markers = ("제21조제4항", "제21조제5항") + tuple(
                reference for criterion in CRITERIA for reference in criterion["security_refs"] + criterion["sensitive_refs"])
            _require(result["confidence"] == "낮음" and bool(result["discussion_points"].strip())
                     and any(reference in result["rationale"] for reference in legal_markers))
    elif result["status"] == "후보제외":
        _require(notice["status"] == "complete")
        _require(candidate["is_candidate"] is False and not candidate["uncertainty"] and not reviewers)
        _require(result["final_grade"] is None)
        _require(not selected and not result["weights"] and result["overall_avg"] is None and result["rule_grade"] is None)
        _require(result["documents"]["expected_files"] == 1)
    else:
        _require(result["final_grade"] is None)
    if notice["status"] == "error":
        _require(result["status"] == "오류")
    if notice["status"] == "needs_info":
        _require(result["status"] in ("검토필요", "오류"))
    if opts is not None:
        opts = checked_opts
        _require(opts.catalogue_fingerprint == result["catalogue_fingerprint"])
        _require(result["options_fingerprint"] == options_fingerprint(opts))
        _require((result["method"], result["provider"], result["model"]) == (opts.method, opts.provider, opts.model))
        if result["overall_avg"] is not None:
            _require(len(reviewers) == opts.num_reviewers)
        if result["status"] == "완료":
            _require(len(reviewers) == opts.num_reviewers)
            policy = snapshot["부처 세부기준"] or opts.ministry_policy
            eligible = eligible_items(policy)
            for item in result["criteria"]:
                if item["item"] in eligible:
                    _require(item["level"] not in ("판단곤란", "미검토") and not item["needs_expert_review"] and bool(item["note"].strip()))
                    if item["level"] in ("해당", "일부"):
                        _require(bool(item["law_refs"]))
            for reviewer in reviewers:
                for item in reviewer["item_reviews"]:
                    if item["item"] in eligible:
                        _require(item["level"] not in ("판단곤란", "미검토"))
                        if item["level"] in ("해당", "일부"):
                            _require(bool(item["law_refs"]))
            expected = (list(opts.selected_items) if opts.selection_mode == "manual" else
                        [entry["item"] for entry in result["criteria"] if entry["item"] in eligible
                         and entry["level"] in ("해당", "일부", "판단곤란")])
            _require(selected == expected)
            if opts.method == "impact":
                _require(result["weights"] == effective_weights(opts, selected))
    if task is not None:
        _require(snapshot == task_snapshot(task))
    return result


validate_documents = _contract_validator(_validate_documents)
