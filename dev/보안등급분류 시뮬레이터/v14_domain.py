"""v14 classification contracts and guideline calculations (no UI or network).

The source is the user-supplied final guideline. Numerical bands are reference
opinions; the legal definition and the need to protect against disclosure govern
the final opinion. Unavailable evidence never becomes a score or ordinary grade.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from urllib.parse import urlsplit


GUIDELINE_ID = "research-security-final-a67e47f5ac8ee07d"
SCHEMA_VERSION = 1
GRADES = ("보안과제", "민감과제", "일반과제")
LEVELS = ("해당", "일부", "미해당", "판단곤란", "미검토")
CONFIDENCES = ("높음", "보통", "낮음")
STATUSES = ("완료", "검토필요", "후보제외", "오류")
TASK_COLUMNS = ("세부사업명", "과제명", "연구목표", "연구내용", "기대효과")
OPTIONAL_TASK_COLUMNS = ("추가 검토정보", "부처 세부기준")
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

    def to_dict(self) -> dict:
        return {
            "method": self.method, "provider": self.provider, "model": self.model,
            "num_reviewers": self.num_reviewers, "strictness": self.strictness,
            "selection_mode": self.selection_mode, "selected_items": list(self.selected_items),
            "weights": dict(self.weights), "weight_tolerance": self.weight_tolerance,
            "ministry_policy": self.ministry_policy, "guideline_id": self.guideline_id,
            "local_base_url": self.local_base_url,
        }


def normalize_options(options=None, *, ministry_policy_context="", allow_row_policy=False) -> RunOptions:
    """Freeze public options, validating item 8 against the effective policy.

    A single-task caller supplies the row policy as ``ministry_policy_context``.
    A batch caller can defer this one check with ``allow_row_policy=True`` before
    reading rows, but each task must then pass through ``make_result`` or this
    function with its actual context. Context never changes the frozen options:
    run settings and row contents retain separate stable fingerprints.
    """
    raw = options.to_dict() if isinstance(options, RunOptions) else dict(options or {})
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
    if strictness not in ("엄격", "표준", "관대"):
        raise ValueError("마지막 의견 엄격도가 올바르지 않습니다.")
    selection = raw.get("selection_mode", "auto")
    if selection not in ("auto", "manual"):
        raise ValueError("항목 선택 방식이 올바르지 않습니다.")
    names = canonical_items(raw.get("selected_items", ()))
    policy = str(raw.get("ministry_policy", "") or "").strip()
    context_policy = str(ministry_policy_context or "").strip()
    if ITEM_NAMES[7] in names and not (policy or context_policy or allow_row_policy):
        raise ValueError("8번 항목을 선택하려면 부처 세부기준을 입력해야 합니다.")
    tol = _decimal(raw.get("weight_tolerance", 1e-6), "허용오차")
    if not 0 <= tol <= Decimal("0.000001"):
        raise ValueError("허용오차는 0~0.000001이어야 합니다.")
    weight_map = {}
    if method == "impact":
        for key, value in dict(raw.get("weights", {}) or {}).items():
            name = resolve_item(key)
            if name in weight_map:
                raise ValueError("가중치 항목이 중복되었습니다.")
            number = _decimal(value, "가중치")
            if not Decimal("0.8") <= number <= Decimal("1.2"):
                raise ValueError("가중치는 0.8~1.2여야 합니다.")
            weight_map[name] = float(number)
        if selection == "manual":
            weight_map = validate_weights(names, weight_map, tol)
    guideline = str(raw.get("guideline_id", GUIDELINE_ID))
    if guideline != GUIDELINE_ID:
        raise ValueError("가이드라인 식별값이 일치하지 않습니다.")
    base_url = str(raw.get("local_base_url", "") or "").strip()
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("로컬 서버 주소는 인증정보·쿼리 없는 HTTP(S) 주소여야 합니다.")
    return RunOptions(method, provider, model, count, strictness, selection,
                      names, tuple((name, weight_map[name]) for name in ITEM_NAMES if name in weight_map),
                      float(tol), policy, guideline, base_url)


def task_snapshot(task: Mapping) -> dict[str, str]:
    result = {column: "" if task.get(column) is None else str(task.get(column, "")).strip()
              for column in TASK_COLUMNS + OPTIONAL_TASK_COLUMNS}
    if not result["과제명"]:
        raise ValueError("과제명은 필수입니다.")
    return result


def _fingerprint(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
            "confidence": None, "rationale": "", "discussion_points": "", "unresolved_reasons": []}


def make_result(task: Mapping, options=None) -> dict:
    snapshot = task_snapshot(task)
    opts = normalize_options(options, ministry_policy_context=snapshot["부처 세부기준"])
    # A row-specific policy is part of task_fingerprint; run-level policy is part
    # of options_fingerprint. Either permits considering item 8.
    policy = snapshot["부처 세부기준"] or opts.ministry_policy
    return {
        "schema_version": SCHEMA_VERSION, "guideline_id": GUIDELINE_ID,
        "task_snapshot": snapshot, "task_fingerprint": task_fingerprint(snapshot),
        "options_fingerprint": options_fingerprint(opts), "task_name": snapshot["과제명"],
        "method": opts.method, "provider": opts.provider, "model": opts.model,
        "status": "검토필요", "candidate": {"is_candidate": None, "reason": "", "uncertainty": ""},
        "criteria": [{"item": name, "level": "판단곤란" if name in eligible_items(policy) else "미검토",
                      "note": "" if name in eligible_items(policy) else "부처 세부기준 미제공",
                      "law_refs": list(CRITERIA[index]["security_refs"] + CRITERIA[index]["sensitive_refs"]),
                      "matched_reference": "", "needs_expert_review": True}
                     for index, name in enumerate(ITEM_NAMES)],
        "selected_items": list(opts.selected_items),
        "weights": dict(opts.weights) if opts.method == "impact" else {},
        "reviewers": [], "overall_avg": None, "rule_grade": None, "final_grade": None,
        "confidence": None, "rationale": "", "discussion_points": "", "unresolved_reasons": [],
        "documents": {"status": "미생성", "expected_files": opts.num_reviewers + 1, "files": [], "errors": []},
    }
