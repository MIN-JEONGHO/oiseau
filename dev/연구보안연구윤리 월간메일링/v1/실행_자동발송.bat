@echo off
chcp 65001 > nul
cd /d "%~dp0"
python run_cli.py --report all >> logs\schedule.log 2>&1
