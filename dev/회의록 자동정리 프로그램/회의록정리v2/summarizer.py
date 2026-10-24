# -*- coding: utf-8 -*-
"""
OpenAI GPT 를 이용한 발언자 매칭 + 기관별 요약.

전사문(stt.Transcript)과 사용자가 입력한 참석자 명단을 받아
  1) 발언자 매칭   : 어느 발언이 누구 것인지
     Whisper 는 화자를 구분해 주지 않으므로 자기소개, 호칭, 담당 업무, 질문-답변
     흐름을 근거로 구간별 발언자를 추정한다. 결과는 화면에서 사용자가 고칠 수 있다.
  2) 기관별 요약   : 양식의 "□ 기관별 요약" 표(기관 / 항목 / 발언 내용)
  3) 안건·시사점·환류계획 초안

응답 형식이 흐트러지면 문서 생성이 통째로 깨지므로 structured outputs
(response_format = json_schema, strict)으로 스키마를 강제한다.

전사와 마찬가지로 표준 라이브러리(urllib)만 쓴다. 별도의 SDK 를 붙이지 않으므로
exe 크기가 늘지 않고, 오류 본문을 그대로 보여 줄 수 있어 원인 파악이 쉽다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib import error, request

import config as CFG
from stt import Segment, Transcript

Progress = Callable[[str], None]

UNKNOWN = "미상"

#: 발언자 추정을 한 번에 처리할 구간 수 (출력 길이를 적당히 유지)
SPEAKER_BATCH = 400


class SummarizeError(RuntimeError):
    pass


@dataclass
class Attendee:
    name: str
    org: str = ""
    position: str = ""

    @property
    def label(self) -> str:
        bits = [b for b in (self.org, self.position) if b]
        return f"{self.name}({' '.join(bits)})" if bits else self.name

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "org": self.org, "position": self.position}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Attendee":
        return cls(name=(d.get("name") or "").strip(),
                   org=(d.get("org") or "").strip(),
                   position=(d.get("position") or "").strip())


@dataclass
class SummaryItem:
    topic: str
    content: str


@dataclass
class InstitutionSummary:
    name: str
    items: list[SummaryItem] = field(default_factory=list)


@dataclass
class Summary:
    title: str = ""
    agenda: str = ""
    institutions: list[InstitutionSummary] = field(default_factory=list)
    implications: str = ""
    feedback_plan: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "agenda": self.agenda,
            "implications": self.implications, "feedback_plan": self.feedback_plan,
            "institutions": [
                {"name": i.name, "items": [{"topic": t.topic, "content": t.content}
                                           for t in i.items]}
                for i in self.institutions
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Summary":
        return cls(
            title=d.get("title", ""), agenda=d.get("agenda", ""),
            implications=d.get("implications", ""),
            feedback_plan=d.get("feedback_plan", ""),
            institutions=[
                InstitutionSummary(
                    name=i.get("name", ""),
                    items=[SummaryItem(t.get("topic", ""), t.get("content", ""))
                           for t in i.get("items", [])],
                )
                for i in d.get("institutions", [])
            ],
        )


# ---------------------------------------------------------------------------
# OpenAI 호출 공통
# ---------------------------------------------------------------------------

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class _HTTPFail(Exception):
    """OpenAI 가 돌려준 HTTP 오류. 본문을 보고 재시도 여부를 판단하려고 따로 둔다."""

    def __init__(self, code: int, detail: str):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.detail = detail


def _api_key(cfg: dict[str, Any]) -> str:
    key = (cfg.get("openai_api_key") or "").strip()
    if not key:
        raise SummarizeError("OpenAI API 키가 없습니다. embedded_key.py 에 키를 넣어 "
                             "빌드했거나, [설정] 탭에서 키를 입력해야 합니다.")
    return key


def _post(key: str, payload: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(OPENAI_CHAT_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:800]
        except Exception:  # noqa: BLE001
            pass
        raise _HTTPFail(e.code, detail) from e
    except error.URLError as e:
        raise SummarizeError(f"OpenAI 서버에 연결하지 못했습니다: {e.reason}") from e
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SummarizeError(f"OpenAI 응답을 해석하지 못했습니다: {raw[:200]!r}") from e


def _friendly(fail: _HTTPFail) -> SummarizeError:
    """HTTP 오류를 사람이 읽을 수 있는 안내로."""
    d = fail.detail
    if fail.code == 401:
        return SummarizeError("OpenAI API 키가 올바르지 않습니다(401). 키를 확인해 주세요.")
    if fail.code == 429:
        return SummarizeError("OpenAI 호출 한도에 걸렸거나 잔액이 부족합니다(429). "
                              "잠시 후 다시 시도하거나 결제 상태를 확인해 주세요.")
    if fail.code == 404 or "model_not_found" in d or "does not exist" in d:
        return SummarizeError(
            f"요약 모델 '{CFG.SUMMARY_MODEL}' 을 쓸 수 없습니다(HTTP {fail.code}).\n"
            "모델 이름이 맞는지, 이 API 키로 접근할 수 있는 모델인지 확인해 주세요.\n"
            "모델을 바꾸려면 config.py 의 SUMMARY_MODEL 한 줄만 고치면 됩니다.")
    if fail.code >= 500:
        return SummarizeError(f"OpenAI 서버 오류({fail.code}). 잠시 후 다시 시도해 주세요.")
    return SummarizeError(f"OpenAI 호출 실패(HTTP {fail.code})\n{d[:400]}")


def _ask(cfg: dict[str, Any], system: str, user: str, schema: dict[str, Any],
         schema_name: str, max_tokens: int = 16000) -> dict[str, Any]:
    """JSON 스키마를 강제해 모델에 묻고 파싱된 dict 를 돌려준다."""
    key = _api_key(cfg)
    payload: dict[str, Any] = {
        "model": CFG.SUMMARY_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": schema_name, "strict": True, "schema": schema}},
        "max_completion_tokens": max_tokens,
    }
    try:
        data = _post(key, payload)
    except _HTTPFail as e:
        # 구형 모델은 max_completion_tokens 를 모르고 max_tokens 만 받는다
        if e.code == 400 and "max_completion_tokens" in e.detail:
            payload.pop("max_completion_tokens")
            payload["max_tokens"] = max_tokens
            try:
                data = _post(key, payload)
            except _HTTPFail as e2:
                raise _friendly(e2) from e2
        else:
            raise _friendly(e) from e

    choices = data.get("choices") or []
    if not choices:
        raise SummarizeError("OpenAI 응답에 결과가 없습니다. 잠시 후 다시 시도해 주세요.")
    msg = choices[0].get("message") or {}
    if msg.get("refusal"):
        raise SummarizeError("모델이 이 내용의 처리를 거부했습니다: "
                             + str(msg["refusal"])[:200])
    if choices[0].get("finish_reason") == "length":
        raise SummarizeError("응답이 최대 길이에 걸려 중간에 끊겼습니다. "
                             "회의가 아주 길면 녹음을 나눠 처리해 주세요.")
    text = (msg.get("content") or "").strip()
    if not text:
        raise SummarizeError("OpenAI 응답이 비어 있습니다. 잠시 후 다시 시도해 주세요.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SummarizeError(f"응답을 해석하지 못했습니다: {text[:200]}") from e


def _attendee_block(attendees: list[Attendee]) -> str:
    if not attendees:
        return "(참석자 명단이 입력되지 않았습니다)"
    return "\n".join(
        f"- {a.name} / 기관: {a.org or '미상'} / 직위: {a.position or '미상'}"
        for a in attendees
    )


def _numbered(segments: list[Segment], with_speaker: bool = False) -> str:
    out = []
    for s in segments:
        mm, ss = divmod(int(s.start), 60)
        head = f"[{s.index}] {mm:02d}:{ss:02d}"
        if with_speaker and s.speaker:
            head += f" <{s.speaker}>"
        out.append(f"{head} {s.text}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 1) 발언자 매칭
# ---------------------------------------------------------------------------

_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "integer", "description": "시작 구간 번호(포함)"},
                    "to": {"type": "integer", "description": "끝 구간 번호(포함)"},
                    "speaker": {"type": "string", "description": "참석자 이름 또는 '미상'"},
                },
                "required": ["from", "to", "speaker"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["turns"],
    "additionalProperties": False,
}

_SPEAKER_SYSTEM = (
    "당신은 한국 공공기관(KISTEP) 회의록을 정리하는 담당자입니다. "
    "회의 전사문을 읽고 각 발언이 누구의 것인지 판단합니다. "
    "판단 근거는 자기소개, 호칭(‘○○ 팀장님’ 등), 소속 기관 언급, 담당 업무, "
    "질문-답변의 흐름입니다. "
    "확실하지 않으면 억지로 배정하지 말고 반드시 '미상'으로 두십시오. "
    "명단에 없는 이름을 만들어 내지 마십시오."
)


def infer_speakers(transcript: Transcript, attendees: list[Attendee],
                   cfg: dict[str, Any],
                   progress: Progress | None = None) -> list[dict[str, Any]]:
    """화자 정보가 없는 전사문에서 구간별 발언자를 추정한다."""
    progress = progress or (lambda _m: None)
    segs = transcript.segments
    if not segs:
        return []
    names = {a.name for a in attendees}
    turns: list[dict[str, Any]] = []
    batches = [segs[i:i + SPEAKER_BATCH] for i in range(0, len(segs), SPEAKER_BATCH)]

    carry = ""
    for bi, batch in enumerate(batches):
        progress(f"발언자 추정 중… ({bi + 1}/{len(batches)})")
        user = (
            f"## 참석자 명단\n{_attendee_block(attendees)}\n\n"
            + (f"## 직전까지의 진행 상황\n{carry}\n\n" if carry else "")
            + f"## 전사문 (구간번호 {batch[0].index}~{batch[-1].index})\n"
            + _numbered(batch) + "\n\n"
            "연속으로 같은 사람이 말한 구간을 하나의 발언 묶음으로 만들고, "
            "각 묶음의 발언자를 판단해 주십시오. "
            f"모든 구간({batch[0].index}~{batch[-1].index})이 빠짐없이 어느 묶음엔가 "
            "속해야 하며, 묶음끼리 겹치면 안 됩니다. "
            "판단이 어려우면 '미상'으로 두십시오."
        )
        data = _ask(cfg, _SPEAKER_SYSTEM, user, _TURN_SCHEMA, "speaker_turns",
                    max_tokens=16000)
        got = data.get("turns", [])
        for t in got:
            spk = t.get("speaker", UNKNOWN)
            turns.append({
                "from": int(t.get("from", batch[0].index)),
                "to": int(t.get("to", batch[-1].index)),
                "speaker": spk if spk in names else UNKNOWN,
            })
        tail = [t for t in got if t.get("speaker") and t.get("speaker") != UNKNOWN][-3:]
        carry = "; ".join(f"{t['speaker']} 발언(구간 {t['from']}~{t['to']})" for t in tail)

    return turns


def apply_turns(transcript: Transcript, turns: list[dict[str, Any]]) -> None:
    """추정 결과를 각 구간의 speaker 에 반영한다."""
    by_index = {s.index: s for s in transcript.segments}
    for t in turns:
        for i in range(int(t["from"]), int(t["to"]) + 1):
            s = by_index.get(i)
            if s is not None:
                s.speaker = t["speaker"]
    for s in transcript.segments:
        if not s.speaker:
            s.speaker = UNKNOWN


# ---------------------------------------------------------------------------
# 2) 기관별 요약
# ---------------------------------------------------------------------------

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "회의 제목. '회의록' 이라는 말은 빼고 회의 이름만"},
        "agenda": {"type": "string", "description": "안건. 두 줄 이내의 키워드 중심 서술"},
        "institutions": {
            "type": "array",
            "description": "회의에 참여한 기관별 발언 요약. 참석자 명단의 기관 순서를 따른다.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "기관명"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic": {"type": "string",
                                          "description": "항목. 10자 내외의 짧은 주제어"},
                                "content": {"type": "string",
                                            "description": "해당 항목에 대한 발언 내용 요약"},
                            },
                            "required": ["topic", "content"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "items"],
                "additionalProperties": False,
            },
        },
        "implications": {"type": "string", "description": "회의 결과에 따른 시사점"},
        "feedback_plan": {"type": "string", "description": "향후 조치계획·환류계획"},
    },
    "required": ["title", "agenda", "institutions", "implications", "feedback_plan"],
    "additionalProperties": False,
}

_SUMMARY_SYSTEM = (
    "당신은 KISTEP 연구윤리자산보호센터의 회의록 작성 담당자입니다. "
    "회의 전사문을 읽고 표준 회의록 양식에 맞춰 기관별로 정리합니다.\n\n"
    "작성 원칙\n"
    "- 공문서체로 씁니다. 문장은 '~함', '~임', '~할 필요', '~요청' 같은 개조식 종결로 끝냅니다.\n"
    "- 전사문에 실제로 나온 내용만 씁니다. 없는 수치·기관명·계획을 지어내지 않습니다.\n"
    "- 잡담, 인사말, 진행 안내(‘잠시 쉬겠습니다’ 등)는 회의록에 넣지 않습니다.\n"
    "- '항목'은 그 기관이 다룬 논의 주제를 10자 내외로 압축한 말입니다. "
    "(예: 제도 개선, 예산 집행, 자료 제출, 애로사항)\n"
    "- '발언 내용'은 항목별 발언의 요지를 1~3문장으로 정리합니다. "
    "발언자가 여럿이면 '(○○○) …' 형태로 구분해 적어도 됩니다.\n"
    "- 한 기관당 항목은 2~6개가 적당합니다. 발언이 적은 기관은 1~2개여도 됩니다.\n"
    "- 발언이 전혀 없는 기관은 목록에서 뺍니다.\n"
    "- 전사 과정에서 잘못 들린 말(오인식)은 문맥으로 바로잡아 적습니다."
)


def summarize(transcript: Transcript, attendees: list[Attendee], meta: dict[str, Any],
              cfg: dict[str, Any], progress: Progress | None = None) -> Summary:
    """기관별 요약 + 안건/시사점/환류계획 초안을 만든다."""
    progress = progress or (lambda _m: None)
    if not transcript.segments:
        raise SummarizeError("전사문이 비어 있습니다.")
    progress("기관별 요약을 만드는 중… (회의가 길면 1~3분 걸립니다)")

    orgs: list[str] = []
    for a in attendees:
        if a.org and a.org not in orgs:
            orgs.append(a.org)

    hint = []
    if meta.get("title"):
        hint.append(f"- 회의 제목(사용자 입력): {meta['title']}")
    if meta.get("datetime"):
        hint.append(f"- 일시: {meta['datetime']}")
    if meta.get("place"):
        hint.append(f"- 장소: {meta['place']}")
    if meta.get("agenda"):
        hint.append(f"- 안건(사용자 입력): {meta['agenda']}")

    user = (
        f"## 참석자 명단\n{_attendee_block(attendees)}\n\n"
        f"## 정리 대상 기관\n" + ("\n".join(f"- {o}" for o in orgs) or "(명단에서 기관을 찾지 못함)")
        + "\n\n"
        + (f"## 회의 정보\n" + "\n".join(hint) + "\n\n" if hint else "")
        + f"## 회의 전사문\n{_numbered(transcript.segments, with_speaker=True)}\n\n"
        "위 전사문을 표준 회의록 양식에 맞춰 정리해 주십시오. "
        "'기관별 요약'은 위 '정리 대상 기관' 목록을 기준으로 하되, "
        "전사문에 등장하지만 명단에 없는 기관이 뚜렷하게 있으면 추가해도 됩니다. "
        "사용자가 회의 제목이나 안건을 이미 입력했다면 그 취지를 존중해 다듬어 주십시오."
    )
    data = _ask(cfg, _SUMMARY_SYSTEM, user, _SUMMARY_SCHEMA, "meeting_summary",
                 max_tokens=32000)
    summary = Summary.from_dict(data)
    summary.institutions = [i for i in summary.institutions if i.name and i.items]
    if not summary.institutions:
        raise SummarizeError("기관별 요약을 만들지 못했습니다. "
                             "참석자 명단에 기관이 입력되어 있는지 확인해 주세요.")
    return summary


_PING_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
    "required": ["ok", "note"],
    "additionalProperties": False,
}


def test_connection(cfg: dict[str, Any]) -> str:
    """설정 화면의 [연결 테스트] 용. 키·모델 이름·구조화 출력까지 한 번에 확인한다."""
    data = _ask(cfg, "연결 확인용 요청입니다.",
                "ok 을 true 로, note 에 '정상' 이라고만 답하세요.",
                _PING_SCHEMA, "ping", max_tokens=2000)
    return (f"요약 모델 연결 정상 (모델: {CFG.SUMMARY_MODEL}, "
            f"응답: {data.get('note') or 'ok'})")
