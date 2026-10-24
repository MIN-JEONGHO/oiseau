# -*- coding: utf-8 -*-
"""
raw 파일 전처리 모듈 (v3 신규)

수작업으로 하던 정제 절차를 프로그램에 내장한다.
  1) 출처 국가가 오류값(대한민국·가나·가봉·가이아나)인 행 제거
  2) 지원·지급 내용이 무효값(0, -, 없음 계열 등)인 행 제거
  3) 지원·지급 사유가 무효값(없음 계열)인 행 제거
  4) NRI 등록일자 오름차순 정렬

열은 엑셀 열 문자가 아니라 **머리글 이름**으로 찾는다.
실제 raw 파일과 정제본의 열 위치가 한 칸 어긋나 있어, 위치 기준으로는
두 형식을 모두 처리할 수 없기 때문이다. 머리글을 못 찾으면 위치로 대체한다.

제거 기준값은 매핑테이블.xlsx의 '전처리규칙' 시트에서 읽으므로
새로운 오류 표기가 발견되면 코드 수정 없이 행만 추가하면 된다.
"""
import re
import pandas as pd

# ── 기본 규칙 (매핑테이블에 '전처리규칙' 시트가 없을 때 사용) ──────────
DEFAULT_RULES = {
    '출처국가': ['대한민국', '가나', '가봉', '가이아나'],
    '지원지급내용': ['0', '0원', '1', '-', '--', '없음', '해당없음', '해당사항 없음',
                 '지원 없음', '해당사항없음', '해당 없음', '해당사항 없음 (지급 없음)',
                 '지원 지급 사유 없음',
                 '해당사항 없음 (본 과제의 재원은 한국연구재단에서 나오는 것으로 국외수혜 없음)'],
    '지원지급사유': ['없음', '해당없음', '해당사항 없음', '연구과제 없음', '해당 없음',
                 '글로벌협력사업 (지급 없음)', '지원 지급 사유 없음'],
}
RULE_LABEL = {
    '출처국가': '지원·지급출처 국가',
    '지원지급내용': '지원·지급 내용',
    '지원지급사유': '지원·지급 사유',
}

# ── 머리글 이름 → 내부 컬럼명 (표기 흔들림 흡수) ─────────────────────
HEADER_ALIASES = {
    '번호': '번호',
    '소속기관명': '소속기관명',
    '소속기관사업자등록번호': '소속기관_사업자등록번호',
    '사업자등록번호': '소속기관_사업자등록번호',
    '성명': '성명',
    '국가연구자번호': '국가연구자번호',
    '지원지급기간': '지원지급시작일',
    '기간': '지원지급시작일',
    '시작일': '지원지급시작일',
    '지원지급시작일': '지원지급시작일',
    '개시일': '지원지급시작일',
    '지원지급기간시작': '지원지급시작일',
    '종료일': '지원지급종료일',
    '지원지급종료일': '지원지급종료일',
    '지원지급기간종료': '지원지급종료일',
    '만료일': '지원지급종료일',
    '지원지급사유': '지원지급사유',
    '지원지급내용': '지원지급내용',
    '지원지급출처국가': '출처국가',
    '출처국가': '출처국가',
    '지원지급출처기관': '출처기관',
    '출처기관': '출처기관',
    'nri등록일자': 'NRI등록일자',
    '등록일자': 'NRI등록일자',
    '과제번호': '과제번호',
    '과제명': '과제명',
    '정부연구비': '정부연구비',
    '총연구비': '총연구비',
    '연구책임자': '연구책임자',
    '과제와의관련성': '과제와의관련성',
    '관련성': '과제와의관련성',
}


def norm_header(v):
    """머리글 표기 정규화: 공백·줄바꿈·가운뎃점·괄호·기호 제거 후 소문자화."""
    if v is None:
        return ''
    t = str(v)
    t = re.sub(r'[\s\u00b7\u2027\u30fb\uff65ㆍ·.\-_()\[\]/]+', '', t)
    return t.strip().lower()


def norm_value(v):
    """셀 값 정규화: 앞뒤 공백 제거, 연속 공백 1칸, 끝의 마침표류 제거."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    t = str(v).replace('\u00a0', ' ').strip()
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r'[.,;·]+$', '', t).strip()
    return t


def load_rules(map_path):
    """매핑테이블.xlsx의 '전처리규칙' 시트 → {구분: [값...]}. 없으면 기본값."""
    rules = {k: list(v) for k, v in DEFAULT_RULES.items()}
    try:
        xls = pd.ExcelFile(map_path)
        if '전처리규칙' not in xls.sheet_names:
            return rules
        df = pd.read_excel(xls, '전처리규칙', dtype=str).fillna('')
        if df.shape[1] < 2:
            return rules
        loaded = {}
        for _, r in df.iterrows():
            key = norm_header(r.iloc[0])
            val = str(r.iloc[1]).strip()
            if not key or val == '':
                continue
            key = {'지원지급출처국가': '출처국가'}.get(key, key)
            if key in DEFAULT_RULES:
                loaded.setdefault(key, []).append(val)
        for k, v in loaded.items():
            rules[k] = v          # 시트에 있는 구분만 교체
    except Exception:
        pass
    return rules


PERIOD_END_ALIASES = {'지원지급기간종료', '종료일', '지원지급종료일', '만료일', '기간종료', '종료'}


def _fmt_date(v):
    """날짜/문자 값을 YYYY-MM-DD 문자열로."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d')
    t = str(v).strip()
    if t.endswith(' 00:00:00'):
        t = t[:-9]
    return t


def _split_period(v):
    """'2026-06-25 ~ 2027-06-05' 형태의 한 칸짜리 기간을 (시작, 종료)로 분리."""
    t = _fmt_date(v)
    if not t:
        return '', ''
    for sep in ('~', '∼', '〜', ' - ', '—', '–'):
        if sep in t:
            a, _, b = t.partition(sep)
            return a.strip(), b.strip()
    return t, ''


def resolve_columns(df, positional_names):
    """머리글 이름으로 열을 찾아 표준 컬럼명으로 변경. 실패 시 위치 기준 대체.

    '지원·지급 기간'은 실제 raw에서 시작일·종료일 두 칸이 머리글만 병합된 형태다
    (예: F1:G1 병합 → pandas가 G를 'Unnamed: 6'으로 읽음).
    두 칸을 각각 '지원지급시작일' / '지원지급종료일'로 살려서
    종료일이 버려지지 않게 한다. 기간이 원래 한 칸('시작 ~ 종료')인 파일은 쪼개서 채운다."""
    cols = list(df.columns)
    mapped, used = {}, set()
    period_end = None

    for i, col in enumerate(cols):
        key = norm_header(col)
        std = HEADER_ALIASES.get(key)

        # 기간(시작) 열을 만나면 다음 칸이 짝(병합으로 머리글이 빈 칸 또는 종료일)인지 확인
        if std == '지원지급시작일' and period_end is None and i + 1 < len(cols):
            nxt = cols[i + 1]
            nkey = norm_header(nxt)
            is_blank = (nkey == '' or nkey.startswith('unnamed')
                        or str(nxt).strip().lower().startswith('unnamed'))
            if is_blank or nkey in PERIOD_END_ALIASES:
                period_end = nxt

        if std and std not in used:
            mapped[col] = std
            used.add(std)

    matched = len(used)
    core = {'출처국가', '지원지급내용', '지원지급사유'}

    if not core.issubset(used):
        # 머리글 인식 실패 → 위치 기준
        out = df.copy()
        n = min(len(positional_names), out.shape[1])
        out = out.iloc[:, :n]
        out.columns = positional_names[:n]
        for c in positional_names:
            if c not in out.columns:
                out[c] = None
        return out, 0

    out = df.rename(columns=mapped)

    # 병합된 종료일 칸을 '지원지급종료일'로 편입
    if period_end is not None:
        end_name = mapped.get(period_end, period_end)
        if end_name in out.columns and end_name != '지원지급종료일':
            out = out.rename(columns={end_name: '지원지급종료일'})
            matched += 1

    # 종료일이 없고 시작일 칸에 '시작 ~ 종료'가 들어 있으면 쪼개서 채운다
    if '지원지급시작일' in out.columns:
        has_end = '지원지급종료일' in out.columns and \
                  any(_fmt_date(v) for v in out['지원지급종료일'])
        if not has_end:
            pairs = [_split_period(v) for v in out['지원지급시작일']]
            out['지원지급시작일'] = [a for a, _ in pairs]
            out['지원지급종료일'] = [b for _, b in pairs]
        else:
            out['지원지급시작일'] = [_fmt_date(v) for v in out['지원지급시작일']]
            out['지원지급종료일'] = [_fmt_date(v) for v in out['지원지급종료일']]

    for c in positional_names:
        if c not in out.columns:
            out[c] = None
    return out, matched


def preprocess(df, rules, kind):
    """전처리 실행 → (정제 df, 내역 dict)"""
    log = {'구분': kind, '원본건수': len(df), '단계': [], '검토후보': []}
    work = df.copy()

    # 완전 빈 행 제거 (번호도 값도 없는 행)
    value_cols = [c for c in work.columns if c != '번호']
    blank = work[value_cols].map(norm_value).eq('').all(axis=1) if value_cols else pd.Series(False, index=work.index)
    if blank.any():
        log['단계'].append(('빈 행 제거', '전체 열이 비어 있는 행', int(blank.sum())))
        work = work[~blank]

    # 규칙별 행 제거 (정규화 후 완전 일치)
    for key in ['출처국가', '지원지급내용', '지원지급사유']:
        if key not in work.columns:
            continue
        targets = {norm_value(v) for v in rules.get(key, []) if norm_value(v) != ''}
        if not targets:
            continue
        col = work[key].map(norm_value)
        hit = col.isin(targets)
        removed = int(hit.sum())
        detail = col[hit].value_counts().to_dict()
        log['단계'].append((f'{RULE_LABEL[key]} 오류값 제거',
                            ' / '.join(f'{k}({v})' for k, v in list(detail.items())[:6]) or '-',
                            removed))
        work = work[~hit]

        # 목록에 없지만 무효값으로 의심되는 표기 → 삭제하지 않고 검토 후보로만 기록
        if key in ('지원지급내용', '지원지급사유'):
            rest = work[key].map(norm_value)
            susp = rest[(rest != '') & rest.str.contains('없음|없슴|해당사항|미해당|N/A|n/a', regex=True)
                        & (rest.str.len() <= 40)]
            for val, cnt in susp.value_counts().items():
                log['검토후보'].append((RULE_LABEL[key], val, int(cnt)))

    # NRI 등록일자 오름차순 정렬 (날짜 인식 실패 값은 뒤로)
    if 'NRI등록일자' in work.columns:
        dt = pd.to_datetime(work['NRI등록일자'], errors='coerce')
        work = work.assign(_dt=dt).sort_values(
            '_dt', ascending=True, na_position='last', kind='mergesort').drop(columns='_dt')
        bad = int(dt.isna().sum())
        log['단계'].append(('NRI 등록일자 오름차순 정렬',
                          f'날짜 인식 실패 {bad}건은 뒤로 배치' if bad else '전건 정상 인식', 0))

    work = work.reset_index(drop=True)
    log['정제건수'] = len(work)
    log['제거건수'] = log['원본건수'] - log['정제건수']
    return work, log
