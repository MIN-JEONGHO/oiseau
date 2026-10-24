# -*- coding: utf-8 -*-
"""회귀 테스트: python -m pytest tests  또는  python tests/test_rules.py"""
from __future__ import annotations

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checker.engine import check                       # noqa: E402
from checker.fixer import FIXABLE, fix_file             # noqa: E402
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
