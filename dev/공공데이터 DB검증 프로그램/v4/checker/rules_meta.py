# -*- coding: utf-8 -*-
"""등록 메타정보 검사: 목록명(1) · 데이터명(2) · 키워드(3) · 설명(4) ·
중복(5) · 제3자권리·공공누리(7) · 기준일(11) · 제공신청(14) · 언어(15) · 차기예정일(16)."""
from __future__ import annotations

import re
from typing import Dict, List

from .models import Finding, Level, Result

RE_LIST_OK = re.compile(r"^[가-힣A-Za-z0-9 _()]+$")
RE_PERIODICITY = re.compile(
    r"(매일|일별|매월|월별|매년|연간|반기|분기|주간|주별|갱신|업데이트|"
    r"\d{4}\s*년|\d{1,2}\s*월|\d{1,2}\s*일|\d{4}[-./]\d{1,2})")
RE_STAT_DOC = re.compile(r"(통계|보고서|보도자료|연보|백서|간행물|발간)")
RE_DATE_IN_NAME = re.compile(r"(\d{4}[-./]?\d{2}[-./]?\d{2}|\d{4}\s*년\s*\d{1,2}\s*월)")
RE_NON_KO_EN = re.compile(r"[^ㄱ-ㆎ가-힣A-Za-z0-9 _()\-.,]")
NURI_TYPES = {"1", "2", "3", "4", "제1유형", "제2유형", "제3유형", "제4유형"}
CYCLES = {"연간": 30, "반기": 30, "월간": 15, "분기": 15}


def check_meta(res: Result, meta: Dict) -> None:
    if not meta:
        return
    _list_name(res, meta)
    _data_name(res, meta)
    _keywords(res, meta)
    _description(res, meta)
    _nuri(res, meta)
    _base_date(res, meta)
    _language(res, meta)
    _next_date(res, meta)
    _request_no(res, meta)


# ---- 1번 목록명 --------------------------------------------------------
def _list_name(res: Result, meta: Dict) -> None:
    name = (meta.get("목록명") or "").strip()
    if not name:
        return
    bad = sorted(set(re.findall(r"[^가-힣A-Za-z0-9 _()]", name)))
    if bad:
        res.add(Finding(
            "1-가", "목록명", Level.REJECT,
            f"목록명에 허용되지 않는 특수문자가 있습니다: {' '.join(bad)}",
            "목록명은 한글·영문·숫자와 _(언더바), ()(괄호)만 사용할 수 있습니다.",
            samples=[name]))

    if RE_PERIODICITY.search(name):
        if RE_STAT_DOC.search(name) and re.search(r"\(\s*\d{4}\s*\)", name):
            res.add(Finding(
                "1-다", "목록명", Level.REVIEW,
                "통계 발간물·보도자료로 보이며 목록명에 기준연도가 있습니다.",
                "통계 발간물·보도자료는 기준연도 표기가 허용됩니다. "
                "예: 공공데이터 활용지원센터_통계자료 연간 보고서(2021)",
                samples=[name]))
        else:
            res.add(Finding(
                "1-나", "목록명", Level.REJECT,
                "목록명에 업데이트 주기 또는 기준년도·월·일 표시가 있습니다.",
                "목록명에서 주기·기준일 표기를 제거하세요. 목록 하나를 주기성으로 "
                "관리해야 합니다. 링크데이터도 동일하게 적용됩니다.",
                samples=[name]))

    if "_" not in name:
        res.add(Finding(
            "1-가", "목록명", Level.REVIEW,
            "목록명이 기관명_데이터명 형태가 아닌 것으로 보입니다.",
            "기관명과 직관적인 데이터 명칭을 조합하세요. "
            "예: 공공데이터활용지원센터_자전거보관소 현황",
            samples=[name]))


# ---- 2번 데이터명 ------------------------------------------------------
def _data_name(res: Result, meta: Dict) -> None:
    name = (meta.get("데이터명") or "").strip()
    if not name:
        return
    if RE_DATE_IN_NAME.search(name):
        res.add(Finding(
            "2-가", "데이터명", Level.REJECT,
            "데이터명에 기준일자가 포함되어 있습니다.",
            "기준일자를 제거하세요. 데이터 기준일을 선택하면 자동으로 적용됩니다.",
            samples=[name]))
    org = (meta.get("기관명") or "").strip()
    if org and org in name:
        res.add(Finding(
            "2-가", "데이터명", Level.REVIEW,
            f"데이터명에 기관명('{org}')이 중복 기재되어 있습니다.",
            "기관명은 자동완성되므로 데이터명에 따로 적지 않아도 됩니다.",
            samples=[name]))


# ---- 3번 키워드 --------------------------------------------------------
def _keywords(res: Result, meta: Dict) -> None:
    raw = (meta.get("키워드") or "").strip()
    if not raw:
        return
    kws = [k.strip() for k in re.split(r"[,;\n]+", raw) if k.strip()]
    if not 3 <= len(kws) <= 8:
        res.add(Finding(
            "3-나", "키워드", Level.REJECT,
            f"키워드가 {len(kws)}개입니다.",
            "공공데이터포털에서 검색될 관련 키워드를 3~8개 작성하세요.",
            samples=kws[:8]))

    norm: Dict[str, List[str]] = {}
    for k in kws:
        norm.setdefault(re.sub(r"\s+", "", k), []).append(k)
    dups = [v for v in norm.values() if len(v) > 1]
    if dups:
        res.add(Finding(
            "3-다", "키워드", Level.REJECT,
            "띄어쓰기만 다른 동일 키워드가 있습니다.",
            "중복 키워드를 제거하세요. 예: '자전거 주차장 데이터'와 "
            "'자전거주차장데이터'는 동일 키워드로 봅니다.",
            samples=[" / ".join(d) for d in dups]))

    name = (meta.get("데이터명") or "") + (meta.get("목록명") or "")
    org = (meta.get("기관명") or "").strip()
    overlap = [k for k in kws
               if (org and k == org) or k == (meta.get("데이터명") or "").strip()
               or (len(k) >= 5 and k in name)]
    if overlap:
        res.add(Finding(
            "3-가", "키워드", Level.ACTION,
            f"공공데이터명·기관명과 동일한 키워드가 있습니다: {', '.join(overlap[:5])}",
            "데이터명·기관명과 동일한 값, 특수문자는 키워드에서 제외하고 "
            "활용자가 검색할 만한 연관 키워드를 넣으세요.",
            samples=overlap[:8]))

    special = [k for k in kws if re.search(r"[^가-힣A-Za-z0-9 ]", k)]
    if special:
        res.add(Finding(
            "3-가", "키워드", Level.ACTION,
            f"키워드에 특수문자가 있습니다: {', '.join(special[:5])}",
            "키워드에서 특수문자를 제거하세요.", samples=special[:8]))


# ---- 4번 데이터 설명 ---------------------------------------------------
def _description(res: Result, meta: Dict) -> None:
    desc = (meta.get("설명") or "").strip()
    if not desc:
        return
    length = len(re.sub(r"\s", "", desc))
    if length < 50:
        res.add(Finding(
            "4-가", "데이터 설명", Level.REJECT,
            f"설명이 공백 제외 {length}자입니다.",
            "생성·수집 목적과 활용성 측면에서 상세히 기재하세요. "
            "한글·영문·숫자로 50자 이상이어야 합니다."))
    if re.search(r"\s{2,}", desc):
        res.add(Finding(
            "4-가", "데이터 설명", Level.ACTION,
            "설명에 연속된 띄어쓰기가 있습니다.",
            "여러 번의 띄어쓰기를 제거하세요. 분량 채우기용 반복은 반려 대상입니다."))
    words = [w for w in re.split(r"\s+", desc) if len(w) >= 3]
    rep = {w: words.count(w) for w in set(words) if words.count(w) >= 4}
    if rep:
        res.add(Finding(
            "4-가", "데이터 설명", Level.ACTION,
            f"같은 단어가 반복 사용되었습니다: "
            f"{', '.join(f'{k}({v}회)' for k, v in list(rep.items())[:4])}",
            "동일 단어 반복 없이 데이터 내용을 구체적으로 설명하세요."))
    years = set(re.findall(r"(19|20)\d{2}", desc))
    if years:
        res.add(Finding(
            "4-가", "데이터 설명", Level.REVIEW,
            "설명에 연도가 기재되어 있습니다.",
            "개방하려는 데이터의 내용과 연도가 설명과 일치하는지 확인하세요."))


# ---- 7번 공공누리 ------------------------------------------------------
def _nuri(res: Result, meta: Dict) -> None:
    nuri = str(meta.get("공공누리유형") or "").strip()
    if not nuri:
        res.add(Finding(
            "7-나", "제3자 권리·공공누리", Level.REVIEW,
            "공공누리 유형이 입력되지 않았습니다.",
            "이용허락범위를 검토해 제1~4유형 중 해당 유형을 체크하고, 보고서 또는 "
            "링크 상세화면에서 동일한 공공누리 마크가 확인되는지 대조하세요."))
        return
    if nuri not in NURI_TYPES:
        res.add(Finding(
            "7-나", "제3자 권리·공공누리", Level.ACTION,
            f"공공누리 유형 값이 확인되지 않습니다: {nuri}",
            "제1유형(출처표시), 제2유형(+상업적 이용금지), 제3유형(+변경금지), "
            "제4유형(+상업적 이용금지+변경금지) 중 하나를 선택하세요."))
    if str(meta.get("저작권포함", "")).strip() in ("예", "Y", "y", "true", "True"):
        res.add(Finding(
            "7-다", "제3자 권리·공공누리", Level.ACTION,
            "저작권이 있는 데이터로 표시되어 있습니다.",
            "'저작물 이용허락 동의서'를 첨부해야 합니다. 데이터별로 저작권 여부가 "
            "다르면 기타유의사항에 관련 내용을 반드시 작성하세요."))


# ---- 11번 데이터 기준일 -----------------------------------------------
def _base_date(res: Result, meta: Dict) -> None:
    entered = (meta.get("데이터기준일") or "").strip()
    guessed = res.suggested_base_date
    note = meta.get("기타유의사항", "") or ""
    if not entered:
        if guessed:
            res.add(Finding(
                "11-나", "데이터 기준일", Level.REVIEW,
                f"파일 내 가장 최근 날짜는 {guessed}입니다.",
                "파일 내 기준일이 있으면 그 날짜(여러 개면 가장 최근 날짜)를 "
                "데이터 기준일로 설정하세요."))
        return
    if guessed and entered[:10] != guessed:
        has_reason = any(k in note for k in ("기준일", "생성", "검증", "현행화"))
        res.add(Finding(
            "11-나", "데이터 기준일", Level.ACTION if not has_reason else Level.REVIEW,
            f"입력한 기준일({entered})과 파일 내 최근 날짜({guessed})가 다릅니다.",
            "파일 내 기준일을 우선 적용하세요. 생성일자와 기준일자가 다른 경우 "
            "기타유의사항(한글)에 사유를 기재해야 합니다."
            + (" (사유가 기재되어 있습니다.)" if has_reason else "")))


# ---- 15번 언어 --------------------------------------------------------
def _language(res: Result, meta: Dict) -> None:
    for key in ("목록명", "데이터명", "설명"):
        val = meta.get(key) or ""
        bad = sorted(set(RE_NON_KO_EN.findall(val)))
        bad = [b for b in bad if b.strip()]
        if bad:
            res.add(Finding(
                "15-가", "데이터 언어 선택", Level.REJECT,
                f"{key}에 한글·영문 외 문자가 있습니다: {' '.join(bad[:8])}",
                "포털 화면에 표출되는 목록명·메타데이터는 한글과 영문만 가능합니다. "
                "다운로드되는 파일데이터에는 다른 언어를 쓸 수 있습니다.",
                samples=[val[:60]]))


# ---- 16번 차기 등록 예정일 --------------------------------------------
def _next_date(res: Result, meta: Dict) -> None:
    cycle = (meta.get("갱신주기") or "").strip()
    nxt = (meta.get("차기등록예정일") or "").strip()
    if cycle and cycle in CYCLES and not nxt:
        res.add(Finding(
            "16-가", "차기 등록 예정일", Level.ACTION,
            f"갱신주기가 '{cycle}'인데 차기 등록 예정일이 없습니다.",
            f"등록일·수정일 기준으로 차기 예정일을 설정하세요. "
            f"{cycle}은 ±{CYCLES[cycle]}일 이내 취합이 가능한 경우 예외 승인되며, "
            "예외 승인이 필요하면 기타유의사항에 사유를 작성해야 합니다."))


# ---- 14번 제공신청 ----------------------------------------------------
def _request_no(res: Result, meta: Dict) -> None:
    applied = str(meta.get("제공신청여부") or "").strip()
    number = str(meta.get("제공번호") or "").strip()
    if applied in ("예", "Y", "y") and not number:
        res.add(Finding(
            "14-가", "제공신청 필수사항", Level.REJECT,
            "제공신청 '예'를 선택했으나 제공번호가 없습니다.",
            "제공번호를 입력하세요."))
    if res.ext == "pdf" and applied not in ("예", "Y", "y"):
        res.add(Finding(
            "14-가", "제공신청 필수사항", Level.ACTION,
            "PDF 파일은 제공신청을 통한 개방 대상입니다.",
            "제공신청 여부에서 '예'를 선택하고 제공번호를 입력하세요. "
            "샘플데이터는 오픈포맷으로 변환해 등록해야 합니다."))
