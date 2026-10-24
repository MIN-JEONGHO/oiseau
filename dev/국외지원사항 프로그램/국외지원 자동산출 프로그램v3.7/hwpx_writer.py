# -*- coding: utf-8 -*-
"""
표준보고양식(.hwpx) 출력 모듈

한글 문서 양식 파일을 원본 그대로 두고, 안의 표 셀과 'n' 자리표시자만
값으로 바꿔 저장한다. 서식·글꼴·표 테두리는 양식 그대로 유지된다.

hwpx는 XML 묶음(zip)이므로 Contents/section0.xml만 고쳐 다시 압축한다.
표는 위치(index)가 아니라 머리글 문구로 찾으므로, 양식에서 표 순서가
바뀌거나 문단이 추가돼도 계속 동작한다.
"""
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
def _fill_body(root, S, base_date):
    yy, mm, dd = base_date.strftime('%y'), base_date.strftime('%m'), base_date.strftime('%d')
    logs = S.get('전처리내역') or []
    raw_total = sum(lg['원본건수'] for lg in logs) if logs else S['총건수']
    removed = sum(lg['제거건수'] for lg in logs) if logs else 0
    res_raw = logs[0]['원본건수'] if logs else S['총건수']
    res_removed = logs[0]['제거건수'] if logs else 0

    # 날짜 자리표시자
    for t in root.iter(q('t')):
        s = t.text or ''
        if s == 'yy':
            t.text = yy
        elif s == '.mm.dd.':
            t.text = f'.{mm}.{dd}.'
        elif s.strip() == '’YY':
            t.text = s.replace('YY', yy)
        elif s.startswith('.MM.DD.'):
            t.text = f'.{mm}.{dd}.' + s[len('.MM.DD.'):]

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
def _fill_monthly(tbl, S, warnings):
    """월별 등록 수. 연도·월 라벨을 양식에서 읽어 그대로 따른다."""
    cells = table_cells(tbl)
    ncol = int(tbl.get('colCnt'))
    year_of = dict(S['연도별'])
    month_of = dict(S['월별'])

    # 머리글에서 연도 / 월 파악
    year_cols, month_cols, total_col, sub_col = {}, {}, None, None
    for (r, c), tc in cells.items():
        if r > 1:
            continue
        txt = cell_text(tc)
        m = re.search(r'(\d{2,4})\s*년', txt)
        if m and r == 0:
            y = int(m.group(1))
            y = y + 2000 if y < 100 else y
            span = int(tc.find(q('cellSpan')).get('colSpan'))
            if span == 1:
                year_cols[c] = y
            else:
                for cc in range(c, c + span):
                    month_cols[cc] = y          # 월이 펼쳐진 연도
        elif '합계' in txt:
            total_col = c
        elif '소계' in txt:
            sub_col = c
    for (r, c), tc in cells.items():
        if r == 1:
            m = re.match(r'\s*(\d{1,2})\s*월', cell_text(tc))
            if m and c in month_cols:
                month_cols[c] = (month_cols[c], int(m.group(1)))

    values = {}
    for c, y in year_cols.items():
        values[c] = int(year_of.get(y, 0))
    sub = 0
    for c, v in month_cols.items():
        if isinstance(v, tuple):
            y, mo = v
            n = int(month_of.get(f'{y:04d}-{mo:02d}', 0))
            values[c] = n
            sub += n
    if sub_col is not None:
        values[sub_col] = sub
    total = sum(v for c, v in values.items() if c != sub_col) + \
            (0 if sub_col is None else 0)
    # 소계는 월 합이므로 총합에 중복 반영하지 않도록 연도합 + 소계로 계산
    total = sum(values.get(c, 0) for c in year_cols) + sub
    if total_col is not None:
        values[total_col] = total

    # 데이터에 있는데 양식 열에 없는 기간 확인
    covered = set(year_cols.values()) | {v[0] for v in month_cols.values() if isinstance(v, tuple)}
    outside = sum(cnt for y, cnt in S['연도별'] if y not in covered)
    inside_year = {v[0] for v in month_cols.values() if isinstance(v, tuple)}
    for y in inside_year:
        shown = sum(int(month_of.get(f'{y:04d}-{mo:02d}', 0))
                    for c, v in month_cols.items() if isinstance(v, tuple)
                    for mo in [v[1]])
        outside += max(0, int(year_of.get(y, 0)) - shown)
    if outside:
        warnings.append(f'월별 표: 양식에 없는 기간의 등록 {outside:,}건은 표에 반영되지 않았습니다')

    for c in range(1, ncol):
        if c in values:
            if (2, c) in cells:
                set_cell(cells[(2, c)], f'{values[c]:,}')
            if (3, c) in cells:
                set_cell(cells[(3, c)], _pct(values[c], total))


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
def build_hwpx(S, template_path, out_path, base_date=None):
    """양식(hwpx)에 통계를 채워 새 파일로 저장. 경고 목록을 돌려준다."""
    base_date = base_date or datetime.date.today()
    warnings = []

    with zipfile.ZipFile(template_path) as z:
        names = z.namelist()
        blobs = {n: z.read(n) for n in names}
        comp = {i.filename: i.compress_type for i in z.infolist()}

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(blobs[SECTION], parser)

    _fill_body(root, S, base_date)

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
            fn(tbl, S, warnings)
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
