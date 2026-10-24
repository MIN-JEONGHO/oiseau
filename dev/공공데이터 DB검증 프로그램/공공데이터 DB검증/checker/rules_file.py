# -*- coding: utf-8 -*-
"""파일 확장자(9번) · 비정형 데이터(8번) · 링크·용량(6번) 검사."""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from .models import Finding, Level, Result
from .readers import ext_of, zip_entries

# 개방형 포맷 단계 구분 (9번 표)
CLOSED_DOC = {"hwp": "hwpx", "xls": "xlsx", "doc": "docx", "ppt": "pptx"}
STAGE1 = {"pdf"}
STAGE2 = {"hwp", "xls", "doc", "ppt", "wmv", "avi", "mpeg", "mp3"}
STAGE3 = {"shp", "ttl", "stl", "mp4", "py", "gif", "gpx", "fasta", "sgml",
          "tif", "tiff", "odt", "png", "jpg", "jpeg", "xlsx", "docx",
          "hwpx", "pptx"}
OPEN_FORMAT = {"csv", "json", "xml", "rdf"}
TABULAR_DOC = {"xlsx", "hwpx", "ods"}
UNSTRUCTURED = {"png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp",
                "mp4", "avi", "wmv", "mov", "mpeg", "mp3", "wav", "m4a"}
SPECIAL_TOOL = {"shp": "QGIS·ArcGIS", "sav": "IBM SPSS", "dwg": "AutoCAD",
                "dbf": "GIS·DB 도구", "mdb": "MS Access"}
ARCHIVE_OTHER = {"rar", "7z", "alz", "egg", "tar", "gz", "bz2"}
LINK_SIZE_LIMIT = 500 * 1024 * 1024   # 6-마: 500MB 이상은 링크데이터


def check_file(res: Result, meta: Optional[Dict] = None) -> None:
    meta = meta or {}
    ext = res.ext

    declared = (meta.get("등록확장자") or "").strip().lower().lstrip(".")
    if declared and declared != ext:
        res.add(Finding(
            "17-가", "기타 상세 사유", Level.REJECT,
            f"등록하려는 확장자({declared})와 실제 파일 확장자({ext})가 다릅니다.",
            "실제 파일과 동일한 확장자로 등록하세요. 다르면 반려됩니다."))

    if ext in CLOSED_DOC:
        res.add(Finding(
            "9-다", "파일 확장자", Level.REJECT,
            f"비개방형 문서 포맷({ext.upper()})은 업로드할 수 없습니다.",
            f"개방형 포맷으로 변환해 등록하세요. {ext.upper()} → "
            f"{CLOSED_DOC[ext].upper()}"))

    if ext in ARCHIVE_OTHER:
        res.add(Finding(
            "9-나", "파일 확장자", Level.REJECT,
            f"ZIP 외 압축 확장자({ext})는 등록할 수 없습니다.",
            "ZIP으로 다시 압축하고, ZIP 내부 파일의 대표확장자 1개를 확장자로 등록하세요."))

    if ext == "zip":
        _check_zip(res)

    if ext in TABULAR_DOC:
        res.add(Finding(
            "9-라", "파일 확장자", Level.ACTION,
            f"{ext.upper()} 파일입니다. 표·수치 등 텍스트 형태만 들어 있으면 CSV로 "
            "변환해 개방해야 합니다.",
            "이미지·동영상 등 비정형 데이터가 문서 안에 포함된 경우에만 "
            f"{ext.upper()} 업로드가 허용됩니다. 표 형식이면 CSV로 변환하세요."))

    if ext in STAGE1:
        res.add(Finding(
            "9-가", "파일 확장자", Level.ACTION,
            "PDF는 1단계(기계판독 불가) 포맷입니다.",
            "오픈포맷(CSV, JSON, XML)을 원칙으로 합니다. PDF로 직접 제공해야 하는 "
            "경우 제공신청 절차를 거치고 샘플데이터를 오픈포맷으로 변환해 등록하세요."))
    elif ext in STAGE2 - set(CLOSED_DOC):
        res.add(Finding(
            "9-가", "파일 확장자", Level.ACTION,
            f"{ext.upper()}는 2단계(미충족 포맷)입니다.",
            "오픈포맷(CSV, JSON, XML) 또는 3단계 이상 포맷으로 변환해 등록하세요."))

    if ext in UNSTRUCTURED:
        res.add(Finding(
            "8-가", "비정형 데이터 주의사항", Level.REVIEW,
            "비정형(이미지·동영상·음성) 데이터입니다. 개인정보 포함 여부를 "
            "반드시 사전 점검해야 합니다.",
            _unstructured_guide(ext)))

    if ext in SPECIAL_TOOL:
        res.add(Finding(
            "8-바", "비정형 데이터 주의사항", Level.ACTION,
            f"{ext.upper()}는 {SPECIAL_TOOL[ext]} 등 특정 프로그램으로만 확인할 수 "
            "있는 파일입니다.",
            "해당 프로그램 사용법을 기재한 설명 파일을 첨부하세요."))

    if res.file_size >= LINK_SIZE_LIMIT:
        res.add(Finding(
            "6-마", "링크데이터 등록 검토", Level.ACTION,
            f"파일 용량이 {res.file_size / 1024 / 1024:.0f}MB로 500MB 이상입니다.",
            "500MB 이상은 링크데이터로 등록하세요. 링크는 회원 로그인·추가 검색 없이 "
            "다운로드가 가능한 상세페이지여야 합니다."))


def _unstructured_guide(ext: str) -> str:
    if ext in {"png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp"}:
        return ("사람 얼굴·차량 번호판 등 식별 가능한 정보는 블러 처리하세요. "
                "마스크나 선글라스를 착용한 경우에도 블러 처리를 권고합니다. "
                "파일이 3개 이상이면 내용별로 분류해 ZIP으로 묶어 등록하세요.")
    if ext in {"mp4", "avi", "wmv", "mov", "mpeg"}:
        return ("공인 모델이 아닌 인물, 차량 외관(번호판·차종·색상)이 보이는 경우 "
                "블러 처리하세요.")
    return ("음성·음향에 개인정보가 노출되면 묵음 처리 등으로 비식별화하세요. "
            "군부대·국가안보 관련 정보는 별도 비식별 처리가 필요합니다.")


def _check_zip(res: Result) -> None:
    try:
        entries = zip_entries(res.file_path)
    except Exception as exc:                       # noqa: BLE001
        res.add(Finding("9-나", "파일 확장자", Level.REJECT,
                        f"ZIP 파일을 열 수 없습니다: {exc}",
                        "손상되지 않은 ZIP 파일로 다시 압축해 등록하세요."))
        return

    inner = [ext_of(n) for n in entries if ext_of(n)]
    uniq = sorted(set(inner))
    nested = [e for e in uniq if e in ARCHIVE_OTHER or e == "zip"]

    if not entries:
        res.add(Finding("9-나", "파일 확장자", Level.REJECT,
                        "ZIP 안에 파일이 없습니다.", "내용을 담아 다시 압축하세요."))
        return

    rep = next((e for e in ("csv", "json", "xml") if e in uniq), None)
    res.add(Finding(
        "9-나", "파일 확장자", Level.REVIEW,
        f"ZIP 내부 확장자: {', '.join(uniq)} (총 {len(entries)}개 파일)",
        (f"대표확장자 1개({rep.upper()})를 확장자로 등록하세요." if rep else
         "대표확장자는 오픈포맷(3단계 이상)을 권장합니다. ZIP 내부 파일의 확장자를 "
         "반드시 등록 정보에 기재하세요."),
        samples=entries[:10]))

    if nested:
        res.add(Finding(
            "9-나", "파일 확장자", Level.REJECT,
            f"ZIP 안에 다른 압축파일이 있습니다: {', '.join(nested)}",
            "이중 압축을 풀고 실제 데이터 파일만 담아 압축하세요."))

    closed = [e for e in uniq if e in CLOSED_DOC]
    if closed:
        res.add(Finding(
            "9-다", "파일 확장자", Level.REJECT,
            f"ZIP 안에 비개방형 문서 포맷이 있습니다: {', '.join(closed)}",
            "개방형 포맷으로 변환해 다시 압축하세요. "
            "HWP→HWPX, XLS→XLSX, DOC→DOCX, PPT→PPTX"))

    imgs = [n for n in entries if ext_of(n) in UNSTRUCTURED]
    if imgs:
        res.add(Finding(
            "8-다", "비정형 데이터 주의사항", Level.REVIEW,
            f"ZIP 안에 비정형 파일이 {len(imgs)}개 있습니다.",
            "얼굴·번호판 등 식별 가능한 정보의 블러 처리 여부를 등록 전에 "
            "실무담당자가 확인하세요."))
