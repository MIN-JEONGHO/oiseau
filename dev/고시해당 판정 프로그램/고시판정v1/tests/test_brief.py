"""간단한 결과 자료(brief) 시험. 1.4.0 spec 2절(R1)·3절(R2)·5절(R4)·8절(R7-1·R7-3)·10절.

- 판정 기록은 합성 표 기록·합성 최종목표 사양으로 judge_engine이 만들고, 과제 흐름은 모의 AI(tests/mock_model.py)로 돌린다.
- 의미 검색은 가짜 검색 엔진(고시별 순위를 정해 둠)과 실제 내장 모델·조항 벡터(오프라인, resources/는 읽기만) 둘 다로 본다.
- 글·숫자는 모두 합성이며 실제 과제가 아니다. 실제 AI·네트워크·키를 쓰지 않는다.
"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import ai_stages
import batch
import brief
import excel_report
import judge_engine as je
import notice_search as ns
import pipeline
from notice_catalogue import load_catalogue
from threshold_table import load_threshold_table
from tests import test_pipeline as tp
from tests.mock_model import MockModel
from tests.test_judge_engine import branch, fact, pair, record, rejected, threshold

ALL = ["advanced", "core", "dual_use", "military"]
DONE = pipeline.STATUS_DONE
OVER, NEAR, UNDER = brief.VERDICT_OVER, brief.VERDICT_NEAR, brief.VERDICT_UNDER
EXCLUDED = "대조 안 함(선택 제외)"
OLD_NAMES = ("사양 미달 또는 무관", "최종목표 수치 없음")           # 더 쓰지 않는 판정 이름(뒤의 것은 과제 사유 글로만 남는다)
NOTICE_TEXTS = ("고시 기준값 대부분은 AI가 고시 원문에서 읽은 값으로, 원문 확인이 필요함.",
                "용도·양산 목적·예외 같은 숫자 외 조건은 판정에 넣지 않았으므로 원문으로 확인이 필요함.",
                "이 결과는 고시 수치 기준과의 참고 대조이며 고시 해당 여부의 공식 판정이 아님.")
HINT_SEMANTIC = "의미 검색을 쓸 수 없어 세부 기술 일치 확인 안 함"
EMPTY = "고시 사양을 초과하거나 근접한 조항 없음"
BRIEF_KEYS = ("overall", "reason", "group", "families", "hints", "empty_message", "focus", "under", "review", "counts",
              "semantic")
CLAUSE_KEYS = ("verdict", "family", "family_label", "clause_id", "code", "title", "flags", "lines", "others")
LINE_KEYS = ("verdict", "source_field", "quote", "target", "basis", "difference", "reason", "display_reason")
REVIEW_KEYS = {"family", "family_label", "clause_id", "code", "title", "kept_because", "why", "reason"}
SEVEN_FLAGS = ["추가 확인 조건", "갈래 확인 필요", "매핑 확인 필요", "범위 목표", "일부 수치만 비교", "입력 간 목표값 불일치",
               "기준값 채택 실패(원문 확인 필요)"]


def counts(over=0, near=0, under=0, review=0, hidden=0, dropped=0):
    return dict(over=over, near=near, under=under, review=review, hidden=hidden, detail_match_dropped=dropped)


# ── 합성 판정 기록 → brief ─────────────────────────────────────────────

def decisions_for(cands, detail=()):
    return [dict(clause_id=c["clause_id"], candidate=True, detail_match=c["clause_id"] in detail, reason="합성")
            for c in cands]


def make(cands, facts=(), pairs=(), *, families=ALL, detail=(), rank=None, dropped=0, warnings=0, decisions=None):
    facts, pairs = list(facts), list(pairs)
    judged = je.judge(facts, cands, pairs, families).to_dict()
    return brief.build_brief(DONE, families, judged, decisions=decisions_for(cands, detail) if decisions is None else decisions,
                             records=cands, facts=facts, dropped_count=dropped, option_warning_count=warnings, rank=rank)


def one(operator, t_value, f_value, t_unit="", f_unit="", *, subject="길이", source="최종목표", **kwargs):
    """기준 하나·목표 하나인 조항 하나의 brief."""
    cand = record("advanced:1", "advanced", [branch("b1", [threshold("t1", subject, operator, t_value, t_unit)])])
    return make([cand], [fact("f1", f_value, f_unit, subject=subject, source_field=source)],
                [pair("advanced:1", "f1", "t1")], **kwargs)


def shown(result):
    """초과·근접 조항과 미달 조항을 이은 목록."""
    return result["focus"] + result["under"]


def only_clause(result):
    """숫자로 비교된 조항이 하나뿐인 결과의 그 조항."""
    (clause,) = shown(result)
    return clause


def only_line(result):
    """조항 하나·사양 줄 하나인 결과의 그 줄."""
    (line,) = only_clause(result)["lines"]
    return line


def ids(clauses):
    return [c["clause_id"] for c in clauses]


def numeric(cid, value, operator="ge", unit="nm", subject="길이", **kwargs):
    family = cid.split(":")[0]
    tid = "t:" + cid
    return record(cid, family, [branch("b:" + cid, [threshold(tid, subject, operator, value, unit)])], **kwargs)


def no_numeric(cid, title="합성 정성 항목"):
    return record(cid, cid.split(":")[0], [branch("b:" + cid, text="정성 조건 원문")], title=title)


def failed(cid):
    return record(cid, cid.split(":")[0], [], rejected=[rejected()])


def and_record(cid="advanced:1", family="advanced", **kwargs):
    """한 갈래에 기준 둘(길이 100nm 이상 그리고 출력 10W 이상)."""
    return record(cid, family, [branch("b1", [threshold("t1", "길이", "ge", 100, "nm"),
                                              threshold("t2", "출력", "ge", 10, "W")])], **kwargs)


def or_record(cid="advanced:1", family="advanced", **kwargs):
    """갈래 둘(길이 100nm 이상 또는 출력 10W 이상)."""
    return record(cid, family, [branch("bA", [threshold("tA", "길이", "ge", 100, "nm")]),
                                branch("bB", [threshold("tB", "출력", "ge", 10, "W")])], **kwargs)


def status_brief(status, families=ALL, **kwargs):
    return brief.build_brief(status, families, None, **kwargs)


class Ranker:
    """build_brief의 rank 인자: 부를 때마다 횟수를 세고 정해 둔 순위 결과를 돌려준다."""

    def __init__(self, ranking=None, *, available=True, error=None):
        self.ranking, self.available, self.error, self.calls = ranking or {}, available, error, 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.available:
            return dict(available=False, reason="합성 사유", ranking=None)
        return dict(available=True, reason="", ranking={f: list(self.ranking.get(f, [])) for f in pipeline.FAMILY_ORDER})


class FakeEngine:
    """가짜 검색 엔진(SearchEngine.semantic_ranking과 같은 모양). 받은 글을 기록하며 여러 스레드에서 불러도 된다."""

    semantic_model_fingerprint = ""
    semantic_vectors_fingerprint = ""

    def __init__(self, ranking=None, *, available=True):
        self.ranking, self.available = ranking or {}, available
        self.texts = []
        self._lock = threading.Lock()

    def semantic_ranking(self, text):
        with self._lock:
            self.texts.append(text)
        if not self.available:
            return dict(available=False, reason="합성 사유", ranking=None)
        return dict(available=True, reason="", ranking={f: list(self.ranking.get(f, [])) for f in pipeline.FAMILY_ORDER})


def filler(family, count, prefix="other"):
    return [f"{family}:{prefix}:{i}" for i in range(count)]


# ── 상수·숫자 표시 ───────────────────────────────────────────────────────

class ConstantTests(unittest.TestCase):
    def test_adjustable_defaults_in_one_place(self):
        self.assertEqual(brief.TOP_RANK, 5)
        self.assertEqual(brief.QUOTE_LIMIT, 80)
        self.assertEqual(brief.CONVERTED_DIGITS, 4)

    def test_fixed_texts(self):
        self.assertEqual((OVER, NEAR, UNDER), ("고시 사양 초과", "고시 사양 근접", "고시 사양 미달"))
        self.assertEqual((brief.VERDICT_ERROR, brief.VERDICT_CANCELLED, brief.VERDICT_EXCLUDED), ("오류", "취소", EXCLUDED))
        self.assertEqual(brief.VERDICTS, ("고시 사양 초과", "고시 사양 근접", "고시 사양 미달", "오류", "취소", EXCLUDED))
        self.assertEqual(brief.CLAUSE_VERDICTS, ("고시 사양 초과", "고시 사양 근접", "고시 사양 미달"))
        self.assertEqual(brief.OPERATOR_LABELS, excel_report.OPERATOR_LABELS)
        self.assertEqual(brief.OPERATOR_LABELS, ns.OPERATOR_LABELS)
        self.assertEqual((brief.SEMANTIC_USED, brief.SEMANTIC_UNAVAILABLE, brief.SEMANTIC_NOT_NEEDED),
                         ("used", "unavailable", "not_needed"))
        self.assertEqual(brief.PROGRESS_MESSAGE, "세부 기술 일치 확인 중")
        self.assertEqual(brief.EMPTY_MESSAGE, EMPTY)
        self.assertEqual((brief.REASON_UNDER, brief.REASON_NO_OVERLAP, brief.REASON_NO_CANDIDATES, brief.REASON_NO_FACTS),
                         ("기준에 못 미침", "사양이 겹치는 고시 조항 없음", "관련 고시 조항 없음", "최종목표 수치 없음"))
        self.assertEqual((brief.GROUP_FOCUS, brief.GROUP_OTHER, brief.GROUP_UNJUDGED), ("focus", "other", "unjudged"))
        self.assertEqual(brief.TALLY_KINDS, ("over", "near", "under", "unjudged"))
        self.assertEqual(brief.TALLY_LABELS, dict(over="고시 사양 초과", near="고시 사양 근접", under="고시 사양 미달",
                                                  unjudged="오류·취소(판정 없음)"))

    def test_key_names(self):
        self.assertEqual(brief.BRIEF_KEYS, BRIEF_KEYS)
        self.assertEqual(brief.CLAUSE_KEYS, CLAUSE_KEYS)
        self.assertEqual(brief.LINE_KEYS, LINE_KEYS)
        self.assertEqual(set(brief.REVIEW_KEYS), REVIEW_KEYS)
        self.assertEqual(brief.COUNT_KEYS, ("over", "near", "under", "review", "hidden", "detail_match_dropped"))

    def test_clause_flags_are_the_seven_in_engine_order(self):
        self.assertEqual(list(brief.CLAUSE_FLAGS), SEVEN_FLAGS)
        self.assertEqual(list(brief.CLAUSE_FLAGS), [flag for flag in je.FLAGS if flag != je.FLAG_EXTRACTED])

    def test_removed_names_and_common_notices(self):
        # 공통 안내 상수와 옛 판정 이름·옛 도우미는 없다.
        for name in ("NOTICES", "VERDICT_NO_FACTS", "HINT_NO_CANDIDATES", "SUMMARY_LIMIT", "summary_cell", "ITEM_KEYS",
                     "REASON_FLAGS"):
            self.assertFalse(hasattr(brief, name), name)
            self.assertNotIn(name, brief.__all__)
        texts = [value for value in vars(brief).values() if isinstance(value, str)]
        for value in vars(brief).values():
            if isinstance(value, (tuple, list)):
                texts += [v for v in value if isinstance(v, str)]
            elif isinstance(value, dict):
                texts += [v for v in list(value) + list(value.values()) if isinstance(v, str)]
        constants = [text for text in texts if text != brief.__doc__]
        for notice in NOTICE_TEXTS:
            self.assertNotIn(notice, constants)
        self.assertNotIn("사양 미달 또는 무관", constants)
        self.assertNotIn("AI가 고른 관련 고시 조항 없음", constants)
        for name in brief.__all__:
            self.assertTrue(hasattr(brief, name), name)

    def test_number_display(self):
        cases = (("3E+6", "3,000,000"), ("500.0", "500"), ("0.950", "0.95"), ("1234567.890", "1,234,567.89"),
                 ("-1500", "-1,500"), ("0", "0"), ("0.00", "0"), ("-0", "0"), ("1E-7", "0.0000001"), ("12", "12"),
                 ("16", "16"), ("0.254", "0.254"), ("1000", "1,000"), ("2.5E+3", "2,500"))
        for raw, text in cases:
            self.assertEqual(brief.format_number(raw), text, raw)
        self.assertEqual(brief.format_number("숫자 아님"), "숫자 아님")

    def test_display_quote(self):
        self.assertEqual(brief.display_quote("가" * 80), "가" * 80)
        self.assertEqual(brief.display_quote("가" * 81), "가" * 80 + "…")
        self.assertEqual(brief.display_quote("나" * 12, limit=10), "나" * 10 + "…")


# ── R1 판정 이름과 상태별 대응 ──────────────────────────────────────────────

class StatusTests(unittest.TestCase):
    def test_simple_verdict_table(self):
        table = {je.VERDICT_OVER: OVER, je.VERDICT_NEAR: NEAR, je.VERDICT_UNDER: UNDER, je.FAMILY_VERDICT_NONE: UNDER,
                 je.FAMILY_VERDICT_EXCLUDED: EXCLUDED}
        for value, name in table.items():
            self.assertEqual(brief.simple_verdict(value), name)
        for bad in (je.FAMILY_VERDICT_STATUS, je.CLAUSE_VERDICT_NOT_COMPARABLE, "", None, ["초과"]):
            with self.assertRaises(ValueError):
                brief.simple_verdict(bad)

    def test_done_maps_family_and_overall(self):
        cands = [numeric("advanced:1", 100), numeric("core:1", 100), numeric("dual_use:1", 100), no_numeric("military:1")]
        facts = [fact("fa", 120, "nm"), fact("fc", 95, "nm"), fact("fd", 50, "nm")]
        pairs = [pair("advanced:1", "fa", "t:advanced:1"), pair("core:1", "fc", "t:core:1"), pair("dual_use:1", "fd", "t:dual_use:1")]
        result = make(cands, facts, pairs)
        self.assertEqual(tuple(result), BRIEF_KEYS)
        self.assertEqual(result["families"], dict(advanced=OVER, core=NEAR, dual_use=UNDER, military=UNDER))
        self.assertEqual((result["overall"], result["group"]), (OVER, "focus"))
        near_only = make(cands[1:2], facts[1:2], pairs[1:2], families=["core", "dual_use"])
        self.assertEqual(near_only["families"], dict(advanced=EXCLUDED, core=NEAR, dual_use=UNDER, military=EXCLUDED))
        self.assertEqual((near_only["overall"], near_only["group"]), (NEAR, "focus"))
        none = make([no_numeric("core:1")], families=["core"])
        self.assertEqual((none["families"]["core"], none["overall"], none["group"]), (UNDER, UNDER, "other"))

    def test_unknown_engine_value_is_error_not_another_name(self):
        judged = je.judge([], [no_numeric("core:1")], [], ["core"]).to_dict()
        for key, bad in (("overall", je.FAMILY_VERDICT_STATUS), ("overall", "모르는 값"), ("families", "모르는 값")):
            broken = json.loads(json.dumps(judged))
            if key == "overall":
                broken["overall"] = bad
            else:
                broken["families"]["core"] = bad
            with self.assertRaises(ValueError, msg=(key, bad)):
                brief.build_brief(DONE, ["core"], broken)

    def run_task(self, model, families=ALL, task=None, **kwargs):
        return pipeline.run_task(task or tp.TASK, families, model, tp.TABLE, tp.INDEX, **kwargs)

    def assert_status_brief(self, result, families, name, reason, group):
        data = result.to_dict()["brief"]
        self.assertEqual(tuple(data), BRIEF_KEYS)
        self.assertEqual((data["overall"], data["reason"], data["group"]), (name, reason, group))
        for family in ALL:
            self.assertEqual(data["families"][family], name if family in families else EXCLUDED, family)
        self.assertEqual((data["focus"], data["under"], data["review"]), ([], [], []))
        self.assertEqual(data["counts"], counts())
        self.assertEqual(data["semantic"], "not_needed")
        self.assertEqual(data["empty_message"], "" if group == "unjudged" else EMPTY)
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        return data

    def test_no_candidates(self):
        result = self.run_task(MockModel(facts=tp.FACTS, candidates=set()), ["advanced", "core"])
        self.assertEqual(result.status, pipeline.STATUS_NO_CANDIDATES)
        data = self.assert_status_brief(result, ["advanced", "core"], UNDER, "관련 고시 조항 없음", "other")
        self.assertEqual(data["hints"], [])            # 안내 줄 'AI가 고른 관련 고시 조항 없음'은 사유와 겹쳐 없앴다
        self.assertEqual(result.overall, je.FAMILY_VERDICT_NONE)       # 내부 값은 그대로

    def test_no_facts_without_dropped(self):
        result = self.run_task(MockModel(facts=[]))
        self.assertEqual(result.status, pipeline.STATUS_NO_FACTS)
        data = self.assert_status_brief(result, ALL, UNDER, "최종목표 수치 없음", "other")
        self.assertEqual(data["hints"], [])
        # 내부 값은 그대로(상세는 기존 값).
        self.assertEqual(result.overall, je.FAMILY_VERDICT_STATUS)

    def test_no_facts_with_dropped_shows_count_only(self):
        bad = dict(tp.FACTS[0], fact_id="bad", quote="99 zz")   # 인용이 글에 없어 버려지는 최종목표 사양
        result = self.run_task(MockModel(facts=[bad]), ["core"])
        self.assertEqual(result.status, pipeline.STATUS_NO_FACTS)
        data = self.assert_status_brief(result, ["core"], UNDER, "최종목표 수치 없음", "other")
        self.assertEqual(data["hints"], ["버린 최종목표 사양·매핑 1건 — 상세 보기에서 확인"])
        with_warning = self.run_task(MockModel(facts=[bad]), ["core"], option_warnings=[dict(message="합성 경고")])
        self.assertEqual(with_warning.brief["hints"], ["버린 최종목표 사양·매핑 1건 · 선택 칸 경고 1건 — 상세 보기에서 확인"])
        for hint in data["hints"]:
            self.assertNotIn("고시 대조 안 함", hint)

    def test_error(self):
        result = self.run_task(MockModel(facts=tp.FACTS, faults={"extract": ["shape", "shape"]}), ["advanced", "military"])
        self.assertEqual(result.status, pipeline.STATUS_ERROR)
        self.assertTrue(result.error_reason)
        data = self.assert_status_brief(result, ["advanced", "military"], "오류", "", "unjudged")
        self.assertEqual(data["hints"], [])
        boom = self.run_task(tp.BoomClient(), ["advanced"])
        self.assert_status_brief(boom, ["advanced"], "오류", "", "unjudged")
        direct = pipeline.error_result(tp.TASK, ["core"], "합성 오류", option_warnings=[{}, {}])
        self.assertEqual(self.assert_status_brief(direct, ["core"], "오류", "", "unjudged")["hints"],
                         ["선택 칸 경고 2건 — 상세 보기에서 확인"])

    def test_cancelled(self):
        data = self.assert_status_brief(pipeline.cancelled_result(tp.TASK, ["dual_use"]), ["dual_use"], "취소", "", "unjudged")
        self.assertEqual(data["hints"], [])

        class Refusing:
            def ask_json(self, *_args, **_kwargs):
                raise pipeline.CancelledError()
        result = self.run_task(Refusing(), ["core", "military"])
        self.assertEqual(result.status, pipeline.STATUS_CANCELLED)
        self.assert_status_brief(result, ["core", "military"], "취소", "", "unjudged")

    def test_brief_names_do_not_change_internal_values(self):
        model = MockModel(facts=tp.FACTS, candidates={"advanced:item:001", "dual_use:control:1A003"})
        result = self.run_task(model)
        self.assertEqual(result.families["advanced"], je.VERDICT_OVER)
        self.assertEqual(result.overall, je.VERDICT_OVER)
        self.assertEqual(result.brief["overall"], OVER)
        self.assertEqual({c["verdict"] for c in result.judge["clauses"]}, {je.VERDICT_OVER})

    def test_names_stay_inside_the_name_set(self):
        cands = [numeric("advanced:1", 100), numeric("core:1", 100), numeric("dual_use:1", 100), no_numeric("military:1")]
        facts = [fact("fa", 120, "nm"), fact("fc", 95, "nm"), fact("fd", 50, "nm")]
        pairs = [pair("advanced:1", "fa", "t:advanced:1"), pair("core:1", "fc", "t:core:1"), pair("dual_use:1", "fd", "t:dual_use:1")]
        results = [make(cands, facts, pairs), make(cands[2:], facts[2:], pairs[2:], families=["dual_use"])]
        results += [status_brief(status, ["core", "military"]) for status in pipeline.STATUSES if status != DONE]
        for data in results:
            self.assertIn(data["overall"], brief.VERDICTS[:5])
            for name in data["families"].values():
                self.assertIn(name, brief.VERDICTS)
            for clause in shown(data):
                self.assertIn(clause["verdict"], brief.CLAUSE_VERDICTS)
                for line in clause["lines"]:
                    self.assertIn(line["verdict"], brief.CLAUSE_VERDICTS)
            # 옛 이름은 판정 자리에 나오지 않는다. '최종목표 수치 없음'은 과제 사유 글로만 남는다.
            without_reason = dict(data, reason="")
            text = json.dumps(without_reason, ensure_ascii=False)
            for old in OLD_NAMES:
                self.assertNotIn(old, text)
            self.assertNotIn("notices", data)
            for notice in NOTICE_TEXTS:
                self.assertNotIn(notice, json.dumps(data, ensure_ascii=False))


# ── R1-3 과제 사유, R1-4 과제 묶음 ───────────────────────────────────────────

class ReasonAndGroupTests(unittest.TestCase):
    def test_focus_reason_names_first_clause_and_counts_the_rest(self):
        cands = [numeric("dual_use:1A003", 100, title="필름 두께", code="1A003"), numeric("core:1", 100, title="합성 핵심 항목"),
                 numeric("advanced:1", 100, title="합성 첨단 항목"), numeric("military:1", 100, title="합성 군용 항목")]
        values = {"dual_use:1A003": 120, "core:1": 95, "advanced:1": 96, "military:1": 50}
        facts = [fact("f" + cid, value, "nm") for cid, value in values.items()]
        pairs = [pair(cid, "f" + cid, "t:" + cid) for cid in values]
        result = make(cands, facts, pairs)
        # 첫 초과·근접 조항은 R2-2 순서(초과 → 근접)의 첫 조항. 통제번호가 있으면 넣는다. 미달 조항은 세지 않는다.
        self.assertEqual(ids(result["focus"]), ["dual_use:1A003", "advanced:1", "core:1"])
        self.assertEqual(result["reason"], "전략물자(이중용도) 1A003 필름 두께 외 2건")
        self.assertEqual((result["overall"], result["group"], result["empty_message"]), (OVER, "focus", ""))
        near = make(cands[1:], facts[1:], pairs[1:])
        self.assertEqual(near["reason"], "국가첨단전략기술 합성 첨단 항목 외 1건")       # 통제번호가 없으면 뺀다
        self.assertEqual((near["overall"], near["group"]), (NEAR, "focus"))
        single = make(cands[1:2], facts[1:2], pairs[1:2])
        self.assertEqual(single["reason"], "국가핵심기술 합성 핵심 항목")                  # 하나뿐이면 '외 N건'이 없다
        self.assertEqual((single["overall"], single["group"]), (NEAR, "focus"))

    def test_done_all_under(self):
        result = make([numeric("core:1", 100), numeric("core:2", 100), no_numeric("core:3")],
                      [fact("f1", 50, "nm"), fact("f2", 10, "nm")],
                      [pair("core:1", "f1", "t:core:1"), pair("core:2", "f2", "t:core:2")])
        self.assertEqual((result["overall"], result["reason"], result["group"]), (UNDER, "기준에 못 미침", "other"))
        self.assertEqual((result["focus"], result["empty_message"]), ([], EMPTY))
        self.assertEqual(ids(result["under"]), ["core:1", "core:2"])

    def test_done_without_compared_clause(self):
        result = make([no_numeric("core:1"), numeric("advanced:1", 100), failed("military:1")])
        self.assertEqual((result["overall"], result["reason"], result["group"]),
                         (UNDER, "사양이 겹치는 고시 조항 없음", "other"))
        self.assertEqual((result["focus"], result["under"], result["empty_message"]), ([], [], EMPTY))
        empty = brief.build_brief(DONE, ["core"], je.judge([], [], [], ["core"]).to_dict())
        self.assertEqual((empty["overall"], empty["reason"], empty["group"]), (UNDER, "사양이 겹치는 고시 조항 없음", "other"))

    def test_status_reasons_and_groups(self):
        expected = {pipeline.STATUS_NO_CANDIDATES: (UNDER, "관련 고시 조항 없음", "other", EMPTY),
                    pipeline.STATUS_NO_FACTS: (UNDER, "최종목표 수치 없음", "other", EMPTY),
                    pipeline.STATUS_ERROR: ("오류", "", "unjudged", ""),
                    pipeline.STATUS_CANCELLED: ("취소", "", "unjudged", "")}
        self.assertEqual(set(expected) | {DONE}, set(pipeline.STATUSES))
        for status, (name, reason, group, empty) in expected.items():
            data = status_brief(status, ["core", "dual_use"])
            self.assertEqual((data["overall"], data["reason"], data["group"], data["empty_message"]),
                             (name, reason, group, empty), status)
            self.assertEqual(data["families"], dict(advanced=EXCLUDED, core=name, dual_use=name, military=EXCLUDED))
            self.assertEqual((data["focus"], data["under"], data["review"], data["counts"]), ([], [], [], counts()))

    def test_overall_must_agree_with_clauses(self):
        cand = numeric("advanced:1", 100)
        facts, pairs = [fact("f1", 120, "nm")], [pair("advanced:1", "f1", "t:advanced:1")]
        judged = je.judge(facts, [cand], pairs, ALL).to_dict()
        for wrong in (je.VERDICT_NEAR, je.VERDICT_UNDER, je.FAMILY_VERDICT_NONE):
            with self.assertRaises(ValueError, msg=wrong):
                brief.build_brief(DONE, ALL, dict(judged, overall=wrong), records=[cand], facts=facts)
        under = je.judge([fact("f1", 50, "nm")], [cand], pairs, ALL).to_dict()
        with self.assertRaises(ValueError):
            brief.build_brief(DONE, ALL, dict(under, overall=je.VERDICT_OVER), records=[cand], facts=facts)

    def test_under_task_with_review_stays_other(self):
        result = make([no_numeric("dual_use:1"), numeric("core:1", 100)], [fact("f1", 50, "nm")],
                      [pair("core:1", "f1", "t:core:1")])
        self.assertEqual((result["overall"], result["group"], result["reason"]), (UNDER, "other", "기준에 못 미침"))
        self.assertEqual(result["counts"], counts(under=1, review=1))


# ── R2 조항 나누기·순서·사양 줄 ────────────────────────────────────────────

class ClauseSelectionTests(unittest.TestCase):
    def test_only_compared_clauses_are_shown(self):
        cands = [numeric("advanced:over", 100), numeric("advanced:near", 100), numeric("advanced:under", 100),
                 numeric("advanced:nofact", 100), numeric("advanced:kind", 100, unit="m"),
                 numeric("advanced:convert", 100, unit="K"), numeric("advanced:zero", 0), failed("advanced:failed"),
                 no_numeric("advanced:text")]
        facts = [fact("f1", 120, "nm"), fact("f2", 95, "nm"), fact("f3", 50, "nm"), fact("f4", 3, "초"), fact("f5", 30, "℃"),
                 fact("f6", -1, "nm")]
        pairs = [pair("advanced:over", "f1", "t:advanced:over"), pair("advanced:near", "f2", "t:advanced:near"),
                 pair("advanced:under", "f3", "t:advanced:under"), pair("advanced:kind", "f4", "t:advanced:kind"),
                 pair("advanced:convert", "f5", "t:advanced:convert"), pair("advanced:zero", "f6", "t:advanced:zero")]
        result = make(cands, facts, pairs)
        self.assertEqual(ids(result["focus"]), ["advanced:over", "advanced:near"])
        self.assertEqual([c["verdict"] for c in result["focus"]], [OVER, NEAR])
        self.assertEqual(ids(result["under"]), ["advanced:under"])
        self.assertEqual([c["verdict"] for c in result["under"]], [UNDER])
        # 감춘 조항: 비교 불가 다섯 사유·숫자 기준 없음. 첨단이고 세부 일치가 아니므로 추가 검토 필요도 아니다.
        self.assertEqual(result["review"], [])
        self.assertEqual(result["counts"], counts(over=1, near=1, under=1, hidden=6))
        self.assertEqual(result["semantic"], "not_needed")
        for clause in shown(result):
            self.assertEqual(tuple(clause), CLAUSE_KEYS)
            for line in clause["lines"]:
                self.assertEqual(tuple(line), LINE_KEYS)

    def test_order_focus_verdict_family_record_and_under_family_record(self):
        values = {"military:1": 120, "military:2": 10, "advanced:3": 130, "advanced:2": 50, "core:1": 110, "core:2": 20,
                  "advanced:1": 101, "dual_use:1": 95, "advanced:4": 30, "core:3": 95, "advanced:5": 92}
        cands = [numeric(cid, 100) for cid in values]
        facts = [fact("f" + cid, value, "nm") for cid, value in values.items()]
        pairs = [pair(cid, "f" + cid, "t:" + cid) for cid in values]
        result = make(cands, facts, pairs)
        # 초과·근접 조항: 판정(초과 → 근접) → 고시 → 판정 기록의 조항 순서. 초과 조항 뒤에 근접 조항이 모두 나온다.
        self.assertEqual(ids(result["focus"]), ["advanced:3", "advanced:1", "core:1", "military:1",
                                                "advanced:5", "core:3", "dual_use:1"])
        self.assertEqual([c["verdict"] for c in result["focus"]], [OVER] * 4 + [NEAR] * 3)
        self.assertEqual([c["family_label"] for c in result["focus"]][:4],
                         ["국가첨단전략기술", "국가첨단전략기술", "국가핵심기술", "전략물자(군용)"])
        # 미달 조항: 고시 → 판정 기록의 조항 순서.
        self.assertEqual(ids(result["under"]), ["advanced:2", "advanced:4", "core:2", "military:2"])
        self.assertEqual(result["counts"], counts(over=4, near=3, under=4))
        self.assertEqual((result["overall"], result["group"]), (OVER, "focus"))
        self.assertEqual(result["reason"], "국가첨단전략기술 합성 항목 외 6건")

    def test_clause_fields_and_reason_template(self):
        cand = record("core:9", "core", [branch("b1", [threshold("t1", "화소밀도", "ge", 3000, "ppi")])],
                      title="합성 디스플레이 항목", code="C9")
        f1 = dict(fact("f1", 3200, "ppi", subject="화소밀도"), value_text="3,200", quote="화소밀도 3,200ppi")
        result = make([cand], [f1], [pair("core:9", "f1", "t1")])
        sentence = '최종목표 "화소밀도 3,200ppi" ↔ 기준 화소밀도 3,000ppi 이상, 기준보다 6.7% 초과'
        self.assertEqual(result["focus"], [dict(
            verdict=OVER, family="core", family_label="국가핵심기술", clause_id="core:9", code="C9", title="합성 디스플레이 항목",
            flags=[], lines=[dict(verdict=OVER, source_field="최종목표", quote="화소밀도 3,200ppi", target="3,200 ppi",
                                  basis="화소밀도 3,000ppi 이상", difference="기준보다 6.7% 초과", reason=sentence,
                                  display_reason=sentence)],
            others=0)])
        self.assertEqual(result["reason"], "국가핵심기술 C9 합성 디스플레이 항목")

    def test_target_uses_value_text_and_raw_unit(self):
        # value_text가 단위로 끝나면 단위를 한 번만 쓴다. 단위가 없으면 value_text만.
        self.assertEqual(only_line(one("ge", 100, 120, "nm", "nm"))["target"], "120nm")
        cand = record("advanced:1", "advanced", [branch("b1", [threshold("t1", "길이", "ge", 100, "nm")])])
        raw = dict(fact("f1", 120, "㎚"), value_text="120")
        self.assertEqual(only_line(make([cand], [raw], [pair("advanced:1", "f1", "t1")]))["target"], "120 ㎚")
        self.assertEqual(only_line(one("ge", 3, 4))["target"], "4")

    def test_source_field_and_quote(self):
        line = only_line(one("ge", 100, 120, "nm", "nm", source="목표 발췌"))
        self.assertEqual((line["source_field"], line["quote"]), ("목표 발췌", "목표 120nm"))
        self.assertTrue(line["reason"].startswith('목표 발췌 "목표 120nm" ↔ 기준 '))

    def test_converted_basis(self):
        result = one("gt", 1, 950, "kW", "W", subject="출력", source="연구개발내용")
        line = only_line(result)
        self.assertEqual(line["basis"], "출력 1kW 초과 (환산 0.95 kW)")
        self.assertEqual((only_clause(result)["verdict"], line["verdict"]), (NEAR, NEAR))
        self.assertEqual(line["reason"], '연구개발내용 "목표 950W" ↔ 기준 출력 1kW 초과 (환산 0.95 kW), 기준보다 5.0% 미달')
        self.assertEqual(only_line(one("le", 1, 500, "μm", "nm"))["basis"], "길이 1μm 이하 (환산 0.5 μm)")
        # 같은 단위(별칭 정리 뒤 같음)는 환산 표기가 없다.
        self.assertEqual(only_line(one("ge", 100, 120, "nm", "㎚"))["basis"], "길이 100nm 이상")
        self.assertEqual(only_line(one("ge", 100, 120, "nm", "nm"))["basis"], "길이 100nm 이상")

    def test_number_display_in_basis(self):
        self.assertEqual(only_line(one("ge", "3E+6", "3500000", "Hz", "Hz"))["basis"], "길이 3,000,000Hz 이상")
        self.assertEqual(only_line(one("ge", "500.0", 600, "W", "W"))["basis"], "길이 500W 이상")
        self.assertEqual(only_line(one("ge", 1, 1500, "kW", "W"))["basis"], "길이 1kW 이상 (환산 1.5 kW)")
        self.assertEqual(only_line(one("ge", 1000, 2, "W", "kW"))["basis"], "길이 1,000W 이상 (환산 2,000 W)")

    def test_converted_value_shows_four_significant_digits(self):
        # 사용자 결정(2026-11-10): 간단한 결과의 환산 값은 유효숫자 4자리, 줄여서 달라지면 '약'. 판정 계산은 그대로.
        self.assertEqual(brief.format_converted("107.99999999999999136"), "약 108")
        self.assertEqual(brief.format_converted("0.95"), "0.95")
        self.assertEqual(brief.format_converted("2000"), "2,000")
        self.assertEqual(brief.format_converted("1234567"), "약 1,235,000")
        self.assertEqual(brief.format_converted("0.000123456"), "약 0.0001235")
        self.assertEqual(brief.format_converted("-3.14159"), "약 -3.142")
        self.assertEqual(brief.format_converted("0"), "0")
        self.assertEqual(brief.format_converted("모름"), "모름")
        self.assertEqual(brief.CONVERTED_DIGITS, 4)

    def test_difference_by_operator(self):
        cases = (
            ("ge", 100, 120, OVER, "기준보다 20.0% 초과"), ("ge", 100, 100, OVER, "기준보다 0.0% 초과"),
            ("ge", 100, 95, NEAR, "기준보다 5.0% 미달"), ("ge", 100, 50, UNDER, "기준보다 50.0% 미달"),
            ("gt", 100, 110, OVER, "기준보다 10.0% 초과"), ("gt", 100, 100, NEAR, "기준값과 같음(같은 값은 초과 아님)"),
            ("gt", 100, 95, NEAR, "기준보다 5.0% 미달"), ("gt", 100, 70, UNDER, "기준보다 30.0% 미달"),
            ("le", 100, 80, OVER, "기준보다 20.0% 초과"), ("le", 100, 100, OVER, "기준보다 0.0% 초과"),
            ("le", 100, 105, NEAR, "기준보다 5.0% 미달"), ("le", 100, 150, UNDER, "기준보다 50.0% 미달"),
            ("lt", 100, 80, OVER, "기준보다 20.0% 초과"), ("lt", 100, 100, NEAR, "기준값과 같음(같은 값은 초과 아님)"),
            ("lt", 100, 108, NEAR, "기준보다 8.0% 미달"), ("lt", 100, 130, UNDER, "기준보다 30.0% 미달"),
            ("ge", 3000, 3200, OVER, "기준보다 6.7% 초과"), ("le", 16, 14, OVER, "기준보다 12.5% 초과"),
        )
        for operator, t_value, f_value, verdict, difference in cases:
            with self.subTest(operator=operator, t=t_value, f=f_value):
                result = one(operator, t_value, f_value)
                clause, line = only_clause(result), only_line(result)
                self.assertEqual((clause["verdict"], line["verdict"], line["difference"]), (verdict, verdict, difference))
                self.assertTrue(line["reason"].endswith(", " + difference))
                self.assertEqual(result["under" if verdict == UNDER else "focus"], [clause])

    def test_difference_wording_is_over_or_under(self):
        # 1.4.2: 차이는 판정 이름과 같은 낱말 '초과/미달'로 적는다. '여유'·'충족'·'못 미침'은 초과인지 헷갈린다는 사용자 요청으로 뺐다.
        self.assertEqual((brief.DIFFERENCE_MET, brief.DIFFERENCE_MET_ZERO, brief.DIFFERENCE_SHORT, brief.DIFFERENCE_EQUAL),
                         ("기준보다 {}% 초과", "기준 초과", "기준보다 {}% 미달", "기준값과 같음(같은 값은 초과 아님)"))
        for text in (brief.DIFFERENCE_MET, brief.DIFFERENCE_MET_ZERO, brief.DIFFERENCE_SHORT, brief.DIFFERENCE_EQUAL):
            for old in ("여유", "충족", "못 미침"):
                self.assertNotIn(old, text)

    def test_zero_threshold_satisfied(self):
        result = one("ge", 0, 5)
        line = only_line(result)
        self.assertEqual((only_clause(result)["verdict"], line["verdict"], line["difference"], line["basis"]),
                         (OVER, OVER, "기준 초과", "길이 0 이상"))
        self.assertEqual(line["reason"], '최종목표 "목표 5" ↔ 기준 길이 0 이상, 기준 초과')
        self.assertEqual(shown(one("ge", 0, -1)), [])     # 못 미친 기준값 0은 비교 불가 → 감춤

    def test_display_reason_cuts_long_quote_only(self):
        long_quote = "가" * 79 + "나다라"
        cand = numeric("advanced:1", 100)
        for value in (120, 50):                             # 초과·근접 조항의 줄과 미달 조항의 줄 모두
            long_fact = dict(fact("f1", value, "nm"), quote=long_quote)
            line = only_line(make([cand], [long_fact], [pair("advanced:1", "f1", "t:advanced:1")]))
            self.assertEqual(line["quote"], long_quote)
            self.assertIn(f'"{long_quote}"', line["reason"])
            self.assertIn('"' + "가" * 79 + "나…" + '"', line["display_reason"])
            self.assertEqual(line["display_reason"].replace("가" * 79 + "나…", long_quote), line["reason"])
        short = only_line(one("ge", 100, 120))
        self.assertEqual(short["display_reason"], short["reason"])


# ── R2-3 초과·근접 조항의 사양 줄: 사양마다 한 줄 ───────────────────────────────

class FocusLineTests(unittest.TestCase):
    def test_one_line_per_threshold_in_table_order(self):
        cand = and_record("core:1", "core")
        facts = [fact("f1", 120, "nm"), fact("f2", 12, "W", subject="출력")]
        for pairs in ([pair("core:1", "f1", "t1"), pair("core:1", "f2", "t2")],
                      [pair("core:1", "f2", "t2"), pair("core:1", "f1", "t1")]):       # 매핑 순서와 무관하게 표 기록의 기준 순서
            clause = only_clause(make([cand], facts, pairs))
            self.assertEqual(clause["verdict"], OVER)
            self.assertEqual([(l["verdict"], l["quote"], l["basis"]) for l in clause["lines"]],
                             [(OVER, "목표 120nm", "길이 100nm 이상"), (OVER, "목표 12W", "출력 10W 이상")])
            self.assertEqual(clause["others"], 0)
            for line in clause["lines"]:
                self.assertNotIn("외", line["reason"])
                self.assertNotIn("확인", line["reason"])

    def test_threshold_order_without_table_record_follows_judge_record(self):
        cand = and_record("core:1", "core")
        facts = [fact("f1", 120, "nm"), fact("f2", 12, "W", subject="출력")]
        pairs = [pair("core:1", "f2", "t2"), pair("core:1", "f1", "t1")]
        judged = je.judge(facts, [cand], pairs, ALL).to_dict()
        clause = only_clause(brief.build_brief(DONE, ALL, judged, records=[], facts=facts))
        self.assertEqual([l["quote"] for l in clause["lines"]], ["목표 12W", "목표 120nm"])

    def test_near_clause_mixing_met_and_near(self):
        # spec 10절: 근접 조항 안에서 한 사양은 충족, 한 사양은 근접 → 사양 줄 둘.
        result = make([and_record()], [fact("f1", 120, "nm"), fact("f2", "9.5", "W", subject="출력")],
                      [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t2")])
        clause = only_clause(result)
        self.assertEqual(clause["verdict"], NEAR)
        self.assertEqual([(l["verdict"], l["difference"]) for l in clause["lines"]],
                         [(OVER, "기준보다 20.0% 초과"), (NEAR, "기준보다 5.0% 미달")])
        self.assertEqual([l["reason"] for l in clause["lines"]],
                         ['최종목표 "목표 120nm" ↔ 기준 길이 100nm 이상, 기준보다 20.0% 초과',
                          '최종목표 "목표 9.5W" ↔ 기준 출력 10W 이상, 기준보다 5.0% 미달'])
        self.assertEqual((result["overall"], result["group"], result["counts"]), (NEAR, "focus", counts(near=1)))

    def test_only_deciding_branch_makes_lines(self):
        near = only_clause(make([or_record()], [fact("f1", 50, "nm"), fact("f2", "9.5", "W", subject="출력")],
                                [pair("advanced:1", "f1", "tA"), pair("advanced:1", "f2", "tB")]))
        self.assertEqual(near["verdict"], NEAR)
        # 판정을 정하지 않은 갈래(길이, 미달)의 비교는 줄이 아니고 '외 N건'도 붙지 않는다.
        self.assertEqual([(l["verdict"], l["quote"], l["basis"]) for l in near["lines"]], [(NEAR, "목표 9.5W", "출력 10W 이상")])
        self.assertEqual(near["others"], 0)
        self.assertEqual(near["lines"][0]["reason"], '최종목표 "목표 9.5W" ↔ 기준 출력 10W 이상, 기준보다 5.0% 미달')
        self.assertEqual(near["flags"], ["갈래 확인 필요"])

    def test_every_deciding_branch_in_branch_order(self):
        # 판정을 정한 갈래가 둘 이상이면 갈래 순서대로 모든 갈래의 사양 줄(매핑 순서와 무관).
        both = only_clause(make([or_record()], [fact("f1", 120, "nm"), fact("f2", 11, "W", subject="출력")],
                                [pair("advanced:1", "f2", "tB"), pair("advanced:1", "f1", "tA")]))
        self.assertEqual(both["verdict"], OVER)
        self.assertEqual([l["quote"] for l in both["lines"]], ["목표 120nm", "목표 11W"])
        self.assertEqual((both["others"], both["flags"]), (0, ["갈래 확인 필요"]))

    def test_same_threshold_many_targets_uses_best_only(self):
        cand = numeric("core:1", 100)
        facts = [fact("f1", 50, "nm"), fact("f2", 120, "nm", source_field="연구개발내용")]
        clause = only_clause(make([cand], facts, [pair("core:1", "f1", "t:core:1"), pair("core:1", "f2", "t:core:1")]))
        self.assertEqual(clause["verdict"], OVER)
        self.assertEqual([(l["verdict"], l["source_field"], l["quote"]) for l in clause["lines"]],
                         [(OVER, "연구개발내용", "목표 120nm")])
        self.assertEqual((clause["others"], clause["flags"]), (0, ["입력 간 목표값 불일치"]))
        self.assertEqual(clause["lines"][0]["reason"], '연구개발내용 "목표 120nm" ↔ 기준 길이 100nm 이상, 기준보다 20.0% 초과')
        # 같은 판정이면 판정 기록(비교) 순서상 앞.
        tie = only_clause(make([cand], [fact("f1", 120, "nm"), fact("f2", 130, "nm")],
                               [pair("core:1", "f2", "t:core:1"), pair("core:1", "f1", "t:core:1")]))
        self.assertEqual([l["quote"] for l in tie["lines"]], ["목표 130nm"])
        # 기준 둘 가운데 한 기준에만 값이 둘이어도 기준마다 한 줄.
        cand = and_record("core:1", "core")
        facts = [fact("f1", 120, "nm"), fact("f2", 12, "W", subject="출력"), fact("f3", 130, "nm", source_field="연구개발내용")]
        many = only_clause(make([cand], facts, [pair("core:1", "f1", "t1"), pair("core:1", "f2", "t2"),
                                                pair("core:1", "f3", "t1")]))
        self.assertEqual([l["quote"] for l in many["lines"]], ["목표 120nm", "목표 12W"])
        self.assertEqual(many["others"], 0)

    def test_threshold_without_comparison_has_no_line(self):
        for facts, pairs in (([fact("f1", 120, "nm"), fact("f2", 5, "초", subject="출력")],
                              [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t2")]),     # 단위가 달라 비교 못 함
                             ([fact("f1", 120, "nm")], [pair("advanced:1", "f1", "t1")])):           # 매핑이 없음
            clause = only_clause(make([and_record()], facts, pairs))
            self.assertEqual(clause["verdict"], OVER)
            self.assertEqual([l["quote"] for l in clause["lines"]], ["목표 120nm"])
            self.assertEqual((clause["others"], clause["flags"]), (0, ["일부 수치만 비교"]))

    def test_broken_rule_is_error_not_a_silent_line(self):
        cand = numeric("advanced:1", 100)
        facts, pairs = [fact("f1", 50, "nm")], [pair("advanced:1", "f1", "t:advanced:1")]
        judged = je.judge(facts, [cand], pairs, ALL).to_dict()            # 미달 조항
        # 조항 판정은 초과인데 판정을 정한 갈래의 비교가 미달: 조용히 넣거나 빼지 않는다.
        broken = json.loads(json.dumps(judged))
        broken["clauses"][0]["verdict"] = je.VERDICT_OVER
        broken["families"]["advanced"] = broken["overall"] = je.VERDICT_OVER
        with self.assertRaises(ValueError):
            brief.build_brief(DONE, ALL, broken, records=[cand], facts=facts)
        # 초과·근접 조항인데 줄이 하나도 없음(판정을 정한 갈래가 비어 있음).
        over = je.judge([fact("f1", 120, "nm")], [cand], pairs, ALL).to_dict()
        over["clauses"][0]["deciding_branch_ids"] = []
        with self.assertRaises(ValueError):
            brief.build_brief(DONE, ALL, over, records=[cand], facts=facts)

    def test_broken_rule_ends_the_task_as_error(self):
        real = je.judge

        def tampered(*args, **kwargs):
            result = real(*args, **kwargs)
            for comp in result.comparisons:
                comp["verdict"] = je.VERDICT_UNDER
            return result
        with mock.patch.object(je, "judge", side_effect=tampered):
            result = pipeline.run_task(tp.TASK, ALL, MockModel(facts=tp.FACTS, candidates={"advanced:item:001"}), tp.TABLE,
                                       tp.INDEX)
        self.assertEqual(result.status, pipeline.STATUS_ERROR)
        self.assertTrue(result.error_reason)
        self.assertEqual((result.brief["overall"], result.brief["group"], result.brief["focus"]), ("오류", "unjudged", []))


# ── R2-4 미달 조항의 사양 줄: 한 줄과 '외 N건' ─────────────────────────────────

class UnderLineTests(unittest.TestCase):
    def test_and_branch_uses_threshold_that_decided(self):
        mixed = only_clause(make([and_record()], [fact("f1", 120, "nm"), fact("f2", 5, "W", subject="출력")],
                                 [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t2")]))
        self.assertEqual((mixed["verdict"], mixed["others"]), (UNDER, 1))
        self.assertEqual([(l["verdict"], l["quote"]) for l in mixed["lines"]], [(UNDER, "목표 5W")])
        self.assertEqual(mixed["lines"][0]["reason"], '최종목표 "목표 5W" ↔ 기준 출력 10W 이상, 기준보다 50.0% 미달 · 외 1건')
        self.assertEqual(mixed["lines"][0]["display_reason"], mixed["lines"][0]["reason"])
        # 둘 다 미달이면 갈래 안 기준 순서상 앞(매핑 순서와 무관).
        both = only_clause(make([and_record()], [fact("f1", 50, "nm"), fact("f2", 5, "W", subject="출력")],
                                [pair("advanced:1", "f2", "t2"), pair("advanced:1", "f1", "t1")]))
        self.assertEqual((both["verdict"], both["others"]), (UNDER, 1))
        self.assertEqual([(l["quote"], l["basis"]) for l in both["lines"]], [("목표 50nm", "길이 100nm 이상")])

    def test_one_line_even_with_many_comparisons(self):
        cand = or_record("core:1", "core")
        facts = [fact("f1", 50, "nm"), fact("f2", 5, "W", subject="출력"), fact("f3", 40, "nm", source_field="연구개발내용")]
        result = make([cand], facts, [pair("core:1", "f1", "tA"), pair("core:1", "f2", "tB"), pair("core:1", "f3", "tA")])
        clause = only_clause(result)
        self.assertEqual((clause["verdict"], len(clause["lines"]), clause["others"]), (UNDER, 1, 2))
        self.assertEqual(clause["lines"][0]["quote"], "목표 50nm")
        self.assertTrue(clause["lines"][0]["reason"].endswith(", 기준보다 50.0% 미달 · 외 2건"))
        self.assertTrue(clause["lines"][0]["display_reason"].endswith(" · 외 2건"))
        self.assertEqual(clause["flags"], ["갈래 확인 필요", "입력 간 목표값 불일치"])
        self.assertNotIn("확인:", clause["lines"][0]["reason"])
        self.assertEqual((result["focus"], result["under"]), ([], [clause]))

    def test_others_counts_only_compared_comparisons(self):
        clause = only_clause(make([and_record()], [fact("f1", 50, "nm"), fact("f2", 5, "초", subject="출력")],
                                  [pair("advanced:1", "f1", "t1"), pair("advanced:1", "f2", "t2")]))
        self.assertEqual((clause["verdict"], clause["others"]), (UNDER, 0))     # 단위가 달라 비교하지 못한 비교는 세지 않는다
        self.assertNotIn("외", clause["lines"][0]["reason"])
        self.assertEqual(clause["flags"], ["일부 수치만 비교"])

    def test_single_comparison_has_no_tail(self):
        clause = only_clause(one("ge", 100, 50, "nm", "nm"))
        self.assertEqual((clause["verdict"], clause["others"]), (UNDER, 0))
        self.assertEqual(clause["lines"][0]["reason"], '최종목표 "목표 50nm" ↔ 기준 길이 100nm 이상, 기준보다 50.0% 미달')


# ── R2-5 조항의 확인 표시 ──────────────────────────────────────────────────

class FlagTests(unittest.TestCase):
    CHECKS = [dict(quote="양산용에 한함", source="항목 본문")]

    def test_seven_flags_in_record_order_without_ai_read_flag(self):
        cand = record("advanced:1", "advanced",
                      [branch("bA", [threshold("tA", "길이", "ge", 100, "nm", origin="extracted"),
                                     threshold("tA2", "출력", "ge", 10, "W")]),
                       branch("bB", [threshold("tB", "질량", "le", 10, "kg")])],
                      rejected=[rejected("bB", subject="속도")], checks=self.CHECKS)
        facts = [fact("f1", None, "nm", low=90, high=120), fact("f2", 130, "nm", source_field="연구개발내용")]
        pairs = [pair("advanced:1", "f1", "tA", ambiguous=True), pair("advanced:1", "f2", "tA")]
        judged = je.judge(facts, [cand], pairs, ALL)
        self.assertEqual(judged.clauses[0]["flags"], list(je.FLAGS))          # 조항 기록에는 여덟 가지가 모두 있다
        clause = only_clause(make([cand], facts, pairs))
        self.assertEqual(clause["verdict"], OVER)
        self.assertEqual(clause["flags"], SEVEN_FLAGS)
        self.assertNotIn("AI가 읽은 기준값(원문 확인 필요)", clause["flags"])
        for line in clause["lines"]:                                          # 사유 문장 끝에는 붙이지 않는다
            for flag in SEVEN_FLAGS + ["확인:", "AI가 읽은 기준값"]:
                self.assertNotIn(flag, line["reason"])
                self.assertNotIn(flag, line["display_reason"])

    def test_check_condition_is_shown_and_ai_read_value_is_not(self):
        plain = record("core:1", "core", [branch("b1", [threshold("t1", "길이", "ge", 100, "nm", origin="extracted")])],
                       checks=self.CHECKS)
        for value, verdict in ((120, OVER), (95, NEAR), (50, UNDER)):         # 초과·근접 조항과 미달 조항 모두
            facts, pairs = [fact("f1", value, "nm")], [pair("core:1", "f1", "t1")]
            clause = only_clause(make([plain], facts, pairs))
            self.assertEqual((clause["verdict"], clause["flags"]), (verdict, ["추가 확인 조건"]))
            self.assertNotIn("확인", clause["lines"][0]["reason"])
            engine = je.judge(facts, [plain], pairs, ALL).clauses[0]
            self.assertEqual(engine["flags"], [je.FLAG_CHECK, je.FLAG_EXTRACTED])    # 상세에는 그대로 있다
        only_extracted = record("core:1", "core", [branch("b1", [threshold("t1", "길이", "ge", 100, "nm", origin="extracted")])])
        self.assertEqual(only_clause(make([only_extracted], [fact("f1", 120, "nm")], [pair("core:1", "f1", "t1")]))["flags"], [])

    def test_flags_are_a_copy(self):
        cand = or_record()
        facts, pairs = [fact("f1", 120, "nm")], [pair("advanced:1", "f1", "tA")]
        judged = je.judge(facts, [cand], pairs, ALL).to_dict()
        result = brief.build_brief(DONE, ALL, judged, records=[cand], facts=facts)
        result["focus"][0]["flags"].append("바꿈")
        self.assertNotIn("바꿈", judged["clauses"][0]["flags"])


# ── 추가 검토 필요(지금과 같다) ─────────────────────────────────────────────

class ReviewTests(unittest.TestCase):
    def test_dual_use_hidden_clauses_are_kept(self):
        cands = [no_numeric("dual_use:1A001", "이중용도 정성"), numeric("dual_use:1A002", 100, title="이중용도 수치"),
                 numeric("dual_use:1A003", 100, title="이중용도 비교됨")]
        rank = Ranker()
        result = make(cands, [fact("f1", 120, "nm")], [pair("dual_use:1A003", "f1", "t:dual_use:1A003")], rank=rank)
        self.assertEqual(ids(shown(result)), ["dual_use:1A003"])     # 비교된 것은 초과·근접 조항에만
        self.assertEqual([(r["clause_id"], r["kept_because"], r["why"]) for r in result["review"]], [
            ("dual_use:1A001", "이중용도 관련(AI 선별)", "숫자 기준 없음"),
            ("dual_use:1A002", "이중용도 관련(AI 선별)", "맞는 최종목표 수치 없음")])
        self.assertEqual(result["review"][0]["reason"], "이중용도 관련(AI 선별), 숫자 기준 없음")
        self.assertEqual(set(result["review"][0]), REVIEW_KEYS)
        self.assertEqual(result["review"][0]["family_label"], "전략물자(이중용도)")
        self.assertEqual((result["semantic"], rank.calls), ("not_needed", 0))
        self.assertEqual(result["counts"], counts(over=1, review=2))

    def test_dual_use_detail_match_is_still_dual_use_reason_and_not_a_target(self):
        rank = Ranker()
        result = make([no_numeric("dual_use:1A001")], detail={"dual_use:1A001"}, rank=rank)
        self.assertEqual(result["review"][0]["kept_because"], "이중용도 관련(AI 선별)")
        self.assertEqual((result["semantic"], rank.calls, result["counts"]["detail_match_dropped"]), ("not_needed", 0, 0))
        unavailable = make([no_numeric("dual_use:1A001")], detail={"dual_use:1A001"}, rank=None)
        self.assertEqual(unavailable["semantic"], "not_needed")
        self.assertEqual(unavailable["hints"], [])

    def test_detail_match_needs_ai_and_top_rank(self):
        target = "core:target"
        cands = [no_numeric(target, "세부 항목")]

        def run(detail, position):
            core = filler("core", 10)
            core.insert(position, target)
            rank = Ranker(dict(core=core))
            return make(cands, detail={target} if detail else (), rank=rank), rank

        both, rank = run(True, 0)
        self.assertEqual([(r["clause_id"], r["kept_because"], r["why"]) for r in both["review"]],
                         [(target, "세부 기술 일치(AI·검색)", "숫자 기준 없음")])
        self.assertEqual(both["review"][0]["reason"], "세부 기술 일치(AI·검색), 숫자 기준 없음")
        self.assertEqual((both["semantic"], rank.calls), ("used", 1))
        self.assertEqual(both["counts"], counts(review=1))
        fifth, _ = run(True, 4)
        self.assertEqual(len(fifth["review"]), 1)
        sixth, _ = run(True, 5)                         # 6위
        self.assertEqual(sixth["review"], [])
        self.assertEqual(sixth["counts"], counts(hidden=1, dropped=1))
        self.assertEqual(sixth["semantic"], "used")
        self.assertEqual(sixth["hints"], [])
        ai_only, _ = run(True, 10)                      # AI만 참(순위 밖)
        self.assertEqual((ai_only["review"], ai_only["counts"]["detail_match_dropped"]), ([], 1))
        rank_only, rank = run(False, 0)                 # 순위만 안(AI는 세부 일치 아님)
        self.assertEqual((rank_only["review"], rank_only["counts"]["detail_match_dropped"]), ([], 0))
        self.assertEqual((rank_only["semantic"], rank.calls), ("not_needed", 0))
        self.assertEqual(rank_only["counts"]["hidden"], 1)

    def test_rank_is_within_the_same_family(self):
        target = "military:ML1"
        rank = Ranker(dict(core=[target] * 1, military=filler("military", 5) + [target]))
        result = make([no_numeric(target)], detail={target}, rank=rank)
        self.assertEqual(result["review"], [])
        rank = Ranker(dict(advanced=filler("advanced", 5) + [target], military=[target]))
        self.assertEqual(len(make([no_numeric(target)], detail={target}, rank=rank)["review"]), 1)

    def test_semantic_unavailable(self):
        cands = [no_numeric("core:1"), no_numeric("dual_use:1A001"), numeric("advanced:1", 100)]
        for label, rank in (("엔진 없음", None), ("쓸 수 없음", Ranker(available=False)),
                            ("계산 중 오류", Ranker(error=RuntimeError("합성 실패"))),
                            ("모양이 다름", lambda: dict(available=True, reason="", ranking=None))):
            with self.subTest(label):
                result = make(cands, detail={"core:1", "advanced:1"}, rank=rank, dropped=2)
                self.assertEqual(result["semantic"], "unavailable")
                self.assertEqual(result["hints"], [HINT_SEMANTIC, "버린 최종목표 사양·매핑 2건 — 상세 보기에서 확인"])
                # 이중용도 규칙은 그대로, 세부 일치 대상은 남기지 않고 건수로 드러낸다.
                self.assertEqual([r["clause_id"] for r in result["review"]], ["dual_use:1A001"])
                self.assertEqual(result["counts"], counts(review=1, hidden=2, dropped=2))

    def test_rank_is_called_once_at_most(self):
        cands = [no_numeric("core:1"), no_numeric("core:2"), no_numeric("advanced:1"), no_numeric("military:1"),
                 numeric("core:3", 100)]
        rank = Ranker(dict(core=["core:1", "core:2"], advanced=["advanced:1"], military=filler("military", 6)))
        result = make(cands, [fact("f1", 120, "nm")], [pair("core:3", "f1", "t:core:3")],
                      detail={"core:1", "core:2", "advanced:1", "military:1"}, rank=rank)
        self.assertEqual(rank.calls, 1)                 # 따질 조항이 여럿이어도 한 번만 부른다
        self.assertEqual(ids(result["review"]), ["advanced:1", "core:1", "core:2"])
        self.assertEqual(result["counts"], counts(over=1, review=3, hidden=1, dropped=1))

    def test_not_needed_without_targets_even_without_engine(self):
        result = make([no_numeric("core:1"), numeric("advanced:1", 100)], [fact("f1", 120, "nm")],
                      [pair("advanced:1", "f1", "t:advanced:1")], detail={"advanced:1"}, rank=None)
        # 세부 일치로 답했지만 숫자로 비교된 조항은 초과·근접 조항에만 있고, 따질 조항이 아니다.
        self.assertEqual(result["semantic"], "not_needed")
        self.assertEqual(result["hints"], [])
        self.assertEqual(ids(result["focus"]), ["advanced:1"])
        self.assertEqual(result["counts"], counts(over=1, hidden=1))

    def test_why_reasons_and_their_order(self):
        unit_both = record("dual_use:U", "dual_use", [branch("bU", [threshold("tU1", "길이", "ge", 100, "m"),
                                                                     threshold("tU2", "온도", "ge", 300, "K")])])
        zero_and_kind = record("dual_use:Z", "dual_use", [branch("bZ", [threshold("tZ1", "길이", "ge", 0, "nm"),
                                                                         threshold("tZ2", "출력", "ge", 10, "W")])])
        cands = [no_numeric("dual_use:N"), numeric("dual_use:F", 100), numeric("dual_use:K", 100, unit="m"),
                 numeric("dual_use:C", 100, unit="K"), unit_both, numeric("dual_use:0", 0), failed("dual_use:R"),
                 zero_and_kind]
        facts = [fact("fk", 3, "초"), fact("fc", 30, "℃"), fact("fz", -1, "nm"), fact("fw", 3, "초", subject="출력")]
        pairs = [pair("dual_use:K", "fk", "t:dual_use:K"), pair("dual_use:C", "fc", "t:dual_use:C"),
                 pair("dual_use:U", "fk", "tU1"), pair("dual_use:U", "fc", "tU2"), pair("dual_use:0", "fz", "t:dual_use:0"),
                 pair("dual_use:Z", "fz", "tZ1"), pair("dual_use:Z", "fw", "tZ2")]
        result = make(cands, facts, pairs)
        why = {r["clause_id"]: r["why"] for r in result["review"]}
        self.assertEqual(why, {"dual_use:N": "숫자 기준 없음", "dual_use:F": "맞는 최종목표 수치 없음",
                               "dual_use:K": "단위 비교 불가", "dual_use:C": "단위 비교 불가", "dual_use:U": "단위 비교 불가",
                               "dual_use:0": "기준값 0 비교 불가", "dual_use:R": "기준값 채택 실패(원문 확인 필요)",
                               "dual_use:Z": "단위 비교 불가 · 기준값 0 비교 불가"})
        clause = {c["clause_id"]: c for c in je.judge(facts, cands, pairs, ALL).clauses}
        self.assertEqual(clause["dual_use:U"]["reason"], "비교 불가(단위 종류 다름), 비교 불가(단위 환산 불가)")
        self.assertEqual(clause["dual_use:Z"]["reason"], "비교 불가(기준값 0), 비교 불가(단위 종류 다름)")
        self.assertEqual(result["review"][7]["reason"], "이중용도 관련(AI 선별), 단위 비교 불가 · 기준값 0 비교 불가")

    def test_review_order_family_then_judge_order(self):
        cands = [no_numeric("military:ML1"), no_numeric("dual_use:2A"), no_numeric("core:y"), no_numeric("dual_use:1A"),
                 no_numeric("advanced:z")]
        rank = Ranker(dict(military=["military:ML1"], core=["core:y"], advanced=["advanced:z"]))
        result = make(cands, detail={"military:ML1", "core:y", "advanced:z"}, rank=rank)
        self.assertEqual([r["clause_id"] for r in result["review"]],
                         ["advanced:z", "core:y", "dual_use:2A", "dual_use:1A", "military:ML1"])
        self.assertEqual(rank.calls, 1)

    def test_unit_mismatch_outside_rules_is_hidden_and_counted(self):
        cand = numeric("core:1", 100, unit="m")
        result = make([cand], [fact("f1", 3, "초")], [pair("core:1", "f1", "t:core:1")])
        self.assertEqual((shown(result), result["review"]), ([], []))
        self.assertEqual(result["counts"]["hidden"], 1)
        kept = make([cand], [fact("f1", 3, "초")], [pair("core:1", "f1", "t:core:1")], detail={"core:1"},
                    rank=Ranker(dict(core=["core:1"])))
        self.assertEqual([(r["kept_because"], r["why"]) for r in kept["review"]], [("세부 기술 일치(AI·검색)", "단위 비교 불가")])

    def test_hidden_counts_every_ai_candidate_not_shown(self):
        cands = [numeric("advanced:1", 100), no_numeric("core:1"), no_numeric("dual_use:1"), numeric("core:2", 100)]
        decisions = decisions_for(cands) + [dict(clause_id="core:not-in-table", candidate=True, detail_match=False, reason=""),
                                            dict(clause_id="core:9", candidate=False, detail_match=False, reason="")]
        result = make(cands, [fact("f1", 120, "nm"), fact("f2", 50, "nm")],
                      [pair("advanced:1", "f1", "t:advanced:1"), pair("core:2", "f2", "t:core:2")], decisions=decisions)
        # 넣지 않은 관련 조항: 초과·근접·미달 조항도 추가 검토 필요도 아닌 AI 선별 조항(정성 core:1, 표에 없는 후보).
        self.assertEqual(result["counts"], counts(over=1, under=1, review=1, hidden=2))

    def test_review_is_not_a_verdict(self):
        cands = [no_numeric("dual_use:1"), no_numeric("military:1")]
        result = make(cands, detail={"military:1"}, rank=Ranker(dict(military=["military:1"])))
        self.assertEqual(len(result["review"]), 2)
        self.assertEqual(result["families"], dict(advanced=UNDER, core=UNDER, dual_use=UNDER, military=UNDER))
        self.assertEqual((result["overall"], result["group"]), (UNDER, "other"))
        self.assertEqual((result["reason"], result["empty_message"]), ("사양이 겹치는 고시 조항 없음", EMPTY))


# ── 안내 줄 ─────────────────────────────────────────────────────────────

class HintTests(unittest.TestCase):
    def test_count_line_skips_zero_counts(self):
        def hints(dropped, warnings):
            return make([numeric("advanced:1", 100)], dropped=dropped, warnings=warnings)["hints"]
        self.assertEqual(hints(0, 0), [])
        self.assertEqual(hints(3, 0), ["버린 최종목표 사양·매핑 3건 — 상세 보기에서 확인"])
        self.assertEqual(hints(0, 2), ["선택 칸 경고 2건 — 상세 보기에서 확인"])
        self.assertEqual(hints(3, 2), ["버린 최종목표 사양·매핑 3건 · 선택 칸 경고 2건 — 상세 보기에서 확인"])

    def test_order_semantic_line_first_and_no_candidates_line_is_gone(self):
        result = status_brief(pipeline.STATUS_NO_CANDIDATES, ["core"], dropped_count=1, option_warning_count=1)
        self.assertEqual(result["hints"], ["버린 최종목표 사양·매핑 1건 · 선택 칸 경고 1건 — 상세 보기에서 확인"])
        self.assertEqual(status_brief(pipeline.STATUS_NO_CANDIDATES, ["core"])["hints"], [])
        semantic = make([no_numeric("core:1")], detail={"core:1"}, rank=None, dropped=1)
        self.assertEqual(semantic["hints"], [HINT_SEMANTIC, "버린 최종목표 사양·매핑 1건 — 상세 보기에서 확인"])

    def test_no_common_notices_in_any_status(self):
        for status in pipeline.STATUSES:
            judged = je.judge([], [], [], ["core"]).to_dict() if status == DONE else None
            data = brief.build_brief(status, ["core"], judged)
            self.assertEqual(tuple(data), BRIEF_KEYS, status)
            for gone in ("notices", "summary_cell", "items"):
                self.assertNotIn(gone, data)
            self.assertNotIn("items", data["counts"])
            self.assertEqual(tuple(data["counts"]), brief.COUNT_KEYS)

    def test_unknown_status_is_error(self):
        with self.assertRaises(ValueError):
            brief.build_brief("모르는 상태", ["core"], None)
        with self.assertRaises(ValueError):
            brief.build_brief(DONE, ["core"], None)
        for bad in (-1, 1.0, True, None):
            with self.assertRaises(ValueError):
                brief.build_brief(pipeline.STATUS_ERROR, ["core"], None, dropped_count=bad)


# ── R4·R7-3 종합 건수와 과제 순서 ────────────────────────────────────────────

class TallyTests(unittest.TestCase):
    @staticmethod
    def over():
        return one("ge", 100, 120)

    @staticmethod
    def near():
        return one("ge", 100, 95)

    @staticmethod
    def under():
        return one("ge", 100, 50)

    @staticmethod
    def none():
        return make([no_numeric("core:1")])

    def test_counts_groups_and_order(self):
        briefs = [self.under(), self.near(), self.over(), status_brief(pipeline.STATUS_ERROR),
                  status_brief(pipeline.STATUS_NO_FACTS), self.over(), status_brief(pipeline.STATUS_CANCELLED),
                  status_brief(pipeline.STATUS_NO_CANDIDATES), self.near(), self.none()]
        result = brief.tally_briefs(briefs)
        self.assertEqual(set(result), {"tally", "groups", "members"})
        self.assertEqual(result["tally"], [dict(kind="over", label="고시 사양 초과", count=2),
                                           dict(kind="near", label="고시 사양 근접", count=2),
                                           dict(kind="under", label="고시 사양 미달", count=4),
                                           dict(kind="unjudged", label="오류·취소(판정 없음)", count=2)])
        # 중점: 종합 초과 → 종합 근접, 같으면 받은 순서. 판정 못 함·그 밖: 받은 순서.
        self.assertEqual(result["groups"], dict(focus=[2, 5, 1, 8], unjudged=[3, 6], other=[0, 4, 7, 9]))
        self.assertEqual(list(result["groups"]), ["focus", "unjudged", "other"])
        self.assertEqual(sum(entry["count"] for entry in result["tally"]), len(briefs))
        positions = [p for group in result["groups"].values() for p in group]
        self.assertEqual(sorted(positions), list(range(len(briefs))))          # 모든 과제가 정확히 한 묶음에
        # 종합 건수 항목마다 그 건수에 든 과제(받은 순서). 길이는 count와 같고 모든 과제가 정확히 한 항목에 든다.
        self.assertEqual(result["members"], dict(over=[2, 5], near=[1, 8], under=[0, 4, 7, 9], unjudged=[3, 6]))
        self.assertEqual(list(result["members"]), ["over", "near", "under", "unjudged"])
        for entry in result["tally"]:
            self.assertEqual(len(result["members"][entry["kind"]]), entry["count"], entry["kind"])
        self.assertEqual(result["members"]["over"] + result["members"]["near"], result["groups"]["focus"])
        self.assertEqual(brief.tally_text(result["tally"]),
                         "고시 사양 초과 2건 · 고시 사양 근접 2건 · 고시 사양 미달 4건 · 오류·취소(판정 없음) 2건")
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_unjudged_entry_is_left_out_when_zero(self):
        briefs = [self.under(), self.over(), status_brief(pipeline.STATUS_NO_FACTS), self.none()]
        result = brief.tally_briefs(briefs)
        self.assertEqual([(e["kind"], e["count"]) for e in result["tally"]], [("over", 1), ("near", 0), ("under", 3)])
        self.assertEqual(result["groups"], dict(focus=[1], unjudged=[], other=[0, 2, 3]))
        self.assertEqual(result["members"], dict(over=[1], near=[], under=[0, 2, 3], unjudged=[]))   # 0건 항목도 빈 목록으로 있다
        self.assertEqual(brief.tally_text(result["tally"]), "고시 사양 초과 1건 · 고시 사양 근접 0건 · 고시 사양 미달 3건")

    def test_all_errors(self):
        briefs = [status_brief(pipeline.STATUS_ERROR), status_brief(pipeline.STATUS_CANCELLED),
                  status_brief(pipeline.STATUS_ERROR)]
        result = brief.tally_briefs(briefs)
        self.assertEqual(brief.tally_text(result["tally"]),
                         "고시 사양 초과 0건 · 고시 사양 근접 0건 · 고시 사양 미달 0건 · 오류·취소(판정 없음) 3건")
        self.assertEqual(result["groups"], dict(focus=[], unjudged=[0, 1, 2], other=[]))

    def test_errors_and_cancelled_are_never_counted_as_under(self):
        briefs = [status_brief(pipeline.STATUS_ERROR), status_brief(pipeline.STATUS_CANCELLED), self.under()]
        result = brief.tally_briefs(briefs)
        by_kind = {entry["kind"]: entry["count"] for entry in result["tally"]}
        self.assertEqual(by_kind, dict(over=0, near=0, under=1, unjudged=2))

    def test_empty_run(self):
        result = brief.tally_briefs([])
        self.assertEqual([(e["kind"], e["count"]) for e in result["tally"]], [("over", 0), ("near", 0), ("under", 0)])
        self.assertEqual(result["groups"], dict(focus=[], unjudged=[], other=[]))

    def test_accepts_any_iterable_and_does_not_change_input(self):
        briefs = [self.over(), self.under()]
        before = json.dumps(briefs, ensure_ascii=False)
        self.assertEqual(brief.tally_briefs(iter(briefs)), brief.tally_briefs(briefs))
        self.assertEqual(json.dumps(briefs, ensure_ascii=False), before)

    def test_unknown_or_inconsistent_values_are_errors(self):
        good = self.over()
        bad_cases = [dict(good, group="모르는 묶음"), dict(good, group=None), dict(good, overall="모르는 판정"),
                     dict(good, overall="사양 미달 또는 무관", group="other"), dict(good, overall="최종목표 수치 없음", group="other"),
                     dict(good, overall=EXCLUDED, group="other"), dict(good, overall=["고시 사양 초과"]),
                     dict(good, group="other"),                                  # 종합 초과인데 그 밖 묶음
                     dict(self.under(), group="focus"),                          # 종합 미달인데 중점 묶음
                     dict(status_brief(pipeline.STATUS_ERROR), group="other"),   # 오류를 미달 쪽으로 세지 않는다
                     {k: v for k, v in good.items() if k != "group"}, {k: v for k, v in good.items() if k != "overall"},
                     None, "고시 사양 초과"]
        for bad in bad_cases:
            with self.assertRaises(ValueError, msg=repr(bad)[:80]):
                brief.tally_briefs([self.under(), bad])
        with self.assertRaises(ValueError):
            brief.tally_text([dict(kind="over", label="고시 사양 초과", count=-1)])
        with self.assertRaises(ValueError):
            brief.tally_text([dict(kind="모름", label="고시 사양 초과", count=1)])

    def test_tally_through_pipeline_results(self):
        results = [
            pipeline.run_task(tp.TASK, ALL, MockModel(facts=tp.FACTS, candidates=set()), tp.TABLE, tp.INDEX),
            pipeline.run_task(tp.TASK, ALL, MockModel(facts=tp.FACTS, candidates={"advanced:item:001"}), tp.TABLE, tp.INDEX),
            pipeline.cancelled_result(tp.TASK, ALL),
            pipeline.run_task(tp.TASK, ALL, MockModel(facts=[]), tp.TABLE, tp.INDEX),
            pipeline.error_result(tp.TASK, ALL, "합성 오류"),
        ]
        result = brief.tally_briefs([r.to_dict()["brief"] for r in results])
        self.assertEqual(brief.tally_text(result["tally"]),
                         "고시 사양 초과 1건 · 고시 사양 근접 0건 · 고시 사양 미달 2건 · 오류·취소(판정 없음) 2건")
        self.assertEqual(result["groups"], dict(focus=[1], unjudged=[2, 4], other=[0, 3]))


# ── 과제 흐름: 검색 글·진행 이벤트·보내는 내용 ─────────────────────────────────

class PipelineSemanticTests(unittest.TestCase):
    CANDIDATES = {"advanced:item:001", "advanced:item:002", "core:item:001", "dual_use:control:1A003",
                  "dual_use:control:1A004", "military:item:001"}

    def model(self, detail=("military:item:001", "core:item:001")):
        return MockModel(facts=tp.FACTS, candidates=self.CANDIDATES, detail_matches=set(detail))

    def test_done_brief_through_pipeline(self):
        engine = FakeEngine(dict(military=["military:item:001"], core=filler("core", 5) + ["core:item:001"]))
        result = pipeline.run_task(tp.TASK, ALL, self.model(), tp.TABLE, tp.INDEX, search_engine=engine)
        self.assertEqual(result.status, DONE)
        data = result.to_dict()["brief"]
        self.assertEqual(data["families"], dict(advanced=OVER, core=UNDER, dual_use=OVER, military=UNDER))
        self.assertEqual((data["overall"], data["group"]), (OVER, "focus"))
        self.assertEqual(data["reason"], "국가첨단전략기술 16나노 이하급 D램 외 1건")
        self.assertEqual([(c["clause_id"], c["verdict"], c["flags"], c["others"], [l["reason"] for l in c["lines"]])
                          for c in data["focus"]], [
            ("advanced:item:001", OVER, ["추가 확인 조건"], 0,
             ['최종목표 "14 nm" ↔ 기준 D램 공정노드 16nm 이하, 기준보다 12.5% 초과']),
            ("dual_use:control:1A003", OVER, ["갈래 확인 필요"], 0,
             ['목표 발췌 "0.3 mm" ↔ 기준 두께 0.254mm 초과, 기준보다 18.1% 초과'])])
        self.assertEqual(data["focus"][0]["lines"][0]["target"], "14 nm")
        self.assertEqual(data["focus"][0]["lines"][0]["verdict"], OVER)
        self.assertEqual(data["focus"][1]["code"], "1A003")
        self.assertEqual(data["under"], [])
        self.assertEqual([(r["clause_id"], r["reason"]) for r in data["review"]], [
            ("dual_use:control:1A004", "이중용도 관련(AI 선별), 맞는 최종목표 수치 없음"),
            ("military:item:001", "세부 기술 일치(AI·검색), 기준값 채택 실패(원문 확인 필요)")])
        self.assertEqual(data["counts"], counts(over=2, review=2, hidden=2, dropped=1))
        self.assertEqual(data["semantic"], "used")
        self.assertEqual(data["hints"], [])
        self.assertEqual(data["empty_message"], "")
        self.assertEqual(engine.texts, ["\n".join([tp.TASK["title"], tp.FINAL_GOAL, tp.CONTENT])])
        json.dumps(data, ensure_ascii=False, allow_nan=False)

    def test_search_text(self):
        self.assertEqual(brief.semantic_text(dict(title="과제", final_goal="목표", rnd_content="내용", excerpt="발췌")),
                         "과제\n목표\n내용")
        self.assertEqual(brief.semantic_text(dict(title="과제", final_goal="", rnd_content="내용", excerpt="발췌")), "과제\n내용")
        self.assertEqual(brief.semantic_text(dict(title="과제", final_goal="  ", rnd_content="", excerpt="발췌 글")),
                         "과제\n발췌 글")
        engine = FakeEngine()
        excerpt_task = dict(title="발췌 과제", excerpt=tp.EXCERPT)
        facts = [tp.fact("e1", tp.EXCERPT, ai_stages.SOURCE_EXCERPT, "0.3 mm", "두께", "0.3", "0.3", "mm")]
        model = MockModel(facts=facts, candidates={"core:item:001"}, detail_matches={"core:item:001"})
        pipeline.run_task(excerpt_task, ALL, model, tp.TABLE, tp.INDEX, search_engine=engine)
        self.assertEqual(engine.texts, ["발췌 과제\n" + tp.EXCERPT])

    def test_search_only_when_needed(self):
        engine = FakeEngine()
        pipeline.run_task(tp.TASK, ALL, self.model(detail=()), tp.TABLE, tp.INDEX, search_engine=engine)
        pipeline.run_task(tp.TASK, ALL, MockModel(facts=[]), tp.TABLE, tp.INDEX, search_engine=engine)
        pipeline.run_task(tp.TASK, ALL, MockModel(facts=tp.FACTS, candidates=set(), detail_matches=self.CANDIDATES), tp.TABLE,
                          tp.INDEX, search_engine=engine)
        pipeline.run_task(tp.TASK, ALL, MockModel(facts=tp.FACTS, faults={"screen": ["shape", "shape"]}), tp.TABLE, tp.INDEX,
                          search_engine=engine)
        # 세부 일치로 답한 조항이 이중용도뿐이면 따질 조항이 없다.
        dual = pipeline.run_task(tp.TASK, ALL, self.model(detail=("dual_use:control:1A004",)), tp.TABLE, tp.INDEX,
                                 search_engine=engine)
        self.assertEqual(dual.brief["semantic"], "not_needed")
        self.assertEqual(engine.texts, [])

    def test_no_engine_or_unavailable_engine(self):
        for engine in (None, FakeEngine(available=False)):
            result = pipeline.run_task(tp.TASK, ALL, self.model(), tp.TABLE, tp.INDEX, search_engine=engine)
            self.assertEqual(result.brief["semantic"], "unavailable")
            self.assertEqual(result.brief["hints"], [HINT_SEMANTIC])
            self.assertEqual([r["clause_id"] for r in result.brief["review"]], ["dual_use:control:1A004"])
            self.assertEqual(result.brief["counts"]["detail_match_dropped"], 2)

    def test_progress_event_only_for_the_semantic_check(self):
        events = []
        pipeline.run_task(tp.TASK, ALL, self.model(), tp.TABLE, tp.INDEX, search_engine=FakeEngine(), progress=events.append)
        semantic = [e for e in events if e["message"] == "세부 기술 일치 확인 중"]
        self.assertEqual(semantic, [dict(stage=ai_stages.STAGE_SCREEN, message="세부 기술 일치 확인 중", completed=0, total=1),
                                    dict(stage=ai_stages.STAGE_SCREEN, message="세부 기술 일치 확인 중", completed=1, total=1)])
        # 마지막 진행 값이 1/1이라 브리지의 완료 이벤트가 0/0을 이어 쓰지 않는다.
        self.assertEqual(events[-1], semantic[-1])
        self.assertEqual(ai_stages.STAGE_LABELS[events[-1]["stage"]], "관련 고시 조항 선별")
        for case in (dict(search_engine=None), dict(search_engine=FakeEngine(), detail=())):
            events = []
            model = self.model(detail=case.pop("detail", ("military:item:001",)))
            pipeline.run_task(tp.TASK, ALL, model, tp.TABLE, tp.INDEX, progress=events.append, **case)
            self.assertFalse(any(e["message"] == "세부 기술 일치 확인 중" for e in events))

    def test_requests_unchanged_and_warnings_not_sent(self):
        plain_model, extra_model = self.model(), self.model()
        plain = pipeline.run_task(tp.TASK, ALL, plain_model, tp.TABLE, tp.INDEX)
        warnings = [dict(row_number=None, field="정부지원연구개발비", value="약 3억", message="정부지원연구개발비 값 확인 필요 — 약 3억")]
        extra = pipeline.run_task(tp.TASK, ALL, extra_model, tp.TABLE, tp.INDEX, search_engine=FakeEngine(dict(military=["military:item:001"])),
                                  option_warnings=warnings)
        self.assertEqual([(r["stage"], r["system"], r["user"]) for r in extra_model.requests],
                         [(r["stage"], r["system"], r["user"]) for r in plain_model.requests])
        for request in extra_model.requests:
            self.assertNotIn("약 3억", request["user"])
            self.assertNotIn("세부 기술 일치 확인", request["user"])
        self.assertEqual(extra.brief["hints"], ["선택 칸 경고 1건 — 상세 보기에서 확인"])
        # 판정·건수·상태는 검색 엔진·선택 칸 경고와 무관하게 같다.
        for name in ("status", "families", "overall", "counts", "flagged_clause_count", "judge", "calls", "candidate_ids"):
            self.assertEqual(getattr(extra, name), getattr(plain, name), name)

    def test_search_text_is_not_kept_in_result(self):
        marker = "검색글보관시험표지"
        task = dict(tp.TASK, rnd_content=f"{marker} 메모리 공정 개선")
        engine = FakeEngine()
        result = pipeline.run_task(task, ALL, self.model(), tp.TABLE, tp.INDEX, search_engine=engine)
        self.assertIn(marker, engine.texts[0])
        self.assertNotIn(marker, json.dumps(result.to_dict(), ensure_ascii=False))


# ── 실제 내장 의미 모델·조항 벡터(오프라인) ─────────────────────────────────────

CATALOGUE = REAL_TABLE = ENGINE = None
DRAM = dict(title="D램 적층조립 공정 고도화", final_goal="HBM용 D램 다이를 16단 이상 적층하는 조립 기술과 검사 기술 개발",
            rnd_content="실리콘관통전극(TSV) 기반 적층조립, 하이브리드 본딩 공정, 적층 후 전기적 검사 장비 개발",
            utilization="메모리 제조사에 공정 기술 이전")
AMOLED = dict(title="고해상도 AMOLED 패널 기술 개발", final_goal="화소밀도 2000ppi 이상의 AMOLED 디스플레이 패널 구현",
              rnd_content="마이크로 디스플레이용 OLED 증착 공정과 화소 구동 회로 설계", utilization="디스플레이 업체 기술 이전")
LASER = dict(title="고출력 광섬유 레이저 개발", final_goal="평균 출력 10kW 이상의 연속파 광섬유 레이저 발진기 개발",
             rnd_content="레이저 이득 매질, 펌프 광원, 빔 품질 개선 및 출력 안정화 기술", utilization="가공 장비 업체 기술 이전")


def setUpModule():
    global CATALOGUE, REAL_TABLE, ENGINE
    CATALOGUE = load_catalogue()
    REAL_TABLE = load_threshold_table(catalogue=CATALOGUE)
    ENGINE = ns.SearchEngine(CATALOGUE, REAL_TABLE)


class RealSemanticTests(unittest.TestCase):
    """실제 고시 조항 ID를 쓰는 합성 표(조항 글은 실제 색인, 기준값은 합성)로 과제 흐름을 돌린다."""

    def setUp(self):
        ranking = ENGINE.semantic_ranking("\n".join([DRAM["title"], DRAM["final_goal"], DRAM["rnd_content"]]))
        self.assertTrue(ranking["available"], ranking["reason"])
        self.ranking = ranking["ranking"]
        self.sixth = self.ranking["core"][5]
        records = [tp.numeric_record("advanced:item:002", "advanced", "16나노 이하급 D램에 해당하는 적층조립기술 및 검사기술",
                                     "D램 공정노드", "le", "16", "nm"),
                   tp.text_record("core:item:002", "core", "D램에 해당되는 적층조립기술 및 검사 기술"),
                   tp.text_record(self.sixth, "core", "순위 6위 조항"),
                   tp.text_record("dual_use:control:3B001", "dual_use", "반도체 제조 장비")]
        self.table = tp.make_table(records)
        self.index = [dict(clause_id=r["clause_id"], family=r["family"],
                           code="3B001" if r["family"] == "dual_use" else "", title=r["title"], field="합성 분야")
                      for r in records]
        self.detail = {"advanced:item:002", "core:item:002", self.sixth}

    def model(self):
        return MockModel(candidates={r["clause_id"] for r in self.index}, detail_matches=self.detail)

    def test_dram_task_keeps_detail_matches_in_top5(self):
        self.assertIn("core:item:002", self.ranking["core"][:5])
        self.assertIn("advanced:item:002", self.ranking["advanced"][:5])
        result = pipeline.run_task(DRAM, ALL, self.model(), self.table, self.index, search_engine=ENGINE)
        self.assertEqual(result.status, DONE)
        data = result.brief
        self.assertEqual(data["semantic"], "used")
        self.assertEqual([(r["clause_id"], r["reason"]) for r in data["review"]], [
            ("advanced:item:002", "세부 기술 일치(AI·검색), 맞는 최종목표 수치 없음"),
            ("core:item:002", "세부 기술 일치(AI·검색), 숫자 기준 없음"),
            ("dual_use:control:3B001", "이중용도 관련(AI 선별), 숫자 기준 없음")])
        self.assertEqual(data["counts"], counts(review=3, hidden=1, dropped=1))
        self.assertEqual((data["overall"], data["group"], data["reason"]), (UNDER, "other", "사양이 겹치는 고시 조항 없음"))
        self.assertEqual(data["hints"], [])
        self.assertRegex(ENGINE.semantic_model_fingerprint, r"\A[0-9a-f]{64}\Z")

    def test_model_missing_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = ns.SearchEngine(CATALOGUE, REAL_TABLE, model_folder=Path(folder) / "없는 모델")
            result = pipeline.run_task(DRAM, ALL, self.model(), self.table, self.index, search_engine=engine)
        data = result.brief
        self.assertEqual(data["semantic"], "unavailable")
        self.assertEqual(data["hints"], [HINT_SEMANTIC])
        self.assertEqual([r["clause_id"] for r in data["review"]], ["dual_use:control:3B001"])
        self.assertEqual(data["counts"], counts(review=1, hidden=3, dropped=3))
        self.assertEqual((engine.semantic_model_fingerprint, engine.semantic_vectors_fingerprint), ("", ""))

    def test_batch_with_shared_engine_is_order_independent(self):
        rows = [dict(task, row_number=i + 2, rnd_stage="", gov_fund="") for i, task in
                enumerate([DRAM, AMOLED, LASER, dict(DRAM, title="D램 적층조립 검사"), AMOLED, LASER])]
        sequential = [pipeline.run_task(batch._row_task(row), ALL, self.model(), self.table, self.index,
                                        search_engine=ENGINE).brief for row in rows]
        for workers in (3, 1):
            results = batch.run_batch(rows, ALL, self.model, self.table, self.index, workers=workers, search_engine=ENGINE)
            self.assertEqual([r.brief for r in results], sequential, workers)
        self.assertTrue(all(b["semantic"] == "used" for b in sequential))
        self.assertNotEqual(sequential[0]["review"], sequential[1]["review"])


if __name__ == "__main__":
    unittest.main()
