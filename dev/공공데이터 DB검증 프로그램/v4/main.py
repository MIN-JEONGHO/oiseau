# -*- coding: utf-8 -*-
"""공공데이터 파일데이터 등록 사전검토 — 통합 진입점.

  python main.py                     GUI 실행 (기본)
  python main.py data.csv -x out.xlsx  CLI 검토
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
