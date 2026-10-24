# -*- coding: utf-8 -*-
"""명령줄 실행 진입점."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Dict, List

from . import CRITERIA_VERSION, __version__
from .engine import check, check_many
from .fixer import FIXABLE, default_out_path, fix_file
from .models import Level
from .report import to_console, to_xlsx

META_KEYS = ["목록명", "데이터명", "기관명", "키워드", "설명", "기타유의사항",
             "공공누리유형", "저작권포함", "데이터기준일", "갱신주기",
             "차기등록예정일", "제공신청여부", "제공번호", "등록확장자",
             "링크URL", "중복확인"]


def load_meta(arg: str) -> Dict[str, str]:
    if not arg:
        return {}
    if os.path.isfile(arg):
        with open(arg, encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(arg)


def expand(patterns: List[str]) -> List[str]:
    files: List[str] = []
    for p in patterns:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in names]
        else:
            hits = glob.glob(p)
            files += hits or [p]
    return [f for f in files if os.path.isfile(f)]


def resolve_rules(spec: str, result) -> List[str]:
    """--fix 인수를 실제 조항 목록으로 바꾼다."""
    spec = spec.strip()
    hits = [f for f in result.findings if f.fix_key in FIXABLE]
    if spec == "all":
        return sorted({f.fix_key for f in hits})
    if spec in ("서식", "내용"):
        return sorted({f.fix_key for f in hits if FIXABLE[f.fix_key][1] == spec})
    if spec in ("반려", "보완필요", "확인권장"):
        return sorted({f.fix_key for f in hits if f.level.value == spec})
    return [r.strip() for r in spec.split(",") if r.strip() in FIXABLE]


def _apply_fix(results, spec: str, suffix: str, quiet: bool):
    """검토 결과에 픽스를 적용하고, 수정본을 재검토한 결과를 덧붙인다."""
    extra = []
    for res in list(results):
        rules = resolve_rules(spec, res)
        if not rules:
            continue
        rep = fix_file(res.file_path, rules,
                       out_path=default_out_path(res.file_path, suffix))
        if rep.error:
            print(f"[픽스 실패] {res.file_name}: {rep.error}", file=sys.stderr)
            continue
        after = check(rep.out_path)
        extra.append(after)
        if not quiet:
            applied = " · ".join(f"{FIXABLE[k][0]} {v}건" for k, v in rep.applied.items())
            print(f"\n[픽스] {res.file_name} → {rep.out_path}")
            print(f"       {applied or '변경 없음'}"
                  + (f" · 행 {rep.removed_rows}개 삭제" if rep.removed_rows else ""))
            print(f"       반려 {res.counts()['반려']}건 → {after.counts()['반려']}건")
    return results + extra


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pdcheck",
        description=f"공공데이터포털 파일데이터 등록 사전검토 ({CRITERIA_VERSION})")
    ap.add_argument("paths", nargs="+", help="검토할 파일·폴더·와일드카드")
    ap.add_argument("-m", "--meta", default="",
                    help=f"메타정보 JSON 파일 또는 JSON 문자열. 키: {', '.join(META_KEYS)}")
    ap.add_argument("-x", "--xlsx", default="", help="엑셀 리포트 저장 경로")
    ap.add_argument("--fix", default="",
                    help="자동 수정할 조항. 서식 | 내용 | all | 반려 | 보완필요 | 확인권장 | 10-타,10-하")
    ap.add_argument("--fix-suffix", default="_수정",
                    help="수정본 파일명 접미사 (기본: _수정). 확장자는 원본을 유지")
    ap.add_argument("--json", default="", help="JSON 결과 저장 경로")
    ap.add_argument("-q", "--quiet", action="store_true", help="콘솔 출력 생략")
    ap.add_argument("-V", "--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    files = expand(args.paths)
    if not files:
        print("검토할 파일이 없습니다.", file=sys.stderr)
        return 2

    results = check_many(files, load_meta(args.meta))

    if not args.quiet:
        print(to_console(results))
    if args.xlsx:
        print(f"\n엑셀 리포트 저장: {to_xlsx(results, args.xlsx)}")
    if args.fix:
        results = _apply_fix(results, args.fix, args.fix_suffix, args.quiet)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([r.to_dict() for r in results], fh, ensure_ascii=False, indent=2)
        print(f"JSON 결과 저장: {args.json}")

    return 1 if any(r.verdict is Level.REJECT for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
