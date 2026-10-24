# -*- coding: utf-8 -*-
"""GUI 백엔드 — pywebview + 로컬 전용 HTTP 서버.

이 저장소의 다른 KISTEP 도구들(예: 제재통계 프로그램)과 동일한 패턴을 따른다:
  · ThreadingHTTPServer 를 127.0.0.1 임의 포트에 띄우고 ui/index.html(정적)을 서빙
  · 프론트엔드 JS 는 /api/* 엔드포인트를 fetch 로 호출
  · 장시간 작업(리포트 생성)은 백그라운드 스레드에서 실행하고, 프론트는 /api/state 를
    주기적으로 폴링해 진행 상황(로그·완료 여부)을 갱신한다 — pywebview js_api 브리지를
    쓰지 않는다.
  · pywebview 가 없으면 기본 브라우저로 같은 화면을 연다(오프라인 사내 PC 대응).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__, history, pipeline
from .config import DEFAULT_CONFIG, load_config, save_config
from .config import _deep_merge  # noqa: F401 -- 내부 병합 로직 재사용
from .profiles import PROFILES
from .utils import CallbackHandler, app_dir, resolve_period, resource_dir, setup_logger

APP_TITLE = "연구보안·연구윤리 리포트 모니터링"
# RESOURCE_DIR(읽기 전용: ui/*, prompts/* 등 번들 리소스) 와
# APP_DIR(쓰기 가능: config.json/output/logs/history 등) 를 분리한다 — onefile exe 는
# 실행마다 임시 폴더에 풀리므로, 쓰기 가능한 데이터는 반드시 exe 옆(APP_DIR)에 남겨야 한다.
RESOURCE_DIR = resource_dir()
APP_DIR = app_dir()
UI_FILE = RESOURCE_DIR / "ui" / "index.html"
CONFIG_PATH = APP_DIR / "config.json"

WINDOW = None  # pywebview 창 핸들(있을 때만)
DIALOG_Q: "queue.Queue[tuple[str, dict, queue.Queue]]" = queue.Queue()


# ---------------------------------------------------------------------------
# 상태
# ---------------------------------------------------------------------------
class Job:
    """실행 1회의 진행 상태. GUI 는 이걸 폴링해서 로그·완료 여부를 표시한다."""

    def __init__(self) -> None:
        self.busy = False
        self.error: Optional[str] = None
        self.logs: list[str] = []
        self.results: list[dict] = []

    def log(self, line: str) -> None:
        self.logs.append(line)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def snapshot(self) -> Dict[str, Any]:
        return {"busy": self.busy, "error": self.error,
                "results": self.results, "logs": self.logs[-300:]}


CFG: Dict[str, Any] = load_config(CONFIG_PATH)
JOB = Job()

logger = setup_logger(APP_DIR / CFG.get("log_dir", "logs"))
logger.addHandler(CallbackHandler(JOB.log))


def default_outdir() -> Path:
    home = Path.home()
    for name in ("Documents", "문서"):
        if (home / name).is_dir():
            return home / name / "연구보안연구윤리_리포트"
    return home / "연구보안연구윤리_리포트"


def _do_run(report_keys: list[str], period_mode: str, override: Optional[str],
           write_excel: bool) -> None:
    JOB.busy = True
    JOB.error = None
    JOB.results = []
    try:
        period = resolve_period(period_mode, override)
        JOB.log(f"실행 시작 — {period.mode_label} / {period.period_label} "
                f"({period.start_iso} ~ {period.end_iso})")
        results = pipeline.run_all(report_keys, period, CFG, APP_DIR, RESOURCE_DIR,
                                   write_excel=write_excel, logger=logger)
        JOB.results = results
        failed = [r for r in results if r.get("error")]
        JOB.log(f"실행 완료 — 성공 {len(results) - len(failed)}건 / 실패 {len(failed)}건")
    except Exception as exc:  # noqa: BLE001
        JOB.error = str(exc)
        JOB.log(f"실행 실패: {exc}")
        logger.exception("GUI 실행 중 오류")
    finally:
        JOB.busy = False


def open_file(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ---------------------------------------------------------------------------
# 파일/폴더 선택 (네이티브 창이 있을 때는 즉시, 없을 때는 메인 스레드 tk 로 위임)
# ---------------------------------------------------------------------------
def _pick(kind: str, **opts) -> Optional[str]:
    if WINDOW is not None:
        try:
            import webview
            if kind == "folder":
                got = WINDOW.create_file_dialog(webview.FOLDER_DIALOG)
            elif kind == "save":
                got = WINDOW.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=opts.get("filename", "저장.xlsx"),
                    directory=opts.get("directory", str(default_outdir())))
            else:
                got = WINDOW.create_file_dialog(
                    webview.OPEN_DIALOG, file_types=opts.get("file_types", ("모든 파일 (*.*)",)))
            return got[0] if got else None
        except Exception:  # noqa: BLE001
            return None
    reply: "queue.Queue[str | None]" = queue.Queue(maxsize=1)
    DIALOG_Q.put((kind, opts, reply))
    try:
        return reply.get(timeout=300)
    except queue.Empty:
        return None


def _pump_dialogs() -> None:
    """pywebview 없이 브라우저로 열었을 때, 메인 스레드에서 tkinter 파일창을 대신 띄운다."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        tk = None  # type: ignore[assignment]
    while True:
        kind, opts, reply = DIALOG_Q.get()
        if kind == "stop":
            return
        if tk is None:
            reply.put(None)
            continue
        try:
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            if kind == "folder":
                p = filedialog.askdirectory(title="폴더 선택")
            elif kind == "save":
                p = filedialog.asksaveasfilename(
                    title="저장 위치 선택", initialfile=opts.get("filename", "저장.xlsx"),
                    defaultextension=".xlsx")
            else:
                p = filedialog.askopenfilename(title="파일 선택")
            r.destroy()
            reply.put(p or None)
        except Exception:  # noqa: BLE001
            reply.put(None)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = f"RMonitorUI/{__version__}"

    def log_message(self, *a):  # noqa: A002 - BaseHTTPRequestHandler 표준 시그니처
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    # -- GET ----------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)

        if path in ("/", "/index.html"):
            try:
                self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, b"ui/index.html not found", "text/plain; charset=utf-8")
            return

        if path == "/api/config":
            self._json({"config": CFG, "version": __version__})
            return

        if path == "/api/profiles":
            self._json({"profiles": [
                {"key": p.key, "name": p.name, "titleKr": p.title_kr,
                 "enabled": CFG.get("reports", {}).get(p.key, {}).get("enabled", True)}
                for p in PROFILES.values()
            ]})
            return

        if path == "/api/period-preview":
            mode = (query.get("mode") or ["monthly"])[0]
            override = (query.get("override") or [None])[0] or None
            try:
                period = resolve_period(mode, override)
                self._json({
                    "start": period.start_iso, "end": period.end_iso,
                    "startKr": period.start_kr, "endKr": period.end_kr,
                    "label": period.period_label, "modeLabel": period.mode_label,
                    "tag": period.tag,
                })
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/state":
            self._json(JOB.snapshot())
            return

        if path == "/api/history":
            mode = (query.get("mode") or [None])[0] or None
            report_key = (query.get("report") or [None])[0] or None
            records = history.load_history(APP_DIR, CFG, mode=mode, report_key=report_key)
            self._json({"records": list(reversed(records))})
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")

    # -- POST -----------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"잘못된 요청입니다: {exc}"}, 400)
            return

        try:
            if path == "/api/config":
                global CFG
                posted = data.get("config") or {}
                CFG = _deep_merge(DEFAULT_CONFIG, posted)
                save_config(CFG, CONFIG_PATH)
                self._json({"config": CFG})
                return

            if path == "/api/run":
                if JOB.busy:
                    self._json({"error": "이미 실행 중입니다."}, 409)
                    return
                keys = data.get("reportKeys") or []
                if not keys:
                    self._json({"error": "실행할 리포트를 선택하세요."}, 400)
                    return
                mode = data.get("periodMode") or CFG.get("period", {}).get("mode", "monthly")
                override = data.get("override") or None
                write_excel = bool(data.get("writeExcel", True))
                threading.Thread(target=_do_run, args=(keys, mode, override, write_excel),
                                 daemon=True).start()
                self._json({"started": True})
                return

            if path == "/api/history/export":
                mode = data.get("mode") or None
                report_key = data.get("reportKey") or None
                out_path = data.get("outPath") or _pick(
                    "save", filename="이력보고서.xlsx", directory=str(default_outdir()))
                if not out_path:
                    self._json({"error": "저장 위치를 선택하지 않았습니다."}, 400)
                    return
                path_out = history.export_history_excel(APP_DIR, CFG, out_path,
                                                         mode=mode, report_key=report_key)
                self._json({"path": str(path_out)})
                return

            if path == "/api/save-html":
                src = Path(data.get("htmlPath") or "")
                if not src.exists():
                    self._json({"error": "원본 HTML 파일을 찾을 수 없습니다."}, 404)
                    return
                dest = data.get("outPath") or _pick(
                    "save", filename=src.name, directory=str(default_outdir()))
                if not dest:
                    self._json({"error": "저장 위치를 선택하지 않았습니다."}, 400)
                    return
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(src.read_bytes())
                self._json({"path": dest})
                return

            if path == "/api/open":
                open_file(data.get("path", ""))
                self._json({"ok": True})
                return

            if path == "/api/pick-path":
                kind = data.get("kind", "file")
                p = _pick(kind, filename=data.get("filename", ""))
                self._json({"path": p})
                return
        except Exception as exc:  # noqa: BLE001
            logger.exception("GUI API 오류: %s", path)
            self._json({"error": str(exc)}, 500)
            return

        self._json({"error": "알 수 없는 요청입니다."}, 404)


def free_port() -> int:
    s = socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    port = free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    try:
        import webview
    except ImportError:
        print(f"[{APP_TITLE} v{__version__}] pywebview 가 없어 기본 브라우저로 엽니다: {url}")
        print("  네이티브 창으로 쓰려면: pip install pywebview")
        import webbrowser
        webbrowser.open(url)
        try:
            _pump_dialogs()
        except KeyboardInterrupt:
            pass
        return 0

    global WINDOW
    WINDOW = webview.create_window(
        f"{APP_TITLE} v{__version__}", url, width=1280, height=860, min_size=(1000, 640),
        background_color="#0F1A24", text_select=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
