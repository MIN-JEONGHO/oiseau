# -*- coding: utf-8 -*-
"""
표준양식 hwpx 의 표를 집계 결과로 채워 넣는다.

양식 구조 (Contents/section0.xml 의 유일한 hp:tbl, 16행 x 12열)
  row 0        : (단위: 건, 억 원)            <- colSpan = colCnt
  row 1        : 부처별 | 항목 | 2017..2025 | 합계*
  row 2 ~ 8    : 부처 블록 (7행)
                   국가R&D연구비 / 국가R&D과제수 / ① / ② / ③ / 소계 / (비율%)
  row 9 ~ 15   : 합 계 블록 (7행, 동일 구조)

동작
  1) 부처 블록(7행)을 부처 수만큼 복제
  2) 연도 열 개수를 데이터에 맞춰 증감 (열 너비 재분배)
  3) 각 셀에 값 주입 후 rowAddr/colAddr/rowCnt/colCnt 재계산
"""
from __future__ import annotations

import copy
import re
import shutil
import zipfile
from pathlib import Path

from lxml import etree

from sanction_pipeline import JUDGMENT_ORDER, TOTAL_LABEL, AggregateResult

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}
SECTION = "Contents/section0.xml"

BLOCK_ROWS = 7          # 부처 블록 행 수
ROW_MINISTRY_START = 2  # 부처 블록 시작 rowAddr
#: 블록 내 행 인덱스 -> 값 종류
BLOCK_KINDS = ["ref:국가R&D연구비", "ref:국가R&D과제수", "①", "②", "③", "sub", "ratio"]


# ---------------------------------------------------------------------------
# 저수준 헬퍼
# ---------------------------------------------------------------------------

def _q(tag: str) -> str:
    return f"{{{HP}}}{tag}"


def _cells(tr):
    return tr.findall(_q("tc"))


def _addr(tc):
    return tc.find(_q("cellAddr"))


def _span(tc):
    return tc.find(_q("cellSpan"))


def _sz(tc):
    return tc.find(_q("cellSz"))


def _get_text(tc) -> str:
    return "".join(tc.itertext()).strip()


def _set_text(tc, text: str) -> None:
    """셀의 첫 문단 첫 run 의 텍스트를 교체."""
    sub = tc.find(_q("subList"))
    if sub is None:
        return
    paras = sub.findall(_q("p"))
    if not paras:
        return
    # 두 번째 이후 문단 제거 (여러 줄 셀을 한 줄로)
    for p in paras[1:]:
        sub.remove(p)
    p = paras[0]
    runs = p.findall(_q("run"))
    if not runs:
        run = etree.SubElement(p, _q("run"))
        runs = [run]
    for run in runs[1:]:
        p.remove(run)
    run = runs[0]
    for t in run.findall(_q("t")):
        run.remove(t)
    t = etree.Element(_q("t"))
    t.text = text
    run.insert(0, t)


# ---------------------------------------------------------------------------
# 표 구조 조작
# ---------------------------------------------------------------------------

def _resize_year_columns(tbl, n_new: int) -> None:
    """연도 열(colAddr 2 .. colCnt-2) 개수를 n_new 로 맞추고 너비를 재분배."""
    col_cnt = int(tbl.get("colCnt"))
    n_cur = col_cnt - 3          # 부처별, 항목, 합계 제외
    if n_new == n_cur:
        return
    last_year_addr = col_cnt - 2
    total_addr = col_cnt - 1

    for tr in tbl.findall(_q("tr")):
        cells = _cells(tr)
        if len(cells) == 1 and int(_span(cells[0]).get("colSpan")) >= col_cnt:
            continue  # (단위) 행 - colSpan 만 나중에 수정
        year_cells = [c for c in cells if 2 <= int(_addr(c).get("colAddr")) <= last_year_addr]
        if not year_cells:
            continue
        anchor = year_cells[-1]
        if n_new > n_cur:
            for _ in range(n_new - n_cur):
                clone = copy.deepcopy(anchor)
                _set_text(clone, "")
                anchor.addnext(clone)
                anchor = clone
        else:
            for c in year_cells[n_new:]:
                tr.remove(c)

    # colAddr / 너비 재계산
    year_total_w = None
    total_w = None
    for tr in tbl.findall(_q("tr")):
        for c in _cells(tr):
            a = int(_addr(c).get("colAddr"))
            if 2 <= a <= last_year_addr and year_total_w is None:
                year_total_w = int(_sz(c).get("width")) * n_cur
            if a == total_addr and total_w is None:
                total_w = int(_sz(c).get("width"))
        if year_total_w and total_w:
            break

    each = year_total_w // n_new
    rest = year_total_w - each * (n_new - 1)

    for tr in tbl.findall(_q("tr")):
        cells = _cells(tr)
        if len(cells) == 1 and int(_span(cells[0]).get("colSpan")) >= col_cnt:
            _span(cells[0]).set("colSpan", str(3 + n_new))
            continue
        idx = 0
        for c in cells:
            a = int(_addr(c).get("colAddr"))
            if a < 2:
                continue
            if idx < n_new:
                _addr(c).set("colAddr", str(2 + idx))
                _sz(c).set("width", str(each if idx < n_new - 1 else rest))
                idx += 1
            else:  # 합계 열
                _addr(c).set("colAddr", str(2 + n_new))
                _sz(c).set("width", str(total_w))
    tbl.set("colCnt", str(3 + n_new))


def _clone_blocks(tbl, n_ministries: int) -> None:
    """부처 블록(7행)을 n_ministries 개로 복제."""
    trs = tbl.findall(_q("tr"))
    header = trs[:ROW_MINISTRY_START]
    block = trs[ROW_MINISTRY_START:ROW_MINISTRY_START + BLOCK_ROWS]
    total_block = trs[ROW_MINISTRY_START + BLOCK_ROWS:]

    for tr in trs:
        tbl.remove(tr)

    new_trs = list(header)
    for _ in range(n_ministries):
        new_trs.extend(copy.deepcopy(tr) for tr in block)
    new_trs.extend(total_block)

    for tr in new_trs:
        tbl.append(tr)

    # rowAddr 재계산
    for i, tr in enumerate(tbl.findall(_q("tr"))):
        for c in _cells(tr):
            _addr(c).set("rowAddr", str(i))
    tbl.set("rowCnt", str(len(new_trs)))


# ---------------------------------------------------------------------------
# 값 포맷
# ---------------------------------------------------------------------------

def _fmt_count(v, zero_dash: bool = True) -> str:
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f != f:  # NaN (참조데이터의 빈 셀)
        return ""
    if f == 0 and zero_dash:
        return "-"
    return f"{int(f):,}" if f == int(f) else f"{f:,.1f}"


def _fmt_ratio(v) -> str:
    return "" if v is None else f"{v:.2f}%"


def _fill_block(trs, res: AggregateResult, ministry: str, keys, label: str | None) -> None:
    """7행 블록에 값 주입."""
    for i, tr in enumerate(trs):
        kind = BLOCK_KINDS[i]
        cells = _cells(tr)
        # 부처명 셀 (블록 첫 행의 colAddr 0)
        offset = 0
        if cells and int(_addr(cells[0]).get("colAddr")) == 0:
            if label is not None:
                _set_text(cells[0], label)
            offset = 1
        # 항목 라벨 셀(colAddr 1)은 양식 텍스트 유지
        if len(cells) > offset and int(_addr(cells[offset]).get("colAddr")) == 1:
            offset += 1
        value_cells = cells[offset:]

        for cell, key in zip(value_cells, keys):
            if kind.startswith("ref:"):
                item = kind.split(":", 1)[1]
                _set_text(cell, _fmt_count(res.ref(ministry, item, key), zero_dash=False))
            elif kind == "sub":
                _set_text(cell, _fmt_count(res.subtotal(ministry, key)))
            elif kind == "ratio":
                _set_text(cell, _fmt_ratio(res.ratio(ministry, key)))
            else:
                _set_text(cell, _fmt_count(res.count(ministry, kind, key)))


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def fill_hwpx(template: str, out_path: str, res: AggregateResult) -> str:
    template = str(template)
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(template) as zin:
        names = zin.namelist()
        blobs = {n: zin.read(n) for n in names}

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(blobs[SECTION], parser)
    tbl = root.find(f".//{_q('tbl')}")
    if tbl is None:
        raise ValueError("양식 hwpx 에서 표를 찾을 수 없습니다.")

    years = res.years
    ministries = res.ministries
    keys = list(years) + ["합계"]

    # 1) 연도 열 개수 맞추기
    _resize_year_columns(tbl, len(years))

    # 2) 헤더 연도 라벨
    header_tr = tbl.findall(_q("tr"))[1]
    hcells = _cells(header_tr)
    for cell in hcells:
        a = int(_addr(cell).get("colAddr"))
        if 2 <= a <= 1 + len(years):
            _set_text(cell, str(years[a - 2]))

    # 3) 부처 블록 복제
    _clone_blocks(tbl, len(ministries))

    # 4) 값 주입
    trs = tbl.findall(_q("tr"))
    for bi, m in enumerate(ministries):
        start = ROW_MINISTRY_START + bi * BLOCK_ROWS
        _fill_block(trs[start:start + BLOCK_ROWS], res, m, keys, m)
    start = ROW_MINISTRY_START + len(ministries) * BLOCK_ROWS
    _fill_block(trs[start:start + BLOCK_ROWS], res, TOTAL_LABEL, keys, None)

    # 5) 표 전체 높이 재계산 (한글이 다시 계산하지만 값이 클수록 안전)
    szs = tbl.find(_q("sz"))
    if szs is not None:
        per_block = 10356
        head_h = 1182 + 1566
        szs.set("height", str(head_h + (len(ministries) + 1) * per_block))

    blobs[SECTION] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    # 6) 각주의 연도 범위 문구 갱신
    yr_txt = f"{years[0]}~{years[-1]}"
    blobs[SECTION] = re.sub(
        r"2017~20\d{2}".encode(), yr_txt.encode(), blobs[SECTION]
    )

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        # mimetype 은 압축 없이 먼저 기록
        if "mimetype" in blobs:
            zout.writestr(
                zipfile.ZipInfo("mimetype"), blobs["mimetype"], zipfile.ZIP_STORED
            )
        for n in names:
            if n == "mimetype":
                continue
            zout.writestr(n, blobs[n])
    return out_path


def copy_template(src: str, dst: str) -> str:
    shutil.copy(src, dst)
    return dst
