# -*- coding: utf-8 -*-
"""
표준보고양식(.hwpx) 출력 모듈

한글 문서 양식 파일을 원본 그대로 두고, 안의 표 셀과 'n' 자리표시자만
값으로 바꿔 저장한다. 서식·글꼴·표 테두리는 양식 그대로 유지된다.

hwpx는 XML 묶음(zip)이므로 Contents/section0.xml만 고쳐 다시 압축한다.
표는 위치(index)가 아니라 머리글 문구로 찾으므로, 양식에서 표 순서가
바뀌거나 문단이 추가돼도 계속 동작한다.
"""
import copy
import datetime
import re
import zipfile

from lxml import etree

HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
SECTION = 'Contents/section0.xml'


def q(tag):
    return f'{{{HP}}}{tag}'


# ── 셀/문단 조작 ────────────────────────────────────────────────
def cell_text(tc):
    return ''.join(t.text or '' for t in tc.iter(q('t'))).strip()


def set_cell(tc, value):
    """셀에 값을 쓴다. 원래 글자 서식(charPrIDRef)은 그대로 둔다."""
    sub = tc.find(q('subList'))
    if sub is None:
        return
    paras = sub.findall(q('p'))
    if not paras:
        return
    p = paras[0]
    runs = p.findall(q('run'))
    if not runs:
        return
    # 텍스트가 이미 있는 run을 우선 사용 (서식 유지에 유리)
    target = next((r for r in runs if r.find(q('t')) is not None), runs[0])
    for r in runs:
        for t in r.findall(q('t')):
            r.remove(t)
    t = etree.Element(q('t'))
    t.text = '' if value is None else str(value)
    target.insert(0, t)
    # 여러 줄짜리 셀이면 첫 문단만 남긴다
    for extra in paras[1:]:
        sub.remove(extra)


def table_cells(tbl):
    """{(행, 열): tc} 로 셀 주소 색인."""
    out = {}
    for tc in tbl.iter(q('tc')):
        ad = tc.find(q('cellAddr'))
        if ad is not None:
            out[(int(ad.get('rowAddr')), int(ad.get('colAddr')))] = tc
    return out


def _norm(s):
    return re.sub(r'[\s·\-*()]+', '', str(s or ''))


def find_table(tables, *signatures):
    """머리글 문구로 표를 찾는다. 모든 signature가 표 안에 있어야 한다."""
    for tbl in tables:
        text = _norm(''.join(t.text or '' for t in tbl.iter(q('t'))))
        if all(_norm(s) in text for s in signatures):
            return tbl
    return None


#: 앞뒤가 영숫자가 아닌 홑 'n' (예: 'n명의', ' n ') 만 자리표시자로 본다.
#: 'NRI', 'and' 같은 단어의 n은 걸리지 않는다.
_N_PLACEHOLDER = re.compile(r'(?<![A-Za-z0-9])n(?![A-Za-z0-9])')


def fill_n(para, values):
    """문단 안의 'n' 자리표시자를 순서대로 값으로 치환.
    자리표시자가 문장 중간에 붙어 있는 경우('※ n명의 연구자가')도 처리한다."""
    box = {'k': 0}

    def sub(m):
        if box['k'] >= len(values):
            return m.group(0)
        v = values[box['k']]
        box['k'] += 1
        return f'{v:,}' if isinstance(v, int) else str(v)

    for t in para.iter(q('t')):
        if box['k'] >= len(values):
            break
        if t.text and 'n' in t.text:
            t.text = _N_PLACEHOLDER.sub(sub, t.text)
    return box['k']


def _pct(v, total):
    return f'({v / total * 100:.1f}%)' if total else '(0.0%)'


# ── 본문 채우기 ─────────────────────────────────────────────────
#: 작성 시점(오늘)을 쓰는 문단 — 표제 아래 발행 표기
#: 예: (KISTEP 연구윤리자산보호센터, ’26.07.31.)
#: 나머지 날짜는 모두 산출기준일(raw 파일명에서 뽑은 날짜)을 쓴다.
#: 'KISTEP'만으로는 표제도 걸릴 수 있어 센터명 쪽으로 좁혔다.
ISSUED_MARKS = ('연구윤리자산보호센터', '연구윤리', '자산보호센터', '보호센터')


def _fill_body(root, S, base_date, issue_date=None):
    issue_date = issue_date or datetime.date.today()

    def parts(d):
        return d.strftime('%y'), d.strftime('%m'), d.strftime('%d')

    logs = S.get('전처리내역') or []
    raw_total = sum(lg['원본건수'] for lg in logs) if logs else S['총건수']
    removed = sum(lg['제거건수'] for lg in logs) if logs else 0
    res_raw = logs[0]['원본건수'] if logs else S['총건수']
    res_removed = logs[0]['제거건수'] if logs else 0

    # 날짜 자리표시자. 양식에 따라 'yy.mm.dd'가 한 덩어리이거나 조각나 있어
    # 두 경우를 모두 처리한다.
    #
    # 문단 단위로 보는 이유: 표제 아래 발행 표기만 '오늘'을 쓰고 나머지 본문
    # 날짜는 산출기준일을 써야 하는데, 어느 쪽인지는 문단 전체를 봐야 알 수 있다.
    for p in root.iter(q('p')):
        if p.find('.//' + q('tbl')) is not None:
            continue          # 표를 품은 문단 — 안쪽 문단에서 따로 처리된다
        ts = [t for t in p.iter(q('t')) if t.text]
        if not ts:
            continue
        whole = ''.join(t.text for t in ts)
        if not re.search(r'yy|mm|dd', whole, re.IGNORECASE):
            continue
        use_today = any(k in whole for k in ISSUED_MARKS)
        yy, mm, dd = parts(issue_date if use_today else base_date)
        for t in ts:
            s = t.text
            # 무관한 낱말이 바뀌지 않도록 날짜꼴일 때만 반영
            if not re.search(r'(yy|YY)[.\-]?(mm|MM)?|(mm|MM)[.\-](dd|DD)', s):
                continue
            t.text = (s.replace('yy', yy).replace('YY', yy)
                       .replace('mm', mm).replace('MM', mm)
                       .replace('dd', dd).replace('DD', dd))

    # 'n' 자리표시자가 든 문장들
    for p in root.iter(q('p')):
        text = ''.join(t.text or '' for t in p.iter(q('t')))
        if not text or 'n' not in text:
            continue
        if '국외지원사항 등록 수' in text:
            fill_n(p, [S['고유연구자수'], S['고유연책수'], S['총건수']])
        elif '총 등록 데이터' in text:
            fill_n(p, [res_raw, res_removed])
        elif '국외지원사항 보고된 과제 수' in text:
            fill_n(p, [S['고유과제수']])
        elif '과제 협약 시 보고' in text:
            # 앞: 연구책임자 수 / 뒤: 총 신고 건수 - 과제매핑 미진행 신고 수
            fill_n(p, [S['고유연책수'], S['협약보고건수']])
        elif '중복제외' in text:
            fill_n(p, [S['지원기관수']])
    return raw_total, removed


# ── 표 채우기 ──────────────────────────────────────────────────
def _get(tc, tag):
    return tc.find(q(tag))


def _clone(tpl, row, col, colspan=1, rowspan=1, width=None, height=None, text=''):
    """템플릿 셀을 복제해 주소·크기·내용을 설정한다."""
    tc = copy.deepcopy(tpl)
    ad = _get(tc, 'cellAddr')
    ad.set('rowAddr', str(row))
    ad.set('colAddr', str(col))
    sp = _get(tc, 'cellSpan')
    sp.set('colSpan', str(colspan))
    sp.set('rowSpan', str(rowspan))
    cs = _get(tc, 'cellSz')
    if width is not None:
        cs.set('width', str(width))
    if height is not None:
        cs.set('height', str(height))
    set_cell(tc, text)
    return tc


def _split_width(total, n):
    """total을 n등분하되 합이 정확히 total이 되도록 나머지를 마지막에 더한다."""
    if n <= 0:
        return []
    w = total // n
    out = [w] * n
    out[-1] += total - w * n
    return out


def _fill_monthly(tbl, S, warnings, base_date):
    """월별 등록 수 표를 산출월 기준으로 다시 만들고 값을 채운다.

    열 구성: 구분 | 지난 연도들 | 산출연도 1월~산출월 | 소계 | 합계

    월 열은 달이 갈수록 12월까지 늘어난다. 해가 바뀌면 지난 연도는 월 구분 없이
    연도 한 칸으로 접히고, 새 연도는 다시 1월부터 쌓인다.
      예) 산출기준일 2026-09 → | ‘24년 | ‘25년 | ‘26년(1월~9월, 소계) | 합계 |
          산출기준일 2026-12 → | ‘24년 | ‘25년 | ‘26년(1월~12월, 소계) | 합계 |
          산출기준일 2027-01 → | ‘24년 | ‘25년 | ‘26년 | ‘27년(1월, 소계) | 합계 |
    """
    rows = tbl.findall(q('tr'))
    if len(rows) < 4:
        warnings.append('월별 표 구조를 알아볼 수 없어 건너뛰었습니다')
        return
    cells = table_cells(tbl)

    # ── 원본에서 셀 서식 템플릿 확보 ──
    tpl_gubun = cells[(0, 0)]
    tpl_total = max((tc for (r, c), tc in cells.items() if r == 0),
                    key=lambda tc: int(_get(tc, 'cellAddr').get('colAddr')))
    tpl_year = None
    tpl_block = None
    for (r, c), tc in sorted(cells.items()):
        if r != 0 or c == 0 or tc is tpl_total:
            continue
        if int(_get(tc, 'cellSpan').get('colSpan')) > 1:
            if tpl_block is None:
                tpl_block = tc
        elif tpl_year is None:
            tpl_year = tc
    row1 = {c: tc for (r, c), tc in cells.items() if r == 1}
    tpl_month = row1[min(row1)] if row1 else None
    tpl_sub = row1[max(row1)] if row1 else None
    if tpl_year is None or tpl_block is None or tpl_month is None:
        warnings.append('월별 표의 머리글 구조를 알아볼 수 없어 건너뛰었습니다')
        return
    tpl_lab2, tpl_lab3 = cells[(2, 0)], cells[(3, 0)]
    tpl_d2, tpl_d3 = cells[(2, 1)], cells[(3, 1)]

    # ── 목표 열 구성 산출 ──
    cur_y, cur_m = base_date.year, base_date.month
    data_years = [y for y, _ in S['연도별']]
    start = min([2024] + data_years) if data_years else 2024
    years = list(range(start, cur_y))        # 산출연도 이전 = 연도 한 칸으로 접음

    # 산출연도의 월 열은 산출월까지 채우되, 산출월보다 뒤에 등록된 건이 있으면
    # 그 달까지 넓힌다(입력 착오로 앞선 날짜가 들어와도 표에서 누락되지 않게).
    last_data_m = max((int(k[5:7]) for k, _ in S['월별']
                       if k[:4] == f'{cur_y:04d}'), default=0)
    last_m = min(12, max(cur_m, last_data_m))
    months = list(range(1, last_m + 1))

    year_of = dict(S['연도별'])
    month_of = dict(S['월별'])
    yv = [int(year_of.get(y, 0)) for y in years]
    mv = [int(month_of.get(f'{cur_y:04d}-{m:02d}', 0)) for m in months]
    sub = sum(mv)
    total = sum(yv) + sub

    # 표에 담기지 못한 등록 건 경고 (산출연도보다 뒤의 연도로 등록된 건 등)
    gap = S['날짜인식건수'] - total
    if gap > 0:
        warnings.append(
            f'월별 표: {cur_y}년 이후 연도로 등록된 {gap:,}건은 표에 포함되지 않았습니다 '
            f'(표 합계 {total:,}건 / 전체 {S["날짜인식건수"]:,}건). '
            f'NRI 등록일자를 확인해 주세요')

    # ── 열 너비 계산 (표 전체 폭 유지) ──
    tbl_w = int(tbl.find(q('sz')).get('width'))
    w_gubun = int(_get(tpl_gubun, 'cellSz').get('width'))
    w_total = int(_get(tpl_total, 'cellSz').get('width'))
    n_mid = len(years) + (len(months) + 1 if months else 0)
    if n_mid <= 0:
        warnings.append('월별 표: 표시할 연도·월이 없어 건너뛰었습니다')
        return
    mid_w = _split_width(tbl_w - w_gubun - w_total, n_mid)

    h0_span = int(_get(tpl_block, 'cellSz').get('height'))          # 병합 머리글 1행 높이
    h0_full = int(_get(tpl_gubun, 'cellSz').get('height'))          # 2행 병합 높이
    h_month = int(_get(tpl_month, 'cellSz').get('height'))
    h_data = int(_get(tpl_d2, 'cellSz').get('height'))

    ncol = 1 + n_mid + 1
    has_m = bool(months)
    rspan = 2 if has_m else 1
    h_head = h0_full if has_m else h0_span

    # ── 행 재구성 ──
    r0, r1, r2, r3 = rows[0], rows[1], rows[2], rows[3]
    for tr in (r0, r1, r2, r3):
        for tc in tr.findall(q('tc')):
            tr.remove(tc)

    # 0행: 구분 | 연도들 | (산출연도 병합) | 합계
    r0.append(_clone(tpl_gubun, 0, 0, 1, rspan, w_gubun, h_head,
                     cell_text(tpl_gubun) or '구분'))
    ci = 1
    for i, y in enumerate(years):
        r0.append(_clone(tpl_year, 0, ci, 1, rspan, mid_w[i], h_head, f'‘{y % 100:02d}년'))
        ci += 1
    if has_m:
        span_w = sum(mid_w[len(years):])
        r0.append(_clone(tpl_block, 0, ci, len(months) + 1, 1, span_w, h0_span,
                         f'‘{cur_y % 100:02d}년'))
        ci += len(months) + 1
    r0.append(_clone(tpl_total, 0, ci, 1, rspan, w_total, h_head, '합계'))

    # 1행: 월 라벨 + 소계 (월이 없으면 행 자체를 제거)
    if has_m:
        base = 1 + len(years)
        for j, m in enumerate(months):
            r1.append(_clone(tpl_month, 1, base + j, 1, 1, mid_w[len(years) + j],
                             h_month, f'{m}월'))
        r1.append(_clone(tpl_sub if tpl_sub is not None else tpl_month,
                         1, base + len(months), 1, 1,
                         mid_w[-1], h_month, '소계'))
    else:
        tbl.remove(r1)

    # 2·3행: 등록 수 / 비중
    vals = yv + (mv + [sub] if has_m else []) + [total]
    widths = [w_gubun] + mid_w + [w_total]
    r2.append(_clone(tpl_lab2, 2 if has_m else 1, 0, 1, 1, w_gubun, h_data,
                     cell_text(tpl_lab2) or '등록 수'))
    r3.append(_clone(tpl_lab3, 3 if has_m else 2, 0, 1, 1, w_gubun, h_data,
                     cell_text(tpl_lab3) or '(비중)'))
    for i, v in enumerate(vals):
        c = i + 1
        r2.append(_clone(tpl_d2, 2 if has_m else 1, c, 1, 1, widths[c], h_data, f'{v:,}'))
        r3.append(_clone(tpl_d3, 3 if has_m else 2, c, 1, 1, widths[c], h_data,
                         _pct(v, total)))

    # ── 표 속성 갱신 ──
    tbl.set('colCnt', str(ncol))
    tbl.set('rowCnt', str(4 if has_m else 3))
    sz = tbl.find(q('sz'))
    sz.set('height', str(h_head + (h_month if has_m else 0) + h_data * 2))


def _fill_country(tbl, S):
    """국가별 상위 10개국."""
    cells = table_cells(tbl)
    ncol = int(tbl.get('colCnt'))
    top = S['국가별'][:ncol - 1]
    total = S['총건수']
    for i in range(ncol - 1):
        c = i + 1
        if i < len(top):
            name, cnt, _ = top[i]
            set_cell(cells[(0, c)], name)
            set_cell(cells[(1, c)], f'{cnt:,}')
            set_cell(cells[(2, c)], _pct(cnt, total))
        else:
            for r in (0, 1, 2):
                if (r, c) in cells:
                    set_cell(cells[(r, c)], '')


def _fill_type(tbl, S):
    """지원·지급 유형별. 양식 머리글과 통계 항목을 이름으로 대조한다."""
    cells = table_cells(tbl)
    ncol = int(tbl.get('colCnt'))
    stat = {_norm(k): v for k, v in S['유형별']}
    # '연구장비 및 시설' → '연구장비·시설' 같은 표기 차이 흡수
    alias = {'연구장비시설': '연구장비및시설', '교통숙박': '교통및숙박'}
    total_row = sum(v for _, v in S['유형별'])

    for c in range(1, ncol):
        label = ''
        for r in (1, 0):
            if (r, c) in cells:
                label = cell_text(cells[(r, c)])
                if label:
                    break
        key = _norm(label)
        key = alias.get(key, key)
        if '합계' in key:
            # 양식 각주대로 중복 산출 합계. 총 신고 건수보다 클 수 있다.
            val = total_row
        else:
            val = stat.get(key)
            if val is None:
                continue
        pct = _pct(val, S['총건수'])
        if (2, c) in cells:
            set_cell(cells[(2, c)], f'{val:,}')
        if (3, c) in cells:
            set_cell(cells[(3, c)], pct)


def _fill_sector(tbl, S):
    """소속기관 유형별 (학·연·산·기타)."""
    cells = table_cells(tbl)
    ncol = int(tbl.get('colCnt'))
    stat = {_norm(k): v for k, v in S['산학연']}
    total = S['총건수']
    for c in range(1, ncol):
        label = _norm(cell_text(cells[(0, c)])) if (0, c) in cells else ''
        val = total if '합계' in label else stat.get(label)
        if val is None:
            continue
        if (1, c) in cells:
            set_cell(cells[(1, c)], f'{val:,}')
        if (2, c) in cells:
            set_cell(cells[(2, c)], _pct(val, total))


def _fill_relation(tbl, S):
    """과제와의 연관성."""
    cells = table_cells(tbl)
    rel = S['관련성']
    tot = rel['합계']
    mapping = {'관련있음': rel['관련있음'], '관련없음': rel['관련없음'], '합계': tot}
    for r in range(1, int(tbl.get('rowCnt'))):
        label = _norm(cell_text(cells[(r, 0)])) if (r, 0) in cells else ''
        if label in mapping:
            v = mapping[label]
            if (r, 1) in cells:
                set_cell(cells[(r, 1)], f'{v:,}')
            if (r, 2) in cells:
                set_cell(cells[(r, 2)], _pct(v, tot))


def _fill_rank(tbl, S, kind):
    """순위표. kind='aff' 소속기관 / kind='org' 지원기관."""
    cells = table_cells(tbl)
    nrow = int(tbl.get('rowCnt'))
    data = S['소속Top20'] if kind == 'aff' else S['기관Top30'][:nrow - 1]
    for r in range(1, nrow):
        i = r - 1
        if i < len(data):
            if kind == 'aff':
                aff, cnt, nres, _ = data[i]
                vals = [aff, f'{cnt:,}', f'{nres:,}']
            else:
                org, nat, affs, cnt = data[i]
                vals = [org, nat, affs, f'{cnt:,}']
        else:
            vals = [''] * (4 if kind == 'org' else 3)
        for j, v in enumerate(vals, start=1):
            if (r, j) in cells:
                set_cell(cells[(r, j)], v)


# ── 진입점 ─────────────────────────────────────────────────────
def build_hwpx(S, template_path, out_path, base_date=None, issue_date=None):
    """양식(hwpx)에 통계를 채워 새 파일로 저장. 경고 목록을 돌려준다.

    base_date  산출기준일 — 본문 날짜·월별 표 열 구성에 쓴다(raw 파일명에서 뽑은 날짜)
    issue_date 작성일 — 표제 아래 '(KISTEP 연구윤리자산보호센터, ’yy.mm.dd.)'에만 쓴다"""
    base_date = base_date or datetime.date.today()
    issue_date = issue_date or datetime.date.today()
    warnings = []

    with zipfile.ZipFile(template_path) as z:
        names = z.namelist()
        blobs = {n: z.read(n) for n in names}
        comp = {i.filename: i.compress_type for i in z.infolist()}

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(blobs[SECTION], parser)

    _fill_body(root, S, base_date, issue_date)

    tables = list(root.iter(q('tbl')))
    jobs = [
        (('구분', '소계', '등록 수'), _fill_monthly, 'monthly'),
        (('국가명', '등록 수'), _fill_country, 'country'),
        (('연구장비', '겸직', '유가증권'), _fill_type, 'type'),
        (('학', '연', '산', '기타'), _fill_sector, 'sector'),
        (('관련있음', '관련없음'), _fill_relation, 'relation'),
        (('순위', '소속기관', '보고 수'), lambda t, s: _fill_rank(t, s, 'aff'), 'aff'),
        (('순위', '연구기관명', '수혜국가'), lambda t, s: _fill_rank(t, s, 'org'), 'org'),
    ]
    used = set()
    for sig, fn, name in jobs:
        tbl = None
        for cand in tables:
            if id(cand) in used:
                continue
            text = _norm(''.join(t.text or '' for t in cand.iter(q('t'))))
            if all(_norm(s) in text for s in sig):
                tbl = cand
                break
        if tbl is None:
            warnings.append(f'양식에서 [{name}] 표를 찾지 못해 건너뛰었습니다')
            continue
        used.add(id(tbl))
        if name == 'monthly':
            fn(tbl, S, warnings, base_date)
        else:
            fn(tbl, S)

    blobs[SECTION] = etree.tostring(root, xml_declaration=True,
                                    encoding='UTF-8', standalone=True)

    # mimetype은 zip 첫 항목·무압축이어야 한글에서 열린다.
    # 나머지 항목도 원본과 같은 압축 방식을 유지한다.
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        if 'mimetype' in blobs:
            z.writestr(zipfile.ZipInfo('mimetype'), blobs['mimetype'],
                       compress_type=zipfile.ZIP_STORED)
        for n in names:
            if n == 'mimetype':
                continue
            z.writestr(n, blobs[n], compress_type=comp.get(n, zipfile.ZIP_DEFLATED))
    return warnings
