"""판정 엔진(spec 7장). AI 단계가 만든 목표 수치·후보 항목·매핑을 받아 비교·항목·범위·종합 판정을 낸다.

흐름:
    7.1 매핑 거르기   — 없는 ID·반쪽 매핑·10진수가 아닌 목표값은 버리고 `dropped`에 사유와 함께 남긴다.
                      단위는 별칭표로 표준 표기로 바꾼 뒤 같은 글자면 그대로, 다르면 같은 종류이고 환산표에 있을 때만 환산한다.
    7.2 비교 하나   — 목표값 V와 기준값 T를 Decimal로 비교한다. 충족이면 초과, 못 미친 차이가 근접 기준(%) 이하이면 근접, 넘으면 미달.
    7.3 항목 판정   — 갈래 안은 AND(가장 낮은 판정), 갈래 사이는 OR(AI가 고른 갈래, 못 골랐으면 가장 높은 판정 + 갈래 확인 필요).
    7.4 목표 불일치 — 같은 기준에 서로 다른 출처(최종목표·연구개발내용·활용계획 및 기대효과·목표 발췌 중 어느 두 곳이든)의
                      다른 값이 매핑되면 모두 비교하고 더 높은 판정을 쓴다.
    7.5 과제 판정   — 범위마다 후보 항목 판정 중 가장 높은 수치 판정, 종합은 범위 중 가장 높은 수치 판정.

숫자는 Decimal로 계산하고 출력에서는 문자열로 둔다. 출력 문자열은 모두 이 모듈의 값 집합(7.7) 안에 있다.
고른 범위(families_selected)에 들지 않는 후보 항목은 판정하지 않고 `skipped_clauses`에 남긴다(조용히 버리지 않는다).
후보 기록에 `code`가 실려 오면 그대로 옮기고, 없으면 빈 글이다(기준값 표 기록 4.1에는 code가 없다).
항목 기록의 `deciding_branch_ids`는 판정을 정한 갈래(고려한 갈래 중 항목 판정과 같은 판정의 갈래들, 갈래 순서)이고,
숫자로 판정하지 못한 항목은 빈 목록이다. 판정 계산에는 쓰지 않으며 간단한 결과(brief)가 사유에 쓸 비교를 고르는 데만 쓴다.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from threshold_table import OPERATORS, STATUS_FAILED, STATUS_NONE
from units import UnitError, compare_units, convert, normalize_unit

# 근접 기준(%). 조정할 수 있다. judge()의 near_percent 인자로 바꿀 수도 있다.
NEAR_PERCENT = Decimal("10")

# 7.7 비교 판정
VERDICT_OVER = "초과"
VERDICT_NEAR = "근접"
VERDICT_UNDER = "미달"
VERDICT_UNIT_KIND = "비교 불가(단위 종류 다름)"
VERDICT_UNIT_CONVERT = "비교 불가(단위 환산 불가)"
VERDICT_ZERO = "비교 불가(기준값 0)"
COMPARISON_VERDICTS = (VERDICT_OVER, VERDICT_NEAR, VERDICT_UNDER, VERDICT_UNIT_KIND, VERDICT_UNIT_CONVERT, VERDICT_ZERO)

# 7.7 항목 판정
CLAUSE_VERDICT_NOT_COMPARABLE = "수치 비교 불가"
CLAUSE_VERDICT_NO_NUMERIC = "수치 기준 없음(관련 분야)"
CLAUSE_VERDICTS = (VERDICT_OVER, VERDICT_NEAR, VERDICT_UNDER, CLAUSE_VERDICT_NOT_COMPARABLE, CLAUSE_VERDICT_NO_NUMERIC)

# 7.7 범위·종합 판정. FAMILY_VERDICT_STATUS는 흐름 작업이 과제 상태에 따라 쓴다(엔진은 상수만 둔다).
FAMILY_VERDICT_NONE = "수치 판정 없음"
FAMILY_VERDICT_EXCLUDED = "대조 안 함(선택 제외)"
FAMILY_VERDICT_STATUS = "판정 안 함(상태 참고)"
FAMILY_VERDICTS = (VERDICT_OVER, VERDICT_NEAR, VERDICT_UNDER, FAMILY_VERDICT_NONE, FAMILY_VERDICT_EXCLUDED, FAMILY_VERDICT_STATUS)

# 7.7 확인 표시(출력 순서도 이 순서)
FLAG_CHECK = "추가 확인 조건"
FLAG_BRANCH = "갈래 확인 필요"
FLAG_PAIR = "매핑 확인 필요"
FLAG_RANGE = "범위 목표"
FLAG_PARTIAL = "일부 수치만 비교"
FLAG_INCONSISTENT = "입력 간 목표값 불일치"
FLAG_EXTRACTED = "AI가 읽은 기준값(원문 확인 필요)"
FLAG_REJECTED = "기준값 채택 실패(원문 확인 필요)"
FLAGS = (FLAG_CHECK, FLAG_BRANCH, FLAG_PAIR, FLAG_RANGE, FLAG_PARTIAL, FLAG_INCONSISTENT, FLAG_EXTRACTED, FLAG_REJECTED)

# 수치 비교 불가 사유
REASON_NO_FACT = "매핑된 최종목표 사양 없음"
REASON_FAILED = "기준값 채택 실패"

# 판정별 항목 수의 키
COUNT_OVER = "초과"
COUNT_NEAR = "근접"
COUNT_UNDER = "미달"
COUNT_NOT_COMPARABLE = "수치 비교 불가"
COUNT_NO_NUMERIC = "수치 기준 없음"
COUNT_KEYS = (COUNT_OVER, COUNT_NEAR, COUNT_UNDER, COUNT_NOT_COMPARABLE, COUNT_NO_NUMERIC)

# 수치 판정의 높낮이. 초과 > 근접 > 미달. 비교 불가는 순위가 없다.
_RANK = {VERDICT_OVER: 3, VERDICT_NEAR: 2, VERDICT_UNDER: 1}
_FAMILY_ORDER = ("advanced", "core", "dual_use", "military")
_CLAUSE_TO_COUNT = {
    VERDICT_OVER: COUNT_OVER, VERDICT_NEAR: COUNT_NEAR, VERDICT_UNDER: COUNT_UNDER,
    CLAUSE_VERDICT_NOT_COMPARABLE: COUNT_NOT_COMPARABLE, CLAUSE_VERDICT_NO_NUMERIC: COUNT_NO_NUMERIC,
}


@dataclass
class JudgeResult:
    """judge()의 결과. 모든 값은 JSON으로 바로 직렬화된다(숫자는 문자열)."""
    comparisons: list = field(default_factory=list)
    clauses: list = field(default_factory=list)
    families: dict = field(default_factory=dict)
    overall: str = FAMILY_VERDICT_NONE
    counts: dict = field(default_factory=dict)
    flagged_clause_count: int = 0
    dropped: list = field(default_factory=list)
    skipped_clauses: list = field(default_factory=list)
    near_percent: str = str(NEAR_PERCENT)

    def to_dict(self):
        return dict(comparisons=self.comparisons, clauses=self.clauses, families=self.families, overall=self.overall,
                    counts=self.counts, flagged_clause_count=self.flagged_clause_count, dropped=self.dropped,
                    skipped_clauses=self.skipped_clauses, near_percent=self.near_percent)


# ---------- 작은 도우미 ----------

def _text(value):
    return "" if value is None else str(value)


def _decimal(text):
    """10진수 문자열 → Decimal. 유한한 수가 아니면 None."""
    try:
        value = Decimal(str(text).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def _ordered_flags(flags):
    """FLAGS 순서로 정렬한 중복 없는 목록."""
    present = set(flags)
    return [flag for flag in FLAGS if flag in present]


def _highest(verdicts):
    """순위 있는 판정 중 가장 높은 것. 없으면 None."""
    ranked = [v for v in verdicts if v in _RANK]
    return max(ranked, key=_RANK.__getitem__) if ranked else None


def _lowest(verdicts):
    ranked = [v for v in verdicts if v in _RANK]
    return min(ranked, key=_RANK.__getitem__) if ranked else None


def _display(gap):
    """차이 %의 표시용 값: 소수 첫째 자리 반올림(ROUND_HALF_UP) 문자열."""
    return str(gap.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------- 7.2 비교 하나 ----------

def compare_values(operator, threshold_value, low, high, near_percent):
    """목표값(low·high)과 기준값 T를 비교한다.

    돌려주는 것: (verdict, used_value, gap_percent 또는 None, 범위 목표 여부).
    범위 목표(low≠high)는 기준을 넘기에 가장 유리한 끝값을 쓴다(ge·gt는 high, le·lt는 low).
    """
    is_range = low != high
    if operator in ("ge", "gt"):
        used = max(low, high)
    else:
        used = min(low, high)
    threshold = threshold_value
    if operator == "ge":
        satisfied = used >= threshold
    elif operator == "gt":
        satisfied = used > threshold
    elif operator == "le":
        satisfied = used <= threshold
    elif operator == "lt":
        satisfied = used < threshold
    else:
        raise ValueError(f"operator 값이 아니다: {operator!r}")
    if threshold == 0:
        # 차이 %를 정의할 수 없다. 충족이면 초과, 아니면 비교 불가.
        return (VERDICT_OVER if satisfied else VERDICT_ZERO), used, None, is_range
    if operator in ("ge", "gt"):
        gap = (threshold - used) / abs(threshold) * 100
    else:
        gap = (used - threshold) / abs(threshold) * 100
    if satisfied:
        verdict = VERDICT_OVER
    elif gap <= near_percent:
        verdict = VERDICT_NEAR
    else:
        verdict = VERDICT_UNDER
    return verdict, used, gap, is_range


# ---------- 7.1 매핑 거르기 ----------

def _index_candidates(candidates, selected, skipped):
    """clause_id → 기록, threshold_id → (clause_id, branch), branch_id → clause_id. 고르지 않은 범위의 후보는 skipped에."""
    by_clause = {}
    thresholds = {}
    branches = {}
    for candidate in candidates:
        clause_id = _text(candidate.get("clause_id"))
        family = _text(candidate.get("family"))
        if family not in selected:
            skipped.append(dict(clause_id=clause_id, family=family, reason="선택하지 않은 검토 대상 고시의 관련 고시 조항"))
            continue
        by_clause[clause_id] = candidate
        for branch in candidate.get("branches", []):
            branch_id = _text(branch.get("branch_id"))
            branches[branch_id] = clause_id
            for threshold in branch.get("thresholds", []):
                thresholds[_text(threshold.get("threshold_id"))] = (clause_id, branch, threshold)
    return by_clause, thresholds, branches


def _filter_pairs(pairs, facts_by_id, by_clause, thresholds, branches, dropped):
    """유효한 매핑만 돌려준다. 버린 매핑은 dropped에 (pair, reason)으로 남긴다.

    돌려주는 것: (비교할 매핑 목록 [(pair, clause_id, branch, threshold, fact, low, high)], 갈래 선택 {clause_id: {branch_id}})
    """
    valid = []
    branch_choices = {}
    for pair in pairs:
        clause_id = _text(pair.get("clause_id"))
        fact_id = _text(pair.get("fact_id"))
        threshold_id = _text(pair.get("threshold_id"))
        branch_id = _text(pair.get("branch_id"))

        def drop(reason):
            dropped.append(dict(pair=pair, reason=reason))

        if clause_id not in by_clause:
            drop(f"관련 고시 조항에 없는 clause_id: {clause_id!r}")
            continue
        if branch_id and branches.get(branch_id) != clause_id:
            drop(f"고시 조항 {clause_id}에 없는 branch_id: {branch_id!r}")
            continue
        if branch_id:
            branch_choices.setdefault(clause_id, set()).add(branch_id)
        if not fact_id and not threshold_id:
            continue  # 갈래만 정한 매핑
        if not fact_id:
            drop(f"fact_id가 비어 있다(threshold_id {threshold_id!r})")
            continue
        if not threshold_id:
            drop(f"threshold_id가 비어 있다(fact_id {fact_id!r})")
            continue
        if fact_id not in facts_by_id:
            drop(f"최종목표 사양에 없는 fact_id: {fact_id!r}")
            continue
        if threshold_id not in thresholds or thresholds[threshold_id][0] != clause_id:
            drop(f"고시 조항 {clause_id}에 없는 threshold_id: {threshold_id!r}")
            continue
        _, branch, threshold = thresholds[threshold_id]
        if threshold.get("operator") not in OPERATORS:
            drop(f"고시 기준 {threshold_id}의 operator 값이 아니다: {threshold.get('operator')!r}")
            continue
        if _decimal(threshold.get("value")) is None:
            drop(f"고시 기준 {threshold_id}의 value가 10진수가 아니다: {threshold.get('value')!r}")
            continue
        fact = facts_by_id[fact_id]
        low, high = _decimal(fact.get("low")), _decimal(fact.get("high"))
        if low is None or high is None:
            drop(f"최종목표 사양 {fact_id}의 low·high가 10진수가 아니다: {fact.get('low')!r}, {fact.get('high')!r}")
            continue
        valid.append((pair, clause_id, branch, threshold, fact, low, high))
    return valid, branch_choices


def _compare_pair(pair, clause_id, candidate, branch, threshold, fact, low, high, near_percent):
    """매핑 하나의 비교 기록(출력 comparisons 원소)."""
    threshold_unit = normalize_unit(threshold.get("unit"))
    fact_unit = normalize_unit(fact.get("unit"))
    threshold_value = _decimal(threshold.get("value"))
    operator = threshold.get("operator")
    relation = compare_units(fact_unit, threshold_unit)
    # 단위를 맞추지 못해도 어느 끝값을 쓰려 했는지는 보인다(목표 단위 그대로).
    used = max(low, high) if operator in ("ge", "gt") else min(low, high)
    is_range = low != high
    converted = gap = None
    if relation == "different_kind":
        verdict = VERDICT_UNIT_KIND
    elif relation == "not_convertible":
        verdict = VERDICT_UNIT_CONVERT
    else:
        try:
            converted_low = convert(low, fact_unit, threshold_unit)
            converted_high = convert(high, fact_unit, threshold_unit)
        except UnitError:
            # compare_units가 same·convertible을 돌려줬으면 여기 오지 않는다. 방어용.
            verdict = VERDICT_UNIT_CONVERT
        else:
            verdict, converted, gap, is_range = compare_values(operator, threshold_value, converted_low, converted_high,
                                                               near_percent)
    flags = []
    if is_range:
        flags.append(FLAG_RANGE)
    if pair.get("ambiguous"):
        flags.append(FLAG_PAIR)
    if threshold.get("origin") == "extracted":
        flags.append(FLAG_EXTRACTED)
    return dict(
        clause_id=clause_id, family=_text(candidate.get("family")), code=_text(candidate.get("code")),
        title=_text(candidate.get("title")), branch_id=_text(branch.get("branch_id")), branch_label=_text(branch.get("label")),
        threshold_id=_text(threshold.get("threshold_id")), subject=_text(threshold.get("subject")), operator=operator,
        threshold_value=str(threshold_value), threshold_unit=threshold_unit, origin=_text(threshold.get("origin")),
        threshold_quote=_text(threshold.get("quote")), quote_source=_text(threshold.get("quote_source")),
        fact_id=_text(fact.get("fact_id")), fact_subject=_text(fact.get("subject")), value_text=_text(fact.get("value_text")),
        used_value=str(used), fact_unit=fact_unit, converted_value=None if converted is None else str(converted),
        fact_quote=_text(fact.get("quote")), source_field=_text(fact.get("source_field")),
        gap_percent=None if gap is None else str(gap), gap_percent_display=None if gap is None else _display(gap),
        verdict=verdict, flags=flags, pair_reason=_text(pair.get("reason")),
    )


# ---------- 7.4 같은 기준에 여러 목표 ----------

def _mark_inconsistent(comparisons):
    """같은 기준에 서로 다른 출처(source_field)의 다른 값이 매핑되었으면 그 비교들에 '입력 간 목표값 불일치'를 붙인다."""
    by_threshold = {}
    for comp in comparisons:
        by_threshold.setdefault((comp["clause_id"], comp["threshold_id"]), []).append(comp)
    for group in by_threshold.values():
        sources = {comp["source_field"] for comp in group}
        if len(sources) < 2:
            continue
        values_by_source = {}
        for comp in group:
            key = (comp["used_value"], comp["fact_unit"])
            values_by_source.setdefault(comp["source_field"], set()).add(key)
        all_values = set().union(*values_by_source.values())
        if len(all_values) > 1:
            for comp in group:
                comp["flags"].append(FLAG_INCONSISTENT)


# ---------- 7.3 항목 판정 ----------

def _branch_verdict(branch, comparisons_by_threshold, rejected):
    """숫자 갈래 하나의 (판정 또는 None, 비교 못 한 물리량 목록, 비교 불가 사유 목록, 비교가 하나라도 있었는지)."""
    verdicts = []
    missing = []
    reasons = []
    paired = False
    for threshold in branch.get("thresholds", []):
        comps = comparisons_by_threshold.get(_text(threshold.get("threshold_id")), [])
        if comps:
            paired = True
        best = _highest(comp["verdict"] for comp in comps)
        if best is None:
            missing.append(_text(threshold.get("subject")))
            for comp in comps:
                if comp["verdict"] not in reasons:
                    reasons.append(comp["verdict"])
        else:
            verdicts.append(best)
    branch_id = _text(branch.get("branch_id"))
    for entry in rejected:
        if _text(entry.get("branch_id")) == branch_id:
            missing.append(_text(entry.get("subject")))
    return _lowest(verdicts), missing, reasons, paired


def _judge_clause(candidate, comparisons, branch_choice):
    """항목 하나의 판정 기록(출력 clauses 원소)."""
    clause_id = _text(candidate.get("clause_id"))
    status = _text(candidate.get("numeric_status"))
    branches = candidate.get("branches", [])
    rejected = list(candidate.get("rejected", []))
    checks = list(candidate.get("checks", []))
    flags = []
    reason = ""
    missing_subjects = []
    deciding = []
    branch_texts = [_text(b.get("text")) for b in branches if not b.get("thresholds") and _text(b.get("text"))]
    numeric_branches = [b for b in branches if b.get("thresholds")]

    if status == STATUS_NONE:
        verdict = CLAUSE_VERDICT_NO_NUMERIC
    elif status == STATUS_FAILED or not numeric_branches:
        verdict = CLAUSE_VERDICT_NOT_COMPARABLE
        reason = REASON_FAILED if status == STATUS_FAILED else REASON_NO_FACT
    else:
        comparisons_by_threshold = {}
        for comp in comparisons:
            comparisons_by_threshold.setdefault(comp["threshold_id"], []).append(comp)
        results = {}
        for branch in numeric_branches:
            results[_text(branch.get("branch_id"))] = _branch_verdict(branch, comparisons_by_threshold, rejected)

        chosen = None
        chosen_is_text = False
        if branch_choice is not None and len(branch_choice) == 1:
            chosen = next(iter(branch_choice))
            chosen_is_text = chosen not in results
        if chosen is not None and not chosen_is_text:
            considered = [chosen]
        else:
            considered = [bid for bid, (v, _, _, _) in results.items() if v is not None]
            if considered and (len(numeric_branches) > 1 or chosen_is_text):
                flags.append(FLAG_BRANCH)
        if branch_texts:
            flags.append(FLAG_BRANCH)

        verdict = _highest(results[bid][0] for bid in considered) if considered else None
        if verdict is None:
            verdict = CLAUSE_VERDICT_NOT_COMPARABLE
            # 사유: 고른 갈래(또는 전체)에 매핑이 하나도 없으면 '매핑된 최종목표 사양 없음', 있었으면 비교 불가 사유들.
            scope = [chosen] if chosen is not None and not chosen_is_text else list(results)
            reasons = []
            paired = False
            for bid in scope:
                _, _, branch_reasons, branch_paired = results[bid]
                paired = paired or branch_paired
                for item in branch_reasons:
                    if item not in reasons:
                        reasons.append(item)
            reason = ", ".join(reasons) if paired and reasons else REASON_NO_FACT
        else:
            winners = [bid for bid in considered if results[bid][0] == verdict]
            deciding = winners
            for bid in winners:
                for subject in results[bid][1]:
                    if subject not in missing_subjects:
                        missing_subjects.append(subject)
            if missing_subjects:
                flags.append(FLAG_PARTIAL)

    if rejected:
        flags.append(FLAG_REJECTED)
    if checks:
        flags.append(FLAG_CHECK)
    for comp in comparisons:
        flags.extend(comp["flags"])

    return dict(
        clause_id=clause_id, family=_text(candidate.get("family")), code=_text(candidate.get("code")),
        title=_text(candidate.get("title")), numeric_status=status, verdict=verdict, reason=reason,
        missing_subjects=missing_subjects, deciding_branch_ids=list(deciding), flags=_ordered_flags(flags),
        checks=[dict(quote=_text(c.get("quote")), source=_text(c.get("source"))) for c in checks],
        branch_texts=branch_texts,
        rejected=[dict(branch_id=_text(r.get("branch_id")), subject=_text(r.get("subject")), quote=_text(r.get("quote")),
                       reason=_text(r.get("reason"))) for r in rejected],
    )


# ---------- 7.5 과제 판정 ----------

def judge(facts, candidates, pairs, families_selected, near_percent=NEAR_PERCENT):
    """목표 수치·후보 항목·매핑·고른 범위로 과제 판정을 낸다. 결과는 JudgeResult(JSON 직렬화 가능)."""
    near_percent = Decimal(str(near_percent))
    selected = {_text(f) for f in families_selected}
    result = JudgeResult(near_percent=str(near_percent))

    facts_by_id = {_text(f.get("fact_id")): f for f in facts}
    by_clause, thresholds, branches = _index_candidates(candidates, selected, result.skipped_clauses)
    valid, branch_choices = _filter_pairs(pairs, facts_by_id, by_clause, thresholds, branches, result.dropped)

    comparisons = [_compare_pair(pair, clause_id, by_clause[clause_id], branch, threshold, fact, low, high, near_percent)
                   for pair, clause_id, branch, threshold, fact, low, high in valid]
    _mark_inconsistent(comparisons)
    for comp in comparisons:
        comp["flags"] = _ordered_flags(comp["flags"])
    result.comparisons = comparisons

    comparisons_by_clause = {}
    for comp in comparisons:
        comparisons_by_clause.setdefault(comp["clause_id"], []).append(comp)
    result.clauses = [_judge_clause(candidate, comparisons_by_clause.get(clause_id, []), branch_choices.get(clause_id))
                      for clause_id, candidate in by_clause.items()]

    families = {}
    for family in _FAMILY_ORDER:
        if family not in selected:
            families[family] = FAMILY_VERDICT_EXCLUDED
            continue
        best = _highest(c["verdict"] for c in result.clauses if c["family"] == family)
        families[family] = best or FAMILY_VERDICT_NONE
    for family in sorted(selected - set(_FAMILY_ORDER)):
        # FAMILIES 밖의 이름을 골랐으면 수치 판정 없음으로 드러낸다(조용히 무시하지 않는다).
        families[family] = _highest(c["verdict"] for c in result.clauses if c["family"] == family) or FAMILY_VERDICT_NONE
    result.families = families
    result.overall = _highest(v for f, v in families.items() if f in selected) or FAMILY_VERDICT_NONE

    counts = {key: 0 for key in COUNT_KEYS}
    for clause in result.clauses:
        counts[_CLAUSE_TO_COUNT[clause["verdict"]]] += 1
    result.counts = counts
    result.flagged_clause_count = sum(1 for clause in result.clauses if clause["flags"])
    return result


__all__ = [
    "NEAR_PERCENT", "JudgeResult", "judge", "compare_values",
    "VERDICT_OVER", "VERDICT_NEAR", "VERDICT_UNDER", "VERDICT_UNIT_KIND", "VERDICT_UNIT_CONVERT", "VERDICT_ZERO",
    "COMPARISON_VERDICTS", "CLAUSE_VERDICT_NOT_COMPARABLE", "CLAUSE_VERDICT_NO_NUMERIC", "CLAUSE_VERDICTS",
    "FAMILY_VERDICT_NONE", "FAMILY_VERDICT_EXCLUDED", "FAMILY_VERDICT_STATUS", "FAMILY_VERDICTS",
    "FLAG_CHECK", "FLAG_BRANCH", "FLAG_PAIR", "FLAG_RANGE", "FLAG_PARTIAL", "FLAG_INCONSISTENT", "FLAG_EXTRACTED",
    "FLAG_REJECTED", "FLAGS", "REASON_NO_FACT", "REASON_FAILED",
    "COUNT_OVER", "COUNT_NEAR", "COUNT_UNDER", "COUNT_NOT_COMPARABLE", "COUNT_NO_NUMERIC", "COUNT_KEYS",
]
