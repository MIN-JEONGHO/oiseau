# -*- coding: utf-8 -*-
"""
제재처분 집계 — 데스크톱 실행 진입점

  python app.py

pywebview 가 설치되어 있으면 네이티브 창으로 열리고, 없으면 기본 브라우저로
같은 화면을 엽니다. 화면은 로컬 HTTP 서버(127.0.0.1 임의 포트)에서만 제공되며
외부로 열리지 않습니다.

exe 빌드는 build_exe.bat / app.spec 참고.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from excel_writer import write_excel
from hwpx_writer import fill_hwpx
from sanction_pipeline import (
    JUDGMENT_ORDER,
    TOTAL_LABEL,
    PipelineConfig,
    aggregate,
    analyze_periods,
    check_reference_coverage,
    load_raw,
    load_reference,
    make_reference_template,
    preprocess,
    transform,
)

APP_TITLE = "제재처분 원인과제 집계"


# ---------------------------------------------------------------------------
# 리소스 경로 (PyInstaller onefile 대응)
# ---------------------------------------------------------------------------

def resource_path(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / rel


UI_FILE = resource_path("ui/index.html")
#: 부처별 예산 과제수 제재처분 집계 표준양식 — 바뀌지 않으므로 프로그램에 내장
TEMPLATE_FILE = resource_path("template.hwpx")
#: 조사·분석 참조데이터(국가R&D연구비/과제수) 기본값 — 화면에서 다른 파일로 교체 가능
REFERENCE_FILE = resource_path("reference.xlsx")


# ---------------------------------------------------------------------------
# 애플리케이션 상태
# ---------------------------------------------------------------------------

def default_outdir() -> Path:
    """업로드된 파일은 임시 폴더에 있으므로 결과는 문서 폴더에 모은다."""
    home = Path.home()
    for name in ("Documents", "문서"):
        if (home / name).is_dir():
            return home / name / "제재처분집계"
    return home / "제재처분집계"


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.result = None            # AggregateResult
        self.paths: dict = {"raw": None, "template": None, "ref": None, "outdir": None}
        self.names: dict = {"raw": None, "template": None, "ref": None}
        self.stage = ""
        self.pct = 0
        self.busy = False
        self.error: str | None = None
        self.notes: list[str] = []
        self.payload: dict | None = None
        self.exports: list[str] = []
        self.resolved: dict = {}

    def set(self, stage: str, pct: int) -> None:
        self.stage, self.pct = stage, pct

    def note(self, msg: str) -> None:
        if msg not in self.notes:
            self.notes.append(msg)


ST = State()
WINDOW = None  # pywebview window


# ---------------------------------------------------------------------------
# 파이프라인 실행
# ---------------------------------------------------------------------------

def _cfg_from(opts: dict) -> PipelineConfig:
    def _int(key, default=None):
        v = opts.get(key)
        if v in (None, "", "auto"):
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return PipelineConfig(
        sheet_name=opts.get("sheet") or "제재정보",
        header_row=_int("headerRow"),          # None -> 자동 탐지
        data_start_row=_int("dataStartRow"),
        min_task_year=_int("minTaskYear", 2017) or 2017,
        year_start=_int("yearStart"),
        year_end=_int("yearEnd"),
        year_end_cap=_int("yearEndCap"),
        id_strategy=opts.get("idStrategy") or "번호우선",
        ministry_column=opts.get("ministryColumn") or "소관부처",
        verbose=True,
    )


def _integrity(res, long_df) -> list[dict]:
    """양식 각주가 요구하는 정합성 4건을 서버에서 직접 검산."""
    checks = []

    ok = True
    for y in res.years:
        a = int(long_df[long_df["연도"] == y]["건수"].sum()) if len(long_df) else 0
        if a != res.subtotal(TOTAL_LABEL, y):
            ok = False
            break
    checks.append({"label": "연도별 소계 = 연도 전개 건수 합", "ok": ok})

    ok = all(
        sum(res.subtotal(m, k) for m in res.ministries) == res.subtotal(TOTAL_LABEL, k)
        for k in list(res.years) + ["합계"]
    )
    checks.append({"label": "부처별 합 = 합 계 행", "ok": ok})

    ok = True
    for m in res.ministries + [TOTAL_LABEL]:
        for k in list(res.years) + ["합계"]:
            if sum(res.count(m, c, k) for c in JUDGMENT_ORDER) != res.subtotal(m, k):
                ok = False
    checks.append({"label": "① + ② + ③ = 소계", "ok": ok})

    counted = res.tasks["_판정코드"].notna() & res.tasks["집계반영연도"].ne("")
    dedup = int(counted.sum())
    checks.append(
        {
            "label": "합 계 열 = 계속과제 1건 기준 과제 수*",
            "ok": dedup == res.subtotal(TOTAL_LABEL, "합계"),
        }
    )
    return checks


def _build_payload(res) -> dict:
    keys = list(res.years) + ["합계"]
    rows = {}
    for m in res.ministries + [TOTAL_LABEL]:
        rows[m] = {
            "fee": [_j(res.ref(m, "국가R&D연구비", k)) for k in keys],
            "cnt": [_j(res.ref(m, "국가R&D과제수", k)) for k in keys],
            "①": [res.count(m, "①", k) for k in keys],
            "②": [res.count(m, "②", k) for k in keys],
            "③": [res.count(m, "③", k) for k in keys],
            "sub": [res.subtotal(m, k) for k in keys],
            "ratio": [
                None if res.ratio(m, k) is None else round(res.ratio(m, k), 2)
                for k in keys
            ],
        }

    tasks = res.tasks
    excluded = int((tasks["_판정코드"].isna()).sum())
    long_df = res.long

    return {
        "years": [int(y) for y in res.years],
        "ministries": list(res.ministries),
        "totalLabel": TOTAL_LABEL,
        "rows": rows,
        "hasRef": bool(res.reference),
        "taskTotal": int(len(tasks)),
        "excluded": excluded,
        "counted": int(res.subtotal(TOTAL_LABEL, "합계")),
        "records": int(long_df["건수"].sum()) if len(long_df) else 0,
        "checks": _integrity(res, long_df),
        "notes": list(ST.notes),
        "resolved": {
            "headerRow": ST.resolved.get("header_row"),
            "idStrategy": ST.resolved.get("id_strategy"),
            "sheet": ST.resolved.get("sheet"),
            "ministryColumn": ST.resolved.get("ministry_column"),
            "renames": ST.resolved.get("ministry_renames") or {},
        },
        "outdir": str(default_outdir()),
    }


def _j(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f != f:  # NaN (참조데이터의 빈 셀)
        return None
    return int(f) if f == int(f) else round(f, 2)


def run_analysis(opts: dict) -> None:
    ST.busy, ST.error, ST.notes, ST.exports = True, None, [], []
    ST.payload, ST.result = None, None
    try:
        raw_path = ST.paths.get("raw")
        if not raw_path or not Path(raw_path).exists():
            raise FileNotFoundError("제재정보 rawdata 파일을 먼저 선택해 주세요.")

        cfg = _cfg_from(opts)
        # 파이프라인이 내는 경고('!'로 시작)만 화면 각주로 올린다
        cfg.log = lambda msg: (
            ST.note(msg.strip().lstrip("!").strip()) if "!" in msg else None
        )

        ST.set("rawdata 읽는 중", 8)
        raw = load_raw(raw_path, cfg)

        ST.set("컬럼 정리 · 연도 추출", 26)
        tr = transform(raw, cfg)

        ST.set("부처명 통일 · 결측 보완", 44)
        pp = preprocess(tr, cfg)

        ST.set("과제 단위 제재유형 판정", 62)
        tasks, years, mask = analyze_periods(pp, cfg)

        ST.set("부처 × 연도 집계", 80)
        res = aggregate(tasks, years, mask, cfg)

        # 참조데이터를 고르지 않았으면 내장본을 쓴다 (화면에서 교체 가능)
        ref_path = ST.paths.get("ref")
        if not ref_path and REFERENCE_FILE.exists():
            ref_path = str(REFERENCE_FILE)
            ST.note("참조데이터는 내장된 기본값을 사용했습니다.")
        if ref_path:
            ST.set("조사·분석 참조데이터 결합", 92)
            res.reference = load_reference(ref_path, years, cfg)
            check_reference_coverage(res, cfg)

        ST.set("검산", 97)
        ST.result = res
        ST.resolved = dict(cfg.resolved)
        ST.resolved["sheet"] = cfg.sheet_name
        ST.payload = _build_payload(res)
        ST.set("완료", 100)
    except Exception as e:  # noqa: BLE001
        ST.error = f"{e}"
        ST.set("중단", 0)
        traceback.print_exc()
    finally:
        ST.busy = False


def run_export(
    targets: list[str], outdir: str | None, include_long: bool = False
) -> list[str]:
    res = ST.result
    if res is None:
        raise RuntimeError("집계를 먼저 실행해 주세요.")

    base = Path(outdir) if outdir else default_outdir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    made: list[str] = []

    if "xlsx" in targets:
        p = base / f"제재처분집계_{stamp}.xlsx"
        write_excel(res, str(p), include_long=include_long)
        made.append(str(p))

    if "hwpx" in targets:
        tpl = ST.paths.get("template")
        if not tpl or not Path(tpl).exists():
            tpl = str(TEMPLATE_FILE) if TEMPLATE_FILE.exists() else None
        if not tpl:
            raise FileNotFoundError("한글 표준양식(.hwpx)을 찾을 수 없습니다.")
        p = base / f"제재처분집계_{stamp}.hwpx"
        fill_hwpx(tpl, str(p), res)
        made.append(str(p))

    if "reftpl" in targets:
        p = base / f"참조데이터_양식_{stamp}.xlsx"
        make_reference_template(str(p), res.ministries, res.years)
        made.append(str(p))

    ST.exports = made
    return made


# ---------------------------------------------------------------------------
# 파일 선택 / 탐색기
# ---------------------------------------------------------------------------

#: 파일 자체는 화면의 <input type="file"> 로 받는다. 네이티브 대화상자는
#: 폴더 선택에만 쓰고, 반드시 메인 스레드에서 띄운다.
DIALOG_Q: "queue.Queue[tuple[str, queue.Queue]]" = queue.Queue()


def pick_folder(timeout: float = 300.0) -> tuple[str | None, str | None]:
    """(경로, 오류메시지). 대화상자를 띄울 수 없으면 오류메시지를 돌려준다."""
    if WINDOW is not None:
        # pywebview 는 내부에서 GUI 스레드로 넘겨주므로 여기서 바로 호출해도 된다
        try:
            import webview

            got = WINDOW.create_file_dialog(webview.FOLDER_DIALOG)
            return (got[0] if got else None), None
        except Exception as e:  # noqa: BLE001
            return None, f"폴더 선택창을 열 수 없습니다: {e}"

    reply: "queue.Queue[str | None]" = queue.Queue(maxsize=1)
    DIALOG_Q.put(("folder", reply))
    try:
        return reply.get(timeout=timeout), None
    except queue.Empty:
        return None, "폴더 선택창이 응답하지 않습니다. 경로를 직접 입력해 주세요."


def _pump_dialogs() -> None:
    """브라우저 모드에서 메인 스레드가 호출. tkinter 대화상자를 순서대로 처리."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        tk = None  # type: ignore[assignment]

    while True:
        kind, reply = DIALOG_Q.get()
        if kind == "stop":
            return
        if tk is None:
            reply.put(None)
            continue
        try:
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            p = filedialog.askdirectory(title="결과를 저장할 폴더 선택")
            r.destroy()
            reply.put(p or None)
        except Exception:  # noqa: BLE001
            reply.put(None)


def reveal(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])


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
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "SanctionUI/1.0"

    def log_message(self, *a):  # 콘솔 조용히
        pass

    # -- helpers -----------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    # -- routes ------------------------------------------------------
    def do_GET(self):  # noqa: N802
        route = urlparse(self.path)
        path = route.path

        if path in ("/", "/index.html"):
            try:
                body = UI_FILE.read_bytes()
            except FileNotFoundError:
                self._send(500, b"ui/index.html not found", "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path == "/api/state":
            self._json(
                {
                    "busy": ST.busy,
                    "stage": ST.stage,
                    "pct": ST.pct,
                    "error": ST.error,
                    "paths": ST.paths,
                    "names": ST.names,
                    "payload": ST.payload,
                    "exports": ST.exports,
                    "defaultOutdir": str(default_outdir()),
                    "hasBundledTemplate": TEMPLATE_FILE.exists(),
                    "hasBundledRef": REFERENCE_FILE.exists(),
                }
            )
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"잘못된 요청입니다: {e}"}, 400)
            return

        try:
            if path == "/api/pick-folder":
                p, err = pick_folder()
                if err:
                    self._json({"error": err}, 500)
                    return
                if p:
                    ST.paths["outdir"] = p
                self._json({"path": ST.paths.get("outdir")})
                return

            if path == "/api/set-path":
                kind, val = data.get("kind"), data.get("path")
                if kind in ST.paths:
                    ST.paths[kind] = val or None
                    if kind in ST.names:
                        ST.names[kind] = Path(val).name if val else None
                self._json({"paths": ST.paths, "names": ST.names})
                return

            if path == "/api/upload":
                kind = data.get("kind", "raw")
                name = Path(data.get("name") or "input.xlsx").name
                blob = base64.b64decode((data.get("data") or "").split(",")[-1])
                tmp = Path(tempfile.gettempdir()) / "sanction_ui"
                tmp.mkdir(parents=True, exist_ok=True)
                dest = tmp / name
                dest.write_bytes(blob)
                ST.paths[kind] = str(dest)
                ST.names[kind] = name
                self._json({"path": str(dest), "name": name})
                return

            if path == "/api/analyze":
                if ST.busy:
                    self._json({"error": "이미 실행 중입니다."}, 409)
                    return
                opts = data.get("options") or {}
                threading.Thread(target=run_analysis, args=(opts,), daemon=True).start()
                self._json({"started": True})
                return

            if path == "/api/export":
                made = run_export(
                    data.get("targets") or ["xlsx"],
                    data.get("outdir"),
                    bool(data.get("includeLong")),
                )
                self._json({"files": made})
                return

            if path == "/api/reveal":
                reveal(data.get("path", ""))
                self._json({"ok": True})
                return

            if path == "/api/open":
                open_file(data.get("path", ""))
                self._json({"ok": True})
                return

            if path == "/api/quit":
                self._json({"ok": True})
                threading.Timer(0.3, _shutdown).start()
                return

        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": str(e)}, 500)
            return

        self._json({"error": "알 수 없는 요청입니다."}, 404)


def _shutdown() -> None:
    if WINDOW is not None:
        try:
            WINDOW.destroy()
            return
        except Exception:
            pass
    os._exit(0)


def free_port() -> int:
    s = socket.socket()
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
        print(f"[{APP_TITLE}] pywebview 가 없어 브라우저로 엽니다: {url}")
        print("  네이티브 창으로 쓰려면: pip install pywebview")
        import webbrowser

        webbrowser.open(url)
        try:
            _pump_dialogs()   # 메인 스레드에서 폴더 선택창을 처리
        except KeyboardInterrupt:
            pass
        return 0

    global WINDOW
    WINDOW = webview.create_window(
        APP_TITLE,
        url,
        width=1240,
        height=880,
        min_size=(940, 640),
        background_color="#10202B",
        text_select=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
