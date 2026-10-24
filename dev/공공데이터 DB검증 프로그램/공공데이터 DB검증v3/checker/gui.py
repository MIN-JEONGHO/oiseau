# -*- coding: utf-8 -*-
"""데스크톱 GUI (pywebview 기반). exe 패키징 시 이 모듈이 진입점이 된다."""
from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import Dict, List, Optional

from . import AUTHOR, CRITERIA_VERSION, RELEASE_DATE, __version__
from .engine import check, check_many
from .fixer import default_out_path, fix_file, fixable_rules
from .models import Result
from .report import to_xlsx
from .ui import INDEX_HTML

FILE_TYPES = ("데이터 파일 (*.csv;*.tsv;*.txt;*.xlsx;*.xlsm;*.zip;*.json;*.xml)",
              "모든 파일 (*.*)")


class Api:
    """HTML 화면에서 호출하는 기능 묶음."""

    def __init__(self) -> None:
        self._results: List[Result] = []
        self._meta: Dict = {}
        self._window = None

    def attach(self, window) -> None:
        self._window = window

    # ---- 화면 ↔ 엔진 ---------------------------------------------------
    def criteria(self) -> str:
        return f"기준 {CRITERIA_VERSION} · v{__version__}"

    def about(self) -> Dict[str, str]:
        return {"version": __version__, "release": RELEASE_DATE,
                "author": AUTHOR, "criteria": CRITERIA_VERSION}

    def fixable(self) -> List[Dict[str, str]]:
        return fixable_rules()

    def pick_files(self) -> List[str]:
        import webview
        got = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=FILE_TYPES)
        return list(got or [])

    def run(self, paths: List[str], meta: Optional[Dict] = None) -> List[Dict]:
        paths = [p for p in (paths or []) if os.path.isfile(p)]
        self._meta = meta or {}
        self._results = check_many(paths, self._meta)
        return [r.to_dict() for r in self._results]

    def save_report(self) -> str:
        import webview
        if not self._results:
            return ""
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
        target = self._window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=f"공공데이터_사전검토_{stamp}.xlsx")
        if not target:
            return ""
        path = target if isinstance(target, str) else target[0]
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        return to_xlsx(self._results, path)

    # ---- 픽스 ----------------------------------------------------------
    def fix(self, file_path: str, rule_ids: List[str]) -> Dict:
        """선택한 조항만 수정해 원본과 같은 형식으로 저장하고, 수정본을 재검토한다."""
        import webview
        if not os.path.isfile(file_path):
            return {"error": "원본 파일을 찾을 수 없습니다."}

        target = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=os.path.dirname(file_path),
            save_filename=os.path.basename(default_out_path(file_path)))
        if not target:
            return {"cancelled": True}
        out = target if isinstance(target, str) else target[0]

        src_ext = os.path.splitext(file_path)[1]
        if not out.lower().endswith(src_ext.lower()):
            out += src_ext                     # 원본 형식·확장자 유지

        report = fix_file(file_path, rule_ids, out_path=out)
        if report.error:
            return {"error": report.error}

        after = check(report.out_path, self._meta)
        self._results.append(after)
        return {"report": report.to_dict(), "after": after.to_dict()}


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
