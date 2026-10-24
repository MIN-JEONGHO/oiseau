# -*- coding: utf-8 -*-
"""
제재통계 — 데스크톱 실행 진입점

  python app.py

같은 NTIS 제재정보 rawdata 하나로 두 가지 통계를 만든다.

  원인과제 집계 : 과제 단위 / 총연구기간 기준 / 부처 x 7항목      (sanction_pipeline)
  월별 통계     : 제재 레코드 단위 / 처분연도 기준 / 통계 9종      (monthly_pipeline)

pywebview 가 설치되어 있으면 네이티브 창으로 열리고, 없으면 기본 브라우저로 같은
화면을 엽니다. 화면은 127.0.0.1 임의 포트에서만 제공되며 외부로 열리지 않습니다.
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
from urllib.parse import urlparse

import monthly_pipeline as MP
from excel_writer import write_excel
from hwpx_writer import fill_hwpx
from monthly_excel import write_monthly_excel
from monthly_hwpx import fill_monthly_hwpx
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

APP_TITLE = "제재통계"
CAUSE, MONTHLY = "cause", "monthly"


def resource_path(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / rel


UI_FILE = resource_path("ui/index.html")
#: 원인과제 집계 표준양식 (내장)
TEMPLATE_CAUSE = resource_path("template.hwpx")
#: 월별 통계 표준양식 (내장)
TEMPLATE_MONTHLY = resource_path("template_monthly.hwpx")
#: 조사·분석 참조데이터 기본값 (내장, 화면에서 교체 가능)
REFERENCE_FILE = resource_path("reference.xlsx")


def default_outdir() -> Path:
    home = Path.home()
    for name in ("Documents", "문서"):
        if (home / name).is_dir():
            return home / name / "제재통계"
    return home / "제재통계"


# ---------------------------------------------------------------------------
# 상태 — 통계별로 따로 보관 (같은 rawdata 를 공유)
# ---------------------------------------------------------------------------

class Job:
    def __init__(self) -> None:
        self.result = None
        self.payload: dict | None = None
        self.stage = ""
        self.pct = 0
        self.busy = False
        self.error: str | None = None
        self.notes: list[str] = []
        self.resolved: dict = {}
        self.exports: list[str] = []

    def set(self, stage: str, pct: int) -> None:
        self.stage, self.pct = stage, pct

    def note(self, msg: str) -> None:
        if msg and msg not in self.notes:
            self.notes.append(msg)

    def snapshot(self) -> dict:
        return {
            "busy": self.busy, "stage": self.stage, "pct": self.pct,
            "error": self.error, "payload": self.payload, "exports": self.exports,
        }


class State:
    def __init__(self) -> None:
        self.paths: dict = {"raw": None, "template": None, "templateMonthly": None,
                            "ref": None, "outdir": None}
        self.names: dict = {"raw": None, "template": None, "templateMonthly": None,
                            "ref": None}
        self.jobs: dict[str, Job] = {CAUSE: Job(), MONTHLY: Job()}

    def job(self, kind: str) -> Job:
        return self.jobs[kind if kind in self.jobs else CAUSE]


ST = State()
WINDOW = None


def _log_hook(job: Job):
    """파이프라인이 내는 경고('!'로 시작)만 화면 각주로 올린다."""
    def log(msg: str) -> None:
        if "!" in msg:
            job.note(msg.strip().lstrip("!").strip())
    return log


def _j(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f != f:
        return None
    return int(f) if f == int(f) else round(f, 4)


# ---------------------------------------------------------------------------
# 원인과제 집계
# ---------------------------------------------------------------------------

def _cause_cfg(opts: dict) -> PipelineConfig:
    def i(key, default=None):
        v = opts.get(key)
        if v in (None, "", "auto"):
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return PipelineConfig(
        sheet_name=opts.get("sheet") or "제재정보",
        header_row=i("headerRow"),
        data_start_row=i("dataStartRow"),
        min_task_year=i("minTaskYear", 2017) or 2017,
        year_start=i("yearStart"),
        year_end=i("yearEnd"),
        year_end_cap=i("yearEndCap"),
        id_strategy=opts.get("idStrategy") or "번호우선",
        ministry_column=opts.get("ministryColumn") or "소관부처",
        verbose=True,
    )


def _cause_integrity(res, long_df) -> list[dict]:
    checks = []
    ok = True
    for y in res.years:
        a = int(long_df[long_df["연도"] == y]["건수"].sum()) if len(long_df) else 0
        if a != res.subtotal(TOTAL_LABEL, y):
            ok = False
            break
    checks.append({"label": "연도별 소계 = 연도 전개 건수 합", "ok": ok})
    checks.append({"label": "부처별 합 = 합 계 행", "ok": all(
        sum(res.subtotal(m, k) for m in res.ministries) == res.subtotal(TOTAL_LABEL, k)
        for k in [*res.years, "합계"])})
    ok = True
    for m in [*res.ministries, TOTAL_LABEL]:
        for k in [*res.years, "합계"]:
            if sum(res.count(m, c, k) for c in JUDGMENT_ORDER) != res.subtotal(m, k):
                ok = False
    checks.append({"label": "① + ② + ③ = 소계", "ok": ok})
    counted = res.tasks["_판정코드"].notna() & res.tasks["집계반영연도"].ne("")
    checks.append({"label": "합 계 열 = 계속과제 1건 기준 과제 수*",
                   "ok": int(counted.sum()) == res.subtotal(TOTAL_LABEL, "합계")})
    return checks


def _cause_payload(res, job: Job) -> dict:
    keys = [*res.years, "합계"]
    rows = {}
    for m in [*res.ministries, TOTAL_LABEL]:
        rows[m] = {
            "fee": [_j(res.ref(m, "국가R&D연구비", k)) for k in keys],
            "cnt": [_j(res.ref(m, "국가R&D과제수", k)) for k in keys],
            "①": [res.count(m, "①", k) for k in keys],
            "②": [res.count(m, "②", k) for k in keys],
            "③": [res.count(m, "③", k) for k in keys],
            "sub": [res.subtotal(m, k) for k in keys],
            "ratio": [None if res.ratio(m, k) is None else round(res.ratio(m, k), 2)
                      for k in keys],
        }
    return {
        "years": [int(y) for y in res.years],
        "ministries": list(res.ministries),
        "totalLabel": TOTAL_LABEL,
        "rows": rows,
        "hasRef": bool(res.reference),
        "taskTotal": int(len(res.tasks)),
        "excluded": int(res.tasks["_판정코드"].isna().sum()),
        "counted": int(res.subtotal(TOTAL_LABEL, "합계")),
        "records": int(res.long["건수"].sum()) if len(res.long) else 0,
        "checks": _cause_integrity(res, res.long),
        "notes": list(job.notes),
        "resolved": {
            "headerRow": job.resolved.get("header_row"),
            "sheet": job.resolved.get("sheet"),
            "idStrategy": job.resolved.get("id_strategy"),
            "ministryColumn": job.resolved.get("ministry_column"),
            "renames": job.resolved.get("ministry_renames") or {},
        },
    }


def run_cause(opts: dict) -> None:
    job = ST.job(CAUSE)
    job.busy, job.error, job.notes, job.exports = True, None, [], []
    job.payload, job.result = None, None
    try:
        raw_path = ST.paths.get("raw")
        if not raw_path or not Path(raw_path).exists():
            raise FileNotFoundError("제재정보 rawdata 파일을 먼저 넣어 주세요.")
        cfg = _cause_cfg(opts)
        cfg.log = _log_hook(job)

        job.set("rawdata 읽는 중", 8)
        raw = load_raw(raw_path, cfg)
        job.set("컬럼 정리 · 연도 추출", 26)
        tr = transform(raw, cfg)
        job.set("부처명 통일 · 결측 보완", 44)
        pp = preprocess(tr, cfg)
        job.set("과제 단위 제재유형 판정", 62)
        tasks, years, mask = analyze_periods(pp, cfg)
        job.set("부처 × 연도 집계", 80)
        res = aggregate(tasks, years, mask, cfg)

        ref_path = ST.paths.get("ref")
        if not ref_path and REFERENCE_FILE.exists():
            ref_path = str(REFERENCE_FILE)
            job.note("참조데이터는 내장된 기본값을 사용했습니다.")
        if ref_path:
            job.set("조사·분석 참조데이터 결합", 92)
            res.reference = load_reference(ref_path, years, cfg)
            check_reference_coverage(res, cfg)

        job.set("검산", 97)
        job.result = res
        job.resolved = dict(cfg.resolved)
        job.resolved["sheet"] = cfg.sheet_name
        job.payload = _cause_payload(res, job)
        job.set("완료", 100)
    except Exception as e:  # noqa: BLE001
        job.error = f"{e}"
        job.set("중단", 0)
        traceback.print_exc()
    finally:
        job.busy = False


# ---------------------------------------------------------------------------
# 월별 통계
# ---------------------------------------------------------------------------

def _monthly_cfg(opts: dict) -> MP.MonthlyConfig:
    def i(key, default=None):
        v = opts.get(key)
        if v in (None, "", "auto"):
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return MP.MonthlyConfig(
        sheet_name=opts.get("sheet") or "제재정보",
        header_row=i("headerRow"),
        data_start_row=i("dataStartRow"),
        year_start=i("yearStart", 2017),
        year_end=i("yearEnd"),
        ministry_column=opts.get("ministryColumn") or "소관부처",
        verbose=True,
    )


def _monthly_payload(res: MP.MonthlyResult, job: Job) -> dict:
    keys = [*res.years, "합계"]
    checks = {c["label"]: c["ok"] for c in MP.integrity(res)}
    tables = []
    for t in res.tables:
        label = f"{t.no}. {t.axis}별 {t.sanction}"
        tables.append({
            "no": t.no, "title": t.title, "sanction": t.sanction, "axis": t.axis,
            "unit": t.unit, "items": t.items,
            "labels": t.labels,
            "displayLabels": [MP.display_label(x) for x in t.labels],
            "extraLabels": t.extra_labels,
            "values": {
                lab: {it: [_j(t.get(lab, it, k)) for k in keys] for it in t.items}
                for lab in [*t.labels, MP.TOTAL_LABEL]
            },
            "total": {it: _j(t.get(MP.TOTAL_LABEL, it, "합계")) for it in t.items},
            "ok": checks.get(label, True),
        })
    return {
        "years": [int(y) for y in res.years],
        "totalLabel": MP.TOTAL_LABEL,
        "tables": tables,
        "checks": MP.integrity(res),
        "preRows": int(len(res.pre)),
        "dropped": {
            "outOfRange": int(res.dropped.get("연도밖", 0)),
            "otherTypes": list(res.dropped.get("제재유형외", [])),
        },
        "notes": list(job.notes),
        "resolved": {
            "headerRow": job.resolved.get("header_row"),
            "sheet": job.resolved.get("sheet"),
            "ministryColumn": job.resolved.get("ministry_column"),
            "renames": job.resolved.get("ministry_renames") or {},
            "orgAlias": job.resolved.get("org_alias_hits") or {},
        },
    }


def run_monthly(opts: dict) -> None:
    job = ST.job(MONTHLY)
    job.busy, job.error, job.notes, job.exports = True, None, [], []
    job.payload, job.result = None, None
    try:
        raw_path = ST.paths.get("raw")
        if not raw_path or not Path(raw_path).exists():
            raise FileNotFoundError("제재정보 rawdata 파일을 먼저 넣어 주세요.")
        cfg = _monthly_cfg(opts)
        cfg.log = _log_hook(job)

        job.set("rawdata 읽는 중", 10)
        raw = MP.load_raw(raw_path, cfg)
        job.set("전처리 (11열)", 40)
        pre = MP.preprocess(raw, cfg)
        job.set("통계 9종 집계", 75)
        res = MP.aggregate(pre, cfg)

        job.set("검산", 95)
        job.result = res
        job.resolved = dict(cfg.resolved)
        job.payload = _monthly_payload(res, job)
        job.set("완료", 100)
    except Exception as e:  # noqa: BLE001
        job.error = f"{e}"
        job.set("중단", 0)
        traceback.print_exc()
    finally:
        job.busy = False


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def run_export(kind: str, targets: list[str], outdir: str | None, opts: dict) -> list[str]:
    job = ST.job(kind)
    if job.result is None:
        raise RuntimeError("집계를 먼저 실행해 주세요.")

    base = Path(outdir) if outdir else default_outdir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    prefix = "원인과제집계" if kind == CAUSE else "월별통계"
    made: list[str] = []

    if "xlsx" in targets:
        p = base / f"{prefix}_{stamp}.xlsx"
        if kind == CAUSE:
            write_excel(job.result, str(p), include_long=bool(opts.get("includeLong")))
        else:
            write_monthly_excel(job.result, str(p),
                                include_pre=bool(opts.get("includePre", True)))
        made.append(str(p))

    if "hwpx" in targets:
        slot = "template" if kind == CAUSE else "templateMonthly"
        bundled = TEMPLATE_CAUSE if kind == CAUSE else TEMPLATE_MONTHLY
        tpl = ST.paths.get(slot)
        if not tpl or not Path(tpl).exists():
            tpl = str(bundled) if bundled.exists() else None
        if not tpl:
            raise FileNotFoundError("한글 표준양식(.hwpx)을 찾을 수 없습니다.")
        p = base / f"{prefix}_{stamp}.hwpx"
        if kind == CAUSE:
            fill_hwpx(tpl, str(p), job.result)
        else:
            fill_monthly_hwpx(tpl, str(p), job.result)
        made.append(str(p))

    if "reftpl" in targets and kind == CAUSE:
        p = base / f"참조데이터_양식_{stamp}.xlsx"
        make_reference_template(str(p), job.result.ministries, job.result.years)
        made.append(str(p))

    job.exports = made
    return made


# ---------------------------------------------------------------------------
# 폴더 선택 (메인 스레드에서만)
# ---------------------------------------------------------------------------

DIALOG_Q: "queue.Queue[tuple[str, queue.Queue]]" = queue.Queue()


def pick_folder(timeout: float = 300.0) -> tuple[str | None, str | None]:
    if WINDOW is not None:
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
    server_version = "SanctionUI/2.0"

    def log_message(self, *a):
        pass

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
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, b"ui/index.html not found", "text/plain; charset=utf-8")
            return
        if path == "/api/state":
            self._json({
                "paths": ST.paths,
                "names": ST.names,
                "defaultOutdir": str(default_outdir()),
                "bundled": {
                    "template": TEMPLATE_CAUSE.exists(),
                    "templateMonthly": TEMPLATE_MONTHLY.exists(),
                    "ref": REFERENCE_FILE.exists(),
                },
                "jobs": {k: j.snapshot() for k, j in ST.jobs.items()},
            })
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"잘못된 요청입니다: {e}"}, 400)
            return
        kind = data.get("kind") or CAUSE
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
                slot, val = data.get("slot"), data.get("path")
                if slot in ST.paths:
                    ST.paths[slot] = val or None
                    if slot in ST.names:
                        ST.names[slot] = Path(val).name if val else None
                self._json({"paths": ST.paths, "names": ST.names})
                return

            if path == "/api/upload":
                slot = data.get("slot", "raw")
                name = Path(data.get("name") or "input.xlsx").name
                blob = base64.b64decode((data.get("data") or "").split(",")[-1])
                tmp = Path(tempfile.gettempdir()) / "sanction_ui"
                tmp.mkdir(parents=True, exist_ok=True)
                dest = tmp / name
                dest.write_bytes(blob)
                ST.paths[slot] = str(dest)
                if slot in ST.names:
                    ST.names[slot] = name
                self._json({"path": str(dest), "name": name})
                return

            if path == "/api/analyze":
                job = ST.job(kind)
                if job.busy:
                    self._json({"error": "이미 실행 중입니다."}, 409)
                    return
                fn = run_cause if kind == CAUSE else run_monthly
                threading.Thread(target=fn, args=(data.get("options") or {},),
                                 daemon=True).start()
                self._json({"started": True})
                return

            if path == "/api/export":
                made = run_export(kind, data.get("targets") or ["xlsx"],
                                  data.get("outdir"), data.get("options") or {})
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
        except Exception:  # noqa: BLE001
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
            _pump_dialogs()
        except KeyboardInterrupt:
            pass
        return 0

    global WINDOW
    WINDOW = webview.create_window(
        APP_TITLE, url, width=1280, height=900, min_size=(960, 660),
        background_color="#10202B", text_select=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
