"""v16 model-response acceptance that tolerates explanatory prose around one JSON object.

A real Claude reply put a sentence before otherwise valid JSON, and the v14 parser,
which accepts only a whole-JSON or whole-fence reply, rejected it. llm_client_v14 is
shared with v14 and v15 and stays frozen, so v16 wraps its parser and client here
instead of changing or monkeypatching that module: the strict v14 parse runs first,
and only when it fails is the reply scanned for complete JSON values. Exactly one
complete JSON object is accepted and then re-checked by the v14 parser (duplicate
keys, NaN and infinities stay rejected); no object, several objects, any array
attempt or a broken object is rejected with InvalidResponseError carrying no reply
text. Transport, retry and truncation checks are the unchanged v14 ones.
"""

import json
import math

from llm_client_v14 import ConfigurationError, InvalidResponseError, LLMClient, parse_json_object


_ARRAY_STARTS = frozenset('{[]"')


def _next_non_space(text, index):
    while index < len(text) and text[index].isspace():
        index += 1
    return text[index] if index < len(text) else ""


def _strict(text):
    """Return the v14 parse result, or None when v14 rejects the text."""
    try:
        return parse_json_object(text)
    except InvalidResponseError:
        return None


def _single_object_span(text):
    """Return (start, end) of the only complete JSON object, or None to reject."""
    decoder = json.JSONDecoder()
    spans = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            end = broken = None
            try:
                _, end = decoder.raw_decode(text, index)
            except RecursionError:
                broken = True
            except ValueError:
                broken = _next_non_space(text, index + 1) == '"'
            if broken:
                return None
            if end is not None:
                spans.append((index, end))
                if len(spans) > 1:
                    return None
                index = end
                continue
        elif char == "[" and _next_non_space(text, index + 1) in _ARRAY_STARTS:
            return None
        index += 1
    return spans[0] if len(spans) == 1 else None


def extract_single_json(text):
    """Return (object, trimmed); trimmed is True only when prose had to be skipped."""
    if not isinstance(text, str):
        raise InvalidResponseError()
    result = _strict(text)
    if result is not None:
        return result, False
    span = _single_object_span(text)
    result = _strict(text[span[0]:span[1]]) if span is not None else None
    if result is None:
        # Raised outside any except block so no decoder error (which holds the
        # reply text) is chained as context.
        raise InvalidResponseError()
    return result, True


class TolerantLLMClient(LLMClient):
    """LLMClient whose ask_json accepts one JSON object wrapped in prose."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trimmed_responses = 0

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
            raise ConfigurationError()
        if temperature is not None and (isinstance(temperature, bool)
                or not isinstance(temperature, (int, float))
                or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ConfigurationError()
        text = self._with_transport_retry(lambda: self._ask_once(system_prompt, user_prompt, temperature))
        result, trimmed = extract_single_json(text)
        if trimmed:
            self.trimmed_responses += 1
        return result
