# -*- coding: utf-8 -*-
"""LLM 호출 계층.

웹 검색(그라운딩)을 켠 상태로 프롬프트를 보내고 '텍스트 응답'을 돌려준다.
requests 만 사용하므로 벤더 SDK 설치가 필요 없다.

지원 provider
  - gemini    : Google AI Studio(Generative Language API) / Gemini + Google Search
  - vertex    : Google Cloud Vertex AI (gcloud 인증 토큰 사용)
  - anthropic : Claude + web_search 도구
  - openai    : OpenAI Responses API + web_search 도구

v2 변경점
  - 최신 모델(claude-opus-5, sonnet-5, opus-4.7/4.8 등)은 temperature/top_p/top_k 를
    아예 받지 않고 HTTP 400 을 반환한다. 모델명으로 1차 판단해 처음부터 빼고 보내며,
    그래도 400 이 나면 오류 메시지에서 문제 파라미터를 읽어 제거 후 즉시 재시도한다.
  - 400/401/403/404 같은 요청 오류는 몇 번을 다시 보내도 결과가 같으므로 재시도하지 않고
    즉시 실패시킨다. (v1 은 동일 요청을 3회 반복해 15초를 낭비했다)
  - Claude web_search 도구 버전을 모델에 맞게 고르고, 거부되면 구버전으로 1회 대체한다.
  - 응답이 길이 제한(max_tokens)으로 잘렸거나 안전상 거부된 경우를 명시적으로 알린다.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

log = logging.getLogger("rmonitor")


class LLMError(RuntimeError):
    """LLM 호출 실패(재시도 가능성 있음)."""


class LLMFatal(LLMError):
    """다시 보내도 결과가 같은 오류. 설정/프롬프트를 고쳐야 하므로 재시도하지 않는다."""


class LLMBadRequest(LLMFatal):
    """요청 자체가 잘못됨(4xx)."""

    def __init__(self, message: str, status: int, body: str):
        super().__init__(message)
        self.status = status
        self.body = body


class LLMResponseError(LLMFatal):
    """호출은 성공했지만 응답을 쓸 수 없음(길이 초과로 잘림, 안전상 거부 등)."""


# --------------------------------------------------------------------------
# 모델별 지원 여부 판단
# --------------------------------------------------------------------------
# temperature / top_p / top_k 를 제거한 Claude 모델들.
# (신규 모델이 추가돼도 아래 자동 제거 로직이 받아주므로 목록은 '1차 방어선'일 뿐이다)
_CLAUDE_NO_SAMPLING = (
    "claude-fable-5", "claude-mythos-5", "claude-opus-5",
    "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7",
)

# 최신 web_search 도구(동적 필터링)를 지원하는 Claude 모델들.
_CLAUDE_WEB_SEARCH_NEW = _CLAUDE_NO_SAMPLING + ("claude-opus-4-6", "claude-sonnet-4-6")

# thinking 이 기본 ON 이라 max_tokens 를 사고 과정과 나눠 쓰는 모델들.
# 리포트 JSON 이 길어 잘리기 쉬우므로 출력 토큰 하한을 둔다.
_CLAUDE_THINKING_DEFAULT = ("claude-fable-5", "claude-mythos-5", "claude-opus-5")
_THINKING_MIN_OUTPUT_TOKENS = 32000

# 오류 메시지에서 문제 파라미터를 찾아 제거할 때 허용할 대상.
# (프롬프트/모델 같은 필수 항목이 지워지지 않도록 화이트리스트로 제한한다)
_STRIPPABLE = ("temperature", "top_p", "top_k", "topP", "topK", "thinking")

_PARAM_PATTERNS = (
    re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`"),                     # `temperature` is deprecated
    re.compile(r"[Uu]nsupported parameter:\s*'([A-Za-z0-9_.]+)'"),  # Unsupported parameter: 'temperature'
    re.compile(r"\"([A-Za-z_][A-Za-z0-9_.]*)\"\s*(?:is|are)\s+(?:not supported|deprecated)"),
)


def _startswith_any(model: str, prefixes: Sequence[str]) -> bool:
    m = (model or "").lower()
    return any(m.startswith(p) for p in prefixes)


def _claude_supports_sampling(model: str) -> bool:
    return not _startswith_any(model, _CLAUDE_NO_SAMPLING)


def _claude_web_search_type(model: str) -> str:
    return ("web_search_20260209" if _startswith_any(model, _CLAUDE_WEB_SEARCH_NEW)
            else "web_search_20250305")


def _claude_max_tokens(model: str, requested: int) -> int:
    """thinking 이 켜지는 모델은 사고 과정도 max_tokens 를 소비하므로 여유를 준다."""
    if _startswith_any(model, _CLAUDE_THINKING_DEFAULT):
        return max(int(requested), _THINKING_MIN_OUTPUT_TOKENS)
    return int(requested)


# --------------------------------------------------------------------------
def call_llm(prompt: str, cfg: Dict[str, Any], logger: logging.Logger | None = None) -> str:
    """설정에 따라 적절한 provider 를 호출하고 응답 텍스트를 반환."""
    logger = logger or log
    provider = (cfg.get("provider") or "gemini").lower()
    handlers = {
        "gemini": _call_gemini,
        "vertex": _call_vertex,
        "anthropic": _call_anthropic,
        "claude": _call_anthropic,
        "openai": _call_openai,
    }
    if provider not in handlers:
        raise LLMError(f"지원하지 않는 provider: {provider}")

    last_err: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            logger.info("LLM 호출 (%s / %s) 시도 %d", provider, cfg.get("model"), attempt)
            text = handlers[provider](prompt, cfg, logger)
            if not text or not text.strip():
                raise LLMError("빈 응답을 받았습니다.")
            return text
        except LLMFatal as exc:
            # 요청/설정이 잘못된 경우 재시도해도 동일하게 실패한다. 즉시 중단.
            logger.error("LLM 오류(재시도 없음): %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("LLM 호출 실패(%d/3): %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
    raise LLMError(f"LLM 호출에 3회 실패했습니다: {last_err}")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
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


def _offending_param(body: str) -> Optional[str]:
    """400 응답 본문에서 문제가 된 파라미터 이름을 찾아낸다."""
    for pat in _PARAM_PATTERNS:
        m = pat.search(body or "")
        if m and m.group(1) in _STRIPPABLE:
            return m.group(1)
    return None


def _pop_path(payload: dict, path: Tuple[str, ...]) -> bool:
    """payload 에서 중첩 키를 제거. 실제로 지웠으면 True."""
    node: Any = payload
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    if isinstance(node, dict) and path[-1] in node:
        node.pop(path[-1])
        return True
    return False


def _post_pruning(url: str, headers: dict, payload: dict, timeout: int,
                  strippable: Dict[str, Tuple[str, ...]],
                  logger: logging.Logger) -> dict:
    """400 이 나면 미지원 파라미터를 제거하고 즉시 재시도한다.

    최신 모델이 temperature 등을 거부하는 상황을 코드 수정 없이 흡수하기 위한 장치.
    """
    payload = copy.deepcopy(payload)
    for _ in range(len(strippable) + 1):
        try:
            return _post(url, headers, payload, timeout)
        except LLMBadRequest as exc:
            name = _offending_param(exc.body)
            path = strippable.get(name) if name else None
            if not path or not _pop_path(payload, path):
                raise
            logger.warning("이 모델은 '%s' 파라미터를 지원하지 않아 제외하고 다시 호출합니다.", name)
    raise LLMError("미지원 파라미터를 정리했는데도 요청이 계속 거부되었습니다.")


# --------------------------------------------------------------------------
# Gemini / Vertex
# --------------------------------------------------------------------------
_GEMINI_STRIPPABLE = {
    "temperature": ("generationConfig", "temperature"),
    "topP": ("generationConfig", "topP"),
    "topK": ("generationConfig", "topK"),
    "top_p": ("generationConfig", "topP"),
    "top_k": ("generationConfig", "topK"),
}


def _gemini_payload(prompt: str, cfg: dict) -> dict:
    gen_cfg: Dict[str, Any] = {"maxOutputTokens": cfg.get("max_output_tokens", 20000)}
    temperature = cfg.get("temperature")
    if temperature is not None:
        gen_cfg["temperature"] = temperature
    payload: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    if cfg.get("enable_web_search", True):
        # Gemini 2.x 계열: google_search / 1.5 계열: google_search_retrieval
        payload["tools"] = [{"google_search": {}}]
    return payload


def _gemini_extract(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError(f"예상과 다른 응답 형식: {json.dumps(data)[:800]}")
    cand = candidates[0]
    finish = cand.get("finishReason")
    try:
        parts = cand["content"]["parts"]
    except (KeyError, TypeError) as exc:
        raise LLMError(
            f"응답에 본문이 없습니다(finishReason={finish}): {json.dumps(data)[:800]}"
        ) from exc
    text = "\n".join(p.get("text", "") for p in parts if "text" in p)
    if finish == "MAX_TOKENS":
        raise LLMResponseError(
            "응답이 최대 출력 길이에서 잘렸습니다. config.json 의 llm.max_output_tokens 를 늘려 주세요."
        )
    if finish == "SAFETY":
        raise LLMResponseError("모델이 안전상의 이유로 응답을 거부했습니다.")
    return text


def _call_gemini(prompt: str, cfg: dict, logger: logging.Logger) -> str:
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise LLMError("Gemini API 키가 설정되지 않았습니다.")
    model = cfg.get("model") or "gemini-2.5-pro"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post_pruning(url,
                         {"Content-Type": "application/json", "x-goog-api-key": api_key},
                         _gemini_payload(prompt, cfg),
                         cfg.get("timeout_sec", 900),
                         _GEMINI_STRIPPABLE, logger)
    return _gemini_extract(data)


def _call_vertex(prompt: str, cfg: dict, logger: logging.Logger) -> str:
    """Vertex AI 호출. `gcloud auth print-access-token` 또는 access_token 설정값 사용."""
    project = cfg.get("gcp_project")
    location = cfg.get("gcp_location", "us-central1")
    model = cfg.get("model") or "gemini-2.5-pro"
    if not project:
        raise LLMError("vertex provider 사용 시 llm.gcp_project 설정이 필요합니다.")

    token = (cfg.get("access_token") or "").strip()
    if not token:
        import subprocess
        try:
            token = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"], text=True).strip()
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"gcloud 액세스 토큰을 가져오지 못했습니다: {exc}") from exc

    url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
           f"/locations/{location}/publishers/google/models/{model}:generateContent")
    data = _post_pruning(url,
                         {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                         _gemini_payload(prompt, cfg),
                         cfg.get("timeout_sec", 900),
                         _GEMINI_STRIPPABLE, logger)
    return _gemini_extract(data)


# --------------------------------------------------------------------------
# Anthropic (Claude)
# --------------------------------------------------------------------------
_ANTHROPIC_STRIPPABLE = {
    "temperature": ("temperature",),
    "top_p": ("top_p",),
    "top_k": ("top_k",),
    "thinking": ("thinking",),
}


def _call_anthropic(prompt: str, cfg: dict, logger: logging.Logger) -> str:
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise LLMError("Anthropic API 키가 설정되지 않았습니다.")

    model = cfg.get("model") or "claude-opus-5"
    requested_tokens = cfg.get("max_output_tokens", 20000)
    max_tokens = _claude_max_tokens(model, requested_tokens)
    if max_tokens != requested_tokens:
        logger.info("%s 는 사고 과정도 출력 토큰을 사용하므로 max_tokens 를 %d → %d 로 올립니다.",
                    model, requested_tokens, max_tokens)

    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    # 최신 모델은 temperature 를 받지 않는다(HTTP 400). 구형 모델에서만 전달한다.
    temperature = cfg.get("temperature")
    if temperature is not None and _claude_supports_sampling(model):
        payload["temperature"] = temperature

    if cfg.get("enable_web_search", True):
        payload["tools"] = [{"type": _claude_web_search_type(model),
                             "name": "web_search", "max_uses": 20}]

    headers = {"x-api-key": api_key,
               "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    timeout = cfg.get("timeout_sec", 900)

    try:
        data = _post_pruning("https://api.anthropic.com/v1/messages",
                             headers, payload, timeout, _ANTHROPIC_STRIPPABLE, logger)
    except LLMBadRequest as exc:
        # web_search 도구 버전을 이 모델이 모르는 경우 구버전으로 1회 대체한다.
        if "web_search" in exc.body and payload.get("tools"):
            logger.warning("web_search 도구 최신 버전이 거부되어 구버전(web_search_20250305)으로 재시도합니다.")
            payload["tools"] = [{"type": "web_search_20250305",
                                 "name": "web_search", "max_uses": 20}]
            data = _post_pruning("https://api.anthropic.com/v1/messages",
                                 headers, payload, timeout, _ANTHROPIC_STRIPPABLE, logger)
        else:
            raise

    stop_reason = data.get("stop_reason")
    if stop_reason == "refusal":
        details = data.get("stop_details") or {}
        raise LLMResponseError(
            f"모델이 안전상의 이유로 응답을 거부했습니다(category={details.get('category')}). "
            "프롬프트를 조정하거나 다른 모델을 사용해 주세요."
        )

    blocks: List[dict] = data.get("content", [])
    text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    if stop_reason == "max_tokens":
        raise LLMResponseError(
            f"응답이 최대 출력 길이({max_tokens} 토큰)에서 잘렸습니다. "
            "config.json 의 llm.max_output_tokens 를 늘려 주세요."
        )
    return text


# --------------------------------------------------------------------------
# OpenAI (Responses API)
# --------------------------------------------------------------------------
_OPENAI_STRIPPABLE = {
    "temperature": ("temperature",),
    "top_p": ("top_p",),
}


def _call_openai(prompt: str, cfg: dict, logger: logging.Logger) -> str:
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise LLMError("OpenAI API 키가 설정되지 않았습니다.")
    payload: Dict[str, Any] = {
        "model": cfg.get("model") or "gpt-4.1",
        "input": prompt,
        "max_output_tokens": cfg.get("max_output_tokens", 20000),
    }
    if cfg.get("enable_web_search", True):
        payload["tools"] = [{"type": "web_search"}]

    data = _post_pruning("https://api.openai.com/v1/responses",
                         {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                         payload,
                         cfg.get("timeout_sec", 900),
                         _OPENAI_STRIPPABLE, logger)

    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason")
        if reason == "max_output_tokens":
            raise LLMResponseError(
                "응답이 최대 출력 길이에서 잘렸습니다. "
                "config.json 의 llm.max_output_tokens 를 늘려 주세요."
            )

    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]
    texts = []
    for item in data.get("output", []):
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text"):
                texts.append(part.get("text", ""))
    return "\n".join(texts)
