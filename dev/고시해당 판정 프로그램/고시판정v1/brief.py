"""간단한 결과(1.4.0 spec R1·R2·R4·R7-1·R7-3): 과제 결과를 세 가지 판정 이름·과제 사유·과제 묶음·초과·근접 조항·
미달 조항·추가 검토 필요로 줄여 보이고, 실행 한 번의 종합 건수와 과제 순서를 낸다.

이 모듈은 새 판정을 만들지 않는다. 판정 엔진(judge_engine)의 값을 이름만 바꿔 보이고(R1), 숫자로 비교된 조항을
초과·근접 조항(focus)과 미달 조항(under)으로 나누고(R2), 정해진 경우의 감춘 조항을 '추가 검토 필요'(review)로
고른다. 과제 사유와 사유 문장은 정해진 틀로 이 모듈이 만들며 AI 글을 쓰지 않는다. 화면·결과 엑셀은 build_brief가
만든 사전(TaskResult.brief)과 tally_briefs의 결과를 그대로 보인다(다시 세거나 묶지 않는다).

과제 하나의 간단한 결과 — build_brief(...)가 돌려주는 사전(키 이름·순서는 BRIEF_KEYS):
    overall        종합 결과: '고시 사양 초과' | '고시 사양 근접' | '고시 사양 미달' | '오류' | '취소'
    reason         과제 사유 한 줄(R1-3). 오류·취소는 빈 글
    group          과제 묶음(R1-4): "focus"(종합 초과·근접) | "other"(종합 미달) | "unjudged"(오류·취소)
    families       {advanced|core|dual_use|military: 고시별 결과}. 고르지 않은 고시는 '대조 안 함(선택 제외)'
    hints          안내 줄 목록(의미 검색을 쓸 수 없음, 버린 최종목표 사양·매핑·선택 칸 경고 건수)
    empty_message  초과·근접 조항이 없고 상태가 오류·취소가 아니면 EMPTY_MESSAGE, 그 밖에는 빈 글
    focus          초과·근접 조항 목록. 순서: 판정(초과 → 근접) → 고시 → 판정 기록의 조항 순서
    under          미달 조항 목록. 순서: 고시 → 판정 기록의 조항 순서
    review         추가 검토 필요 목록(REVIEW_KEYS). 순서: 고시 → 판정 기록의 조항 순서
    counts         {over, near, under: 조항 수, review, hidden, detail_match_dropped}(COUNT_KEYS)
    semantic       "used" | "unavailable" | "not_needed"
조항(CLAUSE_KEYS) = {verdict(조항 판정), family, family_label, clause_id, code, title, flags(확인 표시, CLAUSE_FLAGS의
    일곱 가지만 조항 기록의 순서대로), lines(사양 줄), others}
    - focus의 조항: lines는 사양마다 한 줄(1개 이상), others는 0.
    - under의 조항: lines는 정확히 한 줄, others는 사유 문장 끝 ' · 외 N건'의 N.
사양 줄(LINE_KEYS) = {verdict(그 비교의 판정), source_field, quote, target, basis, difference, reason, display_reason}
    사유 문장(reason)에는 확인 표시를 붙이지 않는다. display_reason은 입력 인용만 QUOTE_LIMIT자에서 자른 것이다.
완료가 아닌 과제는 focus·under·review가 빈 목록이다. 공통 안내와 옛 키(notices·summary_cell·items)는 없다.

실행 한 번의 종합 건수와 과제 순서 — tally_briefs(briefs)(R4·R7-3). 일괄 결과와 결과 엑셀이 같이 쓴다:
    받는 것: 과제 결과의 brief 사전들(결과 순서 그대로).
    돌려주는 것: {"tally": [{"kind", "label", "count"}], "groups": {"focus": [...], "unjudged": [...], "other": [...]},
                  "members": {"over": [...], "near": [...], "under": [...], "unjudged": [...]}}
    - tally: kind는 TALLY_KINDS 순서("over"·"near"·"under"·"unjudged"), label은 TALLY_LABELS의 이름, count는 과제 수.
      "unjudged"(오류·취소)는 0이면 목록에 없다. 수의 합은 받은 과제 수와 같다.
    - groups: 받은 목록에서의 위치(0부터)를 보일 순서대로. focus는 종합 초과 → 종합 근접(같으면 받은 순서),
      unjudged·other는 받은 순서. 모든 과제가 정확히 한 묶음에 든다.
    - members(1.4.1): 종합 건수 항목(kind)마다 그 건수에 든 과제의 위치(받은 순서). 화면에서 건수를 눌렀을 때 보일
      과제다. 네 항목이 언제나 있고(없으면 빈 목록) 길이는 그 항목의 count와 같다.
    모르는 overall·group 값, 서로 맞지 않는 overall과 group은 ValueError(조용히 한쪽으로 세지 않는다).
    tally_text(tally)는 '{이름} {n}건'을 ' · '로 이은 한 줄이다.

- AI 선별의 detail_match(세부 기술 일치)는 '추가 검토 필요'에만 쓴다. 판정·조항 목록에는 쓰지 않는다.
- PC 안 의미 검색은 따질 조항(감춘 조항 중 이중용도가 아니고 AI가 세부 기술 일치로 답한 것)이 있을 때만 rank()를
  한 번 불러 쓴다. 쓸 수 없으면 확인하지 않고 그 사실을 안내 줄과 건수로 드러낸다(숫자를 조용히 감추지 않는다).
- 검색 글(semantic_text)은 이 모듈이 저장·기록하지 않는다. 결과 사전에는 순위·유사도를 싣지 않는다.
- 대응표에 없는 판정 값, 종합 결과와 조항이 어긋난 판정 기록, 사양 줄 규칙이 깨진 조항은 다른 값으로 바꾸지 않고
  ValueError로 드러낸다(과제 흐름이 그 과제를 '오류'로 끝낸다).

조정할 수 있는 값은 TOP_RANK(같은 고시 안 상위 기준), QUOTE_LIMIT(화면 인용 자르기), CONVERTED_DIGITS(환산 값 유효숫자).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import judge_engine as je
from pipeline import (FAMILY_LABELS, FAMILY_ORDER, STATUS_CANCELLED, STATUS_DONE, STATUS_ERROR, STATUS_NO_CANDIDATES,
                      STATUS_NO_FACTS)

# ── 조정할 수 있는 값 ────────────────────────────────────────────────────
TOP_RANK = 5          # 세부 기술 일치: PC 안 의미 검색에서 같은 고시 안 이 순위 안에 들어야 남긴다
QUOTE_LIMIT = 80      # 화면용 사유(display_reason)에서 입력 인용을 자르는 길이(글자)

# ── R1-1 간단한 결과의 판정 이름(글자 그대로) ─────────────────────────────────
VERDICT_OVER = "고시 사양 초과"
VERDICT_NEAR = "고시 사양 근접"
VERDICT_UNDER = "고시 사양 미달"
VERDICT_ERROR = "오류"
VERDICT_CANCELLED = "취소"
VERDICT_EXCLUDED = je.FAMILY_VERDICT_EXCLUDED      # 고르지 않은 고시: '대조 안 함(선택 제외)' 그대로
VERDICTS = (VERDICT_OVER, VERDICT_NEAR, VERDICT_UNDER, VERDICT_ERROR, VERDICT_CANCELLED, VERDICT_EXCLUDED)
CLAUSE_VERDICTS = (VERDICT_OVER, VERDICT_NEAR, VERDICT_UNDER)      # 조항 판정·사양 비교 결과
# R1-2 완료 과제의 고시별·종합 판정 대응표
_SIMPLE = {je.VERDICT_OVER: VERDICT_OVER, je.VERDICT_NEAR: VERDICT_NEAR, je.VERDICT_UNDER: VERDICT_UNDER,
           je.FAMILY_VERDICT_NONE: VERDICT_UNDER, je.FAMILY_VERDICT_EXCLUDED: VERDICT_EXCLUDED}
# 조항 판정·비교 판정 대응표(숫자로 비교된 것만)
_COMPARED = {je.VERDICT_OVER: VERDICT_OVER, je.VERDICT_NEAR: VERDICT_NEAR, je.VERDICT_UNDER: VERDICT_UNDER}
# 판정 엔진을 거치지 않은 상태의 고른 고시·종합 결과
_STATUS_VERDICT = {STATUS_NO_CANDIDATES: VERDICT_UNDER, STATUS_NO_FACTS: VERDICT_UNDER, STATUS_ERROR: VERDICT_ERROR,
                   STATUS_CANCELLED: VERDICT_CANCELLED}

# ── R1-3 과제 사유 ──────────────────────────────────────────────────────
REASON_MORE = " 외 {}건"                               # 첫 초과·근접 조항 이름 뒤: 나머지 초과·근접 조항 수
REASON_UNDER = "기준에 못 미침"                        # 완료, 숫자로 비교된 조항이 있고 모두 미달
REASON_NO_OVERLAP = "사양이 겹치는 고시 조항 없음"      # 완료, 숫자로 비교된 조항이 없음
REASON_NO_CANDIDATES = "관련 고시 조항 없음"           # 관련 고시 항목 없음
REASON_NO_FACTS = "최종목표 수치 없음"                 # 목표 수치 없음
_STATUS_REASON = {STATUS_NO_CANDIDATES: REASON_NO_CANDIDATES, STATUS_NO_FACTS: REASON_NO_FACTS, STATUS_ERROR: "",
                  STATUS_CANCELLED: ""}

# ── R1-4 과제 묶음 ──────────────────────────────────────────────────────
GROUP_FOCUS = "focus"          # 중점: 종합이 초과·근접
GROUP_OTHER = "other"          # 그 밖: 종합이 미달
GROUP_UNJUDGED = "unjudged"    # 판정 못 함: 종합이 오류·취소
GROUPS = (GROUP_FOCUS, GROUP_OTHER, GROUP_UNJUDGED)

# ── R4 종합 건수 ────────────────────────────────────────────────────────
TALLY_OVER, TALLY_NEAR, TALLY_UNDER, TALLY_UNJUDGED = "over", "near", "under", "unjudged"
TALLY_KINDS = (TALLY_OVER, TALLY_NEAR, TALLY_UNDER, TALLY_UNJUDGED)
TALLY_LABELS = {TALLY_OVER: VERDICT_OVER, TALLY_NEAR: VERDICT_NEAR, TALLY_UNDER: VERDICT_UNDER,
                TALLY_UNJUDGED: "오류·취소(판정 없음)"}
TALLY_ITEM_TEXT = "{} {}건"      # 표시: '{이름} {n}건'
TALLY_SEPARATOR = " · "
# 종합 결과 → (종합 건수 항목, 과제 묶음). 오류·취소는 어떤 건수에서도 미달에 넣지 않는다.
_OVERALL_TALLY = {VERDICT_OVER: (TALLY_OVER, GROUP_FOCUS), VERDICT_NEAR: (TALLY_NEAR, GROUP_FOCUS),
                  VERDICT_UNDER: (TALLY_UNDER, GROUP_OTHER), VERDICT_ERROR: (TALLY_UNJUDGED, GROUP_UNJUDGED),
                  VERDICT_CANCELLED: (TALLY_UNJUDGED, GROUP_UNJUDGED)}

# ── semantic 값 ───────────────────────────────────────────────────────
SEMANTIC_USED = "used"
SEMANTIC_UNAVAILABLE = "unavailable"
SEMANTIC_NOT_NEEDED = "not_needed"

# ── 안내 줄·빈 목록 문구 ─────────────────────────────────────────────────
HINT_SEMANTIC_UNAVAILABLE = "의미 검색을 쓸 수 없어 세부 기술 일치 확인 안 함"
HINT_DROPPED = "버린 최종목표 사양·매핑 {}건"
HINT_OPTION_WARNINGS = "선택 칸 경고 {}건"
HINT_COUNT_TAIL = " — 상세 보기에서 확인"
EMPTY_MESSAGE = "고시 사양을 초과하거나 근접한 조항 없음"
# 개별 검토의 진행 표시 글(기존 단계 '관련 고시 조항 선별'의 이벤트로 보낸다)
PROGRESS_MESSAGE = "세부 기술 일치 확인 중"

# ── R2-3·R2-4 사유 ────────────────────────────────────────────────────
OPERATOR_LABELS = {"ge": "이상", "gt": "초과", "le": "이하", "lt": "미만"}   # excel_report·notice_search와 같은 낱말
# 차이 표현(1.4.2): 판정 이름과 같은 낱말 '초과/미달'로 적는다. 옛 문구 '기준 충족(여유 N%)'·'기준에 N% 못 미침'은 쓰지 않는다
DIFFERENCE_MET = "기준보다 {}% 초과"
DIFFERENCE_MET_ZERO = "기준 초과"
DIFFERENCE_SHORT = "기준보다 {}% 미달"
DIFFERENCE_EQUAL = "기준값과 같음(같은 값은 초과 아님)"
OTHERS_TAIL = " · 외 {}건"       # 미달 조항의 사유 문장 끝: 같은 조항의 다른 초과·근접·미달 비교 수
# R2-5 조항에 붙여 보이는 확인 표시 일곱 가지(조항 기록의 순서 = 판정 엔진의 확인 표시 순서). 사유 문장 끝에는 붙이지
# 않는다. 'AI가 읽은 기준값(원문 확인 필요)'은 거의 모든 조항에 해당해 앞쪽 결과에 보이지 않는다(상세에는 그대로 있다).
CLAUSE_FLAGS = (je.FLAG_CHECK, je.FLAG_BRANCH, je.FLAG_PAIR, je.FLAG_RANGE, je.FLAG_PARTIAL, je.FLAG_INCONSISTENT,
                je.FLAG_REJECTED)

# ── 추가 검토 필요 ─────────────────────────────────────────────────────
KEPT_DUAL_USE = "이중용도 관련(AI 선별)"
KEPT_DETAIL_MATCH = "세부 기술 일치(AI·검색)"
WHY_NO_NUMERIC = "숫자 기준 없음"
WHY_NO_FACT = "맞는 최종목표 수치 없음"
WHY_UNIT = "단위 비교 불가"
WHY_ZERO = "기준값 0 비교 불가"
WHY_FAILED = "기준값 채택 실패(원문 확인 필요)"
WHY_ORDER = (WHY_NO_FACT, WHY_UNIT, WHY_ZERO, WHY_FAILED)
_WHY_BY_REASON = {je.REASON_NO_FACT: WHY_NO_FACT, je.VERDICT_UNIT_KIND: WHY_UNIT, je.VERDICT_UNIT_CONVERT: WHY_UNIT,
                  je.VERDICT_ZERO: WHY_ZERO, je.REASON_FAILED: WHY_FAILED}
DUAL_USE = "dual_use"
DETAIL_MATCH_FAMILIES = ("advanced", "core", "military")   # 세부 기술 일치(AI·검색)를 따지는 고시

# ── R7-1 키(이름과 순서) ─────────────────────────────────────────────────
BRIEF_KEYS = ("overall", "reason", "group", "families", "hints", "empty_message", "focus", "under", "review", "counts",
              "semantic")
CLAUSE_KEYS = ("verdict", "family", "family_label", "clause_id", "code", "title", "flags", "lines", "others")
LINE_KEYS = ("verdict", "source_field", "quote", "target", "basis", "difference", "reason", "display_reason")
REVIEW_KEYS = ("family", "family_label", "clause_id", "code", "title", "kept_because", "why", "reason")
COUNT_KEYS = ("over", "near", "under", "review", "hidden", "detail_match_dropped")

_RANK = {je.VERDICT_OVER: 3, je.VERDICT_NEAR: 2, je.VERDICT_UNDER: 1}
_FOCUS_ORDER = {je.VERDICT_OVER: 0, je.VERDICT_NEAR: 1}

__all__ = [
    "TOP_RANK", "QUOTE_LIMIT", "CONVERTED_DIGITS", "VERDICT_OVER", "VERDICT_NEAR", "VERDICT_UNDER", "VERDICT_ERROR",
    "VERDICT_CANCELLED", "VERDICT_EXCLUDED", "VERDICTS", "CLAUSE_VERDICTS", "REASON_MORE", "REASON_UNDER",
    "REASON_NO_OVERLAP", "REASON_NO_CANDIDATES", "REASON_NO_FACTS", "GROUP_FOCUS", "GROUP_OTHER", "GROUP_UNJUDGED", "GROUPS",
    "TALLY_OVER", "TALLY_NEAR", "TALLY_UNDER", "TALLY_UNJUDGED", "TALLY_KINDS", "TALLY_LABELS", "TALLY_ITEM_TEXT",
    "TALLY_SEPARATOR", "SEMANTIC_USED", "SEMANTIC_UNAVAILABLE", "SEMANTIC_NOT_NEEDED", "HINT_SEMANTIC_UNAVAILABLE",
    "HINT_DROPPED", "HINT_OPTION_WARNINGS", "HINT_COUNT_TAIL", "EMPTY_MESSAGE", "PROGRESS_MESSAGE", "OPERATOR_LABELS",
    "DIFFERENCE_MET", "DIFFERENCE_MET_ZERO", "DIFFERENCE_SHORT", "DIFFERENCE_EQUAL", "OTHERS_TAIL", "CLAUSE_FLAGS",
    "KEPT_DUAL_USE", "KEPT_DETAIL_MATCH", "WHY_NO_NUMERIC", "WHY_NO_FACT", "WHY_UNIT", "WHY_ZERO", "WHY_FAILED", "WHY_ORDER",
    "DETAIL_MATCH_FAMILIES", "BRIEF_KEYS", "CLAUSE_KEYS", "LINE_KEYS", "REVIEW_KEYS", "COUNT_KEYS",
    "simple_verdict", "format_number", "format_converted", "difference_text", "display_quote", "semantic_text",
    "clause_name", "build_brief", "tally_briefs", "tally_text",
]


# ── 작은 도우미 ────────────────────────────────────────────────────────

def simple_verdict(value):
    """판정 엔진의 고시별·종합 판정 → R1-1 이름. 대응표에 없는 값은 ValueError(조용히 바꾸지 않는다)."""
    try:
        return _SIMPLE[value]
    except (KeyError, TypeError):
        raise ValueError(f"간단한 결과로 바꿀 수 없는 판정 값: {value!r}") from None


def _compared_verdict(value):
    """조항 판정·비교 판정(초과·근접·미달) → R1-1 이름. 그 밖의 값은 ValueError."""
    try:
        return _COMPARED[value]
    except (KeyError, TypeError):
        raise ValueError(f"숫자로 비교된 판정 값이 아니다: {value!r}") from None


def format_number(value):
    """기준값·환산한 값의 표시: 지수 표기 없이, 정수 부분은 세 자리마다 쉼표, 소수 끝의 0은 지운다.

    예: '3E+6' → '3,000,000', '500.0' → '500', '0.950' → '0.95'. 10진수가 아닌 글은 그대로 돌려준다.
    """
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    if number == 0:
        return "0"
    text = format(number, "f")
    sign = "-" if text.startswith("-") else ""
    whole, _, fraction = text.lstrip("-").partition(".")
    fraction = fraction.rstrip("0")
    return f"{sign}{int(whole):,}" + (f".{fraction}" if fraction else "")


CONVERTED_DIGITS = 4   # 간단한 결과의 환산 값 유효숫자(조정 가능). 판정 계산과 상세의 환산 값은 그대로다.


def format_converted(value, digits=None):
    """간단한 결과의 환산 값 표시(사용자 결정 2026-11-10): 유효숫자 digits자리로 줄이고, 줄여서 값이 달라졌으면 '약 '.

    예: '107.99999999999999136' → '약 108', '0.95' → '0.95', '1234567' → '약 1,235,000'. 10진수가 아닌 글은 그대로.
    """
    digits = CONVERTED_DIGITS if digits is None else digits
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite() or number == 0:
        return format_number(value)
    exponent = number.adjusted() - digits + 1
    rounded = number.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)
    text = format_number(rounded)
    return text if rounded == number else f"약 {text}"


def display_quote(quote, limit=None):
    """화면용 인용: limit자(기본 QUOTE_LIMIT)보다 길면 앞 limit자 뒤에 '…'."""
    limit = QUOTE_LIMIT if limit is None else limit
    quote = str(quote)
    return quote if len(quote) <= limit else quote[:limit] + "…"


def difference_text(comparison):
    """비교 하나의 차이 표현. 비교어 방향과 관계없이 '초과/미달'(고시 사양을 넘었는지 못 미쳤는지)로 적는다.
    N은 기존 차이 % 표시와 같은 반올림."""
    verdict = comparison.get("verdict")
    display = comparison.get("gap_percent_display")
    if verdict == je.VERDICT_OVER:
        if display is None:          # 기준값 0을 충족: 차이를 계산할 수 없다
            return DIFFERENCE_MET_ZERO
        return DIFFERENCE_MET.format(str(display).lstrip("-"))
    if verdict in (je.VERDICT_NEAR, je.VERDICT_UNDER):
        if Decimal(str(comparison.get("gap_percent"))) == 0:     # 초과·미만 기준에서 같은 값
            return DIFFERENCE_EQUAL
        return DIFFERENCE_SHORT.format(display)
    raise ValueError(f"차이 표현을 만들 수 없는 비교 판정: {verdict!r}")


def semantic_text(task):
    """PC 안 의미 검색 글: 연구개발과제명 + 최종목표 + 연구개발내용을 줄바꿈으로 잇는다.

    최종목표와 연구개발내용이 모두 비어 있으면(첨부 목표 발췌로만 검토) 연구개발과제명 + 목표 발췌. 빈 칸은 뺀다.
    이 글은 PC 안에서 벡터로만 바꾸며 어디에도 저장·기록하지 않는다.
    """
    def text(key):
        return str(task.get(key) or "").strip()
    title, final_goal, content = text("title"), text("final_goal"), text("rnd_content")
    parts = (title, final_goal, content) if (final_goal or content) else (title, text("excerpt"))
    return "\n".join(part for part in parts if part)


def _family_rank(family):
    return FAMILY_ORDER.index(family) if family in FAMILY_ORDER else len(FAMILY_ORDER)


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name}은(는) 0 이상 정수여야 한다: {value!r}")
    return value


# ── R2 조항과 사양 줄 ───────────────────────────────────────────────────

def _best(comparisons):
    """같은 기준의 비교 중 가장 높은 판정(같으면 판정 기록 순서상 앞). 숫자로 비교한 것이 없으면 None."""
    best = None
    for comp in comparisons:
        if comp.get("verdict") in _RANK and (best is None or _RANK[comp["verdict"]] > _RANK[best["verdict"]]):
            best = comp
    return best


def _threshold_order(record, branch_id, comparisons):
    """갈래 안 기준 순서: 표 기록의 순서. 기록이 없으면 판정 기록에 처음 나온 순서."""
    if record is not None:
        for branch in record.get("branches", []):
            if branch.get("branch_id") == branch_id:
                return [threshold.get("threshold_id") for threshold in branch.get("thresholds", [])]
    return list(dict.fromkeys(c["threshold_id"] for c in comparisons if c.get("branch_id") == branch_id))


def _by_threshold(comparisons):
    grouped = {}
    for comp in comparisons:
        grouped.setdefault(comp["threshold_id"], []).append(comp)
    return grouped


def _deciding_bests(clause, comparisons, record):
    """판정을 정한 갈래를 갈래 순서대로, 갈래 안 기준을 기준 순서대로 보며 기준마다 가장 높은 판정의 비교를 낸다.
    숫자로 비교된 것이 없는 기준은 건너뛴다."""
    grouped = _by_threshold(comparisons)
    for branch_id in clause["deciding_branch_ids"]:
        for threshold_id in _threshold_order(record, branch_id, comparisons):
            best = _best(grouped.get(threshold_id, []))
            if best is not None:
                yield best


def _reason_comparison(clause, comparisons, record):
    """미달 조항의 사유에 쓰는 비교 하나(R2-4): 판정을 정한 갈래 → 갈래 안 기준 순서로 보며, 기준마다 가장 높은 판정의
    비교를 고르고, 그 판정이 조항 판정과 같은 첫 비교."""
    for best in _deciding_bests(clause, comparisons, record):
        if best["verdict"] == clause["verdict"]:
            return best
    raise ValueError(f"고시 조항 {clause['clause_id']}의 사유에 쓸 비교를 찾지 못했다")


def _target(value_text, unit):
    """최종목표 사양: 원문 값 글과 단위. 값 글이 이미 그 단위로 끝나면 단위를 다시 붙이지 않는다."""
    value_text, unit = str(value_text or "").strip(), str(unit or "").strip()
    if not unit or value_text.endswith(unit):
        return value_text
    return f"{value_text} {unit}"


def _basis(comp):
    """고시 기준 사양: '{물리량} {값}{단위} {비교어}', 단위를 환산해 비교했으면 ' (환산 {값} {기준 단위})'."""
    unit = comp.get("threshold_unit", "")
    text = (f"{comp.get('subject', '')} {format_number(comp.get('threshold_value'))}{unit} "
            f"{OPERATOR_LABELS.get(comp.get('operator'), comp.get('operator'))}")
    if comp.get("converted_value") is not None and comp.get("fact_unit") != unit:
        text += f" (환산 {format_converted(comp['converted_value'])} {unit})"
    return text


def _sentence(source_field, quote, basis, difference, tail):
    return f'{source_field} "{quote}" ↔ 기준 {basis}, {difference}{tail}'


def _line(comp, raw_units, tail=""):
    """비교 하나의 사양 줄(LINE_KEYS). tail은 미달 조항의 ' · 외 N건'(초과·근접 조항의 줄에는 없다)."""
    source_field, quote = comp.get("source_field", ""), comp.get("fact_quote", "")
    basis, difference = _basis(comp), difference_text(comp)
    return dict(
        verdict=_compared_verdict(comp.get("verdict")), source_field=source_field, quote=quote,
        target=_target(comp.get("value_text"), raw_units.get(comp.get("fact_id"), comp.get("fact_unit"))),
        basis=basis, difference=difference,
        reason=_sentence(source_field, quote, basis, difference, tail),
        display_reason=_sentence(source_field, display_quote(quote), basis, difference, tail),
    )


def _focus_lines(clause, comparisons, record, raw_units):
    """초과·근접 조항의 사양 줄(R2-3): 판정을 정한 갈래의 기준마다 가장 높은 판정의 비교 하나씩.

    고른 비교는 초과 아니면 근접이어야 한다. 미달이 나오거나 줄이 하나도 없으면 규칙이 깨진 것이므로 ValueError.
    """
    lines = []
    for best in _deciding_bests(clause, comparisons, record):
        if best["verdict"] not in _FOCUS_ORDER:
            raise ValueError(f"고시 조항 {clause['clause_id']}: 판정을 정한 갈래의 사양 비교가 초과·근접이 아니다"
                             f"({best['verdict']!r}, 기준 {best.get('threshold_id')!r})")
        lines.append(_line(best, raw_units))
    if not lines:
        raise ValueError(f"고시 조항 {clause['clause_id']}: 초과·근접 조항인데 보일 사양 줄이 없다")
    return lines


def _clause(clause, comparisons, record, raw_units):
    """숫자로 비교된 조항 하나(CLAUSE_KEYS). 초과·근접 조항은 사양마다 한 줄, 미달 조항은 한 줄과 others."""
    verdict = _compared_verdict(clause["verdict"])
    if clause["verdict"] in _FOCUS_ORDER:
        lines, others = _focus_lines(clause, comparisons, record, raw_units), 0
    else:
        chosen = _reason_comparison(clause, comparisons, record)
        others = sum(1 for comp in comparisons if comp.get("verdict") in _RANK) - 1
        lines = [_line(chosen, raw_units, OTHERS_TAIL.format(others) if others else "")]
    family = clause.get("family", "")
    return dict(
        verdict=verdict, family=family, family_label=FAMILY_LABELS.get(family, family),
        clause_id=clause.get("clause_id", ""), code=clause.get("code", ""), title=clause.get("title", ""),
        flags=[flag for flag in clause.get("flags", []) if flag in CLAUSE_FLAGS], lines=lines, others=others,
    )


# ── 추가 검토 필요 ─────────────────────────────────────────────────────

def _why(clause):
    """비교하지 못한 이유. 수치 비교 불가는 조항 기록 사유의 이유마다 정해진 낱말로, 정해진 순서로 잇는다."""
    if clause.get("verdict") == je.CLAUSE_VERDICT_NO_NUMERIC:
        return WHY_NO_NUMERIC
    found, unknown = set(), []
    for part in str(clause.get("reason") or "").split(", "):
        part = part.strip()
        if not part:
            continue
        if part in _WHY_BY_REASON:
            found.add(_WHY_BY_REASON[part])
        elif part not in unknown:
            unknown.append(part)          # 모르는 사유는 버리지 않고 원래 글로 보인다
    parts = [why for why in WHY_ORDER if why in found] + unknown
    return " · ".join(parts) if parts else str(clause.get("verdict", ""))


def _review(clause):
    family = clause.get("family", "")
    kept = KEPT_DUAL_USE if family == DUAL_USE else KEPT_DETAIL_MATCH
    why = _why(clause)
    return dict(family=family, family_label=FAMILY_LABELS.get(family, family), clause_id=clause.get("clause_id", ""),
                code=clause.get("code", ""), title=clause.get("title", ""), kept_because=kept, why=why,
                reason=f"{kept}, {why}")


def _rank_once(targets, rank):
    """따질 조항이 있을 때만 의미 검색 순위를 한 번 구한다. 돌려주는 것: (semantic 값, 고시별 순위 또는 None)."""
    if not targets:
        return SEMANTIC_NOT_NEEDED, None
    if rank is None:
        return SEMANTIC_UNAVAILABLE, None
    try:
        result = rank()
    except Exception:   # noqa: BLE001 — 모델을 불러오지 못하거나 계산 중 오류: 확인하지 않고 '쓸 수 없음'으로 드러낸다
        return SEMANTIC_UNAVAILABLE, None
    ranking = result.get("ranking") if isinstance(result, dict) and result.get("available") is True else None
    if not isinstance(ranking, dict) or any(not isinstance(ranking.get(c["family"]), list) for c in targets):
        return SEMANTIC_UNAVAILABLE, None
    return SEMANTIC_USED, ranking


def _select(judge, decisions, records, facts, rank):
    """완료 과제의 (초과·근접 조항, 미달 조항, 추가 검토 필요, 건수, semantic)."""
    clauses = list(judge.get("clauses", []))
    comparisons = {}
    for comp in judge.get("comparisons", []):
        comparisons.setdefault(comp["clause_id"], []).append(comp)
    records_by_id = {record.get("clause_id"): record for record in records}
    raw_units = {f.get("fact_id"): f.get("unit") or "" for f in facts}

    def build(clause):
        return _clause(clause, comparisons.get(clause["clause_id"], []), records_by_id.get(clause["clause_id"]), raw_units)

    # R2-2 순서(안정 정렬). 초과·근접: 판정 → 고시 → 판정 기록의 조항 순서. 미달: 고시 → 판정 기록의 조항 순서.
    focus = [build(c) for c in sorted((c for c in clauses if c["verdict"] in _FOCUS_ORDER),
                                      key=lambda c: (_FOCUS_ORDER[c["verdict"]], _family_rank(c.get("family"))))]
    under = [build(c) for c in sorted((c for c in clauses if c["verdict"] == je.VERDICT_UNDER),
                                      key=lambda c: _family_rank(c.get("family")))]

    detail = {d.get("clause_id") for d in decisions if d.get("candidate") is True and d.get("detail_match") is True}
    hidden_clauses = [c for c in clauses if c["verdict"] not in _RANK]
    targets = [c for c in hidden_clauses if c.get("family") in DETAIL_MATCH_FAMILIES and c["clause_id"] in detail]
    semantic, ranking = _rank_once(targets, rank)
    kept = set()
    if semantic == SEMANTIC_USED:
        kept = {c["clause_id"] for c in targets if c["clause_id"] in ranking[c["family"]][:TOP_RANK]}
    review_clauses = [c for c in hidden_clauses if c.get("family") == DUAL_USE or c["clause_id"] in kept]
    review_clauses.sort(key=lambda c: _family_rank(c.get("family")))
    review = [_review(c) for c in review_clauses]

    # AI 선별 조항: 선별 결정의 후보(표에 없어 판정하지 못한 후보 포함)와 판정 기록의 조항.
    candidates = [d.get("clause_id") for d in decisions if d.get("candidate") is True] + [c["clause_id"] for c in clauses]
    shown_ids = {entry["clause_id"] for entry in focus + under + review}
    counts = dict(over=sum(1 for c in focus if c["verdict"] == VERDICT_OVER),
                  near=sum(1 for c in focus if c["verdict"] == VERDICT_NEAR), under=len(under), review=len(review),
                  hidden=sum(1 for cid in dict.fromkeys(candidates) if cid not in shown_ids),
                  detail_match_dropped=len(targets) - len(kept))
    return focus, under, review, counts, semantic


# ── R1-3 과제 사유 ──────────────────────────────────────────────────────

def clause_name(clause):
    """'{고시 이름} {통제번호} {고시 조항명}'. 통제번호가 없으면 뺀다. 조항(초과·근접·미달)과 추가 검토 필요 원소 모두에 쓴다
    (과제 사유와 결과 엑셀 '추가 검토 필요' 칸이 같은 함수를 쓴다)."""
    return " ".join(part for part in (clause["family_label"], clause["code"], clause["title"]) if part)


def _done_reason(focus, under):
    if focus:
        more = len(focus) - 1
        return clause_name(focus[0]) + (REASON_MORE.format(more) if more else "")
    return REASON_UNDER if under else REASON_NO_OVERLAP


# ── 과제 하나의 간단한 결과 ─────────────────────────────────────────────

def build_brief(status, families_selected, judge=None, *, decisions=(), records=(), facts=(), dropped_count=0,
                option_warning_count=0, rank=None):
    """과제 결과 하나의 간단한 결과 사전(spec R7-1 모양, 키는 BRIEF_KEYS — 모듈 머리말 참고).

    status: 과제 상태(pipeline.STATUSES). families_selected: 고른 고시. judge: 완료 과제의 판정 기록(JudgeResult.to_dict()).
    decisions: AI 선별 결정 [{clause_id, candidate, detail_match, reason}]. records: 판정에 넣은 표 기록(갈래 안 기준
    순서에 쓴다). facts: 최종목표 사양(원문 단위에 쓴다). dropped_count: 버린 최종목표 사양·매핑 수.
    option_warning_count: 그 과제의 선택 칸 경고 수(건수 안내에만 쓴다). rank: 인자 없는 함수로 의미 검색 결과
    {available, reason, ranking}를 돌려준다(검색 엔진이 없으면 None). 따질 조항이 있을 때만 한 번 부른다.
    완료가 아닌 과제는 판정 기록·선별 결정을 보지 않는다(초과·근접 조항·미달 조항·추가 검토 필요는 빈 목록).
    대응표에 없는 판정 값, 종합 결과와 조항 판정이 어긋난 판정 기록, 사양 줄 규칙이 깨진 조항은 ValueError.
    """
    selected = {str(f) for f in families_selected}
    dropped_count = _count(dropped_count, "dropped_count")
    option_warning_count = _count(option_warning_count, "option_warning_count")
    hints, focus, under, review = [], [], [], []
    counts = {key: 0 for key in COUNT_KEYS}
    semantic = SEMANTIC_NOT_NEEDED
    if status == STATUS_DONE:
        if not judge:
            raise ValueError("완료 상태에는 판정 기록이 있어야 한다")
        families = {family: simple_verdict(judge["families"][family]) for family in FAMILY_ORDER}
        overall = simple_verdict(judge["overall"])
        focus, under, review, counts, semantic = _select(judge, list(decisions), list(records), list(facts), rank)
        # 종합 결과는 조항 판정 중 가장 높은 것이어야 한다. 어긋나면 과제 묶음·사유·건수가 서로 다른 말을 하게 된다.
        expected = VERDICT_OVER if counts["over"] else VERDICT_NEAR if counts["near"] else VERDICT_UNDER
        if overall != expected:
            raise ValueError(f"종합 결과({overall})가 조항 판정(초과 {counts['over']}·근접 {counts['near']}·"
                             f"미달 {counts['under']})과 어긋난다")
        reason = _done_reason(focus, under)
    elif status in _STATUS_VERDICT:
        overall = _STATUS_VERDICT[status]
        families = {family: overall if family in selected else VERDICT_EXCLUDED for family in FAMILY_ORDER}
        reason = _STATUS_REASON[status]
    else:
        raise ValueError(f"과제 상태 값이 아니다: {status!r}")
    group = _OVERALL_TALLY[overall][1]
    if semantic == SEMANTIC_UNAVAILABLE:
        hints.append(HINT_SEMANTIC_UNAVAILABLE)
    parts = []
    if dropped_count:
        parts.append(HINT_DROPPED.format(dropped_count))
    if option_warning_count:
        parts.append(HINT_OPTION_WARNINGS.format(option_warning_count))
    if parts:
        hints.append(" · ".join(parts) + HINT_COUNT_TAIL)
    empty = EMPTY_MESSAGE if not focus and group != GROUP_UNJUDGED else ""
    return dict(overall=overall, reason=reason, group=group, families=families, hints=hints, empty_message=empty,
                focus=focus, under=under, review=review, counts=counts, semantic=semantic)


# ── R4·R7-3 실행 한 번의 종합 건수와 과제 순서 ──────────────────────────────────

def tally_briefs(briefs):
    """과제 결과의 brief 목록 → 종합 건수와 묶음별 과제 순서(일괄 결과와 결과 엑셀이 같이 쓴다).

    돌려주는 것: dict(tally=[dict(kind, label, count)], groups=dict(focus=[...], unjudged=[...], other=[...]),
    members=dict(over=[...], near=[...], under=[...], unjudged=[...])).
    - tally는 TALLY_KINDS 순서. 'unjudged'(오류·취소)는 0이면 뺀다. count의 합은 받은 과제 수와 같다.
    - groups의 값은 받은 목록에서의 위치(0부터). focus는 종합 초과 → 종합 근접(같으면 받은 순서),
      unjudged·other는 받은 순서. 모든 과제가 정확히 한 묶음에 든다.
    - members는 종합 건수 항목마다 그 건수에 든 과제의 위치(받은 순서). 네 항목이 언제나 있고 길이는 count와 같다.
    brief가 사전이 아니거나, 모르는 overall·group 값이거나, overall과 group이 맞지 않으면 ValueError
    (조용히 한쪽으로 세지 않는다). 받은 목록은 바꾸지 않는다.
    """
    briefs = list(briefs)
    counts = {kind: 0 for kind in TALLY_KINDS}
    positions = {kind: [] for kind in TALLY_KINDS}
    for position, item in enumerate(briefs):
        if not isinstance(item, dict):
            raise ValueError(f"{position}번째 과제에 간단한 결과가 없다: {type(item).__name__}")
        overall, group = item.get("overall"), item.get("group")
        if not isinstance(group, str) or group not in GROUPS:
            raise ValueError(f"{position}번째 과제의 묶음 값을 모른다: {group!r}")
        if not isinstance(overall, str) or overall not in _OVERALL_TALLY:
            raise ValueError(f"{position}번째 과제의 종합 결과 값을 모른다: {overall!r}")
        kind, expected_group = _OVERALL_TALLY[overall]
        if group != expected_group:
            raise ValueError(f"{position}번째 과제의 종합 결과({overall})와 묶음({group})이 맞지 않는다")
        counts[kind] += 1
        positions[kind].append(position)
    groups = {GROUP_FOCUS: positions[TALLY_OVER] + positions[TALLY_NEAR], GROUP_UNJUDGED: positions[TALLY_UNJUDGED],
              GROUP_OTHER: positions[TALLY_UNDER]}
    if sum(counts.values()) != len(briefs) or sum(len(group) for group in groups.values()) != len(briefs):
        raise ValueError(f"종합 건수의 합({sum(counts.values())})이 과제 수({len(briefs)})와 다르다")
    tally = [dict(kind=kind, label=TALLY_LABELS[kind], count=counts[kind]) for kind in TALLY_KINDS
             if kind != TALLY_UNJUDGED or counts[kind]]
    members = {kind: list(positions[kind]) for kind in TALLY_KINDS}
    return dict(tally=tally, groups=groups, members=members)


def tally_text(tally):
    """종합 건수(tally_briefs의 tally) → '{이름} {n}건'을 ' · '로 이은 한 줄.

    예: '고시 사양 초과 2건 · 고시 사양 근접 1건 · 고시 사양 미달 6건'. 모르는 kind나 0 이상 정수가 아닌 count는 ValueError.
    """
    parts = []
    for entry in tally:
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if not isinstance(kind, str) or kind not in TALLY_LABELS:
            raise ValueError(f"종합 건수 항목 값을 모른다: {kind!r}")
        parts.append(TALLY_ITEM_TEXT.format(TALLY_LABELS[kind], _count(entry.get("count"), "종합 건수")))
    return TALLY_SEPARATOR.join(parts)
