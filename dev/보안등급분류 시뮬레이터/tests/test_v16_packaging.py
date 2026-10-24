"""Offline v16 packaging and host-boundary contract; no executable build or native UI.

The spec is executed with inert PyInstaller build targets and the installed
packages' real asset/metadata collectors.  This catches lost relative paths,
incomplete SDK/runtime collection and accidentally bundled working documents.
The release gate separately inspects the actual built archive and runs it.

The host checks here need no WebView: the eleven-name allowlist, the native
message gate, the real pywebview dispatcher against bind_public_api (moved from
the v15 bridge test, spec plan T4/T6), the window title and the save default.
The hidden-WebView run is ``security_grade_classifier_v16.py --self-check``.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import glob
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PyInstaller.utils import hooks

from credential_store import KeyManager
import desktop_bridge_v16
from desktop_bridge_v16 import DesktopBridge
import security_grade_classifier_v16 as host
from test_v16_bridge import FakeBackend, SECRET
from test_v16_engine import Client
from test_v16_notice_review import catalogue


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "보안등급분류시뮬레이터_v16.spec"
V15_SPEC = ROOT / "보안등급분류시뮬레이터_v15.spec"
# Spec 2.2: v16 keeps the v15 pinned dependency set unchanged.
REQUIREMENTS = ROOT / "requirements_v15.txt"
ENTRY = "security_grade_classifier_v16"
EXE_NAME = "보안등급분류시뮬레이터_v16"
TITLE = "연구보안 등급분류 시뮬레이터 · v16"
SAVE_NAME = "v16_검토결과.xlsx"
APP_MODULES = frozenset((
    ENTRY, "desktop_bridge_v16", "batch_v16", "classification_v16",
    "v16_domain", "notice_catalogue_v16", "notice_review_v16",
    "hwpx_writer_v16", "credential_store", "llm_client_v14",
))
# Spec 4.10: the eight v15 runtime modules join the v15 exclusions.
V15_RUNTIME_MODULES = frozenset((
    "security_grade_classifier_v15", "desktop_bridge_v15", "v15_domain", "notice_catalogue_v15",
    "notice_review_v15", "classification_v15", "batch_v15", "hwpx_writer_v15",
))
PUBLIC_METHODS = frozenset((
    "get_initial_state", "select_path", "save_key", "delete_key", "start_single",
    "start_batch", "get_job", "cancel_job", "start_export",
    "search_notice_clauses", "get_notice_clause",
))
# Private helpers, dunder paths and pywebview's implicit native commands.
FORBIDDEN_NAMES = (
    "_keys.resolve", "_keys._backend.get", "_paths.clear", "_jobs.clear", "_get_catalogue",
    "_path", "_path_selector", "_catalogue_loader", "_clause_details.get", "_clause_rows",
    "__str__", "__class__.__base__.__subclasses__", "__dict__._keys.resolve",
    "_pywebviewAlert", "console", "pywebviewStateUpdate", "pywebviewMoveWindow",
    "search_notice_clauses.__globals__", "get_notice_clause.__wrapped__", "Search_notice_clauses",
)
DIRECT_DISTRIBUTIONS = frozenset((
    "lxml", "openpyxl", "requests", "openai", "anthropic", "pywebview",
    "pythonnet", "clr_loader", "cffi", "bottle", "proxy_tools",
    "PyInstaller", "pyinstaller-hooks-contrib",
))
DEVELOPMENT_ONLY = frozenset((
    "playwright", "pymupdf", "pymupdf4llm", "pymupdf-layout", "pypdf",
    "numpy", "onnxruntime", "pytest", "pandas", "torch", "pdfplumber",
))


def required_distributions(names):
    """Evaluate installed mandatory dependencies with this Windows environment."""
    pending = list(names)
    found = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in found:
            continue
        dist = metadata.distribution(name)
        found[name] = dist
        for text in dist.requires or ():
            dependency = Requirement(text)
            if dependency.marker is None or dependency.marker.evaluate({"extra": ""}):
                pending.append(dependency.name)
    return found


def expanded_files(entries):
    """Expand the same file/directory/glob shape accepted by Analysis.datas."""
    mapped = {}
    for source_pattern, destination in entries:
        destination = PurePosixPath(str(destination).replace("\\", "/"))
        if destination.is_absolute() or ".." in destination.parts:
            raise AssertionError("Bundle destination escapes the asset root")
        matches = glob.glob(str(source_pattern), recursive=True)
        if not matches:
            raise AssertionError(f"Packaging source does not exist: {source_pattern}")
        for match in matches:
            source = Path(match).resolve()
            if source.is_dir():
                for file in source.rglob("*"):
                    if file.is_file():
                        mapped[(destination / file.relative_to(source).as_posix()).as_posix()] = file
            else:
                mapped[(destination / source.name).as_posix()] = source
    return mapped


@lru_cache(maxsize=2)
def spec_snapshot(spec=SPEC):
    if not spec.is_file():
        raise AssertionError("The release spec is missing: " + spec.name)
    captured = {}
    calls = []
    collected_files = []

    def analysis(scripts, **options):
        captured["scripts"] = scripts
        captured["analysis"] = options
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[],
                               zipfiles=[], zipped_data=[])

    def exe(*args, **options):
        captured["exe"] = options
        return SimpleNamespace()

    def record(name, original):
        def wrapper(*args, **kwargs):
            calls.append((name, args, kwargs))
            result = original(*args, **kwargs)
            collected_files.extend(result)
            return result
        return wrapper

    # Submodule discovery is represented by a sentinel: the test checks that
    # collection output is actually passed to Analysis, without importing SDKs.
    def submodules(package, **kwargs):
        calls.append(("collect_submodules", (package,), kwargs))
        return [package, package + ".__packaging_probe__"]

    original_data = hooks.collect_data_files
    original_metadata = hooks.copy_metadata
    original_dynamic = hooks.collect_dynamic_libs
    namespace = {"__file__": str(spec), "__name__": "__main__",
                 "SPECPATH": str(ROOT), "SPEC": str(spec),
                 "Analysis": analysis, "PYZ": lambda *a, **kw: object(),
                 "EXE": exe, "COLLECT": lambda *a, **kw: object()}
    with patch.object(hooks, "collect_submodules", submodules), \
            patch.object(hooks, "collect_data_files", record("collect_data_files", original_data)), \
            patch.object(hooks, "copy_metadata", record("copy_metadata", original_metadata)), \
            patch.object(hooks, "collect_dynamic_libs", record("collect_dynamic_libs", original_dynamic)):
        exec(compile(spec.read_text(encoding="utf-8-sig"), str(spec), "exec"), namespace)
    captured["calls"] = calls
    captured["package_sources"] = frozenset(expanded_files(collected_files).values())
    options = captured["analysis"]
    captured["direct_files"] = expanded_files(options.get("datas", []) + options.get("binaries", []))

    # These installed upstream hooks run when their explicitly retained imports
    # enter Analysis.  The actual release archive must still prove they ran.
    hook_files = []
    hidden = set(options.get("hiddenimports", []))
    excluded = set(options.get("excludes", []))
    hook_specs = (
        ("webview", "webview", "__pyinstaller/hook-webview.py"),
        ("clr", "pythonnet", "_pyinstaller/hook-clr.py"),
        ("clr_loader", "_pyinstaller_hooks_contrib", "stdhooks/hook-clr_loader.py"),
    )
    for module, package, relative in hook_specs:
        if module in hidden and module not in excluded:
            package_root = Path(importlib.util.find_spec(package).origin).parent
            result = runpy.run_path(str(package_root / relative))
            hook_files += result.get("datas", []) + result.get("binaries", [])
    captured["runtime_files"] = dict(captured["direct_files"], **expanded_files(hook_files))
    return captured


class PackagingContractTests(unittest.TestCase):
    def test_v16_entry_and_only_current_local_modules(self):
        snapshot = spec_snapshot()
        self.assertEqual([Path(path).resolve() for path in snapshot["scripts"]],
                         [ROOT / (ENTRY + ".py")])
        hidden = set(snapshot["analysis"].get("hiddenimports", []))
        self.assertTrue(APP_MODULES - {ENTRY} <= hidden)
        local_hidden = {name for name in hidden if (ROOT / (name.split(".")[0] + ".py")).exists()}
        self.assertTrue(local_hidden <= APP_MODULES, local_hidden - APP_MODULES)
        # Traverse local imports, including imports inside lazy model functions.
        visited, pending = set(), list(APP_MODULES)
        while pending:
            module = pending.pop()
            if module in visited:
                continue
            visited.add(module)
            tree = ast.parse((ROOT / (module + ".py")).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for name in names:
                    name = name.split(".")[0]
                    if (ROOT / (name + ".py")).is_file():
                        self.assertIn(name, APP_MODULES, "Historical application import enters the bundle")
                        pending.append(name)
        self.assertEqual(visited, set(APP_MODULES))

    def test_exact_project_assets_and_preserved_destinations(self):
        files = spec_snapshot()["direct_files"]
        expected = {"book_icon.ico", "templates/v15/reviewer_opinion.hwpx",
                    "templates/v15/committee_summary.hwpx"}
        expected.update("ui_v16/" + name for name in (
            "index.html", "app.js", "styles.css", "assets/PretendardVariable.woff2",
            "assets/Pretendard-LICENSE.txt"))
        notice_root = ROOT / "resources_v16" / "notices"
        expected.update("resources_v16/notices/" + file.relative_to(notice_root).as_posix()
                        for file in notice_root.rglob("*") if file.is_file())
        # A developer's virtualenv can live inside ROOT. Only sources returned
        # by the actual package collectors are exempt from project asset rules;
        # arbitrary local files (including elsewhere in .dryforge) still fail.
        package_sources = spec_snapshot()["package_sources"]
        project_assets = {target for target, source in files.items()
                          if source.is_relative_to(ROOT) and source not in package_sources}
        self.assertEqual(project_assets, expected)
        self.assertEqual(len([name for name in expected if name.startswith("resources_v16/notices/")]), 25)
        for target in expected:
            self.assertEqual(files[target], (ROOT / target).resolve())
        # Spec 4.10: the v15 screen and frozen catalogue never enter the v16 bundle.
        self.assertFalse([target for target in files if target.startswith(("ui_v15/", "resources_v15/"))])
        manifest = json.loads((notice_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["catalogue_id"], "kr-notices-v16-1")
        for entry in manifest["files"]:
            self.assertIn("resources_v16/notices/" + entry["relative_path"], files)

    def test_sdk_lazy_submodules_data_and_recursive_metadata_are_retained(self):
        snapshot = spec_snapshot()
        calls = snapshot["calls"]
        hidden = set(snapshot["analysis"]["hiddenimports"])
        for package in ("openai", "anthropic"):
            self.assertIn(package + ".__packaging_probe__", hidden)
            self.assertTrue(any(name == "collect_data_files" and args == (package,)
                                for name, args, kwargs in calls))
            self.assertTrue(any(name == "copy_metadata" and args == (package,) and kwargs.get("recursive") is True
                                for name, args, kwargs in calls))
        files = snapshot["direct_files"]
        for name, dist in required_distributions(("openai", "anthropic")).items():
            metadata_files = [str(path).replace("\\", "/") for path in dist.files or ()
                              if str(path).replace("\\", "/").endswith(".dist-info/METADATA")]
            self.assertEqual(len(metadata_files), 1, name)
            self.assertIn(metadata_files[0], files, name)
        for package in ("openai", "anthropic"):
            self.assertIn(package + "/py.typed", files)

    def test_webview_js_managed_and_all_three_native_loader_paths(self):
        snapshot = spec_snapshot()
        hidden = set(snapshot["analysis"]["hiddenimports"])
        self.assertTrue({"webview", "webview.platforms.winforms", "webview.platforms.edgechromium",
                         "webview.platforms.win32", "clr", "pythonnet", "clr_loader", "_cffi_backend"} <= hidden)
        expected = {"webview/js/" + name for name in (
            "api.js", "customize.js", "finish.js", "state.js", "lib/dom_json.js", "lib/polyfill.js")}
        expected.update("webview/lib/" + name for name in (
            "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"))
        expected.update("webview/lib/runtimes/" + architecture + "/native/WebView2Loader.dll"
                        for architecture in ("win-arm64", "win-x64", "win-x86"))
        expected.update("pythonnet/runtime/" + name for name in (
            "Python.Runtime.dll", "Python.Runtime.deps.json", "Python.Runtime.xml"))
        expected.update("clr_loader/ffi/dlls/" + architecture + "/ClrLoader.dll"
                        for architecture in ("amd64", "x86"))
        self.assertTrue(expected <= set(snapshot["runtime_files"]), expected - set(snapshot["runtime_files"]))

    def test_no_development_or_legacy_gui_modules_and_windowed_release(self):
        snapshot = spec_snapshot()
        excluded = set(snapshot["analysis"].get("excludes", []))
        self.assertTrue({"tkinter", "_tkinter", "playwright", "pymupdf", "pypdf", "numpy",
                         "webview.platforms.mshtml", "webview.platforms.qt", "webview.platforms.cef"} <= excluded)
        self.assertFalse({"clr", "pythonnet", "clr_loader", "_cffi_backend", "webview", "openai", "anthropic"} & excluded)
        hidden = set(snapshot["analysis"].get("hiddenimports", []))
        self.assertFalse({"tkinter", "_tkinter", "playwright", "numpy", "fitz", "pymupdf", "pypdf"} & hidden)
        self.assertIs(snapshot["exe"].get("console"), False)
        self.assertIs(snapshot["exe"].get("debug"), False)
        self.assertIs(snapshot["exe"].get("upx"), False)
        self.assertEqual(snapshot["exe"].get("name"), EXE_NAME)
        self.assertEqual([Path(path).resolve() for path in snapshot["exe"].get("icon")],
                         [ROOT / "book_icon.ico"])

    def test_excludes_are_the_v15_list_plus_the_eight_v15_runtime_modules(self):
        v16 = spec_snapshot()["analysis"]["excludes"]
        v15 = spec_snapshot(V15_SPEC)["analysis"]["excludes"]
        self.assertEqual(len(v16), len(set(v16)), "Duplicate exclusion")
        self.assertEqual(set(v16), set(v15) | V15_RUNTIME_MODULES)
        self.assertFalse(set(v15) & V15_RUNTIME_MODULES, "v15 spec unexpectedly excluded itself")
        self.assertFalse(APP_MODULES & set(v16), "A v16 runtime module is excluded")
        # v14-and-earlier runtime modules, PySide6/pandas and the key module stay excluded.
        self.assertTrue({"security_grade_classifier_v12", "security_grade_classifier_v13_test",
                         "security_grade_classifier_v14", "classification_v14", "batch_v14", "v14_domain",
                         "hwpx_writer", "embedded_key", "PySide6", "pandas"} <= set(v16))
        hidden = set(spec_snapshot()["analysis"]["hiddenimports"])
        self.assertFalse(hidden & V15_RUNTIME_MODULES)

    def test_spec_verifies_the_v16_frozen_catalogue_hashes(self):
        text = SPEC.read_text(encoding="utf-8-sig")
        self.assertIn("'resources_v16' / 'notices'", text)
        self.assertNotIn("v15_domain", text.split("excludes=")[0])
        for relative in ("'ui_v16'", "'templates/v15'", "'resources_v16/notices'"):
            self.assertIn(relative, text)
        for stale in ("'ui_v15'", "'resources_v15/notices'", "'resources_v15' / 'notices'"):
            self.assertNotIn(stale, text)

    def test_requirements_are_exact_installed_versions_without_dev_tools(self):
        self.assertTrue(REQUIREMENTS.is_file(), "The v15 pinned requirements are missing")
        pinned = {}
        for line in REQUIREMENTS.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            self.assertIsNone(requirement.url)
            self.assertIsNone(requirement.marker)
            self.assertFalse(requirement.extras)
            specs = list(requirement.specifier)
            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].operator, "==")
            self.assertNotIn("*", specs[0].version)
            name = canonicalize_name(requirement.name)
            self.assertNotIn(name, pinned)
            self.assertEqual(specs[0].version, metadata.version(name), name)
            pinned[name] = specs[0].version
        required = required_distributions(DIRECT_DISTRIBUTIONS)
        self.assertEqual(set(pinned), set(required), "Pin the complete mandatory runtime/build dependency closure")
        self.assertFalse(set(pinned) & {canonicalize_name(name) for name in DEVELOPMENT_ONLY})


class _AllowedSource:
    """Stand-in for LocalAssetServer.allowed with one fixed local page."""
    url = "http://127.0.0.1:65000/nonce/index.html"

    def allowed(self, uri):
        return uri == self.url


def packet(name, params="[]", identifier="synthetic-id"):
    return json.dumps([name, params, identifier])


class HostBoundaryTests(unittest.TestCase):
    def test_title_ui_root_and_eleven_name_allowlist(self):
        self.assertEqual(host.TITLE, TITLE)
        self.assertEqual(len(host.PUBLIC_METHODS), 11)
        self.assertEqual(len(set(host.PUBLIC_METHODS)), 11)
        self.assertEqual(set(host.PUBLIC_METHODS), PUBLIC_METHODS)
        self.assertEqual(host.PUBLIC_METHODS, desktop_bridge_v16.PUBLIC_METHODS)
        bridge_public = {name for name in dir(DesktopBridge)
                         if not name.startswith("_") and callable(getattr(DesktopBridge, name))}
        self.assertEqual(bridge_public, PUBLIC_METHODS)
        server = host.LocalAssetServer()
        try:
            self.assertEqual(server.root, (ROOT / "ui_v16").resolve())
            self.assertEqual(set(server.hashes()), {"index.html", "app.js", "styles.css",
                "assets/PretendardVariable.woff2", "assets/Pretendard-LICENSE.txt"})
            self.assertTrue(server.url.startswith("http://127.0.0.1:"))
        finally:
            server.close()
        html = (ROOT / "ui_v16" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>" + TITLE + "</title>", html)

    def test_host_imports_only_v16_runtime_modules(self):
        tree = ast.parse((ROOT / (ENTRY + ".py")).read_text(encoding="utf-8-sig"))
        local = set()
        for node in ast.walk(tree):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            local.update(name.split(".")[0] for name in names if (ROOT / (name.split(".")[0] + ".py")).is_file())
        self.assertEqual(local, {"desktop_bridge_v16", "credential_store", "notice_catalogue_v16",
                                 "v16_domain", "batch_v16"})

    def test_native_gate_accepts_exactly_the_eleven_public_names(self):
        source = _AllowedSource()
        for name in sorted(PUBLIC_METHODS):
            with self.subTest(name=name):
                self.assertTrue(host._allow_native_message(source, source.url, packet(name)))
                self.assertTrue(host._allow_native_message(source, source.url,
                    packet(name, json.dumps([{"query": "", "family": None, "offset": 0, "limit": 50}]))))

    def test_native_gate_rejects_private_dunder_builtin_and_malformed_packets(self):
        source = _AllowedSource()
        for name in FORBIDDEN_NAMES:
            with self.subTest(name=name):
                self.assertFalse(host._allow_native_message(source, source.url, packet(name)))
        malformed = (
            packet("get_initial_state", identifier=""), packet("get_initial_state", identifier="x" * 129),
            packet("get_initial_state", identifier="bad id"), packet("get_initial_state", params="{}"),
            packet("get_initial_state", params="[NaN]"), packet("get_initial_state", params="not json"),
            json.dumps(["get_initial_state", "[]"]), json.dumps(["get_initial_state", [], "id"]),
            json.dumps({"0": "get_initial_state"}), '["get_initial_state","[]","a","b"]',
            '["get_notice_clause","[{\\"a\\":1,\\"a\\":2}]","id"]', "[]", "",
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                self.assertFalse(host._allow_native_message(source, source.url, raw))
        self.assertFalse(host._allow_native_message(source, source.url, None))
        for origin in ("https://example.invalid/index.html", "http://127.0.0.1:65000/nonce/index.html?x=1",
                       "file:///C:/ui_v16/index.html", None):
            with self.subTest(origin=origin):
                self.assertFalse(host._allow_native_message(source, origin, packet("get_initial_state")))
        real = host.LocalAssetServer()
        try:
            self.assertTrue(host._allow_native_message(real, real.url, packet("search_notice_clauses")))
            self.assertFalse(host._allow_native_message(real, real.origin + "/index.html", packet("get_job")))
        finally:
            real.close()

    def test_bind_public_api_refuses_object_api_missing_or_extra_functions(self):
        class Window:
            def __init__(self, extra=False):
                self._js_api = None
                self._functions = {}
                self.extra = extra

            def expose(self, *functions):
                self._functions.update({function.__name__: function for function in functions})
                if self.extra:
                    self._functions["_keys"] = print

        bridge = DesktopBridge(key_manager=KeyManager(FakeBackend(), environ={}),
                               catalogue_loader=catalogue, client_factory=lambda *a: Client(facts=[]))
        window = Window()
        host.bind_public_api(window, bridge)
        self.assertEqual(set(window._functions), PUBLIC_METHODS)
        self.assertEqual(len(window._functions), 11)
        with_object = Window()
        with_object._js_api = bridge
        with self.assertRaises(host.HostError):
            host.bind_public_api(with_object, bridge)
        with self.assertRaises(host.HostError):
            host.bind_public_api(Window(extra=True), bridge)
        not_callable = SimpleNamespace(**{name: getattr(bridge, name) for name in PUBLIC_METHODS})
        not_callable.get_notice_clause = "not callable"
        with self.assertRaises(host.HostError):
            host.bind_public_api(Window(), not_callable)

    def test_save_dialog_default_name_is_v16(self):
        class Window:
            def __init__(self):
                self.calls = []

            def create_file_dialog(self, dialog, **options):
                self.calls.append((dialog, options))
                return ("C:/synthetic/v16_검토결과.xlsx",)

        import webview
        window = Window()
        self.assertEqual(host._select_native_path(window, "output_excel"), "C:/synthetic/v16_검토결과.xlsx")
        dialog, options = window.calls[-1]
        self.assertEqual(dialog, webview.FileDialog.SAVE)
        self.assertEqual(options["save_filename"], SAVE_NAME)
        self.assertIsNone(host._select_native_path(window, "unknown"))
        self.assertEqual(len(window.calls), 1)
        source = (ROOT / (ENTRY + ".py")).read_text(encoding="utf-8")
        self.assertNotIn("v15_검토결과", source)

    def test_self_check_script_targets_v16_markers_lookups_and_ui_wording(self):
        script = host._selfcheck_script()
        self.assertNotIn("__v15", script)
        self.assertNotIn("v15", script)
        for marker in ("__v16check", "__v16attackReady", "__v16attackGo", "__v16attackDone",
                       "__v16attackChecked", "__v16busyHeld", "__v16busyReleased"):
            self.assertIn(marker, script)
        for name in ("search_notice_clauses", "get_notice_clause", "schema_version===3"):
            self.assertIn(name, script)
        source = (ROOT / (ENTRY + ".py")).read_text(encoding="utf-8")
        self.assertNotIn("__v15", source)
        # Every quoted Korean UI string the self-check waits for exists in ui_v16.
        ui = "".join((ROOT / "ui_v16" / name).read_text(encoding="utf-8") for name in ("index.html", "app.js"))
        bridge_source = (ROOT / "desktop_bridge_v16.py").read_text(encoding="utf-8")
        quoted = set(re.findall(r"'([^'\n]*[가-힣][^'\n]*)'", script))
        self.assertTrue(quoted)
        synthetic = {text for text in quoted if "합성" in text or "실제 연구정보" in text}
        # v15 wording the self-check asserts is absent from the rendered v16 document.
        stale = {"자동 선택", "좋은 판단은", "연구보안 검토실", "研"}
        self.assertTrue(stale - {"研"} <= quoted)
        self.assertIn("'研'", script)
        self.assertIn("'stale wording '+stale", script)
        for text in sorted(quoted - synthetic - stale):
            with self.subTest(text=text):
                self.assertTrue(text in ui or text in bridge_source, text)
        for text in stale:
            self.assertNotIn(text, ui)
        for wording in ("연구개발과제 검토", "자동 선정", "참고 고시", "API 키 저장됨", "API 키 저장되지 않음",
                        "단건 의견서 저장 완료", "연구보안 등급분류 시뮬레이터 · v16"):
            self.assertIn(wording, script)
        self.assertNotIn("단건 의견서를 저장", script)

    def test_host_screen_messages_are_noun_style(self):
        endings = ("니다", "세요", "주세요", "해요", "어요", "아요", "에요", "예요", "까요")
        tree = ast.parse((ROOT / (ENTRY + ".py")).read_text(encoding="utf-8-sig"))
        hangul = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and re.search("[가-힣]", node.value)
                  and not node.value.lstrip().startswith(("\n", "window.", "(", "\r"))]
        self.assertTrue(hangul)
        for text in hangul:
            for sentence in re.split(r"[.\n]", text):
                sentence = sentence.strip()
                with self.subTest(text=sentence):
                    self.assertFalse(sentence.endswith(endings), sentence)


class RealDispatcherTests(unittest.TestCase):
    """Moved from tests/test_v15_bridge.py: the real pywebview dispatcher path."""
    def setUp(self):
        self.backend = FakeBackend()
        self.backend.values["claude"] = SECRET
        self.cat = catalogue()
        self.catalogue_calls = []

        def load():
            self.catalogue_calls.append(True)
            return self.cat
        self.bridge = DesktopBridge(key_manager=KeyManager(self.backend, environ={}), catalogue_loader=load,
                                    client_factory=lambda options, key: Client(facts=[]),
                                    path_selector=lambda purpose: None)

    def test_real_pywebview_dispatcher_cannot_reach_helpers_or_credentials(self):
        from security_grade_classifier_v16 import bind_public_api
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
        self.assertEqual(len(window._functions), 11)
        initial_calls = list(self.backend.calls)
        # Dunder names resolve on js_api=None inside this framework dispatcher;
        # the host's native gate rejects them first (HostBoundaryTests, --self-check).
        with patch("webview.util.logger.error"):
            for method, params in (
                ("_keys.resolve", ["claude"]), ("_keys._backend.get", ["claude"]),
                ("_get_catalogue", []), ("_catalogue_loader", []), ("_path", ["invalid", "input_excel"]),
                ("_paths.clear", []), ("_jobs.clear", []), ("__dict__._keys.resolve", ["claude"]),
                ("_clause_details.get", ["advanced:1"]), ("_clause_rows.__len__", []),
                ("search_notice_clauses.__wrapped__", [{"query": ""}]),
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
        for identifier, method, params in (
            ("allowed-search", "search_notice_clauses", [{"query": "", "family": None, "offset": 0, "limit": 50}]),
            ("allowed-clause", "get_notice_clause", ["advanced:1"]),
            ("rejected-search", "search_notice_clauses", [{"limit": 0}]),
            ("missing-clause", "get_notice_clause", ["missing:clause"]),
        ):
            window.received.clear()
            js_bridge_call(window, method, params, identifier)
            self.assertTrue(window.received.wait(2), identifier)
            self.assertIn(identifier, window.replies[-1])
            self.assertNotIn(SECRET, window.replies[-1])
        self.assertIn('"ok": true', window.replies[-4])
        self.assertIn('"total": 4', window.replies[-4])
        self.assertIn('"ok": true', window.replies[-3])
        self.assertIn('"validation"', window.replies[-2])
        self.assertIn('"not_found"', window.replies[-1])
        self.assertEqual(self.backend.calls, initial_calls + [("get", "claude"), ("get", "openai")])
        self.assertEqual(len(self.catalogue_calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
