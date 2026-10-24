# -*- coding: utf-8 -*-
"""아이콘 생성 — 펼치지 않은 책 한 권.

    python make_icon.py

기존 아이콘은 먹빛 판에 '國' 한자를 얹은 형태여서 인상이 무거웠다.
여기서는 표식을 책으로 바꾼다. 통계가 아니라 '기록'을 다루는 도구이고,
결과물이 보고서 두 권(엑셀·한글)이라는 점에서 책이 맞는 표식이다.

세 가지만 쓴다.
    · 종이빛 책배(page block)  — 어두운 작업표시줄에서 형태를 잡아 준다
    · 먹빛 표지와 등(spine)     — 밝은 배경에서 윤곽을 세운다
    · 주홍 가름끈(ribbon)       — 화면과 같은 단 하나의 강조색

16px에서 살아남아야 하므로 크기마다 디테일을 덜어낸다. 큰 판에서는
책배의 결과 표지 안쪽 선까지 넣고, 24px 이하에서는 등과 가름끈만 남긴다.
세로선은 최종 픽셀 격자에 맞춰 떨어뜨려 흐려지지 않게 한다.
"""
import os
import sys

from PIL import Image, ImageDraw

INK = (22, 24, 28, 255)        # 먹빛 — 표지·등
PAPER = (252, 252, 250, 255)   # 종이빛 — 책배
VERM = (200, 53, 27, 255)      # 주홍 — 가름끈
INK_SOFT = (60, 66, 75, 255)   # 책배의 결

SS = 8                         # 초과표본 배율
SIZES = (256, 128, 64, 48, 32, 24, 16)


def _snap(v, step):
    """좌표를 최종 픽셀 격자에 맞춘다 — 세로선이 반픽셀에 걸려 흐려지는 것을 막는다."""
    return int(round(v / step)) * step


def draw_book(size):
    """한 변이 size인 책 아이콘 한 장.

    책으로 읽히게 하는 것은 좌우 비대칭이다. 왼쪽에 먹빛 등(spine),
    오른쪽에 겹친 책배(fore-edge). 표지는 종이빛으로 두어 어두운
    작업표시줄에서도 형태가 보이게 한다.
    """
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    big = size >= 64

    # ── 책 외곽 (세로로 선 책) ──
    bw, bh = 0.58, 0.78
    x0 = _snap((1 - bw) / 2 * S, SS)
    x1 = _snap((1 + bw) / 2 * S, SS)
    y0 = _snap((1 - bh) / 2 * S, SS)
    y1 = _snap((1 + bh) / 2 * S, SS)
    W = x1 - x0

    # 종이빛 표지 + 얇은 먹빛 윤곽. 윤곽을 얇게 두어야 '액자'로 읽히지 않는다.
    bd = max(_snap(0.045 * W, SS), SS)
    d.rectangle([x0, y0, x1, y1], fill=INK)
    d.rectangle([x0 + bd, y0 + bd, x1 - bd, y1 - bd], fill=PAPER)

    # ── 등 (왼쪽 먹빛 기둥) — 좁게. 책의 결정적 단서 ──
    spine = _snap(0.17 * W, SS)
    d.rectangle([x0, y0, x0 + spine, y1], fill=INK)

    cx0, cx1 = x0 + spine, x1 - bd          # 표지 앞면
    cy0, cy1 = y0 + bd, y1 - bd
    CH = cy1 - cy0

    # ── 표제띠 (주홍, 가로) ──
    # 등이 세로축이므로 강조는 가로축으로 둔다. 축이 교차해 좁은 판에서도
    # 두 요소가 서로 뭉치지 않고, 표지에 감긴 띠는 제책의 관례이기도 하다.
    band_h = max(_snap((0.15 if big else 0.19) * CH, SS), SS)
    by0 = _snap(cy0 + CH * 0.58, SS)
    d.rectangle([cx0, by0, cx1, by0 + band_h], fill=VERM)

    # ── 표제 활자 자리 (큰 판만) ──
    if big:
        lw = max(int(round(0.9 * SS)), 1)
        for frac, ln in ((0.22, 0.66), (0.34, 0.44)):
            yy = _snap(cy0 + CH * frac, SS)
            d.rectangle([cx0 + (cx1 - cx0) * 0.15, yy,
                         cx0 + (cx1 - cx0) * (0.15 + ln), yy + lw], fill=INK_SOFT)

    return img.resize((size, size), Image.LANCZOS)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    layers = [draw_book(s) for s in SIZES]

    ico = os.path.join(here, 'app_icon.ico')
    layers[0].save(ico, format='ICO',
                   sizes=[(s, s) for s in sorted(SIZES)])
    png = os.path.join(here, 'app_icon.png')
    layers[0].save(png, format='PNG')

    print('app_icon.ico  — %d개 크기 %s' % (len(SIZES), sorted(SIZES)))
    print('app_icon.png  — %dpx' % SIZES[0])

    # 미리보기: 크기별로 나란히 이어 붙인 대조판
    pad, bg = 12, (238, 238, 232, 255)
    w = sum(s + pad for s in SIZES) + pad
    h = max(SIZES) + pad * 2
    sheet = Image.new('RGBA', (w, h), bg)
    x = pad
    for s, im in zip(SIZES, layers):
        sheet.alpha_composite(im, (x, (h - s) // 2))
        x += s + pad
    prev = os.path.join(here, 'app_icon_preview.png')
    sheet.save(prev)
    print('app_icon_preview.png — 크기 대조판')
    return 0


if __name__ == '__main__':
    sys.exit(main())
