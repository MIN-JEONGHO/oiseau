# -*- coding: utf-8 -*-
"""픽스 엔진: 선택한 기준 조항만 자동 수정하고 원본과 같은 형식으로 저장한다."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional, Tuple

from .readers import (decode, detect_delimiter, detect_encoding, ext_of,
                      read_csv_text, read_json, read_xlsx, trim_trailing_blank_rows,
                      write_csv, write_json, write_xlsx)
from .rules_csv import (AGGREGATE_WORDS, COMMENT_MARKERS, RE_BAD_HEADER_CHARS,
                        RE_DATE_COMPACT, RE_DATE_WRONG_SEP, RE_EMAIL,
                        RE_FORMULA_ERR, RE_HTML, RE_JUMIN, RE_MOBILE,
                        RE_SCIENTIFIC, RE_THOUSAND_COMMA, RE_TIME_SEMI)

# 항목명에 쓸 수 없는 단위기호 → 한글 표기
UNIT_WORDS = {
    "㎟": "(제곱밀리미터)", "㎠": "(제곱센티미터)", "㎡": "(제곱미터)",
    "㎢": "(제곱킬로미터)", "㎥": "(세제곱미터)", "㎜": "(밀리미터)",
    "㎝": "(센티미터)", "㎞": "(킬로미터)", "㎏": "(킬로그램)", "㎎": "(밀리그램)",
    "㎖": "(밀리리터)", "ℓ": "(리터)", "℃": "(섭씨)", "℉": "(화씨)",
    "㎾": "(킬로와트)", "㏊": "(헥타르)", "%": "(퍼센트)", "‰": "(퍼밀)",
    "₩": "(원)", "￦": "(원)", "$": "(달러)", "㎧": "(초속미터)", "㎿": "(메가와트)",
}

# rule_id -> (표시명, 적용범위, 설명)
FIXABLE: Dict[str, Tuple[str, str, str]] = {
    "10-나": ("주석 행 삭제", "행", "주석으로 판단된 행을 제거합니다."),
    "10-다": ("집계 행 삭제", "행", "소계·합계·전체·평균 행을 제거합니다."),
    "10-라": ("날짜·시간 구분기호 정리", "셀", "20231231 → 2023-12-31, 10;8;30 → 10:08:30"),
    "10-바": ("항목명 특수문자 정리", "항목명", "단위기호는 한글로 바꾸고 나머지 특수문자는 제거합니다."),
    "10-자": ("빈 항목명 채우기", "항목명", "비어 있는 항목명을 항목1, 항목2로 채웁니다."),
    "10-차": ("하이픈 공란 비우기", "셀", "빈값 대체용 하이픈(-)을 공란으로 바꿉니다."),
    "10-타": ("천 단위 콤마 제거", "셀", "1,234 → 1234"),
    "10-파": ("구분자를 콤마로 변경", "파일", "저장할 때 콤마로 구분합니다."),
    "10-하": ("지수표기 펼치기", "셀", "2.23453E+14 → 223453000000000 (원본 자릿수 확인 필요)"),
    "10-거": ("수식 오류값 비우기", "셀", "#VALUE!, #REF! 등을 공란으로 바꿉니다."),
    "10-더": ("셀 안 줄바꿈 제거", "셀", "줄바꿈을 공백 한 칸으로 바꿉니다."),
    "10-러": ("엑셀 호환 인코딩으로 저장", "파일", "UTF-8(BOM)으로 저장해 엑셀에서 깨지지 않게 합니다."),
    "10-머": ("개인정보 비식별화", "셀", "주민등록번호·휴대전화번호·이메일을 마스킹합니다."),
    "10-버": ("전화번호 하이픈 정리", "셀", "0212345678 → 02-1234-5678"),
    "10-서": ("HTML 태그 제거", "셀", "태그와 특수문자 엔티티를 지웁니다."),
    "17-다": ("깨진 문자 제거", "셀", "인코딩 손상으로 생긴 문자를 지웁니다."),
}

# 자동 수정이 불가한 조항 → 사람이 판단해야 하는 이유
NOT_FIXABLE_REASON = {
    "10-너": "원래 글자를 알 수 없어 사람이 확인해야 합니다.",
    "10-사": "적절한 한글 항목명은 담당자가 정해야 합니다.",
    "10-아": "데이터값 자체가 없어 채울 수 없습니다.",
    "10-카": "공란 사유는 기타유의사항에 직접 기재해야 합니다.",
    "13-가": "데이터 보강은 자동화할 수 없습니다.",
}

RE_PHONE_DIGITS = re.compile(r"^0\d{8,10}$")
RE_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>")
RE_ENTITY = re.compile(r"&(nbsp|amp|lt|gt|quot|#\d+);")
SEOUL_LIKE = ("02",)


@dataclass
class FixReport:
    out_path: str = ""
    encoding: str = ""
    applied: Dict[str, int] = field(default_factory=dict)   # rule_id -> 수정 건수
    removed_rows: int = 0
    skipped: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict:
        return {"out_path": self.out_path, "encoding": self.encoding,
                "applied": [{"rule_id": k, "label": FIXABLE[k][0], "count": v}
                            for k, v in self.applied.items() if v],
                "removed_rows": self.removed_rows, "skipped": self.skipped,
                "error": self.error}


# ---- 셀 단위 변환 ------------------------------------------------------
def _fix_date(v: str) -> str:
    s = v.strip()
    if RE_DATE_COMPACT.match(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if RE_DATE_WRONG_SEP.match(s):
        y, m, d = re.split(r"[./]", s)
        return f"{y}-{int(m):02d}-{int(d):02d}"
    if RE_TIME_SEMI.match(s):
        parts = [int(p) for p in s.split(";")]
        while len(parts) < 3:
            parts.append(0)
        return "{:02d}:{:02d}:{:02d}".format(*parts)
    return v


def _fix_scientific(v: str) -> str:
    s = v.strip()
    if not RE_SCIENTIFIC.match(s):
        return v
    try:
        d = Decimal(s)
    except InvalidOperation:
        return v
    txt = format(d, "f")
    return txt.rstrip("0").rstrip(".") if "." in txt else txt


def _fix_comma(v: str) -> str:
    return v.replace(",", "") if RE_THOUSAND_COMMA.match(v.strip()) else v


def _fix_html(v: str) -> str:
    return RE_ENTITY.sub(" ", RE_TAG.sub("", v)).strip()


def _fix_newline(v: str) -> str:
    return re.sub(r"\s*[\r\n]+\s*", " ", v).strip()


def _fix_formula(v: str) -> str:
    return "" if RE_FORMULA_ERR.search(v.strip()) else v


def _fix_hyphen(v: str) -> str:
    return "" if v.strip() == "-" else v


def _fix_broken(v: str) -> str:
    return v.replace("�", "")


def _mask_jumin(m: re.Match) -> str:
    d = re.sub(r"\D", "", m.group(0))
    return f"{d[:6]}-{d[6]}{'*' * 6}"


def _mask_mobile(m: re.Match) -> str:
    d = re.sub(r"\D", "", m.group(0))
    mid = "*" * (len(d) - 7)
    return f"{d[:3]}-{mid}-{d[-4:]}"


def _fix_privacy(v: str) -> str:
    v = RE_JUMIN.sub(_mask_jumin, v)
    v = RE_MOBILE.sub(_mask_mobile, v)
    v = RE_EMAIL.sub(lambda m: m.group(0)[0] + "***@" + m.group(0).split("@")[1], v)
    return v


def _fix_phone(v: str) -> str:
    s = v.strip()
    if not RE_PHONE_DIGITS.match(s):
        return v
    if s.startswith(SEOUL_LIKE):
        head, rest = s[:2], s[2:]
    else:
        head, rest = s[:3], s[3:]
    if len(rest) < 7:
        return v
    return f"{head}-{rest[:-4]}-{rest[-4:]}"


CELL_FIXERS: Dict[str, Callable[[str], str]] = {
    "10-라": _fix_date, "10-하": _fix_scientific, "10-타": _fix_comma,
    "10-서": _fix_html, "10-더": _fix_newline, "10-거": _fix_formula,
    "10-차": _fix_hyphen, "17-다": _fix_broken, "10-머": _fix_privacy,
    "10-버": _fix_phone,
}


# ---- 항목명·행 단위 -----------------------------------------------------
def _fix_header_name(name: str) -> str:
    out = name
    for sym, word in UNIT_WORDS.items():
        bare = word.strip("()")
        out = out.replace(f"({sym})", f"({bare})").replace(f"[{sym}]", f"({bare})")
        out = out.replace(sym, word)
    out = RE_BAD_HEADER_CHARS.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return re.sub(r"\)\(", ")(", out)


def _is_comment_row(row: List[str]) -> bool:
    filled = [(v or "").strip() for v in row if (v or "").strip()]
    first = (row[0] or "").strip() if row else ""
    return bool(first.startswith(COMMENT_MARKERS)
                or (len(filled) == 1 and len(first) > 25))


def _is_aggregate_row(row: List[str]) -> bool:
    filled = [(v or "").strip() for v in row if (v or "").strip()]
    if not filled:
        return False
    first = filled[0]
    return any(first == w or first.startswith(w) for w in AGGREGATE_WORDS) \
        or any(v in AGGREGATE_WORDS for v in filled)


# ---- 실행 --------------------------------------------------------------
def fixable_rules() -> List[Dict[str, str]]:
    return [{"rule_id": k, "label": v[0], "scope": v[1], "note": v[2]}
            for k, v in FIXABLE.items()]


def default_out_path(path: str, suffix: str = "_수정") -> str:
    root, ext = os.path.splitext(path)
    return f"{root}{suffix}{ext}"


def fix_file(path: str, rule_ids: List[str], out_path: Optional[str] = None,
             suffix: str = "_수정") -> FixReport:
    """선택한 조항만 적용해 수정본을 저장한다. 형식·확장자는 원본을 따른다."""
    rep = FixReport()
    rules = [r for r in rule_ids if r in FIXABLE]
    rep.skipped = [r for r in rule_ids if r not in FIXABLE]
    if not rules:
        rep.error = "자동 수정이 가능한 항목이 선택되지 않았습니다."
        return rep

    ext = ext_of(path)
    out_path = out_path or default_out_path(path, suffix)
    root_key, encoding, delimiter = "", "utf-8-sig", ","

    # 1) 판독
    if ext in {"csv", "tsv", "txt"}:
        encoding, raw = detect_encoding(path)
        text = decode(raw, encoding if encoding != "unknown" else "utf-8")
        delimiter = "\t" if ext == "tsv" else detect_delimiter(text)
        rows = read_csv_text(text, delimiter=delimiter)
    elif ext in {"xlsx", "xlsm"}:
        rows, _sheets = read_xlsx(path)
    elif ext == "json":
        rows, encoding, info = read_json(path)
        if not info.get("table"):
            rep.error = "객체 배열 구조가 아니어서 자동 수정을 적용할 수 없습니다."
            return rep
        root_key = info.get("root_key", "")
    else:
        rep.error = f"{ext.upper()} 형식은 자동 수정을 지원하지 않습니다."
        return rep

    rows = trim_trailing_blank_rows([list(r) for r in rows])
    if not rows:
        rep.error = "수정할 내용이 없습니다."
        return rep

    counts = {r: 0 for r in rules}

    # 2) 항목명
    header = list(rows[0])
    if "10-바" in rules:
        for i, h in enumerate(header):
            new = _fix_header_name(h or "")
            if new != (h or ""):
                header[i] = new
                counts["10-바"] += 1
    if "10-자" in rules:
        n = 0
        for i, h in enumerate(header):
            if not (h or "").strip():
                n += 1
                header[i] = f"항목{n}"
                counts["10-자"] += 1

    # 3) 행 삭제
    body = rows[1:]
    keep: List[List[str]] = []
    for row in body:
        if "10-다" in rules and _is_aggregate_row(row):
            counts["10-다"] += 1
            continue
        if "10-나" in rules and _is_comment_row(row):
            counts["10-나"] += 1
            continue
        keep.append(list(row))
    rep.removed_rows = len(body) - len(keep)

    # 4) 셀 값
    cell_rules = [r for r in rules if r in CELL_FIXERS]
    for row in keep:
        for i, v in enumerate(row):
            if v is None or v == "":
                continue
            new = str(v)
            for r in cell_rules:
                changed = CELL_FIXERS[r](new)
                if changed != new:
                    counts[r] += 1
                    new = changed
            if new != str(v):
                row[i] = new

    out_rows = [header] + keep

    # 5) 저장 (형식 유지)
    if ext == "json":
        write_json(out_rows, out_path, encoding="utf-8", root_key=root_key)
        rep.encoding = "utf-8"
    elif ext in {"xlsx", "xlsm"}:
        write_xlsx(out_rows, out_path)
        rep.encoding = "-"
    else:
        out_delim = "," if ("10-파" in rules or ext == "csv") else delimiter
        out_enc = "utf-8-sig" if "10-러" in rules else (
            encoding if encoding not in ("unknown",) else "utf-8-sig")
        rep.encoding = write_csv(out_rows, out_path, encoding=out_enc,
                                 delimiter=out_delim)
        if "10-파" in rules and out_delim == ",":
            counts["10-파"] = 1 if delimiter != "," else 0
        if "10-러" in rules:
            counts["10-러"] = 1

    rep.out_path = out_path
    rep.applied = {k: v for k, v in counts.items() if v}
    return rep
