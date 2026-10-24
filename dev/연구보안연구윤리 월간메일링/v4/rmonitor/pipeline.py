# -*- coding: utf-8 -*-
"""전체 파이프라인: 수집 → 렌더링 → 엑셀 누적 → 이력 기록.

v3 부터 메일 발송 단계는 없다(사내 권한 문제로 제거). HTML 리포트는 항상
`output/<key>_<tag>.html` 로 저장되며, 실행 결과는 `history.py` 를 통해
`history/history.jsonl` 에 감사 기록으로 남는다.

경로는 두 종류로 나뉜다(exe로 패키징했을 때도 안전하게 동작하도록):
  resource_dir : 읽기 전용 번들 리소스(prompts/*.txt, 엑셀 템플릿 등)
  app_dir      : 쓰기 가능한 사용자 데이터(output/logs/history/누적 엑셀 등)
소스로 직접 실행할 때는 둘 다 프로젝트 루트로 같다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from . import collector, excel_log, history, renderer
from .profiles import get_profile
from .utils import Period

log = logging.getLogger("rmonitor")


def run_report(report_key: str,
               period: Period,
               cfg: Dict[str, Any],
               app_dir: Path,
               resource_dir: Path,
               *,
               write_excel: bool = True,
               data_file: Optional[str] = None,
               logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """리포트 1종을 처리한다.

    data_file : 이미 수집된 JSON 을 재사용할 때 경로 지정(재생성·테스트용)
    """
    logger = logger or log
    profile = get_profile(report_key)
    out_dir = app_dir / cfg.get("output_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {"report": report_key, "name": profile.name,
                              "period_mode": period.mode, "excel": None, "issue_count": 0}

    # 1) 수집 -------------------------------------------------------------
    if data_file:
        logger.info("[%s] 기존 데이터 파일 사용: %s", profile.name, data_file)
        raw = json.loads(Path(data_file).read_text(encoding="utf-8"))
        data = collector.normalize(raw, profile, period, logger=logger) \
            if "period" not in raw else raw
    else:
        data = collector.collect(profile, period, cfg, resource_dir, app_dir, logger=logger)

    result["issue_count"] = len(data["issues"])
    result["dropped"] = data.get("dropped", [])

    json_path = out_dir / f"{profile.key}_{period.tag}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    result["json_path"] = str(json_path)

    # 2) 렌더링 -----------------------------------------------------------
    body_html = renderer.render(profile, data)
    subject = renderer.build_subject(profile, data)
    result["subject"] = subject

    html_path = out_dir / f"{profile.key}_{period.tag}.html"
    html_path.write_text(renderer.wrap_full_document(body_html, subject), encoding="utf-8")
    result["html_path"] = str(html_path)
    logger.info("[%s] HTML 생성 완료: %s", profile.name, html_path)

    # 3) 엑셀 누적 --------------------------------------------------------
    if write_excel:
        excel_cfg = dict(cfg["excel"])
        excel_cfg["path"] = str(app_dir / excel_cfg["path"])           # 쓰기 가능한 위치
        if excel_cfg.get("template"):
            excel_cfg["template"] = str(resource_dir / excel_cfg["template"])  # 읽기 전용 번들
        result["excel"] = excel_log.append_issues(data, excel_cfg, logger=logger)

    # 4) 이력 기록 --------------------------------------------------------
    result["history"] = history.record_run(result, period, profile, cfg, app_dir, status="success")

    return result


def run_all(report_keys, period: Period, cfg: Dict[str, Any],
           app_dir: Path, resource_dir: Path, **kwargs):
    results = []
    for key in report_keys:
        try:
            results.append(run_report(key, period, cfg, app_dir, resource_dir, **kwargs))
        except Exception as exc:  # noqa: BLE001
            (kwargs.get("logger") or log).error("[%s] 처리 실패: %s", key, exc, exc_info=True)
            history.record_error(key, period, cfg, app_dir, str(exc))
            results.append({"report": key, "error": str(exc)})
    return results
