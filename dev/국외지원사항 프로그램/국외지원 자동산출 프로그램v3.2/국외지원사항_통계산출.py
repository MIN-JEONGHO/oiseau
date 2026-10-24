# -*- coding: utf-8 -*-
"""
국외지원사항 자동 통계산출 프로그램 v3.2 (GUI)

디자인 노트
  공문서의 시각 언어에서 가져온 구성: 먹빛 네이비 잉크 + 문서지 쿨화이트,
  색은 관인(官印) 주홍 단 하나만 사용한다(헤더 인장과 실행 버튼).
  파일 지정은 실제 순서가 있는 절차이므로 결재란처럼 단계 레일로 표현하고,
  단계 번호는 파일이 지정되면 잉크색으로 채워져 진행 상태를 구조로 보여준다.

사용법
  ① 연구자 raw 파일 → ② 과제 raw 파일 (결합 파일이면 같은 파일 두 번)
  → [통계 산출 실행] → 통계분석결과_날짜.xlsx 생성
  매핑 규칙은 같은 폴더의 '매핑테이블.xlsx'에서 읽는다.
"""
import os
import sys
import datetime
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

from stat_engine import load_mappings, load_researcher_raw, load_project_raw, compute_stats
from preprocessor import load_rules
from report_builder import build_report

# ── 디자인 토큰 ──────────────────────────────────────────────
PAPER = '#F5F7FA'      # 문서지
FIELD = '#FFFFFF'      # 입력면
INK = '#1B2A44'        # 먹빛 네이비 (본문/제목)
SUBINK = '#5A6B85'     # 보조 텍스트
FAINT = '#93A1B7'      # 자리표시자
LINE = '#D8DEE8'       # 괘선
RAIL = '#C4CDDB'       # 단계 레일
SEAL = '#C73E2E'       # 관인 주홍 (유일한 액센트)
SEAL_HOVER = '#A93325'
OK = '#1B2A44'         # 완료 표시도 잉크색으로 (색은 주홍 하나만)


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def pick_family(root, candidates):
    fams = set(tkfont.families(root))
    for c in candidates:
        if c in fams:
            return c
    return 'TkDefaultFont'


class GhostButton(tk.Label):
    """괘선 스타일 보조 버튼 (찾아보기/변경)."""
    def __init__(self, parent, text, command, **kw):
        super().__init__(parent, text=text, cursor='hand2',
                         bg=FIELD, fg=SUBINK, padx=14, pady=4,
                         highlightthickness=1, highlightbackground=LINE, **kw)
        self._cmd = command
        self.bind('<Button-1>', lambda e: self._cmd())
        self.bind('<Enter>', lambda e: self.configure(fg=INK, highlightbackground=SUBINK))
        self.bind('<Leave>', lambda e: self.configure(fg=SUBINK, highlightbackground=LINE))


class SealButton(tk.Label):
    """주 실행 버튼 — 관인 주홍."""
    def __init__(self, parent, text, command, **kw):
        super().__init__(parent, text=text, cursor='hand2',
                         bg=SEAL, fg='#FFFFFF', pady=13, **kw)
        self._cmd = command
        self._enabled = True
        self.bind('<Button-1>', lambda e: self._enabled and self._cmd())
        self.bind('<Enter>', lambda e: self._enabled and self.configure(bg=SEAL_HOVER))
        self.bind('<Leave>', lambda e: self._enabled and self.configure(bg=SEAL))

    def set_enabled(self, on):
        self._enabled = on
        self.configure(bg=SEAL if on else RAIL, cursor='hand2' if on else 'arrow')


class Step:
    """단계 행: 번호 원 + 라벨 + 파일 상태 + 보조 버튼. 레일로 위아래가 이어진다."""
    D = 26  # 번호 원 지름

    def __init__(self, app, parent, row, num, label, hint, browse_text, command,
                 first=False, last=False):
        self.app = app
        self.num = num
        self.value = ''

        rail = tk.Canvas(parent, width=44, height=10, bg=PAPER, highlightthickness=0)
        rail.grid(row=row, column=0, sticky='ns')
        self.rail, self.first, self.last = rail, first, last
        rail.bind('<Configure>', self._draw_rail)

        body = tk.Frame(parent, bg=PAPER)
        body.grid(row=row, column=1, sticky='ew', pady=(0, 14))
        parent.columnconfigure(1, weight=1)

        top = tk.Frame(body, bg=PAPER)
        top.pack(fill='x')
        tk.Label(top, text=label, font=app.f_label, bg=PAPER, fg=INK).pack(side='left')
        tk.Label(top, text='  ' + hint, font=app.f_small, bg=PAPER, fg=FAINT).pack(side='left')

        line = tk.Frame(body, bg=FIELD, highlightthickness=1, highlightbackground=LINE)
        line.pack(fill='x', pady=(5, 0))
        self.path_lbl = tk.Label(line, text='파일을 선택해 주세요', font=app.f_path,
                                 bg=FIELD, fg=FAINT, anchor='w', padx=12, pady=6)
        self.path_lbl.pack(side='left', fill='x', expand=True)
        GhostButton(line, browse_text, command, font=app.f_small).pack(side='right', padx=6, pady=5)

    def _draw_rail(self, e=None):
        c, D = self.rail, self.D
        c.delete('all')
        h = c.winfo_height()
        cx, cy = 22, 24
        if not self.first:
            c.create_line(cx, 0, cx, cy - D // 2, fill=RAIL)
        if not self.last:
            c.create_line(cx, cy + D // 2, cx, h, fill=RAIL)
        filled = bool(self.value)
        c.create_oval(cx - D // 2, cy - D // 2, cx + D // 2, cy + D // 2,
                      fill=INK if filled else PAPER,
                      outline=INK if filled else RAIL, width=1)
        c.create_text(cx, cy, text=str(self.num), font=self.app.f_stepnum,
                      fill='#FFFFFF' if filled else SUBINK)

    def set(self, path, placeholder=False):
        self.value = '' if placeholder else path
        show = path if path else '파일을 선택해 주세요'
        if path and not placeholder and len(show) > 58:
            show = show[:26] + ' … ' + show[-28:]   # 긴 경로는 중간 생략
        self.path_lbl.configure(text=show, fg=INK if (path and not placeholder) else FAINT)
        self._draw_rail()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('국외지원사항 자동 통계산출 v3.2')
        self.configure(bg=PAPER)
        self.geometry('700x780')
        self.resizable(False, False)
        self._set_icon()

        kr = ['맑은 고딕', 'Malgun Gothic', 'Noto Sans CJK KR', 'NanumGothic']
        mono = ['Consolas', 'D2Coding', 'Noto Sans Mono CJK KR', 'Courier New']
        self.F = pick_family(self, kr)
        self.M = pick_family(self, mono)
        self.f_title = (self.F, 15, 'bold')
        self.f_sub = (self.F, 9)
        self.f_label = (self.F, 10, 'bold')
        self.f_small = (self.F, 9)
        self.f_path = (self.F, 9)
        self.f_stepnum = (self.F, 9, 'bold')
        self.f_btn = (self.F, 11, 'bold')
        self.f_log = (self.M, 9)

        self.res_path = ''
        self.prj_path = ''
        self.map_path = os.path.join(app_dir(), '매핑테이블.xlsx')
        self.out_dir = app_dir()

        self._build_header()
        self._build_steps()
        self._build_option()
        self._build_action()
        self._build_footer()
        self._build_log()
        self._log('대기 중 — 파일을 지정하면 실행할 수 있습니다.')

    # ── 창 아이콘 ──
    def _set_icon(self):
        try:
            ico = os.path.join(app_dir(), 'app_icon.ico')
            if sys.platform == 'win32' and os.path.exists(ico):
                self.iconbitmap(ico)
            else:
                png = os.path.join(app_dir(), 'app_icon.png')
                if os.path.exists(png):
                    self._icon_img = tk.PhotoImage(file=png)
                    self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    # ── 헤더: 인장 + 제목, 하단 괘선 ──
    def _build_header(self):
        h = tk.Frame(self, bg=PAPER)
        h.pack(fill='x', padx=24, pady=(20, 0))
        seal = tk.Canvas(h, width=44, height=44, bg=PAPER, highlightthickness=0)
        seal.pack(side='left')
        self._draw_seal(seal, 44)
        t = tk.Frame(h, bg=PAPER)
        t.pack(side='left', padx=(12, 0))
        tk.Label(t, text='국외지원사항 자동 통계산출', font=self.f_title,
                 bg=PAPER, fg=INK).pack(anchor='w')
        tk.Label(t, text='raw 파일을 전처리하고 통계분석 리포트를 생성합니다   ·   v3.2',
                 font=self.f_sub, bg=PAPER, fg=SUBINK).pack(anchor='w')
        tk.Frame(self, bg=LINE, height=1).pack(fill='x', padx=24, pady=(14, 16))

    def _draw_seal(self, c, s):
        r = int(s * 0.24)
        self._rounded(c, 2, 2, s - 2, s - 2, r, fill=SEAL)
        k = int(s * 0.15)
        self._rounded(c, k, k, s - k, s - k, int(r * 0.5), outline='#FFFFFF', width=2, fill='')
        c.create_text(s / 2, s / 2 - 1, text='통', font=(self.F, int(s * 0.34), 'bold'),
                      fill='#FFFFFF')

    @staticmethod
    def _rounded(c, x1, y1, x2, y2, r, **kw):
        pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r, x2,y2-r, x2,y2, x2-r,y2,
               x1+r,y2, x1,y2, x1,y2-r, x1,y1+r, x1,y1]
        return c.create_polygon(pts, smooth=True, **kw)

    # ── 단계 레일 ──
    def _build_steps(self):
        grid = tk.Frame(self, bg=PAPER)
        grid.pack(fill='x', padx=24)
        self.s1 = Step(self, grid, 0, 1, '연구자 raw 파일',
                       '연구자raw 시트가 있는 파일 또는 단독 파일',
                       '찾아보기', self._pick_res, first=True)
        self.s2 = Step(self, grid, 1, 2, '과제 raw 파일',
                       '결합 파일이면 ①과 같은 파일이 자동 지정됩니다',
                       '찾아보기', self._pick_prj)
        self.s3 = Step(self, grid, 2, 3, '매핑테이블',
                       '기관별칭 · 민감국가 · 소속정규화',
                       '변경', self._pick_map)
        self.s4 = Step(self, grid, 3, 4, '결과 저장 폴더', '',
                       '변경', self._pick_out, last=True)
        # 기본값 표시 (자리표시자가 아닌 실제 값)
        self.s3.set(self.map_path if os.path.exists(self.map_path) else '',
                    placeholder=not os.path.exists(self.map_path))
        if not os.path.exists(self.map_path):
            self.s3.path_lbl.configure(text='매핑테이블.xlsx를 찾을 수 없습니다 — 지정해 주세요')
        self.s4.set(self.out_dir)

    # ── 전처리 옵션 ──
    def _build_option(self):
        box = tk.Frame(self, bg=PAPER)
        box.pack(fill='x', padx=24, pady=(2, 10))
        self.do_pre = tk.BooleanVar(value=True)
        self.chk = tk.Canvas(box, width=16, height=16, bg=PAPER, highlightthickness=0,
                             cursor='hand2')
        self.chk.pack(side='left', pady=(1, 0))
        txt = tk.Label(box, text='raw 파일 전처리 실행', font=self.f_label,
                       bg=PAPER, fg=INK, cursor='hand2')
        txt.pack(side='left', padx=(8, 0))
        hint = tk.Label(box, text='오류값 행 제거, 기관별칭, 민감국가, 소속정규화 적용 등',
                        font=self.f_small, bg=PAPER, fg=SUBINK)
        hint.pack(side='left', padx=(8, 0))
        for w in (self.chk, txt):
            w.bind('<Button-1>', lambda e: self._toggle_pre())
        self._draw_chk()

    def _draw_chk(self):
        c, on = self.chk, self.do_pre.get()
        c.delete('all')
        c.create_rectangle(1, 1, 15, 15, outline=INK if on else RAIL,
                           fill=INK if on else FIELD, width=1)
        if on:
            c.create_line(4, 8, 7, 11, fill='#FFFFFF', width=2)
            c.create_line(7, 11, 12, 5, fill='#FFFFFF', width=2)

    def _toggle_pre(self):
        self.do_pre.set(not self.do_pre.get())
        self._draw_chk()

    # ── 실행 버튼 ──
    def _build_action(self):
        self.run_btn = SealButton(self, '통계 산출 실행', self.run, font=self.f_btn)
        self.run_btn.pack(fill='x', padx=24, pady=(6, 0))
        self.run_btn.set_enabled(False)

    # ── 처리 내역 ──
    def _build_log(self):
        cap = tk.Frame(self, bg=PAPER)
        cap.pack(fill='x', padx=24, pady=(16, 4))
        tk.Label(cap, text='처리 내역', font=self.f_label, bg=PAPER, fg=INK).pack(side='left')
        box = tk.Frame(self, bg=FIELD, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill='both', expand=True, padx=24, pady=(0, 0))
        self.log_w = tk.Text(box, font=self.f_log, bg=FIELD, fg=SUBINK, bd=0,
                             padx=12, pady=10, state='disabled', wrap='word',
                             selectbackground=LINE, height=8)
        self.log_w.pack(fill='both', expand=True)
        self.log_w.tag_configure('ink', foreground=INK)
        self.log_w.tag_configure('seal', foreground=SEAL)

    # ── 배포자 표기 (하단 고정) ──
    def _build_footer(self):
        f = tk.Frame(self, bg=PAPER)
        f.pack(side='bottom', fill='x', padx=24, pady=(8, 12))
        tk.Frame(f, bg=LINE, height=1).pack(fill='x', pady=(0, 7))
        row = tk.Frame(f, bg=PAPER)
        row.pack(fill='x')
        tk.Label(row, text='Powered by MIN', font=(self.F, 9, 'bold'),
                 bg=PAPER, fg=INK).pack(side='left')
        tk.Label(row, text='문의  min@kistep.re.kr', font=self.f_small,
                 bg=PAPER, fg=SUBINK).pack(side='right')

    def _log(self, msg, tag=None):
        self.log_w.configure(state='normal')
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        self.log_w.insert('end', f'{stamp}  ', ())
        self.log_w.insert('end', msg + '\n', tag or ())
        self.log_w.see('end')
        self.log_w.configure(state='disabled')
        self.update()

    # ── 파일 선택 ──
    def _ask_file(self):
        return filedialog.askopenfilename(filetypes=[('Excel 파일', '*.xlsx *.xlsm *.xls')])

    def _pick_res(self):
        p = self._ask_file()
        if p:
            self.res_path = p
            self.s1.set(p)
            if not self.prj_path:           # 결합 파일 편의
                self.prj_path = p
                self.s2.set(p)
            self._refresh()

    def _pick_prj(self):
        p = self._ask_file()
        if p:
            self.prj_path = p
            self.s2.set(p)
            self._refresh()

    def _pick_map(self):
        p = self._ask_file()
        if p:
            self.map_path = p
            self.s3.set(p)
            self._refresh()

    def _pick_out(self):
        p = filedialog.askdirectory()
        if p:
            self.out_dir = p
            self.s4.set(p)

    def _refresh(self):
        ready = bool(self.res_path and self.prj_path and os.path.exists(self.map_path))
        self.run_btn.set_enabled(ready)

    def _report_pre(self, lg):
        """전처리 내역을 처리 대장에 기록."""
        self._log(f"{lg['구분']} — 원본 {lg['원본건수']:,}건 → 정제 {lg['정제건수']:,}건 "
                  f"(제거 {lg['제거건수']:,}건, {lg.get('열인식','')})", 'ink')
        for step, detail, cnt in lg['단계']:
            if cnt:
                self._log(f'  · {step}: {cnt:,}건')
        if lg['검토후보']:
            self._log(f"  · 검토 후보 {len(lg['검토후보'])}종 발견 — [전처리 내역] 시트 확인", 'seal')

    # ── 실행 ──
    def run(self):
        try:
            self.run_btn.set_enabled(False)
            self._log('매핑테이블 읽는 중...')
            org_alias, country_map, aff_norm = load_mappings(self.map_path)
            self._log(f'기관별칭 {len(org_alias)}건 · 민감국가 {len(country_map)}건 · '
                      f'소속정규화 {len(aff_norm)}건')

            rules = load_rules(self.map_path)
            pre = self.do_pre.get()
            n_rules = sum(len(v) for v in rules.values())
            self._log(f'전처리 {"실행" if pre else "건너뜀"}'
                      + (f' — 제거 기준값 {n_rules}건 적용' if pre else ''))

            self._log('연구자 raw 읽는 중...')
            res, log_r = load_researcher_raw(self.res_path, rules, pre)
            self._report_pre(log_r)

            self._log('과제 raw 읽는 중...')
            prj, log_p = load_project_raw(self.prj_path, rules, pre)
            self._report_pre(log_p)

            self._log('통계 산출 중...')
            S = compute_stats(res, prj, org_alias, country_map, aff_norm)
            S['전처리내역'] = [log_r, log_p]

            out = os.path.join(self.out_dir,
                               f'통계분석결과_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx')
            self._log('리포트 생성 중...')
            build_report(S, out)

            self._log(f'완료 — {os.path.basename(out)}', 'ink')
            self._log(f'총 {S["총건수"]:,}건 · 연구자 {S["고유연구자수"]:,}명 · '
                      f'국가 {S["국가수"]}개 · 기관 {S["지원기관수"]:,}개 · '
                      f'보안우려 {S["보안"]["위험국가"] + S["보안"]["민감국가"]:,}건', 'ink')
            self._log(f'보고의무 종료 연구자 {S.get("보고의무종료연구자수", 0):,}명 '
                      f'({S.get("산출기준일", "")} 기준)', 'ink')
            self._refresh()
            if messagebox.askyesno('완료', f'통계 산출이 완료되었습니다.\n\n{out}\n\n지금 열어볼까요?'):
                os.startfile(out) if sys.platform == 'win32' else os.system(f'open "{out}"')
        except Exception:
            self._refresh()
            err = traceback.format_exc()
            self._log('오류 발생 — 아래 내용을 확인해 주세요', 'seal')
            self._log(err.strip().splitlines()[-1], 'seal')
            self._log(err)
            messagebox.showerror('오류', '처리 중 오류가 발생했습니다. 처리 내역을 확인해 주세요.')


if __name__ == '__main__':
    # CLI 모드: python 국외지원사항_통계산출.py 연구자.xlsx 과제.xlsx [출력.xlsx]
    if len(sys.argv) >= 3:
        mp = os.path.join(app_dir(), '매핑테이블.xlsx')
        org_alias, country_map, aff_norm = load_mappings(mp)
        rules = load_rules(mp)
        res, log_r = load_researcher_raw(sys.argv[1], rules, True)
        prj, log_p = load_project_raw(sys.argv[2], rules, True)
        for lg in (log_r, log_p):
            print(f"{lg['구분']}: 원본 {lg['원본건수']:,} → 정제 {lg['정제건수']:,} "
                  f"(제거 {lg['제거건수']:,})")
        S = compute_stats(res, prj, org_alias, country_map, aff_norm)
        S['전처리내역'] = [log_r, log_p]
        out = sys.argv[3] if len(sys.argv) > 3 else f'통계분석결과_{datetime.datetime.now():%Y%m%d}.xlsx'
        build_report(S, out)
        print('완료:', out)
    else:
        App().mainloop()
