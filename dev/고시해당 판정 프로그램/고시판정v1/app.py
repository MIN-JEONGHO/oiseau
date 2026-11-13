"""Windows WebView2 호스트(spec 10). 화면은 로컬 자산만, 연결은 bridge.PUBLIC_METHODS만.

- WebView2 Runtime이 없으면 안내 뒤 종료한다. 구형 엔진(MSHTML 등)으로 바꾸지 않는다.
- 화면 자산(ui/)은 127.0.0.1에만 묶인 루프백 서버가 불변 스냅샷으로 낸다. RPC 경로 없음.
- 네이티브 메시지 경계에서 허용 함수 이름만 통과시키고, 외부 탐색·새 창·원격 자원을 막는다.
- 창 크기는 보이기 전에 모니터 작업 영역에 맞춘다.
- `python app.py --selfcheck`: 창 없이 고시 자료·고시 기준 사양 표(지문)·화면 자산·허용 함수 목록·외부 URL 없음과
  고시 검색(관련어 사전·의미 유사 모델·조항 벡터 지문, 검색 시험 질의)을 확인해 JSON을 표준 출력에 쓰고 통과하면 0으로
  끝난다. exe에서도 같은 옵션이 동작한다(paths 사용). 시험 질의는 고정 글이며 사용자 검색어는 쓰지도 남기지도 않는다.

시뮬레이터 v17 호스트와 같은 방식이며 이 프로그램에 맞게 새로 썼다.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.abc
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import bridge as bridge_module
import paths

# 창 제목: '연구보안 등급분류 분류기준(고시) 검토 · v1.4.2'(이름은 1.3.2부터, 옛 이름 '고시 수준 검토'). exe·폴더 이름(고시판정v1)은 바꾸지 않는다.
TITLE = f"{paths.PROGRAM_NAME} · v{paths.PROGRAM_VERSION}"
# 허용 목록은 브리지 목록을 그대로 따른다(고시 검색 두 함수 search_notices·get_notice_detail 포함).
PUBLIC_METHODS = tuple(bridge_module.PUBLIC_METHODS)
# --selfcheck 검색 시험 질의(spec 5에서 고름): (검색어, 확인할 것). 관련어 사전 검수로 바뀌지 않는 질의만 둔다.
SELFCHECK_DRAM = ("D램", "advanced:item:001")
SELFCHECK_CODE = ("3A001", "dual_use:control:3A001")
SELFCHECK_UNRELATED = "김치찌개"
DEFAULT_WINDOW_SIZE = (1366, 900)
DEFAULT_MIN_SIZE = (760, 560)
WINDOW_MARGIN = 16
DOCUMENT_TYPES = ("과제 문서 (*.hwpx;*.pdf;*.docx)",)
EXCEL_TYPES = ("Excel 파일 (*.xlsx)",)
REPORT_FILENAME = "연구보안등급분류_분류기준고시검토_결과.xlsx"
TEMPLATE_FILENAME = "연구보안등급분류_분류기준고시검토_일괄검토입력양식.xlsx"
UI_FILES = ("index.html", "styles.css", "app.js")
EXTERNAL_REFERENCE = re.compile(r"https?://|//cdn", re.IGNORECASE)
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
       "img-src 'self' data:; connect-src 'none'; object-src 'none'; "
       "base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'")
RUNTIME_MESSAGE = ("Microsoft Edge WebView2 Runtime 사용 불가. "
                   "WebView2 Runtime과 .NET Framework 4.6.2 이상 설치 후 다시 실행 필요")
INITIALIZATION_MESSAGE = ("앱 초기화 실패. 앱 재설치 후 Microsoft Edge WebView2 Runtime 및 "
                          ".NET Framework 4.6.2 이상 확인, 다시 실행 필요")
FORBIDDEN_NATIVE_NAMES = ("_keys.resolve", "_keys._backend.get", "_paths.clear", "_job", "_get_resources", "_path",
                          "__str__", "__class__.__base__.__subclasses__", "_pywebviewAlert", "console",
                          "pywebviewStateUpdate", "pywebviewMoveWindow", "run_single.__wrapped__")


class HostError(RuntimeError):
    """고정된 안전 문구의 시작 오류."""


class _NoLegacyRenderer(importlib.abc.MetaPathFinder):
    """pywebview의 WinForms 구형 엔진(MSHTML 등) 전환을 들여오기 단계에서 막는다."""
    _blocked = frozenset(("mshtml", "cef", "qt", "gtk", "cocoa", "android"))

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("webview.platforms.") and fullname.split(".")[2] in self._blocked:
            raise ImportError(RUNTIME_MESSAGE)
        return None


def require_webview2():
    """네이티브 엔진을 들여오기 전에 WebView2 로더 API로 런타임 버전을 확인한다."""
    if os.name != "nt":
        raise HostError(RUNTIME_MESSAGE)
    try:
        from webview.util import interop_dll_path
        architecture = "win-arm64" if platform.machine().lower() in ("arm64", "aarch64") else (
            "win-x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "win-x86")
        loader = ctypes.WinDLL(str(Path(interop_dll_path(architecture)) / "WebView2Loader.dll"))
        query = loader.GetAvailableCoreWebView2BrowserVersionString
        query.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))
        query.restype = ctypes.c_long
        pointer = ctypes.c_void_p()
        result = query(None, ctypes.byref(pointer))
        if result != 0 or not pointer.value:
            raise HostError(RUNTIME_MESSAGE)
        try:
            version = ctypes.wstring_at(pointer)
            if int(version.split(".")[0]) < 86:
                raise HostError(RUNTIME_MESSAGE)
        finally:
            free = ctypes.OleDLL("ole32").CoTaskMemFree
            free.argtypes = (ctypes.c_void_p,)
            free(pointer)
        return version
    except HostError:
        raise
    except Exception:
        raise HostError(RUNTIME_MESSAGE) from None


# ── 루프백 자산 서버 ─────────────────────────────────────────────────────

class LocalAssetServer:
    """127.0.0.1에만 묶인 정적 자산 서버. 임의 파일 접근·API 경로 없음."""

    def __init__(self, ui_root=None):
        self.root = (Path(ui_root) if ui_root else paths.ui_root()).resolve()
        self._nonce = uuid4().hex
        self._assets = {}
        self.requests = []
        self._lock = threading.Lock()
        if not self.root.is_dir():
            raise HostError("앱 화면 자산 확인 불가. 설치 파일 재확인 필요")
        for path in self.root.rglob("*"):
            if path.is_file():
                resolved = path.resolve()
                if not resolved.is_relative_to(self.root) or path.is_symlink():
                    raise HostError("앱 화면 자산 경계 검증 실패")
                relative = path.relative_to(self.root).as_posix()
                content_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
                if relative.endswith(".woff2"):
                    content_type = "font/woff2"
                self._assets[f"/{self._nonce}/{relative}"] = (resolved.read_bytes(), content_type)
        if f"/{self._nonce}/index.html" not in self._assets:
            raise HostError("앱 시작 화면 확인 불가")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LocalJudgeUI"

            def do_GET(self):
                self._serve(False)

            def do_HEAD(self):
                self._serve(True)

            def do_POST(self):
                self._reply(405, b"Method not allowed", "text/plain", False)

            do_PUT = do_POST
            do_DELETE = do_POST
            do_OPTIONS = do_POST

            def _serve(self, head):
                host = self.headers.get("Host", "")
                origin = self.headers.get("Origin")
                parsed = urlsplit(self.path)
                decoded = unquote(parsed.path)
                if host != owner.authority or (origin and origin != owner.origin):
                    self._reply(403, b"Forbidden", "text/plain", head)
                elif (parsed.scheme or parsed.netloc or parsed.query or "\\" in decoded
                      or ".." in PurePosixPath(decoded).parts or decoded != parsed.path):
                    self._reply(404, b"Not found", "text/plain", head)
                elif parsed.path in owner._assets:
                    data, content_type = owner._assets[parsed.path]
                    self._reply(200, data, content_type, head)
                else:
                    self._reply(404, b"Not found", "text/plain", head)

            def _reply(self, status, data, content_type, head):
                with owner._lock:
                    owner.requests.append({"path": self.path, "status": status, "method": self.command})
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", CSP)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.end_headers()
                if not head:
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def log_message(self, *_):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.authority = f"127.0.0.1:{self._server.server_port}"
        self.origin = "http://" + self.authority
        self.url = f"{self.origin}/{self._nonce}/index.html"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def allowed(self, uri):
        if not isinstance(uri, str):
            return False
        parsed = urlsplit(uri)
        return (parsed.scheme == "http" and parsed.netloc == self.authority
                and parsed.username is None and parsed.password is None
                and not parsed.query and parsed.path in self._assets)

    def hashes(self):
        prefix = f"/{self._nonce}/"
        return {path[len(prefix):]: hashlib.sha256(data).hexdigest() for path, (data, _) in self._assets.items()}

    def close(self):
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(3)


# ── 연결 경계 ──────────────────────────────────────────────────────────

def bind_public_api(window, bridge):
    """허용 함수 목록만 평평하게 노출한다. 객체 노출(js_api)은 없다."""
    if window._js_api is not None:
        raise HostError("앱 연결 경계 검증 실패")
    methods = tuple(getattr(bridge, name) for name in PUBLIC_METHODS)
    if any(not callable(method) for method in methods):
        raise HostError("앱 연결 함수 확인 불가")
    window.expose(*methods)
    if set(window._functions) != set(PUBLIC_METHODS):
        raise HostError("앱 공개 함수 검증 실패")


def _allow_native_message(server, source, raw):
    """실제 네이티브 메시지 처리기 앞의 문. 허용 함수 이름의 호출 묶음만 통과한다."""
    if not server.allowed(source) or type(raw) is not str:
        return False

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError()
            value[key] = item
        return value

    def constant(_):
        raise ValueError()

    try:
        packet = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
        if (type(packet) is not list or len(packet) != 3
                or type(packet[0]) is not str or packet[0] not in PUBLIC_METHODS
                or type(packet[1]) is not str or type(packet[2]) is not str
                or not packet[2] or len(packet[2]) > 128
                or any(not (character.isascii() and (character.isalnum() or character in "_-"))
                       for character in packet[2])):
            return False
        params = json.loads(packet[1], object_pairs_hook=unique, parse_constant=constant)
        return type(params) is list
    except (ValueError, TypeError, RecursionError):
        return False


class NativeBoundary:
    """EdgeChrome의 첫 탐색 전에 메시지 문·외부 탐색 차단·새 창 차단·원격 자원 차단을 건다."""

    def __init__(self, window, server, icon_path=None):
        self.window = window
        self.server = server
        self.icon_path = icon_path
        self.events = []
        self.failure = None
        self.version = None
        self._handlers = []
        self._lock = threading.Lock()

    def _record(self, event, **values):
        with self._lock:
            self.events.append({"event": event, **values})

    def _fail(self):
        self.failure = "WebView2 화면 보안 경계 초기화 실패. " + INITIALIZATION_MESSAGE
        self._record("guard_failure")
        self.window.native.Close()

    def _set_icon(self):
        if not self.icon_path or not Path(self.icon_path).is_file():
            return
        try:
            from System.Drawing import Icon
            self.window.native.Icon = Icon(str(self.icon_path))
            self._record("icon_set")
        except Exception:
            self._record("icon_skipped")

    def before_show(self):
        try:
            import webview.platforms.winforms as winforms
            browser = self.window.native.browser
            if winforms.renderer != "edgechromium" or type(browser).__name__ != "EdgeChrome":
                self._fail()
                return
            self._set_icon()
            control = browser.webview
            if control.CoreWebView2 is not None:
                self._fail()
                return
            original_ready = browser.on_webview_ready
            control.CoreWebView2InitializationCompleted -= original_ready
            original_notify = browser.on_script_notify

            def message(sender, args):
                try:
                    allowed = _allow_native_message(self.server, str(args.Source), str(args.get_WebMessageAsJson()))
                except Exception:
                    allowed = False
                if not allowed:
                    self._record("ipc_denied")
                    return
                original_notify(sender, args)

            control.WebMessageReceived -= original_notify
            browser.on_script_notify = message
            control.WebMessageReceived += message
            control.CreationProperties.AdditionalBrowserArguments += (
                " --disable-background-networking --disable-component-update --no-proxy-server"
                " --host-resolver-rules=\"MAP *.invalid ~NOTFOUND\"")

            def navigation(sender, args):
                if not self.server.allowed(str(args.Uri)):
                    args.Cancel = True
                    self._record("navigation_denied", uri=str(args.Uri))

            def new_window(sender, args):
                args.Handled = True
                self._record("new_window_denied", uri=str(args.Uri))

            def resource(sender, args):
                if self.server.allowed(str(args.Request.Uri)):
                    return
                try:
                    from System import Array, Byte
                    from System.IO import MemoryStream
                    content = MemoryStream(Array[Byte](b"Remote resource denied"))
                    args.Response = sender.Environment.CreateWebResourceResponse(
                        content, 403, "Forbidden", "Content-Type: text/plain\r\nCache-Control: no-store\r\n")
                    self._record("resource_denied", uri=str(args.Request.Uri))
                except Exception:
                    sender.Stop()
                    self._fail()

            def ready(sender, args):
                try:
                    if not args.IsSuccess:
                        self._fail()
                        return
                    from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
                    core = sender.CoreWebView2
                    control.NavigationStarting += navigation
                    core.FrameNavigationStarting += navigation
                    core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All)
                    core.WebResourceRequested += resource
                    browser.on_new_window_request = new_window
                    self.version = str(core.Environment.BrowserVersionString)
                    self._record("guards_installed")
                    original_ready(sender, args)
                except Exception:
                    self._fail()

            self._handlers.extend((navigation, new_window, resource, ready, original_ready, message, original_notify))
            control.CoreWebView2InitializationCompleted += ready
        except Exception:
            self._fail()


# ── 창 크기 맞춤 ───────────────────────────────────────────────────────

def window_geometry(work_area, margin=WINDOW_MARGIN):
    """(시작 너비, 시작 높이, 최소 너비, 최소 높이) 논리 픽셀. 작업 영역을 재지 못하면 기본값."""
    default = DEFAULT_WINDOW_SIZE + DEFAULT_MIN_SIZE
    if (type(margin) is not int or margin < 0 or type(work_area) not in (tuple, list)
            or len(work_area) != 2 or any(type(value) is not int for value in work_area)):
        return default
    width = min(DEFAULT_WINDOW_SIZE[0], work_area[0] - 2 * margin)
    height = min(DEFAULT_WINDOW_SIZE[1], work_area[1] - 2 * margin)
    if width < 1 or height < 1:
        return default
    return width, height, min(DEFAULT_MIN_SIZE[0], width), min(DEFAULT_MIN_SIZE[1], height)


def window_plan(work_rect, dpi, margin=WINDOW_MARGIN):
    """작업 영역(물리 픽셀 rcWork)과 DPI로 물리 최소 크기·크기·가운데 위치를 정한다. 못 재면 None."""
    if (type(dpi) is not int or dpi <= 0 or type(margin) is not int or margin < 0
            or type(work_rect) not in (tuple, list) or len(work_rect) != 4
            or any(type(value) is not int for value in work_rect)):
        return None
    left, top, right, bottom = work_rect
    physical_work = (right - left, bottom - top)
    logical_work = tuple(value * 96 // dpi for value in physical_work)
    if min(logical_work) - 2 * margin < 1:
        return None
    width, height, min_width, min_height = window_geometry(logical_work, margin)

    def physical(value):
        return value * dpi // 96

    size = (physical(width), physical(height))
    return {"physical": {"min_size": (physical(min_width), physical(min_height)), "size": size,
                         "location": (left + (physical_work[0] - size[0]) // 2, top + (physical_work[1] - size[1]) // 2)}}


def _measure_work_area(form):
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = (("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD))

    user32 = ctypes.WinDLL("user32")
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
    user32.GetDpiForWindow.restype = wintypes.UINT
    hwnd = form.Handle.ToInt64()

    def work_rect(monitor):
        if not monitor:
            return None
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        return info.rcWork

    work = None
    try:
        cursor = wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(cursor)):
            work = work_rect(user32.MonitorFromPoint(cursor, 2))
    except Exception:
        work = None
    if work is None:
        work = work_rect(user32.MonitorFromWindow(hwnd, 2))
    if work is None:
        return None
    dpi = int(user32.GetDpiForWindow(hwnd))
    if dpi <= 0:
        return None
    return (int(work.left), int(work.top), int(work.right), int(work.bottom)), dpi


class WindowFit:
    """보이기 전(before_show)에 네이티브 폼의 최소 크기·크기·위치를 작업 영역에 맞춘다. 실패하면 기본 크기."""

    def __init__(self, window, margin=WINDOW_MARGIN):
        self.window = window
        self.margin = margin
        self.outcome = {"applied": False, "reason": "not_run"}

    def before_show(self):
        outcome = {"applied": False, "reason": None}
        try:
            form = self.window.native
            if getattr(form, "IsDisposed", False):
                outcome["reason"] = "window_closed"
            else:
                try:
                    measured = _measure_work_area(form)
                except Exception:
                    measured = None
                plan = window_plan(*measured, self.margin) if measured else None
                if plan is None:
                    outcome["reason"] = "work_area_unavailable"
                else:
                    from System.Drawing import Point, Size
                    from System.Windows.Forms import FormStartPosition
                    physical = plan["physical"]
                    form.MinimumSize = Size(*physical["min_size"])
                    form.Size = Size(*physical["size"])
                    form.StartPosition = FormStartPosition.Manual
                    form.Location = Point(*physical["location"])
                    outcome["applied"] = True
        except Exception:
            outcome = {"applied": False, "reason": "native_fit_failed"}
        self.outcome = outcome


# ── 네이티브 파일 선택 ─────────────────────────────────────────────────

def _documents_folder():
    folder = Path.home() / "Documents"
    return str(folder) if folder.is_dir() else str(Path.home())


def _select_native_path(window, kind):
    """용도별 네이티브 열기/저장 창. 기본 폴더는 문서 폴더(프로그램 폴더 밖)."""
    import webview
    directory = _documents_folder()
    if kind == "attachment":
        result = window.create_file_dialog(webview.FileDialog.OPEN, directory=directory, allow_multiple=False,
                                          file_types=DOCUMENT_TYPES)
    elif kind == "batch_input":
        result = window.create_file_dialog(webview.FileDialog.OPEN, directory=directory, allow_multiple=False,
                                          file_types=EXCEL_TYPES)
    elif kind == "save_report":
        result = window.create_file_dialog(webview.FileDialog.SAVE, directory=directory, save_filename=REPORT_FILENAME,
                                          file_types=EXCEL_TYPES)
    elif kind == "save_template":
        result = window.create_file_dialog(webview.FileDialog.SAVE, directory=directory, save_filename=TEMPLATE_FILENAME,
                                          file_types=EXCEL_TYPES)
    else:
        raise ValueError("Unknown path kind")
    return result[0] if isinstance(result, (tuple, list)) and result else result or None


# ── 자체 확인 ──────────────────────────────────────────────────────────

class _FakeBackend:
    def __init__(self):
        self.values = {}

    def get(self, provider):
        return self.values.get(provider)

    def set(self, provider, key):
        self.values[provider] = key

    def delete(self, provider):
        self.values.pop(provider, None)


def _ui_check():
    root = paths.ui_root()
    files = {}
    external = False
    for name in UI_FILES:
        path = root / name
        exists = path.is_file()
        text = path.read_text(encoding="utf-8") if exists else ""
        found = bool(EXTERNAL_REFERENCE.search(text))
        external = external or found
        files[name] = {"exists": exists, "bytes": len(text.encode("utf-8")) if exists else 0, "external_reference": found}
    html = files["index.html"]
    csp = (root / "index.html").read_text(encoding="utf-8") if html["exists"] else ""
    return dict(root=str(root), files=files, external_references=external,
                csp_meta="Content-Security-Policy" in csp and "connect-src 'none'" in csp,
                font=(root / "assets" / "PretendardVariable.woff2").is_file(),
                icon=(paths.resource_path("book_icon.ico")).is_file())


def selfcheck():
    """창 없이 자원·자산·연결 목록을 확인한 보고서(JSON 가능)를 돌려준다."""
    report = {"pass": False, "frozen": paths.is_frozen(), "program": {"name": paths.PROGRAM_NAME, "version": paths.PROGRAM_VERSION},
              "failures": [], "checks": {}}
    checks = report["checks"]

    def step(name, function):
        try:
            checks[name] = function()
        except HostError as error:
            report["failures"].append(f"{name}: {error}")
        except Exception as error:
            report["failures"].append(f"{name}: {type(error).__name__}")

    def catalogue():
        from notice_catalogue import load_catalogue
        loaded = load_catalogue()
        catalogue.value = loaded
        return dict(catalogue_id=loaded.manifest["catalogue_id"], fingerprint=loaded.fingerprint,
                    clause_count=len(loaded.clauses), root=str(paths.notices_root()))
    catalogue.value = None

    def table():
        from threshold_table import load_threshold_table
        loaded = load_threshold_table(catalogue=catalogue.value)
        table.value = loaded
        return dict(fingerprint=loaded.fingerprint, catalogue_fingerprint=loaded.catalogue_fingerprint,
                    record_count=len(loaded.records), near_percent=loaded.near_percent, path=str(paths.threshold_table_path()))
    table.value = None

    def search():
        # 엔진이 불러올 때 파일 안의 지문을 검증한다(사전: 불러오기, 모델 파일 SHA256·조항 벡터: ensure_semantic).
        # 검증을 통과한 뒤 그 지문 값을 보고서에 적는다.
        import notice_search as ns
        engine = ns.SearchEngine(catalogue.value, table.value)
        status = engine.status()
        if not status["dictionary"]["available"]:
            raise HostError("관련어 사전 확인 실패")
        semantic = engine.ensure_semantic()
        if semantic["state"] != ns.SEMANTIC_READY:
            raise HostError("의미 유사 모델 또는 조항 벡터 확인 실패")
        dictionary = json.loads(ns.dictionary_path().read_text(encoding="utf-8"))
        vectors = json.loads(ns.vectors_path().read_text(encoding="utf-8"))
        model_info = json.loads((ns.model_dir() / ns.MODEL_INFO_NAME).read_text(encoding="utf-8"))
        model_files = {name: model_info["files"][name]["sha256"] for name in ns.MODEL_RUNTIME_FILES}
        if vectors["model"]["fingerprint"] != ns.model_fingerprint(model_files):
            raise HostError("조항 벡터와 의미 유사 모델 지문 불일치")

        def ids(group, top=None):
            return [item["clause_id"] for item in group["items"][:top]]

        queries = {}
        query, expected = SELFCHECK_DRAM
        result = engine.search(query)
        if expected not in ids(result["results"], 10):
            raise HostError("검색 시험 질의 실패: 낱말 검색")
        queries[query] = dict(mode=result["mode"], results=result["results"]["total"], similar=result["similar"]["total"],
                              top=ids(result["results"], 3))
        query, expected = SELFCHECK_CODE
        result = engine.search(query)
        first = result["results"]["items"][0] if result["results"]["items"] else {}
        if (result["mode"] != ns.MODE_CODE or first.get("clause_id") != expected or first.get("reason") != ns.REASON_CODE
                or result["similar"]["total"] != 0):
            raise HostError("검색 시험 질의 실패: 통제번호 검색")
        queries[query] = dict(mode=result["mode"], results=result["results"]["total"], similar=result["similar"]["total"],
                              top=ids(result["results"], 3))
        result = engine.search(SELFCHECK_UNRELATED)
        if result["results"]["total"] or result["similar"]["total"] or result["empty_message"] != ns.NOTICE_NO_RESULTS:
            raise HostError("검색 시험 질의 실패: 무관한 말")
        queries[SELFCHECK_UNRELATED] = dict(mode=result["mode"], results=0, similar=0, top=[])
        if any(key in item for group in ("results", "similar") for item in result[group]["items"]
               for key in ("score", "similarity")):
            raise HostError("검색 결과에 점수 있음")
        return dict(clause_count=len(engine.docs), dictionary=dict(available=True, fingerprint=dictionary["fingerprint"],
                                                                    reviewed_on=status["dictionary"]["reviewed_on"],
                                                                    path=str(ns.dictionary_path())),
                    semantic=dict(state=semantic["state"], model_fingerprint=vectors["model"]["fingerprint"],
                                  model_files=model_files, vectors_fingerprint=vectors["fingerprint"],
                                  vectors_sha256=vectors["vectors"]["sha256"], model_path=str(ns.model_dir()),
                                  vectors_path=str(ns.vectors_path())),
                    queries=queries)

    def ui():
        result = _ui_check()
        if not all(item["exists"] for item in result["files"].values()):
            raise HostError("화면 자산 누락")
        if result["external_references"]:
            raise HostError("화면 자산에 외부 참조 있음")
        if not result["csp_meta"]:
            raise HostError("화면 CSP 메타 없음")
        return result

    def bridge():
        from credential_store import KeyManager
        names = list(PUBLIC_METHODS)
        if names != list(bridge_module.PUBLIC_METHODS) or len(set(names)) != len(names):
            raise HostError("허용 함수 목록 불일치")
        public = {name for name in dir(bridge_module.Bridge) if not name.startswith("_")
                  and callable(getattr(bridge_module.Bridge, name))}
        if public != set(names):
            raise HostError("브리지 공개 함수가 허용 목록과 다름")
        backend = _FakeBackend()
        synthetic_key = "synthetic-selfcheck-credential-" + uuid4().hex
        backend.values["claude"] = synthetic_key
        instance = bridge_module.Bridge(key_manager=KeyManager(backend=backend, environ={}))
        initial = instance.get_initial_state()
        text = json.dumps(initial, ensure_ascii=False)
        if not initial.get("ok") or synthetic_key in text:
            raise HostError("브리지 초기 상태 확인 실패")
        estimate = instance.estimate(["advanced", "core", "dual_use", "military"], True, 1)
        if not estimate.get("ok"):
            raise HostError("예상 호출 수 확인 실패")
        search_state = initial["data"].get("search") or {}
        if not search_state.get("available") or not search_state.get("status"):
            raise HostError("브리지 고시 검색 상태 확인 실패")
        detail = instance.get_notice_detail(SELFCHECK_CODE[1], "")
        too_long = instance.search_notices("가" * (bridge_module.notice_search.MAX_QUERY_CHARS + 1))
        unknown = instance.get_notice_detail("unknown:clause", "")
        if (not detail.get("ok") or detail["data"]["clause_id"] != SELFCHECK_CODE[1] or too_long.get("ok") is not False
                or unknown.get("ok") is not False):
            raise HostError("브리지 고시 검색 함수 확인 실패")
        return dict(public_methods=names, count=len(names), initial_state_ok=True, key_text_absent=True,
                    key_state=initial["data"]["key_state"]["claude"]["has_key"], estimate=estimate["data"]["per_task"],
                    search_available=True, search_detail_ok=True, search_limits_refused=True)

    def native_gate():
        server = LocalAssetServer()
        try:
            def admitted(name):
                return _allow_native_message(server, server.url, json.dumps([name, "[]", "self-check"]))
            accepted = [name for name in PUBLIC_METHODS if admitted(name)]
            rejected = [name for name in FORBIDDEN_NATIVE_NAMES if not admitted(name)]
            if accepted != list(PUBLIC_METHODS) or rejected != list(FORBIDDEN_NATIVE_NAMES):
                raise HostError("네이티브 메시지 문이 허용 목록과 다름")
            return dict(accepted=len(accepted), rejected=len(rejected), loopback=server.authority.startswith("127.0.0.1:"),
                        asset_count=len(server.hashes()))
        finally:
            server.close()

    def runtime():
        try:
            return dict(available=True, version=require_webview2())
        except HostError:
            # 정보로만 적는다: 자체 확인은 창을 띄우지 않으므로 통과 조건이 아니다.
            return dict(available=False, version=None)

    step("catalogue", catalogue)
    step("table", table)
    step("search", search)
    step("ui", ui)
    step("bridge", bridge)
    step("native_gate", native_gate)
    step("webview2", runtime)
    report["pass"] = not report["failures"]
    return report


# ── 실행 ──────────────────────────────────────────────────────────────

def run_app():
    """창을 띄운다. 시작 오류는 고정 문구로 안내하고 1로 끝난다."""
    blocker = _NoLegacyRenderer()
    sys.meta_path.insert(0, blocker)
    server = None
    temporary = None
    boundary = None
    failure = None
    try:
        require_webview2()
        import webview
        webview.settings.update(ALLOW_FILE_URLS=False, ALLOW_DOWNLOADS=False, OPEN_EXTERNAL_LINKS_IN_BROWSER=False,
                                IGNORE_SSL_ERRORS=False, REMOTE_DEBUGGING_PORT=None)
        server = LocalAssetServer().start()
        temporary = Path(tempfile.mkdtemp(prefix="gosi-judge-"))
        profile = temporary / "profile"
        profile.mkdir()
        bridge = bridge_module.Bridge()
        window = webview.create_window(TITLE, url=server.url, js_api=None, width=DEFAULT_WINDOW_SIZE[0],
                                       height=DEFAULT_WINDOW_SIZE[1], min_size=DEFAULT_MIN_SIZE, text_select=True,
                                       zoomable=False, background_color="#F5F3ED")
        bind_public_api(window, bridge)
        bridge._path_selector = lambda kind: _select_native_path(window, kind)
        boundary = NativeBoundary(window, server, icon_path=paths.resource_path("book_icon.ico"))
        window.events.before_show += boundary.before_show
        fit = WindowFit(window)
        window.events.before_show += fit.before_show
        webview.start(gui="edgechromium", debug=False, private_mode=True, storage_path=str(profile), http_server=False)
        if boundary.failure:
            raise HostError(boundary.failure)
    except Exception as error:
        failure = str(error) if isinstance(error, HostError) else INITIALIZATION_MESSAGE
        try:
            ctypes.windll.user32.MessageBoxW(None, failure, TITLE, 0x10)
        except Exception:
            print(failure, file=sys.stderr)
    finally:
        if server:
            server.close()
        if temporary:
            for _ in range(30):
                try:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                    break
                except OSError:
                    time.sleep(.1)
        if blocker in sys.meta_path:
            sys.meta_path.remove(blocker)
    return 1 if failure else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--selfcheck", action="store_true",
                        help="창 없이 고시 자료·고시 기준 사양 표·고시 검색·화면 자산·연결 목록 확인")
    args = parser.parse_args(argv)
    if args.selfcheck:
        report = selfcheck()
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["pass"] else 1
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
