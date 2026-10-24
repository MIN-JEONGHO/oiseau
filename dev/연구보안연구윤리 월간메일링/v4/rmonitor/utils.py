# -*- coding: utf-8 -*-
"""공통 유틸리티: 날짜 계산, 로깅, HTML 이스케이프."""
from __future__ import annotations

import calendar
import datetime as dt
import html
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))


# --------------------------------------------------------------------------
# 경로 — 소스 실행 / PyInstaller onefile exe 실행 모두 지원
# --------------------------------------------------------------------------
def resource_dir() -> Path:
    """읽기 전용 번들 리소스(prompts/*, ui/*, data 의 템플릿·샘플 등) 위치.

    onefile exe 는 실행할 때마다 임시 폴더(sys._MEIPASS)에 내용을 풀어 놓고 종료 시
    지워버리므로, 이 값에는 절대 쓰기(파일 생성)를 하면 안 된다 — 읽기 전용으로만 쓸 것.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """사용자 데이터(config.json / output / logs / history / 누적 엑셀) 저장 위치.

    onefile exe 로 실행 중이면 exe 파일이 있는 폴더(재실행해도 고정) — resource_dir() 과
    달리 임시 폴더가 아니어서 여기 쓴 내용은 다음 실행에도 그대로 남는다.
    소스(python run_cli.py 등)로 직접 실행 중이면 프로젝트 루트를 그대로 쓴다.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# 날짜/기간
# --------------------------------------------------------------------------
@dataclass
class Period:
    """리포트 수집 기간 정보."""

    start: dt.date          # 수집 시작일
    end: dt.date            # 수집 종료일
    report_date: dt.date    # 발행일
    mode: str = "monthly"   # "monthly" | "weekly"

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
    def iso_year_week(self) -> tuple[int, int]:
        """ISO 연/주차. 예: (2026, 36)"""
        y, w, _ = self.start.isocalendar()
        return y, w

    @property
    def mode_label(self) -> str:
        """예: '월간' / '주간'"""
        return "주간" if self.mode == "weekly" else "월간"

    @property
    def this_label(self) -> str:
        """무이슈 기본 문구 등에 쓰는 상대 표현. 예: '이번 달' / '이번 주'"""
        return "이번 주" if self.mode == "weekly" else "이번 달"

    @property
    def period_label(self) -> str:
        """리포트 표제용 기간 라벨(구 report_month).
        월간: '2026년 7월호'. 주간: '2026년 36주차 (9/1~9/7)'."""
        if self.mode == "weekly":
            _, wk = self.iso_year_week
            return (f"{self.start.year}년 {wk}주차 "
                    f"({self.start.month}/{self.start.day}~{self.end.month}/{self.end.day})")
        return f"{self.start.year}년 {self.start.month}월호"

    @property
    def tag(self) -> str:
        """파일명용 태그. 월간: 2026-07. 주간: 2026-W36 (충돌 없음)."""
        if self.mode == "weekly":
            y, wk = self.iso_year_week
            return f"{y}-W{wk:02d}"
        return self.start.strftime("%Y-%m")


def month_period(year: int, month: int, report_date: dt.date | None = None) -> Period:
    """지정한 연/월 1일~말일을 수집 기간으로 하는 Period 생성."""
    last_day = calendar.monthrange(year, month)[1]
    start = dt.date(year, month, 1)
    end = dt.date(year, month, last_day)
    if report_date is None:
        report_date = now_kst().date()
    return Period(start=start, end=end, report_date=report_date, mode="monthly")


def previous_month_period(today: dt.date | None = None) -> Period:
    """오늘 기준 '지난달' 전체를 수집 기간으로 하는 Period 생성."""
    today = today or now_kst().date()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - dt.timedelta(days=1)
    return month_period(last_month_end.year, last_month_end.month, report_date=today)


def week_period(year: int, week: int, report_date: dt.date | None = None) -> Period:
    """ISO 연/주차(월요일~일요일) 기준 Period 생성. 예: week_period(2026, 36)"""
    start = dt.date.fromisocalendar(year, week, 1)   # 월요일
    end = dt.date.fromisocalendar(year, week, 7)      # 일요일
    if report_date is None:
        report_date = now_kst().date()
    return Period(start=start, end=end, report_date=report_date, mode="weekly")


def previous_week_period(today: dt.date | None = None) -> Period:
    """오늘 기준 '지난주(월~일)' 전체를 수집 기간으로 하는 Period 생성."""
    today = today or now_kst().date()
    this_monday = today - dt.timedelta(days=today.weekday())
    last_monday = this_monday - dt.timedelta(days=7)
    return Period(start=last_monday, end=last_monday + dt.timedelta(days=6),
                  report_date=today, mode="weekly")


def parse_iso_week(text: str) -> tuple[int, int]:
    """'2026-W36' 또는 '2026-36' → (2026, 36). HTML5 <input type="week"> 출력과 호환."""
    t = text.strip().upper().replace("W", "-")
    parts = [p for p in t.split("-") if p]
    if len(parts) != 2:
        raise ValueError(f"주차 형식이 올바르지 않습니다: {text!r} (예: 2026-W36)")
    y, w = int(parts[0]), int(parts[1])
    return y, w


def resolve_period(mode: str, override: str | None = None,
                    today: dt.date | None = None) -> Period:
    """CLI/GUI 공용 기간 결정 진입점.

    mode     : "monthly" | "weekly"
    override : monthly="YYYY-MM", weekly="YYYY-Www". 없으면 이전 달/이전 주(자동).
    """
    if mode == "weekly":
        if override:
            y, w = parse_iso_week(override)
            return week_period(y, w, report_date=today)
        return previous_week_period(today)
    if override:
        y, m = (int(x) for x in override.split("-")[:2])
        return month_period(y, m, report_date=today)
    return previous_month_period(today)


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
