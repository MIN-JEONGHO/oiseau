# -*- coding: utf-8 -*-
"""OPEN API 회귀 테스트: python tests/test_api_rules.py

바깥으로 실제 요청을 보내지 않는다. 19번(실호출) 검사는 ProbeResult 를 직접
만들어 넣어 확인한다. 검토 도구의 테스트가 남의 서버를 두드리면 안 된다.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checker.api_fixer import API_FIXABLE, fix_api            # noqa: E402
from checker.api_models import ApiSpec                        # noqa: E402
from checker.api_probe import ProbeResult, build_url, mask_key  # noqa: E402
from checker.api_reader import read_spec                      # noqa: E402
from checker.engine import check_api                          # noqa: E402
from checker.models import Level                              # noqa: E402
from checker.rules_api import check_api as run_rules          # noqa: E402

# ---- 공통 자료 ---------------------------------------------------------
GOOD_META = {
    "목록명": "공공데이터활용지원센터_자전거보관소현황 조회 서비스",
    "기관명": "공공데이터활용지원센터",
    "기관코드": "15012345",
    "API명(영문)": "BikeInfoService",
    "등록유형": "PUBC",
    "서비스URL": "https://apis.data.go.kr/15012345/BikeInfoService/getBikeList",
    "응답포맷": "JSON",
    "전송방식": "GET",
    "키워드": "자전거, 보관소, 거치대, 교통시설",
    "설명": "자치구별 자전거 보관소의 위치와 보관 가능 대수를 제공하는 데이터로 "
            "생활교통 분야 서비스 개발에 활용할 수 있습니다.",
    "공공누리유형": "제1유형",
    "부담당자": "홍길동",
    "담당자연락처": "02-1234-5678",
    "중복확인": "완료",
    "기술문서검토": "완료",
    "TESTKEY": "testkey-0001",
}

SWAGGER = {
    "swagger": "2.0",
    "info": {"title": "자전거보관소 정보 서비스"},
    "host": "apis.data.go.kr",
    "basePath": "/15012345/BikeInfoService",
    "schemes": ["https"],
    "produces": ["application/json;charset=UTF-8"],
    "paths": {
        "/getBikeList": {
            "get": {
                "operationId": "getBikeList",
                "summary": "자전거보관소 목록 조회",
                "parameters": [
                    {"name": "serviceKey", "in": "query", "required": True,
                     "type": "string", "description": "인증키", "example": "abcd"},
                    {"name": "pageNo", "in": "query", "type": "string",
                     "description": "페이지 번호", "example": "1"},
                    {"name": "numOfRows", "in": "query", "type": "string",
                     "description": "한 페이지 결과 수", "example": "10"},
                ],
                "responses": {"200": {"description": "OK",
                                      "schema": {"$ref": "#/definitions/Resp"}}},
            }
        }
    },
    "definitions": {
        "Resp": {
            "type": "object",
            "properties": {
                "resultCode": {"type": "string", "description": "결과코드"},
                "resultMsg": {"type": "string", "description": "결과메시지"},
                "totalCount": {"type": "integer", "description": "전체 결과수"},
                "items": {"type": "array", "items": {"$ref": "#/definitions/Item"}},
            },
        },
        "Item": {
            "type": "object",
            "properties": {
                "bikeStationNm": {"type": "string", "description": "보관소 이름"},
                "parkingCnt": {"type": "integer", "description": "보관 가능 대수(대)"},
            },
        },
    },
}


def _json_file(payload) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


def _csv_file(rows) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path


def rule_ids(res):
    return {f.rule_id for f in res.findings}


def run(meta=None, spec_path="", probes=None):
    """규칙만 직접 돌린다(실호출 없음)."""
    if probes is None:
        res, _spec = check_api(meta or {}, spec_path=spec_path)
        return res
    from checker.models import Result
    spec = read_spec(spec_path) if spec_path else ApiSpec()
    spec.meta = dict(meta or {})
    res = Result(file_name="t", file_path="", domain="api")
    run_rules(res, spec, probes)
    return res


# ---- 기술문서 판독 -----------------------------------------------------
def test_swagger를_읽어_오퍼레이션과_파라메터를_뽑는다():
    spec = read_spec(_json_file(SWAGGER))
    assert spec.source_kind == "swagger", spec.parse_error
    assert len(spec.operations) == 1
    op = spec.operations[0]
    assert op.name_ko == "자전거보관소 목록 조회" and op.name_en == "getBikeList"
    assert op.method == "GET"
    assert {p.name for p in op.request} == {"serviceKey", "pageNo", "numOfRows"}
    # 배열 안 객체는 items.필드 형태로 펼쳐진다
    assert "items.bikeStationNm" in {p.name for p in op.response}
    assert spec.formats == ["JSON"]


def test_swagger가_아니면_이유를_알려준다():
    spec = read_spec(_json_file({"hello": "world"}))
    assert spec.parse_error and "paths" in spec.parse_error


def test_명세표_csv를_읽는다():
    rows = [
        ["오퍼레이션명(국문)", "자전거보관소 목록 조회"],
        ["오퍼레이션명(영문)", "getBikeList"],
        ["요청 메시지 명세"],
        ["항목명(국문)", "항목명(영문)", "항목크기", "항목구분", "샘플데이터", "항목설명"],
        ["인증키", "serviceKey", "100", "필수", "abcd", "공공데이터포털 인증키"],
        ["페이지 번호", "pageNo", "4", "옵션", "1", "페이지 번호"],
        ["응답 메시지 명세"],
        ["항목명(국문)", "항목명(영문)", "항목크기", "항목구분", "샘플데이터", "항목설명"],
        ["결과코드", "resultCode", "2", "필수", "00", "결과코드"],
        ["보관소명", "bikeStationNm", "50", "필수", "강남역", "보관소 이름"],
    ]
    spec = read_spec(_csv_file(rows))
    assert spec.source_kind == "table", spec.parse_error
    assert not spec.parse_error, spec.parse_error
    assert len(spec.operations) == 1
    op = spec.operations[0]
    assert op.name_ko == "자전거보관소 목록 조회"
    assert {p.name for p in op.request} == {"serviceKey", "pageNo"}
    assert {p.name for p in op.response} == {"resultCode", "bikeStationNm"}
    assert op.request[0].required is True and op.request[1].required is False


def test_머리글이_없으면_읽지_못한_사실을_알려준다():
    spec = read_spec(_csv_file([["아무", "내용"], ["1", "2"]]))
    assert spec.parse_error and "머리글" in spec.parse_error


# ---- 등록 정보 규칙 (5~10번) --------------------------------------------
def test_목록명_특수문자와_주기표시():
    res = run({**GOOD_META, "목록명": "센터_자전거현황(연간)!"})
    assert {"5-가", "5-나"} <= rule_ids(res)


def test_목록명_연도는_연도별_분리_개방으로_본다():
    res = run({**GOOD_META, "목록명": "센터_2023년 자전거현황 조회 서비스"})
    assert "4-나" in rule_ids(res)


def test_키워드_개수와_중복():
    res = run({**GOOD_META, "키워드": "자전거, 자전거 거치대, 자전거거치대"})
    ids = rule_ids(res)
    assert "6-다" in ids                       # 띄어쓰기만 다른 중복
    res2 = run({**GOOD_META, "키워드": "자전거, 보관소"})
    assert "6-나" in rule_ids(res2)             # 3개 미만


def test_설명_50자_미만():
    res = run({**GOOD_META, "설명": "자전거 보관소 현황"})
    assert "7-가" in rule_ids(res)


def test_제공신청_예인데_제공번호_없음():
    res = run({**GOOD_META, "제공신청여부": "예"})
    assert "9-가" in rule_ids(res)


def test_담당자_연락처_형식():
    res = run({**GOOD_META, "담당자연락처": "0212345678"})
    hit = [f for f in res.findings if f.rule_id == "10-나"]
    assert hit and hit[0].fix_key == "api:10-나"


# ---- 등록유형별 규칙 (12~14번) -----------------------------------------
def test_GW는_POST와_비표준_포트를_반려한다():
    res = run({**GOOD_META, "등록유형": "GW", "전송방식": "POST",
               "인증모듈적용": "예",
               "서비스URL": "https://apis.data.go.kr:8443/15012345/BikeInfoService/getBikeList"})
    ids = rule_ids(res)
    assert "13-다" in ids and "13-라" in ids


def test_GW_인증모듈_미적용은_반려():
    res = run({**GOOD_META, "등록유형": "GW", "전송방식": "GET"})
    assert "13-나" in rule_ids(res)


def test_PUBC는_TESTKEY가_없으면_반려():
    meta = dict(GOOD_META)
    meta.pop("TESTKEY")
    res = run(meta)
    assert "12-다" in rule_ids(res)


def test_기술문서와_등록내용이_다르면_잡는다():
    path = _json_file(SWAGGER)
    res = run({**GOOD_META, "응답포맷": "XML"}, spec_path=path)
    assert "12-나" in rule_ids(res)


def test_등록유형이_다르면_해당_항목은_검사하지_않는다():
    """13번(GW)은 GW 로 등록할 때만 본다. 유형을 가리지 않으면 오탐이 쏟아진다."""
    res = run({**GOOD_META, "등록유형": "PUBC", "전송방식": "POST"})
    assert "13-다" not in rule_ids(res)


def test_멀티클라우드는_설명없는_변수를_반려한다():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Item"]["properties"]["etcInfo"] = {"type": "string"}
    res = run({**GOOD_META, "등록유형": "멀티클라우드"}, spec_path=_json_file(doc))
    assert "14-다" in rule_ids(res)


# ---- 오퍼레이션 규칙 (17~18번) -----------------------------------------
def test_오퍼레이션명이_목록명과_같으면_반려():
    doc = json.loads(json.dumps(SWAGGER))
    doc["paths"]["/getBikeList"]["get"]["summary"] = GOOD_META["목록명"]
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "17-가" in rule_ids(res)


def test_국문_오퍼레이션명이_없으면_반려():
    doc = json.loads(json.dumps(SWAGGER))
    doc["paths"]["/getBikeList"]["get"]["summary"] = "bike list"
    doc["paths"]["/getBikeList"]["get"].pop("description", None)
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "17-나" in rule_ids(res)


def test_URL에_요청파라메터가_붙어_있으면_픽스대상():
    res = run({**GOOD_META,
               "서비스URL": GOOD_META["서비스URL"] + "?serviceKey=abc&pageNo=1"})
    hit = [f for f in res.findings if f.rule_id == "18-가"]
    assert hit and hit[0].fix_key == "api:18-가"


def test_API명과_오퍼레이션명이_같으면_반려():
    res = run({**GOOD_META,
               "서비스URL": "https://apis.data.go.kr/15012345/BikeInfoService/BikeInfoService"})
    assert "18-나" in rule_ids(res)


def test_포괄적인_단어_단독사용은_반려():
    res = run({**GOOD_META, "API명(영문)": "BikeInfoService",
               "서비스URL": "https://apis.data.go.kr/15012345/BikeInfoService/list"})
    msgs = [f.message for f in res.findings if f.rule_id == "18-나"]
    assert any("포괄적" in m for m in msgs), msgs


def test_영문항목명에_한글이_있으면_반려():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Item"]["properties"]["면적"] = {
        "type": "string", "description": "면적"}
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "18-다" in rule_ids(res)


def test_설명이_없는_항목은_반려():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Item"]["properties"]["addr"] = {"type": "string"}
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "18-라" in rule_ids(res)


# ---- 파라메터 규칙 (20~21번) -------------------------------------------
def test_페이징_파라메터가_없으면_반려():
    doc = json.loads(json.dumps(SWAGGER))
    doc["paths"]["/getBikeList"]["get"]["parameters"] = [
        {"name": "serviceKey", "in": "query", "type": "string",
         "description": "인증키", "example": "a"}]
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "20-나" in rule_ids(res)


def test_두_포맷을_제공하면_변환_파라메터가_있어야_한다():
    res = run({**GOOD_META, "응답포맷": "JSON+XML"}, spec_path=_json_file(SWAGGER))
    assert "20-가" in rule_ids(res)


def test_필수_응답파라메터_누락():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Resp"]["properties"].pop("totalCount")
    res = run(GOOD_META, spec_path=_json_file(doc))
    hit = [f for f in res.findings if f.rule_id == "21-가"]
    assert hit and "totalCount" in hit[0].message


def test_필수_응답파라메터가_모두_있으면_지적하지_않는다():
    res = run(GOOD_META, spec_path=_json_file(SWAGGER))
    assert "21-가" not in rule_ids(res)


# ---- 응답 항목 규칙 (1번) -----------------------------------------------
def test_seq만_응답하면_개방불가():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Item"]["properties"] = {
        "seq": {"type": "integer", "description": "순번"},
        "비고": {"type": "string", "description": "비고"}}
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "1-나" in rule_ids(res)


def test_로그성_항목은_확인권장():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Item"]["properties"]["ipAddr"] = {
        "type": "string", "description": "접속 IP"}
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "1-가" in rule_ids(res)


def test_개인정보_의심항목은_알린다():
    doc = json.loads(json.dumps(SWAGGER))
    doc["definitions"]["Item"]["properties"]["mobileNo"] = {
        "type": "string", "description": "휴대전화번호"}
    res = run(GOOD_META, spec_path=_json_file(doc))
    assert "23-나" in rule_ids(res)


# ---- 에러코드 규칙 (22번) ----------------------------------------------
def _spec_with_codes(codes):
    spec = ApiSpec(source_kind="table", source_name="t.xlsx")
    spec.meta = {**GOOD_META, "등록유형": "GW", "인증모듈적용": "예"}
    from checker.api_models import ApiErrorCode
    spec.error_codes = [ApiErrorCode(code=c, message=m) for c, m in codes]
    return spec


def test_포털_표준_에러코드와_200은_GW에서_반려():
    from checker.models import Result
    spec = _spec_with_codes([("30", "SERVICE KEY 미등록"), ("200", "정상"),
                             ("A01", "기관 자체 코드")])
    res = Result(file_name="t", file_path="", domain="api")
    run_rules(res, spec, [])
    hits = {f.rule_id: f.level for f in res.findings if f.rule_id.startswith("22-")}
    assert hits.get("22-나") is Level.REJECT and hits.get("22-다") is Level.REJECT


def test_GW가_아니면_에러코드는_확인권장으로_낮춘다():
    """안내문상 22번 반려 기준은 GW 전용이다. 유형을 안 가리면 과잉 반려가 된다."""
    from checker.models import Result
    spec = _spec_with_codes([("200", "정상")])
    spec.meta = {**GOOD_META, "등록유형": "PUBC"}
    res = Result(file_name="t", file_path="", domain="api")
    run_rules(res, spec, [])
    hit = [f for f in res.findings if f.rule_id == "22-다"]
    assert hit and hit[0].level is Level.REVIEW
    assert hit[0].fix_key == "api:22-다"      # 등급이 낮아도 픽스는 된다


def test_에러코드_픽스는_해당_행만_지운다():
    spec = _spec_with_codes([("30", "포털코드"), ("200", "정상"), ("A01", "기관코드")])
    fixed, rep = fix_api(spec, ["api:22-나", "api:22-다"])
    assert [c.code for c in fixed.error_codes] == ["A01"]
    assert len(rep.removed_codes) == 2


# ---- 실호출 규칙 (19번 · 16번) -----------------------------------------
def test_호출_실패와_상태코드와_지연을_잡는다():
    probes = [
        ProbeResult(url="u1", called="u1", ok=False, error="연결 실패"),
        ProbeResult(url="u2", called="u2", ok=True, status=500, elapsed=0.2),
        ProbeResult(url="u3", called="u3", ok=True, status=200, elapsed=7.5),
    ]
    res = run(GOOD_META, probes=probes)
    ids = rule_ids(res)
    assert {"19-가", "19-나", "19-마", "8-나"} <= ids


def test_Content_Type이_기준과_다르면_반려():
    probes = [ProbeResult(url="u", called="u", ok=True, status=200, elapsed=0.1,
                          content_type="text/html", body_kind="html")]
    res = run(GOOD_META, probes=probes)
    ids = rule_ids(res)
    assert "16-나" in ids and "16-가" in ids


def test_기재한_항목명이_실제_응답에_없으면_반려():
    probes = [ProbeResult(url="u", called="u", ok=True, status=200, elapsed=0.1,
                          content_type="application/json;charset=utf-8",
                          body_kind="json",
                          fields=["resultCode", "resultMsg", "totalCount", "items"])]
    res = run(GOOD_META, spec_path=_json_file(SWAGGER), probes=probes)
    hit = [f for f in res.findings if f.rule_id == "19-다"]
    assert hit and any("bikeStationNm" in " ".join(f.samples) for f in hit)


def test_실호출을_안하면_확인권장으로_남긴다():
    res = run(GOOD_META)
    hit = [f for f in res.findings if f.rule_id == "19-가"]
    assert hit and hit[0].level is Level.REVIEW


def test_인증키는_기록에서_가려진다():
    url = build_url("https://apis.data.go.kr/a/b/c", "SECRET-KEY")
    assert "SECRET-KEY" in url                    # 실제 호출에는 들어가고
    assert "SECRET-KEY" not in mask_key(url)      # 남기는 기록에서는 가린다


def test_이미_인증키가_붙어_있으면_덧붙이지_않는다():
    url = build_url("https://apis.data.go.kr/a/b/c?serviceKey=MINE", "OTHER")
    assert url.count("serviceKey") == 1 and "MINE" in url


# ---- 픽스 -------------------------------------------------------------
def test_픽스는_등록정보를_고치고_반려를_줄인다():
    meta = {**GOOD_META,
            "목록명": "센터_자전거현황(연간)!",
            "키워드": "자전거, 자전거 보관소, 자전거보관소, 보관대수!",
            "설명": "자전거  보관소  현황을  제공하는  데이터로 생활교통 분야 "
                    "서비스 개발에 활용할 수 있는 자료입니다.",
            "담당자연락처": "0212345678",
            "서비스URL": GOOD_META["서비스URL"] + "?serviceKey=abc"}
    res, spec = check_api(meta, spec_path=_json_file(SWAGGER))
    keys = sorted({f.fix_key for f in res.findings if f.fix_key in API_FIXABLE})
    assert keys, "픽스 가능한 지적사항이 없습니다"
    fixed, rep = fix_api(spec, keys)
    after, _ = check_api(fixed.meta, spec=fixed)
    assert after.counts()["반려"] < res.counts()["반려"]
    assert fixed.meta["목록명"] == "센터_자전거현황"
    assert fixed.meta["담당자연락처"] == "02-1234-5678"
    assert "?" not in fixed.meta["서비스URL"]


def test_픽스는_선택한_조항만_적용한다():
    meta = {**GOOD_META, "목록명": "센터_자전거현황(연간)!", "담당자연락처": "0212345678"}
    spec = ApiSpec()
    spec.meta = meta
    fixed, rep = fix_api(spec, ["api:5-가"])
    assert fixed.meta["목록명"] == "센터_자전거현황(연간)"    # 주기는 그대로
    assert fixed.meta["담당자연락처"] == "0212345678"        # 연락처도 그대로


def test_기술문서는_고치지_않고_알려만_준다():
    doc = json.loads(json.dumps(SWAGGER))
    doc["paths"]["/getBikeList"]["get"]["operationId"] = "getBikeList"
    spec = read_spec(_json_file(doc))
    spec.operations[0].url += "?serviceKey=abc"
    spec.meta = dict(GOOD_META)
    fixed, rep = fix_api(spec, ["api:18-가"])
    assert "?" in fixed.operations[0].url            # 문서 원본은 그대로
    assert rep.manual and "기술문서" in rep.manual[0]


def test_자동수정_불가항목에는_이유가_붙는다():
    res = run({**GOOD_META, "등록유형": "GW", "전송방식": "POST", "인증모듈적용": "예"})
    d = res.to_dict()
    hit = [f for f in d["findings"] if f["rule_id"] == "13-다"]
    assert hit and not hit[0]["fixable"] and hit[0]["manual_reason"]


def test_조항번호가_겹쳐도_영역별로_다른_표를_본다():
    """파일 '10-라'(날짜 정리)와 API '10-나'(연락처)는 번호만 비슷한 남남이다."""
    res = run({**GOOD_META, "담당자연락처": "0212345678"})
    d = res.to_dict()
    hit = [f for f in d["findings"] if f["rule_id"] == "10-나"][0]
    assert hit["fixable"] and hit["fix_label"] == "담당자 연락처 하이픈 정리"


# ---- 종합 -------------------------------------------------------------
def test_바른_등록정보는_반려가_없다():
    res = run(GOOD_META, spec_path=_json_file(SWAGGER))
    rejects = [f for f in res.findings if f.level is Level.REJECT]
    assert not rejects, [f"{f.rule_id} {f.message}" for f in rejects]


def test_결과에_구분과_명세요약이_담긴다():
    res, _ = check_api(GOOD_META, spec_path=_json_file(SWAGGER))
    d = res.to_dict()
    assert d["domain"] == "api"
    assert d["api"]["operations"] == 1
    assert d["api"]["ops"][0]["name_en"] == "getBikeList"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  FAIL  {name}: {exc}")
            except Exception as exc:                   # noqa: BLE001
                fails += 1
                print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print("\n실패 없음" if not fails else f"\n실패 {fails}건")
    sys.exit(1 if fails else 0)
