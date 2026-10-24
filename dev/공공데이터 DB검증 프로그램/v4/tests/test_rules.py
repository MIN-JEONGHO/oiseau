# -*- coding: utf-8 -*-
"""회귀 테스트: python -m pytest tests  또는  python tests/test_rules.py"""
from __future__ import annotations

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checker.engine import check                       # noqa: E402
from checker.fixer import (FIXABLE, NOT_FIXABLE_REASON,  # noqa: E402
                           fix_file, fixable_rules)
from checker.models import Level                        # noqa: E402


def _csv(rows, encoding="cp949", ext="csv"):
    fd, path = tempfile.mkstemp(suffix="." + ext)
    os.close(fd)
    with open(path, "w", encoding=encoding, newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path


GOOD = [
    ["기관명", "기준일자", "보관대수(대)", "연락처", "관리부서"],
    ["서울시 강남구", "2026-01-05", "120", "02-1234-5678", "교통행정과"],
    ["서울시 서초구", "2026-01-05", "95", "02-2345-6789", "교통행정과"],
    ["서울시 송파구", "2026-01-05", "210", "02-3456-7890", "도시교통과"],
    ["서울시 마포구", "2026-01-06", "88", "02-4567-8901", "교통행정과"],
    ["서울시 용산구", "2026-01-06", "64", "02-5678-9012", "교통행정과"],
]


def rule_ids(result):
    return {f.rule_id for f in result.findings}


def test_정상파일은_지적없음():
    res = check(_csv(GOOD), {"중복확인": "완료", "공공누리유형": "제1유형",
                             "데이터기준일": "2026-01-06"})
    assert res.verdict is Level.PASS, [f.message for f in res.findings]


def test_주요_위반이_모두_검출():
    rows = [r[:] for r in GOOD]
    rows[0][1] = "DATE"                    # 10-사 영문 항목명
    rows[0][2] = "면적(㎟)"                 # 10-바 특수문자
    rows[1][1] = "20260105"                # 10-라 날짜 표기
    rows[2][2] = "1,234"                   # 10-타 천단위 콤마
    rows[3][2] = "#VALUE!"                 # 10-거 수식오류
    rows[4][2] = "2.23453E+14"             # 10-하 지수표기
    rows[5][4] = "담당자 010-1234-5678"     # 10-머 개인정보
    rows.append(["합계", "", "577", "", ""])  # 10-다 집계행
    res = check(_csv(rows))
    assert {"10-사", "10-바", "10-라", "10-타", "10-거", "10-하", "10-머",
            "10-다"} <= rule_ids(res)


def test_최소규모_미달():
    res = check(_csv([["가", "나"], ["1", "2"]]))
    assert "13-가" in rule_ids(res)


def test_구분자와_인코딩():
    path = _csv(GOOD, encoding="utf-8")
    res = check(path)
    assert "10-러" in rule_ids(res)         # UTF-8 안내 필요

    fd, semi = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(semi, "w", encoding="cp949") as fh:
        fh.write("\n".join(";".join(r) for r in GOOD))
    assert "10-파" in rule_ids(check(semi))


def test_메타정보_검사():
    meta = {
        "목록명": "서울시_자전거 보관소 현황(2023년 12월)",   # 1-나
        "데이터명": "서울시_자전거보관소현황_20231231",        # 2-가
        "기관명": "서울시",
        "키워드": "자전거, 자전거 보관소, 자전거보관소",        # 3-다
        "설명": "짧은 설명입니다.",                          # 4-가
        "제공신청여부": "예",                                # 14-가 (제공번호 없음)
        "갱신주기": "월간",                                  # 16-가
    }
    ids = rule_ids(check(_csv(GOOD), meta))
    assert {"1-나", "2-가", "3-다", "4-가", "14-가", "16-가"} <= ids


def test_비개방형_확장자():
    fd, path = tempfile.mkstemp(suffix=".xls")
    os.close(fd)
    with open(path, "wb") as fh:
        fh.write(b"dummy")
    assert "9-다" in rule_ids(check(path))


# ---- 픽스 -------------------------------------------------------------
BAD = [
    ["기관명", "기준일자", "면적(㎟)", "전화번호", "금액", "", "비고"],
    ["※ 참고용 자료입니다. 활용 시 유의하시기 바랍니다.", "", "", "", "", "", ""],
    ["서울시", "20231231", "12.5", "0212345678", "1,234", "값", "<b>강조</b>"],
    ["부산시", "2023.05.01", "3.1", "051-123-4567", "2.23453E+14", "값", "줄바꿈\n포함"],
    ["대구시", "2023-06-01", "#VALUE!", "053-123-4567", "500", "값", "-"],
    ["인천시", "2023-07-01", "4.0", "032-111-2222", "700", "값", "담당 010-1234-5678"],
    ["합계", "", "19.6", "", "2434", "", ""],
]


def test_픽스_후_반려가_줄어든다():
    src = _csv(BAD)
    before = check(src)
    rules = sorted({f.rule_id for f in before.findings} & set(FIXABLE))
    out = os.path.join(tempfile.mkdtemp(), "fixed.csv")
    rep = fix_file(src, rules, out_path=out)
    assert not rep.error, rep.error
    after = check(out)
    assert after.counts()["반려"] < before.counts()["반려"]
    assert {"10-타", "10-하", "10-라", "10-서", "10-더", "10-거"} & set(rep.applied)
    assert rep.removed_rows == 2          # 주석 1행 + 합계 1행


def test_픽스는_선택한_조항만_적용():
    src = _csv(BAD)
    out = os.path.join(tempfile.mkdtemp(), "one.csv")
    rep = fix_file(src, ["10-타"], out_path=out)
    assert set(rep.applied) == {"10-타"}
    assert rep.encoding == "cp949"        # 원본 인코딩 유지
    text = open(out, encoding=rep.encoding).read()
    assert "1234" in text and "1,234" not in text
    assert "2.23453E+14" in text          # 선택하지 않은 조항은 그대로


def test_픽스_결과는_입력_형식을_유지():
    import json
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "d.json")
    with open(src, "w", encoding="utf-8") as fh:
        json.dump([{"기관명": "서울시", "금액": "1,234", "기준일자": "20260105"},
                   {"기관명": "부산시", "금액": "800", "기준일자": "2026-01-06"}],
                  fh, ensure_ascii=False)
    out = os.path.join(tmp, "d_fixed.json")
    rep = fix_file(src, ["10-타", "10-라"], out_path=out)
    assert not rep.error, rep.error
    data = json.load(open(out, encoding="utf-8"))
    assert isinstance(data, list) and data[0]["금액"] == "1234"
    assert data[0]["기준일자"] == "2026-01-05"


def test_JSON_파일도_검토된다():
    import json
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([{"기관명": "서울시", "금액": "1,234"}], fh, ensure_ascii=False)
    res = check(path)
    assert res.source_kind == "json" and "10-타" in rule_ids(res)


def test_자동수정_불가항목은_표시된다():
    d = check(_csv(BAD)).to_dict()
    by = {f["rule_id"]: f for f in d["findings"]}
    assert by["10-타"]["fixable"] and by["10-타"]["fix_label"]
    if "10-사" in by:
        assert not by["10-사"]["fixable"] and by["10-사"]["manual_reason"]


def test_빈값은_임의로_채우지_않는다():
    assert "10-자" not in FIXABLE                    # 빈 항목명 채우기 없음
    assert "10-아" not in FIXABLE                    # 빈 데이터값 채우기 없음
    assert "10-자" in NOT_FIXABLE_REASON

    rows = [r[:] for r in BAD]
    src = _csv(rows)
    out = os.path.join(tempfile.mkdtemp(), "keep.csv")
    rep = fix_file(src, sorted(FIXABLE), out_path=out)
    header = open(out, encoding=rep.encoding).readline().rstrip("\n").split(",")
    assert header[5] == "", "빈 항목명은 그대로 두어야 한다"


def test_서식과_내용_등급이_분리된다():
    tiers = {r["rule_id"]: r["tier"] for r in fixable_rules()}
    assert tiers["10-타"] == "서식" and tiers["10-라"] == "서식"
    assert tiers["10-다"] == "내용" and tiers["10-머"] == "내용"

    src = _csv(BAD)
    out = os.path.join(tempfile.mkdtemp(), "fmt.csv")
    fmt_rules = [k for k, v in FIXABLE.items() if v[1] == "서식"]
    rep = fix_file(src, fmt_rules, out_path=out)
    assert rep.removed_rows == 0, "서식 정리는 행을 지우지 않는다"
    text = open(out, encoding=rep.encoding).read()
    assert "합계" in text and "※" in text          # 내용 변경 대상은 그대로
    assert "1234" in text and "1,234" not in text  # 서식은 정리됨


def test_결과에_픽스_등급이_담긴다():
    d = check(_csv(BAD)).to_dict()
    by = {f["rule_id"]: f for f in d["findings"]}
    assert by["10-타"]["fix_tier"] == "서식"
    assert by["10-다"]["fix_tier"] == "내용"


# ---- 픽스 표기 정합성 (조항 번호 중복으로 인한 오표기 방지) -------------
def _all_findings():
    """여러 형태의 위반 파일에서 지적사항을 모아 온다."""
    out = []
    out += check(_csv(BAD)).findings
    out += check(_csv(BAD, encoding="utf-8")).findings          # 10-러
    out += check(_csv(GOOD)).findings
    semi = os.path.join(tempfile.mkdtemp(), "semi.csv")
    with open(semi, "w", encoding="cp949") as fh:               # 10-파
        fh.write("\n".join(";".join(r) for r in GOOD))
    out += check(semi).findings
    broken = os.path.join(tempfile.mkdtemp(), "b.csv")          # 17-다
    with open(broken, "wb") as fh:
        fh.write("기관명,값\n서울,정상\n".encode("cp949") + b"\xed\x95,\xb1\n")
    out += check(broken).findings
    return out


def test_픽스키가_없는_지적사항은_수정불가로_표시된다():
    for f in _all_findings():
        if f.fix_key:
            assert f.fix_key in FIXABLE, f"{f.rule_id}: 등록되지 않은 픽스키 {f.fix_key}"


def test_빈셀_지적사항은_픽스대상이_아니다():
    """10-차는 '하이픈 대체'와 '빈 셀'이 같은 조항을 쓰므로 분리되어야 한다."""
    rows = [r[:] for r in BAD]
    d = check(_csv(rows)).to_dict()
    blank = [f for f in d["findings"]
             if f["rule_id"] == "10-차" and "비어 있는" in f["message"]]
    hyphen = [f for f in d["findings"]
              if f["rule_id"] == "10-차" and "하이픈" in f["message"]]
    assert blank and not blank[0]["fixable"]
    assert "임의의 값으로 채우지 않습니다" in blank[0]["manual_reason"]
    assert hyphen and hyphen[0]["fixable"]
    assert hyphen[0]["fix_key"] == "10-차-하이픈"


def test_전화번호_지역번호_누락은_픽스대상이_아니다():
    d = check(_csv(BAD)).to_dict()
    by_msg = {f["message"]: f for f in d["findings"] if f["rule_id"] == "10-버"}
    for msg, f in by_msg.items():
        if "지역번호" in msg:
            assert not f["fixable"]
        if "하이픈" in msg:
            assert f["fixable"]


def test_선택한_픽스는_반드시_파일을_바꾼다():
    """픽스 가능으로 표시했는데 실제로는 아무것도 바뀌지 않는 경우를 막는다."""
    checked = set()
    for src, res in [(p, check(p)) for p in _fix_targets()]:
        for f in res.findings:
            if not f.fix_key or f.fix_key in checked:
                continue
            out = os.path.join(tempfile.mkdtemp(), "o" + os.path.splitext(src)[1])
            rep = fix_file(src, [f.fix_key], out_path=out)
            assert not rep.error, f"{f.fix_key}: {rep.error}"
            assert rep.applied or rep.removed_rows, \
                f"{f.fix_key}({f.rule_id})는 픽스 대상인데 변화가 없습니다"
            checked.add(f.fix_key)
    assert len(checked) >= 12, f"검증한 픽스 항목이 너무 적습니다: {sorted(checked)}"


def _fix_targets():
    paths = [_csv(BAD), _csv(BAD, encoding="utf-8")]
    semi = os.path.join(tempfile.mkdtemp(), "semi.csv")
    with open(semi, "w", encoding="cp949") as fh:
        fh.write("\n".join(";".join(r) for r in BAD))
    paths.append(semi)
    broken = os.path.join(tempfile.mkdtemp(), "b.csv")
    with open(broken, "wb") as fh:
        fh.write("기관명,값,비고\n".encode("cp949")
                 + "서울,1,정상\n부산,2,".encode("cp949") + b"\xed\x95\n")
    paths.append(broken)
    return paths


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
    print("\n실패 없음" if not fails else f"\n실패 {fails}건")
    sys.exit(1 if fails else 0)
