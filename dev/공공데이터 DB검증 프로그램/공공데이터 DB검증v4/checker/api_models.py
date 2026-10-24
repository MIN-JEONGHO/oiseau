# -*- coding: utf-8 -*-
"""OPEN API 명세 자료구조.

기술문서(Swagger/OpenAPI JSON)나 오퍼레이션 명세표(엑셀·CSV)를 읽어
이 구조로 정규화한 뒤 rules_api 가 검사한다. 판독 방식이 달라도 규칙은
같은 구조만 보게 하려는 것이다.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# 등록 유형 — 항목 12·13·14 는 유형에 따라 적용 여부가 갈린다
REG_PUBC = "PUBC"
REG_GW = "GW"
REG_CLOUD = "멀티클라우드"
REG_LINK = "링크"
REG_TYPES = (REG_PUBC, REG_GW, REG_CLOUD, REG_LINK)

REQUEST, RESPONSE = "request", "response"

#: 21-가 필수 응답 파라메터
REQUIRED_RESPONSE = ("resultCode", "resultMsg", "totalCount")

#: 20-나 페이징 파라메터 (하나씩 짝을 이룬다)
PAGING_HINTS = (("pageNo", "pageIndex", "page", "startPage", "pageNum"),
                ("numOfRows", "rowsPerPage", "pageSize", "perPage", "numOfRow"))

#: 20-가 데이터 포맷 변환 파라메터
FORMAT_PARAMS = ("type", "dataType", "_type", "resultType", "format", "responseType")

#: 18-나 단독으로 쓸 수 없는 포괄적 단어
VAGUE_WORDS = ("info", "list", "data", "service", "api", "get", "search",
               "select", "view", "detail", "item", "result")

#: 18-사 GW 항목유형으로 허용되는 값
ALLOWED_TYPES = ("문자열", "숫자", "정수", "실수", "불린", "날짜",
                 "string", "number", "integer", "int", "float", "double",
                 "boolean", "bool", "date", "datetime", "array", "object", "long")

#: 1-나 그 자체로는 데이터라 볼 수 없는 응답 항목 (이것만 있으면 개방 불가)
FILLER_PARAMS = ("seq", "rownum", "rn", "no", "num", "idx", "index", "id",
                 "비고", "순번", "일련번호", "번호", "기타", "etc", "remark", "note")

#: 1-가 로그성 데이터로 의심되는 항목
LOG_LIKE = ("ip", "ipaddr", "accesslog", "loginlog", "log", "접속이력", "접속로그",
            "로그인이력", "세션", "session", "dbname", "dbinfo", "tablename",
            "schema", "sysdate", "servername")

#: 23-나 개인정보로 의심되는 항목
PRIVACY_LIKE = ("주민등록번호", "주민번호", "jumin", "ssn", "residentno",
                "휴대전화", "휴대폰", "핸드폰", "mobile", "phone", "tel", "hp",
                "이메일", "email", "mail", "성명", "이름", "name", "생년월일",
                "birth", "주소", "addr", "계좌", "account", "카드번호")

#: 22-나 포털이 직접 출력하는 표준 에러코드 (기관이 자기 코드로 적으면 반려)
PORTAL_ERROR_CODES = {
    "1": "APPLICATION_ERROR", "4": "HTTP_ERROR",
    "12": "NO_OPENAPI_SERVICE_ERROR", "20": "SERVICE_ACCESS_DENIED_ERROR",
    "22": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "30": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "31": "DEADLINE_HAS_EXPIRED_ERROR", "32": "UNREGISTERED_IP_ERROR",
    "33": "UNSIGNED_CALL_ERROR", "99": "UNKNOWN_ERROR",
}

#: 16-나 허용되는 응답 Content-Type
OK_CONTENT_TYPE = ("application/json", "application/xml", "text/xml")

RE_HANGUL = re.compile(r"[가-힣]")
RE_UNIT_SYMBOL = re.compile(r"[㎟㎠㎡㎢㎥㎜㎝㎞㎏㎎㎖ℓ℃℉㎾㏊‰㎧㎿%]")
RE_PORTAL_HOST = re.compile(r"^apis?\.data\.go\.kr$", re.I)


def norm(v: Any) -> str:
    return "" if v is None else str(v).strip()


def is_truthy(v: Any) -> bool:
    return norm(v).lower() in ("예", "y", "yes", "true", "1", "적용", "완료", "on")


@dataclass
class ApiParam:
    """요청 또는 응답 파라메터 1개."""

    name: str = ""                      # 항목명(영문)
    ko_name: str = ""                   # 항목명(국문)
    desc: str = ""                      # 설명
    type: str = ""                      # 항목유형
    required: Optional[bool] = None     # 필수 여부 (모르면 None)
    sample: str = ""                    # 샘플데이터
    where: str = RESPONSE               # request | response
    op: str = ""                        # 소속 오퍼레이션명 (위치 표기용)

    @property
    def leaf(self) -> str:
        """중첩 응답을 편 이름(`items.seq`)에서 마지막 마디만.

        규격상 정해진 이름(resultCode·totalCount)이나 무의미 항목(seq)인지 볼 때는
        어느 계층에 있든 마지막 마디로 판단해야 한다.
        """
        return (self.name or self.ko_name).split(".")[-1]

    @property
    def label(self) -> str:
        side = "요청" if self.where == REQUEST else "응답"
        head = f"{self.op} · " if self.op else ""
        return f"{head}{side} · {self.name or self.ko_name or '(이름없음)'}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiOperation:
    """오퍼레이션 1개."""

    name_ko: str = ""
    name_en: str = ""
    url: str = ""                       # 서비스 URL / 외부노출 URL
    method: str = ""                    # GET / POST ...
    summary: str = ""
    content_types: List[str] = field(default_factory=list)
    request: List[ApiParam] = field(default_factory=list)
    response: List[ApiParam] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.name_ko or self.name_en or self.url or "(오퍼레이션)"

    @property
    def params(self) -> List[ApiParam]:
        return [*self.request, *self.response]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["title"] = self.title
        return d


@dataclass
class ApiErrorCode:
    code: str = ""
    message: str = ""
    desc: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiSpec:
    """검사 대상이 되는 API 등록 정보 한 벌.

    명세 파일에서 읽은 값과 화면에서 입력한 값이 함께 담긴다. 둘이 어긋나면
    12-나(기술문서 ↔ 등록내용 상이)로 잡아야 하므로, 화면 입력값은
    `declared_*` 로 따로 보관하고 명세 쪽 값을 덮어쓰지 않는다.
    """

    source_name: str = ""               # 명세 파일명 (없으면 빈 값)
    source_kind: str = "none"           # swagger | table | none
    title: str = ""                     # 명세에 적힌 서비스명
    base_url: str = ""                  # 명세에서 뽑은 기본 URL
    operations: List[ApiOperation] = field(default_factory=list)
    error_codes: List[ApiErrorCode] = field(default_factory=list)
    formats: List[str] = field(default_factory=list)     # json / xml
    notes: List[str] = field(default_factory=list)       # 판독 과정 안내
    parse_error: str = ""

    # 화면에서 입력한 등록 정보
    meta: Dict[str, str] = field(default_factory=dict)

    # ---- 등록 정보 접근자 ---------------------------------------------
    @property
    def list_name(self) -> str:
        return norm(self.meta.get("목록명"))

    @property
    def org_name(self) -> str:
        return norm(self.meta.get("기관명"))

    @property
    def org_code(self) -> str:
        return norm(self.meta.get("기관코드"))

    @property
    def api_name_en(self) -> str:
        return norm(self.meta.get("API명(영문)"))

    @property
    def reg_type(self) -> str:
        v = norm(self.meta.get("등록유형"))
        return v if v in REG_TYPES else ""

    @property
    def service_url(self) -> str:
        return norm(self.meta.get("서비스URL"))

    @property
    def urls(self) -> List[str]:
        """검사 대상 URL 전체 — 등록 정보의 서비스 URL + 오퍼레이션별 URL.

        base_url(Swagger 의 host+basePath)은 오퍼레이션 URL 의 앞토막일 뿐이라
        그 자체로는 URL 규칙(18-나)의 검사 대상이 아니다. 오퍼레이션을 하나도
        읽지 못했을 때만 최후 수단으로 넣는다.
        """
        candidates = [self.service_url, *[o.url for o in self.operations]]
        if not self.operations:
            candidates.append(self.base_url)
        out: List[str] = []
        for u in candidates:
            u = norm(u)
            if u and u not in out:
                out.append(u)
        return out

    @property
    def all_params(self) -> List[ApiParam]:
        return [p for o in self.operations for p in o.params]

    @property
    def response_params(self) -> List[ApiParam]:
        return [p for o in self.operations for p in o.response]

    @property
    def request_params(self) -> List[ApiParam]:
        return [p for o in self.operations for p in o.request]

    @property
    def has_spec(self) -> bool:
        return bool(self.operations or self.error_codes)

    def declared_formats(self) -> List[str]:
        """등록 정보에 적은 응답 포맷 (JSON / XML)."""
        raw = norm(self.meta.get("응답포맷")).upper()
        out = [f for f in ("JSON", "XML") if f in raw]
        return out

    def summary(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "reg_type": self.reg_type or "-",
            "operations": len(self.operations),
            "request_params": len(self.request_params),
            "response_params": len(self.response_params),
            "error_codes": len(self.error_codes),
            "formats": self.formats or self.declared_formats(),
            "notes": self.notes,
            "ops": [o.to_dict() for o in self.operations],
            "codes": [c.to_dict() for c in self.error_codes],
        }


# ---- URL 판별 ----------------------------------------------------------
@dataclass
class UrlParts:
    raw: str = ""
    ok: bool = False                 # 파싱 성공 여부
    scheme: str = ""
    host: str = ""
    port: Optional[int] = None
    segments: List[str] = field(default_factory=list)
    query: str = ""
    error: str = ""

    @property
    def is_portal(self) -> bool:
        return bool(RE_PORTAL_HOST.match(self.host or ""))

    @property
    def effective_port(self) -> int:
        if self.port:
            return self.port
        return 443 if self.scheme == "https" else 80


def parse_url(url: str) -> UrlParts:
    """등록 URL 을 뜯어본다. 13-라(포트)·18-가(요청파라메터)·18-나(URL 규칙) 공용."""
    raw = norm(url)
    p = UrlParts(raw=raw)
    if not raw:
        p.error = "빈 값"
        return p
    try:
        s = urlsplit(raw if "//" in raw else "//" + raw, scheme="http")
        p.scheme = (s.scheme or "").lower()
        p.host = (s.hostname or "").lower()
        p.port = s.port
        p.query = s.query
        p.segments = [seg for seg in (s.path or "").split("/") if seg]
        p.ok = bool(p.host)
        if not p.ok:
            p.error = "호스트를 읽을 수 없습니다"
    except ValueError as exc:
        p.error = str(exc)
    return p


def strip_query(url: str) -> str:
    """18-가 픽스 — URL 에 붙은 요청 파라메터를 떼어낸다."""
    raw = norm(url)
    return raw.split("?", 1)[0].split("#", 1)[0].rstrip("&?") if raw else raw


def has_hangul(v: str) -> bool:
    return bool(RE_HANGUL.search(norm(v)))


def code_key(v: str) -> str:
    """에러코드 비교용 정규화 — '00', '0', 0 을 같게 본다."""
    s = norm(v)
    if re.fullmatch(r"\d+", s):
        return str(int(s))
    return s.upper()


def looks_like(name: str, needles) -> bool:
    """항목명·설명에 후보 낱말이 들어 있는지. 영문은 대소문자를 무시한다."""
    s = norm(name).lower().replace("_", "").replace("-", "").replace(" ", "")
    return any(n.lower().replace("_", "") in s for n in needles)


def name_equals(name: str, needles) -> bool:
    """항목명이 후보와 정확히 같은지 (부분일치로 번지지 않게)."""
    s = norm(name).lower().replace("_", "").replace("-", "").replace(" ", "")
    return any(s == n.lower().replace("_", "") for n in needles)
