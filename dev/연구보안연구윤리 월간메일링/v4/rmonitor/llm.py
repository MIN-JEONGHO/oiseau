# -*- coding: utf-8 -*-
"""Claude(Anthropic) 호출 계층 — claude-sonnet-5-5 로 고정.

웹 검색(그라운딩)을 켠 상태로 프롬프트를 보내고 '텍스트 응답'을 돌려준다.
requests 만 사용하므로 anthropic SDK 설치가 필요 없다.

v3 부터 LLM 연동 자체를 설정 가능한 기능으로 두지 않고, Claude Sonnet 5.5 하나로
고정했다(API 키도 하드코딩 — rmonitor/_secrets.py 참고). 아래 값들은 Anthropic API의
최신 정책을 확인해 반영한 것이다(2026-10 기준):

  - temperature / top_p / top_k 는 이 모델에서 아예 받지 않는다(보내면 HTTP 400).
    → 애초에 요청에 넣지 않는다(과거처럼 모델명으로 판단해 선택적으로 빼는 방식이 아니라,
      이 모델에서는 무조건 빼는 것이 맞다).
  - extended thinking 은 기본적으로 켜져 있다(adaptive). budget_tokens 방식은 제거되어
    400 을 반환하므로, thinking 은 {"type": "adaptive"} 로만 지정한다.
  - thinking 이 사고 과정에도 max_tokens 를 함께 쓰므로, 응답이 잘리지 않도록 출력 토큰
    하한(MAX_TOKENS_FLOOR)을 둔다.
  - 웹 검색 도구는 동적 필터링을 지원하는 최신 버전(web_search_20260209)을 쓴다.

그래도 Anthropic이 정책을 또 바꿔 특정 파라미터를 거부(400)하면, 오류 메시지에서 문제
파라미터를 읽어 제거하고 즉시 재시도하는 방어 로직은 남겨 둔다(코드 수정 없이 흡수).
"""
from __future__ import annotations

import copy
import logging
import os
import re
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger("rmonitor")

MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT_SEC = 900
MAX_TOKENS_FLOOR = 32000        # thinking 이 기본 켜져 있어 사고 과정도 max_tokens 를 함께 쓴다
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"   # 동적 필터링 지원 버전 (Sonnet 5.5 대응)

try:
    from ._secrets import ANTHROPIC_API_KEY as _HARDCODED_KEY
except ImportError:  # rmonitor/_secrets.py 가 없으면(신규 클론 등) 빈 값으로 시작
    _HARDCODED_KEY = ""


def _resolve_api_key() -> str:
    """RM_LLM_API_KEY 환경변수 > 하드코딩된 키 순으로 사용(키 교체 시 재빌드 없이 대응 가능)."""
    return (os.getenv("RM_LLM_API_KEY") or _HARDCODED_KEY or "").strip()


class LLMError(RuntimeError):
    """LLM 호출 실패(재시도 가능성 있음)."""


class LLMFatal(LLMError):
    """다시 보내도 결과가 같은 오류. 재시도하지 않는다."""


class LLMBadRequest(LLMFatal):
    """요청 자체가 잘못됨(4xx)."""

    def __init__(self, message: str, status: int, body: str):
        super().__init__(message)
        self.status = status
        self.body = body


class LLMResponseError(LLMFatal):
    """호출은 성공했지만 응답을 쓸 수 없음(길이 초과로 잘림, 안전상 거부 등)."""


# --------------------------------------------------------------------------
# 400 오류 시 미지원 파라미터 자동 제거(정책이 또 바뀌어도 흡수)
# --------------------------------------------------------------------------
_STRIPPABLE = ("thinking",)   # temperature/top_p/top_k 는 애초에 보내지 않으므로 대상에서 제외

_PARAM_PATTERNS = (
    re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`"),                     # `thinking` is deprecated
    re.compile(r"[Uu]nsupported parameter:\s*'([A-Za-z0-9_.]+)'"),  # Unsupported parameter: 'thinking'
    re.compile(r"\"([A-Za-z_][A-Za-z0-9_.]*)\"\s*(?:is|are)\s+(?:not supported|deprecated)"),
)


def _offending_param(body: str) -> Optional[str]:
    for pat in _PARAM_PATTERNS:
        m = pat.search(body or "")
        if m and m.group(1) in _STRIPPABLE:
            return m.group(1)
    return None


def _post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        body = resp.text[:2000]
        msg = f"HTTP {resp.status_code}: {body[:800]}"
        # 408(타임아웃)·429(호출량 초과)·5xx 는 잠시 후 재시도할 가치가 있다.
        if 400 <= resp.status_code < 500 and resp.status_code not in (408, 429):
            raise LLMBadRequest(msg, resp.status_code, body)
        raise LLMError(msg)
    return resp.json()


def _post_pruning(url: str, headers: dict, payload: dict, timeout: int,
                  logger: logging.Logger) -> dict:
    """400 이 나면 미지원 파라미터를 제거하고 즉시 재시도한다."""
    payload = copy.deepcopy(payload)
    for _ in range(len(_STRIPPABLE) + 1):
        try:
            return _post(url, headers, payload, timeout)
        except LLMBadRequest as exc:
            name = _offending_param(exc.body)
            if not name or name not in payload:
                raise
            payload.pop(name)
            logger.warning("Claude Sonnet 5.5 가 '%s' 파라미터를 지원하지 않아 제외하고 다시 호출합니다.", name)
    raise LLMError("미지원 파라미터를 정리했는데도 요청이 계속 거부되었습니다.")


# --------------------------------------------------------------------------
def call_llm(prompt: str, logger: Optional[logging.Logger] = None) -> str:
    """Claude Sonnet 5.5 를 호출해 응답 텍스트를 반환한다(429/5xx/타임아웃만 최대 3회 재시도)."""
    logger = logger or log
    api_key = _resolve_api_key()
    if not api_key:
        raise LLMError(
            "Anthropic API 키가 설정되지 않았습니다. rmonitor/_secrets.py 에 ANTHROPIC_API_KEY 를 "
            "입력하거나 RM_LLM_API_KEY 환경변수를 지정하세요."
        )

    payload: Dict[str, Any] = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS_FLOOR,
        "thinking": {"type": "adaptive"},
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": 20}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    last_err: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            logger.info("LLM 호출 (%s) 시도 %d", MODEL, attempt)
            data = _post_pruning(API_URL, headers, payload, TIMEOUT_SEC, logger)
            return _extract_text(data)
        except LLMFatal as exc:
            logger.error("LLM 오류(재시도 없음): %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("LLM 호출 실패(%d/3): %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
    raise LLMError(f"LLM 호출에 3회 실패했습니다: {last_err}")


def _extract_text(data: dict) -> str:
    stop_reason = data.get("stop_reason")
    if stop_reason == "refusal":
        details = data.get("stop_details") or {}
        raise LLMResponseError(
            f"모델이 안전상의 이유로 응답을 거부했습니다(category={details.get('category')}). "
            "프롬프트를 조정해 주세요."
        )

    blocks = data.get("content", [])
    text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    if stop_reason == "max_tokens":
        raise LLMResponseError(
            f"응답이 최대 출력 길이({MAX_TOKENS_FLOOR} 토큰)에서 잘렸습니다. "
            "rmonitor/llm.py 의 MAX_TOKENS_FLOOR 를 늘려 주세요."
        )
    if not text.strip():
        raise LLMError("빈 응답을 받았습니다.")
    return text
