"""Offline v16 model-response acceptance checks; synthetic replies and fake SDKs only."""
import json
import types
import unittest
from unittest.mock import Mock, patch

import llm_client_v14
from llm_client_v14 import ConfigurationError, InvalidResponseError, LLMClient, parse_json_object

V14_ASK_JSON = LLMClient.ask_json
V14_PARSE = llm_client_v14.parse_json_object

import llm_json_v16  # noqa: E402  (imported after capturing the v14 originals)
from llm_json_v16 import TolerantLLMClient, extract_single_json  # noqa: E402


# Spec section 2: the captured Claude reply (contains no task content).
CAPTURED_REPLY = ("The segment is a title only and contains no numeric values, units, or measurable "
                  "technical facts. There is nothing to extract.\n\n{\"facts\": []}")
# A marker that must never appear in an error raised for a rejected reply.
MARKER = "PRIVATE_REPLY_TEXT_7731"

ACCEPTED_CLEAN = [
    ('{"facts": []}', {"facts": []}),
    ('```json\n{"facts": []}\n```', {"facts": []}),
    ('```\n{"facts": []}\n```', {"facts": []}),
    ('  {"facts": [{"value": 4}]}\n', {"facts": [{"value": 4}]}),
]
ACCEPTED_TRIMMED = [
    (CAPTURED_REPLY, {"facts": []}),
    ('Here is the result.\n```json\n{"facts": []}\n```\nThat is all.', {"facts": []}),
    ('Section {제목} has no facts.\n{"facts": []}', {"facts": []}),
    ('[참고] 결과는 아래와 같음\n{"facts": []}', {"facts": []}),
    ('Result:\n{"outer": {"facts": []}}', {"outer": {"facts": []}}),
    ('{"facts": []}\nNo further facts.', {"facts": []}),
    ('Empty braces {} are an object: done.', {}),
]
REJECTED = {
    "two_objects": '{"facts": []}\n{"facts": []}',
    "two_objects_with_prose": 'First {"a": 1} then {"b": 2}',
    "truncated": 'Explanation follows. {"facts": [',
    "outer_unclosed": '{"a": {"facts": []}',
    "outer_unclosed_with_prose": 'Note {"a": {"facts": []}',
    "array": '[{"facts": []}]',
    "array_with_prose": 'Result: [{"facts": []}]',
    "empty_array": 'Nothing: []',
    "string_array": 'Values ["x", "y"] and {"facts": []}',
    "nested_array": 'Values [[1]] and {"facts": []}',
    "broken_array": 'Values [{"facts": ',
    "prose_only": 'There is nothing to extract.',
    "prose_with_bracket_words": '[참고] {제목} 없음',
    "empty": '',
    "whitespace": '   \n ',
    "duplicate_key": 'Result:\n{"facts": [], "facts": []}',
    "nested_duplicate_key": 'Result:\n{"facts": [{"v": 1, "v": 2}]}',
    "nan": 'Result:\n{"facts": [NaN]}',
    "infinity": 'Result:\n{"value": Infinity}',
    "huge_exponent": 'Result:\n{"value": 1e999}',
    "fence_two_objects": '```json\n{"a": 1}\n{"b": 2}\n```',
}


def claude_sdk(text=CAPTURED_REPLY, stop="end_turn"):
    sdk = Mock()
    sdk.messages.create.return_value = types.SimpleNamespace(stop_reason=stop, content=[
        types.SimpleNamespace(type="thinking", thinking="private reasoning"),
        types.SimpleNamespace(type="text", text=text),
    ])
    return sdk


def openai_sdk(content=CAPTURED_REPLY, finish="stop"):
    sdk = Mock()
    sdk.chat.completions.create.return_value = {
        "choices": [{"finish_reason": finish, "message": {"content": content, "refusal": None}}]}
    return sdk


def deep_object(depth):
    return '{"a":' * depth + '1' + '}' * depth


class ExtractSingleJsonTests(unittest.TestCase):
    def assert_rejected(self, value):
        with self.assertRaises(InvalidResponseError) as caught:
            extract_single_json(value)
        error = caught.exception
        self.assertEqual(type(error), InvalidResponseError)
        self.assertEqual(str(error), InvalidResponseError.code)
        self.assertEqual(error.args, (InvalidResponseError.code,))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        return error

    def test_clean_replies_accepted_untrimmed(self):
        for text, expected in ACCEPTED_CLEAN:
            with self.subTest(text=text):
                self.assertEqual(extract_single_json(text), (expected, False))

    def test_captured_reply_fixture_accepted_and_trimmed(self):
        result, trimmed = extract_single_json(CAPTURED_REPLY)
        self.assertEqual(result, {"facts": []})
        self.assertIs(trimmed, True)
        with self.assertRaises(InvalidResponseError):
            parse_json_object(CAPTURED_REPLY)

    def test_single_object_inside_prose_accepted_and_trimmed(self):
        for text, expected in ACCEPTED_TRIMMED:
            with self.subTest(text=text):
                result, trimmed = extract_single_json(text)
                self.assertEqual(result, expected)
                self.assertIs(trimmed, True)

    def test_rejected_replies(self):
        for name, text in REJECTED.items():
            with self.subTest(case=name):
                self.assert_rejected(text)

    def test_non_string_reply_rejected(self):
        for value in (None, b'{"facts": []}', {"facts": []}, ["{}"], 0):
            with self.subTest(value=value):
                self.assert_rejected(value)

    def test_deeply_nested_reply_rejected(self):
        for text in (deep_object(100000), "Result: " + deep_object(100000),
                     "[" * 100000 + "]" * 100000):
            with self.subTest(prefix=text[:12]):
                self.assert_rejected(text)

    def test_recursion_error_while_scanning_is_broken_json(self):
        with patch.object(llm_json_v16.json.JSONDecoder, "raw_decode", side_effect=RecursionError):
            self.assert_rejected('Result:\n{"facts": []}')

    def test_error_carries_no_reply_text(self):
        for template in ('{"%s": [', '%s only', '{"%s": 1} {"%s": 2}', 'x {"%s": NaN}',
                         '{"%s": 1, "%s": 2} note', '[{"%s": 1}]'):
            text = template.replace("%s", MARKER)
            with self.subTest(text=text):
                error = self.assert_rejected(text)
                for rendered in (str(error), repr(error), repr(error.args), repr(vars(error))):
                    self.assertNotIn(MARKER, rendered)

    def test_accepted_result_is_plain_json_dict(self):
        result, _ = extract_single_json('Note:\n{"facts": [{"value": 1.5, "unit": "nm"}]}')
        self.assertIs(type(result), dict)
        self.assertEqual(json.loads(json.dumps(result)), result)


class TolerantClientTests(unittest.TestCase):
    SYSTEM = "  JSON 전용 시스템 지시문\n\t규칙 {제목}  "
    USER = "과제명 구간\n\n<segment>합성 과제</segment>\r\n"

    def test_v14_parser_and_client_are_not_changed(self):
        self.assertIs(LLMClient.ask_json, V14_ASK_JSON)
        self.assertIs(llm_client_v14.parse_json_object, V14_PARSE)
        sdk = claude_sdk()
        with self.assertRaises(InvalidResponseError):
            LLMClient("claude", "synthetic-key", client=sdk).ask_json("s", "u")

    def test_only_ask_json_is_overridden(self):
        self.assertTrue(issubclass(TolerantLLMClient, LLMClient))
        overridden = {name for name, value in vars(TolerantLLMClient).items() if callable(value)}
        self.assertEqual(overridden, {"__init__", "ask_json"})

    def test_counter_starts_at_zero_and_constructor_checks_are_kept(self):
        client = TolerantLLMClient("claude", "synthetic-key", client=claude_sdk())
        self.assertEqual(client.trimmed_responses, 0)
        self.assertIs(type(client.trimmed_responses), int)
        self.assertEqual(client.max_tokens, 8000)
        with self.assertRaises(ConfigurationError):
            TolerantLLMClient("unknown", "synthetic-key")
        with self.assertRaises(llm_client_v14.AuthenticationError):
            TolerantLLMClient("claude")

    def test_claude_prompts_pass_through_and_fixture_is_trimmed(self):
        sdk = claude_sdk()
        client = TolerantLLMClient("claude", "synthetic-key", client=sdk)
        self.assertEqual(client.ask_json(self.SYSTEM, self.USER), {"facts": []})
        self.assertEqual(client.trimmed_responses, 1)
        self.assertEqual(sdk.messages.create.call_count, 1)
        kwargs = sdk.messages.create.call_args.kwargs
        self.assertEqual(kwargs["system"], self.SYSTEM)
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": self.USER}])
        self.assertEqual(kwargs["model"], "claude-sonnet-5-5")
        self.assertNotIn("temperature", kwargs)
        client.ask_json(self.SYSTEM, self.USER)
        self.assertEqual(client.trimmed_responses, 2)

    def test_claude_clean_reply_does_not_count(self):
        for text in ('{"facts": []}', '```json\n{"facts": []}\n```'):
            with self.subTest(text=text):
                client = TolerantLLMClient("claude", "synthetic-key", client=claude_sdk(text))
                self.assertEqual(client.ask_json(self.SYSTEM, self.USER), {"facts": []})
                self.assertEqual(client.trimmed_responses, 0)

    def test_claude_truncation_and_bad_stop_reasons_rejected(self):
        for stop in ("max_tokens", "refusal", "pause_turn"):
            with self.subTest(stop=stop):
                sdk = claude_sdk('{"facts": []}', stop=stop)
                client = TolerantLLMClient("claude", "synthetic-key", client=sdk)
                with self.assertRaises(InvalidResponseError):
                    client.ask_json(self.SYSTEM, self.USER)
                self.assertEqual(client.trimmed_responses, 0)
                self.assertEqual(sdk.messages.create.call_count, 1)

    def test_claude_rejected_replies_raise_without_text(self):
        for name, text in REJECTED.items():
            with self.subTest(case=name):
                client = TolerantLLMClient("claude", "synthetic-key", client=claude_sdk(text))
                with self.assertRaises(InvalidResponseError) as caught:
                    client.ask_json(self.SYSTEM, self.USER)
                self.assertEqual(str(caught.exception), InvalidResponseError.code)
                self.assertEqual(client.trimmed_responses, 0)

    def test_openai_follows_the_same_rule(self):
        sdk = openai_sdk()
        client = TolerantLLMClient("openai", "synthetic-key", client=sdk)
        self.assertEqual(client.ask_json(self.SYSTEM, self.USER), {"facts": []})
        self.assertEqual(client.trimmed_responses, 1)
        kwargs = sdk.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["messages"], [{"role": "system", "content": self.SYSTEM},
                                              {"role": "user", "content": self.USER}])
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        clean = TolerantLLMClient("openai", "synthetic-key", client=openai_sdk('{"facts": []}'))
        self.assertEqual(clean.ask_json(self.SYSTEM, self.USER), {"facts": []})
        self.assertEqual(clean.trimmed_responses, 0)
        for text in ('{"a": 1}\n{"b": 2}', 'note {"facts": ['):
            with self.subTest(text=text):
                bad = TolerantLLMClient("openai", "synthetic-key", client=openai_sdk(text))
                with self.assertRaises(InvalidResponseError):
                    bad.ask_json(self.SYSTEM, self.USER)
        truncated = TolerantLLMClient("openai", "synthetic-key",
                                      client=openai_sdk('{"facts": []}', finish="length"))
        with self.assertRaises(InvalidResponseError):
            truncated.ask_json(self.SYSTEM, self.USER)

    def test_openai_none_content_rejected(self):
        client = TolerantLLMClient("openai", "synthetic-key", client=openai_sdk(None))
        with self.assertRaises(InvalidResponseError):
            client.ask_json(self.SYSTEM, self.USER)
        self.assertEqual(client.trimmed_responses, 0)

    def test_deeply_nested_reply_through_client_rejected(self):
        client = TolerantLLMClient("claude", "synthetic-key",
                                   client=claude_sdk("Result: " + deep_object(100000)))
        with self.assertRaises(InvalidResponseError):
            client.ask_json(self.SYSTEM, self.USER)

    def test_argument_checks_match_parent(self):
        bad_calls = [(None, "u", None), ("s", 1, None), ("s", "u", True), ("s", "u", -0.1),
                     ("s", "u", 2.5), ("s", "u", float("nan")), ("s", "u", float("inf")),
                     ("s", "u", "0.5")]
        for system, user, temperature in bad_calls:
            with self.subTest(system=system, user=user, temperature=temperature):
                sdk = claude_sdk()
                with self.assertRaises(ConfigurationError):
                    TolerantLLMClient("claude", "synthetic-key", client=sdk).ask_json(
                        system, user, temperature)
                with self.assertRaises(ConfigurationError):
                    LLMClient("claude", "synthetic-key", client=sdk).ask_json(system, user, temperature)
                sdk.messages.create.assert_not_called()
        for temperature in (None, 0, 0.3, 2):
            with self.subTest(temperature=temperature):
                client = TolerantLLMClient("claude", "synthetic-key", client=claude_sdk())
                self.assertEqual(client.ask_json("s", "u", temperature), {"facts": []})

    def test_transport_retry_is_the_parent_one(self):
        class Timeout(Exception):
            pass

        sdk = claude_sdk()
        ok = sdk.messages.create.return_value
        sdk.messages.create.side_effect = [Timeout(MARKER), ok]
        client = TolerantLLMClient("claude", "synthetic-key", client=sdk, retry_delay=0)
        self.assertEqual(client.ask_json("s", "u"), {"facts": []})
        self.assertEqual(sdk.messages.create.call_count, 2)
        self.assertEqual(client.trimmed_responses, 1)


if __name__ == "__main__":
    unittest.main()
