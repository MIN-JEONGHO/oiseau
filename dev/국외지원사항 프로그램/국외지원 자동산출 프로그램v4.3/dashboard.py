# -*- coding: utf-8 -*-
"""대시보드 — 산출 결과를 파일 열지 않고 화면에서 읽는 판.

차트는 tk.Canvas에 직접 그린다. matplotlib을 쓰면 exe가 39MB에서 100MB를
넘겨 '한 개만 옮기는 배포'라는 목적과 어긋나기 때문이다. 대신 이 판에 필요한
네 가지 형태만 손으로 그린다.

    HBars     가로 막대 — 국가·유형·기관 순위
    VBars     세로 막대 — 월별·연도별 추이
    SplitBar  100% 분할 막대 — 산학연·과제 관련성
    KPI       수치 타일

색은 먹빛 3단 계조뿐이다(1위·중위·하위). 주홍은 연구보안 우려와 정합성
불일치에만 쓴다. 순위가 색이 아니라 계조로 읽히면 표가 조용해진다.

대시보드를 열면 막대가 0에서 자란다. 차트마다 시작을 조금씩 늦춰
왼쪽에서 오른쪽으로 판이 차오르게 한다 — 이 화면에서 유일한 움직임이다.
"""
import tkinter as tk
import tkinter.font as tkfont

from theme import (PAPER, PAPER_2, PAPER_3, INK, INK_2, GREY, GREY_2,
                   RULE, RULE_2, VERM, VERM_2, GREEN, BAR, ease_out, spaced,
                   px, hair)

FRAMES = 20          # 애니메이션 프레임 수
FRAME_MS = 16


def fmt(n):
    return f'{n:,}'


def fit(font, text, px):
    """글자 수가 아니라 실제 폭으로 자른다.

    기관명은 한글·영문·괄호가 섞여 글자 수로 자르면 폭이 들쭉날쭉해
    막대 영역을 침범한다(예: 'AFOSR(미 공군과학연구국)').
    """
    s = str(text or '')
    if px <= 0 or font.measure(s) <= px:
        return s
    ell = font.measure('…')
    while s and font.measure(s) + ell > px:
        s = s[:-1]
    return s + '…'


def grade(rank, total):
    """순위 → 먹빛 계조. 값이 큰 것이 짙다.

    행 순서가 아니라 값의 순위로 매긴다. 유형별처럼 규칙 순서로 나열되는
    표에서는 행 순서로 칠하면 최대값이 오히려 옅어진다.
    """
    if rank == 0:
        return BAR[0]
    return BAR[1] if rank < max(3, total // 2) else BAR[2]


def ranks_of(values):
    """값 → 순위(0이 최대). 동점은 먼저 나온 쪽이 앞선다."""
    order = sorted(range(len(values)), key=lambda i: (-values[i], i))
    out = [0] * len(values)
    for r, i in enumerate(order):
        out[i] = r
    return out


class Animated(tk.Canvas):
    """0→1 진행값을 받아 다시 그리는 캔버스 기반 도형."""

    def __init__(self, parent, height, bg=PAPER):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0)
        self._prog = 0.0
        self._job = None
        self.bind('<Configure>', lambda e: self._render(self._prog))

    def _render(self, prog):
        raise NotImplementedError

    def animate(self, delay=0):
        self.stop()
        self._prog = 0.0
        self._render(0.0)
        self._job = self.after(max(delay, 1), lambda: self._step(0))

    def _step(self, i):
        if not self.winfo_exists():
            return
        t = min((i + 1) / FRAMES, 1.0)
        self._prog = ease_out(t)
        self._render(self._prog)
        if t < 1.0:
            self._job = self.after(FRAME_MS, lambda: self._step(i + 1))
        else:
            self._job = None

    def show_instantly(self):
        self.stop()
        self._prog = 1.0
        self._render(1.0)

    def stop(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None


class HBars(Animated):
    """가로 막대. rows=[(라벨, 값, 꼬리말)] — 값 기준 상대 길이."""

    def __init__(self, parent, th, rows, label_w=132, row_h=22, note_w=0,
                 accent=None, total=None):
        self.th, self.rows = th, list(rows)
        self.label_w, self.row_h, self.note_w = px(label_w), px(row_h), px(note_w) if note_w else 0
        self.accent = accent or set()       # 주홍으로 그릴 라벨 집합
        self.total = total
        self._font = None
        self._rank = ranks_of([v for _, v, _ in self.rows])
        super().__init__(parent, height=max(len(self.rows), 1) * self.row_h + px(4))

    def _render(self, prog):
        self.delete('all')
        W = self.winfo_width()
        if W < px(60) or not self.rows:
            return
        if self._font is None:
            self._font = tkfont.Font(font=self.th.f_body)
        vmax = max([v for _, v, _ in self.rows] + [1])
        val_w = px(58)
        x0 = self.label_w
        x1 = W - val_w - self.note_w
        n = len(self.rows)
        bh = px(9)
        for i, (label, val, note) in enumerate(self.rows):
            cy = i * self.row_h + self.row_h / 2 + px(2)
            hot = label in self.accent
            # 라벨 — 막대 영역을 침범하지 않도록 실제 폭으로 자른다
            self.create_text(0, cy, text=fit(self._font, label, self.label_w - px(10)),
                             anchor='w', font=self.th.f_body,
                             fill=VERM if hot else INK)
            # 트랙 (아주 흐린 실선)
            self.create_line(x0, cy, x1, cy, fill=RULE_2, width=hair())
            # 막대
            bw = (x1 - x0) * (val / vmax) * prog
            if bw >= 1:
                self.create_rectangle(x0, cy - bh / 2, x0 + bw, cy + bh / 2,
                                      fill=VERM if hot else grade(self._rank[i], n),
                                      width=0)
            # 값
            self.create_text(W - self.note_w, cy, text=fmt(val), anchor='e',
                             font=self.th.f_num_b, fill=VERM if hot else INK)
            if note:
                self.create_text(W, cy, text=note, anchor='e',
                                 font=self.th.f_small, fill=GREY)


class VBars(Animated):
    """세로 막대. bars=[(축라벨, 값, 구분선여부, 구간라벨)]"""

    def __init__(self, parent, th, bars, height=136):
        self.th, self.bars = th, list(bars)
        super().__init__(parent, height=px(height))

    def _render(self, prog):
        self.delete('all')
        W, H = self.winfo_width(), self.winfo_height()
        if W < px(80) or not self.bars:
            return
        pad_l, pad_r = px(4), px(4)
        base = H - px(22)           # 축선
        top = px(30)                # 연도 표기 자리를 위에 비워 둔다
        vmax = max([v for _, v, _, _ in self.bars] + [1])
        n = len(self.bars)
        slot = (W - pad_l - pad_r) / n
        bw = min(slot * 0.62, px(26))
        # 축선
        self.create_line(pad_l, base, W - pad_r, base, fill=RULE, width=hair())
        for i, (lab, val, sep, seclab) in enumerate(self.bars):
            cx = pad_l + slot * (i + 0.5)
            if sep and i:
                self.create_line(cx - slot / 2, top - px(14), cx - slot / 2, base,
                                 fill=RULE, dash=(2, 3), width=hair())
            if seclab:
                # 막대 위 값 표기와 겹치지 않도록 눈금 윗단에 따로 얹는다
                self.create_text(max(cx - slot / 2 + px(3), pad_l), px(2), text=seclab,
                                 anchor='nw', font=self.th.f_edition, fill=GREY)
            h = (base - top) * (val / vmax) * prog
            if h >= 1:
                self.create_rectangle(cx - bw / 2, base - h, cx + bw / 2, base,
                                      fill=INK if val == vmax else INK_2, width=0)
            # 축 라벨
            self.create_text(cx, base + px(8), text=lab, anchor='n',
                             font=self.th.f_small, fill=GREY)
            # 값 — 자리가 될 때만
            if slot >= px(22) and val and prog > 0.6:
                self.create_text(cx, base - h - px(4), text=fmt(val), anchor='s',
                                 font=self.th.f_small, fill=GREY if val != vmax else INK)


class SplitBar(Animated):
    """100% 분할 막대 + 아래 범례. segs=[(라벨, 값)]"""

    def __init__(self, parent, th, segs, accent=None):
        self.th, self.segs = th, [(k, v) for k, v in segs]
        self.accent = accent or set()
        self._rank = ranks_of([v for _, v in self.segs])
        super().__init__(parent, height=px(24) + len(self.segs) * px(18) + px(4))

    def _render(self, prog):
        self.delete('all')
        W = self.winfo_width()
        if W < px(80) or not self.segs:
            return
        tot = sum(v for _, v in self.segs) or 1
        bh = px(16)
        x = 0.0
        for i, (lab, val) in enumerate(self.segs):
            w = W * (val / tot) * prog
            hot = lab in self.accent
            col = VERM if hot else grade(self._rank[i], len(self.segs))
            if w >= 1:
                self.create_rectangle(x, 0, x + w, bh, fill=col, width=0)
                if w > px(34):
                    self.create_text(x + w / 2, bh / 2,
                                     text=f'{val / tot * 100:.0f}%', anchor='center',
                                     font=self.th.f_small,
                                     fill=PAPER if (self._rank[i] < 2 or hot) else INK)
            x += w
        # 범례 — 한 단으로 세운다. 두 단으로 두면 값이 다음 칸 라벨을 침범한다.
        for i, (lab, val) in enumerate(self.segs):
            ly = bh + px(14) + i * px(18)
            hot = lab in self.accent
            col = VERM if hot else grade(self._rank[i], len(self.segs))
            self.create_rectangle(0, ly - px(4), px(8), ly + px(4), fill=col, width=0)
            self.create_text(px(14), ly, text=lab, anchor='w',
                             font=self.th.f_small, fill=VERM if hot else INK)
            self.create_text(W - px(46), ly, text=fmt(val), anchor='e',
                             font=self.th.f_num_b, fill=VERM if hot else INK)
            self.create_text(W, ly, text=f'{val / tot * 100:.1f}%', anchor='e',
                             font=self.th.f_small, fill=GREY)
            if i < len(self.segs) - 1:
                self.create_line(0, ly + px(9), W, ly + px(9), fill=RULE_2, width=hair())


class ScrollArea(tk.Frame):
    """세로 스크롤 영역 + 얇은 먹빛 손잡이. 휠·드래그 모두 받는다."""

    def __init__(self, parent, bg=PAPER):
        super().__init__(parent, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.cv.pack(side='left', fill='both', expand=True)
        self.rail = tk.Canvas(self, width=px(6), bg=bg, highlightthickness=0, bd=0,
                              cursor='hand2')
        self.rail.pack(side='right', fill='y')
        self.inner = tk.Frame(self.cv, bg=bg)
        self._win = self.cv.create_window(0, 0, window=self.inner, anchor='nw')
        self._thumb = None
        self._drag = None

        self.inner.bind('<Configure>', self._on_inner)
        self.cv.bind('<Configure>', self._on_outer)
        for w in (self.cv, self.inner, self.rail):
            w.bind('<MouseWheel>', self._wheel)
        self.rail.bind('<Button-1>', self._rail_press)
        self.rail.bind('<B1-Motion>', self._rail_drag)
        self.rail.bind('<ButtonRelease-1>', lambda e: setattr(self, '_drag', None))

    # 자식 위젯이 휠 이벤트를 먹지 않도록 재귀 바인딩
    def bind_wheel(self, widget):
        widget.bind('<MouseWheel>', self._wheel)
        for ch in widget.winfo_children():
            self.bind_wheel(ch)

    def _on_inner(self, e=None):
        self.cv.configure(scrollregion=self.cv.bbox('all'))
        self._draw_thumb()

    def _on_outer(self, e):
        self.cv.itemconfigure(self._win, width=e.width)
        self._draw_thumb()

    def _wheel(self, e):
        if self._span() <= 0:
            return
        self.cv.yview_scroll(-1 * int(e.delta / 60), 'units')
        self._draw_thumb()
        return 'break'

    def _span(self):
        bb = self.cv.bbox('all')
        if not bb:
            return 0
        return max(bb[3] - self.cv.winfo_height(), 0)

    def _draw_thumb(self):
        self.rail.delete('all')
        H = self.rail.winfo_height()
        bb = self.cv.bbox('all')
        if not bb or H < px(20):
            return
        content = max(bb[3], 1)
        view = self.cv.winfo_height()
        if content <= view:
            return
        frac = view / content
        th = max(H * frac, px(24))
        top = (self.cv.yview()[0]) * H
        W = self.rail.winfo_width()
        self.rail.create_rectangle(W / 2 - hair(), 0, W / 2 + hair(), H,
                                   fill=RULE_2, width=0)
        self._thumb = self.rail.create_rectangle(0, top, W, top + th,
                                                 fill=GREY_2, width=0)

    def _rail_press(self, e):
        self._drag = e.y
        self._jump(e.y)

    def _rail_drag(self, e):
        self._jump(e.y)

    def _jump(self, y):
        H = max(self.rail.winfo_height(), 1)
        self.cv.yview_moveto(max(min(y / H, 1.0), 0.0))
        self._draw_thumb()

    def to_top(self):
        self.cv.yview_moveto(0)
        self._draw_thumb()


# ── 판 조립 도우미 ────────────────────────────────────────────
def section(parent, th, title, note=''):
    """구획 표제 — 세리프 제목 + 오른쪽 작은 주석 + 아래 먹빛 실선."""
    wrap = tk.Frame(parent, bg=PAPER)
    wrap.pack(fill='x', pady=(px(22), 0))
    head = tk.Frame(wrap, bg=PAPER)
    head.pack(fill='x')
    tk.Label(head, text=title, font=th.f_section, bg=PAPER, fg=INK).pack(side='left')
    if note:
        tk.Label(head, text=note, font=th.f_caption, bg=PAPER, fg=GREY).pack(
            side='right', pady=(px(4), 0))
    tk.Frame(wrap, bg=INK, height=hair()).pack(fill='x', pady=(px(5), 0))
    body = tk.Frame(wrap, bg=PAPER)
    body.pack(fill='x', pady=(px(10), 0))
    return body


def kpi_row(parent, th, items, bg=PAPER):
    """수치 타일 한 줄. items=[(값, 라벨, 주석|None, 강조여부)]"""
    grid = tk.Frame(parent, bg=bg)
    grid.pack(fill='x')
    for i, (val, label, sub, hot) in enumerate(items):
        grid.columnconfigure(i, weight=1, uniform='kpi')
        cell = tk.Frame(grid, bg=bg)
        cell.grid(row=0, column=i, sticky='nsew')
        pad = tk.Frame(cell, bg=bg)
        pad.pack(fill='x', padx=(0 if i == 0 else px(14), px(14)),
                 pady=(px(2), px(10)))
        tk.Label(pad, text=val, font=th.f_kpi, bg=bg,
                 fg=VERM if hot else INK, anchor='w').pack(anchor='w')
        tk.Label(pad, text=label, font=th.f_small, bg=bg, fg=GREY,
                 anchor='w').pack(anchor='w', pady=(px(1), 0))
        if sub:
            tk.Label(pad, text=sub, font=th.f_small, bg=bg, fg=GREY_2,
                     anchor='w').pack(anchor='w')
        if i < len(items) - 1:
            tk.Frame(cell, bg=RULE_2, width=hair()).place(relx=1.0, rely=0.08,
                                                          relheight=0.72, anchor='n')
    return grid


class Dashboard(tk.Frame):
    """산출 결과 판. build(S)로 채우고 reveal()로 막대를 자라게 한다."""

    def __init__(self, parent, th):
        super().__init__(parent, bg=PAPER)
        self.th = th
        self.area = ScrollArea(self, bg=PAPER)
        self.area.pack(fill='both', expand=True)
        self.body = self.area.inner
        self.charts = []
        self._empty()

    # ── 빈 판 ──
    def _empty(self):
        self.clear()
        box = tk.Frame(self.body, bg=PAPER)
        box.pack(fill='both', expand=True, pady=(px(90), 0))
        tk.Label(box, text='아직 산출한 결과가 없습니다', font=self.th.f_section,
                 bg=PAPER, fg=GREY).pack()
        tk.Label(box, text='[산출] 판에서 raw 파일 두 개를 지정하고 실행하면\n'
                           '이 자리에 통계가 펼쳐집니다.',
                 font=self.th.f_body, bg=PAPER, fg=GREY_2, justify='center').pack(
            pady=(px(8), 0))

    def clear(self):
        for c in self.charts:
            c.stop()
        self.charts = []
        for w in self.body.winfo_children():
            w.destroy()

    # ── 채우기 ──
    def build(self, S, out_files, stamp):
        self.clear()
        th = self.th
        B = tk.Frame(self.body, bg=PAPER)
        B.pack(fill='both', expand=True, padx=(px(2), px(12)))
        total = S['총건수'] or 1

        # ═══ 표제 — 등록 건수를 크게 하나만 세운다 ═══
        head = tk.Frame(B, bg=PAPER)
        head.pack(fill='x', pady=(px(16), 0))
        left = tk.Frame(head, bg=PAPER)
        left.pack(side='left')
        tk.Label(left, text=spaced('국외지원사항 등록'), font=th.f_eyebrow,
                 bg=PAPER, fg=GREY).pack(anchor='w')
        figure = tk.Frame(left, bg=PAPER)
        figure.pack(anchor='w', pady=(px(2), 0))
        tk.Label(figure, text=fmt(S['총건수']), font=th.f_hero, bg=PAPER,
                 fg=INK).pack(side='left')
        tk.Label(figure, text='건', font=th.f_body, bg=PAPER, fg=GREY).pack(
            side='left', anchor='s', pady=(0, px(9)), padx=(px(4), 0))

        right = tk.Frame(head, bg=PAPER)
        right.pack(side='right', anchor='se')
        for txt, fnt, col in (
                (f"산출기준일 {S.get('산출기준일', '')}", th.f_edition, GREY),
                (f"연구자 raw {fmt(S['총건수'])}건 · 과제 raw {fmt(S['총과제매핑건수'])}건",
                 th.f_small, GREY_2)):
            tk.Label(right, text=txt, font=fnt, bg=PAPER, fg=col).pack(anchor='e')
        for f in out_files:
            tk.Label(right, text=f, font=th.f_small, bg=PAPER, fg=GREY_2).pack(anchor='e')

        tk.Frame(B, bg=INK, height=px(2)).pack(fill='x', pady=(px(10), 0))

        # ═══ 주요 수치 ═══
        body = section(B, th, '주요 수치')
        sec = S['보안']['위험국가'] + S['보안']['민감국가']
        kpi_row(body, th, [
            (fmt(S['고유연구자수']), '연구자', f"연구책임자 {fmt(S['고유연책수'])}명", False),
            (fmt(S['국가수']), '지원·지급 국가', f"기관 {fmt(S['지원기관수'])}개", False),
            (fmt(S['고유과제수']), '보고된 과제', f"중복 제외", False),
            (fmt(S['미매핑신고수']), '과제매핑 미진행',
             f"연구자 {fmt(S['미매핑연구자수'])}명", False),
            (fmt(S.get('보고의무종료연구자수', 0)), '보고의무 종료',
             f"연책 {fmt(S.get('보고의무종료연책수', 0))} · "
             f"일반 {fmt(S.get('보고의무종료일반수', 0))}", False),
            (fmt(sec), '연구보안 우려',
             f"위험 {fmt(S['보안']['위험국가'])} · 민감 {fmt(S['보안']['민감국가'])}",
             bool(sec)),
        ])

        # ═══ 검산 ═══
        self._audit(section(B, th, '검산', '파일을 열지 않고 정합성을 대조합니다'), S)

        # ═══ 월별 추이 ═══
        months = S['월별'][-24:]
        if months:
            note = (f"NRI 등록일자 기준 · 날짜 인식 {fmt(S['날짜인식건수'])}건"
                    + (f" (최근 24개월)" if len(S['월별']) > 24 else ''))
            body = section(B, th, '등록 추이', note)
            bars, prev_y = [], None
            for ym, cnt in months:
                y, m = ym.split('-')
                new_year = (y != prev_y)
                bars.append((f'{int(m)}', cnt, new_year, f'’{y[2:]}' if new_year else ''))
                prev_y = y
            self._add(VBars(body, th, bars), body)

        # ═══ 국가 · 유형 (두 칸) ═══
        cols = self._two(B)
        body = section(cols[0], th, '상위 지원·지급 국가', 'Top 10')
        rows = [(k, v, f'{p * 100:.1f}%') for k, v, p in S['국가별'][:10]]
        self._add(HBars(body, th, rows, label_w=96, note_w=44), body)

        body = section(cols[1], th, '지원·지급 유형별', '중복 산출')
        trows = [(k, v, f'{v / total * 100:.0f}%') for k, v in S['유형별']]
        self._add(HBars(body, th, trows, label_w=104, note_w=40,
                        accent={'기타'} if dict(S['유형별']).get('기타') else None), body)

        # ═══ 소속 유형 · 과제 관련성 (두 칸) ═══
        cols = self._two(B)
        body = section(cols[0], th, '연구자 소속기관 유형', '산 · 학 · 연 · 기타')
        self._add(SplitBar(body, th, S['산학연']), body)

        body = section(cols[1], th, '과제와의 연관성',
                       f"판정 {fmt(S['관련성']['합계'])}건")
        rel = S['관련성']
        self._add(SplitBar(body, th, [('관련 있음', rel['관련있음']),
                                      ('관련 없음', rel['관련없음'])]), body)

        # ═══ 소속기관 · 지원기관 (두 칸) ═══
        cols = self._two(B)
        body = section(cols[0], th, '최다 수혜 소속기관', 'Top 10 · 별칭 통합')
        arows = [(a, c, f'{n}명') for a, c, n, _ in S['소속Top20'][:10]]
        self._add(HBars(body, th, arows, label_w=130, note_w=40), body)

        body = section(cols[1], th, '최다 지원기관', 'Top 10 · 별칭 통합')
        orows = [(o, c, nat or '') for o, nat, _, c in S['기관Top30'][:10]]
        self._add(HBars(body, th, orows, label_w=130, note_w=52), body)

        # ═══ 연구보안 ═══
        if sec:
            self._security(section(B, th, '연구보안 우려',
                                   'DOE 지정 위험·민감국가 수혜'), S)

        # ═══ 데이터 품질 경고 ═══
        if S.get('번호중복인물') or S.get('종료일미상건수'):
            self._quality(section(B, th, '확인이 필요한 항목'), S)

        # 배포자 표기는 창 바닥에 이미 한 번 있다 — 여기서는 판이 끝났음만 알린다
        tk.Frame(B, bg=RULE_2, height=hair()).pack(fill='x', pady=(px(26), 0))
        tk.Label(B, text=spaced('이상'), font=th.f_eyebrow, bg=PAPER,
                 fg=GREY_2).pack(anchor='w', pady=(px(6), px(18)))

        self.area.bind_wheel(self.body)
        self.area.to_top()

    # ── 구획 구현 ──
    def _two(self, parent):
        """좌우 두 칸. 가운데에 얇은 세로 실선을 둔다."""
        row = tk.Frame(parent, bg=PAPER)
        row.pack(fill='x')
        row.columnconfigure(0, weight=1, uniform='c')
        row.columnconfigure(2, weight=1, uniform='c')
        a = tk.Frame(row, bg=PAPER)
        a.grid(row=0, column=0, sticky='nsew', padx=(0, px(18)))
        tk.Frame(row, bg=RULE_2, width=hair()).grid(row=0, column=1, sticky='ns',
                                                    pady=(px(30), px(6)))
        b = tk.Frame(row, bg=PAPER)
        b.grid(row=0, column=2, sticky='nsew', padx=(px(18), 0))
        return a, b

    def _audit(self, body, S):
        th = self.th
        type_sum = sum(c for _, c in S['유형별'])
        rel = S['관련성']
        checks = [
            (type_sum >= S['총건수'],
             '유형 합계 ≥ 등록 건수',
             f"{fmt(type_sum)} ≥ {fmt(S['총건수'])}  (중복 {fmt(S['유형중복건수'])})"),
            (rel['합계'] == S['총과제매핑건수'],
             '관련성 판정 = 과제 건수',
             f"{fmt(rel['합계'])} / {fmt(S['총과제매핑건수'])}"),
        ]
        for i, (ok, label, detail) in enumerate(checks):
            row = tk.Frame(body, bg=PAPER)
            row.pack(fill='x', pady=(0 if i == 0 else px(1), 0))
            tk.Label(row, text='✓' if ok else '✕', font=th.f_mark, bg=PAPER,
                     fg=GREEN if ok else VERM, width=2, anchor='w').pack(side='left')
            tk.Label(row, text=label, font=th.f_body, bg=PAPER,
                     fg=INK if ok else VERM).pack(side='left')
            tk.Label(row, text=detail, font=th.f_num, bg=PAPER,
                     fg=GREY if ok else VERM).pack(side='right')

    def _security(self, body, S):
        th = self.th
        rows = []
        for lvl, key in (('위험국가', '위험국가'), ('민감국가', '민감국가')):
            if S['보안'][key]:
                rows.append((lvl, S['보안'][key],
                             f"{S['보안'][key] / (S['총건수'] or 1) * 100:.1f}%"))
        if rows:
            self._add(HBars(body, th, rows, label_w=96, note_w=44,
                            accent={'위험국가'}), body)
        det = S.get('보안세부')
        if det is not None and len(det):
            nat = ', '.join(sorted({str(v) for v in det['수혜국가'] if str(v).strip()})[:12])
            tk.Label(body, text=f'수혜 국가 — {nat}', font=th.f_small, bg=PAPER,
                     fg=GREY, anchor='w', wraplength=px(760), justify='left').pack(
                anchor='w', pady=(px(8), 0))
        tk.Label(body, text='세부 내역은 리포트의 [연구보안 세부] 시트에 전건 수록됩니다',
                 font=th.f_small, bg=PAPER, fg=GREY_2).pack(anchor='w', pady=(px(4), 0))

    def _quality(self, body, S):
        th = self.th
        notes = []
        if S.get('번호중복인물'):
            top = S['번호중복인물'][:3]
            notes.append(
                (True, f"하나의 국가연구자번호에 서로 다른 성명 {len(S['번호중복인물'])}건 — "
                       + ' / '.join(f'{rid}: {nm}' for rid, nm, _ in top)
                       + (' 외' if len(S['번호중복인물']) > 3 else '')
                       + '. 해당 건은 성명으로 분리 집계했습니다.'))
        if S.get('번호미기재건수'):
            notes.append((False, f"국가연구자번호 미기재 {fmt(S['번호미기재건수'])}건 — "
                                 f"성명으로 대체 집계했습니다."))
        if S.get('종료일미상건수'):
            notes.append((False, f"지원·지급 종료일 미상 {fmt(S['종료일미상건수'])}건 — "
                                 f"보고의무 종료로 보지 않았습니다."))
        for hot, txt in notes:
            row = tk.Frame(body, bg=PAPER)
            row.pack(fill='x', pady=(0, px(3)))
            tk.Label(row, text='!' if hot else '·', font=th.f_mark, bg=PAPER,
                     fg=VERM if hot else GREY_2, width=2, anchor='w').pack(
                side='left', anchor='n')
            tk.Label(row, text=txt, font=th.f_body, bg=PAPER,
                     fg=VERM if hot else GREY, anchor='w', justify='left',
                     wraplength=px(740)).pack(side='left', fill='x', expand=True)

    def _add(self, chart, parent):
        chart.pack(fill='x')
        self.charts.append(chart)
        return chart

    # ── 순차 노출 ──
    def reveal(self):
        for i, c in enumerate(self.charts):
            c.animate(delay=90 + i * 80)
