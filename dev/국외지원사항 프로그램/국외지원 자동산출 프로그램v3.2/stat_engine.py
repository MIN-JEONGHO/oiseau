# -*- coding: utf-8 -*-
"""
국외지원사항 자동 통계산출 엔진
기존 엑셀(v5)의 보조시트/통계분석 로직을 pandas로 재구현.
매핑 규칙은 '매핑테이블.xlsx'(기관별칭/민감국가/소속정규화)에서 읽어온다.
"""
import datetime
import re
import pandas as pd
from collections import OrderedDict

from preprocessor import DEFAULT_RULES, load_rules, resolve_columns, preprocess

# ── 연구자raw / 과제raw 컬럼 정의 (원본 엑셀과 동일 순서) ──────────────
RESEARCHER_COLS = ['번호', '소속기관명', '소속기관_사업자등록번호', '성명', '국가연구자번호',
                   '지원지급시작일', '지원지급종료일', '지원지급사유', '지원지급내용',
                   '출처국가', '출처기관', 'NRI등록일자']
PROJECT_COLS = ['번호', '과제번호', '과제명', '정부연구비', '총연구비', '소속기관명',
                '소속기관_사업자등록번호', '연구책임자', '국가연구자번호',
                '지원지급시작일', '지원지급종료일',
                '과제와의관련성', '지원지급사유', '지원지급내용', '출처국가', '출처기관', 'NRI등록일자']

# ── 지원·지급 유형 키워드 (엑셀 통계분석!M67 IFS 우선순위 분류) ──────────
# 원본 대시보드(B67~B73)와 동일한 다중 카운트 방식.
# 한 건이 여러 유형에 동시 집계될 수 있으며, 합계는 총건수, 별도로 중복건수를 산출한다.
# 각 항목: (포함 키워드, 제외 키워드) — 제외 키워드가 하나라도 있으면 해당 유형에서 제외.
_MONEY_KW_BASE = ["employee", "인건비", "급여", "월급", "연봉", "임금", "호봉", "salary",
                  "full", "stipend", "연구비", "연구과제", "과제비", "연구활동비", "연구수당",
                  "grant", "funding", "fellowship", "펠로우십", "공동연구", "수탁연구",
                  "산학과제", "산학연구", "연구지원", "료", "학비", "등록금", "장학",
                  "입금액", "입금금액", "누적과제", "재료비", "자문료", "자문비", "자문계약",
                  "consulting", "consultant", "컨설팅", "기술자문", "기술 자문",
                  "강의료", "강연료", "강의비", "honorarium", "수강료", "교육비",
                  "용역비", "용역수행금", "보수", "물품대금",
                  "원", "달러", "달라", "usd", "유로", "eur", "엔", "jpy", "파운드",
                  "chf", "cad", "sgd", "aud", "thb", "nok", "hkd", "rmb", "dm",
                  "위안", "yuan", "yen", "euro", "pound", "불", "천원", "만원", "억",
                  "krw", "$", "￡", "€", "won", "미화", "한화", "/",
                  "0", "1", "2", "3", "4", "5", "6", "7", "8"]

TYPE_RULES = OrderedDict([
    # (표시명, 포함 키워드, 제외 키워드, 정확일치 키워드)
    ('연구장비 및 시설', dict(
        include=["장비", "기자재", "기기", "설비", "gpu", "cpu", "서버", "슈퍼컴퓨터", "로봇",
                 "자석", "reactor", "scanner", "분석기", "실험장비", "연구장비", "시험연구장비",
                 "node hours", "exaflop", "소자", "소프트웨어", "하드웨어", "software",
                 "시설", "실험실", "연구실", "연구공간", "방문 공간", "사무 공간", "사무공간",
                 "사무소", "시험소", "laboratory", "computing facility", "생산라인",
                 "창업 보육", "자원", "연구자원", "연구시설", "오가노이드", "api"],
        exclude=[], exact=[])),
    ('연구인력', dict(
        include=["박사급", "석사급", "석박사", "박사후", "포닥", "postdoc", "박사과정", "박사",
                 "학사", "석사", "연구원", "연구인력", "참여연구원", "인력활용", "인턴",
                 "phd student", "연구인력 이전", "학생"],
        exclude=_MONEY_KW_BASE,   # 엑셀 B68: 금전 키워드가 있으면 연구인력에서 제외 (0~8)
        exact=[])),
    ('겸직', dict(
        include=["겸직", "visiting faculty", "방문 교수", "방문교수", "co-pi", "co-i",
                 "co-investigator", "pi 역할", "pi로 참여", "pi 로 참여", "editor",
                 "근무함", "근무기관", "postdoctoral research associate", "research fellow",
                 "자격", "멤버", "위임", "ambassadors", "이사회", "자원위원회",
                 "연구책임자", "대표 본인", "사업자등록"],
        exclude=[], exact=[])),
    ('금전', dict(
        include=_MONEY_KW_BASE + ["9"],  # 엑셀 B70: 금전 포함 키워드는 숫자 0~9
        exclude=[], exact=[])),
    ('유가증권', dict(
        include=["token", "토큰", "주식", "바우처", "royalty", "로열티", "크레딧", "노드", "node"],
        exclude=[], exact=[])),
    ('교통 및 숙박', dict(
        include=["항공", "비행기", "왕복", "교통", "숙박", "편도", "호텔", "hilton", "출장",
                 "여비", "숙식", "체재", "체류", "생활", "reimbursement", "일비", "식비",
                 "주거", "거주"],
        exclude=[], exact=[])),
    ('기타', dict(
        include=["잡비", "연구지원", "단순", "award", "기술교류", "기술 교류", "양성",
                 "지원사업", "구축사업", "공동 개최", "창업", "교육"],
        exclude=[], exact=["자문"])),  # 엑셀 B73: TRIM(사유)="자문" 정확 일치
])

# ── 산·학·연·기타 분류 키워드 (엑셀 통계분석!G67~G70 로직) ──────────────
YEON_KW = ["kist", "한국과학기술연구원", "nigt", "국가녹색기술연구소", "kbsi", "한국기초과학지원연구원",
           "기초연", "kfe", "한국핵융합에너지연구원", "kribb", "한국생명공학연구원", "생명연",
           "kisti", "한국과학기술정보연구원", "kiom", "한국한의학연구원", "kitech", "한국생산기술연구원",
           "생기원", "etri", "한국전자통신연구원", "nsr", "국가보안기술연구소", "kict", "한국건설기술연구원",
           "건설연", "건기연", "krri", "한국철도기술연구원", "철도연", "철기연", "kriss", "한국표준과학연구원",
           "kfri", "한국식품연구원", "wikim", "세계김치연구소", "kigam", "한국지질자원연구원",
           "kimm", "한국기계연구원", "kims", "한국재료연구원", "재료연", "kier", "한국에너지기술연구원",
           "keri", "한국전기연구원", "krict", "한국화학연구원", "화학연", "국가독성과학연구소",
           "kaeri", "한국원자력연구원", "기초과학연구원", "ibs", "iris", "중이온가속기연구소",
           "nmis", "국가수리과학연구소", "kvri", "한국바이러스기초연구소", "kaist", "한국과학기술원",
           "kias", "고등과학원", "nnfc", "나노종합기술원", "gist", "광주과학기술원",
           "dgist", "대구경북과학기술원", "kbri", "한국뇌연구원", "unist", "울산과학기술원",
           "한국나노기술원", "kanc"]
HAK_KW = ["대학교", "대학원", "university", "college", "univ.", "univ", "school of",
          "institute of technology", "mit", "caltech", "harvard", "stanford", "yale",
          "oxford", "cambridge", "princeton", "columbia", "cornell", "usc", "ucla",
          "ucsd", "ucsf", "uc berkeley", "eth", "epfl", "imperial", "ucl", "kcl",
          "학교", "학원"]
GITA_KW = ["병원", "의료원", "의료센터", "의료재단", "hospital", "medical center", "clinic",
           "nih", "nci", "한국연구재단", "nrf", "한국산업기술기획평가원", "keit", "정보통신기획평가원",
           "iitp", "정보통신산업진흥원", "nipa", "한국과학창의재단", "kofac", "한국데이터산업진흥원",
           "k-data", "한국인터넷진흥원", "kisa", "한국지능정보사회진흥원", "nia", "한국과학기술한림원",
           "kast", "국가과학기술인력개발원", "kird", "국가연구시설장비진흥센터", "nfec",
           "한국원자력의학원", "kirams", "소프트웨어정책연구소", "spri", "한국보건산업진흥원",
           "한국에너지기술평가원", "ketep", "한국환경산업기술원", "keiti", "국토교통과학기술진흥원",
           "kaia", "농림식품기술기획평가원", "ipet", "중소기업기술정보진흥원", "tipa",
           "한국해양과학기술진흥원", "kimst", "재단법인", "진흥원"]

# ── 과제 관련성 '관련 없음' 판정 키워드 (엑셀 통계분석!B61) ──────────────
UNRELATED_KW = ["n", "미존", "미관", "낮", "x", "-", "부", "없", "무관", "아니"]


def _s(v):
    """셀 값을 문자열로 정리."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    return str(v).strip()


def _contains_any(text, keywords):
    t = text.lower()
    return any(k in t for k in keywords)


def load_mappings(path):
    """매핑테이블.xlsx → (기관별칭 dict, 민감국가 dict, 소속정규화 dict)"""
    xls = pd.ExcelFile(path)
    a = pd.read_excel(xls, '기관별칭', dtype=str).fillna('')
    org_alias = {r.iloc[0].strip(): r.iloc[1].strip() for _, r in a.iterrows() if r.iloc[0].strip()}
    c = pd.read_excel(xls, '민감국가', dtype=str).fillna('')
    country_map = {r.iloc[0].strip(): r.iloc[1].strip() for _, r in c.iterrows() if r.iloc[0].strip()}
    n = pd.read_excel(xls, '소속정규화', dtype=str).fillna('')
    aff_norm = {r.iloc[0].strip(): r.iloc[1].strip() for _, r in n.iterrows() if r.iloc[0].strip()}
    return org_alias, country_map, aff_norm


def _read_sheet(path, preferred_names, col_names, rules, kind, do_preprocess):
    """raw 파일 읽기 → (정제 df, 전처리 내역).
    열은 머리글 이름으로 인식한다. 실제 raw 파일과 정제본은 열 위치가 한 칸
    어긋나 있어 위치 기준으로는 두 형식을 함께 처리할 수 없기 때문이다.
    머리글 인식에 실패하면 위치 기준으로 대체한다.
    '지원·지급 기간'이 시작·종료 두 칸으로 나뉘고 머리글만 병합된 경우
    (F1:G1 / J1:K1) 두 칸을 합쳐 종료일이 버려지지 않게 한다."""
    xls = pd.ExcelFile(path)
    sheet = next((s for s in xls.sheet_names if s in preferred_names), xls.sheet_names[0])
    df = pd.read_excel(xls, sheet, header=0, dtype=object)
    df, matched = resolve_columns(df, col_names)
    df = df[col_names]

    # 파일 종류 오선택 방지: 과제 raw 자리에 연구자 파일을 넣는 실수를 잡는다
    if kind == '과제 raw':
        has = any(_s(v) for v in df['과제번호']) or any(_s(v) for v in df['연구책임자'])
        if len(df) and not has:
            raise ValueError(
                '과제 raw 파일에 과제번호·연구책임자 열이 없습니다.\n'
                f'선택한 파일의 시트: [{sheet}]\n'
                '연구자 raw 파일을 과제 자리에 지정하지 않았는지 확인해 주세요.')
    else:
        if len(df) and not any(_s(v) for v in df['성명']):
            raise ValueError(
                '연구자 raw 파일에 성명 열이 없습니다.\n'
                f'선택한 파일의 시트: [{sheet}]\n'
                '과제 raw 파일을 연구자 자리에 지정하지 않았는지 확인해 주세요.')

    if do_preprocess:
        df, log = preprocess(df, rules, kind)
    else:
        df = df[df.apply(lambda r: any(_s(v) for v in r), axis=1)].reset_index(drop=True)
        log = {'구분': kind, '원본건수': len(df), '정제건수': len(df), '제거건수': 0,
               '단계': [('전처리 건너뜀', '이미 정제된 파일로 처리', 0)], '검토후보': []}
    log['열인식'] = '머리글 이름 기준' if matched else '열 위치 기준(머리글 인식 실패)'
    log['시트'] = sheet
    return df, log


def load_researcher_raw(path, rules=None, do_preprocess=True):
    return _read_sheet(path, ['연구자raw', '연구자 raw', '연구자'], RESEARCHER_COLS,
                       rules or DEFAULT_RULES, '연구자 raw', do_preprocess)


def load_project_raw(path, rules=None, do_preprocess=True):
    return _read_sheet(path, ['과제raw', '과제 raw', '과제'], PROJECT_COLS,
                       rules or DEFAULT_RULES, '과제 raw', do_preprocess)


def match_types(reason):
    """지원·지급 사유 → 매칭되는 유형 집합 (엑셀 B67~B73 다중 카운트 방식).
    포함 키워드 중 하나라도 있고 제외 키워드가 하나도 없으면 해당 유형에 집계.
    한 건이 여러 유형에 동시 집계될 수 있다.
    단, 어떤 유형에도 해당하지 않는 건(빈 사유 포함)은 '기타'로 집계하여
    모든 신고 건이 최소 한 유형에 속하도록 보장한다 (→ 유형합계 ≥ 총건수, 중복건수 ≥ 0)."""
    t = _s(reason)
    if not t:
        return {'기타'}
    low = t.lower()
    matched = set()
    for cat, rule in TYPE_RULES.items():
        hit = any(k in low for k in rule['include']) or (t in rule['exact'])
        if hit and rule['exclude'] and any(k in low for k in rule['exclude']):
            hit = False
        if hit:
            matched.add(cat)
    if not matched:
        matched.add('기타')
    return matched


def classify_sector(aff):
    """소속기관명 → 산/학/연/기타 (우선순위: 연 > 학 > 기타 > 산)"""
    t = _s(aff)
    if not t:
        return '기타'
    if _contains_any(t, YEON_KW):
        return '연'
    if _contains_any(t, HAK_KW):
        return '학'
    if _contains_any(t, GITA_KW):
        return '기타'
    return '산'


def is_unrelated(rel):
    """과제와의 관련성 → '관련 없음' 여부"""
    t = _s(rel)
    if not t:
        return None  # 빈 값은 합계에서 제외
    if t in ('.', '-'):
        return True
    return _contains_any(t, UNRELATED_KW)


def compute_stats(res_df, prj_df, org_alias, country_map, aff_norm):
    """전체 통계 산출 → dict"""
    R, P = res_df, prj_df
    S = {}

    # ── 정규화 열 추가 ──
    R = R.copy()
    R['출처기관_정규화'] = R['출처기관'].map(lambda v: org_alias.get(_s(v), _s(v)))
    R['소속_정규화'] = R['소속기관명'].map(lambda v: aff_norm.get(_s(v), _s(v)))
    R['국가'] = R['출처국가'].map(_s)
    R['성명_'] = R['성명'].map(_s)
    R['등록일'] = pd.to_datetime(R['NRI등록일자'], errors='coerce')

    # ── 기본 통계 ──
    S['총건수'] = len(R)
    S['총과제매핑건수'] = len(P)
    S['고유연구자수'] = R.loc[R['성명_'] != '', '성명_'].nunique()
    prj_pi = P['연구책임자'].map(_s)
    S['고유연책수'] = prj_pi[prj_pi != ''].nunique()
    S['국가수'] = R.loc[R['국가'] != '', '국가'].nunique()
    gov = pd.to_numeric(P['정부연구비'], errors='coerce')
    S['정부연구비합'] = float(gov.fillna(0).sum())
    pos = gov[gov > 0]
    S['정부연구비평균'] = float(pos.mean()) if len(pos) else 0.0
    pn = P['과제번호'].map(_s)
    S['고유과제수'] = pn[pn != ''].nunique()
    orgs = R.loc[R['출처기관_정규화'] != '', '출처기관_정규화']
    S['지원기관수'] = orgs.nunique()

    # ── 미매핑 연구자 (과제raw 연구책임자에 성명이 없는 연구자raw 행) ──
    pi_set = set(prj_pi[prj_pi != ''])
    unmapped = R[~R['성명_'].isin(pi_set) & (R['성명_'] != '')]
    S['미매핑연구자수'] = unmapped['성명_'].nunique()
    S['미매핑신고수'] = len(unmapped)
    S['미매핑리스트'] = unmapped[RESEARCHER_COLS].copy()

    # ── 보고의무 종료 연구자 (산출일 기준 지원·지급 기간이 끝난 경우) ──
    # 연구자 raw 전처리 데이터 기준. 한 연구자가 여러 건을 신고했을 수 있으므로,
    # 신고한 모든 건의 종료일이 지난 연구자만 '보고의무 종료'로 본다.
    # 종료일을 알 수 없는 건(미기재·형식 오류)이 하나라도 있으면 종료로 보지 않는다.
    today = pd.Timestamp(datetime.date.today())
    S['산출기준일'] = today.strftime('%Y-%m-%d')
    end = pd.to_datetime(R['지원지급종료일'], errors='coerce')
    R = R.assign(_end=end, _ended=end.notna() & (end < today))
    S['기간종료건수'] = int(R['_ended'].sum())
    S['종료일미상건수'] = int(end.isna().sum())

    named = R[R['성명_'] != '']
    if len(named):
        g = named.groupby('성명_')
        # 모든 건이 종료 + 종료일 미상이 하나도 없는 연구자
        done = g.apply(lambda d: bool(d['_ended'].all() and d['_end'].notna().all()),
                       include_groups=False)
        S['보고의무종료연구자수'] = int(done.sum())
        S['보고의무진행연구자수'] = int((~done).sum())
        S['보고의무종료명단'] = sorted(done[done].index.tolist())
    else:
        S['보고의무종료연구자수'] = 0
        S['보고의무진행연구자수'] = 0
        S['보고의무종료명단'] = []

    # ── 상위 국가 (Top 20 + 비율) ──
    cc = R.loc[R['국가'] != '', '국가'].value_counts()
    S['국가별'] = [(k, int(v), v / S['총건수'] if S['총건수'] else 0) for k, v in cc.items()]

    # ── 기관 Top 30 (별칭 통합 + 교차분석) ──
    top_org = []
    oc = orgs.value_counts()
    for org, cnt in oc.head(30).items():
        sub = R[R['출처기관_정규화'] == org]
        nat = next((x for x in sub['국가'] if x), '')
        affs = sorted({a for a in sub['소속_정규화'] if a})
        top_org.append((org, nat, ', '.join(affs), int(cnt)))
    S['기관Top30'] = top_org
    S['기관Top30합계'] = int(oc.head(30).sum())

    # ── 소속기관 Top 20 (보고건수/연구자수/지원기관) ──
    aff_cnt = R.loc[R['소속_정규화'] != '', '소속_정규화'].value_counts()
    top_aff = []
    for aff, cnt in aff_cnt.head(20).items():
        sub = R[R['소속_정규화'] == aff]
        nres = sub.loc[sub['성명_'] != '', '성명_'].nunique()
        sup = sorted({o for o in sub['출처기관_정규화'] if o})
        top_aff.append((aff, int(cnt), int(nres), ', '.join(sup)))
    S['소속Top20'] = top_aff

    # ── 다수 국제지원 수령 연구자 Top 10 ──
    rc = R.loc[R['성명_'] != '', '성명_'].value_counts()
    top_res = []
    for name, cnt in rc.head(10).items():
        sub = R[R['성명_'] == name]
        aff = next((a for a in sub['소속_정규화'] if a), '')
        sup = sorted({o for o in sub['출처기관_정규화'] if o})
        top_res.append((name, aff, ', '.join(sup), int(cnt)))
    S['연구자Top10'] = top_res

    # ── 연도별 / 월별 통계 (NRI 등록일자 기준, 데이터에 있는 기간 자동 인식) ──
    dt = R['등록일'].dropna()
    yc = dt.dt.year.value_counts().sort_index()
    S['연도별'] = [(int(y), int(c)) for y, c in yc.items()]
    mc = dt.dt.strftime('%Y-%m').value_counts().sort_index()
    S['월별'] = [(m, int(c)) for m, c in mc.items()]
    S['날짜인식건수'] = int(len(dt))

    # ── 과제 관련성 ──
    rel = P['과제와의관련성'].map(is_unrelated)
    total_rel = int(rel.notna().sum())
    unrelated = int((rel == True).sum())
    S['관련성'] = {'관련있음': total_rel - unrelated, '관련없음': unrelated, '합계': total_rel}

    # ── 지원·지급 유형별 (엑셀 B67~B73 다중 카운트: 한 건이 여러 유형에 집계 가능) ──
    type_sets = R['지원지급사유'].map(match_types)
    S['유형별'] = [(cat, int(type_sets.map(lambda s, c=cat: c in s).sum()))
                 for cat in TYPE_RULES.keys()]
    S['유형중복건수'] = sum(c for _, c in S['유형별']) - S['총건수']  # 엑셀 B75와 동일

    # ── 소속기관 유형별 (산·학·연·기타) ──
    sc = R['소속기관명'].map(classify_sector).value_counts()
    S['산학연'] = [(t, int(sc.get(t, 0))) for t in ['학', '연', '산', '기타']]

    # ── 연구보안 우려 (DOE 위험·민감국가) ──
    def grade(c):
        if c == '' or c == '한국':
            return ''
        return country_map.get(c, '')
    R['보안등급'] = R['국가'].map(grade)
    danger = R[R['보안등급'] == '위험국가']
    sensi = R[R['보안등급'] == '민감국가']
    S['보안'] = {'위험국가': len(danger), '민감국가': len(sensi)}
    detail = R[R['보안등급'] != ''][['보안등급', '국가', '출처기관_정규화', '소속_정규화',
                                     '지원지급내용', '지원지급사유']].copy()
    detail.columns = ['보안등급', '수혜국가', '지원기관(정규화)', '연구자 소속(정규화)',
                      '지원·지급 내용', '지원·지급 사유']
    S['보안세부'] = detail.reset_index(drop=True)

    S['_R'] = R  # 리포트용
    S['정제_연구자'] = res_df.copy()   # 전처리 이후 연구자 raw (리포트 수록용)
    S['정제_과제'] = prj_df.copy()     # 전처리 이후 과제 raw (리포트 수록용)
    return S
