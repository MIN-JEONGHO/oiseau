# -*- coding: utf-8 -*-
"""공공데이터 등록 사전검토 — 통합 진입점 (파일데이터 · OPEN API).

  python main.py                            GUI 실행 (기본)
  python main.py data.csv -x out.xlsx       CLI · 파일데이터 검토
  python main.py --api -m meta.json         CLI · OPEN API 검토
  python main.py --api -m meta.json --spec 기술문서.json --probe --key KEY
"""
from __future__ import annotations

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("--gui", "-g"):
        from checker.gui import main as gui_main
        return gui_main()
    from checker.cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
