# -*- coding: utf-8 -*-
"""OPEN API 픽스 엔진 — 선택한 조항만 등록 정보를 고쳐 준다.

파일데이터 픽스(fixer.py)는 데이터 파일을 고쳐 새 파일로 저장하지만, OPEN API 는
고칠 대상이 **포털 등록 화면에 넣는 값**이다. 그래서 결과물이 파일 하나가 아니라
'무엇을 무엇으로 바꾸면 되는지'의 대조표이고, 그 대조표를 JSON 으로도 남긴다.
화면에서는 고친 값을 그대로 복사해 포털에 붙여 넣으면 된다.

기술문서(Swagger·명세표) 자체는 고치지 않는다. 기관이 서명·배포한 문서를 도구가
말없이 바꾸면 원본과 어긋나 12-나(기술문서 ↔ 등록내용 상이)를 새로 만들기 때문에,
문서에서 고쳐야 할 값은 `manual` 목록으로 따로 알려 준다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .api_models import ApiSpec, code_key, norm, strip_query
from .api_models import PORTAL_ERROR_CODES
from .fixer import TIER_CONTENT, TIER_FORMAT

# 픽스 키 -> (표시명, 등급, 적용범위, 설명)
API_FIXABLE: Dict[str, Tuple[str, str, str, str]] = {
    "api:5-가": ("목록명 특수문자 정리", TIER_FORMAT, "목록명",
                "_(언더바)와 ()(괄호) 외의 특수문자를 지웁니다."),
    "api:5-나": ("목록명 주기·연도 표기 제거", TIER_CONTENT, "목록명",
                "공공데이터_개방현황(연간) → 공공데이터_개방현황. "
                "지운 낱말이 데이터 이름의 일부는 아닌지 확인하세요."),
    "api:6-가": ("키워드 특수문자 제거", TIER_FORMAT, "키워드",
                "키워드에서 특수문자를 지웁니다."),
    "api:6-다": ("중복 키워드 제거", TIER_FORMAT, "키워드",
                "띄어쓰기만 다른 중복 키워드 중 첫 번째만 남깁니다."),
    "api:7-가": ("설명 연속 띄어쓰기 정리", TIER_FORMAT, "설명",
                "두 칸 이상 이어진 공백을 한 칸으로 줄입니다."),
    "api:10-나": ("담당자 연락처 하이픈 정리", TIER_FORMAT, "담당자연락처",
                 "0212345678 → 02-1234-5678. 지역번호가 없으면 손대지 않습니다."),
    "api:18-가": ("URL 요청 파라메터 제거", TIER_FORMAT, "URL",
                 ".../getList?serviceKey=... → .../getList"),
    "api:22-나": ("포털 표준 에러코드 삭제", TIER_CONTENT, "에러코드",
                 "포털이 직접 출력하는 에러코드 행을 지웁니다."),
    "api:22-다": ("에러코드 200 삭제", TIER_CONTENT, "에러코드",
                 "에러코드 200 행을 지웁니다."),
}

# 자동 수정하지 않는 조항 -> 사람이 판단해야 하는 이유
API_NOT_FIXABLE_REASON = {
    "1-가": "로그성 데이터인지는 데이터의 뜻을 아는 담당자가 판단해야 합니다.",
    "1-나": "목록명이 뜻하는 데이터 항목을 임의로 만들어 넣을 수 없습니다.",
    "2-가": "목록명과 데이터의 관련성은 사람이 판단해야 합니다.",
    "3-가": "타기관 동의 공문은 기관이 직접 받아 제출해야 합니다.",
    "3-나": "가공 여부는 담당자가 확인해야 합니다.",
    "4-가": "포털에 이미 등록된 목록인지는 포털에서 직접 조회해야 합니다.",
    "5-다": "적절한 기관명·데이터 명칭은 담당자가 정해야 합니다.",
    "6-나": "키워드를 임의로 만들거나 지우면 검색성이 달라져 담당자가 정해야 합니다.",
    "9-가": "제공번호는 제공신청 결과로 받은 값이라 임의로 채울 수 없습니다.",
    "10-가": "부담당자는 기관이 지정해야 합니다.",
    "11-가": "링크 주소는 담당자가 실제 페이지를 확인해 넣어야 합니다.",
    "11-나": "링크 페이지 구성은 기관 홈페이지에서 고쳐야 합니다.",
    "11-다": "링크 페이지 내용은 사람이 열어 확인해야 합니다.",
    "12-가": "기술문서 검토 요청은 담당자가 메일로 진행해야 합니다.",
    "12-나": "기술문서와 등록 내용 중 어느 쪽이 맞는지는 담당자가 정해야 합니다.",
    "12-다": "TEST KEY 는 발급받은 값을 담당자가 입력해야 합니다.",
    "13-나": "인증모듈 적용은 시스템에서 처리해야 합니다.",
    "13-다": "전송방식 변경은 API 구현을 고쳐야 합니다.",
    "13-라": "포트 변경은 서버 설정을 고쳐야 합니다.",
    "14-나": "Example Value 는 명세서에서 직접 확인해야 합니다.",
    "14-다": "변수 설명은 담당자가 뜻에 맞게 써야 합니다.",
    "15-나": "이용허락범위는 기관이 검토해 선택해야 합니다.",
    "15-다": "이용허락 동의서는 기관이 첨부해야 합니다.",
    "15-라": "응답의 저작 관련 표출은 API 구현을 고쳐야 합니다.",
    "16-가": "응답 포맷은 API 구현을 고쳐야 합니다.",
    "16-나": "Content-Type 은 End Point 응답 헤더 설정에서 고쳐야 합니다.",
    "16-다": "두 포맷의 구조 일치는 사람이 대조해야 합니다.",
    "16-라": "REST → LINK 형식 전환은 등록 방식을 바꾸는 일입니다.",
    "17-가": "오퍼레이션명은 담당자가 목록명과 다르게 지어야 합니다.",
    "17-나": "국문 오퍼레이션명은 담당자가 지어야 합니다.",
    "18-나": "URL 규칙에 맞는 이름은 담당자가 정해야 합니다.",
    "18-다": "영문 항목명은 담당자가 지어야 합니다.",
    "18-라": "항목 설명과 단위는 담당자가 써야 합니다.",
    "18-마": "코드표 제공 방식은 담당자가 정해야 합니다.",
    "18-바": "실제 동작하는 샘플값은 담당자가 넣어야 합니다.",
    "18-사": "항목유형은 실제 자료형에 맞게 담당자가 골라야 합니다.",
    "18-아": "SWAGGER 미리보기는 사람이 열어 확인해야 합니다.",
    "19-가": "호출 오류는 API 서버에서 고쳐야 합니다.",
    "19-나": "상태코드는 API 구현을 고쳐야 합니다.",
    "19-다": "기술문서와 실제 응답 중 어느 쪽이 맞는지는 담당자가 정해야 합니다.",
    "19-마": "응답 지연은 API 성능을 개선해야 합니다.",
    "20-가": "포맷 변환 파라메터는 API 구현에 추가해야 합니다.",
    "20-나": "페이징 파라메터는 API 구현에 추가해야 합니다.",
    "21-가": "필수 응답 항목은 API 구현에 추가해야 합니다.",
    "21-나": "조건별 응답 구조는 사람이 대조해야 합니다.",
    "22-가": "에러코드 표는 담당자가 기술문서에 작성해야 합니다.",
    "23-가": "비식별 처리는 원본 데이터에서 해야 합니다.",
    "23-나": "개인정보 항목을 지울지는 담당자가 판단해야 합니다.",
    "23-바": "설명 파일 첨부는 담당자가 해야 합니다.",
}

RE_KW_SPECIAL = re.compile(r"[^가-힣A-Za-z0-9 ]")
RE_LIST_SPECIAL = re.compile(r"[^가-힣A-Za-z0-9 _()]")
RE_CYCLE_WORD = re.compile(r"(매일|일별|매월|월별|매년|연간|반기|분기|주간|주별|"
                           r"갱신주기|업데이트|상시|수시)")
RE_YEAR_WORD = re.compile(r"((?:19|20)\d{2}\s*년?|['’]\d{2}\s*년)")
RE_PHONE_DIGITS = re.compile(r"^0\d{8,10}$")
SEOUL_LIKE = ("02",)

#: 픽스 대상이 되는 URL 성격의 등록 항목
URL_FIELDS = ("서비스URL", "링크URL")


@dataclass
class ApiChange:
    field: str = ""
    before: str = ""
    after: str = ""
    rule_id: str = ""
    label: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "before": self.before, "after": self.after,
                "rule_id": self.rule_id, "label": self.label}


@dataclass
class ApiFixReport:
    out_path: str = ""
    changes: List[ApiChange] = field(default_factory=list)
    #: 지운 에러코드 — (픽스 키, 표시 문구). 어느 조항이 지웠는지 남겨야
    #: 화면의 '적용 내역' 에 건수를 조항별로 셀 수 있다.
    removed: List[Tuple[str, str]] = field(default_factory=list)
    manual: List[str] = field(default_factory=list)      # 기술문서에서 직접 고칠 값
    skipped: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def removed_codes(self) -> List[str]:
        return [text for _rule, text in self.removed]

    @property
    def applied(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for c in self.changes:
            out[c.rule_id] = out.get(c.rule_id, 0) + 1
        for rule, _text in self.removed:
            out[rule] = out.get(rule, 0) + 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        counts = self.applied
        return {
            "out_path": self.out_path,
            "applied": [{"rule_id": k, "label": API_FIXABLE[k][0],
                         "tier": API_FIXABLE[k][1], "count": v}
                        for k, v in counts.items() if k in API_FIXABLE],
            "changes": [c.to_dict() for c in self.changes],
            "removed_codes": self.removed_codes,
            "removed_rows": len(self.removed_codes),
            "manual": self.manual,
            "skipped": self.skipped,
            "error": self.error,
        }


def api_fixable_rules() -> List[Dict[str, str]]:
    return [{"rule_id": k, "label": v[0], "tier": v[1], "scope": v[2], "note": v[3]}
            for k, v in API_FIXABLE.items()]


# ---- 값 단위 변환 ------------------------------------------------------
def fix_list_special(v: str) -> str:
    return re.sub(r"\s{2,}", " ", RE_LIST_SPECIAL.sub("", v)).strip()


def fix_list_cycle(v: str) -> str:
    """목록명에서 주기·연도 표기를 걷어낸다."""
    out = v
    # (연간) · [2023년] 처럼 괄호 안이 통째로 주기·연도인 경우 먼저 지운다
    out = re.sub(r"[(\[]\s*(?:%s|%s)[^)\]]{0,4}[)\]]"
                 % (RE_CYCLE_WORD.pattern, RE_YEAR_WORD.pattern), "", out)
    out = RE_CYCLE_WORD.sub("", out)
    out = RE_YEAR_WORD.sub("", out)
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" _-·,")


def fix_keywords_special(v: str) -> str:
    kws = [RE_KW_SPECIAL.sub("", k).strip() for k in re.split(r"[,;\n]+", v)]
    return ", ".join([k for k in kws if k])


def fix_keywords_dup(v: str) -> str:
    seen, out = set(), []
    for k in [x.strip() for x in re.split(r"[,;\n]+", v) if x.strip()]:
        key = re.sub(r"\s+", "", k)
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    return ", ".join(out)


def fix_desc_space(v: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", v).strip()


def fix_phone(v: str) -> str:
    s = norm(v)
    digits = re.sub(r"\D", "", s)
    if not RE_PHONE_DIGITS.match(digits):
        return v
    head, rest = ((digits[:2], digits[2:]) if digits.startswith(SEOUL_LIKE)
                  else (digits[:3], digits[3:]))
    if len(rest) < 7:
        return v
    return f"{head}-{rest[:-4]}-{rest[-4:]}"


#: 픽스 키 -> (대상 등록 항목, 변환 함수)
FIELD_FIXERS: Dict[str, Tuple[str, Any]] = {
    "api:5-가": ("목록명", fix_list_special),
    "api:5-나": ("목록명", fix_list_cycle),
    "api:6-가": ("키워드", fix_keywords_special),
    "api:6-다": ("키워드", fix_keywords_dup),
    "api:7-가": ("설명", fix_desc_space),
    "api:10-나": ("담당자연락처", fix_phone),
}


# ---- 실행 --------------------------------------------------------------
def default_api_out_path(name: str = "등록정보") -> str:
    return f"{name}_수정.json"


def fix_api(spec: ApiSpec, rule_ids: List[str],
            out_path: Optional[str] = None) -> Tuple[ApiSpec, ApiFixReport]:
    """선택한 조항만 적용해 고친 ApiSpec 과 대조표를 돌려준다.

    원본 spec 은 건드리지 않는다. 화면이 '고치기 전' 결과를 그대로 들고 있어야
    반려 건수가 얼마나 줄었는지 비교할 수 있기 때문이다.
    """
    rep = ApiFixReport()
    rules = [r for r in rule_ids if r in API_FIXABLE]
    rep.skipped = [r for r in rule_ids if r not in API_FIXABLE]
    if not rules:
        rep.error = "자동 수정이 가능한 항목이 선택되지 않았습니다."
        return spec, rep

    meta = dict(spec.meta)

    # 1) 등록 항목 값 고치기 — 같은 칸에 두 조항이 걸리면 차례로 적용된다
    for key in rules:
        target = FIELD_FIXERS.get(key)
        if not target:
            continue
        fld, fn = target
        before = norm(meta.get(fld))
        if not before:
            continue
        after = fn(before)
        if after != before:
            meta[fld] = after
            rep.changes.append(ApiChange(
                field=fld, before=before, after=after,
                rule_id=key, label=API_FIXABLE[key][0]))

    # 2) URL 에 붙은 요청 파라메터 떼기
    if "api:18-가" in rules:
        for fld in URL_FIELDS:
            before = norm(meta.get(fld))
            after = strip_query(before)
            if before and after != before:
                meta[fld] = after
                rep.changes.append(ApiChange(
                    field=fld, before=before, after=after,
                    rule_id="api:18-가", label=API_FIXABLE["api:18-가"][0]))
        for op in spec.operations:
            if "?" in norm(op.url):
                rep.manual.append(
                    f"기술문서 · {op.title} · URL: {op.url} → {strip_query(op.url)}")

    # 3) 에러코드 행 지우기
    keep = []
    for c in spec.error_codes:
        k = code_key(c.code)
        if "api:22-다" in rules and k == "200":
            rep.removed.append(("api:22-다", f"{c.code} · {c.message}".strip(" ·")))
            continue
        if "api:22-나" in rules and k in PORTAL_ERROR_CODES:
            rep.removed.append(("api:22-나", f"{c.code} · {PORTAL_ERROR_CODES[k]}"))
            continue
        keep.append(c)
    if rep.removed and spec.source_name:
        rep.manual.append(
            f"기술문서 · 에러코드 표에서 {len(rep.removed_codes)}개 행을 지우세요: "
            + ", ".join(rep.removed_codes[:6]))

    if not rep.changes and not rep.removed:
        rep.error = "선택한 조항으로 바뀌는 값이 없습니다."
        return spec, rep

    fixed = ApiSpec(
        source_name=spec.source_name, source_kind=spec.source_kind,
        title=spec.title, base_url=strip_query(spec.base_url)
        if "api:18-가" in rules else spec.base_url,
        operations=spec.operations, error_codes=keep,
        formats=list(spec.formats), notes=list(spec.notes),
        parse_error=spec.parse_error, meta=meta)

    if out_path:
        rep.out_path = _save(fixed, rep, out_path)
    return fixed, rep


def _save(spec: ApiSpec, rep: ApiFixReport, path: str) -> str:
    """고친 등록 정보를 JSON 으로 남긴다. 포털에 붙여 넣을 값이 곧 이 파일이다."""
    payload = {
        "등록정보": spec.meta,
        "수정내역": [c.to_dict() for c in rep.changes],
        "삭제한_에러코드": rep.removed_codes,
        "기술문서에서_직접_고칠_값": rep.manual,
        "에러코드": [c.to_dict() for c in spec.error_codes],
    }
    root = os.path.splitext(path)[0]
    out = root + ".json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return out
