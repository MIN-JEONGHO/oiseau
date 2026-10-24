@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  회의록 자동정리 프로그램 - exe 빌드
echo ============================================
echo.

where python > nul 2>&1
if errorlevel 1 (
    echo [실패] python 을 찾을 수 없습니다. Python 3.10 이상을 설치하고 PATH 에 추가해 주세요.
    pause
    exit /b 1
)

echo [1/3] 의존 패키지 설치
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [실패] 패키지 설치 중 오류가 발생했습니다.
    pause
    exit /b 1
)

echo [2/3] 동작 점검 ^(API 키 없이 문서 생성만 확인^)
python selftest.py
if errorlevel 1 (
    echo [실패] 자체 점검을 통과하지 못했습니다. 위 메시지를 확인해 주세요.
    pause
    exit /b 1
)
del /q "_selftest_결과.hwpx" "_selftest_전사문.txt" 2> nul

echo [3/3] exe 생성
python -m PyInstaller --noconfirm --clean 회의록자동정리.spec
if errorlevel 1 (
    echo [실패] 빌드 중 오류가 발생했습니다.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  완료 : dist\회의록자동정리.exe
echo ============================================
echo.
echo  · 배포 시 exe 파일 하나만 전달하면 됩니다.
echo  · API 키를 내장해 배포하려면 빌드 전에 embedded_key.py 에 키를 적어 두세요.
echo  · 25MB 넘는 녹음파일을 처리하려면 빌드 전에
echo    ffmpeg.exe 를 이 폴더에 두거나 pip install av 를 해두세요.
echo.
pause
