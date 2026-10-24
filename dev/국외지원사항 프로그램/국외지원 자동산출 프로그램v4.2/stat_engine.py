# -*- coding: utf-8 -*-
"""
국외지원사항 자동 통계산출 엔진
기존 엑셀(v5)의 보조시트/통계분석 로직을 pandas로 재구현.
매핑 규칙은 '매핑테이블.xlsx'(기관별칭/민감국가/소속정규화)에서 읽어온다.
"""
import datetime
import os
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
# 각 유형은 여섯 가지 조건을 가진다.
#   include : 이 중 하나라도 있으면 후보 (그 자체로 유형을 확정할 수 있는 표현)
#   require : 후보가 된 뒤 이 중 하나가 더 있어야 확정 (비어 있으면 조건 없음)
#   exclude : 이 중 하나라도 있으면 탈락
#   exact   : 값 전체가 일치하면 후보
#   cond    : 조건부 후보 — 그 자체로는 유형을 확정할 수 없는 표현(활동명·숫자 등).
#             같은 텍스트에 아래 evid가 함께 있어야 확정된다.
#   evid    : cond 전용 확정 근거
# 특수 토큰 두 개를 쓸 수 있다.
#   {수량} : '숫자+명/인' 패턴 (예: 박사급 1명)
#   {금액} : '숫자+통화·금액단위' 패턴 (예: 50,000달러 · USD 3,000 · 3천만원 · $2,500)
#: '숫자 + 명/인'
QTY_PATTERN = re.compile(r'\d+\s*[명인]')
QTY_TOKEN = '{수량}'

#: 통화·금액 단위
_CUR = (r'원|달러|달라|불|엔|유로|위안|파운드|프랑|루피|페소|링깃|크로나|헤알|'
        r'krw|usd|eur|jpy|cny|rmb|gbp|chf|cad|sgd|aud|thb|nok|hkd|dm|'
        r'dollars?|euros?|yen|yuan|pounds?|won')
#: '숫자 + 통화·금액단위' — 금액이 실제로 적혀 있다는 근거
AMOUNT_PATTERN = re.compile(
    r'[$€£￡¥₩]\s*\d[\d,.]*'                                  # $2,500
    r'|\d[\d,.]*\s*[$€£￡¥₩]'                                 # 68000 $
    # 3천만원 · 1억 · 15백만원. 뒤가 명·인이면 수량이므로 제외한다(3백명).
    r'|\d[\d,.]*(?:\s*[백천만억조])+\s*(?:' + _CUR + r')?(?![명인])'
    r'|\d[\d,.]*\s*(?:' + _CUR + r')'                          # 50,000달러
    # 통화 표기가 먼저 오는 형태(USD 3,000). 앞이 글자면 낱말 일부이므로 제외한다
    # — 이 가드가 없으면 '지원 3건'의 `원 3`이 금액으로 잡힌다.
    r'|(?<![가-힣A-Za-z])(?:' + _CUR + r')\s*\d[\d,.]*',
    re.IGNORECASE)
AMOUNT_TOKEN = '{금액}'

# ── 금액 재판정 (기타로 남은 건을 마지막에 한 번 더 훑는다) ─────────────
# 위 AMOUNT_PATTERN은 '숫자와 통화가 붙어 있는' 표기만 인정한다. 실제 데이터에는
# 둘이 떨어져 있거나 통화가 아예 없는 금액 표기가 많다.
#
#   1050 미국 달러 연구 자문              숫자와 통화 사이에 낱말이 끼어 있다
#   5년간 총 200,000 (이십만) 유로        괄호가 끼어 있다
#   1,500,000/월 *12 = (총계) 18,000,000/년   통화 표기가 아예 없다
#   68000 $ per year                      통화 기호가 뒤에 있다
#
# 이런 건은 어떤 유형에도 걸리지 않아 기타로 떨어진다. 그래서 기타로 남은 건만
# 마지막에 느슨한 기준으로 다시 보고, 금액으로 판단되면 금전으로 되돌린다.
# 이미 다른 유형이 붙은 건은 건드리지 않으므로 오탐이 번지지 않는다.
#: 자릿점이 찍힌 수 — 1,500,000 · 200,000 (사람 수가 아닌 것만)
_NUM_GROUPED = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\s*[명인건개])')
#: 아무 수
_NUM_ANY = re.compile(r'\d[\d,.]*')
#: 통화 표기 — 기호는 그대로, 낱말은 앞뒤가 글자가 아닐 때만
_CUR_TOKEN = re.compile(
    r'[$€£￡¥₩]|(?<![가-힣A-Za-z])(?:' + _CUR + r'|원화|엔화|달러화|미화|한화)(?![가-힣])',
    re.IGNORECASE)

# 금전 — 돈을 받았다는 근거가 있어야 한다.
#
# 아래 STRONG은 그 자체로 금전이 확정되는 표현이고, COND는 '공동연구'처럼
# 금전일 수도 아닐 수도 있는 활동명·구조 표현이다. COND는 금액 표현이나
# STRONG이 같은 칸에 함께 있을 때만 금전으로 본다.
#
# 이전에는 둘을 구분하지 않아, 지원·지급 내용에 돈이 전혀 없는 공동연구나
# 장비만 받은 공동연구가 모두 금전으로 집계됐다. 특히 `원`(→ 지원·연구원·원자력),
# `료`(→ 재료·자료), 낱개 숫자 `0`~`9`(→ 연도·횟수·수량)가 포함 키워드로 들어 있어
# 금전이 과다하게 잡혔다.
_MONEY_STRONG = ["인건비", "급여", "월급", "연봉", "임금", "호봉", "salary", "stipend",
                 "연구비", "과제비", "연구활동비", "연구수당", "연구장려금", "장려금",
                 "grant", "funding", "fellowship", "펠로우십", "지원금", "보조금",
                 "학비", "등록금", "장학", "입금액", "입금금액", "재료비",
                 "자문료", "자문비", "강의료", "강연료", "강의비", "honorarium",
                 "수강료", "교육비", "용역비", "용역수행금", "보수", "물품대금",
                 "미화", "한화", "송금", "지급액", "수령액", "상금", "포상금"]
_MONEY_COND = ["공동연구", "수탁연구", "산학과제", "산학연구", "연구지원", "연구과제",
               "누적과제", "employee", "full", "료", "/", "자문계약",
               "consulting", "consultant", "컨설팅", "기술자문", "기술 자문",
               "기술교류", "기술 교류", "교류", "협력연구", "국제공동연구",
               "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]

MONEY_CAT = '금전'

#: 금전의 '포함' 키워드로 두면 오탐이 큰 표현 — 조건부로 내린다.
#: 통화 낱말도 여기 넣는다. 낱말만으로는 금액이 적혀 있다는 근거가 못 되고
#: (`원` → 지원·연구원·원자력), 실제 금액은 {금액} 패턴이 잡아낸다.
_MONEY_DEMOTE = set(_MONEY_COND) | {
    "원", "억", "천원", "만원", "달러", "달라", "달라화", "엔", "유로", "위안", "불",
    "파운드", "usd", "eur", "jpy", "krw", "cny", "rmb", "gbp", "chf", "cad", "sgd",
    "aud", "thb", "nok", "hkd", "dm", "yuan", "yen", "euro", "pound", "won",
    "$", "￡", "€", "¥", "₩"}

TYPE_RULES = OrderedDict([
    # (표시명, 포함 키워드, 제외 키워드, 정확일치 키워드)
    ('연구장비 및 시설', dict(
        include=["장비", "기자재", "기기", "설비", "gpu", "cpu", "서버", "슈퍼컴퓨터", "로봇",
                 "자석", "reactor", "scanner", "분석기", "실험장비", "연구장비", "시험연구장비",
                 "node hours", "exaflop", "소자", "소프트웨어", "하드웨어", "software",
                 "시설", "실험실", "연구실", "연구공간", "방문 공간", "사무 공간", "사무공간",
                 "사무소", "시험소", "laboratory", "computing facility", "생산라인",
                 "창업 보육", "자원", "연구자원", "연구시설", "오가노이드", "api"],
        require=[], exclude=[], exact=[])),
    # 연구인력은 '행정적 지원', 즉 사람을 받은 경우다. 인건비·급여만 받은 경우는
    # 금전으로 남긴다. 원본 수식은 이를 '금액·숫자가 있으면 제외'로 구현해
    # '박사급 1명'처럼 인원수만 적어도 탈락했다. 그래서 소극적 배제 대신
    # '인원수 표현 또는 제공성 표현'을 필수 조건으로 둔다.
    ('연구인력', dict(
        include=["박사급", "박사후", "포닥", "postdoc", "박사과정", "석박사", "박사", "석사",
                 "학사", "연구원", "참여연구원", "연구인력", "인력", "인턴", "학생",
                 "전임교원", "교원", "research associate", "research fellow",
                 "phd student", "연구조교", "보조원"],
        require=[QTY_TOKEN, "인력 제공", "인력제공", "인력 지원", "인력지원", "인력활용",
                 "인력 활용", "파견", "배정", "채용", "고용", "투입", "제공받", "배치",
                 "충원", "인력 교류", "인력교류"],
        exclude=[], exact=[])),
    ('겸직', dict(
        include=["겸직", "visiting faculty", "방문 교수", "방문교수", "co-pi", "co-i",
                 "co-investigator", "pi 역할", "pi로 참여", "pi 로 참여", "editor",
                 "근무함", "근무기관", "postdoctoral research associate", "research fellow",
                 "자격", "멤버", "위임", "ambassadors", "이사회", "자원위원회",
                 "연구책임자", "대표 본인", "사업자등록"],
        require=[], exclude=[], exact=[])),
    ('금전', dict(
        include=_MONEY_STRONG + [AMOUNT_TOKEN],
        require=[], exclude=[], exact=[],
        # 활동명·낱개 숫자는 금액 표현이나 명시적 금전 표현이 함께 있어야 금전으로 본다.
        cond=_MONEY_COND,
        evid=[AMOUNT_TOKEN] + _MONEY_STRONG)),
    ('유가증권', dict(
        include=["token", "토큰", "주식", "바우처", "royalty", "로열티", "크레딧", "노드", "node"],
        require=[], exclude=[], exact=[])),
    ('교통 및 숙박', dict(
        include=["항공", "비행기", "왕복", "교통", "숙박", "편도", "호텔", "hilton", "출장",
                 "여비", "숙식", "체재", "체류", "생활", "reimbursement", "일비", "식비",
                 "주거", "거주"],
        require=[], exclude=[], exact=[])),
    # 기타는 '잔여 유형'이다. 규칙 판정에 참여하지 않으며,
    # 다른 여섯 유형이 하나도 걸리지 않은 건에만 붙는다.
    #
    # 이전에는 기타도 다른 유형과 동등하게 판정됐고, 포함 키워드가
    # '연구지원·교육·창업·양성·지원사업·award'처럼 넓어서 이미 금전·연구인력
    # 등으로 분류된 건에 기타가 중복으로 따라붙었다(기타 건수 과다).
    # 이제 include는 비워 두고 아래 OTHER_KW로 근거만 남긴다.
    ('기타', dict(include=[], require=[], exclude=[], exact=[])),
])

OTHER_CAT = '기타'

#: 기타로 인정하는 표현. 다른 유형에 걸리지 않은 건의 '판정 근거'로만 쓰인다.
#: 물건·돈·사람을 받은 것이 아니라 교류·양성·논의 성격인 경우다.
OTHER_KW = ["기술교류", "기술 교류", "인력양성", "인력 양성", "단순논의", "단순 논의"]

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

# ── 산출기준일 (raw 파일명에서 추출) ────────────────────────────────
# 통계의 기준 시점은 프로그램을 돌린 날이 아니라 raw를 내려받은 날이다.
# 며칠 뒤에 다시 돌려도 같은 raw면 같은 보고서가 나와야 하므로,
# 파일명에 적힌 날짜를 산출기준일로 쓴다.
#
#   국외지원사항_20260727.xlsx      → 2026-07-27
#   국외지원사항(2026.07.27).xlsx   → 2026-07-27
#   국외지원 26-07-27 최종.xlsx     → 2026-07-27
#   2026년 7월 27일 기준.xlsx       → 2026-07-27
#
#: 네 자리 연도 — 구분자는 있어도 없어도 된다
_DATE_Y4 = re.compile(r'(?<!\d)(20\d{2})\s*[.\-_/년]?\s*(\d{1,2})\s*[.\-_/월]?\s*(\d{1,2})\s*일?(?!\d)')
#: 두 자리 연도 — 구분자가 반드시 있어야 한다 (버전 번호 등과 섞이지 않게)
_DATE_Y2 = re.compile(r'(?<!\d)(\d{2})[.\-_/](\d{1,2})[.\-_/](\d{1,2})(?!\d)')


def date_from_filename(path):
    """파일명에서 연·월·일을 뽑아 date로 돌려준다. 없으면 None.

    실제로 존재하는 날짜만 인정한다(2026.13.01 같은 값은 건너뛴다).
    네 자리 연도를 먼저 찾고, 없을 때만 두 자리 연도를 본다."""
    if not path:
        return None
    name = os.path.basename(str(path))
    name = name.rsplit('.', 1)[0] if '.' in name else name   # 확장자 제거
    for rx, base in ((_DATE_Y4, 0), (_DATE_Y2, 2000)):
        for m in rx.finditer(name):
            y, mo, d = int(m.group(1)) + base, int(m.group(2)), int(m.group(3))
            try:
                return datetime.date(y, mo, d)
            except ValueError:
                continue
    return None


def resolve_base_date(*paths):
    """raw 파일명들에서 산출기준일을 정한다.
    → (기준일, 근거 문구). 어디에서도 못 찾으면 오늘 날짜로 대체한다."""
    for p in paths:
        d = date_from_filename(p)
        if d:
            return d, f'{d:%Y-%m-%d} — {os.path.basename(str(p))}'
    return datetime.date.today(), ''


def _s(v):
    """셀 값을 문자열로 정리."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    return str(v).strip()


def norm_researcher_id(v):
    """국가연구자번호 정규화.
    엑셀에서 숫자로 읽혀 '12345678.0'이 되는 경우와 하이픈·공백 표기를 흡수한다.
    앞자리 0이 의미를 가질 수 있으므로 0 제거는 하지 않는다."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, float) and float(v).is_integer():
        return str(int(v))
    t = str(v).strip()
    if t.endswith('.0') and t[:-2].isdigit():
        t = t[:-2]
    return re.sub(r'[\s\-]', '', t)


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


def check_mapping_conflicts(map_path):
    """매핑테이블의 별칭 충돌 점검.
    같은 원본명이 서로 다른 정규화명으로 적혀 있으면 통합이 깨져 한 기관이
    둘로 나뉘어 집계된다. 마지막 행이 조용히 이기므로 미리 알려야 한다.
    → [(시트, 원본명, [정규화명들]), ...]"""
    out = []
    try:
        xls = pd.ExcelFile(map_path)
        for sheet in ('기관별칭', '소속정규화'):
            if sheet not in xls.sheet_names:
                continue
            df = pd.read_excel(xls, sheet, dtype=str).fillna('')
            if df.shape[1] < 2:
                continue
            src = df.iloc[:, 0].map(lambda v: _s(v))
            dst = df.iloc[:, 1].map(lambda v: _s(v))
            seen = {}
            for a, b in zip(src, dst):
                if not a or not b:
                    continue
                seen.setdefault(a, set()).add(b)
            for a, bs in seen.items():
                if len(bs) > 1:
                    out.append((sheet, a, sorted(bs)))
    except Exception:
        pass
    return out


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


def _first_token(t, low, tokens):
    """목록에서 처음 걸리는 표현. {수량}·{금액}은 패턴으로 본다."""
    for k in tokens or ():
        if k == QTY_TOKEN:
            m = QTY_PATTERN.search(t)
            if m:
                return m.group(0)
        elif k == AMOUNT_TOKEN:
            m = AMOUNT_PATTERN.search(t)
            if m:
                return m.group(0).strip()
        elif k in low:
            return k
    return None


def _rule_hit(text, rule):
    """한 유형 규칙에 대한 판정. 맞으면 근거 키워드, 아니면 None."""
    t = _s(text)
    if not t:
        return None
    low = t.lower()
    why = _first_token(t, low, rule.get('include'))
    if why is None and t in rule.get('exact', ()):
        why = f'="{t}"'
    if why is not None:
        # include·exact 후보 — require가 있으면 하나 더 있어야 확정
        got = _first_token(t, low, rule.get('require'))
        if (rule.get('require') or []) and got is None:
            return None
        if got is not None:
            why = f'{why}+{got}'
    else:
        # 조건부 후보 — 그 자체로는 유형을 확정할 수 없는 표현.
        # 같은 텍스트에 근거(evid)가 함께 있어야 확정한다.
        cand = _first_token(t, low, rule.get('cond'))
        if cand is None:
            return None
        got = _first_token(t, low, rule.get('evid'))
        if got is None:
            return None
        why = f'{cand}+{got}'
    exc = rule.get('exclude') or []
    if exc and any(k in low for k in exc):
        return None
    return why


def _other_hit(text):
    """기타 표현(기술교류·인력양성·단순논의) 탐지 → 걸린 표현 또는 None."""
    t = _s(text)
    if not t:
        return None
    low = t.lower()
    return next((k for k in OTHER_KW if k in low), None)


def looks_like_money(text):
    """느슨한 금액 판정 — 기타로 남은 건을 되돌릴 때만 쓴다.
    금액으로 볼 근거가 있으면 그 문구를, 없으면 None을 돌려준다."""
    t = _s(text)
    if not t:
        return None
    # ① 자릿점이 찍힌 수 — 통화 표기가 없어도 금액으로 본다
    #    (1,500,000/월 · 18,000,000/년). 뒤가 명·인·건·개면 수량이므로 제외한다.
    m = _NUM_GROUPED.search(t)
    if m:
        return m.group(0)
    # ② 통화 표기와 수가 같은 칸에 함께 있으면 떨어져 있어도 금액으로 본다
    #    (1050 미국 달러 · 68000 $ per year)
    c = _CUR_TOKEN.search(t)
    if c:
        n = _NUM_ANY.search(t)
        if n:
            return f'{n.group(0)}+{c.group(0).strip()}'
    # ③ 엄격한 금액 패턴 (3천만원 등)
    m = AMOUNT_PATTERN.search(t)
    if m:
        return m.group(0).strip()
    return None


def ordered_types(rules=None):
    """표시·집계 순서. 기타는 잔여 유형이므로 항상 마지막에 한 번만 온다.
    매핑테이블 [유형규칙] 시트에 기타 행이 없어도 유형 목록에서 빠지지 않는다."""
    rules = rules or TYPE_RULES
    return [c for c in rules.keys() if c != OTHER_CAT] + [OTHER_CAT]


def match_types(reason, fallback=True, rules=None):
    """지원·지급 사유/내용 → 매칭되는 유형 집합 (다중 카운트).
    기타는 판정에 참여하지 않으며, fallback=True일 때 아무 유형에도
    걸리지 않은 경우에만 '기타'로 돌려준다."""
    rules = rules or TYPE_RULES
    t = _s(reason)
    if not t:
        return {OTHER_CAT} if fallback else set()
    matched = {cat for cat, rule in rules.items()
               if cat != OTHER_CAT and _rule_hit(t, rule) is not None}
    if not matched and fallback:
        matched.add(OTHER_CAT)
    return matched


def match_types_detail(reason, content, rules=None):
    """사유·내용을 각각 판정하고 근거를 함께 돌려준다.
    → {유형: [(열이름, 근거키워드), ...]}

    두 열을 한 문자열로 이어붙이지 않는 이유: '연구인력'의 필수 조건이나
    다른 유형의 제외 조건이 상대 열의 내용 때문에 잘못 발동하는 것을 막기 위해서다.

    기타 처리
      기타는 다른 유형과 함께 붙지 않는다. 여섯 유형 중 하나라도 걸리면
      기타를 달지 않고, 하나도 걸리지 않은 건에만 기타를 준다.
      그 건이 OTHER_KW(기술교류·인력양성·단순논의)에 해당하면 근거를 남기고,
      아니면 근거 없이 '어떤 유형에도 미해당'으로 남는다.

      단, 기타로 떨어지기 직전에 금액 재판정을 한 번 거친다. 금액으로 판단되면
      기타가 아니라 금전으로 돌린다(looks_like_money 참고)."""
    rules = rules or TYPE_RULES
    out = {}
    other_ev = []
    for col, text in (('사유', reason), ('내용', content)):
        t = _s(text)
        if not t:
            continue
        for cat, rule in rules.items():
            if cat == OTHER_CAT:
                continue          # 기타는 잔여 유형 — 규칙 판정에서 제외
            why = _rule_hit(t, rule)
            if why is not None:
                out.setdefault(cat, []).append((col, why))
        k = _other_hit(t)
        if k:
            other_ev.append((col, k))
    if not out:
        # 기타로 떨어지기 전 마지막 진단 — 금액이 적혀 있으면 금전으로 되돌린다
        if MONEY_CAT in rules:
            rescue = []
            for col, text in (('사유', reason), ('내용', content)):
                w = looks_like_money(text)
                if w:
                    rescue.append((col, f'금액재판정 {w}'))
            if rescue:
                return {MONEY_CAT: rescue}
        out = {OTHER_CAT: other_ev}
    return out


def match_types_pair(reason, content, rules=None):
    """사유·내용 각각 판정 후 합집합."""
    return set(match_types_detail(reason, content, rules).keys())


def harden_money(rule):
    """금전 규칙 보정 — 활동명·낱개 숫자·통화 낱말은 '조건부'로 내리고 근거를 붙인다.

    매핑테이블 [유형규칙] 시트에 예전 포함 키워드(`공동연구`·`료`·`원`·`0`~`9` 등)가
    남아 있어도 코드와 같은 판정이 되게 한다. 돈을 받았다는 근거({금액} 또는
    명시적 금전 표현)가 없으면 금전으로 보지 않는다."""
    inc_all = list(rule.get('include') or [])
    inc = [k for k in inc_all if k not in _MONEY_DEMOTE]
    dem = [k for k in inc_all if k in _MONEY_DEMOTE]
    if AMOUNT_TOKEN not in inc:
        inc.append(AMOUNT_TOKEN)
    cond = list(dict.fromkeys(list(rule.get('cond') or []) + dem))
    evid = list(rule.get('evid') or []) or [AMOUNT_TOKEN] + _MONEY_STRONG
    return dict(rule, include=inc, cond=cond, evid=evid)


def load_type_rules(map_path):
    """매핑테이블.xlsx의 '유형규칙' 시트 → 규칙 dict. 없으면 기본 규칙."""
    try:
        xls = pd.ExcelFile(map_path)
        if '유형규칙' not in xls.sheet_names:
            return TYPE_RULES
        df = pd.read_excel(xls, '유형규칙', dtype=str).fillna('')
        if df.shape[1] < 3:
            return TYPE_RULES
        kind_map = {'포함': 'include', '필수': 'require', '제외': 'exclude', '정확일치': 'exact',
                    '조건부': 'cond', '근거': 'evid'}
        rules = OrderedDict()
        for _, row in df.iterrows():
            cat = str(row.iloc[0]).strip()
            kind = kind_map.get(str(row.iloc[1]).strip())
            val = str(row.iloc[2])
            if not cat or not kind or val.strip() == '':
                continue
            rules.setdefault(cat, {'include': [], 'require': [], 'exclude': [],
                                   'exact': [], 'cond': [], 'evid': []})
            rules[cat][kind].append(val if kind == 'exact' else val.strip().lower())
        if not rules:
            return TYPE_RULES
        if MONEY_CAT in rules:
            rules[MONEY_CAT] = harden_money(rules[MONEY_CAT])
        return rules
    except Exception:
        return TYPE_RULES


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


# ── 과제 관련성 판정 (원본 엑셀 B61의 단일 문자 부분일치 오작동을 보정) ──────
# 원본은 "부", "n" 같은 한 글자를 부분일치로 찾아 '1세부 공동연구기관', 'Stipend',
# '자격 부여', '일부 관련' 등을 모두 '관련 없음'으로 잘못 판정했다.
# 한 글자 응답은 완전일치로만 보고, 서술문은 어구 단위로 판정한다.

#: 단독 응답 (앞뒤 공백·마침표 제거 후 완전일치)
REL_NO_EXACT = {'무', '부', '해당무', '무함', '없', '없음', '미존', '미존재', '미관', '미관련',
                '아니', '아니오', '아니요', '해당없음', '해당 없음', '해당사항없음', '해당사항 없음',
                'n', 'no', 'none', 'not related', 'x', '-', '--', '.', '·', '불가'}
REL_YES_EXACT = {'유', '여', '네', '예', '오', 'o', 'y', 'yes', '있음', '관련', '관련있음',
                 '관련 있음', '해당', '유관', '일치', '본인', '포함', '연구책임자'}

#: 명확한 부정 어구 — 있으면 관련 없음
REL_NO_STRONG = ['관련없', '관련 없', '관련이 없', '관련성없', '관련성 없', '관련성이 없',
                 '관계없', '관계 없', '관계가 없', '연관없', '연관 없', '연관성없', '연관성 없',
                 '연관성이 없', '상관없', '상관 없', '무관', '해당없', '해당 없', '해당사항없',
                 '해당사항 없', '관련사항없', '관련사항 없', '관련여부없', '관련여부 없',
                 '관련 여부 없', '관련내용 없', '관련 사항 없', '미존재', '미관련', '무함',
                 '없습니', '없으며', '없으나', '없다', '연관 없', '연광성이 없']
#: 명확한 긍정 어구 — 부정 어구가 없을 때 관련 있음
REL_YES_STRONG = ['관련이 있', '관련 있', '관련있', '관련성이 있', '관련성 있', '관련성을 갖',
                  '연관 있', '연관성 있', '연관성이 있', '연관됨', '관련됨', '관련함', '관련된',
                  '높은 관련', '직접 관련이 있', '관련이 높']
#: 약한 부정 어구 — 명확한 긍정이 없을 때 관련 없음
REL_NO_WEAK = ['상이', '다름', '다르', '별개', '차별성', '독립적', '관련성 낮', '관련 낮',
               '관련성이 낮', '연관성 낮', '직접적 관련은 없', '무관함']


def is_unrelated(rel):
    """과제와의 관련성 → 관련 없음이면 True, 관련 있음이면 False, 빈 값이면 None."""
    t = _s(rel)
    if not t:
        return None
    key = re.sub(r'[\s.,;·]+$', '', t).strip().lower()
    if key in REL_NO_EXACT:
        return True
    if key in REL_YES_EXACT:
        return False
    low = t.lower()
    if any(k in low for k in REL_NO_STRONG):
        return True
    if any(k in low for k in REL_YES_STRONG):
        return False
    if any(k in low for k in REL_NO_WEAK):
        return True
    return False


def compute_stats(res_df, prj_df, org_alias, country_map, aff_norm, type_rules=None,
                  base_date=None):
    """전체 통계 산출 → dict

    base_date는 산출기준일이다. raw 파일명에서 뽑은 날짜를 넘긴다.
    보고의무 종료 판정이 이 날짜를 기준으로 이뤄지므로, 며칠 뒤에 다시 돌려도
    같은 raw면 같은 결과가 나온다. 넘기지 않으면 오늘 날짜를 쓴다."""
    R, P = res_df, prj_df
    S = {}

    # ── 정규화 열 추가 ──
    R = R.copy()
    R['출처기관_정규화'] = R['출처기관'].map(lambda v: org_alias.get(_s(v), _s(v)))
    R['소속_정규화'] = R['소속기관명'].map(lambda v: aff_norm.get(_s(v), _s(v)))
    R['국가'] = R['출처국가'].map(_s)
    R['성명_'] = R['성명'].map(_s)
    R['등록일'] = pd.to_datetime(R['NRI등록일자'], errors='coerce')

    # 연구자 식별은 국가연구자번호 기준. 번호가 없으면 성명으로 대체해
    # 해당 인원이 집계에서 누락되지 않게 한다.
    R['연구자ID'] = R['국가연구자번호'].map(norm_researcher_id)
    R['연구자키'] = [rid if rid else (f'성명:{nm}' if nm else '')
                  for rid, nm in zip(R['연구자ID'], R['성명_'])]
    P = P.copy()
    P['연책ID'] = P['국가연구자번호'].map(norm_researcher_id)
    P['연책명'] = P['연구책임자'].map(_s)
    P['연책키'] = [rid if rid else (f'성명:{nm}' if nm else '')
                 for rid, nm in zip(P['연책ID'], P['연책명'])]

    # 키 → 대표 성명 (표시용)
    name_of = {}
    for k, nm in zip(R['연구자키'], R['성명_']):
        if k and nm and k not in name_of:
            name_of[k] = nm
    for k, nm in zip(P['연책키'], P['연책명']):
        if k and nm and k not in name_of:
            name_of[k] = nm
    S['_이름표'] = name_of

    # 데이터 품질 점검: 번호 미기재 / 한 번호에 서로 다른 성명이 붙은 경우
    S['번호미기재건수'] = int((R['연구자ID'] == '').sum())
    conflicts = []
    bad_ids = set()
    for rid, grp in R[R['연구자ID'] != ''].groupby('연구자ID')['성명_']:
        names = sorted({n for n in grp if n})
        if len(names) > 1:
            conflicts.append((rid, ', '.join(names), int(len(grp))))
            bad_ids.add(rid)
    S['번호중복인물'] = sorted(conflicts, key=lambda x: -x[2])

    # 한 번호에 여러 성명이 붙은 경우(마스킹된 더미 번호 등)는 그 번호를 식별자로
    # 쓸 수 없다. 해당 건만 '번호+성명'으로 분리해 서로 다른 인물이 한 명으로
    # 합쳐지는 사고를 막는다. 나머지는 그대로 번호 기준을 유지한다.
    if bad_ids:
        R['연구자키'] = [f'{rid}|{nm}' if rid in bad_ids else k
                      for k, rid, nm in zip(R['연구자키'], R['연구자ID'], R['성명_'])]
        P['연책키'] = [f'{rid}|{nm}' if rid in bad_ids else k
                     for k, rid, nm in zip(P['연책키'], P['연책ID'], P['연책명'])]
        name_of = {}
        for k, nm in zip(R['연구자키'], R['성명_']):
            if k and nm and k not in name_of:
                name_of[k] = nm
        for k, nm in zip(P['연책키'], P['연책명']):
            if k and nm and k not in name_of:
                name_of[k] = nm
        S['_이름표'] = name_of

    # ── 기본 통계 ──
    S['총건수'] = len(R)
    S['총과제매핑건수'] = len(P)
    S['고유연구자수'] = R.loc[R['연구자키'] != '', '연구자키'].nunique()
    prj_pi = P['연책키']
    S['고유연책수'] = prj_pi[prj_pi != ''].nunique()
    S['국가수'] = R.loc[R['국가'] != '', '국가'].nunique()
    # 정부연구비는 같은 과제가 여러 행에 나오므로 과제번호 기준으로 중복을 제거한다.
    # (행 단위로 더하면 다수 신고가 있는 과제의 예산이 여러 번 합산돼 크게 부풀려진다)
    gov = pd.to_numeric(P['정부연구비'], errors='coerce')
    pn = P['과제번호'].map(_s)
    budget = P.assign(_g=gov, _pn=pn)
    ded = pd.concat([budget[budget['_pn'] != ''].drop_duplicates('_pn'),
                     budget[budget['_pn'] == '']])
    S['정부연구비합'] = float(ded['_g'].fillna(0).sum())
    pos = ded['_g'][ded['_g'] > 0]
    S['정부연구비평균'] = float(pos.mean()) if len(pos) else 0.0
    S['정부연구비행합'] = float(gov.fillna(0).sum())   # 참고용(중복 미제거)
    S['고유과제수'] = pn[pn != ''].nunique()
    orgs = R.loc[R['출처기관_정규화'] != '', '출처기관_정규화']
    S['지원기관수'] = orgs.nunique()

    # ── 미매핑 연구자 (과제raw 연구책임자에 없는 연구자raw 행) ──
    pi_set = set(prj_pi[prj_pi != ''])
    unmapped = R[~R['연구자키'].isin(pi_set) & (R['연구자키'] != '')]
    S['미매핑연구자수'] = unmapped['연구자키'].nunique()
    S['미매핑신고수'] = len(unmapped)
    # 과제 협약 시 보고된 건수 = 전체 신고 - 과제매핑 미진행 신고
    S['협약보고건수'] = S['총건수'] - S['미매핑신고수']
    S['미매핑리스트'] = unmapped[RESEARCHER_COLS].copy()

    # ── 보고의무 종료 연구자 (산출일 기준 지원·지급 기간이 끝난 경우) ──
    # 연구자 raw 전처리 데이터 기준. 한 연구자가 여러 건을 신고했을 수 있으므로,
    # 신고한 모든 건의 종료일이 지난 연구자만 '보고의무 종료'로 본다.
    # 종료일을 알 수 없는 건(미기재·형식 오류)이 하나라도 있으면 종료로 보지 않는다.
    today = pd.Timestamp(base_date or datetime.date.today())
    S['산출기준일'] = today.strftime('%Y-%m-%d')
    end = pd.to_datetime(R['지원지급종료일'], errors='coerce')
    R = R.assign(_end=end, _ended=end.notna() & (end < today))
    S['기간종료건수'] = int(R['_ended'].sum())
    S['종료일미상건수'] = int(end.isna().sum())

    named = R[R['연구자키'] != '']
    if len(named):
        g = named.groupby('연구자키')
        # 모든 건이 종료 + 종료일 미상이 하나도 없는 연구자
        done = g.apply(lambda d: bool(d['_ended'].all() and d['_end'].notna().all()),
                       include_groups=False)
        ended_keys = list(done[done].index)
        S['보고의무종료연구자수'] = int(done.sum())
        S['보고의무진행연구자수'] = int((~done).sum())
        S['보고의무종료명단'] = sorted(name_of.get(k, k) for k in ended_keys)
        # 연구책임자 여부는 과제 raw의 연구책임자(국가연구자번호) 기준
        pi_ended = [k for k in ended_keys if k in pi_set]
        S['보고의무종료연책수'] = len(pi_ended)
        S['보고의무종료일반수'] = len(ended_keys) - len(pi_ended)
        S['보고의무종료연책명단'] = sorted(name_of.get(k, k) for k in pi_ended)

        # ── 보고의무 종료 연구자 명세 (별도 시트용) ──
        rows = []
        for key in ended_keys:
            sub = named[named['연구자키'] == key]
            last = sub['_end'].max()
            aff = next((a for a in sub['소속_정규화'] if a), '')
            sups = sorted({o for o in sub['출처기관_정규화'] if o})
            nats = sorted({c for c in sub['국가'] if c})
            rid = next((i for i in sub['연구자ID'] if i), '')
            rows.append({
                '성명': name_of.get(key, ''),
                '국가연구자번호': rid or '(미기재)',
                '구분': '연구책임자' if key in pi_set else '일반연구자',
                '소속기관(정규화)': aff,
                '신고 건수': len(sub),
                '최종 종료일': last.strftime('%Y-%m-%d') if pd.notna(last) else '',
                '경과일': int((today - last).days) if pd.notna(last) else '',
                '지원·지급 국가': ', '.join(nats),
                '지원기관(정규화)': ', '.join(sups),
            })
        detail = pd.DataFrame(rows, columns=['성명', '국가연구자번호', '구분', '소속기관(정규화)',
                                             '신고 건수', '최종 종료일', '경과일',
                                             '지원·지급 국가', '지원기관(정규화)'])
        if len(detail):
            detail = detail.sort_values('최종 종료일', ascending=True,
                                        kind='mergesort').reset_index(drop=True)
        S['보고의무종료명세'] = detail
        S['보고의무종료신고건수'] = int(detail['신고 건수'].sum()) if len(detail) else 0
    else:
        S['보고의무종료연구자수'] = 0
        S['보고의무진행연구자수'] = 0
        S['보고의무종료명단'] = []
        S['보고의무종료연책수'] = 0
        S['보고의무종료일반수'] = 0
        S['보고의무종료연책명단'] = []
        S['보고의무종료명세'] = pd.DataFrame(
            columns=['성명', '국가연구자번호', '구분', '소속기관(정규화)', '신고 건수',
                     '최종 종료일', '경과일', '지원·지급 국가', '지원기관(정규화)'])
        S['보고의무종료신고건수'] = 0

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
        nres = sub.loc[sub['연구자키'] != '', '연구자키'].nunique()
        sup = sorted({o for o in sub['출처기관_정규화'] if o})
        top_aff.append((aff, int(cnt), int(nres), ', '.join(sup)))
    S['소속Top20'] = top_aff

    # ── 다수 국제지원 수령 연구자 Top 10 ──
    rc = R.loc[R['연구자키'] != '', '연구자키'].value_counts()
    top_res = []
    for key, cnt in rc.head(10).items():
        sub = R[R['연구자키'] == key]
        aff = next((a for a in sub['소속_정규화'] if a), '')
        sup = sorted({o for o in sub['출처기관_정규화'] if o})
        top_res.append((name_of.get(key, key), aff, ', '.join(sup), int(cnt)))
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
    trules = type_rules or TYPE_RULES
    details = [match_types_detail(a, b, trules)
               for a, b in zip(R['지원지급사유'], R['지원지급내용'])]
    cats = ordered_types(trules)
    type_sets = pd.Series([set(d.keys()) for d in details], index=R.index)
    S['유형별'] = [(cat, int(type_sets.map(lambda s, c=cat: c in s).sum()))
                 for cat in cats]

    # ── 유형 분류 내역 (건별 판정 근거, 별도 시트용) ──
    rows = []
    for (idx, row), det in zip(R.iterrows(), details):
        for cat in cats:
            if cat not in det:
                continue
            ev = det[cat]
            rows.append({
                '번호': row['번호'],
                '성명': row['성명_'],
                '유형': cat,
                '판정 열': ', '.join(sorted({c for c, _ in ev})) if ev else '(미분류→기타)',
                '판정 근거': ', '.join(f'{c}:{w}' for c, w in ev) if ev else '어떤 유형에도 미해당',
                '분류된 유형 수': len(det),
                '지원·지급 사유': _s(row['지원지급사유']),
                '지원·지급 내용': _s(row['지원지급내용']),
            })
    S['유형분류내역'] = pd.DataFrame(rows, columns=[
        '번호', '성명', '유형', '판정 열', '판정 근거', '분류된 유형 수',
        '지원·지급 사유', '지원·지급 내용'])
    if len(S['유형분류내역']):
        order = {c: i for i, c in enumerate(cats)}
        S['유형분류내역'] = (S['유형분류내역']
                        .assign(_o=lambda d: d['유형'].map(order))
                        .sort_values(['_o', '번호'], kind='mergesort')
                        .drop(columns='_o').reset_index(drop=True))
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
