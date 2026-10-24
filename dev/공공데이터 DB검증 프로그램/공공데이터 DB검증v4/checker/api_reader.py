# -*- coding: utf-8 -*-
"""OPEN API 기술문서 판독 — Swagger/OpenAPI JSON, 오퍼레이션 명세표(엑셀·CSV).

두 판독기 모두 결과를 ApiSpec 하나로 맞춘다. 규칙(rules_api)은 어느 쪽에서
읽었는지 모르게 하려는 것이다. 어떤 방식으로 읽었는지는 `source_kind` 와
`notes` 에 남겨 화면에서 확인할 수 있게 한다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .api_models import (REQUEST, RESPONSE, ApiErrorCode, ApiOperation,
                         ApiParam, ApiSpec, norm)
from .readers import decode, detect_delimiter, detect_encoding, ext_of, read_csv_text, read_xlsx

MAX_REF_DEPTH = 6          # $ref 순환 방지
MAX_PARAMS = 4000          # 비정상적으로 큰 명세 방어

# ---- 명세표 열 이름 별칭 ------------------------------------------------
ALIAS: Dict[str, Tuple[str, ...]] = {
    "name": ("항목명영문", "영문항목명", "영문명", "파라메터명영문", "파라미터명영문",
             "name", "필드명", "요소명", "변수명"),
    "ko_name": ("항목명국문", "국문항목명", "국문명", "항목명", "한글명", "한글항목명",
                "파라메터명", "파라미터명"),
    "desc": ("항목설명", "설명", "description", "desc", "항목정의", "비고"),
    "type": ("항목유형", "유형", "타입", "type", "데이터타입", "자료형"),
    "size": ("항목크기", "크기", "길이", "length", "size"),
    "required": ("항목구분", "필수여부", "required", "필수", "구분필수", "옵션여부"),
    "sample": ("샘플데이터", "샘플", "예시", "예시값", "sample", "example", "샘플값"),
    "op": ("오퍼레이션", "오퍼레이션명", "오퍼레이션명국문", "operation", "기능명", "api명"),
    "side": ("메시지구분", "요청응답", "요청응답구분", "파라메터구분", "파라미터구분",
             "메세지구분", "reqres", "inout"),
}
ERR_ALIAS: Dict[str, Tuple[str, ...]] = {
    "code": ("에러코드", "오류코드", "에러코드값", "errorcode"),
    "message": ("에러메시지", "오류메시지", "에러메세지", "errormessage"),
    "desc": ("설명", "에러설명", "오류설명", "description", "비고", "조치방법"),
}

RE_SECTION_REQ = re.compile(r"요\s*청.*(메시지|메세지|파라|명세|항목)")
RE_SECTION_RES = re.compile(r"응\s*답.*(메시지|메세지|파라|명세|항목)")
RE_SECTION_ERR = re.compile(r"(에러|오류)\s*코드")
#: 에러코드 표의 머리글로 보려면 '에러·오류' 라는 말이 실제로 있어야 한다.
#: 이 조건이 없으면 `결과코드 | resultCode | …` 같은 응답 파라메터 줄이
#: 에러코드 머리글로 잘못 잡혀 그 아래 항목이 통째로 사라진다.
RE_ERR_HINT = re.compile(r"(에러|오류|error)", re.I)
RE_OP_KO = re.compile(r"오퍼레이션\s*명?\s*\(?\s*국문\s*\)?")
RE_OP_EN = re.compile(r"오퍼레이션\s*명?\s*\(?\s*영문\s*\)?")
RE_REQUIRED_YES = re.compile(r"(필수|required|필|1|Y|M)$", re.I)
RE_REQUIRED_NO = re.compile(r"(옵션|option|선택|0|N|O)$", re.I)


def _key(v: Any) -> str:
    """열 이름 비교용 정규화 — 공백·괄호·기호를 지우고 소문자로."""
    return re.sub(r"[\s()（）\[\]{}·:：/\\_\-.]", "", norm(v)).lower()


def _match(cell: str, names: Tuple[str, ...]) -> bool:
    """열 이름이 별칭 중 하나인지.

    부분일치는 **한글 별칭에만** 허용한다. 영문 별칭까지 부분일치를 허용하면
    `code` 가 `resultCode` 에, `type` 이 `dataType` 에 걸려 파라메터 줄을
    머리글로 오인한다.
    """
    k = _key(cell)
    if not k:
        return False
    for n in names:
        if k == n:
            return True
        if len(n) >= 4 and not n.isascii() and n in k:
            return True
    return False


def _required_of(v: str) -> Optional[bool]:
    s = norm(v)
    if not s:
        return None
    if RE_REQUIRED_NO.search(s):
        return False
    if RE_REQUIRED_YES.search(s):
        return True
    return None


# =======================================================================
# 진입점
# =======================================================================
def read_spec(path: str) -> ApiSpec:
    """기술문서 1건을 읽어 ApiSpec 으로 정규화한다."""
    spec = ApiSpec(source_name=path.replace("\\", "/").split("/")[-1])
    ext = ext_of(path)
    try:
        if ext == "json":
            _read_json(path, spec)
        elif ext in {"xlsx", "xlsm"}:
            rows, sheets = read_xlsx(path)
            if len(sheets) > 1:
                spec.notes.append(f"시트 {len(sheets)}개 중 첫 시트만 읽었습니다: {sheets[0]}")
            _read_table(rows, spec)
        elif ext in {"csv", "tsv", "txt"}:
            enc, raw = detect_encoding(path)
            text = decode(raw, enc if enc != "unknown" else "utf-8")
            delim = "\t" if ext == "tsv" else detect_delimiter(text)
            _read_table(read_csv_text(text, delimiter=delim), spec)
        elif ext in {"yaml", "yml"}:
            spec.parse_error = ("YAML 기술문서는 읽지 못합니다. Swagger Editor 등에서 "
                                "JSON 으로 변환해 올려 주세요.")
        else:
            spec.parse_error = (f"{ext.upper() or '이'} 형식은 기술문서로 읽을 수 없습니다. "
                                "Swagger/OpenAPI JSON 또는 오퍼레이션 명세표"
                                "(xlsx · csv)를 올려 주세요.")
    except Exception as exc:                       # noqa: BLE001
        spec.parse_error = f"기술문서를 읽는 중 오류가 발생했습니다: {exc}"
    return spec


# =======================================================================
# Swagger / OpenAPI JSON
# =======================================================================
def _read_json(path: str, spec: ApiSpec) -> None:
    enc, raw = detect_encoding(path)
    data = json.loads(decode(raw, enc if enc != "unknown" else "utf-8"))
    if not isinstance(data, dict):
        spec.parse_error = "최상위가 객체가 아니어서 기술문서로 읽을 수 없습니다."
        return
    if "paths" in data and isinstance(data.get("paths"), dict):
        _read_swagger(data, spec)
        return
    spec.parse_error = ("paths 항목이 없어 Swagger/OpenAPI 문서로 보이지 않습니다. "
                        "명세표(xlsx · csv)로 올리거나 SWAGGER JSON 을 내려받아 "
                        "올려 주세요.")


def _read_swagger(doc: Dict, spec: ApiSpec) -> None:
    is_v3 = str(doc.get("openapi") or "").startswith("3")
    spec.source_kind = "swagger"
    info = doc.get("info") or {}
    spec.title = norm(info.get("title"))
    spec.notes.append("OpenAPI 3.x 문서로 읽었습니다." if is_v3
                      else "Swagger 2.0 문서로 읽었습니다.")

    spec.base_url = _swagger_base(doc, is_v3)
    produces = [norm(p) for p in (doc.get("produces") or []) if norm(p)]

    for raw_path, node in (doc.get("paths") or {}).items():
        if not isinstance(node, dict):
            continue
        for method, op in node.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch", "head"):
                continue
            if not isinstance(op, dict):
                continue
            spec.operations.append(
                _swagger_operation(doc, spec, raw_path, method, op, produces, is_v3))

    fmts = set()
    for o in spec.operations:
        for ct in o.content_types:
            if "json" in ct.lower():
                fmts.add("JSON")
            elif "xml" in ct.lower():
                fmts.add("XML")
    spec.formats = sorted(fmts)
    _swagger_error_codes(doc, spec)

    if not spec.operations:
        spec.notes.append("paths 안에서 읽을 수 있는 오퍼레이션을 찾지 못했습니다.")


def _swagger_base(doc: Dict, is_v3: bool) -> str:
    if is_v3:
        servers = doc.get("servers") or []
        if servers and isinstance(servers[0], dict):
            return norm(servers[0].get("url"))
        return ""
    host, base = norm(doc.get("host")), norm(doc.get("basePath"))
    if not host:
        return ""
    schemes = doc.get("schemes") or ["https"]
    return f"{schemes[0]}://{host}{base}"


def _swagger_operation(doc: Dict, spec: ApiSpec, raw_path: str, method: str,
                       op: Dict, produces: List[str], is_v3: bool) -> ApiOperation:
    name_en = norm(op.get("operationId")) or raw_path.strip("/").split("/")[-1]
    name_ko = norm(op.get("summary")) or norm(op.get("description"))[:60]
    url = (spec.base_url.rstrip("/") + "/" + raw_path.lstrip("/")) if spec.base_url else raw_path
    o = ApiOperation(name_ko=name_ko, name_en=name_en, url=url,
                     method=method.upper(), summary=norm(op.get("description")))

    o.content_types = [norm(p) for p in (op.get("produces") or produces) if norm(p)]

    for p in op.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        p = _deref(doc, p)
        if norm(p.get("in")).lower() == "body":
            o.request.extend(_schema_params(
                doc, _body_schema(p, is_v3), REQUEST, o.title, prefix=""))
            continue
        o.request.append(ApiParam(
            name=norm(p.get("name")),
            ko_name=_ko_of(p),
            desc=norm(p.get("description")),
            type=_type_of(doc, p, is_v3),
            required=bool(p.get("required")) if "required" in p else None,
            sample=_sample_of(p, is_v3), where=REQUEST, op=o.title))

    if is_v3 and isinstance(op.get("requestBody"), dict):
        body = _deref(doc, op["requestBody"])
        for ct, node in (body.get("content") or {}).items():
            o.request.extend(_schema_params(
                doc, (node or {}).get("schema"), REQUEST, o.title, prefix=""))
            break

    ok = _ok_response(op)
    if ok is not None:
        ok = _deref(doc, ok)
        if is_v3:
            for ct, node in (ok.get("content") or {}).items():
                if norm(ct) and norm(ct) not in o.content_types:
                    o.content_types.append(norm(ct))
                o.response.extend(_schema_params(
                    doc, (node or {}).get("schema"), RESPONSE, o.title, prefix=""))
        else:
            o.response.extend(_schema_params(
                doc, ok.get("schema"), RESPONSE, o.title, prefix=""))
    return o


def _ok_response(op: Dict) -> Optional[Dict]:
    responses = op.get("responses") or {}
    for key in ("200", 200, "default"):
        node = responses.get(key)
        if isinstance(node, dict):
            return node
    for node in responses.values():
        if isinstance(node, dict):
            return node
    return None


def _body_schema(p: Dict, is_v3: bool) -> Optional[Dict]:
    return p.get("schema")


def _ko_of(p: Dict) -> str:
    for k in ("title", "x-korean-name", "x-name-ko", "koName"):
        v = norm(p.get(k))
        if v:
            return v
    return ""


def _type_of(doc: Dict, p: Dict, is_v3: bool) -> str:
    if is_v3 and isinstance(p.get("schema"), dict):
        s = _deref(doc, p["schema"])
        return norm(s.get("type")) or norm(s.get("format"))
    return norm(p.get("type")) or norm(p.get("format"))


def _sample_of(p: Dict, is_v3: bool) -> str:
    for holder in (p, p.get("schema") if isinstance(p.get("schema"), dict) else {}):
        for k in ("example", "x-example", "default"):
            v = holder.get(k)
            if v not in (None, ""):
                return norm(v)
        ex = holder.get("examples")
        if isinstance(ex, dict) and ex:
            first = next(iter(ex.values()))
            if isinstance(first, dict) and "value" in first:
                return norm(first["value"])
            return norm(first)
    return ""


def _deref(doc: Dict, node: Any, depth: int = 0) -> Dict:
    """$ref 를 실제 정의로 바꾼다. 순환 참조는 깊이로 끊는다."""
    if not isinstance(node, dict) or depth > MAX_REF_DEPTH:
        return node if isinstance(node, dict) else {}
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return node
    cur: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or part not in cur:
            return {}
        cur = cur[part]
    merged = _deref(doc, cur, depth + 1)
    rest = {k: v for k, v in node.items() if k != "$ref"}
    return {**merged, **rest} if rest else merged


def _schema_params(doc: Dict, schema: Any, where: str, op_title: str,
                   prefix: str = "", depth: int = 0) -> List[ApiParam]:
    """응답 스키마를 평평한 파라메터 목록으로 편다."""
    out: List[ApiParam] = []
    if depth > MAX_REF_DEPTH or not isinstance(schema, dict):
        return out
    schema = _deref(doc, schema, depth)
    if schema.get("type") == "array" or "items" in schema:
        return _schema_params(doc, schema.get("items"), where, op_title, prefix, depth + 1)

    props = schema.get("properties")
    if not isinstance(props, dict):
        return out
    required = set(schema.get("required") or [])
    for name, node in props.items():
        if len(out) >= MAX_PARAMS:
            break
        node = _deref(doc, node, depth)
        full = f"{prefix}{name}"
        kind = norm(node.get("type"))
        if kind in ("object", "array") or "properties" in node or "items" in node:
            child = _schema_params(doc, node, where, op_title, f"{full}.", depth + 1)
            if child:
                out.extend(child)
                continue
        out.append(ApiParam(
            name=full, ko_name=_ko_of(node), desc=norm(node.get("description")),
            type=kind or norm(node.get("format")),
            required=(name in required) if required else None,
            sample=_sample_of(node, True), where=where, op=op_title))
    return out


def _swagger_error_codes(doc: Dict, spec: ApiSpec) -> None:
    """responses 의 200 외 상태코드와, 별도로 적어 둔 에러코드 표를 모은다."""
    seen = set()
    for node in (doc.get("paths") or {}).values():
        if not isinstance(node, dict):
            continue
        for op in node.values():
            if not isinstance(op, dict):
                continue
            for code, body in (op.get("responses") or {}).items():
                c = norm(code)
                if c in ("200", "default", "") or c in seen:
                    continue
                seen.add(c)
                spec.error_codes.append(ApiErrorCode(
                    code=c, message=norm((body or {}).get("description"))))
    for key in ("x-error-codes", "x-errorCodes", "errorCodes"):
        rows = doc.get(key)
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    spec.error_codes.append(ApiErrorCode(
                        code=norm(r.get("code") or r.get("errorCode")),
                        message=norm(r.get("message") or r.get("errorMessage")),
                        desc=norm(r.get("description") or r.get("desc"))))


# =======================================================================
# 오퍼레이션 명세표 (엑셀 · CSV)
# =======================================================================
def _read_table(rows: List[List[str]], spec: ApiSpec) -> None:
    """공공데이터포털 기술문서 서식을 훑어 오퍼레이션·파라메터·에러코드를 뽑는다.

    서식이 기관마다 조금씩 달라서 위치가 아니라 **머리글 이름**으로 열을 찾고,
    '요청 메시지 명세' 같은 구역 제목을 만나면 그때부터 요청/응답을 갈라 담는다.
    """
    spec.source_kind = "table"
    rows = [[norm(c) for c in r] for r in rows if any(norm(c) for c in r)]
    if not rows:
        spec.parse_error = "명세표가 비어 있습니다."
        return

    ops: Dict[str, ApiOperation] = {}
    cur_op = ApiOperation(name_ko="", name_en="")
    side = RESPONSE
    cols: Dict[str, int] = {}
    err_cols: Dict[str, int] = {}
    mode = ""          # "param" | "error"
    found_header = False

    def op_for(title_ko: str, title_en: str) -> ApiOperation:
        key = (title_ko or title_en or "(오퍼레이션)").strip()
        if key not in ops:
            ops[key] = ApiOperation(name_ko=title_ko, name_en=title_en)
        else:
            if title_ko and not ops[key].name_ko:
                ops[key].name_ko = title_ko
            if title_en and not ops[key].name_en:
                ops[key].name_en = title_en
        return ops[key]

    for row in rows:
        joined = " ".join(row)

        # 1) 키-값 줄 (오퍼레이션명, URL 등)
        kv = _kv_of(row)
        if kv:
            k, v = kv
            if RE_OP_KO.search(k):
                cur_op = op_for(v, cur_op.name_en)
                continue
            if RE_OP_EN.search(k):
                cur_op = op_for(cur_op.name_ko, v)
                continue
            if _match(k, ("서비스url", "외부노출url", "호출url", "endpoint",
                          "요청주소", "url", "서비스urlhttp")):
                if v and not cur_op.url:
                    cur_op.url = v
                if v and not spec.base_url:
                    spec.base_url = v
                continue
            if _match(k, ("서비스명", "api명", "오픈api명", "서비스이름")):
                spec.title = spec.title or v
                continue
            if _match(k, ("메세지교환유형", "메시지교환유형", "httpmethod", "요청방식", "전송방식")):
                if v and not cur_op.method:
                    cur_op.method = v.upper()
                continue
            if _match(k, ("데이터포맷", "응답포맷", "출력포맷", "포맷")):
                for f in ("JSON", "XML"):
                    if f.lower() in v.lower() and f not in spec.formats:
                        spec.formats.append(f)
                continue

        # 2) 구역 제목
        if RE_SECTION_ERR.search(joined) and not _looks_header(row, ALIAS):
            mode, err_cols = "error", {}
            continue
        if RE_SECTION_REQ.search(joined):
            side, mode = REQUEST, "param"
            cols = {}
            continue
        if RE_SECTION_RES.search(joined):
            side, mode = RESPONSE, "param"
            cols = {}
            continue

        # 3) 머리글
        if (_looks_header(row, ERR_ALIAS) and RE_ERR_HINT.search(joined)
                and not _looks_header(row, ALIAS)):
            err_cols = _header_map(row, ERR_ALIAS)
            mode = "error"
            continue
        if _looks_header(row, ALIAS):
            cols = _header_map(row, ALIAS)
            mode, found_header = "param", True
            continue

        # 4) 본문
        if mode == "error" and err_cols:
            code = _cell(row, err_cols.get("code"))
            if code and not _match(code, ERR_ALIAS["code"]):
                spec.error_codes.append(ApiErrorCode(
                    code=code, message=_cell(row, err_cols.get("message")),
                    desc=_cell(row, err_cols.get("desc"))))
            continue
        if mode == "param" and cols:
            p = _param_of(row, cols, side)
            if not (p.name or p.ko_name):
                continue
            target = cur_op
            op_cell = _cell(row, cols.get("op"))
            if op_cell:
                target = op_for(op_cell, "")
            elif target.title == "(오퍼레이션)" and ops:
                target = list(ops.values())[-1]
            if target.title not in ops:
                ops[target.title] = target
            p.op = target.title
            p.where = _side_of(row, cols, side)
            (target.request if p.where == REQUEST else target.response).append(p)

    spec.operations = [o for o in ops.values() if o.request or o.response or o.url]
    if not spec.operations and (cur_op.request or cur_op.response):
        spec.operations = [cur_op]

    if not found_header:
        spec.parse_error = (
            "명세표에서 항목명 머리글을 찾지 못했습니다. "
            "'항목명(영문) · 항목명(국문) · 항목크기 · 항목구분 · 샘플데이터 · 항목설명' "
            "형태의 머리글이 있는 표인지 확인해 주세요.")
        return

    n = sum(len(o.params) for o in spec.operations)
    spec.notes.append(
        f"명세표에서 오퍼레이션 {len(spec.operations)}개 · 파라메터 {n}개를 읽었습니다.")
    if spec.error_codes:
        spec.notes.append(f"에러코드 {len(spec.error_codes)}개를 읽었습니다.")


def _looks_header(row: List[str], alias: Dict[str, Tuple[str, ...]]) -> bool:
    hits = sum(1 for cell in row
               if any(_match(cell, names) for names in alias.values()))
    return hits >= 2


def _header_map(row: List[str], alias: Dict[str, Tuple[str, ...]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, cell in enumerate(row):
        for key, names in alias.items():
            if key not in out and _match(cell, names):
                out[key] = i
                break
    return out


def _cell(row: List[str], idx: Optional[int]) -> str:
    if idx is None or idx >= len(row):
        return ""
    return norm(row[idx])


def _kv_of(row: List[str]) -> Optional[Tuple[str, str]]:
    """'오퍼레이션명(국문) | 자전거보관소 조회' 형태의 두 칸짜리 줄."""
    filled = [(i, c) for i, c in enumerate(row) if c]
    if not 2 <= len(filled) <= 3:
        return None
    key, val = filled[0][1], filled[1][1]
    if len(key) > 30 or not val:
        return None
    return key, val


def _side_of(row: List[str], cols: Dict[str, int], default: str) -> str:
    v = _cell(row, cols.get("side"))
    if not v:
        return default
    low = v.lower()
    if "요청" in v or "request" in low or low in ("req", "in"):
        return REQUEST
    if "응답" in v or "response" in low or low in ("res", "out"):
        return RESPONSE
    return default


def _param_of(row: List[str], cols: Dict[str, int], side: str) -> ApiParam:
    return ApiParam(
        name=_cell(row, cols.get("name")),
        ko_name=_cell(row, cols.get("ko_name")),
        desc=_cell(row, cols.get("desc")),
        type=_cell(row, cols.get("type")),
        required=_required_of(_cell(row, cols.get("required"))),
        sample=_cell(row, cols.get("sample")),
        where=side)
