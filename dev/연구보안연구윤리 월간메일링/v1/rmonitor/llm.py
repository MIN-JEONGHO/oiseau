# -*- coding: utf-8 -*-
"""LLM 호출 계층.

웹 검색(그라운딩)을 켠 상태로 프롬프트를 보내고 '텍스트 응답'을 돌려준다.
requests 만 사용하므로 벤더 SDK 설치가 필요 없다.

지원 provider
  - gemini    : Google AI Studio(Generative Language API) / Gemini + Google Search
  - vertex    : Google Cloud Vertex AI (gcloud 인증 토큰 사용)
  - anthropic : Claude + web_search 도구
  - openai    : OpenAI Responses API + web_search 도구
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

import requests

log = logging.getLogger("rmonitor")


class LLMError(RuntimeError):
    pass


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

    last_err = None
    for attempt in range(1, 4):
        try:
            logger.info("LLM 호출 (%s / %s) 시도 %d", provider, cfg.get("model"), attempt)
            text = handlers[provider](prompt, cfg)
            if not text or not text.strip():
                raise LLMError("빈 응답을 받았습니다.")
            return text
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("LLM 호출 실패(%d/3): %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
    raise LLMError(f"LLM 호출에 3회 실패했습니다: {last_err}")


# --------------------------------------------------------------------------
def _post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise LLMError(f"HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def _gemini_payload(prompt: str, cfg: dict) -> dict:
    payload: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": cfg.get("temperature", 0.2),
            "maxOutputTokens": cfg.get("max_output_tokens", 20000),
        },
    }
    if cfg.get("enable_web_search", True):
        # Gemini 2.x 계열: google_search / 1.5 계열: google_search_retrieval
        payload["tools"] = [{"google_search": {}}]
    return payload


def _gemini_extract(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"예상과 다른 응답 형식: {json.dumps(data)[:800]}") from exc
    return "\n".join(p.get("text", "") for p in parts if "text" in p)


def _call_gemini(prompt: str, cfg: dict) -> str:
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise LLMError("Gemini API 키가 설정되지 않았습니다.")
    model = cfg.get("model") or "gemini-2.5-pro"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post(url,
                 {"Content-Type": "application/json", "x-goog-api-key": api_key},
                 _gemini_payload(prompt, cfg),
                 cfg.get("timeout_sec", 900))
    return _gemini_extract(data)


def _call_vertex(prompt: str, cfg: dict) -> str:
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
    data = _post(url,
                 {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                 _gemini_payload(prompt, cfg),
                 cfg.get("timeout_sec", 900))
    return _gemini_extract(data)


def _call_anthropic(prompt: str, cfg: dict) -> str:
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise LLMError("Anthropic API 키가 설정되지 않았습니다.")
    payload: Dict[str, Any] = {
        "model": cfg.get("model") or "claude-sonnet-4-5",
        "max_tokens": cfg.get("max_output_tokens", 20000),
        "temperature": cfg.get("temperature", 0.2),
        "messages": [{"role": "user", "content": prompt}],
    }
    if cfg.get("enable_web_search", True):
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 20}]

    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": api_key,
                  "anthropic-version": "2023-06-01",
                  "content-type": "application/json"},
                 payload,
                 cfg.get("timeout_sec", 900))
    blocks: List[dict] = data.get("content", [])
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_openai(prompt: str, cfg: dict) -> str:
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

    data = _post("https://api.openai.com/v1/responses",
                 {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                 payload,
                 cfg.get("timeout_sec", 900))
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts = []
    for item in data.get("output", []):
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text"):
                texts.append(part.get("text", ""))
    return "\n".join(texts)
