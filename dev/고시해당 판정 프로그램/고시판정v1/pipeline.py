"""한 과제 흐름(spec 5.1·7.6·7.7): 입력 확인 → 최종목표 사양 추출 → 관련 고시 조항 선별 → 매핑 → 판정 엔진.

이 모듈은 AI 단계(ai_stages)와 판정 엔진(judge_engine)을 잇기만 한다. 판정 계산은 judge_engine만 한다.
파일을 열지 않는다. 사용자가 확인한 발췌 글(task["excerpt"])만 받아 그대로 AI 단계에 넘긴다.
모델 클라이언트는 주입받으며(`client.ask_json(system, user_json_text, temperature=0)`), 키는 이 모듈에 들어오지 않는다.

과제 입력(키 → 화면·양식 이름):
    title        연구개발과제명(필수)
    final_goal   최종목표          ┐ 과제요약정보 세 칸. 확인한 목표 발췌가 없으면 셋 다 필수,
    rnd_content  연구개발내용      │ 있으면 선택(적은 칸은 함께 쓴다).
    utilization  활용계획 및 기대효과 ┘
    excerpt      확인한 목표 발췌(첨부에서 사용자가 확인한 글). 비어 있으면 첨부가 없는 것과 같다.
    attachment_name  첨부 파일 이름. 발췌가 있을 때만 '입력 정보'에 쓴다.
    rnd_stage    연구개발단계(선택, 정식 이름 기초연구·응용연구·개발연구 또는 빈 글)
    gov_fund     정부지원연구개발비(백만원, 선택, 0보다 큰 10진수 글 또는 빈 글)
    row_number   일괄 검토의 입력 행 번호(개별 검토는 None)
연구개발단계·정부지원연구개발비는 결과에 싣기만 하고 AI 단계·판정에는 넘기지 않는다.
두 선택 칸의 정리 규칙은 normalize_rnd_stage·normalize_gov_fund 한 곳에 있고, 일괄 읽기(batch)와 화면 연결 함수
(bridge)가 같이 쓴다. 잘못된 값은 빈칸으로 두고 행 번호·원래 값을 담은 경고를 돌려준다(조용히 바꾸지 않는다).

과제 상태(7.6, 값 문자열은 그대로):
    완료              모든 단계를 거쳐 judge 결과가 있다.
    목표 수치 없음    최종 목표 수치를 찾지 못해 고시 대조를 하지 않았다(선별·매핑 호출 0).
    관련 고시 항목 없음  검토 대상 고시에서 관련 고시 조항이 없다. 공인 비해당이 아니다.
    오류              StageError·AI 실패·형식 오류·예외. 사유를 error_reason에 남긴다.
    취소              일괄 검토에서 시작하지 않은 행(batch가 cancelled_result()로 만듦)과, 취소 뒤 AI 요청이 거부되어 끝나지 못한 행(CancelledError).
고시별·종합 검토 결과(7.7): 완료는 judge 결과대로, 관련 고시 항목 없음은 고른 고시가 '수치 판정 없음', 그 밖의 상태는
고른 고시가 '판정 안 함(상태 참고)'. 고르지 않은 고시는 언제나 '대조 안 함(선택 제외)'.

간단한 결과(brief 모듈, 1.4.0 모양): 모든 상태의 결과에 `brief`가 있다. 종합 결과(고시 사양 초과·근접·미달, 오류, 취소)·
과제 사유·과제 묶음·초과·근접 조항·미달 조항·추가 검토 필요·건수를 담으며, 판정 이름 대응·사유·묶음·조항 고르기는
모두 brief 모듈이 한다(이 모듈의 과제 상태와 위 내부 판정 값은 그대로다 — 목표 수치 없음·관련 고시 항목 없음 과제는
brief에서만 '고시 사양 미달'로 보인다). brief를 만들다 난 예외(대응표에 없는 판정 값, 사양 줄 규칙이 깨진 조항)는
그 과제를 '오류'로 끝낸다. 완료 과제는 선별 결정의 detail_match와(따질 조항이 있을 때만) PC 안 의미 검색 순위로
'추가 검토 필요'를 고른다. 검색 엔진(search_engine)과 그 과제의 선택 칸 경고(option_warnings)는 선택 인자다.
선택 칸 경고는 건수 안내에만 쓰고 AI 단계·판정에는 넘기지 않는다. 의미 검색 글은 PC 안에서만 쓰고 결과에 담지 않는다.
실행 한 번의 종합 건수와 과제 순서는 brief.tally_briefs가 과제 결과의 brief 목록으로 낸다(이 모듈은 세지 않는다).
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import copy
import math
import re

import judge_engine as je
from ai_stages import STAGE_SCREEN, CallCounter, StageError, extract_goal_facts, pair_facts, screen_candidates, screen_index
from paths import PROGRAM_NAME, PROGRAM_VERSION

STATUS_DONE = "완료"
STATUS_NO_FACTS = "목표 수치 없음"
STATUS_NO_CANDIDATES = "관련 고시 항목 없음"
STATUS_ERROR = "오류"
STATUS_CANCELLED = "취소"
STATUSES = (STATUS_DONE, STATUS_NO_FACTS, STATUS_NO_CANDIDATES, STATUS_ERROR, STATUS_CANCELLED)

# 검토 대상 고시 이름과 화면·결과 표기. 결과 엑셀·처리내역이 이 순서를 쓴다.
FAMILY_ORDER = ("advanced", "core", "dual_use", "military")
FAMILY_LABELS = {"advanced": "국가첨단전략기술", "core": "국가핵심기술", "dual_use": "전략물자(이중용도)",
                 "military": "전략물자(군용)"}

# 과제 입력 칸의 화면·양식 이름
FIELD_TITLE = "연구개발과제명"
FIELD_FINAL_GOAL = "최종목표"
FIELD_CONTENT = "연구개발내용"
FIELD_UTILIZATION = "활용계획 및 기대효과"
FIELD_STAGE = "연구개발단계"
FIELD_FUND = "정부지원연구개발비(백만원)"
# 과제요약정보 세 칸: (과제 입력 키, 이름)
SUMMARY_FIELDS = (("final_goal", FIELD_FINAL_GOAL), ("rnd_content", FIELD_CONTENT), ("utilization", FIELD_UTILIZATION))

# 연구개발단계 정식 이름과 받는 줄임말(공백을 뺀 값으로 찾는다)
RND_STAGES = ("기초연구", "응용연구", "개발연구")
RND_STAGE_ALIASES = {"기초연구": "기초연구", "기초": "기초연구", "응용연구": "응용연구", "응용": "응용연구",
                     "개발연구": "개발연구", "개발": "개발연구"}
# 선택 칸 경고에 쓰는 칸 이름
WARNING_FIELD_STAGE = "연구개발단계"
WARNING_FIELD_FUND = "정부지원연구개발비"
_PLAIN_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
_SPACES = re.compile(r"\s+")

# 입력 설명(결과 '입력 정보' 칸)
INPUT_SUMMARY = "과제요약정보"

# 버린 것의 단계 이름(dropped[].stage)
DROP_STAGE_EXTRACT = "최종목표 사양 추출"
DROP_STAGE_PAIR = "매핑"
DROP_STAGE_CANDIDATE = "관련 고시 조항"
DROP_STAGE_JUDGE = "판정"
REASON_CANDIDATE_NOT_IN_TABLE = "고시 기준 사양 표에 없는 관련 고시 조항"

CALL_KEYS = ("extract", "screen", "pair", "total")

__all__ = [
    "STATUS_DONE", "STATUS_NO_FACTS", "STATUS_NO_CANDIDATES", "STATUS_ERROR", "STATUS_CANCELLED", "STATUSES",
    "FAMILY_ORDER", "FAMILY_LABELS", "FIELD_TITLE", "FIELD_FINAL_GOAL", "FIELD_CONTENT", "FIELD_UTILIZATION", "FIELD_STAGE",
    "FIELD_FUND", "SUMMARY_FIELDS", "RND_STAGES", "RND_STAGE_ALIASES", "INPUT_SUMMARY", "DROP_STAGE_EXTRACT",
    "DROP_STAGE_PAIR", "DROP_STAGE_CANDIDATE", "DROP_STAGE_JUDGE", "REASON_CANDIDATE_NOT_IN_TABLE", "CALL_KEYS",
    "PROGRAM_NAME", "PROGRAM_VERSION", "CallCounter", "InputError", "TaskResult", "normalize_rnd_stage",
    "normalize_gov_fund", "validate_task", "describe_input", "merge_branch_choices", "build_candidates",
    "family_verdicts_for_status", "empty_counts", "run_task", "cancelled_result", "error_result", "CancelledError",
]


class InputError(ValueError):
    """과제 입력이 검토 시작 조건(spec 2.2)에 맞지 않는다."""


@dataclass
class TaskResult:
    """과제 한 건의 결과. to_dict()는 JSON으로 바로 직렬화된다(숫자는 judge 결과와 같이 문자열, 건수는 정수).

    rnd_stage는 정식 이름 또는 빈 글, gov_fund는 10진수 글(백만원) 또는 빈 글이다. 둘 다 판정에 쓰지 않는다.
    brief는 간단한 결과 사전(brief.build_brief, 키는 brief.BRIEF_KEYS — 1.4.0 spec R7-1 모양)이다. 기존 키는 그대로 두고
    더한 키다.
    """
    title: str = ""
    rnd_stage: str = ""
    gov_fund: str = ""
    input_description: str = ""
    status: str = STATUS_ERROR
    error_reason: str = ""
    families: dict = field(default_factory=dict)
    overall: str = je.FAMILY_VERDICT_STATUS
    counts: dict = field(default_factory=dict)
    flagged_clause_count: int = 0
    judge: dict | None = None
    facts: list = field(default_factory=list)
    candidate_ids: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    calls: dict = field(default_factory=dict)
    row_number: int | None = None
    brief: dict | None = None

    def to_dict(self):
        return dict(title=self.title, rnd_stage=self.rnd_stage, gov_fund=self.gov_fund,
                    input_description=self.input_description, status=self.status,
                    error_reason=self.error_reason, families=dict(self.families), overall=self.overall,
                    counts=dict(self.counts), flagged_clause_count=self.flagged_clause_count,
                    judge=copy.deepcopy(self.judge), facts=copy.deepcopy(self.facts), candidate_ids=list(self.candidate_ids),
                    dropped=copy.deepcopy(self.dropped), calls=dict(self.calls), row_number=self.row_number,
                    brief=copy.deepcopy(self.brief))


# ── 선택 칸 정리(spec 2.3) ────────────────────────────────────────────

def _shown(value):
    """경고에 보일 원래 값. 엑셀 정수 모양 실수(1500.0)는 정수 표기로 보인다."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _option_warning(row_number, field_name, value):
    """선택 칸 경고 하나. message는 화면·처리내역에 그대로 쓰는 글이다(개별 검토는 행 번호 없이)."""
    prefix = f"{row_number}행: " if type(row_number) is int else ""
    return dict(row_number=row_number if type(row_number) is int else None, field=field_name, value=value,
                message=f"{prefix}{field_name} 값 확인 필요 — {value}")


def normalize_rnd_stage(value, row_number=None):
    """연구개발단계 값을 정리한다. 돌려주는 것: (정식 이름 또는 "", 경고 dict 또는 None).

    공백을 뺀 값이 기초연구·기초 → 기초연구, 응용연구·응용 → 응용연구, 개발연구·개발 → 개발연구.
    빈칸은 경고 없이 "". 그 밖의 값은 ""로 두고 경고(행 번호·칸 이름·원래 값)를 돌려준다.
    """
    if value is None:
        return "", None
    shown = _shown(value)
    if shown == "":
        return "", None
    key = _SPACES.sub("", shown) if isinstance(value, str) else None
    if key in RND_STAGE_ALIASES:
        return RND_STAGE_ALIASES[key], None
    return "", _option_warning(row_number, WARNING_FIELD_STAGE, shown)


def normalize_gov_fund(value, row_number=None):
    """정부지원연구개발비(백만원) 값을 정리한다. 돌려주는 것: (10진수 글 또는 "", 경고 dict 또는 None).

    글은 쉼표를 뺀 뒤 10진수(소수 허용, 지수 표기 불가)로 읽고, 엑셀 숫자 셀(정수·실수)도 받는다. 빈칸은 경고 없이 "".
    숫자가 아니거나 0 이하이면 ""로 두고 경고를 돌려준다. 크기가 커도 따로 경고하지 않는다.
    """
    if value is None:
        return "", None
    shown = _shown(value)
    if shown == "":
        return "", None
    number = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, (int, Decimal)):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value)) if math.isfinite(value) else None
    elif isinstance(value, str):
        text = shown.replace(",", "").strip()
        if _PLAIN_DECIMAL.fullmatch(text):
            try:
                number = Decimal(text)
            except InvalidOperation:
                number = None
    if number is None or not number.is_finite() or number <= 0:
        return "", _option_warning(row_number, WARNING_FIELD_FUND, shown)
    text = format(number, "f")
    if "." in text and isinstance(value, float):
        text = text.rstrip("0").rstrip(".")
    return text, None


# ── 입력 확인(spec 2.2) ────────────────────────────────────────────────

def _text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InputError(f"과제 입력 값이 글이 아니다: {type(value).__name__}")
    return value


def validate_task(task):
    """과제 입력을 확인하고 정리한 사본을 돌려준다. 어긋나면 InputError.

    시작 조건: 연구개발과제명 있음 그리고 (과제요약정보 세 칸 모두 있음 또는 확인한 목표 발췌 있음).
    발췌가 비어 있으면 첨부가 없는 것과 같다(첨부 파일 이름을 지운다).
    연구개발단계·정부지원연구개발비는 normalize_* 규칙으로 다시 확인하며, 정리되지 않은 잘못된 값은 조용히 지우지
    않고 InputError로 거부한다(일괄 읽기와 연결 함수가 먼저 정리하고 경고를 남긴다).
    돌려주는 키: title, final_goal, rnd_content, utilization, excerpt, attachment_name, rnd_stage, gov_fund, row_number.
    """
    if not isinstance(task, dict):
        raise InputError("과제 입력이 객체가 아니다")
    title = _text(task.get("title")).strip()
    summary = {key: _text(task.get(key)).strip() for key, _ in SUMMARY_FIELDS}
    excerpt = _text(task.get("excerpt")).strip()
    attachment_name = _text(task.get("attachment_name")).strip() if excerpt else ""
    if not title:
        raise InputError(f"{FIELD_TITLE}이 없다")
    missing = [name for key, name in SUMMARY_FIELDS if not summary[key]]
    if missing and not excerpt:
        raise InputError("확인한 목표 발췌가 없으면 과제요약정보 세 칸이 모두 있어야 한다. 빈 칸: " + ", ".join(missing))
    rnd_stage, stage_warning = normalize_rnd_stage(task.get("rnd_stage"))
    if stage_warning:
        raise InputError(f"{FIELD_STAGE} 값이 정리되지 않았다")
    gov_fund, fund_warning = normalize_gov_fund(task.get("gov_fund"))
    if fund_warning:
        raise InputError(f"{FIELD_FUND} 값이 정리되지 않았다")
    row_number = task.get("row_number")
    return dict(title=title, **summary, excerpt=excerpt, attachment_name=attachment_name, rnd_stage=rnd_stage,
                gov_fund=gov_fund, row_number=row_number if type(row_number) is int else None)


def describe_input(task):
    """'입력 정보' 칸 글: 과제요약정보 칸이 하나라도 있으면 '과제요약정보', 확인한 발췌가 있고 첨부 파일 이름이 있으면
    그 파일 이름. 둘 다면 '; '로 잇는다. 발췌를 확인하지 않은 첨부의 이름은 쓰지 않는다."""
    parts = []
    if any(_text(task.get(key)).strip() for key, _ in SUMMARY_FIELDS):
        parts.append(INPUT_SUMMARY)
    name = _text(task.get("attachment_name")).strip()
    if name and _text(task.get("excerpt")).strip():
        parts.append(name)
    return "; ".join(parts)


# ── 합치기 도우미 ───────────────────────────────────────────────────────

def merge_branch_choices(pairs, branch_choices):
    """ai_stages의 branch_choices를 매핑 목록에 합친다(입력은 바꾸지 않는다).

    같은 조항의 매핑 중 branch_id가 빈 것에 선택한 branch_id를 채우고, 매핑이 하나도 없는 조항에 선택이 있으면
    갈래만 정한 매핑 {clause_id, fact_id:"", threshold_id:"", branch_id, reason, ambiguous:false}을 더한다.
    """
    merged = [dict(pair) for pair in pairs]
    clauses_with_pairs = {pair.get("clause_id") for pair in merged}
    for choice in branch_choices:
        clause_id, branch_id = choice.get("clause_id", ""), choice.get("branch_id", "")
        if not branch_id:
            continue
        if clause_id in clauses_with_pairs:
            for pair in merged:
                if pair.get("clause_id") == clause_id and not pair.get("branch_id"):
                    pair["branch_id"] = branch_id
        else:
            merged.append(dict(clause_id=clause_id, fact_id="", threshold_id="", branch_id=branch_id,
                               reason=choice.get("reason", ""), ambiguous=False))
    return merged


def build_candidates(candidate_ids, table, catalogue_index):
    """관련 고시 조항 clause_id → 판정 엔진에 넣을 표 기록(기준본 색인의 code를 더함).

    돌려주는 것: (기록 목록, 표에 없는 조항의 dropped 항목 목록). 표에 없는 조항은 조용히 빼지 않는다.
    """
    codes = {entry["clause_id"]: entry.get("code", "") for entry in catalogue_index}
    candidates, dropped = [], []
    for clause_id in candidate_ids:
        try:
            record = table.record(clause_id)
        except KeyError:
            dropped.append(_drop(DROP_STAGE_CANDIDATE, "관련 고시 조항", clause_id, REASON_CANDIDATE_NOT_IN_TABLE))
            continue
        record["code"] = codes.get(clause_id, "")
        candidates.append(record)
    return candidates, dropped


def _drop(stage, kind, ids, reason):
    return dict(stage=stage, kind=kind, ids=ids, reason=reason)


def _ids_text(item, keys):
    return "/".join(str(item.get(key) or "") for key in keys)


def _merge_dropped(extract_dropped, pair_dropped, judge_dropped):
    """세 단계의 버림 목록을 {stage, kind, ids, reason} 한 모양으로 합친다."""
    merged = []
    for item in extract_dropped:
        merged.append(_drop(DROP_STAGE_EXTRACT, "최종목표 사양", str(item.get("fact_id") or ""), item.get("reason", "")))
    for item in pair_dropped:
        kind = "갈래 선택" if item.get("kind") == "branch_choice" else "매핑"
        merged.append(_drop(DROP_STAGE_PAIR, kind, _ids_text(item, ("clause_id", "fact_id", "threshold_id", "branch_id")),
                            item.get("reason", "")))
    for item in judge_dropped:
        pair = item.get("pair") or {}
        merged.append(_drop(DROP_STAGE_JUDGE, "매핑", _ids_text(pair, ("clause_id", "fact_id", "threshold_id", "branch_id")),
                            item.get("reason", "")))
    return merged


# ── 상태별 고시별·종합 검토 결과(7.7) ──────────────────────────────────────────

def family_verdicts_for_status(status, families_selected, judge_dict):
    """상태에 따른 (고시별 검토 결과, 종합 검토 결과). '완료'는 judge 결과를 그대로 쓴다."""
    selected = [str(f) for f in families_selected]
    if status == STATUS_DONE:
        if not judge_dict:
            raise ValueError("완료 상태에는 judge 결과가 있어야 한다")
        return dict(judge_dict["families"]), judge_dict["overall"]
    verdict = je.FAMILY_VERDICT_NONE if status == STATUS_NO_CANDIDATES else je.FAMILY_VERDICT_STATUS
    families = {}
    for family in FAMILY_ORDER:
        families[family] = verdict if family in selected else je.FAMILY_VERDICT_EXCLUDED
    for family in selected:
        if family not in families:
            families[family] = verdict
    return families, verdict


def empty_counts():
    return {key: 0 for key in je.COUNT_KEYS}


def _calls(extract=0, screen=0, pair=0):
    return dict(extract=extract, screen=screen, pair=pair, total=extract + screen + pair)


def _base_result(clean, families_selected, status, *, error_reason="", judge_dict=None):
    families, overall = family_verdicts_for_status(status, families_selected, judge_dict)
    return TaskResult(title=clean["title"], rnd_stage=clean["rnd_stage"], gov_fund=clean["gov_fund"],
                      input_description=describe_input(clean),
                      status=status, error_reason=error_reason, families=families, overall=overall,
                      counts=dict(judge_dict["counts"]) if judge_dict else empty_counts(),
                      flagged_clause_count=judge_dict["flagged_clause_count"] if judge_dict else 0,
                      judge=judge_dict, calls=_calls(), row_number=clean["row_number"])


def _loose(task):
    """상태 결과용 느슨한 정리: 입력이 어긋나도 연구개발과제명·행 번호와 정리되는 선택 칸 값은 남긴다."""
    try:
        return validate_task(task)
    except InputError:
        task = task if isinstance(task, dict) else {}
        row_number = task.get("row_number")
        texts = {key: str(task.get(key) or "").strip() for key in ("title", "final_goal", "rnd_content", "utilization",
                                                                   "excerpt", "attachment_name")}
        if not texts["excerpt"]:
            texts["attachment_name"] = ""
        return dict(**texts, rnd_stage=normalize_rnd_stage(task.get("rnd_stage"))[0],
                    gov_fund=normalize_gov_fund(task.get("gov_fund"))[0],
                    row_number=row_number if type(row_number) is int else None)


class CancelledError(RuntimeError):
    """취소 뒤의 AI 요청 거부. run_task는 이 예외를 '취소' 결과로 돌려준다(오류가 아님)."""


def _set_brief(result, families_selected, *, decisions=(), records=(), rank=None, option_warnings=()):
    """결과에 간단한 결과(brief, 1.4.0 spec R7-1 모양)를 담는다. 상태·판정 기록·최종목표 사양·버린 것은 result의 값을 쓴다."""
    import brief   # brief가 이 모듈의 상태·고시 이름을 쓰므로 순환 import를 피해 쓸 때 불러온다
    result.brief = brief.build_brief(result.status, families_selected, result.judge, decisions=decisions, records=records,
                                     facts=result.facts, dropped_count=len(result.dropped),
                                     option_warning_count=len(option_warnings), rank=rank)
    return result


def cancelled_result(task, families_selected, *, option_warnings=()):
    """시작하지 않은 과제의 '취소' 결과(일괄 검토용). AI 호출 0. option_warnings는 그 과제의 선택 칸 경고(건수 안내용)."""
    return _set_brief(_base_result(_loose(task), families_selected, STATUS_CANCELLED), families_selected,
                      option_warnings=list(option_warnings or ()))


def error_result(task, families_selected, reason, *, calls=None, facts=(), dropped=(), option_warnings=()):
    """'오류' 결과. reason은 고정 문구·예외 이름·ID만 담는다(키·응답 본문은 넣지 않는다)."""
    result = _base_result(_loose(task), families_selected, STATUS_ERROR, error_reason=str(reason))
    result.calls = dict(calls) if calls else _calls()
    result.facts = list(facts)
    result.dropped = list(dropped)
    return _set_brief(result, families_selected, option_warnings=list(option_warnings or ()))


# ── 한 과제 흐름 ───────────────────────────────────────────────────────

def run_task(task, families, client, table, catalogue_index, *, progress=None, counter=None, search_engine=None,
             option_warnings=()):
    """과제 한 건을 끝까지 돌려 TaskResult를 낸다.

    task: validate_task가 받는 과제 입력(모듈 머리말의 키). 시작 조건에 어긋나면 InputError.
    AI 단계에는 연구개발과제명·과제요약정보 세 칸·목표 발췌만 넘기고 연구개발단계·지원금은 넘기지 않는다.
    families: 검토 대상 고시 이름 목록. client: ask_json을 가진 클라이언트. table: ThresholdTable.
    catalogue_index: notice_catalogue.clause_index(catalogue)의 결과.
    search_engine: semantic_ranking(text)을 가진 PC 안 검색 엔진(선택). 간단한 결과의 세부 기술 일치 확인에만 쓰며,
        따질 조항이 있을 때만 한 번 부른다. 없으면 그런 과제의 간단한 결과에 '쓸 수 없음'을 드러낸다.
    option_warnings: 그 과제의 선택 칸 경고 목록(선택). 간단한 결과의 건수 안내에만 쓴다(AI·판정에 넘기지 않는다).
    단계 오류(StageError)와 그 밖의 예외는 '오류' 상태로 담아 돌려준다(예외를 밖으로 내지 않는다).
    """
    clean = validate_task(task)
    families = [str(f) for f in dict.fromkeys(families)]
    if not families:
        raise InputError("검토 대상 고시를 하나 이상 골라야 한다")
    option_warnings = list(option_warnings or ())
    # 단계가 StageError로 끝나도 보낸 요청 수가 남도록, 단계마다 계수기를 따로 두고 끝에 합친다.
    counters = dict(extract=CallCounter(), screen=CallCounter(), pair=CallCounter())

    def stage_calls():
        calls = {stage: counters[stage].calls for stage in counters}
        return calls

    rank = None
    if search_engine is not None:
        def rank():
            import brief   # _set_brief와 같은 까닭으로 쓸 때 불러온다
            # 의미 모델을 처음 불러오는 몇 초 동안 진행 표시가 멈춘 것처럼 보이지 않게, 기존 단계 이름(관련 고시 조항
            # 선별)의 이벤트로 알린다. 일괄 검토는 progress 없이 부르므로 과제별 진행을 보내지 않는다.
            # 끝날 때 1/1을 다시 보내 브리지의 마지막 진행 값(완료 이벤트가 이어 씀)이 0/0으로 남지 않게 한다.
            if progress is not None:
                progress(dict(stage=STAGE_SCREEN, message=brief.PROGRESS_MESSAGE, completed=0, total=1))
            try:
                return search_engine.semantic_ranking(brief.semantic_text(clean))
            finally:
                if progress is not None:
                    progress(dict(stage=STAGE_SCREEN, message=brief.PROGRESS_MESSAGE, completed=1, total=1))

    common = dict(families=families, option_warnings=option_warnings)
    facts, dropped = [], []
    # AI 단계로 가는 글: 연구개발과제명·과제요약정보 세 칸·확인한 목표 발췌뿐.
    task_text = {key: clean[key] for key in ("title", "final_goal", "rnd_content", "utilization", "excerpt")}
    try:
        extracted = extract_goal_facts(task_text, client, progress=progress, counter=counters["extract"])
        facts = extracted["facts"]
        dropped = _merge_dropped(extracted["dropped"], [], [])
        if not facts:
            result = _base_result(clean, families, STATUS_NO_FACTS)
            return _finish(result, stage_calls(), facts, [], dropped, counter, **common)

        index = screen_index(catalogue_index, table, families)
        screened = screen_candidates(task_text, facts, index, client, progress=progress, counter=counters["screen"])
        candidate_ids = screened["candidates"]
        if not candidate_ids:
            result = _base_result(clean, families, STATUS_NO_CANDIDATES)
            return _finish(result, stage_calls(), facts, candidate_ids, dropped, counter, **common)

        paired = pair_facts(task_text, facts, candidate_ids, table, client, progress=progress, counter=counters["pair"])
        pairs = merge_branch_choices(paired["pairs"], paired["branch_choices"])
        candidates, candidate_dropped = build_candidates(candidate_ids, table, catalogue_index)
        judged = je.judge(facts, candidates, pairs, families, near_percent=je.NEAR_PERCENT).to_dict()
        dropped = (_merge_dropped(extracted["dropped"], paired["dropped"], judged["dropped"]) + candidate_dropped)
        result = _base_result(clean, families, STATUS_DONE, judge_dict=judged)
        return _finish(result, stage_calls(), facts, candidate_ids, dropped, counter, decisions=screened["decisions"],
                       records=candidates, rank=rank, **common)
    except CancelledError:
        return _finish(cancelled_result(clean, families), stage_calls(), facts, [], dropped, counter, **common)
    except StageError as error:
        return _finish(error_result(clean, families, str(error)), stage_calls(), facts, [], dropped, counter, **common)
    except Exception as error:  # noqa: BLE001 — 행 하나의 실패를 결과로 남기고 흐름을 끝낸다
        reason = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
        return _finish(error_result(clean, families, reason), stage_calls(), facts, [], dropped, counter, **common)


def _finish(result, stage_calls, facts, candidate_ids, dropped, counter, *, families, option_warnings=(), decisions=(),
            records=(), rank=None):
    result.calls = _calls(**stage_calls)
    result.facts = list(facts)
    result.candidate_ids = list(candidate_ids)
    result.dropped = list(dropped)
    # 간단한 결과를 먼저 만든다: 만들다 실패하면 부른 쪽이 '오류'로 다시 끝내며, 그때 요청 수를 한 번만 센다.
    _set_brief(result, families, decisions=decisions, records=records, rank=rank, option_warnings=option_warnings)
    if counter is not None:
        counter.add(result.calls["total"])
    return result
