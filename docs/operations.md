# 설치·실행·빌드

## 공통 준비

1. Windows 10/11. pywebview 화면을 쓰는 도구(공공데이터·제재통계·리포트·회의록)는 Microsoft Edge WebView2 런타임이 필요하다. Windows 10 21H2 이상과 Windows 11에는 기본으로 들어 있다.
   - exe는 WebView2가 없으면 구형 IE 엔진으로 창을 열어서 화면이 동작하지 않는다.
   - 소스로 실행할 때 pywebview가 설치되어 있지 않으면, 제재통계·리포트·회의록은 같은 화면을 기본 브라우저로 연다. 공공데이터는 HTTP 서버 없이 창을 직접 띄우므로 브라우저로 대신 여는 기능이 없다.
2. Python 3.10 이상. 이 PC에서는 `python`이 3.14.2이고, 의존성이 사용자 site-packages에 설치되어 있다. `-I`·`-s` 옵션 없이 실행한다.
3. 경로에 공백과 한글이 있으므로 항상 따옴표로 감싼다. 아래 명령은 PowerShell 기준이며, 각 프로그램의 **현재 버전 폴더**에서 실행한다. 다른 폴더에서 빌드하면 build·dist가 그 폴더에 생긴다.
4. hwpx 산출물을 확인하려면 한컴오피스 한글이 필요하다.

## 공공데이터 등록 사전검토

```powershell
cd "dev/공공데이터 DB검증 프로그램/공공데이터 DB검증v4"
python -m pip install -r requirements.txt     # openpyxl, pywebview, pyinstaller
python main.py                                 # 화면(파일데이터·OPEN API 두 탭)
python main.py data.csv -x 검토결과.xlsx        # 파일데이터 검토 + 엑셀 리포트
python main.py 폴더경로 -m meta.json            # 폴더 일괄 + 등록정보 함께 검토
python main.py data.csv --fix 서식              # 서식 수정만 적용 → data_수정.csv
python main.py --api -m api.json --spec 기술문서.json          # OPEN API 검토
python main.py --api -m api.json --probe --key <인증키>        # 실호출 포함(외부로 요청이 나간다)
python tests/test_rules.py                      # 파일데이터 회귀 시험
python tests/test_api_rules.py                  # OPEN API 회귀 시험
.\build_exe.bat                                 # → dist\공공데이터_사전검토.exe
```

- `build_exe.bat`은 requirements를 설치하고 build·dist를 지운 뒤 `--onefile --windowed`로 빌드한다. 화면 HTML이 소스 안 문자열이라 별도 자원 지정이 없다.
- 환경변수 `PDCHECK_DEBUG`를 아무 값으로 두면 화면 개발자 도구가 켜진다.
- 샘플은 `samples/`에 있다(`good_sample.csv`, `bad_sample.csv`, `sample.json`, `api_meta.json`, `api_swagger.json`).

## 국외지원사항 통계

```powershell
cd "dev/국외지원사항 프로그램/국외지원 자동산출 프로그램v4.3"
python -m pip install pandas openpyxl lxml        # 실행에 필요
python -m pip install pyinstaller pillow           # 빌드·아이콘 재생성에만 필요
python 국외지원사항_통계산출.py                      # 화면
python 국외지원사항_통계산출.py 연구자raw_20260727.xlsx 과제raw_20260727.xlsx 결과.xlsx
python -m PyInstaller 국외지원사항_통계산출.spec     # → dist\국외지원사항_통계산출.exe
python make_icon.py                                # 아이콘(app_icon.ico·png·preview) 다시 만들기
```

- 화면에서 [저장폴더]의 기본값은 프로그램 폴더다. 실제 자료로 돌릴 때는 저장소 밖 폴더로 바꾼다.
- 명령줄 출력은 세 번째 인수(없으면 현재 폴더의 `통계분석결과_YYYYMMDD.xlsx`)이고, 양식이 있으면 같은 이름의 `.hwpx`가 함께 생긴다.
- 매핑테이블·표준보고양식·사용설명서·아이콘은 `.spec`의 datas로 exe에 들어간다. exe 하나만 옮기면 된다. 소스 폴더의 `매핑테이블.xlsx`를 고친 내용은 다시 빌드해야 exe 기본값에 반영된다.
- 사내 보안 프로그램이 exe를 막으면 Python을 설치하고 `.py`를 직접 실행해도 똑같이 동작한다.

## 제재통계

```powershell
cd "dev/제재통계 프로그램/통계v6"
python -m pip install pandas openpyxl lxml xlsxwriter python-calamine pywebview
python app.py                                      # 화면(두 통계 탭)
python run_report.py rawdata_20260301.xlsx --template template.hwpx           # 연구수행 기준, 엑셀+hwpx
python run_report.py rawdata.xlsx --template template.hwpx --ref 조사분석_참조데이터.xlsx --outdir 결과
python run_report.py rawdata.xlsx --make-ref-template          # 참조데이터 입력 양식 만들기
python run_report.py rawdata.xlsx --year-start 2017 --year-end 2025
.\build_exe.bat                                    # → dist\제재통계.exe
```

- `python-calamine`이 없으면 openpyxl로 읽는다(10만 행에서 수 배 느림). 소스 실행에서 `pywebview`가 없으면 기본 브라우저로 열린다.
- 명령줄은 `--template`을 항상 지정한다. 지정하지 않으면 rawdata 폴더 등에 있는 아무 `.hwpx`(이전 결과물 포함)를 양식으로 쓴다.
- 명령줄은 연구수행 기준 검산을 하지 않는다. 검산 ✓를 확인하려면 화면으로 실행한다.
- `build_exe.bat`은 자기 폴더로 이동하지 않는다. 탐색기에서 더블클릭하거나 위처럼 폴더로 이동한 뒤 실행한다.
- 실행 창이 뜨지 않으면 `app.spec`의 `console=False`를 `True`로 바꿔 다시 빌드해 콘솔에서 원인을 본다.
- `ui/index.html`, 두 양식(`template.hwpx`, `template_monthly.hwpx`), `reference.xlsx`가 exe에 들어간다. 화면에서 다른 파일을 넣으면 그 파일을 대신 쓴다.
- 참조데이터 준비: `--make-ref-template`으로 부처·연도가 채워진 양식을 만들고, NTIS 조사·분석 값(국가R&D연구비·과제수)을 넣어 `--ref`로 넘기거나 화면에서 지정한다.

## 연구보안·연구윤리 동향 리포트

```powershell
cd "dev/연구보안연구윤리 월간메일링/v4"
.\최초설치.bat          # requirements 설치, config.json·rmonitor\_secrets.py가 없으면 example에서 복사
.\실행_GUI.bat          # 또는 python run_gui.py
python run_cli.py --period-mode monthly                     # 지난달, 켜진 리포트 전부
python run_cli.py --period-mode weekly --report security    # 지난주(월~일), 연구보안만
python run_cli.py --period-mode monthly --month 2026-07     # 특정 월
python run_cli.py --period-mode weekly --week 2026-W27      # 특정 주(ISO)
python run_cli.py --report security --period-mode monthly --month 2026-07 --data data/sample_security.json   # API 없이 확인
python run_cli.py --history-report output/이력.xlsx         # 수집 없이 이력 엑셀만
.\build_exe.bat         # → dist\연구보안연구윤리_모니터링.exe
```

- `최초설치.bat`은 `_secrets.py`에 아직 견본 문구가 있으면 키를 넣으라고 알린다. 키는 `rmonitor/_secrets.py`의 `ANTHROPIC_API_KEY`에 넣고, 환경변수 `RM_LLM_API_KEY`가 있으면 그 값이 먼저 쓰인다.
- exe는 실행한 폴더 옆에 `config.json`·`output`·`logs`·`history`·`data`를 만든다. 폴더째 옮기면 설정과 이력이 이어진다.
- **예약 실행**
  - Windows 작업 스케줄러에 `실행_자동발송.bat`(예: 매월 1일 00:05, 월간)과 `실행_자동발송_주간.bat`(예: 매주 월요일 08:00, 주간)을 등록한다. 시작 위치는 이 폴더로 둔다.
  - 두 배치는 exe가 아니라 `python run_cli.py`를 부르므로, 그 PC에 Python과 의존성이 있어야 한다.
  - 결과는 `logs\schedule.log`에 쌓인다. 이 폴더에 `logs` 폴더가 없으면 첫 실행부터 기록 없이 실패하므로, 등록 전에 `logs` 폴더를 만들거나 한 번 실행해 둔다.
- 누적 엑셀(`data/동향_모니터링_누적.xlsx`)이 없으면 첫 실행 때 `data/_양식_동향_모니터링.xlsx`를 복사해 만든다.
- 메일 발송 기능은 없다. 만들어진 HTML(`output/security_YYYY-MM.html` 등)을 [다른 이름으로 저장]으로 내보내 사람이 전달한다.

## 회의록 자동정리

```powershell
cd "dev/회의록 자동정리 프로그램/회의록정리v3.1"
python -m pip install -r requirements.txt     # lxml(필수), pywebview(권장), av(녹음 변환·분할)
python app.py                                  # 화면
python app.py --cli 회의녹음.m4a --attendees "홍길동/과학기술정보통신부/사무관, 김철수/한국연구재단/팀장" --title "회의 제목" --date 2026-09-04 --place "’26. 9. 4.(금) 14:00 / 장소" --out "C:\결과"
python app.py --cli 아무값 --session "<저장한 세션>.json" --out "C:\결과"   # 전사 건너뛰기
python -m unittest discover -s tests -p test_summary_model.py              # 모의 응답 시험
python selftest.py                                                         # API 없이 hwpx 생성 점검
.\build_exe.bat          # 또는 python -m PyInstaller --noconfirm --clean 회의록자동정리.spec → dist\회의록자동정리v3.1.exe
```

- 이 폴더는 자체 git 저장소다. 커밋은 이 폴더 안에서 한다.
- 키는 빌드 전에 `embedded_key.py`의 `OPENAI_API_KEY`에 넣는다. 내장 키가 없을 때만 환경변수 `OPENAI_API_KEY`를 쓴다.
- `selftest.py`가 만드는 `_selftest_결과.hwpx`·`_selftest_전사문.txt`는 검증용 산출물이다.
- 24MiB를 넘는 녹음이나 aac·wma·opus 같은 형식을 처리하려면 빌드 전에 `av`를 설치하거나 `ffmpeg.exe`를 이 폴더에 둔다. 그래야 exe에 함께 묶인다.
- 명령줄 `--session`도 발언자 매칭(참석자가 있을 때)과 요약을 다시 실행하므로 유료 호출이 생긴다.
- 설정(작성 부서 등 문서 기본값)은 `%APPDATA%\KISTEP회의록정리\config.json`에 저장된다.
- 배포 전 수동 확인: 새 exe에서 [요약 모델 연결 테스트]를 실행한다(실제 호출, 소액 과금). 이어서 합성 회의 자료로 발언자 매칭 → 요약 → 수정 → 세션 저장·복원 → hwpx 생성까지 확인한다. 400구간을 넘는 자료로 구간 누락·중복과 기관 혼합도 본다.
- 되돌리기: 이전 버전 폴더(`회의록정리v3`)의 exe를 쓰거나, `config.py`의 `SUMMARY_MODEL`을 이전 값으로 고친 뒤 다시 검증·빌드한다.

## 환경변수

| 이름 | 쓰는 곳 | 뜻과 범위 |
|---|---|---|
| `OPENAI_API_KEY` | 회의록 | `embedded_key.py`에 키가 없을 때만 쓰는 OpenAI 키(개발용) |
| `RM_LLM_API_KEY` | 리포트 v3·v4 | 내장 키보다 먼저 쓰는 Anthropic 키. 다시 빌드하지 않고 키를 바꿀 때 쓴다 |
| `PDCHECK_DEBUG` | 공공데이터 | 값이 있으면 화면 개발자 도구를 켠다 |
| `APPDATA` | 회의록 | 설정 파일 위치(`%APPDATA%\KISTEP회의록정리`) |

## 배포

1. 해당 버전 폴더에서 빌드한다. 빌드 종료 코드 0을 확인한다.
2. 빈 폴더에 exe만 두고 실행해 화면과 기본 기능을 확인한다.
3. 회의록·리포트 exe에는 API 키가 들어 있다. 같은 센터·부서 동료에게만 준다.
4. 받는 PC에 WebView2 런타임이 있는지 확인한다. 없으면 화면이 동작하지 않는다.
5. 이전 버전 exe는 이전 버전 폴더의 `dist`에 그대로 둔다(되돌리기용).
