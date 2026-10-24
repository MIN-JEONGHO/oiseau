# -*- coding: utf-8 -*-
"""
월별통계 표준양식 hwpx 를 집계 결과로 채운다.

양식 구조 (표 9개, 통계 1~9와 순서 일치)
  각 표 12열: [분류] [항목] [연도 x N] [합 계]
  r0            : 분류축명(colSpan 2) | 연도들 | 합 계
  r1 이후 블록  : 참여제한 표는 1행(건수), 금액 표는 5행
                  (부과액/납부액/미납액/미납률/건수)
                  분류명 셀은 col0 에 rowSpan = 블록 행수로 병합

동작
  1) 연도 열 개수를 데이터에 맞춰 증감 (열 너비 재분배)
  2) 분류 블록을 표준 목록 + 추가 분류 + 합 계 만큼 복제
  3) 값 주입 후 rowAddr/colAddr/rowCnt/colCnt 재계산

양식에 적힌 분류 행은 이전 산출물의 스냅샷이어서 표마다 목록이 다르다
(예: 환수금 제재사유 표에 '기술료 미납'이 없음). 그래서 행은 양식을 따르지
않고 표준 목록으로 다시 만든다.
"""
from __future__ import annotations

import copy
import re
import zipfile
from pathlib import Path

from lxml import etree

from monthly_pipeline import (
    TOTAL_LABEL, MonthlyResult, display_label, standard_tables,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}
SECTION = "Contents/section0.xml"

#: 양식 각주의 자리표시자 — 표마다 하나씩 9곳에 있다.
#:   "※ 기준연도는 처분연도 기준, NTIS 제재정보에 전문기관이 현재(’yy.mm.dd일까지 입력) …"
ASOF_PLACEHOLDER = "’yy.mm.dd"

#: rawdata 파일명에서 기준일을 찾는다. 20260101 / 2026-01-01 / 2026.01.01 형태.
_DATE_IN_NAME = re.compile(
    r"(20\d{2})[.\-_]?(0[1-9]|1[0-2])[.\-_]?(0[1-9]|[12]\d|3[01])(?!\d)"
)


def asof_from_filename(path: str | None) -> str | None:
    """rawdata 파일명의 연월일 -> '’26.01.01'. 못 찾으면 None.

    예) 제재정보_rawdata_20260101_샘플.xlsx -> ’26.01.01
        제재정보_rawdata_20260301 (1).xlsx -> ’26.03.01

    파일명에 여러 개 있으면 마지막 것을 쓴다('2026년 제재통계' 같은 상위 폴더·접두어보다
    파일 뒤쪽에 붙은 추출일자가 기준일이기 때문).
    """
    if not path:
        return None
    name = Path(str(path)).stem
    got = _DATE_IN_NAME.findall(name)
    if not got:
        return None
    y, m, d = got[-1]
    return f"’{y[2:]}.{m}.{d}"


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


def _set_text(tc, text: str) -> None:
    sub = tc.find(_q("subList"))
    if sub is None:
        return
    paras = sub.findall(_q("p"))
    if not paras:
        return
    for p in paras[1:]:
        sub.remove(p)
    p = paras[0]
    runs = p.findall(_q("run"))
    if not runs:
        runs = [etree.SubElement(p, _q("run"))]
    for run in runs[1:]:
        p.remove(run)
    run = runs[0]
    for t in run.findall(_q("t")):
        run.remove(t)
    t = etree.Element(_q("t"))
    t.text = text
    run.insert(0, t)


# ---------------------------------------------------------------------------
# 값 포맷
# ---------------------------------------------------------------------------

def fmt(item: str, v, occurred: bool = True) -> str:
    """항목별 표기.

    양식 각주:
      ※ 미납률(%) = 미납액/부과액. 따라서 **미납률 0%가 전액 납부를 의미**함
        (당해 연도 미발생한 경우, "-"으로 표기)

    그래서 `-` 는 **당해 연도에 부과가 없었다는 뜻만** 쓴다. 0 을 `-` 로 찍으면
    전액 납부한 것과 부과가 없던 것이 구별되지 않는다.

    occurred : 그 칸에 부과액이 있었는지 (부과액 != 0)
    """
    if v is None:
        return "-"                       # 산출 불가 = 부과액 0 = 미발생
    if item == "건수":
        return "-" if not v else f"{int(round(v)):,}"
    if not occurred:
        return "-"                       # 부과가 없던 연도
    if item == "미납률":
        return f"{v:.1f}%"               # 0.0% = 전액 납부
    return f"{v:,.1f}"                   # 금액(억원). 0.0 도 값으로 남긴다


# ---------------------------------------------------------------------------
# 표 구조 조작
# ---------------------------------------------------------------------------

def _resize_year_columns(tbl, n_new: int) -> None:
    """연도 열(colAddr 2 .. colCnt-2) 개수를 n_new 로 맞추고 너비를 재분배."""
    col_cnt = int(tbl.get("colCnt"))
    n_cur = col_cnt - 3
    if n_new == n_cur:
        return
    last_year, total_addr = col_cnt - 2, col_cnt - 1

    for tr in tbl.findall(_q("tr")):
        year_cells = [
            c for c in _cells(tr) if 2 <= int(_addr(c).get("colAddr")) <= last_year
        ]
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

    # 너비 기준 확보
    year_w = tot_w = None
    for tr in tbl.findall(_q("tr")):
        for c in _cells(tr):
            a = int(_addr(c).get("colAddr"))
            if 2 <= a <= last_year and year_w is None:
                year_w = int(_sz(c).get("width")) * n_cur
            if a == total_addr and tot_w is None:
                tot_w = int(_sz(c).get("width"))
        if year_w and tot_w:
            break

    each = year_w // n_new
    rest = year_w - each * (n_new - 1)
    for tr in tbl.findall(_q("tr")):
        idx = 0
        for c in _cells(tr):
            a = int(_addr(c).get("colAddr"))
            if a < 2:
                continue
            if idx < n_new:
                _addr(c).set("colAddr", str(2 + idx))
                _sz(c).set("width", str(each if idx < n_new - 1 else rest))
                idx += 1
            else:
                _addr(c).set("colAddr", str(2 + n_new))
                _sz(c).set("width", str(tot_w))
    tbl.set("colCnt", str(3 + n_new))


def _block_size(tbl) -> int:
    """첫 데이터 블록의 행 수 = col0 셀의 rowSpan."""
    trs = tbl.findall(_q("tr"))
    first = _cells(trs[1])[0]
    return int(_span(first).get("rowSpan"))


def _rebuild_blocks(tbl, n_blocks: int) -> int:
    """데이터 블록을 n_blocks 개로 맞춘다. 블록 행수를 반환."""
    trs = tbl.findall(_q("tr"))
    size = _block_size(tbl)
    header, block = trs[:1], trs[1 : 1 + size]

    for tr in trs:
        tbl.remove(tr)

    new = list(header)
    for _ in range(n_blocks):
        new.extend(copy.deepcopy(tr) for tr in block)
    for tr in new:
        tbl.append(tr)

    for i, tr in enumerate(tbl.findall(_q("tr"))):
        for c in _cells(tr):
            _addr(c).set("rowAddr", str(i))
    tbl.set("rowCnt", str(len(new)))
    return size


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def fill_monthly_hwpx(
    template: str, out_path: str, res: MonthlyResult,
    raw_name: str | None = None, asof: str | None = None,
) -> str:
    """양식을 채운다.

    raw_name : rawdata 파일명(또는 경로). 각주의 '’yy.mm.dd' 를 이 이름의 연월일로 바꾼다.
    asof     : 기준일을 직접 지정할 때 ('’26.01.01' 형태). raw_name 보다 우선.
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(template)) as zin:
        names = zin.namelist()
        blobs = {n: zin.read(n) for n in names}

    root = etree.fromstring(blobs[SECTION])
    tbls = root.findall(f".//{_q('tbl')}")
    # 양식은 표 9개(제재유형 3 x 표준 분류축 3)로 고정이다. 축을 더 골랐더라도
    # 표준 9개만, 번호가 아니라 (제재유형, 축) 으로 골라 담는다.
    stats = standard_tables(res)
    if len(tbls) < len(stats):
        raise ValueError(
            f"양식의 표가 {len(tbls)}개뿐입니다. 통계 {len(stats)}개를 담을 수 없습니다."
        )

    years = res.years
    keys = [*years, "합계"]

    for tbl, stat in zip(tbls, stats):
        _resize_year_columns(tbl, len(years))

        # 헤더: 연도 라벨
        hcells = _cells(tbl.findall(_q("tr"))[0])
        for c in hcells:
            a = int(_addr(c).get("colAddr"))
            if 2 <= a <= 1 + len(years):
                _set_text(c, str(years[a - 2]))

        rows = [*stat.labels, TOTAL_LABEL]
        size = _rebuild_blocks(tbl, len(rows))

        trs = tbl.findall(_q("tr"))
        for bi, label in enumerate(rows):
            start = 1 + bi * size
            for k in range(size):
                tr = trs[start + k]
                cells = _cells(tr)
                off = 0
                if cells and int(_addr(cells[0]).get("colAddr")) == 0:
                    _set_text(cells[0], display_label(label))
                    off = 1
                item = stat.items[k] if k < len(stat.items) else stat.items[-1]
                if len(cells) > off and int(_addr(cells[off]).get("colAddr")) == 1:
                    _set_text(cells[off], item)
                    off += 1
                for cell, col in zip(cells[off:], keys):
                    imp = stat.get(label, "부과액", col)
                    _set_text(cell, fmt(item, stat.get(label, item, col),
                                        occurred=bool(imp)))

        szs = tbl.find(_q("sz"))
        if szs is not None:
            szs.set("height", str(1200 + len(rows) * size * 1100))

    blobs[SECTION] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    # 제목·각주의 연도 범위 문구 갱신
    blobs[SECTION] = re.sub(
        r"20\d{2}~20\d{2}".encode(), f"{years[0]}~{years[-1]}".encode(), blobs[SECTION]
    )

    # 각주의 기준일 자리표시자 갱신. 못 찾으면 자리표시자를 그대로 남긴다 —
    # 잘못된 날짜를 적는 것보다 비어 있는 것이 눈에 띈다.
    stamp = asof or asof_from_filename(raw_name)
    if stamp:
        blobs[SECTION] = blobs[SECTION].replace(
            ASOF_PLACEHOLDER.encode("utf-8"), stamp.encode("utf-8")
        )
    else:
        print(
            f"  ! rawdata 파일명에서 기준일을 찾지 못해 각주의 '{ASOF_PLACEHOLDER}' 를 "
            "그대로 두었습니다. 한글에서 직접 채워 주세요"
        )

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        if "mimetype" in blobs:
            zout.writestr(
                zipfile.ZipInfo("mimetype"), blobs["mimetype"], zipfile.ZIP_STORED
            )
        for n in names:
            if n != "mimetype":
                zout.writestr(n, blobs[n])
    return out_path
