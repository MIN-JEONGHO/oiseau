# -*- coding: utf-8 -*-
"""
회의록 자동정리 프로그램 — 실행 진입점

  python app.py                      GUI (pywebview 창, 없으면 기본 브라우저)
  python app.py --cli 녹음.m4a ...    명령줄

처리 흐름
  녹음파일 --(OpenAI Whisper API)--> 전사문
          --(OpenAI GPT: 발언자 매칭)--> 참석자별 발언
          --(OpenAI GPT: 기관별 요약)--> 요약 초안 (화면에서 수정 가능)
          --> 표준 양식 hwpx

화면은 127.0.0.1 의 임의 포트에서만 제공되며 외부로 열리지 않는다.
"""
from __future__ import annotations

import argparse
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
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import audio
import config as CFG
import hwpx_writer as HW
import stt
import summarizer as SUM
from hwpx_writer import Document, fill_hwpx
from stt import Transcript
from summarizer import Attendee, Summary

APP_TITLE = "회의록 자동정리 프로그램"
APP_VERSION = "v3.0.0"

WINDOW = None
DIALOG_Q: "queue.Queue[tuple[str, dict, queue.Queue]]" = queue.Queue()


def resource_path(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / rel


def workdir() -> Path:
    d = Path(tempfile.gettempdir()) / "kistep_minutes"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 상태 / 작업
# ---------------------------------------------------------------------------

@dataclass
class Job:
    busy: bool = False
    step: str = ""
    message: str = ""
    log: list[str] = field(default_factory=list)
    error: str = ""
    done: bool = False

    def start(self, step: str) -> None:
        self.busy, self.step, self.error, self.done = True, step, "", False
        self.message = ""
        self.log = []

    def say(self, msg: str) -> None:
        self.message = msg
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")
        del self.log[:-200]

    def finish(self, error: str = "") -> None:
        self.busy, self.done, self.error = False, True, error
        if error:
            self.say("실패: " + error.splitlines()[0])
        else:
            self.say("완료")

    def to_dict(self) -> dict[str, Any]:
        return {"busy": self.busy, "step": self.step, "message": self.message,
                "log": self.log, "error": self.error, "done": self.done}


@dataclass
class State:
    cfg: dict[str, Any] = field(default_factory=CFG.load)
    audio_path: str = ""
    audio_name: str = ""
    transcript: Transcript | None = None
    attendees: list[Attendee] = field(default_factory=list)
    summary: Summary | None = None
    meta: dict[str, Any] = field(default_factory=lambda: {
        "title": "", "date": datetime.now().strftime("%Y-%m-%d"),
        "when_where": "", "agenda": "",
    })
    outdir: str = ""
    last_files: list[str] = field(default_factory=list)
    job: Job = field(default_factory=Job)

    def snapshot(self) -> dict[str, Any]:
        return {
            "config": CFG.settings(self.cfg),
            "audio": {"path": self.audio_path, "name": self.audio_name},
            "transcript": self.transcript.to_dict() if self.transcript else None,
            "attendees": [a.to_dict() for a in self.attendees],
            "summary": self.summary.to_dict() if self.summary else None,
            "meta": self.meta,
            "outdir": self.outdir or self.cfg.get("last_outdir") or "",
            "last_files": self.last_files,
            "job": self.job.to_dict(),
            "env": {
                "audio_backend": audio.backend_name() or "",
                "key_embedded": CFG.key_embedded(),
                "key_ready": bool(CFG.api_key()),
                "stt_model": CFG.STT_MODEL,
                "summary_model": CFG.SUMMARY_MODEL,
                "version": APP_VERSION,
            },
        }

    # --- 세션 저장/복원 (전사 비용을 다시 치르지 않기 위해) ---
    def session_dict(self) -> dict[str, Any]:
        return {
            "app": APP_TITLE, "version": APP_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "audio_name": self.audio_name,
            "transcript": self.transcript.to_dict() if self.transcript else None,
            "attendees": [a.to_dict() for a in self.attendees],
            "summary": self.summary.to_dict() if self.summary else None,
            "meta": self.meta,
        }

    def load_session(self, d: dict[str, Any]) -> None:
        self.audio_name = d.get("audio_name", "")
        self.transcript = Transcript.from_dict(d["transcript"]) if d.get("transcript") else None
        self.attendees = [Attendee.from_dict(a) for a in d.get("attendees", [])]
        self.summary = Summary.from_dict(d["summary"]) if d.get("summary") else None
        self.meta.update(d.get("meta") or {})


ST = State()


def _run(step: str, fn: Callable[[Callable[[str], None]], None]) -> None:
    """백그라운드 작업 공통 래퍼."""
    def worker() -> None:
        try:
            fn(ST.job.say)
            ST.job.finish()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            ST.job.finish(str(e) or type(e).__name__)

    ST.job.start(step)
    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# 파이프라인 단계
# ---------------------------------------------------------------------------

def do_transcribe(say: Callable[[str], None]) -> None:
    if not ST.audio_path:
        raise RuntimeError("녹음파일을 먼저 선택해 주세요.")
    say(f"전사 시작 — OpenAI Whisper API ({CFG.STT_MODEL})")
    tr = stt.transcribe(ST.audio_path, ST.cfg, workdir(), say)
    ST.transcript = tr
    mins = int(tr.duration // 60)
    say(f"전사 완료 — {len(tr.segments)}개 구간, 약 {mins}분")


def do_match_speakers(say: Callable[[str], None]) -> None:
    if not ST.transcript:
        raise RuntimeError("먼저 전사를 진행해 주세요.")
    if not ST.attendees:
        raise RuntimeError("참석자를 한 명 이상 입력해 주세요.")
    tr = ST.transcript
    turns = SUM.infer_speakers(tr, ST.attendees, ST.cfg, say)
    SUM.apply_turns(tr, turns)
    named = len({s.speaker for s in tr.segments if s.speaker and s.speaker != SUM.UNKNOWN})
    say(f"발언 묶음 {len(turns)}개를 만들고 참석자 {named}명을 배정했습니다.")
    say("추정 결과이므로 아래 전사문에서 직접 고칠 수 있습니다.")


def do_summarize(say: Callable[[str], None]) -> None:
    if not ST.transcript:
        raise RuntimeError("먼저 전사를 진행해 주세요.")
    if not ST.attendees:
        raise RuntimeError("참석자를 한 명 이상 입력해 주세요.")
    ST.summary = SUM.summarize(ST.transcript, ST.attendees, ST.meta, ST.cfg, say)
    n = sum(len(i.items) for i in ST.summary.institutions)
    say(f"기관 {len(ST.summary.institutions)}곳, 항목 {n}개로 정리했습니다.")
    if not ST.meta.get("title"):
        ST.meta["title"] = ST.summary.title
    if not ST.meta.get("agenda"):
        ST.meta["agenda"] = ST.summary.agenda


def export(outdir: str | None = None, attach: bool | None = None,
           merge: bool = True, also_txt: bool = True) -> list[str]:
    if not ST.summary:
        raise RuntimeError("먼저 요약을 생성해 주세요.")
    out = Path(outdir or ST.outdir or ST.cfg.get("last_outdir") or Path.home() / "Downloads")
    out.mkdir(parents=True, exist_ok=True)
    ST.outdir = str(out)
    ST.cfg["last_outdir"] = str(out)
    CFG.save(ST.cfg)

    title = (ST.meta.get("title") or ST.summary.title or "회의").strip()
    safe = "".join(c for c in title if c not in '\\/:*?"<>|').strip() or "회의"
    stamp = (ST.meta.get("date") or datetime.now().strftime("%Y-%m-%d")).replace("-", "")

    doc = Document(
        summary=ST.summary,
        attendees=ST.attendees,
        meeting_date=ST.meta.get("date", ""),
        when_where=ST.meta.get("when_where", ""),
        org_footer=ST.cfg.get("org_footer") or "KISTEP 연구윤리자산보호센터",
        transcript=ST.transcript,
        attach_transcript=(ST.cfg.get("attach_transcript", True) if attach is None else attach),
        merge_transcript=merge,
    )
    made = [fill_hwpx(resource_path("template.hwpx"), out / f"{stamp}_{safe}_회의록.hwpx", doc)]
    if also_txt and ST.transcript:
        made.append(HW.write_transcript_txt(out / f"{stamp}_{safe}_전사문.txt",
                                            ST.transcript, title))
    session = out / f"{stamp}_{safe}_세션.json"
    session.write_text(json.dumps(ST.session_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
    made.append(str(session))
    ST.last_files = made
    return made


# ---------------------------------------------------------------------------
# 파일 대화상자 / 탐색기
# ---------------------------------------------------------------------------

AUDIO_FILTER = ("녹음 파일 (*.mp3;*.m4a;*.wav;*.flac;*.ogg;*.opus;*.aac;*.wma;*.mp4;*.webm)",
                "모든 파일 (*.*)")


def ask_path(kind: str) -> str | None:
    """네이티브 파일/폴더 선택. pywebview 가 없으면 tkinter 로 대체."""
    if WINDOW is not None:
        try:
            import webview
            if kind == "folder":
                got = WINDOW.create_file_dialog(webview.FOLDER_DIALOG)
            elif kind == "audio":
                got = WINDOW.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                                file_types=AUDIO_FILTER)
            else:
                got = WINDOW.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                                file_types=("세션 파일 (*.json)",))
            return got[0] if got else None
        except Exception:  # noqa: BLE001
            pass
    reply: "queue.Queue[str | None]" = queue.Queue()
    DIALOG_Q.put((kind, {}, reply))
    return reply.get()


def _pump_dialogs() -> None:
    """브라우저 대체 모드에서 tkinter 대화상자를 메인 스레드로 처리."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        tk = None  # type: ignore[assignment]
    while True:
        kind, _opts, reply = DIALOG_Q.get()
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
                p = filedialog.askdirectory(title="결과를 저장할 폴더 선택")
            elif kind == "audio":
                p = filedialog.askopenfilename(
                    title="회의 녹음파일 선택",
                    filetypes=[("녹음 파일", "*.mp3 *.m4a *.wav *.flac *.ogg *.opus "
                                          "*.aac *.wma *.mp4 *.webm"),
                               ("모든 파일", "*.*")])
            else:
                p = filedialog.askopenfilename(title="세션 파일 선택",
                                               filetypes=[("세션 파일", "*.json")])
            r.destroy()
            reply.put(p or None)
        except Exception:  # noqa: BLE001
            reply.put(None)


def reveal(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])


def open_file(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    if sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ---------------------------------------------------------------------------
# HTTP 핸들러
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a: Any) -> None:  # 콘솔 조용히
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = resource_path("ui/index.html").read_bytes()
            self._send(html, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._json(ST.snapshot())
            return
        if path == "/api/job":
            self._json(ST.job.to_dict())
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}

        try:
            self._dispatch(path, data)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": str(e) or type(e).__name__}, 500)

    # -- 라우팅 ------------------------------------------------------------
    def _dispatch(self, path: str, data: dict[str, Any]) -> None:
        if path == "/api/config":
            for k, v in (data.get("config") or {}).items():
                if k in CFG.DEFAULTS:     # 그 밖의 값(키 등)은 화면에서 바꿀 수 없다
                    ST.cfg[k] = v
            CFG.save(ST.cfg)
            self._json({"ok": True, "config": CFG.settings(ST.cfg)})
            return

        if path == "/api/test-stt":
            self._json({"message": stt.test_connection(ST.cfg)})
            return

        if path == "/api/test-summary":
            self._json({"message": SUM.test_connection(ST.cfg)})
            return

        if path == "/api/pick-audio":
            p = ask_path("audio")
            if p:
                ST.audio_path, ST.audio_name = p, Path(p).name
            self._json({"path": ST.audio_path, "name": ST.audio_name,
                        "size": Path(p).stat().st_size if p else 0})
            return

        if path == "/api/upload-audio":     # 브라우저 대체 모드용
            name = Path(data.get("name") or "recording.m4a").name
            blob = base64.b64decode((data.get("data") or "").split(",")[-1])
            dest = workdir() / name
            dest.write_bytes(blob)
            ST.audio_path, ST.audio_name = str(dest), name
            self._json({"path": ST.audio_path, "name": name, "size": len(blob)})
            return

        if path == "/api/pick-folder":
            p = ask_path("folder")
            if p:
                ST.outdir = p
            self._json({"path": ST.outdir})
            return

        if path == "/api/attendees":
            ST.attendees = [Attendee.from_dict(a) for a in (data.get("attendees") or [])
                            if (a.get("name") or "").strip()]
            self._json({"attendees": [a.to_dict() for a in ST.attendees]})
            return

        if path == "/api/meta":
            ST.meta.update(data.get("meta") or {})
            self._json({"meta": ST.meta})
            return

        if path == "/api/transcript":
            """화면에서 고친 전사문(발언자/문장)을 반영."""
            if ST.transcript is None:
                self._json({"error": "전사 결과가 없습니다."}, 400)
                return
            edits = {int(e["index"]): e for e in (data.get("segments") or [])}
            for s in ST.transcript.segments:
                e = edits.get(s.index)
                if e:
                    if "speaker" in e:
                        s.speaker = (e["speaker"] or "").strip() or SUM.UNKNOWN
                    if "text" in e:
                        s.text = e["text"]
            self._json({"ok": True, "transcript": ST.transcript.to_dict()})
            return

        if path == "/api/summary":
            ST.summary = Summary.from_dict(data.get("summary") or {})
            self._json({"ok": True, "summary": ST.summary.to_dict()})
            return

        if path in ("/api/transcribe", "/api/match-speakers", "/api/summarize"):
            if ST.job.busy:
                self._json({"error": "이미 다른 작업이 진행 중입니다."}, 409)
                return
            fn, step = {
                "/api/transcribe": (do_transcribe, "transcribe"),
                "/api/match-speakers": (do_match_speakers, "match"),
                "/api/summarize": (do_summarize, "summarize"),
            }[path]
            _run(step, fn)
            self._json({"started": True})
            return

        if path == "/api/export":
            files = export(data.get("outdir"), data.get("attach"),
                           bool(data.get("merge", True)))
            self._json({"files": files})
            return

        if path == "/api/save-session":
            out = Path(ST.outdir or Path.home() / "Downloads")
            out.mkdir(parents=True, exist_ok=True)
            p = out / f"{datetime.now():%Y%m%d_%H%M}_회의록세션.json"
            p.write_text(json.dumps(ST.session_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")
            self._json({"path": str(p)})
            return

        if path == "/api/load-session":
            p = data.get("path") or ask_path("session")
            if not p:
                self._json({"cancelled": True})
                return
            ST.load_session(json.loads(Path(p).read_text(encoding="utf-8")))
            self._json({"ok": True, "state": ST.snapshot()})
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_attendees(spec: str) -> list[Attendee]:
    """'홍길동/과기정통부/사무관, 김철수/연구재단/팀장' 형태를 파싱."""
    out = []
    for chunk in spec.split(","):
        bits = [b.strip() for b in chunk.split("/")]
        if bits and bits[0]:
            out.append(Attendee(bits[0], bits[1] if len(bits) > 1 else "",
                                bits[2] if len(bits) > 2 else ""))
    return out


def run_cli(args: argparse.Namespace) -> int:
    def say(msg: str) -> None:
        print(f"  {msg}", flush=True)

    ST.audio_path, ST.audio_name = str(Path(args.audio).resolve()), Path(args.audio).name
    ST.attendees = parse_attendees(args.attendees or "")
    if args.title:
        ST.meta["title"] = args.title
    if args.date:
        ST.meta["date"] = args.date
    if args.place:
        ST.meta["when_where"] = args.place

    if args.session:
        print("[0/4] 세션 불러오기")
        ST.load_session(json.loads(Path(args.session).read_text(encoding="utf-8")))
        if args.attendees:
            ST.attendees = parse_attendees(args.attendees)
    else:
        print("[1/4] 전사")
        do_transcribe(say)

    if not ST.attendees:
        print("  참석자가 지정되지 않아 발언자 매칭을 건너뜁니다. "
              "(--attendees \"이름/기관/직위, …\")")
    else:
        print("[2/4] 발언자 매칭")
        do_match_speakers(say)

    print("[3/4] 기관별 요약")
    do_summarize(say)

    print("[4/4] hwpx 생성")
    files = export(args.out, also_txt=True)
    for f in files:
        print(f"  -> {f}")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{APP_TITLE} {APP_VERSION}")
    ap.add_argument("--cli", dest="audio", metavar="녹음파일",
                    help="명령줄 모드로 실행할 녹음파일 경로")
    ap.add_argument("--attendees", help='참석자. "이름/기관/직위, 이름/기관/직위" 형태')
    ap.add_argument("--title", help="회의 제목")
    ap.add_argument("--date", help="회의 날짜 (YYYY-MM-DD)")
    ap.add_argument("--place", help="일시·장소 표기 (예: '’26. 9. 4. 14:00 / 대회의실')")
    ap.add_argument("--out", help="결과를 저장할 폴더")
    ap.add_argument("--session", help="이전에 저장한 세션 json (전사를 다시 하지 않음)")
    args = ap.parse_args(argv)

    if args.audio:
        try:
            return run_cli(args)
        except Exception as e:  # noqa: BLE001
            print(f"\n[실패] {e}", file=sys.stderr)
            return 1

    port = free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    try:
        import webview
    except ImportError:
        print(f"[{APP_TITLE} {APP_VERSION}] pywebview 가 없어 브라우저로 엽니다: {url}")
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
        f"{APP_TITLE} {APP_VERSION}", url, width=1320, height=920,
        min_size=(1020, 700), background_color="#FBFAF7", text_select=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
