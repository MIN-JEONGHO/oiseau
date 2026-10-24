# -*- coding: utf-8 -*-
"""데스크톱 GUI (pywebview 기반). exe 패키징 시 이 모듈이 진입점이 된다."""
from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import Dict, List, Optional

from . import CRITERIA_VERSION, __version__
from .engine import check_many
from .models import Result
from .report import to_markdown, to_xlsx
from .ui import INDEX_HTML

FILE_TYPES = ("데이터 파일 (*.csv;*.tsv;*.txt;*.xlsx;*.xlsm;*.zip;*.json;*.xml)",
              "모든 파일 (*.*)")


class Api:
    """HTML 화면에서 호출하는 기능 묶음."""

    def __init__(self) -> None:
        self._results: List[Result] = []
        self._window = None

    def attach(self, window) -> None:
        self._window = window

    # ---- 화면 ↔ 엔진 ---------------------------------------------------
    def criteria(self) -> str:
        return f"기준 {CRITERIA_VERSION} · v{__version__}"

    def pick_files(self) -> List[str]:
        import webview
        got = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=FILE_TYPES)
        return list(got or [])

    def run(self, paths: List[str], meta: Optional[Dict] = None) -> List[Dict]:
        paths = [p for p in (paths or []) if os.path.isfile(p)]
        self._results = check_many(paths, meta or {})
        return [r.to_dict() for r in self._results]

    def save_report(self, kind: str = "xlsx") -> str:
        import webview
        if not self._results:
            return ""
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
        default = f"공공데이터_사전검토_{stamp}.{'xlsx' if kind == 'xlsx' else 'md'}"
        target = self._window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=default)
        if not target:
            return ""
        path = target if isinstance(target, str) else target[0]
        if kind == "xlsx":
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            return to_xlsx(self._results, path)
        if not path.lower().endswith(".md"):
            path += ".md"
        return to_markdown(self._results, path)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        import webview
    except ImportError:
        print("GUI 실행에는 pywebview 가 필요합니다.  pip install pywebview",
              file=sys.stderr)
        return 2

    api = Api()
    window = webview.create_window(
        f"공공데이터 파일데이터 등록 사전검토  v{__version__}",
        html=INDEX_HTML, js_api=api, width=1240, height=900,
        min_size=(900, 640), text_select=True)
    api.attach(window)
    webview.start(debug=bool(os.environ.get("PDCHECK_DEBUG")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
