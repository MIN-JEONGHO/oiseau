@echo off
REM ============================================================
REM  Public Data Precheck Program v3.0.0 - Windows exe build
REM  (file data + OPEN API)
REM  Prerequisite: python -m pip install -r requirements.txt
REM  (Comments/messages kept ASCII-only so this runs regardless
REM   of the console's active codepage.)
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] Checking dependencies
python -m pip install -r requirements.txt || goto :err

echo [2/3] Cleaning previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Running PyInstaller (single exe)
python -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "공공데이터_사전검토" ^
  --collect-all webview ^
  --hidden-import openpyxl ^
  --hidden-import clr_loader ^
  main.py || goto :err

echo.
echo Build complete: dist\공공데이터_사전검토.exe
echo Note: the target PC needs the Microsoft Edge WebView2 runtime
echo       (already installed on most Windows 10/11 systems)
goto :eof

:err
echo.
echo Build failed. Check the error messages above.
exit /b 1
