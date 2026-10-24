"""Offline credential tests: all native API access is replaced by fakes."""

import ctypes
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import credential_store as store


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.fail = set()
        self.calls = []

    def _call(self, operation, provider):
        self.calls.append((operation, provider))
        if operation in self.fail:
            raise RuntimeError("provider leaked sk-synthetic-secret")

    def get(self, provider):
        self._call("get", provider)
        return self.values.get(provider)

    def set(self, provider, key):
        self._call("set", provider)
        self.values[provider] = key

    def delete(self, provider):
        self._call("delete", provider)
        self.values.pop(provider, None)


class FakeNative:
    def __init__(self, key="synthetic-native-key"):
        self.blob = (ctypes.c_ubyte * len(key.encode())).from_buffer_copy(key.encode())
        self.credential = store._CredentialW()
        self.credential.CredentialBlob = self.blob
        self.credential.CredentialBlobSize = len(self.blob)
        self.freed = 0
        self.read_ok = True
        self.write_ok = True
        self.delete_ok = True
        self.calls = []

    def CredReadW(self, target, kind, flags, output):
        self.calls.append(("read", target, kind, flags))
        if self.read_ok:
            pointer = ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(store._CredentialW)))
            pointer[0] = ctypes.pointer(self.credential)
        return self.read_ok

    def CredFree(self, pointer):
        self.freed += 1

    def CredWriteW(self, pointer, flags):
        value = ctypes.cast(pointer, ctypes.POINTER(store._CredentialW)).contents
        self.written = {
            "target": value.TargetName, "kind": value.Type, "persist": value.Persist,
            "user": value.UserName, "key": ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode(),
            "flags": flags,
        }
        return self.write_ok

    def CredDeleteW(self, target, kind, flags):
        self.calls.append(("delete", target, kind, flags))
        return self.delete_ok


class KeyManagerTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.env = {}
        self.manager = store.KeyManager(self.backend, self.env)

    def test_new_application_loads_same_provider_key(self):
        self.manager.apply("claude", "synthetic-claude-key")
        fresh = store.KeyManager(self.backend, {})
        state = fresh.resolve("claude")
        self.assertEqual((state.key, state.source, state.stored), ("synthetic-claude-key", "saved", True))

    def test_provider_separation_and_replacement(self):
        self.manager.apply("claude", "synthetic-a")
        self.manager.apply("openai", "synthetic-b")
        self.manager.apply("claude", "synthetic-c")
        self.assertEqual(self.backend.values, {"claude": "synthetic-c", "openai": "synthetic-b"})
        self.assertEqual(self.manager.resolve("openai").key, "synthetic-b")

    def test_session_saved_environment_precedence(self):
        self.env["ANTHROPIC_API_KEY"] = "synthetic-env"
        self.assertEqual(self.manager.resolve("claude").source, "environment")
        self.backend.values["claude"] = "synthetic-saved"
        self.assertEqual(self.manager.resolve("claude").key, "synthetic-saved")
        self.manager.apply("claude", "synthetic-session")
        self.backend.values["claude"] = "synthetic-outside-change"
        self.assertEqual(self.manager.resolve("claude").key, "synthetic-session")

    def test_environment_is_never_automatically_saved(self):
        self.env["OPENAI_API_KEY"] = "synthetic-env"
        self.assertEqual(self.manager.apply("openai", " ").key, "synthetic-env")
        self.assertNotIn("openai", self.backend.values)
        self.assertFalse(any(call[0] == "set" for call in self.backend.calls))

    def test_empty_input_does_not_overwrite(self):
        self.manager.apply("openai", "synthetic-existing")
        self.manager.apply("openai", "")
        self.manager.apply("openai", None)
        self.assertEqual(self.backend.values["openai"], "synthetic-existing")
        self.assertEqual(sum(call[0] == "set" for call in self.backend.calls), 1)

    def test_missing_and_delete_are_idempotent(self):
        self.assertFalse(self.manager.resolve("claude").has_key)
        self.manager.delete("claude")
        self.manager.apply("claude", "synthetic-to-delete")
        self.assertFalse(self.manager.delete("claude").has_key)
        self.assertFalse(self.manager.resolve("claude").has_key)

    def test_delete_keeps_other_provider(self):
        self.manager.apply("claude", "synthetic-a")
        self.manager.apply("openai", "synthetic-b")
        self.manager.delete("claude")
        self.assertEqual(self.manager.resolve("openai").key, "synthetic-b")

    def test_delete_reveals_explicit_environment_fallback(self):
        self.manager.apply("openai", "synthetic-saved")
        self.env["OPENAI_API_KEY"] = "synthetic-env"
        state = self.manager.delete("openai")
        self.assertEqual((state.key, state.source, state.stored), ("synthetic-env", "environment", False))
        self.assertIn("환경변수", state.warning)
        self.assertNotIn("폐기", state.warning)

    def test_failed_save_is_memory_only_safe_warning(self):
        self.backend.fail.add("set")
        state = self.manager.apply("claude", "sk-synthetic-secret")
        self.assertEqual((state.key, state.source, state.stored), ("sk-synthetic-secret", "session", None))
        self.assertIn("이번 실행", state.warning)
        self.assertNotIn("sk-synthetic-secret", state.warning)
        self.assertFalse(store.KeyManager(self.backend, {}).resolve("claude").has_key)

    def test_failed_load_prompts_reentry_or_explicit_environment(self):
        self.backend.fail.add("get")
        state = self.manager.resolve("openai")
        self.assertFalse(state.has_key)
        self.assertIsNone(state.stored)
        self.assertIn("새 키", state.warning)
        self.assertNotIn("sk-synthetic-secret", state.warning)
        self.env["OPENAI_API_KEY"] = "synthetic-env"
        self.assertEqual(self.manager.resolve("openai").source, "environment")

    def test_failed_delete_clears_memory_without_claiming_success(self):
        self.manager.apply("claude", "synthetic-saved")
        self.backend.fail.add("delete")
        state = self.manager.delete("claude")
        self.assertFalse(state.has_key)
        self.assertIsNone(state.stored)
        self.assertIn("삭제하지 못", state.warning)
        self.assertNotIn("claude", self.manager._session)

    def test_keys_absent_from_repr_and_public_info(self):
        state = self.manager.apply("openai", "sk-synthetic-secret")
        self.assertNotIn("sk-synthetic-secret", repr(state))
        self.assertNotIn("sk-synthetic-secret", repr(self.manager))
        self.assertNotIn("sk-synthetic-secret", json.dumps(state.public_info()))

    def test_masks_and_malformed_values_are_rejected_without_echo(self):
        for value in ("********", "sk-****1234", "••••••", "●●●●", "<saved>", "[saved]", "a\nsecret", "a\x00secret", 42):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as error:
                    self.manager.apply("openai", value)
                self.assertNotIn(str(value), str(error.exception))
        self.assertEqual(self.backend.values, {})

    def test_invalid_environment_mask_is_not_used(self):
        self.env["OPENAI_API_KEY"] = "********"
        self.assertFalse(self.manager.resolve("openai").has_key)

    def test_invalid_unicode_or_oversize_key_is_safe_and_never_saved(self):
        for value in ("synthetic-secret-\ud800", "s" * (store.MAX_CREDENTIAL_BYTES + 1)):
            with self.assertRaises(ValueError) as error:
                self.manager.apply("openai", value)
            self.assertNotIn(value, str(error.exception))
        self.assertEqual(self.backend.calls, [])

    def test_unknown_provider_is_rejected_before_backend_access(self):
        with self.assertRaises(ValueError):
            self.manager.resolve("unknown-secret-provider")
        self.assertEqual(self.backend.calls, [])


class NativeContractTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeNative()
        self.backend = store.WindowsCredentialBackend()
        self.backend._api = self.api

    def test_only_named_credential_and_read_buffer_is_freed(self):
        self.assertEqual(self.backend.get("claude"), "synthetic-native-key")
        self.assertEqual(self.api.freed, 1)
        self.assertEqual(self.api.calls, [("read", store.SERVICE_NAMESPACE + "/claude", 1, 0)])

    def test_read_buffer_freed_even_when_blob_invalid(self):
        self.api.blob[0] = 0xff
        with self.assertRaises(store.CredentialStoreError):
            self.backend.get("openai")
        self.assertEqual(self.api.freed, 1)

    def test_write_is_generic_current_machine_persistent(self):
        self.backend.set("openai", "synthetic-replacement")
        self.assertEqual(self.api.written, {
            "target": store.SERVICE_NAMESPACE + "/openai", "kind": 1,
            "persist": 2, "user": "openai", "key": "synthetic-replacement", "flags": 0,
        })

    def test_native_missing_is_normal_read_and_delete(self):
        self.api.read_ok = self.api.delete_ok = False
        with patch.object(store.ctypes, "get_last_error", return_value=1168, create=True):
            self.assertIsNone(self.backend.get("claude"))
            self.backend.delete("claude")
        self.assertEqual(self.api.freed, 0)

    def test_other_native_errors_are_explicit(self):
        self.api.read_ok = self.api.write_ok = self.api.delete_ok = False
        with patch.object(store.ctypes, "get_last_error", return_value=5, create=True):
            for operation in (
                lambda: self.backend.get("claude"),
                lambda: self.backend.set("claude", "sk-synthetic-secret"),
                lambda: self.backend.delete("claude"),
            ):
                with self.assertRaises(store.CredentialStoreError) as error:
                    operation()
                self.assertIn("5", str(error.exception))
                self.assertNotIn("sk-synthetic-secret", str(error.exception))

    def test_namespace_has_no_version_and_provider_isolation(self):
        self.assertNotEqual(self.backend.target_name("claude"), self.backend.target_name("openai"))
        self.assertNotIn("v14", store.SERVICE_NAMESPACE.lower())


if __name__ == "__main__":
    unittest.main()
