@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo  연구보안연구윤리 모니터링 - exe 빌드 (GUI)
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [중단] python 을 찾을 수 없습니다. Python 3.10 이상을 설치하고 PATH에 추가하세요.
  pause & exit /b 1
)

echo [1/3] 필요한 패키지 확인
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt pyinstaller
if errorlevel 1 (
  echo [중단] 패키지 설치에 실패했습니다. 사내망 프록시 설정을 확인하세요.
  pause & exit /b 1
)

echo [2/3] 기존 빌드 정리
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] 빌드
python -m PyInstaller 연구보안연구윤리_모니터링.spec --noconfirm
if errorlevel 1 (
  echo [중단] 빌드에 실패했습니다. 위 메시지를 확인하세요.
  pause & exit /b 1
)

echo.
echo ============================================================
echo  완료: dist\연구보안연구윤리_모니터링.exe
echo ============================================================
echo.
echo  * 배포 대상 PC에 Microsoft Edge WebView2 런타임이 필요합니다.
echo    Windows 10 21H2 이상 / Windows 11 은 기본 포함되어 있습니다.
echo    없으면 화면이 기본 브라우저로 열립니다.
echo  * exe 를 다른 폴더로 옮기면 config.json/output/logs/history 도 그 폴더를
echo    기준으로 새로 만들어집니다 — exe 하나만 복사해도 되지만, 기존 기록을
echo    옮기려면 exe 옆의 이 폴더들도 함께 복사하세요.
echo  * 자동 실행(작업 스케줄러)은 이 exe 가 아니라 지금처럼
echo    실행_자동발송.bat / 실행_자동발송_주간.bat (python run_cli.py) 를 사용하세요.
echo.
if exist dist explorer dist
pause
