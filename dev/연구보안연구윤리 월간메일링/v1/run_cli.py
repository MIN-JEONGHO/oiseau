# -*- coding: utf-8 -*-
"""명령줄 실행 진입점 (윈도우 작업 스케줄러 등록용).

예)
  python run_cli.py                          # 지난달 기준, 활성화된 리포트 전부 수집·발송
  python run_cli.py --report security        # 연구보안만
  python run_cli.py --month 2026-07          # 특정 월
  python run_cli.py --no-send                # 발송 없이 HTML 미리보기만 생성
  python run_cli.py --data output/security_2026-07.json --report security
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rmonitor.config import load_config
from rmonitor.pipeline import run_all
from rmonitor.utils import month_period, previous_month_period, setup_logger

BASE_DIR = Path(__file__).resolve().parent


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="연구보안·연구윤리 월간 리포트 자동 발송")
    ap.add_argument("--config", default=str(BASE_DIR / "config.json"))
    ap.add_argument("--report", choices=["security", "ethics", "all"], default="all")
    ap.add_argument("--month", help="수집 대상 월 (YYYY-MM). 미지정 시 지난달")
    ap.add_argument("--no-send", action="store_true", help="메일을 보내지 않는다")
    ap.add_argument("--no-excel", action="store_true", help="엑셀 누적 기록을 하지 않는다")
    ap.add_argument("--data", help="이미 수집된 JSON 파일로 재렌더링/재발송")
    ap.add_argument("--test-mail", metavar="ADDRESS", nargs="?", const="",
                    help="SMTP 설정 점검용 테스트 메일 1통 발송(주소 생략 시 본인에게)")
    return ap.parse_args(argv)


def send_test_mail(cfg, logger, address: str = "") -> int:
    """SMTP 설정이 올바른지 확인하는 짧은 테스트 메일."""
    from rmonitor.config import sender_address
    from rmonitor.mailer import build_message, send

    to = address or sender_address(cfg)
    msg = build_message(
        subject="[테스트] 연구보안·연구윤리 리포트 자동 발송 설정 확인",
        html_body=('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                   'border="0"><tr><td style="padding:16px; font-size:14px; '
                   "font-family:'맑은 고딕',Arial,sans-serif;\">SMTP 설정이 정상입니다. "
                   "이 메일이 보이면 발송 준비가 끝난 것입니다.</td></tr></table>"),
        sender=sender_address(cfg),
        sender_name=cfg["smtp"].get("sender_name", ""),
        to=[to],
    )
    send(msg, cfg["smtp"], logger=logger)
    logger.info("테스트 메일을 %s 로 보냈습니다.", to)
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    logger = setup_logger(BASE_DIR / cfg.get("log_dir", "logs"))

    if args.test_mail is not None:
        try:
            return send_test_mail(cfg, logger, args.test_mail)
        except Exception as exc:  # noqa: BLE001
            logger.error("테스트 메일 실패: %s", exc)
            return 1

    if args.month:
        year, month = (int(x) for x in args.month.split("-")[:2])
        period = month_period(year, month)
    else:
        period = previous_month_period()

    if args.report == "all":
        keys = [k for k, v in cfg["reports"].items() if v.get("enabled", True)]
    else:
        keys = [args.report]

    if not keys:
        logger.error("실행할 리포트가 없습니다. config.json 의 reports.*.enabled 를 확인하세요.")
        return 1

    logger.info("=" * 70)
    logger.info("대상 월: %s (%s ~ %s) / 리포트: %s",
                period.report_month, period.start_iso, period.end_iso, ", ".join(keys))

    results = run_all(keys, period, cfg, BASE_DIR,
                      send_mail=not args.no_send,
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
            logger.info("· %s : 이슈 %d건 / 발송 %s / 엑셀 %s건 추가",
                        r.get("name", r["report"]), r.get("issue_count", 0),
                        "완료" if r.get("sent") else "안 함", excel.get("added", 0))
    logger.info("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
