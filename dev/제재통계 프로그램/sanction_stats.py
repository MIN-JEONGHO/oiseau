# -*- coding: utf-8 -*-
"""
제재통계 자동 산출 (원자료 -> 1~9번 결과시트)

원본 엑셀 자동화(제재통계_자동_분석...xlsx)의 계산 로직을 파이썬으로 그대로 옮긴 것.
엑셀/LibreOffice 없이 동작하므로 PyInstaller 로 단독 exe 패키징이 가능하다.

파이프라인:
  원자료(입력)  ->  전처리  ->  1~9 결과시트  ->  결과 엑셀 저장

사용법:
  python sanction_stats.py 원자료.xlsx -o 결과.xlsx
  python sanction_stats.py 원자료.csv  -o 결과.xlsx --base-year 2017
"""

import argparse
import sys
import os

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# 원자료 컬럼 정의 (엑셀 '원자료' 시트 헤더와 동일)
# ---------------------------------------------------------------------------
RAW_COLS = [
    "처분연도", "제재유형구분", "연구수행주체", "연구수행주체(정제)",
    "제재사유(기본법)", "제재사유(혁신법)", "미납금액", "대상금액(원)",
    "납부금액(원)", "소관부처", "제재ID",
]

N_YEARS = 14  # 2017~2030 (원본과 동일: C~P / B~O 14개 연도)

# 금액 시트 단위: 원 -> 억원
AMOUNT_DIVISOR = 100_000_000


# ---------------------------------------------------------------------------
# 결과(consolidation) 매핑
#   - 원본 '결과' 블록의 SUMIFS 라벨 묶음을 그대로 재현
# ---------------------------------------------------------------------------

# 제재사유별 (시트 1/4/7): (출력라벨, 기본법 코드집합, 혁신법 코드집합)
REASON_MAP = [
    ("연구결과 불량",            ["01. 연구결과불량"],                              ["12. 연구과정 및 결과 불량"]),
    ("연구개발결과 누설‧유출",   ["02. 연구개발 내용 누설 및 유출"],                  []),
    ("연구개발과제 수행포기",    ["03. 연구개발과제 수행포기"],                       ["27. 연구개발과제 수행포기"]),
    ("기술료 미납",              ["04. 기술료 미납"],                                ["28. 기술료 미납"]),
    ("환수금 미납",              ["05. 환수금 미납"],                                ["29. 회수금 미납"]),
    ("연구비 부정사용",
        ["06. 연구개발비 용도외 사용", "07. 학생인건비부당회수", "071. 연구개발비 용도외 사용"],
        ["15. 연구개발비 용도외 사용", "16. 학생인건비부당회수"]),
    ("연구개발 성과의 소유 위반",
        ["08. 지식재산권의 개인 명의 출원 및 등록"],
        ["17. 연구개발 성과의 소유 위반"]),
    ("연구 부정행위",
        ["09. 부정한 방법으로 연구 수행", "10. 위조·변조·표절", "101. 부정한 방법으로 연구 수행"],
        ["14. 위조·변조·표절", "21. 부정한 방법으로 연구 신청",
         "22. 부정한 방법으로 연구 수행", "24. 연구비 사용 건전성 저해 행위"]),
    ("그 외 법령 및 협약 위반",
        ["11. 그 외 법령 및 협약 위반"],
        ["13. 협약불이행에 따른 과제 변경‧중단"]),
]

# 시트 7(제재부가금)은 결과 5번째 항목만 라벨/코드가 다르다:
#   "환수금 미납"(05. 환수금 미납)  ->  "제재부가금 미납"(05. 제재부가금 미납)
REASON_MAP_7 = [
    row if row[0] != "환수금 미납"
    else ("제재부가금 미납", ["05. 제재부가금 미납"], ["29. 회수금 미납"])
    for row in REASON_MAP
]

# 기관유형별 (시트 2/5/8): (출력라벨, 원천 라벨집합)
#   빈 문자열("")은 미기재 항목을 '기타'로 합산하는 원본 규칙을 반영
INSTITUTION_MAP = [
    ("대학",         ["대학"]),
    ("대기업",       ["대기업"]),
    ("중견기업",     ["중견기업"]),
    ("중소기업",     ["중소기업"]),
    ("출연연",       ["출연연구소"]),
    ("국공립연구소", ["국공립연구소", "정부부처"]),
    ("기타",         ["", "기타"]),
]

# 부처별 (시트 3/6/9): (출력라벨, 원천 라벨집합) - 부처명 변경 이력 병합 포함
MINISTRY_MAP = [
    ("경찰청",             ["경찰청"]),
    ("과학기술정보통신부", ["과학기술정보통신부", "미래창조과학부"]),
    ("교육부",             ["교육부"]),
    ("국토교통부",         ["국토교통부"]),
    ("기상청",             ["기상청"]),
    ("기후에너지환경부",   ["기후에너지환경부"]),
    ("농림축산식품부",     ["농림축산식품부"]),
    ("농촌진흥청",         ["농촌진흥청"]),
    ("다부처",             ["다부처"]),
    ("문화체육관광부",     ["문화체육관광부"]),
    ("방송미디어통신위원회", ["방송통신위원회", "방송미디어통신위원회"]),
    ("방위사업청",         ["방위사업청"]),
    ("보건복지부",         ["보건복지부"]),
    ("산림청",             ["산림청"]),
    ("산업통상자원부",     ["산업통상자원부"]),
    ("소방청",             ["소방방재청", "소방청"]),
    ("식품의약품안전처",   ["식품의약품안전처"]),
    ("원자력안전위원회",   ["원자력안전위원회"]),
    ("중소벤처기업부",     ["중소기업청", "중소벤처기업부"]),
    ("특허청",             ["특허청"]),
    ("해양경찰청",         ["해양경찰청"]),
    ("해양수산부",         ["해양수산부"]),
    ("행정안전부",         ["행정안전부"]),
    ("환경부",             ["환경부"]),
]

# 9개 시트 정의
SHEETS = [
    dict(name="1", title="1. 국가R&D사업 참여제한 현황(제재사유별)",   unit="건",   measure="count",  filt="참여제한",   dim="reason",      reason_map=REASON_MAP),
    dict(name="2", title="2. 국가R&D사업 참여제한 현황(기관유형별)",   unit="건",   measure="count",  filt="참여제한",   dim="institution"),
    dict(name="3", title="3. 국가R&D사업 참여제한 현황(부처별)",       unit="건",   measure="count",  filt="참여제한",   dim="ministry"),
    dict(name="4", title="4. 국가R&D사업 환수금 현황(제재사유별)",     unit="억원", measure="amount", filt="환수금",     dim="reason",      reason_map=REASON_MAP),
    dict(name="5", title="5. 국가R&D사업 환수금 현황(기관유형별)",     unit="억원", measure="amount", filt="환수금",     dim="institution"),
    dict(name="6", title="6. 국가R&D사업 환수금 현황(부처별)",         unit="억원", measure="amount", filt="환수금",     dim="ministry"),
    dict(name="7", title="7. 국가R&D사업 제재부가금 현황(제재사유별)", unit="억원", measure="amount", filt="제재부가금", dim="reason",      reason_map=REASON_MAP_7),
    dict(name="8", title="8. 국가R&D사업 제재부가금 현황(기관유형별)", unit="억원", measure="amount", filt="제재부가금", dim="institution"),
    dict(name="9", title="9. 국가R&D사업 제재부가금 현황(부처별)",     unit="억원", measure="amount", filt="제재부가금", dim="ministry"),
]


# ---------------------------------------------------------------------------
# 입력 로드 & 전처리
# ---------------------------------------------------------------------------
def load_raw(path):
    """원자료를 DataFrame 으로 읽는다. xlsx('원자료' 시트) 또는 csv 지원."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(path)
        sheet = "원자료" if "원자료" in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(path, sheet_name=sheet, dtype=object)
    elif ext in (".csv", ".tsv", ".txt"):
        sep = "\t" if ext == ".tsv" else ","
        df = pd.read_csv(path, dtype=object, sep=sep)
    else:
        raise ValueError(f"지원하지 않는 입력 형식입니다: {ext}")

    # 헤더가 원자료 형식과 같으면 이름으로, 아니면 위치로 매핑
    if set(RAW_COLS).issubset(set(df.columns)):
        df = df[RAW_COLS].copy()
    else:
        if df.shape[1] < len(RAW_COLS):
            raise ValueError(f"원자료 컬럼이 부족합니다. {len(RAW_COLS)}개 필요, {df.shape[1]}개 발견")
        df = df.iloc[:, :len(RAW_COLS)].copy()
        df.columns = RAW_COLS
    return df


def _to_str(v):
    """엑셀의 IF(x="","",x) 규칙: None/NaN/공백을 빈 문자열로."""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("", "nan", "none") else s


def _to_num(v):
    """엑셀 VALUE()+IF(=0,"") 규칙: 숫자화 실패/0/공백은 결측(빈칸)."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        s = str(v).replace(",", "").strip()
        if s == "":
            return None
        n = float(s)
    except (ValueError, TypeError):
        return None
    return None if n == 0 else n


def preprocess(raw):
    """원자료 -> 전처리 테이블 (엑셀 '원자료(전처리)' 시트와 동일 규칙)."""
    w = pd.DataFrame()
    w["연도"]   = raw["처분연도"].map(_to_num)                    # 0/오류 -> None
    w["유형"]   = raw["제재유형구분"].map(_to_str)
    # 연구수행주체(정제): 정제값 우선, 없으면 원본
    refined = raw["연구수행주체(정제)"].map(_to_str)
    origin  = raw["연구수행주체"].map(_to_str)
    w["주체"]   = refined.where(refined != "", origin)
    w["기본법"] = raw["제재사유(기본법)"].map(_to_str)
    w["혁신법"] = raw["제재사유(혁신법)"].map(_to_str)
    w["미납금액"] = raw["미납금액"].map(_to_num)
    w["대상금액"] = raw["대상금액(원)"].map(_to_num)              # 금액 시트 측정값
    w["납부금액"] = raw["납부금액(원)"].map(_to_num)
    w["부처"]   = raw["소관부처"].map(_to_str)
    id_num      = raw["제재ID"].map(_to_num)
    # 주의: pandas Series 는 None 을 NaN 으로 저장하므로 반드시 notna 로 판정
    w["건수"]   = id_num.notna().astype(int)              # 제재ID 있으면 1건
    # 연도를 정수로 (결측은 None 유지; NaN 에 int() 호출 방지)
    w["연도"] = w["연도"].map(lambda x: int(x) if pd.notna(x) else None)
    return w


# ---------------------------------------------------------------------------
# 집계 엔진
# ---------------------------------------------------------------------------
def _blank_if_zero(v):
    return "" if (v is None or v == 0) else v


def _measure_series(sub, measure):
    if measure == "count":
        return sub["건수"]
    # amount: 대상금액 합계 / 1e8 (억원). 결측은 0으로.
    return sub["대상금액"].fillna(0.0) / AMOUNT_DIVISOR


def build_sheet(work, cfg, years):
    """
    한 시트의 결과 데이터를 만든다.
    반환: dict(
        top = [(label, {year:val}, total)],      # 상단 원천 피벗 (검증용/재현용)
        top_sub = 'reason' 이면 [('기본법',rows),('혁신법',rows)] 형태로 분리 정보 포함
        result = [(label, {year:val}, total)],    # 결과(consolidation) 블록
        result_total = {year:val}, total          # 결과 합계
        verify = {year:bool}                       # 상단합 == 결과합
    )
    """
    measure = cfg["measure"]
    filt = cfg["filt"]
    dim = cfg["dim"]

    base = work[work["유형"] == filt].copy()
    base["_m"] = _measure_series(base, measure)

    def pivot(colname, categories):
        """카테고리 x 연도 피벗 (원본 SUMIFS 와 동일). 값 0은 그대로 0.
        합계 열은 원본과 동일하게 '표시 연도(C:P)의 합'이므로 범위 밖 연도는 제외된다."""
        rows = []
        for cat in categories:
            yd = {}
            catrows = base[base[colname] == cat]
            for y in years:
                yd[y] = float(catrows[catrows["연도"] == y]["_m"].sum())
            total = float(sum(yd.values()))  # = SUM(C:P), 범위 밖 연도 제외
            rows.append((cat, yd, total))
        return rows

    if dim == "reason":
        # 상단: 기본법 / 혁신법 두 블록 (정렬된 고유값)
        g_cats = sorted([c for c in base["기본법"].unique() if c != ""])
        h_cats = sorted([c for c in base["혁신법"].unique() if c != ""])
        g_rows = pivot("기본법", g_cats)
        h_rows = pivot("혁신법", h_cats)
        top = {"기본법": g_rows, "혁신법": h_rows}

        # 결과 블록: 라벨 묶음 합산
        g_lookup = {c: yd for c, yd, _ in g_rows}
        g_tot = {c: t for c, _, t in g_rows}
        h_lookup = {c: yd for c, yd, _ in h_rows}
        h_tot = {c: t for c, _, t in h_rows}
        result = []
        for label, gset, hset in cfg.get("reason_map", REASON_MAP):
            yd = {y: 0.0 for y in years}
            for c in gset:
                if c in g_lookup:
                    for y in years:
                        yd[y] += g_lookup[c][y]
            for c in hset:
                if c in h_lookup:
                    for y in years:
                        yd[y] += h_lookup[c][y]
            result.append((label, yd, float(sum(yd.values()))))

    else:
        colname = "주체" if dim == "institution" else "부처"
        cats = sorted([c for c in base[colname].unique() if c != ""])
        rows = pivot(colname, cats)
        top = {"single": rows}

        lookup = {c: yd for c, yd, _ in rows}
        tot_l = {c: t for c, _, t in rows}
        cmap = INSTITUTION_MAP if dim == "institution" else MINISTRY_MAP
        # '기타' 규칙에 빈 문자열("") 포함 -> 원천 '' 카테고리도 합산 대상
        # (단, base[colname]=="" 인 행은 위 cats 에서 제외되었으므로 별도 합산)
        empty_rows = base[base[colname] == ""]
        result = []
        for label, srcset in cmap:
            yd = {y: 0.0 for y in years}
            for c in srcset:
                if c == "":
                    for y in years:
                        yd[y] += float(empty_rows[empty_rows["연도"] == y]["_m"].sum())
                elif c in lookup:
                    for y in years:
                        yd[y] += lookup[c][y]
            result.append((label, yd, float(sum(yd.values()))))

    # 결과 합계 행
    rtotal = {y: sum(r[1][y] for r in result) for y in years}
    rtotal_all = sum(r[2] for r in result)

    # 검증: 결과(consolidation) 합 == 필터링된 원천 데이터 전체합 (연도별)
    #   -> 매핑에 없는 카테고리로 데이터가 누락되면 불일치로 잡힌다.
    #      (빈 기관/부처는 '기타' 로 포함되므로 전체합 기준이 정확하다)
    verify = {}
    for y in years:
        full_sum = float(base[base["연도"] == y]["_m"].sum())
        verify[y] = abs(full_sum - rtotal[y]) < 1e-6

    return dict(top=top, result=result, rtotal=rtotal, rtotal_all=rtotal_all,
                verify=verify, cfg=cfg)


# ---------------------------------------------------------------------------
# 결과 엑셀 작성
# ---------------------------------------------------------------------------
def _amount_fmt(unit):
    return "#,##0.0" if unit == "억원" else "#,##0"


def write_workbook(sheets_data, years, out_path):
    wb = Workbook()
    wb.remove(wb.active)

    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_fill = PatternFill("solid", fgColor="D9E1F2")
    sub_fill = PatternFill("solid", fgColor="F2F2F2")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")
    bold = Font(name="맑은 고딕", bold=True)
    normal = Font(name="맑은 고딕")

    for sd in sheets_data:
        cfg = sd["cfg"]
        ws = wb.create_sheet(title=cfg["name"])
        numfmt = _amount_fmt(cfg["unit"])
        ncols = len(years)  # 연도 개수

        # 결과(consolidation) 블록만 담은 깔끔한 결과 시트
        ws["A1"] = cfg["title"]
        ws["A1"].font = Font(name="맑은 고딕", bold=True, size=12)
        ws["A2"] = f" (단위 : {cfg['unit']})"
        ws["A2"].font = normal

        hdr_row = 4
        ws.cell(row=hdr_row, column=1, value="구분")
        for j, y in enumerate(years):
            ws.cell(row=hdr_row, column=2 + j, value=y)
        ws.cell(row=hdr_row, column=2 + ncols, value="합계")
        for c in range(1, 3 + ncols):
            cell = ws.cell(row=hdr_row, column=c)
            cell.font = bold
            cell.alignment = center
            cell.fill = hdr_fill
            cell.border = border

        r = hdr_row + 1
        for label, yd, tot in sd["result"]:
            ws.cell(row=r, column=1, value=label).font = normal
            ws.cell(row=r, column=1).alignment = left
            ws.cell(row=r, column=1).border = border
            for j, y in enumerate(years):
                cell = ws.cell(row=r, column=2 + j, value=_blank_if_zero(yd[y]))
                cell.number_format = numfmt
                cell.alignment = center
                cell.border = border
            tcell = ws.cell(row=r, column=2 + ncols, value=_blank_if_zero(tot))
            tcell.number_format = numfmt
            tcell.alignment = center
            tcell.border = border
            r += 1

        # 합계 행
        ws.cell(row=r, column=1, value="합계").font = bold
        ws.cell(row=r, column=1).alignment = center
        ws.cell(row=r, column=1).fill = sub_fill
        ws.cell(row=r, column=1).border = border
        for j, y in enumerate(years):
            cell = ws.cell(row=r, column=2 + j, value=_blank_if_zero(sd["rtotal"][y]))
            cell.number_format = numfmt
            cell.font = bold
            cell.alignment = center
            cell.fill = sub_fill
            cell.border = border
        tcell = ws.cell(row=r, column=2 + ncols, value=_blank_if_zero(sd["rtotal_all"]))
        tcell.number_format = numfmt
        tcell.font = bold
        tcell.alignment = center
        tcell.fill = sub_fill
        tcell.border = border

        # 열 너비
        ws.column_dimensions["A"].width = 26
        for j in range(ncols + 1):
            ws.column_dimensions[get_column_letter(2 + j)].width = 11

    wb.save(out_path)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def run(input_path, output_path, base_year=2017):
    years = list(range(base_year, base_year + N_YEARS))
    raw = load_raw(input_path)
    work = preprocess(raw)
    sheets_data = [build_sheet(work, cfg, years) for cfg in SHEETS]
    write_workbook(sheets_data, years, output_path)
    return sheets_data, years


def _pause_if_console():
    """더블클릭(콘솔 자동종료) 환경에서 결과를 볼 수 있도록 잠시 대기."""
    try:
        if os.name == "nt" and sys.stdin and sys.stdin.isatty():
            input("\n엔터를 누르면 종료합니다...")
    except Exception:
        pass


def main(argv=None):
    p = argparse.ArgumentParser(description="제재통계 자동 산출 (원자료 -> 1~9 결과)")
    p.add_argument("input", nargs="?", help="원자료 파일 (.xlsx 의 '원자료' 시트 또는 .csv)")
    p.add_argument("-o", "--output", default="제재통계_결과.xlsx", help="결과 엑셀 경로")
    p.add_argument("--base-year", type=int, default=2017, help="시작 연도 (기본 2017)")
    args = p.parse_args(argv)

    # 입력을 안 준 채 실행(예: exe 더블클릭)하면 경로를 물어본다.
    if not args.input:
        try:
            args.input = input("원자료 파일 경로를 입력하세요 (.xlsx 또는 .csv): ").strip().strip('"')
        except EOFError:
            p.print_help()
            return 2

    if not args.input or not os.path.exists(args.input):
        print(f"[오류] 입력 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        _pause_if_console()
        return 2

    # 입력과 같은 폴더에 결과를 저장(기본값일 때) -> exe 사용 편의
    if args.output == "제재통계_결과.xlsx":
        args.output = os.path.join(os.path.dirname(os.path.abspath(args.input)),
                                   "제재통계_결과.xlsx")

    sheets_data, years = run(args.input, args.output, args.base_year)
    warn = [sd["cfg"]["name"] for sd in sheets_data if not all(sd["verify"].values())]
    print(f"[완료] 결과 저장: {args.output}")
    print(f"       연도 범위: {years[0]} ~ {years[-1]}")
    if warn:
        print(f"       [주의] 검증 불일치 시트: {', '.join(warn)}")
        print("       (매핑에 없는 제재사유/기관/부처가 원자료에 있을 수 있습니다)")
    else:
        print("       검증: 모든 시트에서 원천 합계 = 결과 합계 일치")
    _pause_if_console()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
