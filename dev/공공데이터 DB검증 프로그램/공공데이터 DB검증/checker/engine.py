# -*- coding: utf-8 -*-
"""검토 실행기: 파일 1건 또는 여러 건을 기준에 따라 검사한다."""
from __future__ import annotations

import os
import tempfile
import zipfile
from typing import Dict, List, Optional

from . import rules_file, rules_meta
from .models import Finding, Level, Result
from .readers import (decode, detect_delimiter, detect_encoding, ext_of,
                      read_csv_text, read_xlsx)
from .rules_csv import analyze_table

TEXT_TABLE_EXT = {"csv", "tsv", "txt"}
ZIP_INNER_LIMIT = 5     # ZIP 내부 CSV 최대 검사 개수


def check(path: str, meta: Optional[Dict] = None) -> Result:
    """파일 1건을 검토한다."""
    meta = meta or {}
    res = Result(file_name=os.path.basename(path), file_path=path,
                 ext=ext_of(path))
    try:
        res.file_size = os.path.getsize(path)
    except OSError as exc:
        res.error = f"파일을 읽을 수 없습니다: {exc}"
        return res

    rules_file.check_file(res, meta)

    try:
        if res.ext in TEXT_TABLE_EXT:
            _check_text_table(res, meta)
        elif res.ext in {"xlsx", "xlsm"}:
            _check_xlsx(res, meta)
        elif res.ext == "zip":
            _check_zip_inner(res, meta)
    except Exception as exc:                       # noqa: BLE001
        res.add(Finding(
            "17-다", "기타 상세 사유", Level.REJECT,
            f"파일 판독 중 오류가 발생했습니다: {exc}",
            "데이터가 암호화되어 있거나 인코딩이 손상된 경우일 수 있습니다. "
            "파일을 다시 저장한 뒤 검토하세요."))

    rules_meta.check_meta(res, meta)
    _link_and_duplicate_checklist(res, meta)
    return res


def check_many(paths: List[str], meta: Optional[Dict] = None) -> List[Result]:
    return [check(p, meta) for p in paths]


# ---- 형식별 판독 -------------------------------------------------------
def _check_text_table(res: Result, meta: Dict) -> None:
    enc, raw = detect_encoding(res.file_path)
    res.encoding = enc
    if enc == "unknown":
        res.add(Finding(
            "17-다", "기타 상세 사유", Level.REJECT,
            "인코딩을 판별할 수 없습니다.",
            "CP949 또는 UTF-8로 다시 저장하세요. 데이터가 깨져 보이면 반려됩니다."))
    text = decode(raw, enc if enc != "unknown" else "utf-8")

    delim = "\t" if res.ext == "tsv" else detect_delimiter(text)
    res.delimiter = {"\t": "탭", ",": "콤마(,)"}.get(delim, delim)
    if res.ext == "csv" and delim != ",":
        res.add(Finding(
            "10-파", "CSV 기준준수", Level.REJECT,
            f"데이터 구분자가 콤마(,)가 아닙니다(현재: {res.delimiter}).",
            "엑셀에서 '다른 이름으로 저장 → CSV(쉼표로 분리)(*.csv)'를 선택해 "
            "저장하세요."))

    if enc == "utf-8" and any(b > 127 for b in raw):
        note = meta.get("기타유의사항", "") or ""
        has_guide = "UTF-8" in note.upper()
        res.add(Finding(
            "10-러", "CSV 기준준수", Level.REVIEW if has_guide else Level.ACTION,
            "한글 인코딩이 UTF-8(BOM 없음)입니다. 엑셀에서 한글이 깨져 보입니다.",
            "기타유의사항에 UTF-8 인코딩 데이터 이용 방법을 기재하세요."
            + (" (안내가 기재되어 있습니다.)" if has_guide else "")))

    rows = read_csv_text(text, delimiter=delim)
    analyze_table(res, rows, text, meta)


def _check_xlsx(res: Result, meta: Dict) -> None:
    rows, sheets = read_xlsx(res.file_path)
    res.encoding = "-"
    res.delimiter = "-"
    if len(sheets) > 1:
        res.add(Finding(
            "9-라", "파일 확장자", Level.REVIEW,
            f"시트가 {len(sheets)}개입니다: {', '.join(sheets[:5])}",
            "CSV로 변환하면 첫 시트만 남습니다. 시트별로 데이터를 분리해 "
            "등록할지 검토하세요."))
    analyze_table(res, rows, "", meta)


def _check_zip_inner(res: Result, meta: Dict) -> None:
    with zipfile.ZipFile(res.file_path) as zf:
        targets = [n for n in zf.namelist() if ext_of(n) in {"csv", "tsv"}][:ZIP_INNER_LIMIT]
        if not targets:
            return
        with tempfile.TemporaryDirectory() as tmp:
            for name in targets:
                out = zf.extract(name, tmp)
                sub = check(out, meta)
                for f in sub.findings:
                    f.item = f"{f.item} · {os.path.basename(name)}"
                    res.add(f)
                res.rows = max(res.rows, sub.rows)
                res.cols = max(res.cols, sub.cols)
                if sub.suggested_base_date:
                    res.suggested_base_date = max(
                        filter(None, [res.suggested_base_date, sub.suggested_base_date]))


# ---- 자동 검증이 불가한 항목 안내 -------------------------------------
def _link_and_duplicate_checklist(res: Result, meta: Dict) -> None:
    url = (meta.get("링크URL") or "").strip()
    if url:
        res.add(Finding(
            "6-가", "링크데이터 등록 검토", Level.REVIEW,
            f"링크데이터 URL이 입력되었습니다: {url}",
            "추가 검색·화면 이동·회원 로그인 없이 데이터를 바로 내려받을 수 있는 "
            "상세페이지인지 확인하세요. 홈페이지 첫 화면 링크는 불허하며, "
            "클릭 시 바로 내려받는 형태도 불허입니다."))
    if meta.get("중복확인") not in ("완료", "예", "Y", "y", True):
        res.add(Finding(
            "5-가", "중복 등록 제외", Level.REVIEW,
            "동일한 데이터명이 이미 등록되어 있는지 확인이 필요합니다.",
            "중복된 데이터명은 목록 제외 또는 삭제 요청을 접수해야 합니다. "
            "공문 위치: 정보공유 > 공지사항조회 > [검색어]별지 > "
            "[게시판번호 765] > [서식5] 공공데이터 목록 제외 요청서"))
