# -*- coding: utf-8 -*-
"""OPEN API 등록 사전검토 규칙 1~23번.

『(OPEN API) 공공데이터 목록 및 데이터 등록 시 검토사항 및 반려 사유 안내(’26.2.~)』
23개 항목을 옮긴 것이다. 파일데이터 쪽 규칙(rules_csv·rules_file·rules_meta)과
조항 번호가 겹치므로, 픽스 키에는 `api:` 접두어를 붙여 서로 섞이지 않게 한다.

자동 판정이 불가능한 항목(타기관 동의 공문, 목록명 관련성 판단 등)은 지우지 않고
'확인권장'으로 남긴다. 검토자가 무엇을 눈으로 봐야 하는지가 곧 이 도구의 값이다.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from .api_models import (ALLOWED_TYPES, FILLER_PARAMS, FORMAT_PARAMS, LOG_LIKE,
                         OK_CONTENT_TYPE, PAGING_HINTS, PORTAL_ERROR_CODES,
                         PRIVACY_LIKE, REG_CLOUD, REG_GW, REG_LINK, REG_PUBC,
                         REQUIRED_RESPONSE, VAGUE_WORDS, ApiSpec, code_key,
                         has_hangul, is_truthy, looks_like, name_equals, norm,
                         parse_url, RE_UNIT_SYMBOL)
from .api_probe import SLOW_LIMIT, ProbeResult
from .models import Finding, Level, Result

# ---- 항목 이름 (안내문의 '항 목' 열) ------------------------------------
IT = {
    1: "불량 데이터 개방", 2: "관련 없는 데이터", 3: "타기관 데이터 개방",
    4: "중복 등록 제외", 5: "목록명", 6: "키워드", 7: "데이터 설명",
    8: "API 일시정지·폐기", 9: "제공신청 필수사항", 10: "담당자 지정",
    11: "링크형태 API URL", 12: "PUBC 등록 검토", 13: "GW 등록 절차",
    14: "멀티클라우드 등록", 15: "제3자 권리·공공누리", 16: "응답 포맷",
    17: "오퍼레이션명", 18: "오퍼레이션 정보", 19: "호출 오류",
    20: "요청 파라메터", 21: "응답 파라메터", 22: "에러코드",
    23: "비공개 정보·비정형",
}

#: 응답 봉투(envelope) — 데이터 본문이 아니라 규격상 늘 붙는 항목
ENVELOPE = ("resultcode", "resultmsg", "totalcount", "numofrows", "pageno",
            "header", "body", "items", "item", "response", "returncode",
            "returnauthmsg", "returnreasoncode", "errmsg", "resultmessage",
            "currentcount", "matchcount", "perpage", "page")

NURI_TYPES = {"1", "2", "3", "4", "제1유형", "제2유형", "제3유형", "제4유형"}

RE_CYCLE = re.compile(r"(매일|일별|매월|월별|매년|연간|반기|분기|주간|주별|"
                      r"갱신주기|업데이트|상시|수시)")
RE_YEAR = re.compile(r"((?:19|20)\d{2}\s*년?|['’]\d{2}\s*년)")
RE_LIST_BAD = re.compile(r"[^가-힣A-Za-z0-9 _()]")
RE_PHONE_OK = re.compile(r"^0\d{1,2}-\d{3,4}-\d{4}$")
RE_PHONE_DIGITS = re.compile(r"^0\d{8,10}$")
RE_UNIT_IN_DESC = re.compile(r"(단위|㎟|㎠|㎡|㎢|㎥|㎜|㎝|㎞|㎏|㎎|㎖|ℓ|℃|℉|㎾|㏊|%|원|명|건|개)")
RE_CODE_PARAM = re.compile(r"(코드|code|cd)$", re.I)

# 픽스 키 (api_fixer.API_FIXABLE 와 짝을 이룬다)
FX_LIST_SPECIAL = "api:5-가"
FX_LIST_CYCLE = "api:5-나"
FX_KW_SPECIAL = "api:6-가"
FX_KW_DUP = "api:6-다"
FX_DESC_SPACE = "api:7-가"
FX_PHONE = "api:10-나"
FX_URL_QUERY = "api:18-가"
FX_ERR_PORTAL = "api:22-나"
FX_ERR_200 = "api:22-다"


def check_api(res: Result, spec: ApiSpec,
              probes: Optional[Sequence[ProbeResult]] = None) -> None:
    """등록 정보 + 기술문서 + (선택) 실호출 결과를 23개 항목으로 검토한다."""
    probes = list(probes or [])
    _bad_data(res, spec)             # 1
    _relevance(res, spec)            # 2
    _third_party(res, spec)          # 3
    _duplicate(res, spec)            # 4
    _list_name(res, spec)            # 5
    _keywords(res, spec)             # 6
    _description(res, spec)          # 7
    _suspend(res, spec, probes)      # 8
    _request_no(res, spec)           # 9
    _manager(res, spec)              # 10
    _link_api(res, spec)             # 11
    _pubc(res, spec)                 # 12
    _gateway(res, spec)              # 13
    _multicloud(res, spec)           # 14
    _nuri(res, spec)                 # 15
    _response_format(res, spec, probes)   # 16
    _operation_name(res, spec)       # 17
    _operation_info(res, spec)       # 18
    _call(res, spec, probes)         # 19
    _request_params(res, spec)       # 20
    _response_params(res, spec)      # 21
    _error_codes(res, spec)          # 22
    _privacy(res, spec, probes)      # 23


def _data_params(spec: ApiSpec):
    """봉투 항목을 뺀 실제 데이터 응답 항목.

    `items.seq` 처럼 계층이 펴진 이름은 마지막 마디로 본다. 봉투인지 아닌지는
    어느 계층에 있느냐가 아니라 이름이 무엇이냐로 갈린다.
    """
    return [p for p in spec.response_params if not name_equals(p.leaf, ENVELOPE)]


# ===== 1. 불량 데이터 개방 불가 ==========================================
def _bad_data(res: Result, spec: ApiSpec) -> None:
    data = _data_params(spec)

    logs = [p for p in data
            if looks_like(p.name, LOG_LIKE) or looks_like(p.ko_name, LOG_LIKE)]
    if logs:
        res.add(Finding(
            "1-가", IT[1], Level.REVIEW,
            f"로그성 데이터로 보이는 응답 항목이 {len(logs)}개 있습니다.",
            "DB 정보·IP 접속이력 등 대국민 활용성이 낮은 로그성 데이터는 개방할 수 "
            "없습니다. 실제로 로그성 항목이라면 제외하고 등록하세요.",
            locations=[p.label for p in logs[:20]],
            samples=[f"{p.name or p.ko_name}" for p in logs[:6]],
            count=len(logs)))

    if not spec.has_spec or not spec.response_params:
        return
    meaningful = [p for p in data if not name_equals(p.leaf, FILLER_PARAMS)]
    if not meaningful:
        res.add(Finding(
            "1-나", IT[1], Level.REJECT,
            "응답 파라메터에 실제 데이터 항목이 없습니다.",
            "목록과 관련된 데이터 개방 없이 seq·비고 같은 항목만 응답하면 개방할 수 "
            "없습니다. 목록명이 뜻하는 데이터를 응답 항목으로 추가하세요.",
            locations=[p.label for p in data[:20]],
            samples=[p.name or p.ko_name for p in data[:6]],
            count=len(data) or 1))


# ===== 2. 관련 없는 데이터 개방 불가 =====================================
def _relevance(res: Result, spec: ApiSpec) -> None:
    name, data = spec.list_name, _data_params(spec)
    if not name or not data:
        return
    # 주기·연도 표기는 5-나·4-나 가 따로 잡는다. 여기서 관련성 낱말로 삼으면
    # '연간' 이 데이터에 없다고 또 지적해 같은 말을 두 번 하게 된다.
    bare = RE_YEAR.sub("", RE_CYCLE.sub("", re.sub(r"조회\s*서비스", "", name)))
    core = [w for w in re.split(r"[_\s()]+", bare)
            if len(w) >= 2 and w != spec.org_name]
    if not core:
        return
    haystack = " ".join(f"{p.name} {p.ko_name} {p.desc}" for p in data)
    hit = [w for w in core if w in haystack]
    if not hit:
        res.add(Finding(
            "2-가", IT[2], Level.REVIEW,
            f"목록명의 낱말({', '.join(core[:4])})이 응답 항목 어디에도 나오지 않습니다.",
            "개방목록명과 관련성·부합성·일치성이 있는 데이터를 개방해야 합니다. "
            "목록명과 실제 응답 항목이 맞는지 확인하세요. 관련 없다고 판단되면 "
            "개방이 불가능합니다.",
            samples=[name]))


# ===== 3. 타기관 데이터 개방 =============================================
def _third_party(res: Result, spec: ApiSpec) -> None:
    if is_truthy(spec.meta.get("타기관데이터포함")):
        res.add(Finding(
            "3-가", IT[3], Level.ACTION,
            "타기관 데이터가 포함된 것으로 표시되어 있습니다.",
            "해당 기관의 동의를 얻은 공문을 포함한 증빙자료를 data@nia.or.kr 로 제출하고, "
            "공공데이터활용지원센터 검토 후 승인받아야 개방할 수 있습니다."))
    blob = f"{spec.list_name} {norm(spec.meta.get('설명'))}"
    if "뉴스" in blob:
        res.add(Finding(
            "3-나", IT[3], Level.REVIEW,
            "뉴스데이터로 보입니다.",
            "뉴스데이터는 기관에서 직접 가공하여 등록한 데이터만 개방이 승인됩니다."))


# ===== 4. 중복 등록 제외 =================================================
def _duplicate(res: Result, spec: ApiSpec) -> None:
    if not is_truthy(spec.meta.get("중복확인")):
        res.add(Finding(
            "4-가", IT[4], Level.REVIEW,
            "동일한 데이터명이 이미 등록되어 있는지 확인이 필요합니다.",
            "현행화된 중복 데이터명은 목록 제외 또는 삭제 요청을 접수해야 합니다. "
            "공문 위치: 정보공유 > 공지사항조회 > [검색어]별지 > "
            "[서식5] 공공데이터 목록 제외 요청서"))

    name = spec.list_name
    years = RE_YEAR.findall(name) if name else []
    if years:
        res.add(Finding(
            "4-나", IT[4], Level.REJECT,
            f"목록명에 연도 표기가 있습니다: {', '.join(years[:3])}",
            "동일한 파라메터 형태를 가진 데이터를 연도별로 분리해 개방하는 것은 "
            "허용되지 않습니다. 연도는 요청 파라메터로 받고 목록은 하나로 "
            "등록하세요.", samples=[name], fix_key=FX_LIST_CYCLE))


# ===== 5. 목록명 오류 ====================================================
def _list_name(res: Result, spec: ApiSpec) -> None:
    name = spec.list_name
    if not name:
        res.add(Finding(
            "5-다", IT[5], Level.REVIEW,
            "목록명이 입력되지 않아 5번 항목을 검토하지 못했습니다.",
            "등록하려는 목록명을 입력하면 특수문자·주기 표시·명명 규칙을 함께 "
            "검토합니다."))
        return

    bad = sorted(set(RE_LIST_BAD.findall(name)))
    if bad:
        res.add(Finding(
            "5-가", IT[5], Level.REJECT,
            f"목록명에 허용되지 않는 특수문자가 있습니다: {' '.join(bad)}",
            "목록명에는 _(언더바)와 ()(괄호)만 쓸 수 있습니다. 한글·영문·숫자는 "
            "허용됩니다.", locations=["목록명"], samples=[name],
            fix_key=FX_LIST_SPECIAL))

    cycles = RE_CYCLE.findall(name)
    if cycles:
        res.add(Finding(
            "5-나", IT[5], Level.REJECT,
            f"목록명에 업데이트 주기 표시가 있습니다: {', '.join(sorted(set(cycles))[:3])}",
            "목록명에는 업데이트 주기를 표시할 수 없습니다. "
            "예: 공공데이터_개방현황(연간) → 공공데이터_개방현황",
            locations=["목록명"], samples=[name], fix_key=FX_LIST_CYCLE))

    if "_" not in name:
        res.add(Finding(
            "5-다", IT[5], Level.REVIEW,
            "목록명이 기관명_데이터명 형태가 아닌 것으로 보입니다.",
            "기관명과 직관적인 데이터 명칭을 조합하세요. "
            "예: 공공데이터활용지원센터_자전거보관소현황 조회 서비스 "
            "(기관명은 등록 시 자동 기재되므로 입력하지 않아도 됩니다.)",
            locations=["목록명"], samples=[name]))

    if not re.search(r"조회\s*서비스", name):
        res.add(Finding(
            "5-다", IT[5], Level.REVIEW,
            "목록명이 'OOO 조회 서비스' 형태가 아닙니다.",
            "API는 서비스이므로 목록명을 'OOO 조회 서비스'로 기재하도록 권장합니다.",
            locations=["목록명"], samples=[name]))


# ===== 6. 키워드 오류 ====================================================
def _keywords(res: Result, spec: ApiSpec) -> None:
    raw = norm(spec.meta.get("키워드"))
    if not raw:
        return
    kws = [k.strip() for k in re.split(r"[,;\n]+", raw) if k.strip()]

    if not 3 <= len(kws) <= 8:
        res.add(Finding(
            "6-나", IT[6], Level.REJECT,
            f"키워드가 {len(kws)}개입니다.",
            "공공데이터포털 목록에서 검색될 수 있는 관련 키워드를 3~8개 작성하세요.",
            locations=["키워드"], samples=kws[:8]))

    norm_map: Dict[str, List[str]] = {}
    for k in kws:
        norm_map.setdefault(re.sub(r"\s+", "", k), []).append(k)
    dups = [v for v in norm_map.values() if len(v) > 1]
    if dups:
        res.add(Finding(
            "6-다", IT[6], Level.REJECT,
            "띄어쓰기만 다른 동일 키워드가 있습니다.",
            "중복 키워드를 제거하세요. 예: '자전거 주차장 데이터'와 "
            "'자전거주차장데이터'는 동일 키워드로 봅니다.",
            locations=["키워드"], samples=[" / ".join(d) for d in dups],
            fix_key=FX_KW_DUP))

    org, name = spec.org_name, spec.list_name
    overlap = [k for k in kws if (org and k == org) or (name and k == name)]
    if overlap:
        res.add(Finding(
            "6-가", IT[6], Level.ACTION,
            f"공공데이터명·기관명과 동일한 키워드가 있습니다: {', '.join(overlap[:5])}",
            "동일한 공공데이터명·기관명은 키워드에서 제외하고, 활용자가 검색할 만한 "
            "연관 키워드를 넣으세요.", locations=["키워드"], samples=overlap[:8]))

    special = [k for k in kws if re.search(r"[^가-힣A-Za-z0-9 ]", k)]
    if special:
        res.add(Finding(
            "6-가", IT[6], Level.ACTION,
            f"키워드에 특수문자가 있습니다: {', '.join(special[:5])}",
            "키워드에서 특수문자를 제거하세요.",
            locations=["키워드"], samples=special[:8], fix_key=FX_KW_SPECIAL))


# ===== 7. 데이터 설명 부족 ===============================================
def _description(res: Result, spec: ApiSpec) -> None:
    desc = norm(spec.meta.get("설명"))
    if not desc:
        res.add(Finding(
            "7-가", IT[7], Level.REJECT,
            "데이터 설명이 입력되지 않았습니다.",
            "생성·수집 목적과 활용성 측면에서 상세히 기재하세요. 한글·영문·숫자로 "
            "50자 이상이어야 합니다.", locations=["설명"]))
        return

    length = len(re.sub(r"\s", "", desc))
    if length < 50:
        res.add(Finding(
            "7-가", IT[7], Level.REJECT,
            f"설명이 공백 제외 {length}자입니다.",
            "생성·수집 목적과 활용성 측면에서 데이터 설명을 상세히 기재하세요. "
            "한글·영문·숫자로 50자 이상이어야 합니다.", locations=["설명"]))

    if re.search(r"\s{2,}", desc):
        res.add(Finding(
            "7-가", IT[7], Level.ACTION,
            "설명에 연속된 띄어쓰기가 있습니다.",
            "여러 번의 띄어쓰기는 금지됩니다. 분량을 채우기 위한 반복은 반려 대상입니다.",
            locations=["설명"], fix_key=FX_DESC_SPACE))

    words = [w for w in re.split(r"\s+", desc) if len(w) >= 3]
    rep = {w: words.count(w) for w in set(words) if words.count(w) >= 4}
    if rep:
        res.add(Finding(
            "7-가", IT[7], Level.ACTION,
            "같은 단어가 반복 사용되었습니다: "
            + ", ".join(f"{k}({v}회)" for k, v in list(rep.items())[:4]),
            "동일 단어 반복 없이 데이터 내용을 구체적으로 설명하세요.",
            locations=["설명"]))

    if RE_YEAR.search(desc):
        res.add(Finding(
            "7-가", IT[7], Level.REVIEW,
            "설명에 연도가 기재되어 있습니다.",
            "개방하려는 공공데이터의 내용과 연도가 설명과 일치하는지 확인하세요.",
            locations=["설명"]))


# ===== 8. API 일시정지 및 폐기(제외) 대상 =================================
def _suspend(res: Result, spec: ApiSpec, probes: Sequence[ProbeResult]) -> None:
    slow = [p for p in probes if p.ok and p.slow]
    if slow:
        res.add(Finding(
            "8-나", IT[8], Level.REJECT,
            f"응답이 {SLOW_LIMIT:.0f}초를 넘긴 오퍼레이션이 {len(slow)}개 있습니다.",
            "수집 데이터량 과다누적 등으로 응답속도가 5초 이상이 되면 "
            "공공데이터활용지원센터에서 API 를 일시정지할 수 있습니다. "
            "개방 기관에서 해결책을 마련해야 합니다.",
            locations=[f"{p.called} · {p.elapsed:.1f}초" for p in slow[:10]],
            count=len(slow)))

    if is_truthy(spec.meta.get("일시정지요청")):
        res.add(Finding(
            "8-다", IT[8], Level.REVIEW,
            "API 일시정지를 요청하는 경우 공문 확인이 필요합니다.",
            "일시정지 API 목록명 · 일시정지 기간(YYYY-MM-DD~YYYY-MM-DD) · 일시정지 "
            "사유가 포함된 공문을 일시정지 개시일 최소 2주 전까지 공공데이터활용"
            "지원센터에서 확인해야 승인됩니다."))


# ===== 9. 제공신청 필수사항 ==============================================
def _request_no(res: Result, spec: ApiSpec) -> None:
    applied = is_truthy(spec.meta.get("제공신청여부"))
    number = norm(spec.meta.get("제공번호"))
    if applied and not number:
        res.add(Finding(
            "9-가", IT[9], Level.REJECT,
            "제공신청 '예'를 선택했으나 제공번호가 없습니다.",
            "제공신청을 통한 데이터 개방 시 제공번호 입력이 필수입니다.",
            locations=["제공번호"]))


# ===== 10. 담당자 지정 ===================================================
def _manager(res: Result, spec: ApiSpec) -> None:
    sub = norm(spec.meta.get("부담당자"))
    if not sub:
        res.add(Finding(
            "10-가", IT[10], Level.ACTION,
            "부담당자가 지정되지 않았습니다.",
            "오류 등이 발생할 때 즉각적으로 연락할 수 있도록 부담당자를 지정해야 합니다.",
            locations=["부담당자"]))

    tel = norm(spec.meta.get("담당자연락처"))
    if not tel:
        res.add(Finding(
            "10-나", IT[10], Level.ACTION,
            "담당자 연락처가 입력되지 않았습니다.",
            "제공기관에서 활용자 민원을 실제 응대할 수 있는 번호로 반드시 현행화해야 "
            "합니다.", locations=["담당자연락처"]))
        return

    digits = re.sub(r"\D", "", tel)
    if RE_PHONE_OK.match(tel):
        return
    if RE_PHONE_DIGITS.match(digits):
        res.add(Finding(
            "10-나", IT[10], Level.ACTION,
            f"담당자 연락처 표기가 기준 형태가 아닙니다: {tel}",
            "지역번호-국번-번호 형태로 적으세요. 예: 0212345678 → 02-1234-5678",
            locations=["담당자연락처"], samples=[tel], fix_key=FX_PHONE))
    else:
        res.add(Finding(
            "10-나", IT[10], Level.ACTION,
            f"담당자 연락처를 전화번호로 읽을 수 없습니다: {tel}",
            "활용자 민원을 실제 응대할 수 있는 번호를 현행화해 입력하세요.",
            locations=["담당자연락처"], samples=[tel]))


# ===== 11. 링크형태 API 등록 시 URL 점검 ==================================
def _link_api(res: Result, spec: ApiSpec) -> None:
    link = norm(spec.meta.get("링크URL"))
    if spec.reg_type != REG_LINK and not link:
        return

    if spec.reg_type == REG_LINK and not link:
        res.add(Finding(
            "11-가", IT[11], Level.REJECT,
            "링크형태로 등록하는데 링크 URL 이 입력되지 않았습니다.",
            "해당 API 정보를 바로 확인할 수 있는 페이지 주소를 입력하세요.",
            locations=["링크URL"]))
        return

    p = parse_url(link)
    if not p.ok:
        res.add(Finding(
            "11-가", IT[11], Level.REJECT,
            f"링크 URL 을 읽을 수 없습니다: {link}",
            "http:// 또는 https:// 로 시작하는 전체 주소를 입력하세요.",
            locations=["링크URL"], samples=[link]))
        return

    if not p.segments:
        res.add(Finding(
            "11-나", IT[11], Level.REJECT,
            "링크 URL 이 사이트 첫 화면 주소로 보입니다.",
            "추가 검색·화면 이동·회원 로그인 등의 제한 없이 해당 API 정보"
            "(요청주소·요청 파라메터·응답 파라메터)를 바로 확인할 수 있는 "
            "상세페이지 주소여야 합니다.",
            locations=["링크URL"], samples=[link]))

    others = [u for u in spec.urls if u and u != link]
    same = [u for u in others if u.rstrip("/") == link.rstrip("/")]
    if same:
        res.add(Finding(
            "11-나", IT[11], Level.REJECT,
            "링크 URL 이 다른 등록 URL 과 같습니다.",
            "기관의 모든 API 페이지가 같은 주소를 사용하면 안 됩니다. "
            "API 마다 해당 정보를 확인할 수 있는 별도 페이지를 연결하세요.",
            locations=["링크URL"], samples=[link]))

    res.add(Finding(
        "11-다", IT[11], Level.REVIEW,
        "링크 페이지가 목록명과 일치하는 API 인지 확인이 필요합니다.",
        "목록명과 일치하는 API 인 경우에만 승인됩니다. 링크 URL 페이지 안에 목록과 "
        "관련 없는 API 내용이 노출되면 반려됩니다.",
        locations=["링크URL"], samples=[link]))


# ===== 12. PUBC 등록 검토사항 ============================================
def _pubc(res: Result, spec: ApiSpec) -> None:
    if spec.reg_type and spec.reg_type != REG_PUBC:
        return

    if not spec.has_spec:
        res.add(Finding(
            "12-가", IT[12], Level.REJECT,
            "기술문서를 읽지 못했습니다.",
            "기술문서를 첨부하고 apis.data@nia.or.kr 로 검토를 요청해야 합니다. "
            "미검토 시 반려됩니다. 이 프로그램에는 Swagger/OpenAPI JSON 또는 "
            "오퍼레이션 명세표(xlsx · csv)를 올리면 함께 검토합니다."))
    elif not is_truthy(spec.meta.get("기술문서검토")):
        res.add(Finding(
            "12-가", IT[12], Level.REVIEW,
            "기술문서 검토 요청 여부가 확인되지 않았습니다.",
            "기술문서 미검토 시 반려됩니다. 검토 E-mail: apis.data@nia.or.kr"))

    if not norm(spec.meta.get("TESTKEY")):
        res.add(Finding(
            "12-다", IT[12], Level.REJECT,
            "TEST KEY 가 입력되지 않았습니다.",
            "지원센터 호출 테스트를 위해 TEST KEY 입력이 필요합니다.",
            locations=["TESTKEY"]))

    _spec_vs_form(res, spec)


def _spec_vs_form(res: Result, spec: ApiSpec) -> None:
    """12-나 기술문서 ↔ 목록등록관리시스템 등록내용 대조."""
    if not spec.has_spec:
        return
    gaps: List[str] = []

    declared_url, spec_urls = spec.service_url, [o.url for o in spec.operations if o.url]
    if declared_url and spec_urls:
        base = declared_url.split("?")[0].rstrip("/").lower()
        if not any(base in u.lower() or u.split("?")[0].rstrip("/").lower() in base
                   for u in spec_urls):
            gaps.append(f"서비스 URL — 등록 '{declared_url}' / 기술문서 '{spec_urls[0]}'")

    d_fmt, s_fmt = spec.declared_formats(), spec.formats
    if d_fmt and s_fmt and sorted(d_fmt) != sorted(s_fmt):
        gaps.append(f"응답 포맷 — 등록 '{'+'.join(d_fmt)}' / 기술문서 '{'+'.join(s_fmt)}'")

    d_method = norm(spec.meta.get("전송방식")).upper()
    s_methods = sorted({o.method for o in spec.operations if o.method})
    if d_method and s_methods and d_method not in s_methods:
        gaps.append(f"전송방식 — 등록 '{d_method}' / 기술문서 '{', '.join(s_methods)}'")

    api_en = spec.api_name_en
    if api_en and spec_urls and not any(api_en.lower() in u.lower() for u in spec_urls):
        gaps.append(f"API명(영문) — 등록 '{api_en}' 이 기술문서 URL 에 없습니다")

    if gaps:
        res.add(Finding(
            "12-나", IT[12], Level.REJECT,
            f"기술문서와 등록 내용이 다른 항목이 {len(gaps)}개 있습니다.",
            "기술문서와 목록등록관리시스템에 등록된 내용이 상이하면 반려됩니다. "
            "둘 중 맞는 쪽으로 통일하세요.",
            locations=gaps[:10], samples=gaps[:4], count=len(gaps)))


# ===== 13. GW 등록 절차준수 ==============================================
def _gateway(res: Result, spec: ApiSpec) -> None:
    if spec.reg_type != REG_GW:
        return

    if not is_truthy(spec.meta.get("인증모듈적용")):
        res.add(Finding(
            "13-나", IT[13], Level.REJECT,
            "인증모듈 적용 여부가 '예'가 아닙니다.",
            "GW 등록은 인증모듈을 적용해야 합니다. 미적용 시 반려됩니다.",
            locations=["인증모듈적용"]))

    methods = {o.method.upper() for o in spec.operations if o.method}
    declared = norm(spec.meta.get("전송방식")).upper()
    if declared:
        methods.add(declared)
    bad = sorted(m for m in methods if m and m != "GET")
    if bad:
        res.add(Finding(
            "13-다", IT[13], Level.REJECT,
            f"GET 이 아닌 전송방식이 있습니다: {', '.join(bad)}",
            "GW 로는 GET 방식만 등록할 수 있으며, POST 방식으로 등록하면 반려됩니다.",
            locations=[f"{o.title} · {o.method}" for o in spec.operations
                       if o.method and o.method.upper() != "GET"][:10] or ["전송방식"]))

    for url in spec.urls:
        p = parse_url(url)
        if not p.ok:
            continue
        if p.effective_port not in (80, 443):
            res.add(Finding(
                "13-라", IT[13], Level.REJECT,
                f"허용되지 않는 포트를 사용합니다: {p.effective_port}",
                "기관 endPoint 에서 사용할 수 있는 포트는 http 80, https 443 뿐입니다.",
                locations=[url], samples=[url]))


# ===== 14. 멀티클라우드 등록 절차준수 =====================================
def _multicloud(res: Result, spec: ApiSpec) -> None:
    if spec.reg_type != REG_CLOUD:
        return

    auto = ("servicekey", "authkey", "apikey", "pageno", "numofrows", "type",
            "datatype", "_type", "resulttype")
    blank = [p for p in spec.all_params
             if not p.desc and not name_equals(p.name, auto)]
    if blank:
        res.add(Finding(
            "14-다", IT[14], Level.REJECT,
            f"설명이 없는 변수가 {len(blank)}개 있습니다.",
            "models 에서 자동으로 입력되는 변수를 제외한 모든 변수에 설명을 "
            "기재해야 합니다. 미기재 시 반려됩니다.",
            locations=[p.label for p in blank[:20]],
            samples=[p.name or p.ko_name for p in blank[:6]], count=len(blank)))

    res.add(Finding(
        "14-나", IT[14], Level.REVIEW,
        "Example Value 의 호출 화면이 실제 호출과 같은지 확인이 필요합니다.",
        "(프록시 타입) API 명세서를 통하여 등록한 Example Value 상의 호출 화면이 "
        "실제 호출과 다르면 반려됩니다."))


# ===== 15. 제3자 권리포함 여부 및 공공누리 마크 ============================
def _nuri(res: Result, spec: ApiSpec) -> None:
    nuri = norm(spec.meta.get("공공누리유형"))
    if not nuri:
        res.add(Finding(
            "15-나", IT[15], Level.ACTION,
            "공공누리 유형이 선택되지 않았습니다.",
            "이용허락범위를 검토·재확인한 뒤 공공저작물에 체크하고 제1~4유형 중 "
            "해당 유형을 선택해야 합니다. 마크 없이 개방하면 이용자가 변형·상업적 "
            "이용을 하는 문제 소지가 있습니다.", locations=["공공누리유형"]))
    elif nuri not in NURI_TYPES:
        res.add(Finding(
            "15-나", IT[15], Level.ACTION,
            f"공공누리 유형 값이 확인되지 않습니다: {nuri}",
            "제1유형(출처표시), 제2유형(+상업적 이용금지), 제3유형(+변경금지), "
            "제4유형(+상업적 이용금지+변경금지) 중 하나를 선택하세요.",
            locations=["공공누리유형"]))

    if is_truthy(spec.meta.get("저작권포함")):
        res.add(Finding(
            "15-다", IT[15], Level.ACTION,
            "저작권이 있는 데이터로 표시되어 있습니다.",
            "'저작물 이용허락 동의서'를 첨부해야 합니다. 공문양식: 목록등록관리 > "
            "정보공유 > 공통 매뉴얼 조회 > [게시판번호 3160] 공공데이터 제공·관리 "
            "실무 매뉴얼 p87"))
        res.add(Finding(
            "15-라", IT[15], Level.REVIEW,
            "공공저작물이 포함된 경우 API 호출 시 저작 관련 내용이 표출되어야 합니다.",
            "응답에 공공데이터 저작 관련 내용(출처·이용조건)이 함께 나오는지 "
            "확인하세요."))


# ===== 16. 응답 포맷 검토사항 ============================================
def _response_format(res: Result, spec: ApiSpec, probes: Sequence[ProbeResult]) -> None:
    declared = spec.declared_formats()

    for p in probes:
        if not p.ok or not p.content_type:
            continue
        ct = p.content_type.lower()
        if not any(ok in ct for ok in OK_CONTENT_TYPE):
            res.add(Finding(
                "16-나", IT[16], Level.REJECT,
                f"응답 Content-Type 이 기준과 다릅니다: {p.content_type}",
                "End Point 에서 보내는 응답 헤더가 application/json;charset=utf-8 "
                "또는 application/xml 로 설정되어 있어야 합니다. XML·JSON 으로 "
                "보이더라도 Content-Type 이 text·html 이면 반려됩니다.",
                locations=[p.called], samples=[p.content_type]))
        elif "charset" not in ct and "json" in ct:
            res.add(Finding(
                "16-나", IT[16], Level.ACTION,
                f"응답 Content-Type 에 charset 이 없습니다: {p.content_type}",
                "application/json;charset=utf-8 형태로 설정하세요.",
                locations=[p.called], samples=[p.content_type]))

        if declared and p.body_kind in ("json", "xml"):
            got = p.body_kind.upper()
            if got not in declared:
                res.add(Finding(
                    "16-가", IT[16], Level.REJECT,
                    f"안내한 포맷({'+'.join(declared)})과 다른 포맷({got})으로 "
                    "결과가 출력됩니다.",
                    "안내된·요청한 데이터 포맷과 다른 포맷으로 결과가 출력되면 "
                    "반려됩니다.", locations=[p.called]))

        if p.body_kind == "html":
            res.add(Finding(
                "16-가", IT[16], Level.REJECT,
                "응답이 HTML 로 출력됩니다.",
                "XML 또는 JSON 으로 응답해야 합니다. 오류 안내 페이지가 그대로 "
                "나오는 것은 아닌지 확인하세요.", locations=[p.called]))

    if len(declared) >= 2:
        res.add(Finding(
            "16-다", IT[16], Level.REVIEW,
            "JSON 과 XML 을 함께 제공합니다.",
            "두 포맷의 응답 결과 구조 형태가 동일하지 않으면 반려됩니다. "
            "항목 구성과 계층이 같은지 대조하세요."))

    binary = [p for p in probes if p.body_kind == "binary"]
    if binary or norm(spec.meta.get("응답형태")) in ("이미지", "엑셀", "파일"):
        res.add(Finding(
            "16-라", IT[16], Level.ACTION,
            "XML·JSON 이 아닌 이미지·엑셀 형태로 응답하는 API 로 보입니다.",
            "이미지 송출에 따른 서버 과부하로 인해 REST 형식이 아닌 LINK 형식으로만 "
            "등록할 수 있습니다.",
            locations=[p.called for p in binary[:5]] or ["응답형태"]))


# ===== 17. 오퍼레이션명 오류 =============================================
def _operation_name(res: Result, spec: ApiSpec) -> None:
    if not spec.operations:
        return
    name = spec.list_name

    same = [o for o in spec.operations
            if name and (o.name_ko.strip() == name.strip()
                         or o.name_en.strip().lower() == name.strip().lower())]
    if same:
        res.add(Finding(
            "17-가", IT[17], Level.REJECT,
            f"목록명과 같은 오퍼레이션명이 {len(same)}개 있습니다.",
            "오퍼레이션명은 목록명과 동일한 명칭을 사용할 수 없습니다.",
            locations=[o.title for o in same[:10]], samples=[name],
            count=len(same)))

    no_ko = [o for o in spec.operations if not has_hangul(o.name_ko)]
    if no_ko:
        res.add(Finding(
            "17-나", IT[17], Level.REJECT,
            f"국문 오퍼레이션명이 없는 오퍼레이션이 {len(no_ko)}개 있습니다.",
            "오퍼레이션명은 국문으로 기재해야 합니다. 영문 오퍼레이션명과 별개로 "
            "국문명을 적으세요.",
            locations=[o.name_en or o.url or "(이름없음)" for o in no_ko[:10]],
            count=len(no_ko)))


# ===== 18. 오퍼레이션 정보 오기재 ========================================
def _operation_info(res: Result, spec: ApiSpec) -> None:
    _op_url(res, spec)
    _op_params(res, spec)


def _op_url(res: Result, spec: ApiSpec) -> None:
    api_en, org_code = spec.api_name_en, spec.org_code

    with_query = [u for u in spec.urls if "?" in u]
    if with_query:
        res.add(Finding(
            "18-가", IT[18], Level.REJECT,
            f"URL 에 요청 파라메터가 함께 적혀 있습니다({len(with_query)}건).",
            "URL 에는 요청 파라메터를 함께 기재하지 않습니다. "
            "예: .../getList?serviceKey=... → .../getList",
            locations=with_query[:10], samples=with_query[:3],
            count=len(with_query), fix_key=FX_URL_QUERY))

    for url in spec.urls:
        p = parse_url(url)
        if not p.ok:
            res.add(Finding(
                "18-나", IT[18], Level.REJECT,
                f"URL 을 읽을 수 없습니다: {url}",
                "URL 규칙: apis.data.go.kr/기관코드/API명(영문)/오퍼레이션명(영문)",
                locations=[url], samples=[url]))
            continue

        if not p.is_portal:
            res.add(Finding(
                "18-나", IT[18], Level.REVIEW,
                f"서비스 URL 호스트가 apis.data.go.kr 이 아닙니다: {p.host}",
                "외부노출 URL 은 apis.data.go.kr/기관코드/API명(영문)/오퍼레이션명(영문) "
                "규칙을 따라야 합니다. 기관 endPoint 주소라면 외부노출 URL 을 따로 "
                "확인하세요.", locations=[url], samples=[url]))
            continue

        if len(p.segments) < 3:
            res.add(Finding(
                "18-나", IT[18], Level.REJECT,
                f"URL 이 규칙에 맞지 않습니다: /{'/'.join(p.segments)}",
                "URL 규칙: apis.data.go.kr/기관코드/API명(영문)/오퍼레이션명(영문). "
                "세 단계가 모두 있어야 합니다.", locations=[url], samples=[url]))
            continue

        code, api_seg, op_seg = p.segments[0], p.segments[1], p.segments[-1]

        if org_code and code.lower() != org_code.lower():
            res.add(Finding(
                "18-나", IT[18], Level.ACTION,
                f"URL 의 기관코드('{code}')가 등록한 기관코드('{org_code}')와 다릅니다.",
                "URL 규칙의 첫 단계는 기관코드입니다.",
                locations=[url], samples=[url]))

        if api_seg.lower() == op_seg.lower():
            res.add(Finding(
                "18-나", IT[18], Level.REJECT,
                f"API명(영문)과 오퍼레이션명(영문)이 같습니다: {api_seg}",
                "API명(영문)과 오퍼레이션명(영문)은 동일하면 안 됩니다. "
                "(목록명과 오퍼레이션명의 영문 번역이 아닙니다.)",
                locations=[url], samples=[url]))

        if api_en and api_seg.lower() != api_en.lower():
            res.add(Finding(
                "18-나", IT[18], Level.ACTION,
                f"URL 의 API명('{api_seg}')이 등록한 API명(영문)('{api_en}')과 다릅니다.",
                "등록 정보와 URL 의 API명(영문)을 일치시키세요.",
                locations=[url], samples=[url]))

        vague = [s for s in (api_seg, op_seg) if s.lower() in VAGUE_WORDS]
        if vague:
            res.add(Finding(
                "18-나", IT[18], Level.REJECT,
                f"포괄적인 단어를 단독으로 사용했습니다: {', '.join(vague)}",
                "info, list 등 포괄적인 단어는 단독으로 사용할 수 없습니다. "
                "무엇을 조회하는지 드러나는 이름을 쓰세요.",
                locations=[url], samples=[url]))


def _op_params(res: Result, spec: ApiSpec) -> None:
    params = spec.all_params
    if not params:
        return

    ko_named = [p for p in params if has_hangul(p.name)]
    if ko_named:
        res.add(Finding(
            "18-다", IT[18], Level.REJECT,
            f"항목명(영문)에 한글이 들어간 항목이 {len(ko_named)}개 있습니다.",
            "항목명(영문)은 한글로 표기할 수 없습니다. 국문 항목명은 "
            "항목명(국문) 칸에 적으세요.",
            locations=[p.label for p in ko_named[:20]],
            samples=[p.name for p in ko_named[:6]], count=len(ko_named)))

    no_desc = [p for p in params if not p.desc]
    if no_desc:
        res.add(Finding(
            "18-라", IT[18], Level.REJECT,
            f"설명이 없는 항목이 {len(no_desc)}개 있습니다.",
            "항목에 대한 설명은 반드시 기재해야 하며, 설명을 참고해 호출할 수 있도록 "
            "입력형식까지 자세히 기재해야 합니다.",
            locations=[p.label for p in no_desc[:20]],
            samples=[p.name or p.ko_name for p in no_desc[:6]], count=len(no_desc)))

    unit_missing = [p for p in params
                    if (RE_UNIT_SYMBOL.search(p.ko_name) or RE_UNIT_SYMBOL.search(p.name))
                    and p.desc and not RE_UNIT_IN_DESC.search(p.desc)]
    if unit_missing:
        res.add(Finding(
            "18-라", IT[18], Level.ACTION,
            f"단위가 있는데 설명에 단위를 적지 않은 항목이 {len(unit_missing)}개 있습니다.",
            "단위(㎟, ㎠ 등)가 존재할 경우 반드시 설명에 기재해야 합니다.",
            locations=[p.label for p in unit_missing[:20]],
            samples=[f"{p.name or p.ko_name}: {p.desc[:30]}" for p in unit_missing[:4]],
            count=len(unit_missing)))

    coded = [p for p in params
             if RE_CODE_PARAM.search(p.name or p.ko_name or "")
             and not re.search(r"(코드|code)", p.desc or "", re.I)]
    if coded:
        res.add(Finding(
            "18-마", IT[18], Level.REVIEW,
            f"코드를 쓰는 것으로 보이는 항목이 {len(coded)}개 있습니다.",
            "코드가 사용될 경우 ① 항목설명에 코드 기재 ② 코드 확인 방법 기재"
            "(로그인·설문조사 절차가 필요한 링크는 불가) ③ 참고 문서에 코드표 첨부 "
            "중 한 가지 방식으로 제공해야 합니다. 응답 파라메터로 코드명이 함께 "
            "출력되면 예외입니다.",
            locations=[p.label for p in coded[:20]],
            samples=[p.name or p.ko_name for p in coded[:6]], count=len(coded)))

    req = [p for p in spec.request_params if not p.sample]
    if req:
        res.add(Finding(
            "18-바", IT[18], Level.ACTION,
            f"샘플이 없는 요청 항목이 {len(req)}개 있습니다.",
            "기재된 샘플로 호출했을 때 결과가 나와야 합니다. 요청 항목마다 실제 "
            "동작하는 샘플값을 적으세요.",
            locations=[p.label for p in req[:20]],
            samples=[p.name or p.ko_name for p in req[:6]], count=len(req)))

    if spec.reg_type == REG_GW:
        bad_type = [p for p in params if p.type and not name_equals(p.type, ALLOWED_TYPES)]
        if bad_type:
            res.add(Finding(
                "18-사", IT[18], Level.REJECT,
                f"항목유형이 기준 형식과 다른 항목이 {len(bad_type)}개 있습니다.",
                "(GW) 항목유형은 문자열·숫자·정수 등 정해진 형식으로 적어야 하며 "
                "오기재 시 반려됩니다.",
                locations=[f"{p.label} · {p.type}" for p in bad_type[:20]],
                samples=[f"{p.name}: {p.type}" for p in bad_type[:6]],
                count=len(bad_type)))
        res.add(Finding(
            "18-아", IT[18], Level.REVIEW,
            "SWAGGER 문서 미리보기의 Example Value 를 확인하세요.",
            "(GW) Example Value 의 결과 구조가 실제 호출과 다를 경우 반려됩니다."))


# ===== 19. 호출 오류 =====================================================
def _call(res: Result, spec: ApiSpec, probes: Sequence[ProbeResult]) -> None:
    if not probes:
        res.add(Finding(
            "19-가", IT[19], Level.REVIEW,
            "endPoint 실호출 검사를 하지 않았습니다.",
            "화면에서 'endPoint 실제 호출' 을 켜고 인증키를 넣으면 호출 오류·상태코드·"
            "응답 지연·응답 항목명 일치를 자동으로 검사합니다. 사내망에서 외부 호출이 "
            "막혀 있으면 기재한 URL 로 직접 호출해 결과를 확인하세요."))
        return

    failed = [p for p in probes if not p.ok]
    if failed:
        res.add(Finding(
            "19-가", IT[19], Level.REJECT,
            f"호출에 실패한 URL 이 {len(failed)}개 있습니다.",
            "기재한 endPoint URL 로 호출했을 때 에러가 나오면 승인이 불가합니다.",
            locations=[f"{p.called} · {p.error}" for p in failed[:10]],
            samples=[p.error for p in failed[:4]], count=len(failed)))

    bad_status = [p for p in probes if p.ok and p.status and p.status != 200]
    if bad_status:
        res.add(Finding(
            "19-나", IT[19], Level.REJECT,
            f"HTTP 상태코드가 200 이 아닌 URL 이 {len(bad_status)}개 있습니다.",
            "endPoint URL 호출 시 http 상태코드가 200 외 다른 값이면 승인이 "
            "불가합니다(인증모듈에 대한 에러는 제외).",
            locations=[f"{p.called} · HTTP {p.status}" for p in bad_status[:10]],
            count=len(bad_status)))

    slow = [p for p in probes if p.ok and p.slow]
    if slow:
        res.add(Finding(
            "19-마", IT[19], Level.REJECT,
            f"응답이 {SLOW_LIMIT:.0f}초 이상 지연된 URL 이 {len(slow)}개 있습니다.",
            "응답호출이 5초 이상 지연되면 반려되고, 응답속도가 느릴 경우 승인이 "
            "불가합니다. 개방 후에도 지연되면 API 일시정지 또는 재정비를 요청할 수 "
            "있습니다.",
            locations=[f"{p.called} · {p.elapsed:.1f}초" for p in slow[:10]],
            count=len(slow)))

    _declared_vs_actual(res, spec, probes)


def _declared_vs_actual(res: Result, spec: ApiSpec,
                        probes: Sequence[ProbeResult]) -> None:
    """19-다 기재한 항목명 ↔ 실제 응답 항목명 대조."""
    actual: List[str] = []
    for p in probes:
        actual.extend(p.fields)
    if not actual or not spec.response_params:
        return

    lower = {a.lower() for a in actual}
    missing = [p for p in spec.response_params
               if p.name and p.name.split(".")[-1].lower() not in lower]
    if missing:
        res.add(Finding(
            "19-다", IT[19], Level.REJECT,
            f"기재한 응답 항목 중 실제 응답에 없는 항목이 {len(missing)}개 있습니다.",
            "기재하신 항목명과 실제 응답항목명이 다르면 반려됩니다"
            "(대소문자·특수문자 포함). 기술문서와 실제 응답을 맞추세요.",
            locations=[p.label for p in missing[:20]],
            samples=[p.name for p in missing[:6]], count=len(missing)))

    declared = {p.name.split(".")[-1].lower() for p in spec.response_params if p.name}
    extra = sorted({a for a in actual if a.lower() not in declared})
    if extra:
        res.add(Finding(
            "19-다", IT[19], Level.ACTION,
            f"기술문서에 없는 응답 항목이 실제 응답에 {len(extra)}개 있습니다.",
            "실제 응답에만 있는 항목은 기술문서에도 기재해야 합니다.",
            samples=extra[:8], count=len(extra)))


# ===== 20. 요청 파라메터 설정 오류 ========================================
def _request_params(res: Result, spec: ApiSpec) -> None:
    if not spec.operations:
        return
    names = [p.name or p.ko_name for p in spec.request_params]
    declared = spec.declared_formats()
    multi = len(declared) >= 2 or len(spec.formats) >= 2

    if multi and not any(name_equals(n, FORMAT_PARAMS) for n in names):
        res.add(Finding(
            "20-가", IT[20], Level.REJECT,
            "여러 데이터 포맷을 제공하는데 포맷 변환 파라메터가 없습니다.",
            "JSON·XML 을 함께 제공하려면 요청 파라메터에 포맷 변환 항목"
            "(예: dataType, _type, resultType)을 두어야 합니다.",
            samples=names[:8] or ["(요청 파라메터 없음)"]))

    page = [any(name_equals(n, group) for n in names) for group in PAGING_HINTS]
    if not all(page):
        missing = []
        if not page[0]:
            missing.append("페이지 번호(pageNo)")
        if not page[1]:
            missing.append("한 페이지 결과 수(numOfRows)")
        res.add(Finding(
            "20-나", IT[20], Level.REJECT,
            f"페이징 처리 파라메터가 없습니다: {' · '.join(missing)}",
            "다수의 데이터가 있을 경우 페이징 처리는 필수입니다. 요청 파라메터에 "
            "pageNo · numOfRows 를 추가하세요.",
            samples=names[:8] or ["(요청 파라메터 없음)"]))


# ===== 21. 응답 파라메터 설정오류 =========================================
def _response_params(res: Result, spec: ApiSpec) -> None:
    if not spec.operations:
        return
    names = [p.leaf for p in spec.response_params if p.leaf]

    missing = [need for need in REQUIRED_RESPONSE
               if not any(name_equals(n, (need,)) for n in names)]
    if missing:
        res.add(Finding(
            "21-가", IT[21], Level.REJECT,
            f"필수 응답 파라메터가 없습니다: {', '.join(missing)}",
            "resultCode(결과코드) · resultMsg(결과 메시지) · totalCount(전체 결과수)는 "
            "반드시 나와야 합니다.",
            samples=names[:10] or ["(응답 파라메터 없음)"], count=len(missing)))

    res.add(Finding(
        "21-나", IT[21], Level.REVIEW,
        "요청 파라메터 값에 따라 응답 파라메터가 바뀌지 않는지 확인하세요.",
        "요청 파라메터 값에 따라 응답파라메터들이 바뀌어서는 안 됩니다. "
        "조건을 달리해 호출했을 때 응답 항목 구성이 같은지 대조하세요."))


# ===== 22. 에러코드 ======================================================
def _error_codes(res: Result, spec: ApiSpec) -> None:
    is_gw = spec.reg_type in ("", REG_GW)

    if spec.reg_type == REG_PUBC and not spec.error_codes:
        res.add(Finding(
            "22-가", IT[22], Level.REVIEW,
            "기술문서에서 에러코드 표를 찾지 못했습니다.",
            "PUBC 의 경우 기술문서에 ① 에러코드 ② 에러메세지 및 설명을 "
            "기재해야 합니다."))
    if not spec.error_codes:
        return

    # 22번은 안내문상 'GW의 경우만 해당'이라 반려는 GW 로 등록할 때만 매긴다.
    # 다만 다른 유형이라도 기술문서에 포털 코드나 200 이 섞여 있으면 검토 단계에서
    # 지적받으므로, 등급만 낮춰 확인권장으로 남긴다.
    lv = Level.REJECT if is_gw else Level.REVIEW
    tailnote = ("" if is_gw else
                " (에러코드 반려 기준은 GW 등록에 적용되지만, 기술문서에 남아 있으면 "
                "검토 단계에서 지적될 수 있습니다.)")

    portal = [c for c in spec.error_codes if code_key(c.code) in PORTAL_ERROR_CODES]
    if portal:
        res.add(Finding(
            "22-나", IT[22], lv,
            f"포털이 출력하는 표준 에러코드를 기관 에러코드로 기재했습니다"
            f"({len(portal)}건).",
            "기관에서 설정한 에러코드만 기재해야 하며, 포털에서 출력하는 에러코드를 "
            "입력하면 반려됩니다. 해당 행을 지우세요." + tailnote,
            locations=[f"에러코드 {c.code} · {PORTAL_ERROR_CODES[code_key(c.code)]}"
                       for c in portal[:10]],
            samples=[c.code for c in portal[:6]], count=len(portal),
            fix_key=FX_ERR_PORTAL))

    ok200 = [c for c in spec.error_codes if code_key(c.code) == "200"]
    if ok200:
        res.add(Finding(
            "22-다", IT[22], lv,
            "에러코드에 200 이 기재되어 있습니다.",
            "에러코드 200 은 기재할 수 없습니다. 해당 행을 지우세요." + tailnote,
            locations=[f"에러코드 {c.code}" for c in ok200[:5]],
            count=len(ok200), fix_key=FX_ERR_200))


# ===== 23. 비공개 정보 포함, 비정형 데이터 등 주의 사항 =====================
def _privacy(res: Result, spec: ApiSpec, probes: Sequence[ProbeResult]) -> None:
    hits = [p for p in spec.all_params
            if looks_like(p.name, PRIVACY_LIKE) or looks_like(p.ko_name, PRIVACY_LIKE)]
    if hits:
        res.add(Finding(
            "23-나", IT[23], Level.ACTION,
            f"개인정보로 보이는 항목이 {len(hits)}개 있습니다.",
            "주민등록번호·휴대전화번호·이메일·개인 이름 등은 반드시 삭제하거나 "
            "비식별화해야 합니다. 다른 정보와 조합했을 때 개인이 식별 가능한 항목도 "
            "포함 대상입니다.",
            locations=[p.label for p in hits[:20]],
            samples=[p.name or p.ko_name for p in hits[:6]], count=len(hits)))

    unstructured = norm(spec.meta.get("비정형포함"))
    if is_truthy(unstructured):
        res.add(Finding(
            "23-가", IT[23], Level.REVIEW,
            "비정형(이미지·동영상·음성) 데이터가 포함되어 있습니다.",
            "개인정보 포함 여부를 사전 점검하고, 식별 가능한 정보는 블러·마스킹·음성 "
            "변조 등으로 비식별화한 뒤 등록하세요. 최종 등록 전 실무담당자가 문제 "
            "없음을 반드시 확인해야 합니다."))
        res.add(Finding(
            "23-바", IT[23], Level.REVIEW,
            "군부대·국가안보 관련 정보가 노출되지 않는지 확인하세요.",
            "shp(QGIS·ArcGIS) · sav(SPSS) 등 특정 프로그램으로 확인하는 파일을 "
            "등록하는 경우 해당 프로그램 사용법을 기재한 설명 파일을 첨부해야 "
            "합니다."))
