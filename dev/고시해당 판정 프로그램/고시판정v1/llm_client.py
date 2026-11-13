"""Isolated v14 model transport. Credentials belong to the calling application.

No request, response, SDK exception text, or credential is included in errors.
The injected SDK/HTTP clients make every transport test runnable offline.
"""

import json
import math
import re
import time
from urllib.parse import urlsplit


DEFAULT_MODELS = {
    "claude": "claude-sonnet-5-5",
    "openai": "gpt-6-luna",
    "ollama": "qwen2.5:14b",
    "lmstudio": "local-model",
}
DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234",
}


class LLMError(RuntimeError):
    code = "model_error"
    retryable = False

    def __init__(self):
        super().__init__(self.code)


class ConfigurationError(LLMError):
    code = "invalid_model_configuration"


class AuthenticationError(LLMError):
    code = "model_authentication_failed"


class PermissionError(LLMError):
    code = "model_permission_denied"


class UnsupportedModelError(LLMError):
    code = "model_unavailable_or_unsupported"


class InvalidResponseError(LLMError):
    code = "invalid_or_incomplete_model_response"


class TransientLLMError(LLMError):
    code = "temporary_model_connection_failure"
    retryable = True


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def parse_json_object(text):
    """Accept a JSON object or one complete JSON fence, never substring salvage."""
    if not isinstance(text, str) or not text.strip():
        raise InvalidResponseError()
    cleaned = text.strip()
    if cleaned.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL | re.IGNORECASE)
        if not match:
            raise InvalidResponseError()
        cleaned = match.group(1).strip()
    try:
        def reject_constant(_):
            raise ValueError()

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        result = json.loads(cleaned, parse_constant=reject_constant, object_pairs_hook=unique_object)
        # JSON's exponent syntax can otherwise silently produce an infinite float.
        pending = [result]
        while pending:
            value = pending.pop()
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError, RecursionError):
        raise InvalidResponseError() from None


def _safe_error(exc):
    """Classify using types/status only; never expose str(exc) or response bodies."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    name = type(exc).__name__.lower()
    if status == 401 or name == "authenticationerror":
        return AuthenticationError()
    if status == 403 or name == "permissiondeniederror":
        return PermissionError()
    if status in (400, 404, 405, 409, 422):
        return UnsupportedModelError()
    if status in (408, 425, 429) or isinstance(status, int) and status >= 500:
        return TransientLLMError()
    if any(word in name for word in ("timeout", "connection", "ratelimit")):
        return TransientLLMError()
    return LLMError()


def _json_body(response):
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise InvalidResponseError() from None
    if not isinstance(data, dict):
        raise InvalidResponseError()
    return data


class LLMClient:
    def __init__(self, provider="claude", api_key=None, model=None, base_url=None, *,
                 timeout=600, max_tokens=8000, reasoning_effort="medium", client=None,
                 http_session=None, max_retries=2, retry_delay=0.5):
        if provider not in DEFAULT_MODELS:
            raise ConfigurationError()
        chosen_model = model or DEFAULT_MODELS[provider]
        if not isinstance(chosen_model, str) or not chosen_model.strip():
            raise ConfigurationError()
        if provider in ("claude", "openai") and chosen_model != DEFAULT_MODELS[provider]:
            raise UnsupportedModelError()
        if provider in ("claude", "openai") and not (isinstance(api_key, str) and api_key.strip()):
            raise AuthenticationError()
        if reasoning_effort not in ("none", "low", "medium", "high", "xhigh", "max"):
            raise ConfigurationError()
        if (not isinstance(timeout, (float, int)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or timeout <= 0
                or type(max_tokens) is not int or max_tokens < 1
                or type(max_retries) is not int or not 0 <= max_retries <= 5
                or not isinstance(retry_delay, (float, int)) or isinstance(retry_delay, bool)
                or not math.isfinite(retry_delay) or retry_delay < 0):
            raise ConfigurationError()
        self.provider = provider
        self.model = chosen_model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._api_key = api_key.strip() if isinstance(api_key, str) else None
        self._client = client
        self._http = http_session
        self.base_url = None
        if provider in DEFAULT_BASE_URLS:
            url = base_url or DEFAULT_BASE_URLS[provider]
            try:
                parts = urlsplit(url)
                valid = (parts.scheme in ("http", "https") and bool(parts.hostname)
                         and not parts.username and not parts.password
                         and not parts.query and not parts.fragment)
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise ConfigurationError()
            self.base_url = url.rstrip("/")
            if provider == "lmstudio" and self.base_url.endswith("/v1"):
                self.base_url = self.base_url[:-3]

    def __repr__(self):
        # Even a caller-supplied local model/base URL may contain sensitive text.
        return f"LLMClient(provider={self.provider!r})"

    def _ensure_client(self):
        if self.provider in DEFAULT_BASE_URLS:
            if self._http is None:
                import requests
                self._http = requests.Session()
            return
        if self._client is None:
            if self.provider == "openai":
                from openai import OpenAI
                self._client = OpenAI(api_key=self._api_key, timeout=self.timeout, max_retries=0)
            else:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self._api_key, timeout=self.timeout, max_retries=0)

    def _with_transport_retry(self, operation):
        for attempt in range(self.max_retries + 1):
            try:
                self._ensure_client()
                return operation()
            except LLMError:
                raise
            except (ImportError, ModuleNotFoundError):
                raise ConfigurationError() from None
            except Exception as exc:
                error = _safe_error(exc)
                if not error.retryable or attempt >= self.max_retries:
                    raise error from None
                time.sleep(self.retry_delay * (2 ** attempt))

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
            raise ConfigurationError()
        if temperature is not None and (isinstance(temperature, bool)
                or not isinstance(temperature, (int, float))
                or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ConfigurationError()
        text = self._with_transport_retry(lambda: self._ask_once(system_prompt, user_prompt, temperature))
        return parse_json_object(text)

    def _ask_once(self, system_prompt, user_prompt, temperature):
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        if self.provider == "openai":
            payload = dict(model=self.model, messages=messages,
                           response_format={"type": "json_object"},
                           max_completion_tokens=self.max_tokens,
                           reasoning_effort=self.reasoning_effort)
            if self.reasoning_effort == "none" and temperature is not None:
                payload["temperature"] = temperature
            return self._openai_text(self._client.chat.completions.create(**payload))
        if self.provider == "claude":
            # Adaptive thinking is the model default; sampling parameters are omitted.
            response = self._client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}])
            if _field(response, "stop_reason") not in ("end_turn", "stop_sequence"):
                raise InvalidResponseError()
            blocks = _field(response, "content", []) or []
            if not isinstance(blocks, (list, tuple)):
                raise InvalidResponseError()
            parts = [_field(block, "text", "") for block in blocks
                     if _field(block, "type") == "text"]
            if any(not isinstance(part, str) for part in parts):
                raise InvalidResponseError()
            return "".join(parts)
        if self.provider == "ollama":
            options = {"num_predict": self.max_tokens}
            if temperature is not None:
                options["temperature"] = temperature
            response = self._http.post(self.base_url + "/api/chat", timeout=self.timeout,
                json={"model": self.model, "messages": messages, "stream": False,
                      "format": "json", "options": options})
            response.raise_for_status()
            data = _json_body(response)
            if (data.get("error") or data.get("done") is not True
                    or data.get("done_reason") in ("length", "error", "unload")):
                raise InvalidResponseError()
            return _field(data.get("message", {}), "content", "")
        payload = dict(model=self.model, messages=messages,
                       response_format={"type": "json_object"}, max_tokens=self.max_tokens)
        if temperature is not None:
            payload["temperature"] = temperature
        response = self._http.post(self.base_url + "/v1/chat/completions",
                                   json=payload, timeout=self.timeout)
        response.raise_for_status()
        return self._openai_text(_json_body(response))

    @staticmethod
    def _openai_text(response):
        choices = _field(response, "choices", []) or []
        if (not isinstance(choices, (list, tuple)) or not choices
                or _field(choices[0], "finish_reason") != "stop"):
            raise InvalidResponseError()
        message = _field(choices[0], "message", {})
        if _field(message, "refusal") or _field(message, "tool_calls"):
            raise InvalidResponseError()
        return _field(message, "content", "")

    def discover_models(self):
        """Fetch the local server's actual model IDs only when explicitly requested."""
        if self.provider not in DEFAULT_BASE_URLS:
            return [self.model]

        def discover():
            path = "/api/tags" if self.provider == "ollama" else "/v1/models"
            response = self._http.get(self.base_url + path, timeout=min(self.timeout, 5))
            response.raise_for_status()
            data = _json_body(response)
            entries = data.get("models" if self.provider == "ollama" else "data")
            key = "name" if self.provider == "ollama" else "id"
            if not isinstance(entries, list):
                raise InvalidResponseError()
            names = [_field(entry, key) for entry in entries]
            if any(not isinstance(name, str) or not name for name in names):
                raise InvalidResponseError()
            return names

        return self._with_transport_retry(discover)

    def check_health(self):
        if self.provider in DEFAULT_BASE_URLS and self.model not in self.discover_models():
            raise UnsupportedModelError()
        return True
