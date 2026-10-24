# -*- coding: utf-8 -*-
"""endPoint 실호출 검사 (19번 · 16번 · 8-나).

기재한 URL 로 실제 한 번 호출해 상태코드·응답시간·Content-Type·응답 항목명을
받아 온다. 사내망이나 오프라인에서는 쓸 수 없으므로 **화면에서 켤 때만** 동작하며,
표준 라이브러리(urllib)만 쓴다. exe 용량을 늘리지 않으려는 것이다.

호출은 GET 한 번으로 끝내고 응답 본문도 앞부분만 읽는다. 검토 도구가 대상
서버에 부하를 주면 안 되기 때문이다.
"""
from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from .api_models import norm

BODY_LIMIT = 256 * 1024        # 응답 본문은 앞 256KB 만 읽는다
DEFAULT_TIMEOUT = 10.0         # 19-마 기준(5초)의 두 배까지 기다렸다가 끊는다
SLOW_LIMIT = 5.0               # 19-마 · 8-나 응답 지연 기준
UA = "PublicDataPrecheck/2.1 (+KISTEP)"
RE_XML_TAG = re.compile(r"<\s*([A-Za-z_][\w.\-]*)\s*[>/ ]")


@dataclass
class ProbeResult:
    url: str = ""
    called: str = ""                 # 인증키를 가린 실제 호출 URL
    ok: bool = False                 # 호출 자체가 성공했는지
    status: int = 0
    elapsed: float = 0.0
    content_type: str = ""
    body_kind: str = ""              # json | xml | html | text | binary
    fields: List[str] = field(default_factory=list)   # 응답에서 찾은 항목명
    body_head: str = ""
    error: str = ""

    @property
    def slow(self) -> bool:
        return self.elapsed >= SLOW_LIMIT

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["slow"] = self.slow
        return d


def mask_key(url: str) -> str:
    """화면·리포트에 남기는 URL 에서 인증키를 가린다."""
    return re.sub(r"((?:serviceKey|authKey|apiKey|key)=)[^&]+", r"\1****", url,
                  flags=re.I)


def build_url(url: str, service_key: str = "", extra: Optional[Dict[str, str]] = None) -> str:
    """인증키와 기본 파라메터를 붙인 호출 URL 을 만든다.

    이미 serviceKey 가 붙어 있으면 건드리지 않는다. 사용자가 직접 완성한
    호출 URL 을 넣었을 수 있기 때문이다.
    """
    u = norm(url)
    if not u:
        return ""
    parts = urlsplit(u)
    query = parts.query
    add: Dict[str, str] = dict(extra or {})
    if service_key and not re.search(r"(serviceKey|authKey|apiKey)=", query, re.I):
        add["serviceKey"] = service_key
    if add:
        query = (query + "&" if query else "") + urlencode(add, safe="%+=")
    return urlunsplit((parts.scheme or "http", parts.netloc, parts.path, query, ""))


def probe(url: str, service_key: str = "", timeout: float = DEFAULT_TIMEOUT,
          extra: Optional[Dict[str, str]] = None) -> ProbeResult:
    """URL 하나를 GET 으로 한 번 호출한다. 예외는 결과에 담고 올리지 않는다."""
    called = build_url(url, service_key, extra)
    res = ProbeResult(url=norm(url), called=mask_key(called))
    if not called:
        res.error = "호출할 URL 이 없습니다."
        return res
    if not called.lower().startswith(("http://", "https://")):
        res.error = "http:// 또는 https:// 로 시작하는 URL 이 아닙니다."
        return res

    req = urllib.request.Request(called, headers={
        "User-Agent": UA, "Accept": "application/json, application/xml;q=0.9, */*;q=0.5"})
    started = time.monotonic()
    raw = b""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res.status = int(getattr(resp, "status", 0) or resp.getcode() or 0)
            res.content_type = norm(resp.headers.get("Content-Type"))
            raw = resp.read(BODY_LIMIT)
            res.ok = True
    except urllib.error.HTTPError as exc:
        # 200 이 아닌 응답도 검토 대상이므로 본문까지 받아 둔다
        res.status = int(exc.code or 0)
        res.content_type = norm(exc.headers.get("Content-Type") if exc.headers else "")
        try:
            raw = exc.read(BODY_LIMIT)
        except Exception:                          # noqa: BLE001
            raw = b""
        res.ok = True
        res.error = f"HTTP {exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        res.error = f"연결하지 못했습니다: {getattr(exc, 'reason', exc)}"
    except socket.timeout:
        res.error = f"{timeout:.0f}초 안에 응답이 없어 호출을 끊었습니다."
    except Exception as exc:                       # noqa: BLE001
        res.error = f"호출 중 오류가 발생했습니다: {exc}"
    finally:
        res.elapsed = round(time.monotonic() - started, 3)

    if raw:
        _read_body(res, raw)
    return res


def probe_many(urls: List[str], service_key: str = "", limit: int = 5,
               timeout: float = DEFAULT_TIMEOUT) -> List[ProbeResult]:
    """URL 여러 개를 차례로 호출한다. 대상 서버 부하를 생각해 개수를 제한한다."""
    seen: List[str] = []
    for u in urls:
        u = norm(u)
        if u and u not in seen:
            seen.append(u)
    return [probe(u, service_key, timeout) for u in seen[:limit]]


# ---- 응답 본문 판독 -----------------------------------------------------
def _read_body(res: ProbeResult, raw: bytes) -> None:
    text = ""
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        res.body_kind = "binary"
        return

    res.body_head = text[:600]
    head = text.lstrip()[:400].lower()

    if head.startswith(("{", "[")):
        try:
            res.fields = _json_fields(json.loads(text))
            res.body_kind = "json"
            return
        except (ValueError, RecursionError):
            pass
    if head.startswith("<?xml") or (head.startswith("<") and "<html" not in head):
        res.body_kind = "xml"
        res.fields = _xml_fields(text)
        return
    if "<html" in head or "<!doctype html" in head:
        res.body_kind = "html"
        return
    res.body_kind = "text"


def _json_fields(node: Any, depth: int = 0, out: Optional[List[str]] = None) -> List[str]:
    out = [] if out is None else out
    if depth > 8 or len(out) > 500:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            if k not in out:
                out.append(str(k))
            _json_fields(v, depth + 1, out)
    elif isinstance(node, list):
        for v in node[:20]:
            _json_fields(v, depth + 1, out)
    return out


def _xml_fields(text: str) -> List[str]:
    out: List[str] = []
    for m in RE_XML_TAG.finditer(text[:BODY_LIMIT]):
        tag = m.group(1)
        if tag not in out:
            out.append(tag)
        if len(out) > 500:
            break
    return out
