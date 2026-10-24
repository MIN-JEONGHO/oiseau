@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo  제재처분 원인과제 집계 - exe 빌드
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [중단] python 을 찾을 수 없습니다. Python 3.10 이상을 설치하고 PATH에 추가하세요.
  pause & exit /b 1
)

echo [1/3] 필요한 패키지 확인
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pandas openpyxl lxml xlsxwriter python-calamine pywebview pyinstaller
if errorlevel 1 (
  echo [중단] 패키지 설치에 실패했습니다. 사내망 프록시 설정을 확인하세요.
  pause & exit /b 1
)

echo [2/3] 기존 빌드 정리
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] 빌드
python -m PyInstaller app.spec --noconfirm
if errorlevel 1 (
  echo [중단] 빌드에 실패했습니다. 위 메시지를 확인하세요.
  pause & exit /b 1
)

echo.
echo ============================================================
echo  완료: dist\제재처분집계.exe
echo ============================================================
echo.
echo  * 배포 대상 PC에 Microsoft Edge WebView2 런타임이 필요합니다.
echo    Windows 10 21H2 이상 / Windows 11 은 기본 포함되어 있습니다.
echo    없으면 화면이 기본 브라우저로 열립니다.
echo.
if exist dist explorer dist
pause
