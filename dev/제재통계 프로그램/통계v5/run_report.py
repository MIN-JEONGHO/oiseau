# -*- coding: utf-8 -*-
"""
국가R&D 제재처분 원인과제 현황 집계 프로그램

사용 예
-------
# 1) 가장 기본 (엑셀만)
python run_report.py 제재정보_rawdata_20260301.xlsx

# 2) hwpx 표준양식까지 채우기
python run_report.py 제재정보_rawdata.xlsx ^
    --template "(표준양식) 부처별 예산 과제수 제재처분 집계(유형별)(원인과제수행연도기준).hwpx" ^
    --ref 조사분석_참조데이터.xlsx ^
    --outdir 결과

# 3) 참조데이터(국가R&D연구비/과제수) 입력 양식 만들기
python run_report.py 제재정보_rawdata.xlsx --make-ref-template

# 4) 인자 없이 실행하면 파일 선택창이 열립니다
python run_report.py
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

from excel_writer import write_excel
from hwpx_writer import fill_hwpx
from sanction_pipeline import (
    PipelineConfig,
    aggregate,
    analyze_periods,
    check_reference_coverage,
    load_raw,
    load_reference,
    make_reference_template,
    preprocess,
    transform,
)

DEFAULT_TEMPLATE_HINT = "(표준양식) 부처별 예산 과제수 제재처분 집계(유형별)(원인과제수행연도기준).hwpx"


# ---------------------------------------------------------------------------
# 파일 선택 GUI (인자 없이 실행할 때)
# ---------------------------------------------------------------------------

def pick_files() -> dict:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except Exception:
        print("파일 선택창을 열 수 없습니다. 인자로 경로를 지정해 주세요.")
        print(__doc__)
        sys.exit(1)

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("제재처분 집계", "① 제재정보 rawdata 엑셀을 선택하세요.")
    raw = filedialog.askopenfilename(
        title="제재정보 rawdata 선택",
        filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv"), ("모든 파일", "*.*")],
    )
    if not raw:
        sys.exit(0)

    template = None
    if messagebox.askyesno("제재처분 집계", "② hwpx 표준양식도 채우시겠습니까?"):
        template = filedialog.askopenfilename(
            title="표준양식 hwpx 선택", filetypes=[("HWPX", "*.hwpx")]
        ) or None

    ref = None
    if messagebox.askyesno(
        "제재처분 집계",
        "③ 국가R&D연구비/과제수 참조 엑셀이 있습니까?\n(없으면 해당 행은 비워둡니다)",
    ):
        ref = filedialog.askopenfilename(
            title="조사·분석 참조데이터 선택",
            filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv")],
        ) or None

    outdir = filedialog.askdirectory(title="④ 결과를 저장할 폴더 선택") or str(Path(raw).parent)
    root.destroy()
    return {"raw": raw, "template": template, "ref": ref, "outdir": outdir}


# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="NTIS 제재정보 rawdata -> 부처별/연도별 제재처분 집계 (엑셀 + hwpx)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("raw", nargs="?", help="제재정보 rawdata 파일 (xlsx/xls/csv)")
    p.add_argument("--sheet", default="제재정보", help="시트명 (기본: 제재정보)")
    p.add_argument(
        "--header-row", type=int, default=None,
        help="헤더 행 번호 (기본: 자동 탐지)",
    )
    p.add_argument("--data-start-row", type=int, default=None, help="데이터 시작 행 (기본: 자동)")
    p.add_argument("--min-task-year", type=int, default=2017, help="과제수행연도 하한 (기본: 2017)")
    p.add_argument("--year-start", type=int, default=None, help="연도 축 시작 (기본: 자동)")
    p.add_argument("--year-end", type=int, default=None, help="연도 축 종료 (기본: 자동)")
    p.add_argument(
        "--year-end-cap", type=int, default=None,
        help="자동 결정 시 종료연도 상한 (기본: 올해)",
    )
    p.add_argument(
        "--id-strategy", default="과제명",
        choices=["과제명", "번호우선", "번호", "번호+명"],
        help="과제 동일성 판정 키 (기본: 과제명)",
    )
    p.add_argument(
        "--task-type", default="전체",
        choices=["전체", "세부만", "공동위탁제외"],
        help="원인과제로 셀 과제유형 기준 (기본: 전체). "
             "세부만=주관·협동 과제만, 공동위탁제외=공동·위탁 제외(유형 미상은 포함)",
    )
    p.add_argument(
        "--target", default="전체", choices=["전체", "기관", "인물"],
        help="제재대상 한정 (기본: 전체)",
    )
    p.add_argument(
        "--end-date-missing", default="시작일로채움",
        choices=["시작일로채움", "행제외"],
        help="총연구기간 종료일이 없는 행 처리 (기본: 시작연도로 채움). "
             "행제외는 원본에 종료일이 적힌 행만 세며, 같은 과제의 다른 행에서 빌린 값도 인정하지 않는다",
    )
    p.add_argument(
        "--ministry-pick", default="first", choices=["first", "최다레코드"],
        help="한 과제에 부처가 둘 이상일 때의 귀속 (기본: 처음 나온 부처). 합계는 같고 부처별 배분만 달라진다",
    )
    p.add_argument(
        "--ministry-column", default="소관부처", choices=["소관부처", "부처명"],
        help="부처 기준 컬럼 (기본: 소관부처)",
    )
    p.add_argument("--template", default=None, help="hwpx 표준양식 경로")
    p.add_argument("--ref", default=None, help="국가R&D연구비/과제수 참조 엑셀")
    p.add_argument("--outdir", default=None, help="결과 저장 폴더 (기본: rawdata 와 같은 폴더)")
    p.add_argument("--prefix", default="제재처분집계", help="출력 파일명 접두어")
    p.add_argument(
        "--make-ref-template", action="store_true",
        help="참조데이터 입력 양식(xlsx)을 함께 생성",
    )
    p.add_argument(
        "--no-long", action="store_true",
        help="엑셀에서 '연도전개' 시트를 뺀다 (기본은 포함)",
    )
    p.add_argument("-q", "--quiet", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if not args.raw:
        picked = pick_files()
        args.raw = picked["raw"]
        args.template = args.template or picked["template"]
        args.ref = args.ref or picked["ref"]
        args.outdir = args.outdir or picked["outdir"]

    raw_path = Path(args.raw)
    if not raw_path.exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {raw_path}")
        return 1

    outdir = Path(args.outdir) if args.outdir else raw_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    # 양식 자동 탐색
    template = args.template
    if template is None:
        for cand in (raw_path.parent, Path.cwd(), outdir):
            hit = list(cand.glob("*표준양식*제재처분*.hwpx")) or list(cand.glob("*.hwpx"))
            if hit:
                template = str(hit[0])
                break
        else:
            bundled = Path(__file__).resolve().parent / "template.hwpx"
            if bundled.exists():
                template = str(bundled)

    # 참조데이터도 지정하지 않으면 내장본을 쓴다
    if not args.ref:
        bundled_ref = Path(__file__).resolve().parent / "reference.xlsx"
        if bundled_ref.exists():
            args.ref = str(bundled_ref)
            print(f"  * 참조데이터 내장본 사용: {bundled_ref.name}")

    cfg = PipelineConfig(
        sheet_name=args.sheet,
        header_row=args.header_row,
        data_start_row=args.data_start_row,
        min_task_year=args.min_task_year,
        year_start=args.year_start,
        year_end=args.year_end,
        year_end_cap=args.year_end_cap,
        id_strategy=args.id_strategy,
        task_type_mode=args.task_type,
        target_filter=args.target,
        end_date_missing=args.end_date_missing,
        ministry_pick=args.ministry_pick,
        ministry_column=args.ministry_column,
        verbose=not args.quiet,
    )

    print("=" * 62)
    print(f" 제재처분 집계 시작  |  {raw_path.name}")
    print("=" * 62)

    raw = load_raw(str(raw_path), cfg)
    tr = transform(raw, cfg)
    pp = preprocess(tr, cfg)
    tasks, years, mask = analyze_periods(pp, cfg)
    res = aggregate(tasks, years, mask, cfg)
    res.reference = load_reference(args.ref, years, cfg)
    check_reference_coverage(res, cfg)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    made = []

    # 참조데이터 양식
    if args.make_ref_template:
        p = outdir / f"참조데이터_양식_{stamp}.xlsx"
        make_reference_template(str(p), res.ministries, years)
        made.append(p)

    # 엑셀
    xlsx = outdir / f"{args.prefix}_{stamp}.xlsx"
    write_excel(res, str(xlsx), include_long=not args.no_long)
    made.append(xlsx)

    # hwpx
    if template and Path(template).exists():
        hwpx = outdir / f"{args.prefix}_{stamp}.hwpx"
        try:
            fill_hwpx(template, str(hwpx), res)
            made.append(hwpx)
        except Exception as e:
            print(f"  ! hwpx 생성 실패: {e}")
            traceback.print_exc()
    else:
        print(f"  ! hwpx 양식을 찾지 못했습니다 (--template 로 지정). 힌트: {DEFAULT_TEMPLATE_HINT}")

    # 요약 출력
    print("-" * 62)
    print(f" 연도축   : {years[0]}~{years[-1]}  ({len(years)}개)")
    print(f" 부처수   : {len(res.ministries)}")
    for code in ("①", "②", "③"):
        print(f" {code} 합계  : {res.count('합 계', code, '합계'):>6,}건")
    print(f" 소계     : {res.subtotal('합 계', '합계'):>6,}건")
    if not res.reference:
        print(" 참조데이터 없음 -> 국가R&D연구비/과제수/비율 행은 공란")
    print("-" * 62)
    for p in made:
        print(f" [생성] {p}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
