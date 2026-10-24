# -*- coding: utf-8 -*-
"""공통 유틸리티: 날짜 계산, 로깅, HTML 이스케이프."""
from __future__ import annotations

import calendar
import datetime as dt
import html
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))


# --------------------------------------------------------------------------
# 날짜/기간
# --------------------------------------------------------------------------
@dataclass
class Period:
    """리포트 수집 기간 정보."""

    start: dt.date          # 수집 시작일
    end: dt.date            # 수집 종료일
    report_date: dt.date    # 발행일

    @property
    def start_iso(self) -> str:
        return self.start.strftime("%Y-%m-%d")

    @property
    def end_iso(self) -> str:
        return self.end.strftime("%Y-%m-%d")

    @property
    def report_date_iso(self) -> str:
        return self.report_date.strftime("%Y-%m-%d")

    @property
    def start_kr(self) -> str:
        return f"{self.start.year}년 {self.start.month}월 {self.start.day}일"

    @property
    def end_kr(self) -> str:
        return f"{self.end.year}년 {self.end.month}월 {self.end.day}일"

    @property
    def report_month(self) -> str:
        """예: '2026년 7월호' (수집 대상 월 기준)."""
        return f"{self.start.year}년 {self.start.month}월호"

    @property
    def tag(self) -> str:
        """파일명용 태그. 예: 2026-07"""
        return self.start.strftime("%Y-%m")


def month_period(year: int, month: int, report_date: dt.date | None = None) -> Period:
    """지정한 연/월 1일~말일을 수집 기간으로 하는 Period 생성."""
    last_day = calendar.monthrange(year, month)[1]
    start = dt.date(year, month, 1)
    end = dt.date(year, month, last_day)
    if report_date is None:
        report_date = now_kst().date()
    return Period(start=start, end=end, report_date=report_date)


def previous_month_period(today: dt.date | None = None) -> Period:
    """오늘 기준 '지난달' 전체를 수집 기간으로 하는 Period 생성(기본값)."""
    today = today or now_kst().date()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - dt.timedelta(days=1)
    return month_period(last_month_end.year, last_month_end.month, report_date=today)


def now_kst() -> dt.datetime:
    return dt.datetime.now(tz=KST)


# --------------------------------------------------------------------------
# 로깅
# --------------------------------------------------------------------------
def setup_logger(log_dir: str | os.PathLike = "logs", name: str = "rmonitor") -> logging.Logger:
    """콘솔 + 파일 동시 출력 로거."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:  # 중복 등록 방지
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    logfile = Path(log_dir) / f"{name}_{now_kst():%Y%m}.log"
    fileh = logging.FileHandler(logfile, encoding="utf-8")
    fileh.setFormatter(fmt)
    logger.addHandler(fileh)
    return logger


class CallbackHandler(logging.Handler):
    """GUI 로그창 등 외부로 로그를 흘려보내기 위한 핸들러."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", "%H:%M:%S"))

    def emit(self, record):  # pragma: no cover - GUI 전용
        try:
            self.callback(self.format(record))
        except Exception:
            pass


# --------------------------------------------------------------------------
# 문자열/HTML
# --------------------------------------------------------------------------
def esc(value) -> str:
    """HTML 본문 삽입용 이스케이프."""
    if value is None:
        return ""
    return html.escape(str(value).strip(), quote=True)


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def esc_inline(value) -> str:
    """이스케이프 후 **강조** 만 <b> 로 허용한다(그 외 태그는 모두 무력화)."""
    return _BOLD_RE.sub(r"<b>\1</b>", esc(value))


_URL_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def is_valid_url(url) -> bool:
    """형식상 사용 가능한 http(s) URL인지 검사."""
    if not url:
        return False
    return bool(_URL_RE.match(str(url).strip()))


def safe_url(url) -> str:
    """href 속성에 넣을 수 있도록 정제. 형식이 틀리면 빈 문자열."""
    url = (str(url).strip() if url else "")
    return html.escape(url, quote=True) if is_valid_url(url) else ""


def strip_code_fence(text: str) -> str:
    """```json ... ``` 코드펜스 제거."""
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def extract_json_object(text: str) -> str:
    """응답 텍스트에서 최상위 JSON 객체만 잘라낸다."""
    t = strip_code_fence(text)
    start = t.find("{")
    if start == -1:
        raise ValueError("응답에서 JSON 객체를 찾지 못했습니다.")
    depth, in_str, escape = 0, False, False
    for i, ch in enumerate(t[start:], start=start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    raise ValueError("JSON 객체가 완결되지 않았습니다(응답이 잘렸을 수 있습니다).")
