# -*- coding: utf-8 -*-
"""버튼 하나로 실행하는 GUI (tkinter, 별도 설치 불필요).

실행:  python run_gui.py
"""
from __future__ import annotations

import logging
import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, scrolledtext, ttk

from rmonitor.config import apply_smtp_preset, load_config, save_config
from rmonitor.pipeline import run_report
from rmonitor.profiles import PROFILES
from rmonitor.utils import CallbackHandler, month_period, previous_month_period, setup_logger

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.cfg = load_config(CONFIG_PATH)
        self.logger = setup_logger(BASE_DIR / self.cfg.get("log_dir", "logs"))
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.logger.addHandler(CallbackHandler(self.log_queue.put))
        self.running = False
        self.last_results: list[dict] = []

        root.title("연구보안·연구윤리 월간 리포트 자동 발송")
        root.geometry("880x720")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_run = ttk.Frame(nb)
        self.tab_cfg = ttk.Frame(nb)
        nb.add(self.tab_run, text="  실행  ")
        nb.add(self.tab_cfg, text="  설정  ")

        self._build_run_tab()
        self._build_config_tab()
        self._poll_log()

    # ------------------------------------------------------------------
    def _build_run_tab(self):
        f = self.tab_run
        top = ttk.LabelFrame(f, text="실행 옵션")
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="수집 대상 월").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        default_period = previous_month_period()
        self.var_month = StringVar(value=default_period.tag)
        ttk.Entry(top, textvariable=self.var_month, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="(YYYY-MM · 비우면 지난달)").grid(row=0, column=2, sticky="w", padx=6)

        self.var_security = BooleanVar(value=self.cfg["reports"]["security"].get("enabled", True))
        self.var_ethics = BooleanVar(value=self.cfg["reports"]["ethics"].get("enabled", True))
        ttk.Checkbutton(top, text="연구보안 리포트", variable=self.var_security)\
            .grid(row=1, column=0, columnspan=2, sticky="w", padx=8)
        ttk.Checkbutton(top, text="연구윤리 리포트", variable=self.var_ethics)\
            .grid(row=1, column=2, sticky="w")

        self.var_send = BooleanVar(value=True)
        self.var_excel = BooleanVar(value=True)
        self.var_confirm = BooleanVar(value=True)
        ttk.Checkbutton(top, text="메일 발송", variable=self.var_send)\
            .grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(top, text="엑셀 누적 기록", variable=self.var_excel)\
            .grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(top, text="발송 전 미리보기·확인", variable=self.var_confirm)\
            .grid(row=2, column=2, sticky="w")

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=8)
        self.btn_run = ttk.Button(btns, text="▶  실행", command=self.on_run)
        self.btn_run.pack(side="left", ipadx=30, ipady=10, pady=6)
        ttk.Button(btns, text="미리보기 열기", command=self.open_preview).pack(side="left", padx=6)
        ttk.Button(btns, text="누적 엑셀 열기", command=self.open_excel).pack(side="left", padx=6)

        self.status = StringVar(value="대기 중")
        ttk.Label(f, textvariable=self.status).pack(anchor="w", padx=12)
        self.progress = ttk.Progressbar(f, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=4)

        self.txt = scrolledtext.ScrolledText(f, height=24, font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True, padx=8, pady=8)

    # ------------------------------------------------------------------
    def _build_config_tab(self):
        f = self.tab_cfg
        self.vars: dict[str, StringVar] = {}

        def row(parent, label, key, value, r, width=48, show=None):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            v = StringVar(value=str(value or ""))
            ttk.Entry(parent, textvariable=v, width=width, show=show)\
                .grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
            self.vars[key] = v
            return v

        llm = ttk.LabelFrame(f, text="AI 조사(LLM) 설정")
        llm.pack(fill="x", padx=8, pady=6)
        ttk.Label(llm, text="Provider").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.var_provider = StringVar(value=self.cfg["llm"]["provider"])
        ttk.Combobox(llm, textvariable=self.var_provider, width=14, state="readonly",
                     values=["gemini", "vertex", "anthropic", "openai"])\
            .grid(row=0, column=1, sticky="w")
        row(llm, "모델", "llm.model", self.cfg["llm"]["model"], 1, width=30)
        row(llm, "API 키", "llm.api_key", self.cfg["llm"]["api_key"], 2, show="*")

        smtp = ttk.LabelFrame(f, text="메일(SMTP) 설정")
        smtp.pack(fill="x", padx=8, pady=6)
        ttk.Label(smtp, text="메일 서비스").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.var_smtp_provider = StringVar(value=self.cfg["smtp"]["provider"])
        cb = ttk.Combobox(smtp, textvariable=self.var_smtp_provider, width=14, state="readonly",
                          values=["gmail", "naver", "daum", "outlook", "custom"])
        cb.grid(row=0, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", self.on_smtp_provider)
        row(smtp, "SMTP 호스트", "smtp.host", self.cfg["smtp"]["host"], 1, width=30)
        row(smtp, "포트", "smtp.port", self.cfg["smtp"]["port"], 2, width=10)
        row(smtp, "보안(starttls/ssl)", "smtp.security", self.cfg["smtp"]["security"], 3, width=14)
        row(smtp, "계정(보내는 주소)", "smtp.user", self.cfg["smtp"]["user"], 4)
        row(smtp, "비밀번호/앱 비밀번호", "smtp.password", self.cfg["smtp"]["password"], 5, show="*")
        row(smtp, "보내는 사람 이름", "smtp.sender_name", self.cfg["smtp"]["sender_name"], 6)

        rcp = ttk.LabelFrame(f, text="수신자 (쉼표 또는 줄바꿈으로 구분)")
        rcp.pack(fill="both", expand=True, padx=8, pady=6)
        ttk.Label(rcp, text="연구보안").grid(row=0, column=0, sticky="nw", padx=8, pady=4)
        self.txt_sec = scrolledtext.ScrolledText(rcp, height=4, width=70)
        self.txt_sec.grid(row=0, column=1, pady=4)
        self.txt_sec.insert("1.0", ", ".join(self.cfg["reports"]["security"]["recipients"]))
        ttk.Label(rcp, text="연구윤리").grid(row=1, column=0, sticky="nw", padx=8, pady=4)
        self.txt_eth = scrolledtext.ScrolledText(rcp, height=4, width=70)
        self.txt_eth.grid(row=1, column=1, pady=4)
        self.txt_eth.insert("1.0", ", ".join(self.cfg["reports"]["ethics"]["recipients"]))

        ex = ttk.LabelFrame(f, text="누적 엑셀")
        ex.pack(fill="x", padx=8, pady=6)
        row(ex, "파일 경로", "excel.path", self.cfg["excel"]["path"], 0, width=52)
        ttk.Button(ex, text="찾아보기", command=self.pick_excel).grid(row=0, column=3, padx=6)

        ttk.Button(f, text="💾  설정 저장", command=self.save_settings)\
            .pack(pady=10, ipadx=20, ipady=6)

    # ------------------------------------------------------------------
    def on_smtp_provider(self, _evt=None):
        from rmonitor.config import SMTP_PRESETS
        preset = SMTP_PRESETS.get(self.var_smtp_provider.get())
        if preset:
            self.vars["smtp.host"].set(preset["host"])
            self.vars["smtp.port"].set(str(preset["port"]))
            self.vars["smtp.security"].set(preset["security"])

    def pick_excel(self):
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            filetypes=[("Excel", "*.xlsx")])
        if path:
            self.vars["excel.path"].set(path)

    @staticmethod
    def _split_addrs(text: str) -> list[str]:
        raw = text.replace("\n", ",").replace(";", ",")
        return [a.strip() for a in raw.split(",") if a.strip()]

    def save_settings(self):
        self.cfg["llm"]["provider"] = self.var_provider.get()
        self.cfg["llm"]["model"] = self.vars["llm.model"].get().strip()
        self.cfg["llm"]["api_key"] = self.vars["llm.api_key"].get().strip()

        apply_smtp_preset(self.cfg, self.var_smtp_provider.get())
        self.cfg["smtp"]["host"] = self.vars["smtp.host"].get().strip()
        try:
            self.cfg["smtp"]["port"] = int(self.vars["smtp.port"].get())
        except ValueError:
            messagebox.showerror("설정 오류", "포트는 숫자여야 합니다.")
            return
        self.cfg["smtp"]["security"] = self.vars["smtp.security"].get().strip().lower()
        self.cfg["smtp"]["user"] = self.vars["smtp.user"].get().strip()
        self.cfg["smtp"]["password"] = self.vars["smtp.password"].get()
        self.cfg["smtp"]["sender_name"] = self.vars["smtp.sender_name"].get().strip()

        self.cfg["reports"]["security"]["recipients"] = self._split_addrs(
            self.txt_sec.get("1.0", "end"))
        self.cfg["reports"]["ethics"]["recipients"] = self._split_addrs(
            self.txt_eth.get("1.0", "end"))
        self.cfg["excel"]["path"] = self.vars["excel.path"].get().strip()

        save_config(self.cfg, CONFIG_PATH)
        messagebox.showinfo("저장 완료", f"설정을 저장했습니다.\n{CONFIG_PATH}")

    # ------------------------------------------------------------------
    def on_run(self):
        if self.running:
            return
        keys = []
        if self.var_security.get():
            keys.append("security")
        if self.var_ethics.get():
            keys.append("ethics")
        if not keys:
            messagebox.showwarning("확인", "리포트를 최소 1개 선택하세요.")
            return
        if self.var_send.get() and not self.cfg["smtp"].get("password"):
            messagebox.showwarning("확인", "설정 탭에서 SMTP 계정과 비밀번호를 먼저 입력하세요.")
            return

        self.running = True
        self.btn_run.config(state="disabled")
        self.progress.start(12)
        self.status.set("실행 중… (웹 조사에 수 분이 걸릴 수 있습니다)")
        threading.Thread(target=self._worker, args=(keys,), daemon=True).start()

    def _worker(self, keys):
        try:
            month = self.var_month.get().strip()
            if month:
                y, m = (int(x) for x in month.split("-")[:2])
                period = month_period(y, m)
            else:
                period = previous_month_period()

            self.last_results = []
            for key in keys:
                self.status.set(f"{PROFILES[key].name} 처리 중…")
                res = run_report(
                    key, period, self.cfg, BASE_DIR,
                    send_mail=self.var_send.get(),
                    write_excel=self.var_excel.get(),
                    confirm=self._confirm if self.var_confirm.get() else None,
                    logger=self.logger,
                )
                self.last_results.append(res)
            self.status.set("완료")
            summary = "\n".join(
                f"· {r.get('name', r['report'])}: 이슈 {r.get('issue_count', 0)}건 / "
                f"발송 {'완료' if r.get('sent') else '안 함'} / "
                f"엑셀 {(r.get('excel') or {}).get('added', 0)}건 추가"
                for r in self.last_results)
            self.root.after(0, lambda: messagebox.showinfo("실행 완료", summary or "처리 결과 없음"))
        except Exception as exc:  # noqa: BLE001
            self.logger.error("실행 실패: %s", exc, exc_info=True)
            self.status.set("실패")
            self.root.after(0, lambda: messagebox.showerror("오류", str(exc)))
        finally:
            self.running = False
            self.root.after(0, self.progress.stop)
            self.root.after(0, lambda: self.btn_run.config(state="normal"))

    def _confirm(self, info) -> bool:
        """발송 직전 미리보기 + 확인 (메인 스레드에서 대화상자 실행)."""
        done = threading.Event()
        answer = {"ok": False}

        def ask():
            try:
                webbrowser.open(Path(info["html_path"]).resolve().as_uri())
            except Exception:
                pass
            answer["ok"] = messagebox.askyesno(
                "발송 확인",
                f"[{info['name']}]\n\n제목: {info['subject']}\n"
                f"이슈: {info['issue_count']}건\n"
                f"수신자 {len(info['recipients'])}명:\n"
                f"{', '.join(info['recipients']) or '(없음)'}\n\n"
                "브라우저에 열린 미리보기를 확인한 뒤 발송하시겠습니까?")
            done.set()

        self.root.after(0, ask)
        done.wait()
        return answer["ok"]

    # ------------------------------------------------------------------
    def open_preview(self):
        if not self.last_results:
            messagebox.showinfo("안내", "먼저 실행해 주세요.")
            return
        for r in self.last_results:
            if r.get("html_path"):
                webbrowser.open(Path(r["html_path"]).resolve().as_uri())

    def open_excel(self):
        path = BASE_DIR / self.cfg["excel"]["path"]
        if not path.exists():
            messagebox.showinfo("안내", "아직 누적 엑셀 파일이 없습니다.")
            return
        webbrowser.open(path.resolve().as_uri())

    def _poll_log(self):
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.txt.insert("end", line + "\n")
            self.txt.see("end")
        self.root.after(200, self._poll_log)


def main():
    logging.getLogger("rmonitor").setLevel(logging.INFO)
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
