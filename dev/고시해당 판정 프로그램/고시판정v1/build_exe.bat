@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo  연구보안 등급분류 분류기준(고시) 검토 - 설치 파일 빌드 (1.2.0부터 폴더형 + 설치 파일)
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [중단] python 을 찾을 수 없습니다. Python 3.14 를 설치하고 PATH에 추가하세요.
  pause & exit /b 1
)

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo [중단] Inno Setup 6 이 없습니다. winget install --id JRSoftware.InnoSetup -e --scope user 로 설치하세요.
  pause & exit /b 1
)

echo [1/6] 필요한 패키지 확인 (requirements.txt)
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo [중단] 패키지 설치에 실패했습니다. 사내망 프록시 설정을 확인하세요.
  pause & exit /b 1
)

echo [2/6] 기준값 표·고시 검색 자원 확인
if not exist resources\thresholds.json (
  echo [중단] resources\thresholds.json 이 없습니다. python tools\build_threshold_table.py 를 먼저 실행하세요.
  pause & exit /b 1
)
if not exist resources\search_dictionary.json (
  echo [중단] resources\search_dictionary.json 이 없습니다. python tools\build_search_dictionary.py 를 먼저 실행하세요.
  pause & exit /b 1
)
if not exist resources\search_vectors.npy (
  echo [중단] resources\search_vectors.npy 가 없습니다. python tools\build_search_vectors.py 를 먼저 실행하세요.
  pause & exit /b 1
)

echo [3/6] 소스 자체 확인
python app.py --selfcheck > build-selfcheck-source.json
if errorlevel 1 (
  echo [중단] 소스 자체 확인에 실패했습니다. build-selfcheck-source.json 을 확인하세요.
  pause & exit /b 1
)

echo [4/6] 기존 빌드 정리 후 폴더형 빌드
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
python -m PyInstaller --noconfirm 고시판정v1.spec
if errorlevel 1 (
  echo [중단] 빌드에 실패했습니다.
  pause & exit /b 1
)

echo [5/6] 빌드한 프로그램 자체 확인
"dist\고시판정v1\고시판정v1.exe" --selfcheck > build-selfcheck-exe.json
if errorlevel 1 (
  echo [중단] 빌드한 프로그램 자체 확인에 실패했습니다. build-selfcheck-exe.json 을 확인하세요.
  pause & exit /b 1
)

echo [6/6] 설치 파일 만들기
"%ISCC%" /Q "installer\고시수준검토.iss"
if errorlevel 1 (
  echo [중단] 설치 파일 만들기에 실패했습니다.
  pause & exit /b 1
)

echo.
echo 완료: dist\연구보안등급분류_분류기준고시검토_설치_v1.4.2.exe
echo 받는 PC에는 Microsoft Edge WebView2 런타임이 있어야 합니다. build, dist 폴더와 설치 파일은 커밋하지 않습니다.
pause
