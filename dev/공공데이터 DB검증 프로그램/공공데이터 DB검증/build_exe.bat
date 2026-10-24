@echo off
REM ============================================================
REM  공공데이터 사전검토 프로그램 - 윈도우 exe 빌드
REM  사전 준비: python -m pip install -r requirements.txt
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] 의존성 확인
python -m pip install -r requirements.txt || goto :err

echo [2/3] 기존 빌드 정리
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] PyInstaller 실행 (단일 exe)
python -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "공공데이터_사전검토" ^
  --collect-all webview ^
  --hidden-import openpyxl ^
  --hidden-import clr_loader ^
  main.py || goto :err

echo.
echo 빌드 완료: dist\공공데이터_사전검토.exe
echo 주의: 실행 PC에 Microsoft Edge WebView2 런타임이 필요합니다
echo        (윈도우 10/11 대부분 기본 설치됨)
goto :eof

:err
echo.
echo 빌드 실패. 위 오류 메시지를 확인하세요.
exit /b 1
