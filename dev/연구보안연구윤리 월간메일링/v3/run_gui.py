# -*- coding: utf-8 -*-
"""GUI 실행 진입점.

버튼 하나로 실행하는 GUI(pywebview + 로컬 웹 화면). pywebview 가 없으면
자동으로 기본 브라우저에서 같은 화면을 연다. 실제 구현은 rmonitor/gui.py.
"""
from __future__ import annotations

import sys

from rmonitor.gui import main

if __name__ == "__main__":
    sys.exit(main())
