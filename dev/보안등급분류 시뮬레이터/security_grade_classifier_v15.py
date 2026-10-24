"""Windows WebView2 host for the local v15 review interface.

The renderer receives nine explicitly exposed functions, never a Python object.
The HTTP service serves an immutable snapshot of ui_v15 only; it has no RPC routes.
``--self-check report.json`` uses the same host with synthetic credentials/model
and a hidden, isolated WebView2 profile. No personal browser is controlled.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.abc
import importlib.metadata
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
from uuid import uuid4


TITLE = "연구보안 등급분류 시뮬레이터 · v15"
PUBLIC_METHODS = (
    "get_initial_state", "select_path", "save_key", "delete_key",
    "start_single", "start_batch", "get_job", "cancel_job", "start_export",
)
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
       "img-src 'self' data:; connect-src 'none'; object-src 'none'; "
       "base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'")
RUNTIME_MESSAGE = ("Microsoft Edge WebView2 Runtime을 사용할 수 없습니다. "
                   "WebView2 Runtime과 .NET Framework 4.6.2 이상을 설치한 뒤 다시 실행해 주세요.")
INITIALIZATION_MESSAGE = ("앱을 초기화하지 못했습니다. 앱을 다시 설치하고 Microsoft Edge WebView2 Runtime 및 "
                          ".NET Framework 4.6.2 이상을 확인한 뒤 다시 실행해 주세요.")


class HostError(RuntimeError):
    """Fixed, non-sensitive startup error."""


def asset_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()


class _NoLegacyRenderer(importlib.abc.MetaPathFinder):
    """Prevent pywebview's WinForms fallback before MSHTML has side effects."""
    _blocked = frozenset(("mshtml", "cef", "qt", "gtk", "cocoa", "android"))

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("webview.platforms.") and fullname.split(".")[2] in self._blocked:
            raise ImportError(RUNTIME_MESSAGE)
        return None


def require_webview2():
    """Check the loader API before importing a native renderer or reading keys."""
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


class LocalAssetServer:
    """Loopback static assets, with no arbitrary file access or API endpoint."""
    def __init__(self, ui_root=None):
        self.root = (Path(ui_root) if ui_root else asset_root() / "ui_v15").resolve()
        self._nonce = uuid4().hex
        self._assets = {}
        self.requests = []
        self._lock = threading.Lock()
        if not self.root.is_dir():
            raise HostError("앱 화면 자산을 찾을 수 없습니다. 설치 파일을 다시 확인해 주세요.")
        for path in self.root.rglob("*"):
            if path.is_file():
                resolved = path.resolve()
                if not resolved.is_relative_to(self.root) or path.is_symlink():
                    raise HostError("앱 화면 자산 경계 검증에 실패했습니다.")
                relative = path.relative_to(self.root).as_posix()
                content_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
                self._assets[f"/{self._nonce}/{relative}"] = (resolved.read_bytes(), content_type)
        if f"/{self._nonce}/index.html" not in self._assets:
            raise HostError("앱 시작 화면을 찾을 수 없습니다.")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LocalReviewUI"

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
        return {path[len(prefix):]: hashlib.sha256(data).hexdigest()
                for path, (data, _) in self._assets.items()}

    def close(self):
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(3)


def bind_public_api(window, bridge):
    """Expose only the flat nine-function whitelist; no object fallback exists."""
    if window._js_api is not None:
        raise HostError("앱 연결 경계 검증에 실패했습니다.")
    methods = tuple(getattr(bridge, name) for name in PUBLIC_METHODS)
    if any(not callable(method) for method in methods):
        raise HostError("앱 연결 함수를 확인할 수 없습니다.")
    window.expose(*methods)
    if set(window._functions) != set(PUBLIC_METHODS):
        raise HostError("앱 공개 함수 검증에 실패했습니다.")


def _allow_native_message(server, source, raw):
    """Gate the real native dispatcher, including its framework-only builtins.

    js_api=None eliminates the bridge object's private paths. This additional
    gate also removes getattr(None, ...) and pywebview's implicit native commands.
    A malformed native packet is not a public API invocation and is discarded.
    """
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
    """Install native cancellation before EdgeChrome's first navigation."""
    def __init__(self, window, server):
        self.window = window
        self.server = server
        self.events = []
        self.failure = None
        self.version = None
        self._handlers = []
        self._lock = threading.Lock()

    def _record(self, event, **values):
        with self._lock:
            self.events.append({"event": event, **values})

    def _fail(self):
        self.failure = "WebView2 화면 보안 경계를 초기화하지 못했습니다. " + INITIALIZATION_MESSAGE
        self._record("guard_failure")
        self.window.native.Close()

    def before_show(self):
        try:
            import webview.platforms.winforms as winforms
            browser = self.window.native.browser
            if winforms.renderer != "edgechromium" or type(browser).__name__ != "EdgeChrome":
                self._fail()
                return
            control = browser.webview
            self._record("before_show", core_already_ready=control.CoreWebView2 is not None)
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

            # EdgeChrome subscribes this in __init__, before before_show. Merely
            # replacing its Python attribute would leave the old native delegate.
            control.WebMessageReceived -= original_notify
            browser.on_script_notify = message
            control.WebMessageReceived += message
            self._record("ipc_whitelist_installed", before_first_load=True)
            control.CreationProperties.AdditionalBrowserArguments += (
                " --disable-background-networking --disable-component-update --no-proxy-server"
                " --host-resolver-rules=\"MAP *.invalid ~NOTFOUND\"")

            def navigation(sender, args):
                if not self.server.allowed(str(args.Uri)):
                    args.Cancel = True
                    self._record("navigation_denied", uri=str(args.Uri), cancelled=bool(args.Cancel))

            def new_window(sender, args):
                args.Handled = True
                self._record("new_window_denied", uri=str(args.Uri), handled=bool(args.Handled))

            def resource(sender, args):
                if self.server.allowed(str(args.Request.Uri)):
                    self._record("resource_allowed", uri=str(args.Request.Uri))
                    return
                try:
                    from System import Array, Byte
                    from System.IO import MemoryStream
                    content = MemoryStream(Array[Byte](b"Remote resource denied"))
                    args.Response = sender.Environment.CreateWebResourceResponse(
                        content, 403, "Forbidden", "Content-Type: text/plain\r\nCache-Control: no-store\r\n")
                    self._record("resource_denied", uri=str(args.Request.Uri),
                                 status=int(args.Response.StatusCode), context=str(args.ResourceContext))
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
                    self._record("guards_installed", before_first_load=True)
                    original_ready(sender, args)
                except Exception:
                    self._fail()

            self._handlers.extend((navigation, new_window, resource, ready, original_ready, message, original_notify))
            control.CoreWebView2InitializationCompleted += ready
        except Exception:
            self._fail()


def _select_native_path(window, purpose):
    import webview
    if purpose == "input_excel":
        result = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                          file_types=("Excel files (*.xlsx)",))
    elif purpose == "output_excel":
        result = window.create_file_dialog(webview.FileDialog.SAVE, save_filename="v15_검토결과.xlsx",
                                          file_types=("Excel files (*.xlsx)",))
    elif purpose == "output_directory":
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
    else:
        return None
    return result[0] if isinstance(result, (tuple, list)) and result else result or None


class _FakeBackend:
    def __init__(self):
        self.values = {}
        self.calls = []

    def get(self, provider):
        self.calls.append(("get", provider))
        return self.values.get(provider)

    def set(self, provider, key):
        self.calls.append(("set", provider))
        self.values[provider] = key

    def delete(self, provider):
        self.calls.append(("delete", provider))
        self.values.pop(provider, None)


class _FakeClient:
    """Synthetic negative screening, with actual domain/batch/writer execution."""
    def __init__(self, options, key, calls):
        self.provider, self.model = options.provider, options.model
        self._calls = calls

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        request = json.loads(user_prompt)
        phase = request.get("phase") or request.get("stage")
        self._calls.append(phase)
        if phase == "facts":
            return {"facts": []}
        if phase == "screen":
            return {"decisions": [{"clause_id": item["clause_id"], "candidate": False,
                                   "reason": "합성 자체검사 전용 비관련 분야"}
                                  for item in request["clauses"]]}
        if phase == "candidate":
            return {"is_candidate": False, "reason": "합성 자체검사 전용 후보제외", "uncertainty": ""}
        raise ValueError("Unexpected synthetic model stage")


def _check(condition, label):
    if not condition:
        raise HostError(label)


def _selfcheck_script():
    """Exercise actual async API/DTOs from the loaded local UI document."""
    return r"""
window.__v15check = null;
(async () => {
 const out={calls:[],invalid:[]}, api=window.pywebview.api;
 const assert=(value,label)=>{if(!value)throw new Error(label);};
 const call=async(name,...args)=>{out.calls.push(name);const r=await api[name](...args);
   assert(r && r.ok===true && r.error===null,name+' success envelope');return r.data;};
 const poll=async id=>{let last=0;for(let i=0;i<1200;i++){
   const data=await call('get_job',id,last);
   assert(data.job_id===id,'job identity');for(const e of data.events){assert(e.sequence>last,'event order');last=e.sequence;}
   if(['done','failed','cancelled'].includes(data.state))return data;
   assert(data.result===null,'result hidden until terminal');await new Promise(r=>setTimeout(r,35));}
   throw new Error('job timeout');};
 out.api=Object.keys(api).sort();out.location=location.href;
 out.initial=await call('get_initial_state');
 assert(document.getElementById('task-name') && document.querySelector('.brand'),'real UI document');
 const opts={};for(const key of ['method','provider','model','num_reviewers','selection_mode','selected_items',
   'weights','ministry_policy','local_base_url','guideline_id','catalogue_fingerprint','comparison_rules_version'])opts[key]=out.initial.defaults[key];
 opts.num_reviewers=1;opts.catalogue_fingerprint=out.initial.catalogue.fingerprint;
 out.cancelledPath=await call('select_path','output_directory');
 out.directory=await call('select_path','output_directory');
 out.input=await call('select_path','input_excel');out.output=await call('select_path','output_excel');
 const syntheticKey='synthetic-self-check-credential';
 out.saved=await call('save_key','claude',syntheticKey);
 const task={'과제명':'합성 자체검사 단건','세부사업명':'합성','연구목표':'합성 검사',
   '연구내용':'실제 연구정보가 없는 합성 검사','기대효과':'합성 확인','현재 기술사양':'',
   '개발목표 사양':'','추가 검토정보':'','부처 세부기준':''};
 out.singleStarted=await call('start_single',{task,options:opts,output_dir_token:null});
 out.single=await poll(out.singleStarted.job_id);
 assert(out.single.state==='done' && out.single.result.schema_version===2,'single DTO root');
 out.exportStarted=await call('start_export',{job_id:out.single.job_id,
   task_fingerprint:out.single.result.task_fingerprint,output_dir_token:out.directory.path_token});
 out.exported=await poll(out.exportStarted.job_id);
 assert(out.exported.result.schema_version===2 && out.exported.result.task_fingerprint===out.single.result.task_fingerprint,'export same DTO');
 out.batchStarted=await call('start_batch',{input_token:out.input.path_token,output_token:out.output.path_token,
   output_dir_token:out.directory.path_token,options:opts,workers:2,resume:false,make_forms:false});
 out.batch=await poll(out.batchStarted.job_id);
 assert(out.batch.state==='done' && out.batch.result.results.length===2,'two synthetic batch rows');
 const cancelStarted=await call('start_single',{task:{...task,'과제명':'합성 취소 요청'},options:opts,output_dir_token:null});
 out.cancel=await call('cancel_job',cancelStarted.job_id);out.cancelled=await poll(cancelStarted.job_id);
 for(const name of Object.keys(api)){
   const response=await api[name]({unexpected:'synthetic-invalid-argument'},[],null,{},false);
   assert(response && response.ok===false && response.data===null &&
     Object.keys(response.error).sort().join(',')==='code,message','safe arity '+name);
   out.invalid.push({name,response});
 }
 assert(!JSON.stringify(out).includes(syntheticKey),'credential never returned');
 // Attack the actual WebView2 message dispatcher, bypassing generated API names.
 window.__v15attackReady=true;
 while(!window.__v15attackGo)await new Promise(r=>setTimeout(r,25));
 out.privateReplies=0;
 for(const [name,args] of [['_keys.resolve',['claude']],['_keys._backend.get',['claude']],
   ['_paths.clear',[]],['_jobs.clear',[]],['_get_catalogue',[]],
   ['_path',[out.directory.path_token,'output_directory']],['_path_selector',['output_directory']],['_catalogue_loader',[]],
   ['__str__',[]],['__class__.__base__.__subclasses__',[]],['_pywebviewAlert',['synthetic forbidden alert']],
   ['console',['synthetic forbidden console']],['pywebviewStateUpdate',{key:'v15Forbidden',value:'synthetic'}],
   ['pywebviewMoveWindow',[42,42]]]){
   window.pywebview._returnValuesCallbacks[name]={};
   window.pywebview._returnValuesCallbacks[name]['v15-private']=()=>{out.privateReplies++;};
   window.chrome.webview.postMessage([name,JSON.stringify(args),'v15-private']);
 }
 await new Promise(r=>setTimeout(r,250));
 out.builtinStateAbsent=window.pywebview.state.v15Forbidden===undefined;
 window.__v15attackDone=true;
 while(!window.__v15attackChecked)await new Promise(r=>setTimeout(r,25));
 out.deleted=await call('delete_key','claude');out.initialAfter=await call('get_initial_state');
 // Exercise the shipped app.js handlers too, including actual rendered DTOs.
 const el=id=>document.getElementById(id);
 const until=async(test,label)=>{for(let i=0;i<1200;i++){
   if(test())return;await new Promise(r=>setTimeout(r,25));}throw new Error(label);};
 await until(()=>document.body.dataset.ready==='true','UI initialization');
 el('provider').value='claude';el('provider').dispatchEvent(new Event('change'));
 el('api-key').value='synthetic-ui-only-credential';el('save-key').click();
 await until(()=>el('key-status').textContent.includes('API 키 저장됨'),'UI key save');
 assert(el('api-key').value==='','UI key input cleared');
 el('task-name').value='합성 UI 클릭 단건';el('task-content').value='실제 연구정보가 아닌 합성 UI 검사';
 el('reviewer-count').value='1';el('start-single').click();
 await until(()=>el('result-heading').textContent==='합성 UI 클릭 단건' && !el('start-single').disabled,'UI single result');
 out.dom={ready:true,keyInputCleared:true,singleStatus:el('result-status').textContent};
 el('start-export').click();
 await until(()=>!el('start-export').disabled && el('job-events').textContent.includes('단건 의견서를 저장'),'UI export');
 out.dom.exportRendered=el('result-content').textContent.includes('완료');
 el('batch-input').click();await until(()=>el('batch-input-name').textContent.includes('synthetic-input'),'UI input picker');
 el('batch-output').click();await until(()=>el('batch-output-name').textContent.includes('synthetic-output'),'UI output picker');
 el('batch-resume').checked=false;el('batch-forms').checked=false;el('start-batch').click();
 await until(()=>el('result-picker').options.length===3 && !el('start-batch').disabled,'UI batch result');
 out.dom.resultRecords=el('result-picker').options.length;
 document.querySelector('[data-result-tab="evidence"]').click();
 out.dom.evidenceRendered=el('result-content').textContent.includes('고시') && el('result-content').textContent.includes('전략물자');
 el('delete-key').click();await until(()=>el('key-status').textContent==='API 키 저장되지 않음','UI key delete');
 out.dom.keyDeleted=true;
 assert(!document.body.textContent.includes('synthetic-ui-only-credential'),'UI credential absent from markup');
 out.finalUrl=location.href;out.assetUrls=performance.getEntriesByType('resource').map(x=>x.name);
 window.__v15check=out;
})().catch(error=>{window.__v15check={failure:String(error)};});true;
"""


def _native_boundary_cases(window, boundary, server):
    """Observe each actual blocking layer without weakening the document CSP."""
    remote = "https://example.invalid/v15-self-check"
    window.evaluate_js(r"""window.__v15csp={violations:[]};
      document.addEventListener('securitypolicyviolation',event=>{
        window.__v15csp.violations.push({blockedURI:event.blockedURI,directive:event.effectiveDirective});});
      fetch('https://example.invalid/v15-csp-fetch').then(()=>{window.__v15csp.fetchBlocked=false;})
        .catch(()=>{window.__v15csp.fetchBlocked=true;});
      const cspImage=new Image();cspImage.onload=()=>{window.__v15csp.imageBlocked=false;};
      cspImage.onerror=()=>{window.__v15csp.imageBlocked=true;};
      cspImage.src='https://example.invalid/v15-csp-image.png';document.body.append(cspImage);true;""")
    time.sleep(.3)
    csp = window.evaluate_js("window.__v15csp")
    _check(csp.get("fetchBlocked") is True and csp.get("imageBlocked") is True, "UI CSP failed to block remote resources")
    _check(any(item["directive"] == "connect-src" and item["blockedURI"] == "https://example.invalid/v15-csp-fetch"
               for item in csp["violations"]), "CSP connect-src rejection was not observed")
    _check(any(item["directive"] == "img-src" and item["blockedURI"] == "https://example.invalid/v15-csp-image.png"
               for item in csp["violations"]), "CSP img-src rejection was not observed")
    window.evaluate_js(r"""window.__v15remote=null;(async()=>{
      window.open('https://example.invalid/v15-self-check-new','_blank');
      await new Promise(r=>setTimeout(r,150));
      location.href='https://example.invalid/v15-self-check-navigation';
      await new Promise(r=>setTimeout(r,150));
      window.__v15remote={finalUrl:location.href};
    })().catch(()=>{window.__v15remote={failure:true};});true;""")
    deadline = time.monotonic() + 8
    result = None
    while time.monotonic() < deadline and result is None:
        result = window.evaluate_js("window.__v15remote")
        if result is None:
            time.sleep(.05)
    _check(isinstance(result, dict) and result.get("finalUrl") == server.url, "Remote navigation changed the local UI")
    names = [event["event"] for event in boundary.events]
    _check("navigation_denied" in names, "Native remote navigation was not observed")
    _check("new_window_denied" in names, "Native new-window denial was not observed")
    _check("resource_denied" in names, "Native remote resource denial was not observed")
    denied = [event for event in boundary.events if event["event"] == "resource_denied"]
    _check(any(event["uri"] == remote + "-navigation" and event["status"] == 403
               and event.get("context") == "Document" for event in denied), "Native remote document 403 missing")
    _check(window.evaluate_js("location.href") == server.url, "UI origin changed")
    return {"document_csp": csp, "native_resource_403_contexts": sorted({event.get("context") for event in denied}),
            "native_navigation_cancelled": True, "native_new_window_handled": True,
            "csp_unchanged": True,
            "scope_note": "Fetch/image rejected by document CSP; native 403 observed for remote Document. No native fetch/image 403 claim."}


def _verify_static_server(server):
    import http.client
    cases = [("/security_grade_classifier_v15.py", {}, 404),
             (f"/{server._nonce}/../desktop_bridge_v15.py", {}, 404),
             (f"/{server._nonce}/%2e%2e/credential_store.py", {}, 404),
             ("/", {}, 404), (urlsplit(server.url).path, {"Host": "example.invalid"}, 403),
             (urlsplit(server.url).path, {"Origin": "https://example.invalid"}, 403)]
    results = []
    for path, headers, expected in cases:
        conn = http.client.HTTPConnection(server.authority, timeout=3)
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            response.read()
            _check(response.status == expected, "Static server boundary failure")
            results.append({"path": path, "status": response.status})
        finally:
            conn.close()
    conn = http.client.HTTPConnection(server.authority, timeout=3)
    try:
        conn.request("POST", urlsplit(server.url).path, body=b"synthetic")
        response = conn.getresponse()
        response.read()
        _check(response.status == 405, "HTTP API route was accepted")
    finally:
        conn.close()
    return results


def _cleanup_directory(directory):
    """Remove only this run's explicitly created absolute temporary directory."""
    directory = Path(directory).resolve()
    if directory.parent != Path(tempfile.gettempdir()).resolve() or not directory.name.startswith("v15-self-"):
        raise HostError("Own temporary directory boundary check failed")
    for attempt in range(30):
        try:
            if directory.exists():
                shutil.rmtree(directory)
            return not directory.exists()
        except OSError:
            time.sleep(.1)
    return False


def _selfcheck_sdks():
    """Exercise the real delayed SDK imports without creating an API client."""
    result = {}
    for package, client_class, expected in (
        ("openai", "OpenAI", "2.47.0"), ("anthropic", "Anthropic", "1.3.0")
    ):
        module = importlib.import_module(package)
        client = getattr(module, client_class)
        version = importlib.metadata.version(package)
        _check(version == expected and isinstance(client, type), "Packaged model SDK check failed")
        result[package] = {"version": version, "client_class": client.__name__}
    return result


def run_app(*, self_check_path=None):
    """One runtime entry path for source and frozen execution."""
    checking = self_check_path is not None
    report = {"pass": False, "frozen": bool(getattr(sys, "frozen", False)), "failures": [],
              "scope": "own hidden WebView2, fake credentials/model, synthetic tasks" if checking else "application"}
    server = None
    temporary = None
    window = None
    boundary = None
    finished = threading.Event()
    blocker = _NoLegacyRenderer()
    sys.meta_path.insert(0, blocker)
    backend = None
    calls = []
    probes = {"catalogue_loads": 0, "path_selections": 0, "client_creations": 0, "exports": []}
    try:
        report["available_runtime"] = require_webview2()
        import webview
        from desktop_bridge_v15 import DesktopBridge
        from credential_store import KeyManager
        from notice_catalogue_v15 import load_catalogue
        from v15_domain import canonical_hash, validate_result

        report["pywebview_version"] = importlib.metadata.version("pywebview")
        _check(report["pywebview_version"] == "6.2.1", INITIALIZATION_MESSAGE)
        webview.settings.update(ALLOW_FILE_URLS=False, ALLOW_DOWNLOADS=False,
                                OPEN_EXTERNAL_LINKS_IN_BROWSER=False, IGNORE_SSL_ERRORS=False,
                                REMOTE_DEBUGGING_PORT=None)
        server = LocalAssetServer().start()
        temporary = Path(tempfile.mkdtemp(prefix="v15-self-"))
        profile = temporary / "profile"
        profile.mkdir()
        if checking:
            report["sdk_imports"] = _selfcheck_sdks()
            from openpyxl import Workbook
            backend = _FakeBackend()
            key_manager = KeyManager(backend=backend, environ={})
            catalogue = load_catalogue()
            report["catalogue"] = {"catalogue_id": catalogue.manifest["catalogue_id"],
                "fingerprint": catalogue.fingerprint, "manifest_hash": canonical_hash(catalogue.to_dict()["manifest"]),
                "clause_count": len(catalogue.clauses)}
            report["asset_sha256"] = server.hashes()
            report["server_scope_cases"] = _verify_static_server(server)
            input_path = temporary / "synthetic-input.xlsx"
            output_path = temporary / "synthetic-output.xlsx"
            document_path = temporary / "documents"
            document_path.mkdir()
            book = Workbook()
            book.active.title = "분류대상"
            book.active.append(["과제명", "연구내용"])
            book.active.append(["합성 자체검사 배치 A", "실제 연구정보가 아닌 합성 A"])
            book.active.append(["합성 자체검사 배치 B", "실제 연구정보가 아닌 합성 B"])
            book.save(input_path)
            book.close()
            selected = {"output_directory": [None, document_path, document_path],
                        "input_excel": [input_path, input_path], "output_excel": [output_path, output_path]}

            def selector(purpose):
                probes["path_selections"] += 1
                values = selected.get(purpose, [])
                return values.pop(0) if values else None

            def catalogue_loader():
                probes["catalogue_loads"] += 1
                return catalogue

            def client_factory(opts, key):
                probes["client_creations"] += 1
                return _FakeClient(opts, key, calls)

            def regenerator(saved, directory):
                from batch_v15 import regenerate_documents
                before = (len(calls), probes["client_creations"], probes["catalogue_loads"])
                result = regenerate_documents(saved, directory)
                after = (len(calls), probes["client_creations"], probes["catalogue_loads"])
                probes["exports"].append({"model_calls": after[0] - before[0],
                    "client_creations": after[1] - before[1], "catalogue_loads": after[2] - before[2]})
                return result

            bridge = DesktopBridge(key_manager=key_manager, catalogue_loader=catalogue_loader,
                client_factory=client_factory, path_selector=selector, regenerator=regenerator)
        else:
            bridge = DesktopBridge()
        window = webview.create_window(TITLE, url=server.url, js_api=None,
            hidden=checking, focus=not checking, width=1366, height=900, min_size=(760, 560),
            text_select=True, zoomable=False, background_color="#F4F5F3")
        bind_public_api(window, bridge)
        if not checking:
            bridge._path_selector = lambda purpose: _select_native_path(window, purpose)
        boundary = NativeBoundary(window, server)
        window.events.before_show += boundary.before_show

        def cases():
            try:
                _check(window.events.loaded.wait(25), "Local UI/bridge did not load")
                _check(boundary.failure is None and boundary.version, "Native WebView2 guard startup failed")
                _check(window._js_api is None and set(window._functions) == set(PUBLIC_METHODS), "Unsafe exposed API")
                window.evaluate_js(_selfcheck_script())
                deadline = time.monotonic() + 130
                result = None
                private_before = None
                private_checked = False

                def private_spies():
                    return {"backend_operations": len(backend.calls), "model_calls": len(calls),
                        "catalogue_loads": probes["catalogue_loads"], "path_selections": probes["path_selections"],
                        "path_tokens": sorted(bridge._paths), "job_ids": sorted(bridge._jobs)}

                while time.monotonic() < deadline and result is None:
                    status = window.evaluate_js("({result:window.__v15check,ready:window.__v15attackReady===true,done:window.__v15attackDone===true})")
                    result = status.get("result")
                    if status.get("ready") and private_before is None:
                        _check(bool(backend.values), "Synthetic private attack marker not present")
                        private_before = private_spies()
                        window.evaluate_js("window.__v15attackGo=true;true")
                    if status.get("done") and not private_checked:
                        private_after = private_spies()
                        _check(private_before == private_after, "Private dispatcher touched internal state")
                        report["private_dispatch_spies"] = {"before": private_before, "after": private_after,
                                                            "unchanged": True}
                        private_checked = True
                        window.evaluate_js("window.__v15attackChecked=true;true")
                    if result is None:
                        time.sleep(.08)
                report["javascript"] = result
                _check(isinstance(result, dict) and "failure" not in result, "Actual async bridge flow failed")
                _check(result["api"] == sorted(PUBLIC_METHODS), "Renderer API list differs")
                _check(set(result["calls"]) == set(PUBLIC_METHODS), "Not all nine APIs were called")
                _check(result["privateReplies"] == 0, "Private dispatcher path returned")
                _check(result["builtinStateAbsent"] is True, "Implicit native state command ran")
                _check(sum(event["event"] == "ipc_denied" for event in boundary.events) >= 14,
                       "Native whitelist did not reject all private and implicit commands")
                _check(result["cancelledPath"] == {"cancelled": True, "path_token": None, "display_name": None}, "Picker cancellation contract")
                _check(result["initial"]["catalogue"]["fingerprint"] == catalogue.fingerprint, "Catalogue metadata fingerprint")
                _check(result["initial"]["catalogue"]["sources"] == catalogue.to_dict()["manifest"]["sources"], "Catalogue sources metadata")
                for dto in [result["single"]["result"], result["exported"]["result"], *result["batch"]["result"]["results"]]:
                    validate_result(dto)
                _check(result["exported"]["result"]["documents"]["status"] == "완료", "Document export failed")
                _check(all(Path(item["path"]).is_file() for item in result["exported"]["result"]["documents"]["files"]), "Exported document missing")
                _check(output_path.is_file(), "Batch workbook missing")
                _check(probes["exports"] and all(all(value == 0 for value in entry.values())
                    for entry in probes["exports"]), "Export invoked model or latest catalogue")
                _check(backend.values == {}, "Synthetic credential deletion failed")
                _check(all(server.allowed(url) or (url == server.origin + "/favicon.ico" and any(
                    event["event"] == "resource_denied" and event.get("uri") == url
                    for event in boundary.events)) for url in result["assetUrls"]), "Remote UI asset found")
                _check(result["dom"]["resultRecords"] == 3 and result["dom"]["exportRendered"]
                    and result["dom"]["evidenceRendered"] and result["dom"]["keyDeleted"], "Actual UI interaction flow failed")
                report["boundary_checks"] = _native_boundary_cases(window, boundary, server)
                report["pass"] = True
            except Exception as error:
                report["failures"].append(str(error) if isinstance(error, HostError) else "Synthetic runtime check failed")
            finally:
                if window is not None:
                    window.destroy()

        def watchdog():
            if finished.wait(175):
                return
            report["failures"].append("Hidden runtime watchdog timed out")
            report["pass"] = False
            try:
                window.destroy()
            except Exception:
                pass

        if checking:
            threading.Thread(target=watchdog, daemon=True).start()
        webview.start(cases if checking else None, gui="edgechromium", debug=False,
                      private_mode=True, storage_path=str(profile), http_server=False)
        if boundary.failure:
            raise HostError(boundary.failure)
    except Exception as error:
        report["failures"].append(str(error) if isinstance(error, HostError) else INITIALIZATION_MESSAGE)
        report["pass"] = False
        if not checking:
            ctypes.windll.user32.MessageBoxW(None, report["failures"][-1], TITLE, 0x10)
    finally:
        if boundary:
            report["native_events"] = boundary.events
            report["runtime_version"] = boundary.version
        if checking:
            report["fake_model_phases"] = calls
            report["synthetic_probes"] = probes
            report["fake_credential_operations"] = backend.calls if backend else []
        if server:
            server.close()
            report["server_closed"] = not server._thread.is_alive()
            report["http_requests"] = server.requests
        report["profile_cleaned"] = _cleanup_directory(temporary) if temporary else True
        if not report["profile_cleaned"]:
            report["pass"] = False
            report["failures"].append("Own temporary profile cleanup failed")
        if blocker in sys.meta_path:
            sys.meta_path.remove(blocker)
        finished.set()
        if checking:
            target = Path(self_check_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    return 0 if report["pass"] or (not checking and not report["failures"]) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--self-check", metavar="REPORT_JSON", help="합성 자료로 숨긴 WebView2 자체검사")
    args = parser.parse_args(argv)
    return run_app(self_check_path=args.self_check)


if __name__ == "__main__":
    raise SystemExit(main())
