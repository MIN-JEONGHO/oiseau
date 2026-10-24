"""Offline desktop bridge contract checks; no native store, dialog or API access."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import classification_v15 as engine
from credential_store import KeyManager
from desktop_bridge_v15 import DesktopBridge
from notice_catalogue_v15 import CatalogueError
import v15_domain as domain
from test_v15_engine import Client
from test_v15_notice_review import catalogue


PUBLIC_METHODS = {
    "get_initial_state", "select_path", "save_key", "delete_key", "start_single",
    "start_batch", "get_job", "cancel_job", "start_export",
}
ERROR_CODES = {"validation", "catalogue", "credential", "busy", "not_found", "io", "runtime"}
STAGES = {"preflight", "facts", "notices", "candidate", "criteria", "agents", "summary", "documents", "persistence"}
TERMINAL = {"done", "cancelled", "failed"}
SECRET = "synthetic-bridge-secret-never-render"
TASK = {"과제명": "합성 브리지 과제", "현재 기술사양": "속도 20 GHz"}


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.fail = set()
        self.calls = []

    def _check(self, operation, provider):
        self.calls.append((operation, provider))
        if operation in self.fail:
            raise RuntimeError("native credential error " + SECRET)

    def get(self, provider):
        self._check("get", provider)
        return self.values.get(provider)

    def set(self, provider, key):
        self._check("set", provider)
        self.values[provider] = key

    def delete(self, provider):
        self._check("delete", provider)
        self.values.pop(provider, None)


def regenerated(result, output_dir):
    result = deepcopy(result)
    files = [dict(kind="reviewer", reviewer_id=r["reviewer_id"],
                  path=str(Path(output_dir) / (r["reviewer_id"] + ".hwpx")), status="완료", error="")
             for r in result["reviewers"]]
    files.append(dict(kind="summary", reviewer_id=None, path=str(Path(output_dir) / "summary.hwpx"),
                      status="완료", error=""))
    result["documents"] = dict(status="완료", expected_files=len(files), files=files, errors=[])
    return result


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.input = self.root / "input.xlsx"
        self.input.write_bytes(b"synthetic selection; batch runner is injected")
        self.output = self.root / "output.xlsx"
        self.directory = self.root / "documents"
        self.directory.mkdir()
        self.selected = {"input_excel": self.input, "output_excel": self.output,
                         "output_directory": self.directory}
        self.backend = FakeBackend()
        self.backend.values["claude"] = SECRET
        self.cat = catalogue()
        self.clients = []
        self.catalogue_calls = []
        self.client_keys = []
        self.bridges = []
        self.bridge = self.make_bridge()

    def load_catalogue(self):
        self.catalogue_calls.append(True)
        return self.cat

    def make_client(self, options, key):
        self.client_keys.append(key)
        client = Client(facts=[])
        self.clients.append(client)
        return client

    def make_bridge(self, **overrides):
        kwargs = dict(key_manager=KeyManager(self.backend, environ={}),
                      catalogue_loader=self.load_catalogue, client_factory=self.make_client,
                      path_selector=lambda purpose: self.selected[purpose])
        kwargs.update(overrides)
        bridge = DesktopBridge(**kwargs)
        self.bridges.append(bridge)
        return bridge

    def envelope(self, response, *, ok=True, code=None):
        self.assertIsInstance(response, dict)
        self.assertEqual(set(response), {"ok", "data", "error"})
        self.assertIs(response["ok"], ok)
        json.dumps(response, ensure_ascii=False, allow_nan=False)
        self.assertNotIn(SECRET, json.dumps(response, ensure_ascii=False))
        if ok:
            self.assertIsNone(response["error"])
            return response["data"]
        self.assertIsNone(response["data"])
        self.assertEqual(set(response["error"]), {"code", "message"})
        self.assertIn(response["error"]["code"], ERROR_CODES)
        self.assertTrue(response["error"]["message"])
        if code:
            self.assertEqual(response["error"]["code"], code)
        return response["error"]

    def token(self, purpose, bridge=None):
        data = self.envelope((bridge or self.bridge).select_path(purpose))
        self.assertIs(data["cancelled"], False)
        self.assertIsInstance(data["path_token"], str)
        self.assertTrue(data["path_token"])
        self.assertIsInstance(data["display_name"], str)
        self.assertTrue(data["display_name"])
        self.assertNotIn(str(self.root), data["path_token"])
        return data["path_token"]

    def single_request(self, **updates):
        return dict(task=deepcopy(TASK), options={"num_reviewers": 1}, output_dir_token=None) | updates

    def batch_request(self, bridge=None, **updates):
        return dict(input_token=self.token("input_excel", bridge), output_token=self.token("output_excel", bridge),
                    output_dir_token=None, options={"num_reviewers": 1}, workers=1,
                    resume=False, make_forms=False) | updates

    def wait_job(self, job_id, bridge=None):
        bridge = bridge or self.bridge
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            data = self.envelope(bridge.get_job(job_id, 0))
            self.assertEqual(data["job_id"], job_id)
            if data["state"] in TERMINAL:
                return data
            time.sleep(.005)
        self.fail("synthetic bridge job did not finish")

    def start_single(self, request=None, bridge=None):
        bridge = bridge or self.bridge
        data = self.envelope(bridge.start_single(request or self.single_request()))
        self.assertEqual(set(data), {"job_id"})
        self.assertIsInstance(data["job_id"], str)
        return data["job_id"]

    def result(self, task=None):
        return engine.classify_task(task or TASK, {"num_reviewers": 1}, Client(facts=[]), catalogue=self.cat)

    def test_only_nine_public_methods_and_safe_arity_envelopes(self):
        actual = {name for name in dir(self.bridge) if not name.startswith("_") and callable(getattr(self.bridge, name))}
        self.assertEqual(actual, PUBLIC_METHODS)
        valid_args = {
            "get_initial_state": (), "select_path": ("input_excel",),
            "save_key": ("claude", SECRET), "delete_key": ("claude",),
            "start_single": ({},), "start_batch": ({},), "get_job": ("unknown", 0),
            "cancel_job": ("unknown",), "start_export": ({},),
        }
        for name, args in valid_args.items():
            method = getattr(self.bridge, name)
            with self.subTest(method=name, case="extra positional"):
                self.envelope(method(*args, None), ok=False, code="validation")
            with self.subTest(method=name, case="unknown keyword"):
                self.envelope(method(untrusted=True), ok=False, code="validation")
            if args:
                with self.subTest(method=name, case="missing positional"):
                    self.envelope(method(*args[:-1]), ok=False, code="validation")

    def test_initial_state_is_renderer_shape_without_credentials(self):
        data = self.envelope(self.bridge.get_initial_state())
        self.assertEqual(set(data), {"defaults", "criteria", "credential_status", "catalogue", "guideline"})
        self.assertEqual(data["defaults"]["model"], "claude-sonnet-5-5")
        self.assertEqual(data["credential_status"], {"claude": True, "openai": False})
        self.assertEqual(len(data["criteria"]), 8)
        self.assertEqual({entry["id"] for entry in data["criteria"]}, set(range(1, 9)))
        self.assertEqual(data["catalogue"]["status"], "ready")
        self.assertEqual(data["catalogue"]["fingerprint"], self.cat.fingerprint)
        self.assertEqual(len(data["catalogue"]["sources"]), 4)
        self.assertEqual({entry["family"] for entry in data["catalogue"]["families"]}, set(domain.FAMILIES))
        for entry in data["catalogue"]["families"]:
            self.assertEqual((entry["total_clauses"], entry["interpreted_clauses"], entry["unsupported_clauses"]), (1, 1, 0))
        self.assertEqual(data["guideline"]["id"], domain.GUIDELINE_ID)
        for field in ("definitions", "principles"):
            self.assertTrue(data["guideline"][field])
        data["defaults"]["num_reviewers"] = 900
        self.assertNotEqual(self.envelope(self.bridge.get_initial_state())["defaults"]["num_reviewers"], 900)

    def test_credential_provider_isolation_and_safe_failures(self):
        self.envelope(self.bridge.save_key("openai", "synthetic-openai"))
        self.assertEqual(self.backend.values["openai"], "synthetic-openai")
        self.envelope(self.bridge.delete_key("openai"))
        self.assertNotIn("openai", self.backend.values)
        self.assertEqual(self.backend.values["claude"], SECRET)
        for args in (("ollama", SECRET), (None, SECRET), ({}, SECRET), (["claude"], SECRET),
                     ("openai", None), ("openai", 7), ("openai", "***")):
            with self.subTest(args=(args[0], type(args[1]).__name__)):
                self.envelope(self.bridge.save_key(*args), ok=False, code="validation")
        self.backend.fail.add("set")
        self.envelope(self.bridge.save_key("openai", SECRET), ok=False, code="credential")
        self.backend.fail.add("delete")
        self.envelope(self.bridge.delete_key("claude"), ok=False, code="credential")
        self.envelope(self.bridge.delete_key("lmstudio"), ok=False, code="validation")

    def test_new_bridge_reuses_saved_provider_key_and_reports_read_failure(self):
        self.envelope(self.bridge.save_key("openai", "synthetic-restart-openai"))
        fresh = self.make_bridge()
        data = self.envelope(fresh.get_initial_state())
        self.assertEqual(data["credential_status"], {"claude": True, "openai": True})
        self.envelope(fresh.delete_key("openai"))
        newest = self.make_bridge()
        self.assertEqual(self.envelope(newest.get_initial_state())["credential_status"], {"claude": True, "openai": False})
        self.backend.fail.add("get")
        failing = self.make_bridge()
        self.envelope(failing.get_initial_state(), ok=False, code="credential")
        self.envelope(failing.start_single(self.single_request()), ok=False, code="credential")
        self.assertFalse(self.clients)

    def test_failed_save_session_key_remains_usable_with_explicit_warning(self):
        self.backend.values.clear()
        self.backend.fail.add("set")
        self.envelope(self.bridge.save_key("claude", SECRET), ok=False, code="credential")
        self.assertNotIn("claude", self.backend.values)
        job = self.wait_job(self.start_single())
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result"]["status"], "완료")
        self.assertEqual(self.client_keys, [SECRET])
        warnings = " ".join(event["message"] for event in job["events"] if event["stage"] == "preflight")
        for text in ("저장", "이번 실행", "다음 실행"):
            self.assertIn(text, warnings)
        self.assertTrue("실패" in warnings or "못했습니다" in warnings)
        fresh = self.make_bridge()
        self.envelope(fresh.start_single(self.single_request()), ok=False, code="credential")
        self.assertEqual(self.client_keys, [SECRET])

    def test_environment_key_is_used_with_source_warning_and_never_saved(self):
        self.backend.values.clear()
        bridge = self.make_bridge(key_manager=KeyManager(self.backend, environ={"ANTHROPIC_API_KEY": SECRET}))
        self.assertEqual(self.envelope(bridge.get_initial_state())["credential_status"], {"claude": False, "openai": False})
        job = self.wait_job(self.start_single(bridge=bridge), bridge)
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.client_keys, [SECRET])
        self.assertEqual(self.backend.values, {})
        self.assertFalse(any(operation == "set" for operation, _ in self.backend.calls))
        self.assertTrue(any(event["stage"] == "preflight" and "환경변수" in event["message"] for event in job["events"]))

    def test_catalogue_aggregate_recurses_unsupported_conditions(self):
        supported = self.cat.to_dict()["clauses"][0]["condition"]
        unsupported = dict(type="unsupported", predicate_id="unknown", subject="분류 경계",
                           text="합성 미해석 조건", source_anchor="advanced.txt#1", reason="시험 미해석")
        mixed = catalogue(dict(type="all", children=[supported, dict(type="not", child=unsupported)]))
        bridge = self.make_bridge(catalogue_loader=lambda: mixed)
        families = {entry["family"]: entry for entry in self.envelope(bridge.get_initial_state())["catalogue"]["families"]}
        self.assertEqual((families["advanced"]["total_clauses"], families["advanced"]["interpreted_clauses"],
                          families["advanced"]["unsupported_clauses"]), (1, 0, 1))
        self.assertEqual((families["core"]["interpreted_clauses"], families["core"]["unsupported_clauses"]), (1, 0))

    def test_path_selection_cancellation_and_purpose_validation(self):
        first = self.token("input_excel")
        self.selected["input_excel"] = None
        data = self.envelope(self.bridge.select_path("input_excel"))
        self.assertEqual(data, {"cancelled": True, "path_token": None, "display_name": None})
        for purpose in (None, 1, "input", "../../escape", {}):
            with self.subTest(purpose=purpose):
                self.envelope(self.bridge.select_path(purpose), ok=False, code="validation")
        output = self.token("output_excel")
        directory = self.token("output_directory")
        for invalid in (first, output, str(self.directory), "forged-token", 5):
            with self.subTest(invalid=invalid):
                self.envelope(self.bridge.start_single(self.single_request(output_dir_token=invalid)), ok=False, code="validation")
        self.assertNotEqual(first, output)
        self.assertNotEqual(output, directory)

    def test_dialog_errors_are_safe_and_tokens_are_bridge_local(self):
        token = self.token("output_directory")
        other = self.make_bridge()
        self.envelope(other.start_single(self.single_request(output_dir_token=token)), ok=False, code="validation")

        def bad_selector(purpose):
            raise OSError("dialog diagnostic " + SECRET)

        bridge = self.make_bridge(path_selector=bad_selector)
        self.envelope(bridge.select_path("input_excel"), ok=False, code="io")

    def test_requests_reject_types_unknown_keys_and_raw_paths_before_model(self):
        for request in (None, [], "request", {}, self.single_request(task={}), self.single_request(task={"과제명": 7}),
                        self.single_request(task=TASK | {"arbitrary": "injected"}), self.single_request(options=[]),
                        self.single_request(options={"api_key": SECRET}), self.single_request(options={"num_reviewers": True}),
                        self.single_request() | {"output_dir": str(self.directory)}):
            with self.subTest(request=type(request).__name__):
                self.envelope(self.bridge.start_single(request), ok=False, code="validation")
        for request in ({}, self.batch_request(workers=True), self.batch_request(workers=9), self.batch_request(resume=1),
                        self.batch_request(make_forms="false"), self.batch_request(input_token=str(self.input)),
                        self.batch_request(output_token=self.token("input_excel")), self.batch_request() | {"input_path": str(self.input)}):
            with self.subTest(request=request):
                self.envelope(self.bridge.start_batch(request), ok=False, code="validation")
        for job_id, sequence in ((None, 0), (1, 0), ({}, 0), ("unknown", -1), ("unknown", True), ("unknown", .5)):
            with self.subTest(job_id=job_id, sequence=sequence):
                self.envelope(self.bridge.get_job(job_id, sequence), ok=False, code="validation")
        self.envelope(self.bridge.get_job("unknown", 0), ok=False, code="not_found")
        self.envelope(self.bridge.cancel_job("unknown"), ok=False, code="not_found")
        self.assertFalse(self.clients)

    def test_single_result_events_cursor_and_read_copy(self):
        request = self.single_request()
        job_id = self.start_single(request)
        request["task"]["과제명"] = "renderer changed after start"
        job = self.wait_job(job_id)
        self.assertEqual(job["state"], "done")
        result = job["result"]
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["task_name"], TASK["과제명"])
        self.assertEqual(result["documents"]["status"], "미생성")
        self.assertEqual(self.client_keys, [SECRET])
        self.assertTrue(job["events"])
        sequences = [event["sequence"] for event in job["events"]]
        self.assertEqual(sequences, sorted(set(sequences)))
        self.assertGreater(sequences[0], 0)
        for event in job["events"]:
            self.assertEqual(set(event), {"sequence", "stage", "message", "completed", "total"})
            self.assertIn(event["stage"], STAGES)
            self.assertIsInstance(event["message"], str)
        self.assertEqual(self.envelope(self.bridge.get_job(job_id, sequences[-1]))["events"], [])
        middle = sequences[len(sequences) // 2]
        self.assertTrue(all(event["sequence"] > middle for event in self.envelope(self.bridge.get_job(job_id, middle))["events"]))
        result["task_name"] = "mutated DTO"
        job["events"][0]["message"] = "mutated event"
        retained = self.envelope(self.bridge.get_job(job_id, 0))
        self.assertEqual(retained["result"]["task_name"], TASK["과제명"])
        self.assertNotEqual(retained["events"][0]["message"], "mutated event")
        self.assertEqual(self.envelope(self.bridge.cancel_job(job_id))["state"], "done")

    def test_busy_cancel_retains_inflight_result_then_accepts_next_job(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def classify(task, options, client, progress_callback=None, *, catalogue=None):
            entered.set()
            if not release.wait(4):
                raise AssertionError("test did not release synthetic classifier")
            return engine.classify_task(task, options, client, progress_callback=progress_callback, catalogue=catalogue)

        bridge = self.make_bridge(classify=classify)
        batch_request = self.batch_request(bridge)
        job_id = self.start_single(bridge=bridge)
        self.assertTrue(entered.wait(2))
        self.envelope(bridge.start_single(self.single_request()), ok=False, code="busy")
        self.envelope(bridge.start_batch(batch_request), ok=False, code="busy")
        self.assertEqual(self.envelope(bridge.cancel_job(job_id))["state"], "cancelling")
        release.set()
        job = self.wait_job(job_id, bridge)
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(job["result"]["task_name"], TASK["과제명"])
        next_id = self.start_single(bridge=bridge)
        self.assertNotEqual(next_id, job_id)
        self.assertEqual(self.wait_job(next_id, bridge)["state"], "done")
        self.assertEqual(self.envelope(bridge.get_job(job_id, 0))["state"], "cancelled")

    def test_late_callback_cannot_change_terminal_or_next_job_events(self):
        callbacks = []
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def classify(task, options, client, progress_callback=None, *, catalogue=None):
            callbacks.append(progress_callback)
            if len(callbacks) == 2:
                entered.set()
                if not release.wait(4):
                    raise AssertionError("test did not release next synthetic classifier")
            return engine.classify_task(task, options, client, progress_callback=progress_callback, catalogue=catalogue)

        bridge = self.make_bridge(classify=classify)
        first_id = self.start_single(bridge=bridge)
        first = self.wait_job(first_id, bridge)
        self.assertEqual(first["state"], "done")
        second_id = self.start_single(bridge=bridge)
        self.assertTrue(entered.wait(2))
        second = self.envelope(bridge.get_job(second_id, 0))
        self.assertEqual(second["state"], "running")
        callbacks[0](dict(stage="candidate", message="late callback " + SECRET, completed=77, total=99))
        self.assertEqual(self.envelope(bridge.get_job(first_id, 0))["events"], first["events"])
        self.assertEqual(self.envelope(bridge.get_job(second_id, 0))["events"], second["events"])
        release.set()
        self.assertEqual(self.wait_job(second_id, bridge)["state"], "done")

    def test_catalogue_and_worker_exceptions_are_safe(self):
        def bad_catalogue():
            raise CatalogueError("catalogue diagnostic " + SECRET)

        bridge = self.make_bridge(catalogue_loader=bad_catalogue)
        self.envelope(bridge.get_initial_state(), ok=False, code="catalogue")
        self.envelope(bridge.start_single(self.single_request()), ok=False, code="catalogue")

        def bad_classify(*args, **kwargs):
            raise RuntimeError("model diagnostic " + SECRET)

        bridge = self.make_bridge(classify=bad_classify)
        job = self.wait_job(self.start_single(bridge=bridge), bridge)
        self.assertEqual(job["state"], "failed")
        self.assertIsNone(job["result"])
        self.assertTrue(job["events"])
        self.assertNotIn(SECRET, json.dumps(job, ensure_ascii=False))

    def test_export_uses_retained_dto_with_zero_model_or_catalogue_calls(self):
        regenerated_calls = []

        def regenerate(saved, output_dir):
            regenerated_calls.append(deepcopy(saved))
            return regenerated(saved, output_dir)

        bridge = self.make_bridge(regenerator=regenerate)
        source_id = self.start_single(bridge=bridge)
        original = self.wait_job(source_id, bridge)["result"]
        calls = len(self.clients), len(self.catalogue_calls)
        token = self.token("output_directory", bridge)
        request = dict(job_id=source_id, task_fingerprint=original["task_fingerprint"], output_dir_token=token)
        for invalid in ({}, request | {"task_fingerprint": "forged"}, request | {"result": original},
                        request | {"output_dir_token": str(self.directory)}, request | {"job_id": "missing"}):
            self.envelope(bridge.start_export(invalid), ok=False)
        export_id = self.envelope(bridge.start_export(request))["job_id"]
        self.assertNotEqual(export_id, source_id)
        exported = self.wait_job(export_id, bridge)["result"]
        self.assertEqual(exported["schema_version"], 2)
        self.assertEqual(exported["documents"]["status"], "완료")
        self.assertEqual({k: v for k, v in exported.items() if k != "documents"},
                         {k: v for k, v in original.items() if k != "documents"})
        second_id = self.envelope(bridge.start_export(request | {"job_id": export_id}))["job_id"]
        self.assertEqual(self.wait_job(second_id, bridge)["result"]["task_fingerprint"], original["task_fingerprint"])
        self.assertEqual((len(self.clients), len(self.catalogue_calls)), calls)
        self.assertEqual(len(regenerated_calls), 2)

    def test_export_refuses_tampered_retained_python_result(self):
        calls = []

        def regenerate(saved, output_dir):
            calls.append(deepcopy(saved))
            return regenerated(saved, output_dir)

        bridge = self.make_bridge(regenerator=regenerate)
        token = self.token("output_directory", bridge)
        source_id = self.start_single(bridge=bridge)
        original = self.wait_job(source_id, bridge)["result"]
        bridge._jobs[source_id].result["task_name"] = "tampered Python retained result"
        request = dict(job_id=source_id, task_fingerprint=original["task_fingerprint"], output_dir_token=token)
        self.envelope(bridge.start_export(request), ok=False, code="validation")
        self.assertEqual(calls, [])

    def test_document_failure_preserves_classification_and_reports_document_event(self):
        def fail_documents(saved, output_dir):
            saved = deepcopy(saved)
            saved["documents"] = dict(status="실패", expected_files=len(saved["reviewers"]) + 1,
                                      files=[], errors=["합성 의견서 저장 실패"])
            return saved

        bridge = self.make_bridge(regenerator=fail_documents)
        token = self.token("output_directory", bridge)
        job = self.wait_job(self.start_single(self.single_request(output_dir_token=token), bridge), bridge)
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result"]["status"], "완료")
        self.assertEqual(job["result"]["documents"]["status"], "실패")
        self.assertTrue(any(event["stage"] == "documents" and "실패" in event["message"] for event in job["events"]))

    def test_real_pywebview_dispatcher_cannot_reach_helpers_or_credentials(self):
        from security_grade_classifier_v15 import bind_public_api
        from webview.util import js_bridge_call

        class FakeWindow:
            def __init__(self):
                self._js_api = None
                self._functions = {}
                self.replies = []
                self.received = threading.Event()

            def expose(self, *functions):
                self._functions.update({function.__name__: function for function in functions})

            def evaluate_js(self, script):
                self.replies.append(script)
                self.received.set()

        window = FakeWindow()
        bind_public_api(window, self.bridge)
        self.assertIsNone(window._js_api)
        self.assertEqual(set(window._functions), PUBLIC_METHODS)
        initial_calls = list(self.backend.calls)
        with patch("webview.util.logger.error"):
            for method, params in (
                ("_keys.resolve", ["claude"]), ("_keys._backend.get", ["claude"]),
                ("_get_catalogue", []), ("_catalogue_loader", []), ("_path", ["invalid", "input_excel"]),
                ("_paths.clear", []), ("_jobs.clear", []), ("__dict__._keys.resolve", ["claude"]),
            ):
                js_bridge_call(window, method, params, "blocked-private-call")
        self.assertEqual(window.replies, [])
        self.assertEqual(self.backend.calls, initial_calls)
        self.assertEqual(self.catalogue_calls, [])
        js_bridge_call(window, "get_initial_state", [], "allowed-public-call")
        self.assertTrue(window.received.wait(2))
        self.assertEqual(len(window.replies), 1)
        self.assertIn("allowed-public-call", window.replies[0])
        self.assertIn('"ok": true', window.replies[0])
        self.assertNotIn(SECRET, window.replies[0])
        self.assertEqual(len(self.catalogue_calls), 1)

    def batch_report(self, results):
        counts = {status: sum(result["status"] == status for result in results) for status in domain.STATUSES}
        return dict(status="완료", results=deepcopy(results), counts=counts, warnings=[],
                    input_counts={"blank": 0, "example": 0, "duplicate": 0}, task_count=len(results), reused_count=0,
                    output_path=str(self.output), input_path=str(self.input),
                    checkpoint_path=str(self.output) + ".checkpoint.jsonl", audit_path=str(self.output) + ".audit.jsonl",
                    documents_dir=str(self.directory), audit_status="완료", input_fingerprints=[r["task_fingerprint"] for r in results],
                    options_fingerprint=results[0]["options_fingerprint"], selection_mode="auto", catalogue_fingerprint=self.cat.fingerprint)

    def test_batch_runner_receives_frozen_context_and_renderer_report_shape(self):
        seen = []
        report = self.batch_report([self.result()])

        def runner(in_path, out_path, options, client_factory, **kwargs):
            seen.append((in_path, out_path, options, kwargs))
            client_factory()
            kwargs["status_cb"]("합성 저장 상태")
            return deepcopy(report)

        bridge = self.make_bridge(batch_runner=runner)
        request = self.batch_request(bridge, workers=3, resume=True, make_forms=True)
        job_id = self.envelope(bridge.start_batch(request))["job_id"]
        request["options"]["num_reviewers"] = 3
        job = self.wait_job(job_id, bridge)
        self.assertEqual(job["state"], "done")
        wire = job["result"]
        for field in ("results", "counts", "paths", "warnings", "persistence"):
            self.assertIn(field, wire)
        self.assertEqual(wire["results"][0]["schema_version"], 2)
        self.assertEqual(wire["paths"]["input_excel"], str(self.input))
        self.assertEqual(wire["paths"]["output_excel"], str(self.output))
        source, output, options, kwargs = seen[0]
        self.assertEqual((Path(source), Path(output)), (self.input, self.output))
        self.assertEqual(options.num_reviewers, 1)
        self.assertEqual((kwargs["workers"], kwargs["resume"], kwargs["make_forms"]), (3, True, True))
        self.assertIs(kwargs["catalogue"], self.cat)
        self.assertIsInstance(kwargs["cancel_event"], threading.Event)
        self.assertNotIn(SECRET, repr(options))

    def test_batch_cancel_passes_event_and_retains_completed_rows(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        result = self.result()
        report = self.batch_report([result])
        report["task_count"] = 3
        seen = []

        def runner(in_path, out_path, options, client_factory, **kwargs):
            seen.append(kwargs["cancel_event"])
            entered.set()
            if not release.wait(4):
                raise AssertionError("test did not release synthetic batch runner")
            self.assertTrue(kwargs["cancel_event"].is_set())
            return deepcopy(report)

        bridge = self.make_bridge(batch_runner=runner)
        job_id = self.envelope(bridge.start_batch(self.batch_request(bridge)))["job_id"]
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.envelope(bridge.cancel_job(job_id))["state"], "cancelling")
        release.set()
        job = self.wait_job(job_id, bridge)
        self.assertEqual(job["state"], "cancelled")
        self.assertTrue(seen[0].is_set())
        self.assertEqual(job["result"]["results"], [result])
        self.assertEqual(job["result"]["counts"]["cancelled"], 2)

    def test_batch_export_chains_share_latest_durable_report(self):
        first, second = self.result(), self.result(TASK | {"과제명": "합성 두번째"})
        base_report = self.batch_report([first, second])
        seen = []

        def persist(report, saved, replacement):
            seen.append(deepcopy(report))
            updated = deepcopy(report)
            updated["results"] = [deepcopy(replacement) if r["task_fingerprint"] == saved["task_fingerprint"] else r
                                  for r in updated["results"]]
            return dict(result=deepcopy(replacement), report=updated,
                        persistence=dict(status="완료", checkpoint="완료", workbook="완료", audit="완료", warnings=[]))

        bridge = self.make_bridge(batch_runner=lambda *args, **kwargs: deepcopy(base_report),
                                  regenerator=regenerated, persister=persist)
        batch_id = self.envelope(bridge.start_batch(self.batch_request(bridge)))["job_id"]
        self.wait_job(batch_id, bridge)
        calls = len(self.clients), len(self.catalogue_calls)
        output_tokens = []
        for suffix in ("first", "second", "third"):
            directory = self.root / suffix
            directory.mkdir()
            self.selected["output_directory"] = directory
            output_tokens.append(self.token("output_directory", bridge))

        def export(source_id, result, token):
            job_id = self.envelope(bridge.start_export(dict(job_id=source_id,
                task_fingerprint=result["task_fingerprint"], output_dir_token=token)))["job_id"]
            return job_id, self.wait_job(job_id, bridge)["result"]

        first_export, first_updated = export(batch_id, first, output_tokens[0])
        _, second_updated = export(batch_id, second, output_tokens[1])
        _, third_updated = export(first_export, first_updated, output_tokens[2])
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[1]["results"][0]["documents"], first_updated["documents"])
        self.assertEqual(seen[2]["results"][0]["documents"], first_updated["documents"])
        self.assertEqual(seen[2]["results"][1]["documents"], second_updated["documents"])
        self.assertNotEqual(third_updated["documents"], first_updated["documents"])
        self.assertEqual((len(self.clients), len(self.catalogue_calls)), calls)

    def test_failed_checkpoint_export_does_not_advance_shared_report(self):
        original = self.result()
        base_report = self.batch_report([original])
        seen = []

        def persist(report, saved, replacement):
            seen.append(deepcopy(report))
            updated = deepcopy(report)
            updated["results"] = [deepcopy(replacement)]
            return dict(result=deepcopy(replacement), report=updated,
                        persistence=dict(status="실패", checkpoint="실패", workbook="미시도", audit="미시도",
                                         warnings=["합성 체크포인트 실패"]))

        bridge = self.make_bridge(batch_runner=lambda *args, **kwargs: deepcopy(base_report),
                                  regenerator=regenerated, persister=persist)
        batch_id = self.envelope(bridge.start_batch(self.batch_request(bridge)))["job_id"]
        self.wait_job(batch_id, bridge)
        token = self.token("output_directory", bridge)
        source_id = batch_id
        for _ in range(2):
            source_id = self.envelope(bridge.start_export(dict(job_id=source_id,
                task_fingerprint=original["task_fingerprint"], output_dir_token=token)))["job_id"]
            job = self.wait_job(source_id, bridge)
            self.assertEqual(job["result"]["documents"]["status"], "완료")
            self.assertTrue(any(event["stage"] == "persistence" for event in job["events"]))
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1]["results"][0]["documents"], original["documents"])


if __name__ == "__main__":
    unittest.main()
