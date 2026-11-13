"""규칙 기반 모의 모델 클라이언트. 실제 AI가 아니며 네트워크를 쓰지 않는다.

`ai_stages`가 보내는 요청 JSON(`stage`가 extract|screen|pair)을 읽어 그럴듯한 응답을 만들고,
받은 요청(지시문·본문·payload·temperature)을 모두 `requests`에 기록한다.
`faults`로 특정 단계에서 깨진 응답을 n번 내도록 정할 수 있다(단계별 목록을 앞에서부터 소비).

깨진 응답 종류(faults 값):
    shape     → 필요한 키가 없는 객체
    not_json  → llm_client.InvalidResponseError(JSON 하나를 받지 못한 상황)
    list      → 객체가 아닌 배열
    missing   → screen: 묶음의 첫 조항 결정 누락 / extract·pair: 목록이 아닌 값
    unknown   → screen: 모르는 clause_id 결정 추가
    duplicate → screen: 같은 clause_id 결정 두 번
    detail_missing  → screen: 첫 결정에서 detail_match 키를 뺌
    detail_not_bool → screen: 첫 결정의 detail_match를 참/거짓이 아닌 글("true")로
    detail_conflict → screen: 첫 결정을 candidate 거짓·detail_match 참으로
faults 목록에 None을 두면 그 차례 요청은 정상 응답이다(예: [None, "detail_missing"] → 둘째 요청만 깨짐).

추출 응답의 수치는 1.3.1 모양의 여덟 키(fact_id·subject·value_text·low·high·unit·source_field·quote)이며 글자 위치
(start·end)를 보내지 않는다(위치는 프로그램이 찾는다). 위치를 보내는 모델을 흉내 내려면 facts에 start·end를 넣거나
transform으로 붙인다(프로그램은 무시해야 한다).

선별 응답의 detail_match(세부 기술 일치)는 `detail_matches`로 정한다. 기본은 모두 거짓이고, 후보가 아닌
조항은 언제나 거짓이다(candidate 거짓인데 detail_match 참은 모양 오류라 일부러 낼 때는 faults를 쓴다).
"""
from copy import deepcopy
import json
import re

from llm_client import InvalidResponseError

_NUMBER_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*([A-Za-zμ%℃°]+)?")
# 최종 목표가 아닌 문장 표지. 모의 규칙은 이 낱말이 든 조각을 건너뛴다.
_NOT_FINAL = re.compile(r"현재|기존|보유|연차|단계|경쟁")


def _overlap(a, b):
    a, b = a.strip().lower(), b.strip().lower()
    return bool(a) and bool(b) and (a in b or b in a)


class MockModel:
    """ask_json(system, user_json_text, temperature) 인터페이스의 모의 구현."""

    def __init__(self, *, facts=None, candidates=None, detail_matches=None, faults=None, transform=None):
        """facts: extract 응답으로 그대로 돌려줄 수치 목록(None이면 규칙 추출).
        candidates: screen에서 후보로 답할 clause_id 집합(None이면 물리량·제목 겹침 규칙).
        detail_matches: screen 후보 중 detail_match를 참으로 답할 조항. None이면 모두 거짓, clause_id 모음이면
            그 조항, 호출 가능 rule(task, clause) -> 참/거짓이면 그 결과(task는 요청의 task — 키 '연구개발과제명'
            등 다섯 글, clause는 요청의 조항 색인 원소). rule은 후보인 조항에만 불린다.
        faults: {stage: [kind, ...]}. transform: (stage, payload, out) -> out 후처리."""
        self.facts = deepcopy(list(facts)) if facts is not None else None
        self.candidates = set(candidates) if candidates is not None else None
        if detail_matches is None or callable(detail_matches):
            self.detail_matches = detail_matches
        else:
            self.detail_matches = set(detail_matches)
        self.faults = {stage: list(kinds) for stage, kinds in (faults or {}).items()}
        self.transform = transform
        self.requests = []

    # ── 인터페이스 ───────────────────────────────────────────────
    def ask_json(self, system_prompt, user_prompt, temperature=None):
        payload = json.loads(user_prompt)
        stage = payload.get("stage")
        self.requests.append(dict(stage=stage, system=system_prompt, user=user_prompt,
                                  payload=deepcopy(payload), temperature=temperature))
        kinds = self.faults.get(stage) or []
        kind = kinds.pop(0) if kinds else None
        if kind == "not_json":
            raise InvalidResponseError()
        if kind == "shape":
            return {"oops": []}
        if kind == "list":
            return []
        if stage == "extract":
            out = self._extract(payload)
        elif stage == "screen":
            out = self._screen(payload)
        elif stage == "pair":
            out = self._pair(payload)
        else:
            out = {}
        out = self._apply_fault(stage, kind, out, payload)
        return self.transform(stage, payload, out) if self.transform else out

    # ── 단계별 규칙 ──────────────────────────────────────────────
    def _extract(self, payload):
        if self.facts is not None:
            return {"facts": deepcopy(self.facts)}
        facts = []
        for field_name in payload.get("fields", []):
            text = payload["task"].get(field_name, "")
            offset = 0
            # 길이 0인 자리에서만 나눠 글자를 잃지 않는다(소수점 '0.3'은 문장 끝이 아니다).
            for piece in re.split(r"(?<=[.。])(?=\s)|(?<=\n)|(?=\()", text):
                if not _NOT_FINAL.search(piece):
                    for match in _NUMBER_UNIT.finditer(piece):
                        start = offset + match.start()
                        quote = match.group(0).strip()
                        head = piece[:match.start()].rstrip()
                        subject = head.split()[-1] if head.split() else "값"
                        facts.append(dict(fact_id=f"{field_name}:{start}", subject=subject, value_text=quote,
                                          low=match.group(1), high=match.group(1), unit=match.group(2) or "",
                                          source_field=field_name, quote=quote))
                offset += len(piece)
        return {"facts": facts}

    def _screen(self, payload):
        decisions = []
        subjects = [f["subject"] for f in payload.get("goal_facts", [])]
        for clause in payload["clauses"]:
            if self.candidates is not None:
                hit = clause["clause_id"] in self.candidates
            else:
                hit = any(_overlap(s, t) for s in subjects for t in clause.get("subjects", []) + [clause["title"]])
            detail = bool(hit) and self._detail_match(payload.get("task", {}), clause)
            decisions.append(dict(clause_id=clause["clause_id"], candidate=bool(hit), detail_match=detail,
                                  reason="물리량·제목 겹침" if hit else "관련 분야 아님"))
        return {"decisions": decisions}

    def _detail_match(self, task, clause):
        if self.detail_matches is None:
            return False
        if callable(self.detail_matches):
            return bool(self.detail_matches(task, clause))
        return clause["clause_id"] in self.detail_matches

    def _pair(self, payload):
        pairs, choices = [], []
        for clause in payload["clauses"]:
            chosen = ""
            for branch in clause["branches"]:
                for threshold in branch["thresholds"]:
                    for fact in payload["goal_facts"]:
                        if _overlap(fact["subject"], threshold["subject"]) and fact["unit"].lower() == threshold["unit"].lower():
                            pairs.append(dict(clause_id=clause["clause_id"], fact_id=fact["fact_id"],
                                              threshold_id=threshold["threshold_id"], branch_id=branch["branch_id"],
                                              reason=f"목표 {fact['subject']} ↔ 기준 {threshold['subject']}", ambiguous=False))
                            chosen = chosen or branch["branch_id"]
            if chosen:
                choices.append(dict(clause_id=clause["clause_id"], branch_id=chosen, reason="매핑된 기준의 갈래"))
        return {"pairs": pairs, "branch_choices": choices}

    @staticmethod
    def _apply_fault(stage, kind, out, payload):
        if kind is None:
            return out
        if stage == "screen":
            if kind == "missing":
                out["decisions"] = out["decisions"][1:]
            elif kind == "unknown":
                out["decisions"].append(dict(clause_id="ghost:000", candidate=True, detail_match=False, reason="없는 조항"))
            elif kind == "duplicate":
                out["decisions"].append(deepcopy(out["decisions"][0]))
            elif kind == "detail_missing":
                del out["decisions"][0]["detail_match"]
            elif kind == "detail_not_bool":
                out["decisions"][0]["detail_match"] = "true"
            elif kind == "detail_conflict":
                out["decisions"][0].update(candidate=False, detail_match=True)
        elif kind == "missing":
            key = "facts" if stage == "extract" else "pairs"
            out[key] = "목록이 아님"
        return out
