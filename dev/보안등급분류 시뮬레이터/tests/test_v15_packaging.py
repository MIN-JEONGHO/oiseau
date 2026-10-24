"""Offline packaging contract; no executable build or native UI is launched.

The spec is executed with inert PyInstaller build targets and the installed
packages' real asset/metadata collectors.  This catches lost relative paths,
incomplete SDK/runtime collection and accidentally bundled working documents.
The release gate separately inspects the actual built archive and runs it.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import glob
import importlib.metadata as metadata
import importlib.util
from pathlib import Path, PurePosixPath
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PyInstaller.utils import hooks


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "보안등급분류시뮬레이터_v15.spec"
REQUIREMENTS = ROOT / "requirements_v15.txt"
ENTRY = "security_grade_classifier_v15"
APP_MODULES = frozenset((
    ENTRY, "desktop_bridge_v15", "batch_v15", "classification_v15",
    "v15_domain", "notice_catalogue_v15", "notice_review_v15",
    "hwpx_writer_v15", "credential_store", "llm_client_v14",
))
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


@lru_cache(maxsize=1)
def spec_snapshot():
    if not SPEC.is_file():
        raise AssertionError("The v15 release spec is missing")
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
    namespace = {"__file__": str(SPEC), "__name__": "__main__",
                 "SPECPATH": str(ROOT), "SPEC": str(SPEC),
                 "Analysis": analysis, "PYZ": lambda *a, **kw: object(),
                 "EXE": exe, "COLLECT": lambda *a, **kw: object()}
    with patch.object(hooks, "collect_submodules", submodules), \
            patch.object(hooks, "collect_data_files", record("collect_data_files", original_data)), \
            patch.object(hooks, "copy_metadata", record("copy_metadata", original_metadata)), \
            patch.object(hooks, "collect_dynamic_libs", record("collect_dynamic_libs", original_dynamic)):
        exec(compile(SPEC.read_text(encoding="utf-8-sig"), str(SPEC), "exec"), namespace)
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
    def test_v15_entry_and_only_current_local_modules(self):
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

    def test_exact_project_assets_and_preserved_destinations(self):
        files = spec_snapshot()["direct_files"]
        expected = {"book_icon.ico", "templates/v15/reviewer_opinion.hwpx",
                    "templates/v15/committee_summary.hwpx"}
        expected.update("ui_v15/" + name for name in (
            "index.html", "app.js", "styles.css", "assets/PretendardVariable.woff2",
            "assets/Pretendard-LICENSE.txt"))
        notice_root = ROOT / "resources_v15" / "notices"
        expected.update("resources_v15/notices/" + file.relative_to(notice_root).as_posix()
                        for file in notice_root.rglob("*") if file.is_file())
        # A developer's virtualenv can live inside ROOT. Only sources returned
        # by the actual package collectors are exempt from project asset rules;
        # arbitrary local files (including elsewhere in .dryforge) still fail.
        package_sources = spec_snapshot()["package_sources"]
        project_assets = {target for target, source in files.items()
                          if source.is_relative_to(ROOT) and source not in package_sources}
        self.assertEqual(project_assets, expected)
        self.assertEqual(len([name for name in expected if name.startswith("resources_v15/notices/")]), 25)
        for target in expected:
            self.assertEqual(files[target], (ROOT / target).resolve())

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
        self.assertIn("v15", snapshot["exe"].get("name", ""))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
