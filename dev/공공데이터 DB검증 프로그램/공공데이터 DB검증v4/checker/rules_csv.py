# -*- coding: utf-8 -*-
"""CSV 기준준수(10번) · 개방목록 일치(12번) · 최소규모(13번) · 기타 상세사유(17번) 검사."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import ColumnInfo, Finding, Level, Result
from .readers import cell_ref, trim_trailing_blank_rows

MAX_LOC = 5000         # 셀 지도·보고서에 담을 최대 좌표 수(화면 표기는 별도로 더 줄임)
BLANK_TOLERANCE = 5    # 공란 허용 한도 (5셀 미만 허용)

# ---- 패턴 ---------------------------------------------------------------
RE_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
RE_HEADER_OK = re.compile(r"^[가-힣A-Za-z0-9 _\-()]+$")
RE_FORMULA_ERR = re.compile(r"#(NAME\?|VALUE!|REF!|NULL!|DIV/0!|N/A|NUM!|SPILL!)", re.I)
RE_SCIENTIFIC = re.compile(r"^[+-]?\d(?:\.\d+)?[Ee][+-]?\d+$")
RE_THOUSAND_COMMA = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
RE_DATE_COMPACT = re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$")
RE_DATE_WRONG_SEP = re.compile(r"^(19|20)\d{2}[./]\d{1,2}[./]\d{1,2}$")
RE_TIME_SEMI = re.compile(r"^\d{1,2};\d{1,2}(;\d{1,2})?$")
RE_TIME_DOT = re.compile(r"^([01]?\d|2[0-3])\.[0-5]?\d\.[0-5]?\d$")
RE_DATE_OK = re.compile(r"(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
RE_PERIOD_VAGUE = re.compile(r"(^~|~$|이전까지|이후부터|\d{4}\s*년?\s*까지|까지$|부터$)")
RE_HTML = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>|&(nbsp|amp|lt|gt|quot|#\d+);")
RE_JUMIN = re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b")
RE_MOBILE = re.compile(r"\b01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}\b")
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
RE_PHONE_NOHYPHEN = re.compile(r"^0\d{8,10}$")
RE_PHONE_LOCALLESS = re.compile(r"^\d{3,4}-\d{4}$")
RE_NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
RE_UNIT_IN_NAME = re.compile(r"[(\[][^)\]]*[)\]]")
RE_CODE_LIKE = re.compile(r"^[A-Z]{1,4}[-_]?\d{2,}$")
RE_BAD_HEADER_CHARS = re.compile(r"[^가-힣A-Za-z0-9 _\-()]")

AGGREGATE_WORDS = ("소계", "합계", "총계", "총합", "전체", "평균", "누계", "소 계", "합 계")
COMMENT_MARKERS = ("※", "＊", "*", "#", "주)", "주석", "비고:", "출처:", "자료:", "註")
SENSITIVE_HEADERS = ("ip", "접속이력", "접속기록", "비밀번호", "password", "passwd",
                     "db명", "디비", "계정", "주민등록번호", "주민번호", "여권번호",
                     "운전면허", "카드번호", "계좌번호")
PHONE_HEADERS = ("전화", "연락처", "번호(전화", "tel", "phone", "팩스", "fax")
ENG_HEADER_ALLOW = ("cctv", "id", "url", "gps", "ip", "km", "kg", "x", "y", "no", "qr",
                    "api", "pdf", "utm", "wgs84", "rfid", "poi")


def _cap(items: List[str]) -> List[str]:
    return items[:MAX_LOC]


def _is_blank(v: Optional[str]) -> bool:
    return v is None or str(v).strip() == ""


def analyze_table(res: Result, rows: List[List[str]], text: str,
                  meta: Optional[Dict] = None) -> None:
    """표(1행 항목명 + 2행 이후 데이터) 형태 데이터를 전수 검사한다."""
    meta = meta or {}
    rows = trim_trailing_blank_rows([list(r) for r in rows])

    if not rows:
        res.error = "파일에 판독 가능한 내용이 없습니다."
        return

    header = [(c or "").strip() for c in rows[0]]
    data = rows[1:]
    res.rows = len(rows)
    res.cols = max((len(r) for r in rows), default=0)

    _check_header_structure(res, header, data)
    _check_header_names(res, header)
    cols = _profile_columns(res, header, data)
    res.columns = cols
    _check_cell_values(res, header, data, cols)
    _check_blanks(res, header, data, cols, meta)
    _check_aggregate_and_comment_rows(res, header, data)
    _check_minimum_size(res, header, data)
    _check_content_alignment(res, header, data, cols, meta)
    _check_units(res, cols, meta)
    res.suggested_base_date = _guess_base_date(rows)


# ---- 10-가 / 아 / 자 : 표 구조 -----------------------------------------
def _check_header_structure(res: Result, header: List[str], data: List[List[str]]) -> None:
    if all(_is_blank(h) for h in header):
        res.add(Finding(
            "10-가", "CSV 기준준수", Level.REJECT,
            "1행에 항목명(컬럼명)이 없습니다.",
            "1행에 항목명, 2행 이후에 데이터값을 배치해 저장하세요. 미충족 시 등록 불가입니다.",
            locations=["1행"]))
        return

    blank_head = []
    for i, h in enumerate(header):
        if not _is_blank(h):
            continue
        has_data = any(not _is_blank(r[i] if i < len(r) else "") for r in data)
        if has_data:
            blank_head.append(cell_ref(0, i))
    if blank_head:
        res.add(Finding(
            "10-자", "CSV 기준준수", Level.REJECT,
            f"항목명(컬럼명)이 비어 있는 열이 {len(blank_head)}개 있습니다. "
            "항목명 없이 데이터값만 존재하면 반려됩니다.",
            "해당 열에 항목명을 한글(영문) 형식으로 기재하세요.",
            locations=_cap(blank_head)))

    if not data:
        res.add(Finding(
            "10-아", "CSV 기준준수", Level.REJECT,
            "1행 항목명은 있으나 2행 이후 데이터값이 없습니다.",
            "데이터값을 채워 등록하세요. 항목이 반드시 있어야 하는 사유가 있다면 "
            "기타유의사항에 사유를 기재해 요청하세요.",
            locations=["2행"]))
        return

    empty_cols = []
    for i, h in enumerate(header):
        if _is_blank(h):
            continue
        if all(_is_blank(r[i] if i < len(r) else "") for r in data):
            empty_cols.append(f"{cell_ref(0, i)}({h})")
    if empty_cols:
        res.add(Finding(
            "10-아", "CSV 기준준수", Level.REJECT,
            f"항목명만 있고 데이터값이 전혀 없는 열이 {len(empty_cols)}개 있습니다.",
            "데이터값을 채우거나, 항목이 반드시 필요한 경우 기타유의사항에 사유를 기재하세요.",
            locations=_cap(empty_cols)))

    dup: Dict[str, List[str]] = {}
    for i, h in enumerate(header):
        if h:
            dup.setdefault(h, []).append(cell_ref(0, i))
    dups = [f"{k}({','.join(v)})" for k, v in dup.items() if len(v) > 1]
    if dups:
        res.add(Finding(
            "10-가", "CSV 기준준수", Level.ACTION,
            f"중복된 항목명이 있습니다: {', '.join(dups[:5])}",
            "항목명을 서로 구분되게 수정하세요.",
            samples=dups[:10]))

    ragged = [f"{i + 2}행({len(r)}열)" for i, r in enumerate(data)
              if len(r) != len(header)]
    if ragged:
        res.add(Finding(
            "10-파", "CSV 기준준수", Level.REJECT,
            f"항목명 열 수({len(header)})와 데이터 열 수가 다른 행이 {len(ragged)}개 있습니다.",
            "구분자로 콤마(,)만 사용하고, 값 안에 콤마가 있으면 큰따옴표로 묶어 저장하세요.",
            locations=_cap(ragged)))


# ---- 10-바 / 사 : 항목명 표기 ------------------------------------------
def _check_header_names(res: Result, header: List[str]) -> None:
    bad_char, eng_only = [], []
    for i, h in enumerate(header):
        if _is_blank(h):
            continue
        found = sorted(set(RE_BAD_HEADER_CHARS.findall(h)))
        if found:
            bad_char.append(f"{cell_ref(0, i)} {h} → {' '.join(found)}")
        if not RE_HANGUL.search(h):
            if h.strip().lower() not in ENG_HEADER_ALLOW:
                eng_only.append(f"{cell_ref(0, i)} {h}")

    if bad_char:
        res.add(Finding(
            "10-바", "CSV 기준준수", Level.REJECT,
            f"항목명에 허용되지 않는 특수문자가 있습니다({len(bad_char)}건). "
            "단위기호(㎟, ℃ 등), 점(.), 슬래시(/) 등은 사용할 수 없습니다.",
            "항목명에는 _(언더바), -(하이픈), (괄호)만 사용하세요. "
            "단위는 괄호로 표기하고 단위기호 대신 문자로 적으세요. 예: 면적(제곱미터)",
            locations=_cap([b.split()[0] for b in bad_char]), samples=bad_char[:10],
            fix_key="10-바"))

    if eng_only:
        res.add(Finding(
            "10-사", "CSV 기준준수", Level.ACTION,
            f"영문으로만 표기된 항목명이 {len(eng_only)}개 있습니다.",
            "한글(영문) 형태로 바꾸세요. 예: DATE → 날짜(DATE). "
            "영문 고유값이거나 코드북을 첨부하는 경우에는 예외 승인이 가능합니다.",
            locations=_cap([e.split()[0] for e in eng_only]), samples=eng_only[:10]))


# ---- 열 성격 프로파일 ---------------------------------------------------
def _profile_columns(res: Result, header: List[str],
                     data: List[List[str]]) -> List[ColumnInfo]:
    cols: List[ColumnInfo] = []
    for i, h in enumerate(header):
        vals = [(r[i] if i < len(r) else "") or "" for r in data]
        filled = [v.strip() for v in vals if v.strip() != ""]
        numeric = bool(filled) and all(
            RE_NUMERIC.match(v.replace(",", "")) or RE_SCIENTIFIC.match(v)
            or v == "-" for v in filled)
        cols.append(ColumnInfo(index=i, name=h,
                               empty_count=len(vals) - len(filled),
                               numeric_like=numeric))
    return cols


# ---- 10-라 ~ 서 : 셀 값 전수 검사 ---------------------------------------
def _check_cell_values(res: Result, header: List[str], data: List[List[str]],
                       cols: List[ColumnInfo]) -> None:
    hits: Dict[str, Tuple[List[str], List[str]]] = {}

    def hit(key: str, ref: str, sample: str) -> None:
        locs, samples = hits.setdefault(key, ([], []))
        locs.append(ref)
        if len(samples) < 8 and sample not in samples:
            samples.append(sample)

    header_lower = [h.lower() for h in header]

    for r_idx, row in enumerate(data):
        for c_idx, raw in enumerate(row):
            v = "" if raw is None else str(raw)
            if v == "":
                continue
            ref = cell_ref(r_idx + 1, c_idx)
            s = v.strip()
            hname = header_lower[c_idx] if c_idx < len(header_lower) else ""

            if "\n" in v or "\r" in v:
                hit("더", ref, s.replace("\n", "\\n")[:40])
            if "\ufffd" in v:
                hit("17-다", ref, s[:40])
            if "#" in s and RE_FORMULA_ERR.search(s):
                hit("거", ref, s[:40])

            has_digit = s[0].isdigit() or (len(s) > 1 and any(c.isdigit() for c in s[:24]))
            if has_digit:
                if ("E" in s or "e" in s) and RE_SCIENTIFIC.match(s):
                    hit("하", ref, s[:40])
                if "," in s and RE_THOUSAND_COMMA.match(s):
                    hit("타", ref, s[:40])
                if 8 <= len(s) <= 10 and (RE_DATE_COMPACT.match(s)
                                          or RE_DATE_WRONG_SEP.match(s)):
                    hit("라", ref, s[:40])
                elif ";" in s and RE_TIME_SEMI.match(s):
                    hit("라", ref, s[:40])
                elif "." in s and ("시간" in hname or "시각" in hname) \
                        and RE_TIME_DOT.match(s):
                    hit("라", ref, s[:40])

            if ("~" in s or "까지" in s or "부터" in s or "년" in s) \
                    and RE_PERIOD_VAGUE.search(s) and RE_DATE_OK.search(s) is None \
                    and ("기간" in hname or "년" in s or "~" in s):
                hit("마", ref, s[:40])
            if ("<" in s or "&" in s) and RE_HTML.search(s):
                hit("서", ref, s[:40])
            if ("@" in s and RE_EMAIL.search(s)) or (
                    has_digit and len(s) >= 10
                    and (RE_JUMIN.search(s) or RE_MOBILE.search(s))):
                hit("머", ref, re.sub(r"\d", "*", s)[:40])
            if "?" in s and not s.endswith("?"):
                hit("너", ref, s[:40])
            if has_digit and any(k in hname for k in PHONE_HEADERS):
                if RE_PHONE_NOHYPHEN.match(s):
                    hit("버-1", ref, s[:40])
                elif RE_PHONE_LOCALLESS.match(s):
                    hit("버-2", ref, s[:40])
            if s == "-":
                hit("차-2", ref, "-")

    # key -> (조항, 등급, 요약, 조치, 픽스키)  · 픽스키가 없으면 자동 수정 불가
    spec = {
        "더": ("10-더", Level.REJECT, "셀 안에 텍스트 줄바꿈이 있습니다",
               "엑셀에서 Ctrl+F → 찾을 내용에 Ctrl+J 입력 → 모두 찾기 후 "
               "바꾸기 탭에서 빈칸으로 모두 바꾸고 저장하세요.", "10-더"),
        "17-다": ("17-다", Level.REJECT, "글자가 깨진 값이 있습니다",
                  "원본 인코딩을 확인해 CP949 또는 UTF-8로 다시 저장하세요. "
                  "데이터가 깨져 보이면 반려 대상입니다.", "17-다"),
        "거": ("10-거", Level.REJECT, "수식 오류값(#NAME?, #VALUE! 등)이 있습니다",
               "메모장으로 파일을 열어 오류값을 실제 데이터값으로 수정하세요.", "10-거"),
        "하": ("10-하", Level.REJECT, "숫자가 지수 형태로 표기되어 있습니다",
               "예: 2.23453E+14 → 223453223324327. 셀 서식을 텍스트로 바꾼 뒤 "
               "전체 자릿수로 다시 저장하세요.", "10-하"),
        "타": ("10-타", Level.REJECT, "숫자의 천 단위를 콤마(,)로 구분했습니다",
               "천 단위 구분 콤마를 제거하세요. 예: 1,234 → 1234", "10-타"),
        "라": ("10-라", Level.REJECT, "날짜·시간 구분기호가 기준과 다릅니다",
               "날짜는 하이픈, 시간은 콜론으로 표기하세요. "
               "예: 20231231 → 2023-12-31, 10;8;30 → 10:08:30", "10-라"),
        "마": ("10-마", Level.REJECT, "기간이 범주화되어 시점이 불분명합니다",
               "시점을 정확히 적고 구분기호는 물결(~)을 쓰세요. "
               "예: ~2023년까지 → 2020-01-01~2023-12-31", ""),
        "서": ("10-서", Level.REJECT, "데이터값에 HTML 태그가 있습니다",
               "HTML 태그와 특수문자 엔티티를 제거한 순수 텍스트로 저장하세요.", "10-서"),
        "머": ("10-머", Level.REJECT, "개인정보로 보이는 값이 있습니다",
               "주민등록번호·휴대전화번호·이메일·개인 이름은 삭제하거나 "
               "비식별화 처리한 뒤 등록하세요.", "10-머"),
        "너": ("10-너", Level.REJECT, "의문형이 아닌 물음표(?)가 있습니다",
               "외래어·한자·특수문자가 깨져 생긴 물음표입니다. 엑셀에서 "
               "Ctrl+F → [ ~? ] 로 모두 찾아 바꾸기 탭에서 수정하세요.", ""),
        "버-1": ("10-버", Level.REJECT, "전화번호에 하이픈(-) 구분기호가 없습니다",
                 "전화번호는 지역번호를 포함하고 하이픈으로 구분하세요. "
                 "예: 0212345678 → 02-1234-5678", "10-버"),
        "버-2": ("10-버", Level.REJECT, "전화번호에 지역번호가 없습니다",
                 "지역번호를 포함해 기재하세요. 예: 1234-5678 → 02-1234-5678", ""),
        "차-2": ("10-차", Level.REJECT, "빈값을 하이픈(-)으로 채운 셀이 있습니다",
                 "문자는 빈값만 가능하며 하이픈 입력은 불가합니다. 하이픈을 지우고 "
                 "공란으로 두세요. 숫자는 빈값이 기본이나 0 입력이 가능합니다.",
                 "10-차-하이픈"),
    }

    for key, (locs, samples) in hits.items():
        rule_id, level, msg, fix, fix_key = spec[key]
        res.add(Finding(rule_id, "CSV 기준준수", level,
                        f"{msg} ({len(locs)}건).", fix,
                        locations=_cap(locs), samples=samples, count=len(locs),
                        fix_key=fix_key))


# ---- 10-차 / 카 : 공란 -------------------------------------------------
def _check_blanks(res: Result, header: List[str], data: List[List[str]],
                  cols: List[ColumnInfo], meta: Dict) -> None:
    blanks: List[str] = []
    for r_idx, row in enumerate(data):
        for c_idx in range(len(header)):
            v = row[c_idx] if c_idx < len(row) else ""
            if _is_blank(v):
                blanks.append(cell_ref(r_idx + 1, c_idx))
    if not blanks:
        return

    noted = _mentions_blank_reason(meta.get("기타유의사항", ""))
    if len(blanks) >= BLANK_TOLERANCE:
        level = Level.ACTION if not noted else Level.REVIEW
        res.add(Finding(
            "10-차", "CSV 기준준수", level,
            f"데이터값이 비어 있는 셀이 {len(blanks)}개입니다(5셀 이상).",
            "기타유의사항(한글)에 공란 사유를 기재하세요. 예: 데이터값이 공란인 부분은 "
            "미집계 데이터 또는 개인정보가 포함되어 공란 처리하였습니다."
            + (" (기타유의사항에 사유가 기재되어 있어 조건은 충족했습니다.)" if noted else ""),
            locations=_cap(blanks), count=len(blanks)))
    else:
        res.add(Finding(
            "10-카", "CSV 기준준수", Level.REVIEW,
            f"공란이 {len(blanks)}개 있습니다(5개 미만은 허용).",
            "그대로 등록 가능하나, 채울 수 있는 값이면 채우는 편이 좋습니다.",
            locations=_cap(blanks), count=len(blanks)))


def _mentions_blank_reason(note: str) -> bool:
    note = note or ""
    return any(k in note for k in ("공란", "빈값", "미집계", "결측"))


# ---- 10-나 / 다 : 주석·집계 행 ----------------------------------------
def _check_aggregate_and_comment_rows(res: Result, header: List[str],
                                      data: List[List[str]]) -> None:
    agg, comment = [], []
    for r_idx, row in enumerate(data):
        filled = [(v or "").strip() for v in row if (v or "").strip()]
        first = (row[0] or "").strip() if row else ""
        if any(w == v or v.startswith(w) for v in filled[:1] for w in AGGREGATE_WORDS) \
                or any(v in AGGREGATE_WORDS for v in filled):
            agg.append(f"{r_idx + 2}행 {first[:20]}")
        if first.startswith(COMMENT_MARKERS) or (len(filled) == 1 and len(first) > 25):
            comment.append(f"{r_idx + 2}행 {first[:20]}")

    if agg:
        res.add(Finding(
            "10-다", "CSV 기준준수", Level.REJECT,
            f'"소계·합계·전체·평균" 등 집계 행이 {len(agg)}개 있습니다.',
            "행에는 실 데이터만 남기고 집계 행을 삭제한 뒤 등록하세요.",
            locations=_cap([a.split("행")[0] + "행" for a in agg]),
            samples=agg[:8], count=len(agg), fix_key="10-다"))
    if comment:
        res.add(Finding(
            "10-나", "CSV 기준준수", Level.REJECT,
            f"주석으로 보이는 행이 {len(comment)}개 있습니다.",
            "CSV는 항목과 데이터로만 구성되어야 합니다. 주석은 삭제하고, "
            "필요한 설명은 기타유의사항에 기재하세요.",
            locations=_cap([c.split("행")[0] + "행" for c in comment]),
            samples=comment[:8], count=len(comment), fix_key="10-나"))


# ---- 13번 : 최소 규모 --------------------------------------------------
def _check_minimum_size(res: Result, header: List[str], data: List[List[str]]) -> None:
    n_cols = len([h for h in header if not _is_blank(h)])
    n_rows = len([r for r in data if any(not _is_blank(v) for v in r)])
    if n_cols < 3 or n_rows < 5:
        res.add(Finding(
            "13-가", "데이터 최소 요구사항", Level.REJECT,
            f"현재 규모는 {n_cols}열 × {n_rows}행입니다. 항목명 행을 제외하고 "
            "최소 3열·5행(값 15개) 이상이어야 합니다.",
            "데이터를 보강하세요. 최소기준을 충족할 수 없는 경우 기타유의사항에 "
            "적정 사유를 작성해야 하며, 증적자료 제출을 요청받을 수 있습니다. "
            "제공신청 데이터는 예외 승인됩니다."))


# ---- 12번 / 8번 : 개방목록-데이터 일치, 민감정보 -----------------------
def _check_content_alignment(res: Result, header: List[str], data: List[List[str]],
                             cols: List[ColumnInfo], meta: Dict) -> None:
    date_like_cols = 0
    code_cols: List[str] = []
    for c in cols:
        vals = [(r[c.index] if c.index < len(r) else "") or "" for r in data]
        filled = [v.strip() for v in vals if v.strip()]
        if not filled:
            continue
        if all(RE_DATE_OK.search(v) or RE_DATE_COMPACT.match(v) for v in filled):
            date_like_cols += 1
        elif all(RE_CODE_LIKE.match(v) for v in filled) and len(set(filled)) > 1:
            code_cols.append(f"{cell_ref(0, c.index)}({c.name})")

    real_cols = [c for c in cols if not _is_blank(c.name)]
    if real_cols and date_like_cols == len(real_cols):
        res.add(Finding(
            "12-마", "개방목록-데이터 일치", Level.REJECT,
            "데이터가 날짜로만 구성되어 있습니다.",
            "개방목록과 관련된 실제 내용 항목을 반드시 추가하세요."))

    if code_cols:
        res.add(Finding(
            "12-다", "개방목록-데이터 일치", Level.ACTION,
            f"코드로만 구성된 것으로 보이는 열이 있습니다: {', '.join(code_cols[:5])}",
            "코드를 해당하는 실제 내용으로 변환해 구성하거나, 코드로 올려야 하는 "
            "경우에는 코드북을 첨부하세요.",
            samples=code_cols[:10]))

    sens = [f"{cell_ref(0, i)}({h})" for i, h in enumerate(header)
            if any(k in h.lower() for k in SENSITIVE_HEADERS)]
    if sens:
        res.add(Finding(
            "12-나", "개방목록-데이터 일치", Level.REVIEW,
            f"개방에 적절하지 않을 수 있는 항목이 있습니다: {', '.join(sens[:5])}",
            "DB 정보, IP 접속이력 등 개방목록과 무관하거나 민감한 내용은 삭제하고 "
            "개방목록에 맞게 데이터를 구성하세요.",
            samples=sens[:10]))


# ---- 17-나 : 단위 표기 -------------------------------------------------
def _check_units(res: Result, cols: List[ColumnInfo], meta: Dict) -> None:
    note = meta.get("기타유의사항", "") or ""
    suspects = [f"{cell_ref(0, c.index)}({c.name})" for c in cols
                if c.numeric_like and c.name and not RE_UNIT_IN_NAME.search(c.name)
                and not any(k in c.name for k in ("번호", "연도", "년도", "코드", "순번", "ID", "id"))]
    if suspects and not any(k in note for k in ("단위", "㎡", "명", "원", "건")):
        res.add(Finding(
            "17-나", "기타 상세 사유", Level.REVIEW,
            f"숫자 항목인데 단위 표기가 없습니다: {', '.join(suspects[:5])}",
            "항목명에 단위를 괄호로 표기하거나, 기타유의사항에 데이터값의 단위를 기재하세요.",
            samples=suspects[:10]))


# ---- 11번 : 데이터 기준일 권고 ----------------------------------------
def _guess_base_date(rows: List[List[str]]) -> Optional[str]:
    """파일 내 날짜 중 가장 최근 날짜를 기준일 후보로 제시(11-나 ①②)."""
    found: List[str] = []
    for row in rows:
        for v in row:
            s = str(v or "")
            m = RE_DATE_OK.search(s)
            if m:
                found.append(m.group(0))
            elif RE_DATE_COMPACT.match(s.strip()):
                t = s.strip()
                found.append(f"{t[:4]}-{t[4:6]}-{t[6:8]}")
    return max(found) if found else None
