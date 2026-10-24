# -*- coding: utf-8 -*-
"""디자인 토큰과 공용 위젯 — 「편집 계기(Editorial Instrument)」

방향
  이 프로그램의 산출물은 한글 보고서다. 그래서 화면도 한글 문서의 활자로 짠다.
  표제에 함초롬바탕(한글 문서의 세리프)을 쓰고, 수치는 등폭 활자로 계기판처럼
  세우고, 구획은 자간을 벌린 작은 돋움과 실선으로만 나눈다.

  색은 먹빛 한 계열과 주홍(朱) 하나뿐이다. 주홍은 뜻이 있는 곳에만 쓴다.
  필수 입력 · 오류 · 정합성 불일치 · 연구보안 우려. 그 밖에는 전부 먹빛 계조다.
  통과는 조용히(먹빛 ✓), 실패는 크게(주홍) 알리는 편이 장부의 문법에 맞다.

  모서리는 각지고, 그림자는 없고, 선은 1px이다.
"""
import ctypes
import sys
import tkinter as tk
import tkinter.font as tkfont

# ── DPI ──────────────────────────────────────────────────────
# 창을 만들기 전에 DPI 인식을 켜야 한다. 켜지 않으면 윈도우가 창 전체를
# 비트맵으로 확대해, 이 디자인의 근간인 1px 실선과 작은 활자가 흐려진다.
# 켜면 tk가 화면 DPI를 스스로 읽어 'tk scaling'을 맞추므로 포인트로 지정한
# 활자는 자동으로 커진다. 반면 픽셀로 적은 여백·크기는 그대로 남으므로
# px()로 배율을 곱해 준다.
_K = 1.0


def enable_dpi_awareness():
    """Tk() 생성 전에 호출한다."""
    if sys.platform != 'win32':
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()       # 구형 윈도우
        except Exception:
            pass


def set_scale(k):
    global _K
    _K = max(k, 1.0)


def scale():
    return _K


def px(v):
    """논리 픽셀 → 화면 픽셀. 여백·막대 두께·캔버스 좌표에 쓴다."""
    return max(int(round(v * _K)), 1)


def hair():
    """실선 두께. 4K에서는 1픽셀이 가장 정확한 세선이 된다.
    배율이 아주 클 때만 2픽셀로 올려 너무 희미해지지 않게 한다."""
    return 1 if _K < 1.75 else 2


# ── 색 ───────────────────────────────────────────────────────
PAPER = '#FCFCFA'      # 종이 — 바탕
PAPER_2 = '#F4F4F0'    # 눌린 면 · 표 홀수행
PAPER_3 = '#E9E9E3'    # 비활성
INK = '#16181C'        # 먹빛 — 표제·주버튼·막대 1단
INK_2 = '#3C424B'      # 막대 2단
GREY = '#6A7078'       # 보조 글자
GREY_2 = '#A6ABB2'     # 자리표시자·막대 3단
RULE = '#D9DAD4'       # 실선
RULE_2 = '#EBEBE5'     # 흐린 실선
VERM = '#C8351B'       # 주홍 — 필수·오류·우려
VERM_2 = '#F3E1DD'     # 주홍 바탕
GREEN = '#1E5C43'      # 정합성 통과 (조용한 확인)

#: 막대 계조 — 1위·중위·하위
BAR = (INK, INK_2, GREY_2)


def pick(root, candidates):
    fams = set(tkfont.families(root))
    for c in candidates:
        if c in fams:
            return c
    return 'TkDefaultFont'


def spaced(s, gap=' '):
    """자간을 벌린 눈썹표제. tkinter에 자간 속성이 없어 글자 사이를 띄운다."""
    return gap.join(s)


def ellipsize(path, limit=58):
    if len(path) <= limit:
        return path
    return path[:limit // 2 - 2] + ' … ' + path[-(limit // 2 - 1):]


class Theme:
    """활자 체계 — 맑은 고딕 하나를 뼈대로 삼는다.

    여러 서체를 섞지 않으므로 위계는 **크기 · 굵기 · 자간**으로만 만든다.
      · 표제는 크고 굵게, 눈썹표제는 아주 작게 굵히고 자간을 벌린다
      · 수치는 굵기로 본문과 갈라 세운다
    등폭 활자는 기계값 두 곳에만 남긴다 — 파일 경로와 시각이 찍히는 처리 대장.
    사람이 읽는 이름·수치는 전부 맑은 고딕이다.
    """

    def __init__(self, root):
        self.sans = pick(root, ['맑은 고딕', 'Malgun Gothic', 'Noto Sans KR',
                                'Apple SD Gothic Neo', 'NanumGothic'])
        self.mono = pick(root, ['Cascadia Mono', 'Consolas', 'D2Coding',
                                'Noto Sans Mono CJK KR', 'Courier New'])

        S, M = self.sans, self.mono
        # 표제
        self.f_masthead = (S, 19, 'bold')
        self.f_deck = (S, 9)
        self.f_edition = (S, 8)
        # 구획
        self.f_eyebrow = (S, 8, 'bold')
        self.f_section = (S, 12, 'bold')
        self.f_caption = (S, 8)
        # 입력
        self.f_tag = (S, 8, 'bold')
        self.f_name = (S, 11, 'bold')
        self.f_hint = (S, 9)
        self.f_path = (M, 9)          # 기계값 — 등폭 유지
        # 조작
        self.f_btn = (S, 11, 'bold')
        self.f_btn_s = (S, 9)
        self.f_tab = (S, 12, 'bold')
        # 수치
        self.f_hero = (S, 38, 'bold')
        self.f_kpi = (S, 18, 'bold')
        self.f_num = (S, 10)
        self.f_num_b = (S, 10, 'bold')
        self.f_mark = (S, 10, 'bold')
        # 본문
        self.f_body = (S, 9)
        self.f_small = (S, 8)
        self.f_log = (M, 9)           # 기계값 — 등폭 유지

        # 화면 배율을 재서 픽셀 상수에 반영한다
        set_scale(root.winfo_fpixels('1i') / 96.0)
        self.k = scale()


class Btn(tk.Label):
    """각진 1px 테두리 버튼. kind='solid'|'line'|'ghost'|'verm'"""

    KINDS = {
        'solid': (INK, PAPER, INK),
        'line': (PAPER, INK, RULE),
        'ghost': (PAPER, GREY, PAPER),
        'verm': (PAPER, VERM, VERM),
    }

    def __init__(self, parent, text, command, font, kind='line', pad=(13, 5), bg=PAPER):
        self.kind = kind
        self._bg, self._fg, self._bd = self.KINDS[kind]
        if kind in ('ghost',):
            self._bg = bg
        super().__init__(parent, text=text, bg=self._bg, fg=self._fg,
                         font=font, padx=px(pad[0]), pady=px(pad[1]), cursor='hand2',
                         highlightthickness=hair(), highlightbackground=self._bd,
                         takefocus=1)
        self._cmd = command
        self._on = True
        for ev in ('<Button-1>', '<Return>', '<space>'):
            self.bind(ev, self._click)
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<FocusIn>', lambda e: self.configure(highlightbackground=INK))
        self.bind('<FocusOut>', lambda e: self.configure(highlightbackground=self._bd))

    def _click(self, e=None):
        if self._on:
            self._cmd()

    def _enter(self, e=None):
        if not self._on:
            return
        if self.kind == 'solid':
            self.configure(bg=INK_2, highlightbackground=INK_2)
        elif self.kind == 'ghost':
            self.configure(fg=INK, highlightbackground=RULE_2)
        elif self.kind == 'verm':
            self.configure(bg=VERM_2)
        else:
            self.configure(bg=PAPER_2, highlightbackground=GREY_2)

    def _leave(self, e=None):
        if self._on:
            self.configure(bg=self._bg, fg=self._fg, highlightbackground=self._bd)

    def set_enabled(self, on):
        self._on = on
        if on:
            self.configure(bg=self._bg, fg=self._fg, highlightbackground=self._bd,
                           cursor='hand2')
        else:
            if self.kind == 'solid':
                self.configure(bg=PAPER_3, fg=GREY_2, highlightbackground=PAPER_3)
            else:
                self.configure(bg=PAPER, fg=GREY_2, highlightbackground=RULE_2)
            self.configure(cursor='arrow')


def eyebrow(parent, th, text, top=18, bottom=8, bg=PAPER):
    """자간을 벌린 눈썹표제 + 이어지는 실선."""
    f = tk.Frame(parent, bg=bg)
    f.pack(fill='x', pady=(px(top), px(bottom)))
    tk.Label(f, text=spaced(text), font=th.f_eyebrow, bg=bg, fg=GREY).pack(side='left')
    tk.Frame(f, bg=RULE_2, height=hair()).pack(side='left', fill='x', expand=True,
                                               padx=(px(10), 0))
    return f


def rule(parent, color=RULE, h=None, pady=0, bg=PAPER):
    f = tk.Frame(parent, bg=color, height=h or hair())
    f.pack(fill='x', pady=pady)
    return f


class BookMark(tk.Canvas):
    """표제부의 책 표식. app_icon과 같은 도형을 그려 창과 아이콘을 일치시킨다.

    파일을 읽지 않고 직접 그리는 이유: 아이콘 파일이 없거나 교체돼도 표제부는
    항상 같은 표식을 보여야 하고, 배율에 따라 선이 흐려지지 않아야 하기 때문이다.
    """

    def __init__(self, parent, size=30, bg=PAPER):
        S = px(size)
        super().__init__(parent, width=S, height=S, bg=bg,
                         highlightthickness=0, bd=0)
        bw, bh = 0.60, 0.82
        x0, x1 = round((1 - bw) / 2 * S), round((1 + bw) / 2 * S)
        y0, y1 = round((1 - bh) / 2 * S), round((1 + bh) / 2 * S)
        W = x1 - x0
        self.create_rectangle(x0, y0, x1, y1, fill=PAPER, outline=INK, width=hair())
        spine = max(round(0.17 * W), px(2))
        self.create_rectangle(x0, y0, x0 + spine, y1, fill=INK, outline=INK)
        # 띠는 표지 안쪽에만 얹는다 — 오른쪽 윤곽선을 덮으면 책이 아니라 깃발로 보인다
        cx0, cx1 = x0 + spine, x1 - hair()
        by = y0 + round((y1 - y0) * 0.58)
        self.create_rectangle(cx0, by, cx1, by + max(round((y1 - y0) * 0.16), px(2)),
                              fill=VERM, outline=VERM)


def ease_out(t):
    """3차 감속 — 막대가 자라 붙는 느낌을 만든다."""
    return 1 - (1 - t) ** 3
