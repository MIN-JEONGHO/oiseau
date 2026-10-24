"""Offline transport contract checks; no real service is contacted."""

import sys
import types
import unittest
from unittest.mock import Mock, patch

from llm_client_v14 import (
    LLMClient, AuthenticationError, ConfigurationError, InvalidResponseError,
    PermissionError, TransientLLMError, UnsupportedModelError, parse_json_object,
)


def completion(content='{"ok":true}', finish="stop", refusal=None):
    return {"choices": [{"finish_reason": finish,
                         "message": {"content": content, "refusal": refusal}}]}


def claude_response(content=None, stop="end_turn"):
    return types.SimpleNamespace(stop_reason=stop, content=content or [
        types.SimpleNamespace(type="thinking", thinking="private reasoning"),
        types.SimpleNamespace(type="text", text='{"ok":'),
        types.SimpleNamespace(type="text", text="true}"),
    ])


def http_response(data=None, status=200):
    response = Mock(status_code=status)
    response.json.return_value = data
    if status >= 400:
        error = RuntimeError("SECRET_KEY and PRIVATE_TASK must not escape")
        error.response = response
        response.raise_for_status.side_effect = error
    return response


class ModelsTests(unittest.TestCase):
    def test_openai_exact_model_reasoning_parameters(self):
        sdk = Mock()
        sdk.chat.completions.create.return_value = completion()
        client = LLMClient("openai", "SECRET_KEY", client=sdk)
        self.assertEqual(client.ask_json("JSON system", "PRIVATE_TASK", 0.4), {"ok": True})
        kwargs = sdk.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6-luna")
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["max_completion_tokens"], 8000)
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)
        self.assertNotIn("logprobs", kwargs)
        self.assertNotIn("api_key", kwargs)
        self.assertNotIn("SECRET_KEY", repr(client))

    def test_reasoning_none_permits_temperature(self):
        sdk = Mock()
        sdk.chat.completions.create.return_value = completion()
        client = LLMClient("openai", "key", reasoning_effort="none", client=sdk)
        client.ask_json("json", "task", 0.2)
        self.assertEqual(sdk.chat.completions.create.call_args.kwargs["temperature"], 0.2)

    def test_lazy_sdk_creation_keys_do_not_cross_provider_or_environment(self):
        openai_factory, claude_factory = Mock(), Mock()
        openai_factory.return_value.chat.completions.create.return_value = completion()
        claude_factory.return_value.messages.create.return_value = claude_response()
        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=openai_factory),
                                     "anthropic": types.SimpleNamespace(Anthropic=claude_factory)}):
            first = LLMClient("openai", "OPENAI_ONLY")
            second = LLMClient("claude", "CLAUDE_ONLY")
            self.assertFalse(openai_factory.called)
            self.assertFalse(claude_factory.called)
            first.ask_json("json", "task")
            second.ask_json("json", "task")
        self.assertEqual(openai_factory.call_args.kwargs["api_key"], "OPENAI_ONLY")
        self.assertEqual(claude_factory.call_args.kwargs["api_key"], "CLAUDE_ONLY")
        self.assertEqual(openai_factory.call_args.kwargs["max_retries"], 0)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "NOT_AUTHORIZED"}):
            with self.assertRaises(AuthenticationError):
                LLMClient("openai")

    def test_cloud_model_override_rejected_without_fallback(self):
        for provider in ("openai", "claude"):
            with self.subTest(provider=provider), self.assertRaises(UnsupportedModelError):
                LLMClient(provider, "key", model="previous-model")

    def test_claude_collects_only_text_and_omits_sampling(self):
        sdk = Mock()
        sdk.messages.create.return_value = claude_response()
        client = LLMClient("claude", "key", client=sdk)
        self.assertEqual(client.ask_json("json", "task", 0.3), {"ok": True})
        kwargs = sdk.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-sonnet-5-5")
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(len(kwargs["messages"]), 1)

    def test_claude_thinking_only_truncation_and_refusal_invalid(self):
        for response in (
            claude_response([{"type": "thinking", "thinking": "hidden"}]),
            claude_response(stop="max_tokens"), claude_response(stop="refusal"),
            claude_response(stop="pause_turn"),
        ):
            sdk = Mock()
            sdk.messages.create.return_value = response
            with self.subTest(response=response), self.assertRaises(InvalidResponseError):
                LLMClient("claude", "key", client=sdk).ask_json("json", "task")
            self.assertEqual(sdk.messages.create.call_count, 1)

    def test_openai_bad_finish_refusal_and_empty_invalid(self):
        responses = [completion(finish="length"), completion(finish="content_filter"),
                     completion(refusal="no"), completion(content=""), {"choices": []}]
        for response in responses:
            sdk = Mock()
            sdk.chat.completions.create.return_value = response
            with self.subTest(response=response), self.assertRaises(InvalidResponseError):
                LLMClient("openai", "key", client=sdk).ask_json("json", "task")
            self.assertEqual(sdk.chat.completions.create.call_count, 1)

    def test_json_fences_and_unicode(self):
        self.assertEqual(parse_json_object('```json\n{"name":"과제"}\n```'), {"name": "과제"})
        self.assertEqual(parse_json_object('{"nested": {"score": 4}}'), {"nested": {"score": 4}})

    def test_no_json_salvage_or_nonfinite_or_duplicate_keys(self):
        for text in ("", "prose {}", "{} trailing", "{}{}", "[]", "null", "3",
                     "```json\n{}\n``` extra", '{"x":NaN}', '{"x":1e999}',
                     '{"x":1,"x":2}', '{"x": Infinity}', '{"x":'):
            with self.subTest(text=text), self.assertRaises(InvalidResponseError):
                parse_json_object(text)

    def test_terminal_errors_sanitized_no_retry(self):
        for status, expected in ((401, AuthenticationError), (403, PermissionError),
                                 (404, UnsupportedModelError), (400, UnsupportedModelError)):
            sdk = Mock()
            error = RuntimeError("SECRET_KEY PRIVATE_TASK raw body")
            error.status_code = status
            sdk.chat.completions.create.side_effect = error
            with self.subTest(status=status), self.assertRaises(expected) as caught:
                LLMClient("openai", "SECRET_KEY", client=sdk).ask_json("json", "PRIVATE_TASK")
            self.assertNotIn("SECRET_KEY", str(caught.exception))
            self.assertNotIn("PRIVATE_TASK", str(caught.exception))
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(sdk.chat.completions.create.call_count, 1)

    def test_transient_retry_and_exhaustion(self):
        sdk = Mock()
        error = RuntimeError("SECRET_KEY")
        error.status_code = 429
        sdk.chat.completions.create.side_effect = [error, completion()]
        client = LLMClient("openai", "key", client=sdk, retry_delay=0)
        self.assertEqual(client.ask_json("json", "task"), {"ok": True})
        self.assertEqual(sdk.chat.completions.create.call_count, 2)
        sdk.chat.completions.create.reset_mock()
        sdk.chat.completions.create.side_effect = error
        with self.assertRaises(TransientLLMError) as caught:
            client.ask_json("json", "task")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(sdk.chat.completions.create.call_count, 3)

    def test_local_ollama_payload_and_explicit_health(self):
        http = Mock()
        http.get.return_value = http_response({"models": [{"name": "test:latest"}]})
        http.post.return_value = http_response({"done": True, "done_reason": "stop",
                                               "message": {"content": '{"ok":true}'}})
        client = LLMClient("ollama", model="test:latest", http_session=http)
        self.assertFalse(http.get.called)
        self.assertTrue(client.check_health())
        self.assertEqual(client.ask_json("json", "task", 0.2), {"ok": True})
        self.assertEqual(http.get.call_args.args[0], "http://localhost:11434/api/tags")
        kwargs = http.post.call_args.kwargs
        self.assertEqual(kwargs["json"]["model"], "test:latest")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertEqual(kwargs["json"]["options"]["temperature"], 0.2)
        http.post.return_value = http_response({"done": True, "done_reason": "length",
                                               "message": {"content": "{}"}})
        with self.assertRaises(InvalidResponseError):
            client.ask_json("json", "task")

    def test_local_lmstudio_normalizes_v1_and_handles_model_missing(self):
        http = Mock()
        http.get.return_value = http_response({"data": [{"id": "loaded"}]})
        http.post.return_value = http_response(completion())
        client = LLMClient("lmstudio", model="loaded", base_url="http://localhost:1234/v1/",
                           http_session=http)
        self.assertEqual(client.discover_models(), ["loaded"])
        self.assertEqual(client.ask_json("json", "task"), {"ok": True})
        self.assertEqual(http.post.call_args.args[0], "http://localhost:1234/v1/chat/completions")
        client.model = "missing"
        with self.assertRaises(UnsupportedModelError):
            client.check_health()

    def test_local_http_auth_does_not_leak_body(self):
        http = Mock()
        http.post.return_value = http_response(status=401)
        client = LLMClient("ollama", http_session=http)
        with self.assertRaises(AuthenticationError) as caught:
            client.ask_json("json", "PRIVATE_TASK")
        self.assertNotIn("PRIVATE_TASK", str(caught.exception))
        self.assertEqual(http.post.call_count, 1)

    def test_local_malformed_http_json_is_invalid_response(self):
        http = Mock()
        for data in ([], None, "not an object"):
            http.post.return_value = http_response(data)
            with self.subTest(data=data), self.assertRaises(InvalidResponseError):
                LLMClient("ollama", http_session=http).ask_json("json", "task")
        response = http_response()
        response.json.side_effect = ValueError("PRIVATE_TASK response body")
        http.post.return_value = response
        with self.assertRaises(InvalidResponseError):
            LLMClient("lmstudio", http_session=http).ask_json("json", "task")

    def test_invalid_json_is_not_transport_retried(self):
        sdk = Mock()
        sdk.chat.completions.create.return_value = completion("{bad JSON")
        with self.assertRaises(InvalidResponseError):
            LLMClient("openai", "key", client=sdk).ask_json("json", "task")
        self.assertEqual(sdk.chat.completions.create.call_count, 1)

    def test_invalid_configuration(self):
        for kwargs in ({"provider": "gemini"}, {"timeout": -1}, {"max_retries": -1},
                       {"reasoning_effort": "random"}, {"timeout": float("nan")},
                       {"max_tokens": True}, {"retry_delay": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigurationError):
                LLMClient(api_key="key", **kwargs)
        for url in ("file:///tmp", "http://user:secret@localhost", "http://localhost/?key=secret"):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                LLMClient("ollama", base_url=url)


if __name__ == "__main__":
    unittest.main()
