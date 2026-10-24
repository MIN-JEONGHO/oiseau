# -*- coding: utf-8 -*-
"""회귀 테스트: python -m pytest tests  또는  python tests/test_rules.py"""
from __future__ import annotations

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checker.engine import check          # noqa: E402
from checker.models import Level          # noqa: E402


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
