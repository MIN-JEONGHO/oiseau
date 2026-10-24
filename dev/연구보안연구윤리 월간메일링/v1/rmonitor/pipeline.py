# -*- coding: utf-8 -*-
"""전체 파이프라인: 수집 → 렌더링 → 발송 → 엑셀 누적."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import collector, excel_log, mailer, renderer
from .config import sender_address
from .profiles import get_profile
from .utils import Period, now_kst

log = logging.getLogger("rmonitor")


def run_report(report_key: str,
               period: Period,
               cfg: Dict[str, Any],
               base_dir: Path,
               *,
               send_mail: bool = True,
               write_excel: bool = True,
               data_file: Optional[str] = None,
               confirm: Optional[Callable[[Dict[str, Any]], bool]] = None,
               logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """리포트 1종을 처리한다.

    data_file : 이미 수집된 JSON 을 재사용할 때 경로 지정(재발송·테스트용)
    confirm   : 발송 직전 호출되는 콜백. False 를 반환하면 발송을 건너뛴다.
    """
    logger = logger or log
    profile = get_profile(report_key)
    out_dir = base_dir / cfg.get("output_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {"report": report_key, "name": profile.name,
                              "sent": False, "excel": None, "issue_count": 0}

    # 1) 수집 -------------------------------------------------------------
    if data_file:
        logger.info("[%s] 기존 데이터 파일 사용: %s", profile.name, data_file)
        raw = json.loads(Path(data_file).read_text(encoding="utf-8"))
        data = collector.normalize(raw, profile, period, logger=logger) \
            if "period" not in raw else raw
    else:
        data = collector.collect(profile, period, cfg, base_dir, logger=logger)

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

    # 3) 발송 -------------------------------------------------------------
    rcfg = cfg.get("reports", {}).get(report_key, {})
    recipients = rcfg.get("recipients") or []
    result["recipients"] = recipients

    if send_mail:
        if confirm is not None and not confirm({**result, "profile": profile}):
            logger.info("[%s] 사용자가 발송을 취소했습니다.", profile.name)
        elif not recipients:
            logger.warning("[%s] 수신자가 없어 발송을 건너뜁니다.", profile.name)
        else:
            msg = mailer.build_message(
                subject=subject,
                html_body=body_html,
                sender=sender_address(cfg),
                sender_name=cfg["smtp"].get("sender_name", ""),
                to=recipients,
                cc=rcfg.get("cc", []),
                bcc=rcfg.get("bcc", []),
            )
            mailer.send(msg, cfg["smtp"], logger=logger)
            result["sent"] = True
            result["sent_at"] = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    else:
        logger.info("[%s] 발송 없이 미리보기만 생성했습니다.", profile.name)

    # 4) 엑셀 누적 --------------------------------------------------------
    if write_excel:
        excel_cfg = dict(cfg["excel"])
        excel_cfg["path"] = str(base_dir / excel_cfg["path"])
        if excel_cfg.get("template"):
            excel_cfg["template"] = str(base_dir / excel_cfg["template"])
        result["excel"] = excel_log.append_issues(data, excel_cfg, logger=logger)

    return result


def run_all(report_keys, period: Period, cfg: Dict[str, Any], base_dir: Path, **kwargs):
    results = []
    for key in report_keys:
        try:
            results.append(run_report(key, period, cfg, base_dir, **kwargs))
        except Exception as exc:  # noqa: BLE001
            (kwargs.get("logger") or log).error("[%s] 처리 실패: %s", key, exc, exc_info=True)
            results.append({"report": key, "error": str(exc), "sent": False})
    return results
