# -*- coding: utf-8 -*-
"""명령줄 실행 진입점 (윈도우 작업 스케줄러 등록용).

예)
  python run_cli.py                                  # 기본 기간모드(config.json) 기준 자동 실행
  python run_cli.py --period-mode monthly            # 지난달 기준, 활성화된 리포트 전부 수집
  python run_cli.py --period-mode weekly              # 지난주(월~일) 기준
  python run_cli.py --report security                # 연구보안만
  python run_cli.py --period-mode monthly --month 2026-07   # 특정 월
  python run_cli.py --period-mode weekly --week 2026-W27    # 특정 주(ISO)
  python run_cli.py --data output/security_2026-07.json --report security
  python run_cli.py --open                            # 생성 후 HTML을 브라우저로 열기
  python run_cli.py --history-report output/이력.xlsx  # 수집 없이 이력 엑셀만 생성
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from rmonitor import history
from rmonitor.config import load_config
from rmonitor.pipeline import run_all
from rmonitor.utils import app_dir, resolve_period, resource_dir, setup_logger

# app_dir(쓰기 가능: config/output/logs/history) 와 resource_dir(읽기 전용: prompts 등) 를
# 분리해 두면, 나중에 이 CLI 도 exe로 패키징하더라도 그대로 안전하게 동작한다.
# 소스로 직접 실행할 때는 둘 다 이 파일이 있는 폴더로 같다.
APP_DIR = app_dir()
RESOURCE_DIR = resource_dir()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="연구보안·연구윤리 리포트 자동 생성")
    ap.add_argument("--config", default=str(APP_DIR / "config.json"))
    ap.add_argument("--report", choices=["security", "ethics", "all"], default="all")
    ap.add_argument("--period-mode", choices=["monthly", "weekly"], default=None,
                    help="미지정 시 config.json 의 period.mode 값을 사용")
    ap.add_argument("--month", help="월간 모드 수동 지정 (YYYY-MM). 미지정 시 지난달")
    ap.add_argument("--week", help="주간 모드 수동 지정 (YYYY-Www, 예: 2026-W36). 미지정 시 지난주")
    ap.add_argument("--no-excel", action="store_true", help="엑셀 누적 기록을 하지 않는다")
    ap.add_argument("--data", help="이미 수집된 JSON 파일로 재렌더링")
    ap.add_argument("--open", action="store_true", help="생성된 HTML을 기본 브라우저로 연다")
    ap.add_argument("--history-report", metavar="OUTPUT.xlsx", nargs="?", const="",
                    help="리포트를 생성하지 않고 history.jsonl 기반 엑셀 이력 보고서만 만든다")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    logger = setup_logger(APP_DIR / cfg.get("log_dir", "logs"))

    if args.history_report is not None:
        out = args.history_report or str(
            APP_DIR / cfg.get("output_dir", "output") /
            f"이력보고서_{__import__('datetime').datetime.now():%Y%m%d_%H%M%S}.xlsx")
        try:
            path = history.export_history_excel(APP_DIR, cfg, out)
            logger.info("이력 엑셀 보고서 생성: %s", path)
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.error("이력 보고서 생성 실패: %s", exc)
            return 1

    mode = args.period_mode or cfg.get("period", {}).get("mode", "monthly")
    override = args.week if mode == "weekly" else args.month
    period = resolve_period(mode, override)

    if args.report == "all":
        keys = [k for k, v in cfg["reports"].items() if v.get("enabled", True)]
    else:
        keys = [args.report]

    if not keys:
        logger.error("실행할 리포트가 없습니다. config.json 의 reports.*.enabled 를 확인하세요.")
        return 1

    logger.info("=" * 70)
    logger.info("기간모드: %s / 대상: %s (%s ~ %s) / 리포트: %s",
                period.mode_label, period.period_label, period.start_iso, period.end_iso,
                ", ".join(keys))

    results = run_all(keys, period, cfg, APP_DIR, RESOURCE_DIR,
                      write_excel=not args.no_excel,
                      data_file=args.data,
                      logger=logger)

    failed = 0
    for r in results:
        if r.get("error"):
            failed += 1
            logger.error("· %s : 실패 - %s", r["report"], r["error"])
        else:
            excel = r.get("excel") or {}
            logger.info("· %s : 이슈 %d건 / 엑셀 %s건 추가 / %s",
                        r.get("name", r["report"]), r.get("issue_count", 0),
                        excel.get("added", 0), r.get("html_path", ""))
            if args.open and r.get("html_path"):
                webbrowser.open(Path(r["html_path"]).resolve().as_uri())
    logger.info("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
