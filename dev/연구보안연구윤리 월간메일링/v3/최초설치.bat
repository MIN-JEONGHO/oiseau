@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -m pip install -r requirements.txt
if not exist config.json copy config.example.json config.json
if not exist rmonitor\_secrets.py copy rmonitor\_secrets.example.py rmonitor\_secrets.py
echo.
echo 설치가 끝났습니다.
if not exist rmonitor\_secrets.py goto :done
findstr /c:"여기에-API-키-입력" rmonitor\_secrets.py >nul
if not errorlevel 1 (
  echo [!] rmonitor\_secrets.py 에 아직 API 키가 입력되지 않았습니다.
  echo     그 파일을 열어 ANTHROPIC_API_KEY 값을 실제 키로 바꿔 주세요.
) else (
  echo LLM(Claude Sonnet 5.5)은 API 키가 이미 설정되어 있어 별도 입력 없이 실행_GUI.bat 으로
  echo 바로 실행할 수 있습니다.
)
:done
pause
