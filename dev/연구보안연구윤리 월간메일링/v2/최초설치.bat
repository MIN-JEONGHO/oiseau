@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -m pip install -r requirements.txt
if not exist config.json copy config.example.json config.json
echo.
echo 설치가 끝났습니다. config.json 을 열어 API 키와 메일 계정을 입력하거나,
echo 실행_GUI.bat 을 실행한 뒤 [설정] 탭에서 입력하세요.
pause
