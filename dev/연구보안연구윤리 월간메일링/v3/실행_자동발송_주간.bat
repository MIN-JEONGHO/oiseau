@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem 작업 스케줄러(매주 월요일 등) 등록용 — 지난주(월~일) 기준으로 전체 리포트를 생성한다.
python run_cli.py --report all --period-mode weekly >> logs\schedule.log 2>&1
