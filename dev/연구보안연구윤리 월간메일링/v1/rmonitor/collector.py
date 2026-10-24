# -*- coding: utf-8 -*-
"""이슈 수집 단계.

프롬프트 생성 → LLM(웹검색) 호출 → JSON 파싱/검증 → 정규화된 dict 반환.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from .llm import call_llm
from .profiles import COUNTRY_NAMES, ReportProfile
from .utils import Period, extract_json_object, is_valid_url

log = logging.getLogger("rmonitor")

ISSUE_FIELDS = ("country", "title_kr", "title_original", "org", "date",
                "category", "status", "content", "source_url", "sub_url", "sub_label")


def build_prompt(profile: ReportProfile, period: Period, base_dir: Path) -> str:
    """prompts/*.txt 를 읽어 날짜·카테고리 등을 치환한 최종 프롬프트를 만든다."""
    path = base_dir / profile.prompt_file
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 파일이 없습니다: {path}")
    text = path.read_text(encoding="utf-8")

    mapping = {
        "{{START_DATE}}": period.start_iso,
        "{{END_DATE}}": period.end_iso,
        "{{START_DATE_KR}}": period.start_kr,
        "{{END_DATE_KR}}": period.end_kr,
        "{{REPORT_DATE}}": period.report_date_iso,
        "{{REPORT_MONTH}}": period.report_month,
        "{{CATEGORIES}}": ", ".join(profile.categories),
        "{{STATUSES}}": ", ".join(profile.statuses),
        "{{MAX_ISSUE}}": str(profile.max_issue_per_country),
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text


def collect(profile: ReportProfile, period: Period, cfg: Dict[str, Any],
            base_dir: Path, logger: logging.Logger | None = None) -> Dict[str, Any]:
    """LLM 을 호출해 이슈 데이터를 수집한다."""
    logger = logger or log
    prompt = build_prompt(profile, period, base_dir)
    logger.info("[%s] 이슈 수집 시작 (%s ~ %s)", profile.name, period.start_iso, period.end_iso)

    raw = call_llm(prompt, cfg["llm"], logger=logger)

    # 디버깅용 원문 저장
    debug_path = Path(cfg.get("output_dir", "output")) / f"{profile.key}_{period.tag}_raw.txt"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(raw, encoding="utf-8")

    data = json.loads(extract_json_object(raw))
    data = normalize(data, profile, period, logger=logger)
    logger.info("[%s] 수집 완료: 이슈 %d건", profile.name, len(data["issues"]))
    return data


def normalize(data: Dict[str, Any], profile: ReportProfile, period: Period,
              logger: logging.Logger | None = None) -> Dict[str, Any]:
    """LLM 응답을 렌더러/엑셀이 기대하는 형태로 정리하고 최소 검증을 수행한다."""
    logger = logger or log
    out: Dict[str, Any] = {
        "report_key": profile.key,
        "report_month": str(data.get("report_month") or period.report_month),
        "period": {
            "start": period.start_iso, "end": period.end_iso,
            "start_kr": period.start_kr, "end_kr": period.end_kr,
            "report_date": period.report_date_iso,
        },
        "executive_summary": [],
        "issues": [],
        "no_issue_countries": {},
        "kr_other_trend": {"text": "", "url": ""},
        "analysis": {},
        "source_compliance_note": str(data.get("source_compliance_note") or "").strip(),
        "dropped": [],
    }

    for s in (data.get("executive_summary") or [])[:5]:
        s = str(s).strip()
        if s:
            out["executive_summary"].append(s)

    valid_countries = set(profile.countries) | {"KR"}
    if profile.has_intl_section:
        valid_countries.add("INTL")

    counts: Dict[str, int] = {}
    seen_urls = set()

    for raw_issue in (data.get("issues") or []):
        if not isinstance(raw_issue, dict):
            continue
        issue = {f: str(raw_issue.get(f) or "").strip() for f in ISSUE_FIELDS}
        country = issue["country"].upper()
        if country in ("USA", "U.S.", "US."):
            country = "US"
        if country in ("KOR", "KOREA", "SOUTH KOREA"):
            country = "KR"
        issue["country"] = country

        # --- 검증 ---
        if country not in valid_countries:
            out["dropped"].append(f"대상 외 국가코드({country}) - {issue['title_kr'][:40]}")
            continue
        if not issue["title_kr"]:
            out["dropped"].append("제목 없음 이슈 1건")
            continue
        if not is_valid_url(issue["source_url"]):
            out["dropped"].append(f"원문 URL 미확인 - {issue['title_kr'][:40]}")
            continue
        if issue["source_url"] in seen_urls:
            out["dropped"].append(f"중복 URL - {issue['title_kr'][:40]}")
            continue
        if not is_valid_url(issue["sub_url"]):
            issue["sub_url"] = ""
            issue["sub_label"] = ""
        if profile.categories and issue["category"] not in profile.categories:
            issue["category"] = issue["category"] or profile.categories[0]
        if profile.has_status and profile.statuses and issue["status"] not in profile.statuses:
            issue["status"] = issue["status"] or "정책 발표"

        cap = profile.max_issue_per_country
        if counts.get(country, 0) >= cap:
            out["dropped"].append(f"{country} 국가별 상한({cap}건) 초과 - {issue['title_kr'][:40]}")
            continue

        counts[country] = counts.get(country, 0) + 1
        seen_urls.add(issue["source_url"])
        out["issues"].append(issue)

    # 국가 표시 순서대로 정렬
    order = {c: i for i, c in enumerate(profile.countries + ["KR", "INTL"])}
    out["issues"].sort(key=lambda x: (order.get(x["country"], 99), x.get("date", "")))

    for code, note in (data.get("no_issue_countries") or {}).items():
        code = str(code).upper()
        if code in valid_countries and code not in counts:
            out["no_issue_countries"][code] = str(note).strip()
    # 응답에 누락된 무이슈 국가는 기본 문구로 보완
    default_note = ("이번 달 특이사항 없음 (신규 1차 발표 미확인)" if profile.key == "security"
                    else "이번 달 검증 가능한 신규 이슈 없음")
    for code in valid_countries:
        if code not in counts and code not in out["no_issue_countries"]:
            out["no_issue_countries"][code] = default_note

    kot = data.get("kr_other_trend") or {}
    if isinstance(kot, dict):
        out["kr_other_trend"] = {
            "text": str(kot.get("text") or "").strip(),
            "url": str(kot.get("url") or "").strip() if is_valid_url(kot.get("url")) else "",
        }

    analysis = data.get("analysis") or {}
    for key, _label in profile.analysis_items:
        out["analysis"][key] = str(analysis.get(key) or "").strip()

    if out["dropped"]:
        logger.warning("검증에서 제외된 항목 %d건: %s", len(out["dropped"]), "; ".join(out["dropped"][:5]))
    if not out["issues"]:
        logger.warning("검증을 통과한 이슈가 0건입니다. '특이사항 없음' 리포트로 발송됩니다.")
    return out


def issues_by_country(data: Dict[str, Any]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {c: [] for c in COUNTRY_NAMES}
    for issue in data["issues"]:
        grouped.setdefault(issue["country"], []).append(issue)
    return grouped
