# -*- coding: utf-8 -*-
"""
국외지원사항 자동 통계산출 프로그램 v4.3 (GUI)

디자인 노트 — 「편집 계기(Editorial Instrument)」
  이 프로그램의 산출물은 한글 보고서다. 그래서 화면도 한글 문서의 활자로 짠다.
  표제는 함초롬바탕, 수치는 등폭 활자, 구획은 자간을 벌린 돋움과 실선.
  색은 먹빛 계조와 주홍(朱) 하나뿐이고, 주홍은 뜻이 있는 곳에만 쓴다
  — 필수 입력 · 오류 · 정합성 불일치 · 연구보안 우려.
  모서리는 각지고 그림자는 없다. 창 맨 위의 3px 주홍 띠가 판식(版式) 표기다.

  화면은 두 판으로 나뉜다.
    [산출]     raw 두 개를 지정하고 실행하는 자리
    [대시보드] 산출을 마치면 열리는, 파일을 열지 않고 수치를 읽는 자리
  대시보드를 열면 막대가 0에서 자란다. 이 화면에서 유일한 움직임이다.

배포
  매핑테이블·표준보고양식·아이콘은 exe 안에 들어 있다. exe 하나만 옮기면 되고,
  고쳐 써야 할 때는 [양식·테이블 내려받기]로 꺼내 고친다. exe 옆에 놓인 파일이
  내장본을 이기므로, 꺼내 고치면 그 다음 실행부터 자동으로 반영된다.

사용법
  ① 연구자 raw · ② 과제 raw 지정 → [통계 산출 실행]
  → 통계분석결과_날짜.xlsx + 국외지원사항_등록보고현황_날짜.hwpx
"""
import datetime
import os
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

import resources
from resources import MAP_NAME, TPL_NAME, app_dir
from theme import (PAPER, PAPER_2, PAPER_3, INK, INK_2, GREY, GREY_2,
                   RULE, RULE_2, VERM, VERM_2, GREEN,
                   Theme, Btn, BookMark, eyebrow, spaced, ellipsize,
                   enable_dpi_awareness, px, hair)
from dashboard import Dashboard

from stat_engine import (load_mappings, load_researcher_raw, load_project_raw,
                         compute_stats, load_type_rules, check_mapping_conflicts,
                         resolve_base_date)
from preprocessor import load_rules
from report_builder import build_report
from hwpx_writer import build_hwpx

VERSION = 'v4.3'


class Slot:
    """입력 한 칸. 필수/선택 표시 → 이름 → 경로 → 조작 버튼."""

    def __init__(self, app, parent, tag, name, hint, on_pick,
                 required=False, pick_dir=False, clearable=True, act='찾아보기',
                 extra=None, kind='xlsx'):
        self.app, self.on_pick, self.pick_dir = app, on_pick, pick_dir
        self.hint, self.required, self.kind = hint, required, kind
        self.value = ''

        outer = tk.Frame(parent, bg=PAPER)
        outer.pack(fill='x')
        self.outer = outer
        # 왼쪽 세로선 — 필수 입력만 주홍으로 표시
        self.edge = tk.Frame(outer, bg=VERM if required else PAPER, width=px(2))
        self.edge.pack(side='left', fill='y')

        row = tk.Frame(outer, bg=PAPER)
        row.pack(side='left', fill='x', expand=True, padx=(px(12), px(2)), pady=px(8))
        row.columnconfigure(1, weight=1)

        tk.Label(row, text=spaced(tag), font=app.th.f_tag, bg=PAPER,
                 fg=VERM if required else GREY_2, width=6, anchor='w'
                 ).grid(row=0, column=0, rowspan=2, sticky='w')
        tk.Label(row, text=name, font=app.th.f_name, bg=PAPER, fg=INK, anchor='w'
                 ).grid(row=0, column=1, sticky='w')
        self.path = tk.Label(row, text=hint, font=app.th.f_hint, bg=PAPER,
                             fg=GREY_2, anchor='w')
        self.path.grid(row=1, column=1, sticky='w', pady=(px(2), 0))

        acts = tk.Frame(row, bg=PAPER)
        acts.grid(row=0, column=2, rowspan=2, sticky='e', padx=(px(12), 0))
        Btn(acts, act, self._pick, app.th.f_btn_s, 'line', (13, 5)).pack(side='right')
        self.clear_btn = None
        if clearable:
            self.clear_btn = Btn(acts, '지우기', self.clear, app.th.f_btn_s,
                                 'ghost', (9, 5))
        if extra:
            Btn(acts, extra[0], extra[1], app.th.f_btn_s, 'ghost', (9, 5)).pack(
                side='right', padx=(0, px(6)))

        tk.Frame(outer.master, bg=RULE_2, height=hair()).pack(fill='x')

    def _pick(self):
        if self.pick_dir:
            p = filedialog.askdirectory(title='결과 저장 폴더')
        else:
            ft = ([('한글 문서', '*.hwpx'), ('모든 파일', '*.*')] if self.kind == 'hwpx'
                  else [('엑셀 파일', '*.xlsx *.xlsm *.xls'), ('모든 파일', '*.*')])
            p = filedialog.askopenfilename(title='파일 선택', filetypes=ft)
        if p:
            self.set(p)
            self.on_pick(p)

    def set(self, path, badge=''):
        self.value = path
        if path:
            txt = ellipsize(path)
            self.path.configure(text=(f'[{badge}]  {txt}' if badge else txt),
                                fg=GREY, font=self.app.th.f_path)
            if self.clear_btn:
                self.clear_btn.pack(side='right', padx=(0, px(6)))
        else:
            self.path.configure(text=self.hint, fg=GREY_2, font=self.app.th.f_hint)
            if self.clear_btn:
                self.clear_btn.pack_forget()

    def clear(self):
        self.set('')
        self.on_pick('')

    def flag_missing(self, filled):
        if self.required:
            self.edge.configure(bg=RULE if filled else VERM)


class TabRail(tk.Frame):
    """밑줄로 현재 판을 표시하는 활자 탭. 알약 모양을 쓰지 않는다."""

    def __init__(self, parent, th, tabs, on_change):
        super().__init__(parent, bg=PAPER)
        self.th, self.on_change = th, on_change
        self.items = {}
        self.current = tabs[0][0]
        row = tk.Frame(self, bg=PAPER)
        row.pack(fill='x')
        for key, label in tabs:
            cell = tk.Frame(row, bg=PAPER)
            cell.pack(side='left', padx=(0, px(26)))
            lab = tk.Label(cell, text=label, font=th.f_tab, bg=PAPER, fg=GREY_2,
                           cursor='hand2', pady=px(5))
            lab.pack()
            bar = tk.Frame(cell, bg=PAPER, height=px(2))
            bar.pack(fill='x')
            lab.bind('<Button-1>', lambda e, k=key: self.select(k))
            self.items[key] = {'lab': lab, 'bar': bar, 'on': True}
        tk.Frame(self, bg=RULE, height=hair()).pack(fill='x')
        # 생성 시점에는 그리기만 한다. 콜백을 부르면 아직 만들어지지 않은
        # 판(view)을 건드리게 된다 — 판 전환은 App이 준비를 마친 뒤 직접 호출한다.
        self._paint()

    def set_enabled(self, key, on):
        self.items[key]['on'] = on
        if not on and self.current == key:
            self.select(next(iter(self.items)))
        self._paint()

    def select(self, key):
        if not self.items[key]['on']:
            return
        self.current = key
        self._paint()
        self.on_change(key)

    def _paint(self):
        for key, it in self.items.items():
            on, cur = it['on'], (key == self.current)
            it['lab'].configure(fg=INK if cur else (GREY if on else PAPER_3),
                                cursor='hand2' if on else 'arrow')
            it['bar'].configure(bg=INK if cur else PAPER)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('국외지원사항 자동 통계산출')
        self.configure(bg=PAPER)
        self.th = Theme(self)           # 화면 배율을 재서 px()에 반영한다
        self._size_window()
        self._set_icon()

        self.res_path = ''
        self.prj_path = ''
        self.map_path = resources.resource_path(MAP_NAME)
        self.tpl_path = resources.resource_path(TPL_NAME)
        self.out_dir = app_dir()
        self.do_pre = True
        self.extra_open = False
        self.last = None                # 마지막 산출 결과 (S, 파일들, 시각)

        # 창 맨 위 판식 띠 — 이 화면에서 주홍이 처음 나타나는 자리
        tk.Frame(self, bg=VERM, height=px(3)).pack(fill='x')
        self._build_masthead()
        self._build_footer()            # side='bottom' — 먼저 자리를 잡아야 밀리지 않는다

        self.stack = tk.Frame(self, bg=PAPER)
        self.stack.pack(fill='both', expand=True)

        self.view_run = tk.Frame(self.stack, bg=PAPER)
        wrap = tk.Frame(self.view_run, bg=PAPER)
        wrap.pack(fill='both', expand=True, padx=px(26))
        self._build_intake(wrap)
        self._build_run(wrap)
        self._build_log(wrap)

        self.view_dash = tk.Frame(self.stack, bg=PAPER)
        self.dash = Dashboard(self.view_dash, self.th)
        self.dash.pack(fill='both', expand=True, padx=(px(26), px(14)))

        self.tabs.set_enabled('dash', False)
        self._show('run')
        self._refresh()

    def _size_window(self):
        """창 크기를 배율에 맞추되 화면을 넘지 않게 한다.

        DPI 인식을 켜면 좌표가 실제 픽셀이 되므로, 1060×880을 그대로 곱하면
        150% 배율의 1920×1080 노트북에서는 세로가 화면을 넘어간다.
        그래서 화면에서 여백을 뺀 크기로 잘라 맞추고, 가운데에 놓는다.
        """
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(px(1060), sw - px(60))
        h = min(px(880), sh - px(90))
        x, y = max((sw - w) // 2, 0), max((sh - h) // 3, 0)
        self.geometry(f'{w}x{h}+{x}+{y}')
        self.minsize(min(px(900), w), min(px(620), h))

    # ── 표제부 ──
    def _set_icon(self):
        try:
            ico = resources.resource_path('app_icon.ico')
            if sys.platform == 'win32' and ico:
                self.iconbitmap(ico)
            else:
                png = resources.resource_path('app_icon.png')
                if png:
                    self._icon = tk.PhotoImage(file=png)
                    self.iconphoto(True, self._icon)
        except Exception:
            pass

    def _build_masthead(self):
        th = self.th
        head = tk.Frame(self, bg=PAPER)
        head.pack(fill='x', padx=px(26), pady=(px(16), 0))

        BookMark(head, 32).pack(side='left', padx=(0, px(14)))
        t = tk.Frame(head, bg=PAPER)
        t.pack(side='left')
        tk.Label(t, text='국외지원사항 자동 통계산출', font=th.f_masthead,
                 bg=PAPER, fg=INK).pack(anchor='w')
        tk.Label(t, text='※ NRI 신고내역을 기반으로 보고서 산출',
                 font=th.f_deck, bg=PAPER, fg=GREY).pack(anchor='w', pady=(px(1), 0))

        right = tk.Frame(head, bg=PAPER)
        right.pack(side='right', anchor='ne')
        self.bar_note = tk.Label(right, text='', font=th.f_edition, bg=PAPER, fg=GREY)
        self.bar_note.pack(anchor='e')
        tk.Label(right, text=spaced(VERSION.upper()), font=th.f_edition,
                 bg=PAPER, fg=GREY_2).pack(anchor='e', pady=(px(2), 0))

        tk.Frame(self, bg=INK, height=hair()).pack(fill='x', padx=px(26),
                                                   pady=(px(12), 0))
        self.tabs = TabRail(self, th, [('run', '산출'), ('dash', '대시보드')],
                            self._show)
        self.tabs.pack(fill='x', padx=px(26))

    def _show(self, key):
        for v in (self.view_run, self.view_dash):
            v.pack_forget()
        (self.view_run if key == 'run' else self.view_dash).pack(
            fill='both', expand=True)

    # ── 입력 ──
    def _build_intake(self, parent):
        th = self.th
        eyebrow(parent, th, '입력', top=16)
        box = tk.Frame(parent, bg=PAPER)
        box.pack(fill='x')
        tk.Frame(box, bg=INK, height=hair()).pack(fill='x')

        req = tk.Frame(box, bg=PAPER)
        req.pack(fill='x')
        self.s_res = Slot(self, req, '필수', '연구자 raw',
                          '연구자 신고내역 목록 · xlsx', self._set_res, required=True)
        self.s_prj = Slot(self, req, '필수', '과제 raw',
                          '과제 매핑 신고내역 목록 · xlsx', self._set_prj, required=True)

        self.extra = tk.Frame(box, bg=PAPER)
        self.s_map = Slot(self, self.extra, '내장', '매핑테이블',
                          '기관별칭 · 민감국가 · 소속정규화 · 전처리규칙 · 유형규칙',
                          self._set_map, clearable=False, act='바꾸기')
        # 두 자원은 항상 내장본으로 되돌아가므로 '지우기'가 뜻을 갖지 않는다
        self.s_tpl = Slot(self, self.extra, '내장', '표준보고양식',
                          '이 양식에 값을 채워 한글 보고서를 만듭니다',
                          self._set_tpl, clearable=False, act='바꾸기', kind='hwpx')
        self.s_out = Slot(self, self.extra, '선택', '결과 저장 폴더',
                          '지정하지 않으면 프로그램 폴더에 저장합니다',
                          self._set_out, pick_dir=True, clearable=False, act='바꾸기')

        # 내려받기 안내 — 내장본을 고쳐 쓰는 경로를 여기서만 설명한다
        guide = tk.Frame(self.extra, bg=PAPER_2)
        guide.pack(fill='x')
        inner = tk.Frame(guide, bg=PAPER_2)
        inner.pack(fill='x', padx=px(14), pady=px(10))
        tk.Label(inner, text='양식과 매핑테이블은 프로그램 안에 들어 있습니다. '
                             '고쳐 쓰려면 내려받아 수정하세요 — 단, 프로그램과 동일 경로에 두면 '
                             '그 파일을 사용합니다.',
                 font=th.f_small, bg=PAPER_2, fg=GREY, anchor='w',
                 justify='left', wraplength=px(620)).pack(side='left', fill='x',
                                                          expand=True)
        Btn(inner, '양식·테이블 내려받기', self._export, th.f_btn_s, 'line', (12, 5),
            bg=PAPER_2).pack(side='right', padx=(px(12), 0))

        self.more = tk.Label(box, text='›  양식 · 매핑테이블 · 저장폴더',
                             font=th.f_body, bg=PAPER, fg=GREY, cursor='hand2',
                             anchor='w', pady=px(7))
        self.more.pack(fill='x')
        self.more.bind('<Button-1>', lambda e: self._toggle_extra())
        self.more.bind('<Enter>', lambda e: self.more.configure(fg=INK))
        self.more.bind('<Leave>', lambda e: self.more.configure(fg=GREY))

        self.s_out.set(self.out_dir)
        self._refresh_assets()

    def _refresh_assets(self):
        """내장본·수정본·직접지정 중 어느 쪽을 쓰는지 경로 앞에 표시한다."""
        for slot, name, attr in ((self.s_map, MAP_NAME, 'map_path'),
                                 (self.s_tpl, TPL_NAME, 'tpl_path')):
            cur = getattr(self, attr)
            if not (cur and os.path.exists(cur)):
                slot.set('')
                continue
            same = os.path.abspath(cur)
            side = os.path.abspath(os.path.join(app_dir(), name))
            inner = os.path.abspath(os.path.join(resources.bundle_dir(), name))
            if same == inner:
                # 소스로 실행하면 app_dir과 bundle_dir이 같은 폴더다.
                # 그 파일이 곧 내장될 원본이므로 '수정본'이라 하면 오해가 된다.
                badge = '내장'
            elif same == side:
                badge = '수정본'
            else:
                badge = '지정'
            slot.set(cur, badge)

    def _toggle_extra(self):
        self.extra_open = not self.extra_open
        if self.extra_open:
            self.extra.pack(fill='x', before=self.more)
            self.more.configure(text='⌄  선택 입력 접기')
        else:
            self.extra.pack_forget()
            self.more.configure(text='›  양식 · 매핑테이블 · 저장폴더')

    # ── 실행 줄 ──
    def _build_run(self, parent):
        th = self.th
        row = tk.Frame(parent, bg=PAPER)
        row.pack(fill='x', pady=(px(18), 0))
        self.run_btn = Btn(row, '통계 산출 실행', self.run, th.f_btn, 'solid', (24, 11))
        self.run_btn.pack(side='left')

        opt = tk.Frame(row, bg=PAPER)
        opt.pack(side='left', padx=(px(16), 0))
        self.chk = tk.Canvas(opt, width=px(14), height=px(14), bg=PAPER,
                             highlightthickness=0, cursor='hand2')
        self.chk.pack(side='left')
        lab = tk.Label(opt, text='raw 전처리', font=th.f_body, bg=PAPER,
                       fg=INK, cursor='hand2')
        lab.pack(side='left', padx=(px(7), 0))
        for w in (self.chk, lab):
            w.bind('<Button-1>', lambda e: self._toggle_pre())
        self._draw_chk()

        prog = tk.Frame(row, bg=PAPER)
        prog.pack(side='left', fill='x', expand=True, padx=(px(20), 0))
        self.track = tk.Canvas(prog, height=px(2), bg=PAPER_3, highlightthickness=0)
        self.track.pack(fill='x')
        self.fill = self.track.create_rectangle(0, 0, 0, px(2), fill=INK, width=0)
        self.ptext = tk.Label(prog, text='', font=th.f_small, bg=PAPER, fg=GREY,
                              anchor='w')
        self.ptext.pack(fill='x', pady=(px(6), 0))

    def _draw_chk(self):
        c = self.chk
        c.delete('all')
        s = px(14)
        c.create_rectangle(hair(), hair(), s - hair(), s - hair(),
                           outline=INK if self.do_pre else RULE,
                           fill=INK if self.do_pre else PAPER, width=hair())
        if self.do_pre:
            # 배율에 따라 체크 표시도 같이 커진다
            c.create_line(s * 0.22, s * 0.52, s * 0.43, s * 0.73,
                          fill=PAPER, width=px(2))
            c.create_line(s * 0.43, s * 0.73, s * 0.78, s * 0.28,
                          fill=PAPER, width=px(2))

    def _toggle_pre(self):
        self.do_pre = not self.do_pre
        self._draw_chk()

    def _progress(self, frac, text):
        w = max(self.track.winfo_width(), 1)
        self.track.coords(self.fill, 0, 0, int(w * frac), px(2))
        self.ptext.configure(text=text)
        self.update()

    # ── 처리 내역 ──
    def _build_log(self, parent):
        th = self.th
        eyebrow(parent, th, '처리 내역')
        box = tk.Frame(parent, bg=PAPER, highlightthickness=hair(),
                       highlightbackground=RULE_2)
        box.pack(fill='both', expand=True, pady=(0, px(4)))
        self.log_w = tk.Text(box, font=th.f_log, bg=PAPER, fg=GREY, bd=0,
                             padx=px(13), pady=px(11), state='disabled', wrap='word',
                             height=6, selectbackground=PAPER_2, insertbackground=INK)
        self.log_w.pack(fill='both', expand=True)
        self.log_w.tag_configure('ink', foreground=INK)
        self.log_w.tag_configure('bad', foreground=VERM)
        self.log_w.tag_configure('ok', foreground=GREEN)
        self.log_w.tag_configure('dim', foreground=GREY_2)

    def _log(self, msg, tag=None):
        self.log_w.configure(state='normal')
        self.log_w.insert('end', f'{datetime.datetime.now():%H:%M:%S}  ', ('dim',))
        self.log_w.insert('end', msg + '\n', (tag,) if tag else ())
        self.log_w.see('end')
        self.log_w.configure(state='disabled')
        self.update()

    # ── 배포자 표기 ──
    def _build_footer(self):
        th = self.th
        f = tk.Frame(self, bg=PAPER)
        f.pack(side='bottom', fill='x', padx=px(26), pady=(px(6), px(12)))
        tk.Frame(f, bg=RULE_2, height=hair()).pack(fill='x', pady=(0, px(7)))
        row = tk.Frame(f, bg=PAPER)
        row.pack(fill='x')
        tk.Label(row, text='Powered by MIN', font=th.f_num_b,
                 bg=PAPER, fg=INK).pack(side='left')
        tk.Label(row, text='min@kistep.re.kr', font=th.f_body,
                 bg=PAPER, fg=GREY_2).pack(side='right')

    # ── 입력 반영 ──
    def _set_res(self, p):
        self.res_path = p
        # 두 시트가 한 파일에 있는 경우가 많다 — 과제 자리를 비워 두면 같이 채운다
        if p and not self.prj_path:
            self.prj_path = p
            self.s_prj.set(p)
        self._refresh()

    def _set_prj(self, p):
        self.prj_path = p
        self._refresh()

    def _set_map(self, p):
        self.map_path = p or resources.resource_path(MAP_NAME)
        self._refresh_assets()
        self._refresh()

    def _set_tpl(self, p):
        self.tpl_path = p or resources.resource_path(TPL_NAME)
        self._refresh_assets()
        self._refresh()

    def _set_out(self, p):
        self.out_dir = p or app_dir()

    def _refresh(self):
        have_map = bool(self.map_path) and os.path.exists(self.map_path)
        ready = bool(self.res_path and self.prj_path and have_map)
        self.run_btn.set_enabled(ready)
        self.s_res.flag_missing(bool(self.res_path))
        self.s_prj.flag_missing(bool(self.prj_path))
        if not self.res_path or not self.prj_path:
            msg = 'raw 파일 두 개를 지정하면 실행할 수 있습니다'
        elif not have_map:
            msg = '매핑테이블을 찾을 수 없습니다 — 선택 입력에서 지정하세요'
        else:
            hwpx = bool(self.tpl_path) and os.path.exists(self.tpl_path)
            msg = ('엑셀과 한글 보고서를 함께 만듭니다' if hwpx
                   else '양식이 없어 엑셀만 만듭니다')
        self.ptext.configure(text=msg)
        n = sum(1 for p in (self.res_path, self.prj_path) if p)
        self.bar_note.configure(text=f'입력 {n}/2' if n < 2 else '입력 완료')

    # ── 내장 자원 내려받기 ──
    def _export(self):
        dest = filedialog.askdirectory(title='양식·매핑테이블을 내려받을 폴더',
                                       initialdir=self.out_dir or app_dir())
        if not dest:
            return
        existing = resources.existing_overrides(dest)
        overwrite = False
        if existing:
            overwrite = messagebox.askyesno(
                '이미 있는 파일',
                f'{", ".join(existing)}\n\n이 폴더에 이미 있습니다. '
                f'덮어쓰면 고쳐 두신 내용이 사라집니다.\n\n'
                f'덮어쓸까요?  (아니오를 고르면 없는 파일만 내려받습니다)')
        for name, status, path in resources.export_resources(dest, overwrite=overwrite):
            tag = 'ink' if status == '내려받음' else (
                'dim' if status == '이미 있음' else 'bad')
            self._log(f'{name} — {status}', tag)
        if os.path.abspath(dest) == os.path.abspath(app_dir()):
            self.map_path = resources.resource_path(MAP_NAME)
            self.tpl_path = resources.resource_path(TPL_NAME)
            self._refresh_assets()
            self._log('프로그램 폴더에 내려받았습니다 — 다음 실행부터 이 파일을 씁니다', 'ok')
        self._refresh()

    # ── 실행 ──
    def run(self):
        try:
            self.run_btn.set_enabled(False)
            self._progress(0.05, '매핑테이블 읽는 중')
            org_alias, country_map, aff_norm = load_mappings(self.map_path)
            rules = load_rules(self.map_path)
            trules = load_type_rules(self.map_path)
            self._log(f'매핑테이블 — 기관별칭 {len(org_alias)} · 민감국가 {len(country_map)} · '
                      f'소속정규화 {len(aff_norm)} · 유형 {len(trules)}개')
            conflicts = check_mapping_conflicts(self.map_path)
            if conflicts:
                self._log(f'매핑테이블에 별칭 충돌 {len(conflicts)}건 — 한 기관이 둘로 '
                          f'나뉘어 집계될 수 있습니다', 'bad')
                for sh, a, bs in conflicts[:5]:
                    self._log(f'  [{sh}] {a} → {" / ".join(bs)}', 'bad')
            self._log(f'전처리 {"실행" if self.do_pre else "건너뜀"}'
                      + (f' — 제거 기준값 {sum(len(v) for v in rules.values())}건'
                         if self.do_pre else ''))

            self._progress(0.2, '연구자 raw 읽는 중')
            res, log_r = load_researcher_raw(self.res_path, rules, self.do_pre)
            self._report_pre(log_r)

            self._progress(0.4, '과제 raw 읽는 중')
            prj, log_p = load_project_raw(self.prj_path, rules, self.do_pre)
            self._report_pre(log_p)

            # 산출기준일은 raw 파일명에 적힌 날짜를 쓴다. 며칠 뒤에 다시 돌려도
            # 같은 raw면 같은 보고서가 나오게 하기 위한 것이다.
            base_date, src = resolve_base_date(self.res_path, self.prj_path)
            if src:
                self._log(f'산출기준일 {src}', 'ink')
            else:
                self._log(f'raw 파일명에서 날짜를 찾지 못해 오늘 날짜를 산출기준일로 '
                          f'씁니다 — {base_date:%Y-%m-%d}', 'bad')

            self._progress(0.6, '통계 산출 중')
            S = compute_stats(res, prj, org_alias, country_map, aff_norm, trules,
                              base_date=base_date)
            S['전처리내역'] = [log_r, log_p]

            stamp = f'{datetime.datetime.now():%Y%m%d_%H%M}'
            out = os.path.join(self.out_dir, f'통계분석결과_{stamp}.xlsx')
            self._progress(0.75, '엑셀 리포트 만드는 중')
            build_report(S, out)
            self._log(f'엑셀 — {os.path.basename(out)}', 'ink')
            made = [os.path.basename(out)]

            hwpx_out = None
            if self.tpl_path and os.path.exists(self.tpl_path):
                self._progress(0.9, '한글 보고서 만드는 중')
                try:
                    hwpx_out = os.path.join(
                        self.out_dir, f'국외지원사항_등록보고현황_{stamp}.hwpx')
                    for w in build_hwpx(S, self.tpl_path, hwpx_out,
                                        base_date=base_date):
                        self._log(w, 'bad')
                    self._log(f'한글 — {os.path.basename(hwpx_out)}', 'ink')
                    made.append(os.path.basename(hwpx_out))
                except Exception as e:
                    hwpx_out = None
                    self._log(f'한글 보고서를 만들지 못했습니다 — {e}', 'bad')
                    self._log('엑셀 리포트는 정상 생성되었습니다')
            else:
                self._log('양식이 없어 엑셀만 만들었습니다', 'dim')

            self._progress(1.0, f'완료 · {datetime.datetime.now():%H:%M}')
            self.last = (S, out, hwpx_out)

            # 대시보드를 채우고 그 판으로 넘긴다 — 결과를 곧바로 읽게 한다
            self.dash.build(S, made, stamp)
            self.tabs.set_enabled('dash', True)
            self.tabs.select('dash')
            self.dash.reveal()
            self._refresh()

            done = out + (f'\n{hwpx_out}' if hwpx_out else '')
            if messagebox.askyesno('완료',
                                   f'산출을 마쳤습니다.\n\n{done}\n\n지금 열어볼까요?'):
                self._open(out)
                if hwpx_out:
                    self._open(hwpx_out)
        except Exception as e:
            self._progress(0, '중단됨 — 처리 내역을 확인하세요')
            self._refresh()
            self._log(str(e).splitlines()[0] if str(e) else e.__class__.__name__, 'bad')
            self._log(traceback.format_exc(), 'dim')
            messagebox.showerror('산출 중단', '처리 내역에 원인을 적었습니다.')

    @staticmethod
    def _open(path):
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            else:
                os.system(f'open "{path}"')
        except Exception:
            pass

    def _report_pre(self, lg):
        self._log(f"{lg['구분']} — 원본 {lg['원본건수']:,} → 정제 {lg['정제건수']:,} "
                  f"(제거 {lg['제거건수']:,}, {lg.get('열인식', '')})", 'ink')
        for step, _d, cnt in lg['단계']:
            if cnt:
                self._log(f'  {step} {cnt:,}건', 'dim')
        if lg['검토후보']:
            self._log(f"  검토 후보 {len(lg['검토후보'])}종 — [전처리 내역] 시트 확인", 'bad')


def _cli():
    """python 국외지원사항_통계산출.py 연구자.xlsx 과제.xlsx [출력.xlsx]"""
    mp = resources.resource_path(MAP_NAME)
    org_alias, country_map, aff_norm = load_mappings(mp)
    rules = load_rules(mp)
    trules = load_type_rules(mp)
    for sh, a, bs in check_mapping_conflicts(mp):
        print(f'  별칭 충돌 [{sh}] {a} → {" / ".join(bs)}')
    res, log_r = load_researcher_raw(sys.argv[1], rules, True)
    prj, log_p = load_project_raw(sys.argv[2], rules, True)
    for lg in (log_r, log_p):
        print(f"{lg['구분']}: 원본 {lg['원본건수']:,} → 정제 {lg['정제건수']:,} "
              f"(제거 {lg['제거건수']:,})")
    base_date, src = resolve_base_date(sys.argv[1], sys.argv[2])
    print('산출기준일:', src or f'{base_date:%Y-%m-%d} (파일명에서 찾지 못해 오늘 날짜)')
    S = compute_stats(res, prj, org_alias, country_map, aff_norm, trules,
                      base_date=base_date)
    S['전처리내역'] = [log_r, log_p]
    out = (sys.argv[3] if len(sys.argv) > 3
           else f'통계분석결과_{datetime.datetime.now():%Y%m%d}.xlsx')
    build_report(S, out)
    print('완료:', out)
    tpl = resources.resource_path(TPL_NAME)
    if tpl:
        h = out.rsplit('.', 1)[0] + '.hwpx'
        for w in build_hwpx(S, tpl, h, base_date=base_date):
            print('  경고:', w)
        print('완료:', h)


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        _cli()
    else:
        # Tk() 생성 전에 켜야 한다. 켠 뒤에는 tk가 화면 DPI를 스스로 읽어
        # 포인트로 지정한 활자를 확대하고, 픽셀 상수는 px()가 맞춘다.
        enable_dpi_awareness()
        App().mainloop()
