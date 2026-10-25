# 설치·실행·배포

Windows 64비트 Python, Microsoft Edge WebView2 Runtime과 .NET Framework 4.6.2 이상을 준비한다. v15 확인 환경은 Python 3.14.6, pywebview 6.2.1·pythonnet 3.2.1·clr_loader 0.3.1·cffi 2.1.1, lxml 6.1.1·openpyxl 3.1.5·requests 2.34.2·OpenAI SDK 2.47.0·Anthropic SDK 1.3.0·PyInstaller 6.21.0이다. requirements는 확인한 전이 의존성까지 고정한다. Anthropic의 httpx2·httpcore2·truststore를 기존 httpx와 임의 교체하지 않는다. v15 실행에 pandas·PySide6·PDF 추출기·Playwright는 필요 없다.

프로젝트 폴더에서 다음 순서로 별도 환경을 만든다. 기존 v12~v14 환경과 운영 파일을 덮어쓰지 않는다. PATH 별칭이 실패하면 실제 설치한 python.exe 경로를 사용한다.

```powershell
python -m venv .venv_v15
.\.venv_v15\Scripts\python.exe -m pip install -r requirements_v15.txt
.\.venv_v15\Scripts\python.exe .\security_grade_classifier_v15.py
```

WebView2 Runtime을 찾지 못하면 앱이 설치 안내 후 종료한다. 구형 브라우저 엔진으로 전환하지 않는다. UI·폰트는 로컬 자산이며 별도 웹사이트나 브라우저 창을 열 필요가 없다.

## 키·모델·입력

설정에서 Claude Sonnet 5.5/claude-sonnet-5-5 또는 OpenAI GPT-6 Luna/gpt-6-luna를 선택한다. 키를 적용하면 현재 Windows 계정 보안 저장소에 제공자별로 자동 저장하고 다음 실행에 재사용한다. 새 입력 → 저장 키 → ANTHROPIC_API_KEY/OPENAI_API_KEY 순서이며 환경변수는 자동 영구 저장하지 않는다. 적용 후 입력란은 비워진다. 저장 실패 시 경고를 확인하고 해당 세션의 입력 키를 사용하거나 재입력한다. 키 유무는 인증·권한·할당량 확인이 아니다. 키 삭제는 앱 저장 항목·현재 입력·메모리 범위다.

Ollama·LM Studio는 별도 서버·설치 모델을 준비하고 주소와 모델 식별자를 입력한다. 기본 주소는 각각 http://localhost:11434와 http://localhost:1234다. 모델 가중치는 앱에 포함하지 않는다. 외부 전송 불가 과제는 실제 내부 목적지인지 확인한 로컬 서버로 처리한다.

단건은 과제명과 요약을 입력하고 현재 기술사양과 개발목표를 구분한다. 필요하면 추가 검토정보·실제 부처 세부기준을 넣는다. 체크리스트 또는 국가영향 지표를 하나 선택한다. 국가영향 자동 선택은 실제 선택 가중치 모두 1.0이며 직접 선택만 가중치 범위·평균을 검사한다. 마지막 의견은 표준으로 고정되어 있다.

실행 후 검토필요·후보제외·오류와 참고 등급을 구분하고 에이전트별 의견, 고시의 현재/목표 조건·예외·부족 질문을 확인한다. 미해석 조건은 자동 판정되지 않으므로 실제 기술 사양과 전문 검토를 보완한다. 저장 위치 선택에서 폴더를 고르면 개별 의견서와 종합 HWPX를 생성한다.

대량은 9열 입력 양식의 분류대상 시트를 사용하고 결과는 입력과 다른 .xlsx 경로로 고른다. 결과 엑셀은 다른 프로그램에서 닫는다. HWPX 생성 옵션·예정/성공/실패/누락 수·저장 경고·감사 상태를 확인한다. 결과 5개 시트와 옆의 .checkpoint.jsonl·.audit.jsonl 및 결과명_HWPX 폴더를 함께 관리한다. 체크포인트에는 입력과 상세 근거가 있으므로 기관 방침에 맞게 보호한다.

재개는 입력·옵션·고시 지문이 일치하는 완료 평가만 사용한다. 구버전·손상 파일은 경고 후 새 처리하며 기존 업무 기록을 보관한 새 경로로 비교 실행한다. 같은 배치의 결과를 다시 내보낼 때는 화면의 최신 결과를 사용한다. 문서 재생성은 모델·키·현재 고시를 호출하지 않으며 문서 생성과 체크포인트/엑셀/감사 갱신 상태를 따로 확인한다. 파일 잠금이면 열린 엑셀을 닫고 재출력한다.

## 개발 확인과 패키징

오프라인 Python 시험은 모의 모델·가짜 저장소를 사용한다. 실제 Edge 렌더링 시험에는 설치된 Microsoft Edge와 개발 전용 Playwright 1.64.0이 필요하다. 아래 시험 명령을 실행할 개발 환경에만 Playwright를 설치하며 실행 requirements나 배포 파일에 추가하지 않는다.

```powershell
.\.venv_v15\Scripts\python.exe -m pip install playwright==1.64.0
.\.venv_v15\Scripts\python.exe -m unittest discover -s tests -p "test_v15_*.py"
.\.venv_v15\Scripts\python.exe -m unittest discover -s tests -p "test_v14_*.py"
.\.venv_v15\Scripts\python.exe -m py_compile security_grade_classifier_v15.py desktop_bridge_v15.py v15_domain.py notice_catalogue_v15.py notice_review_v15.py classification_v15.py batch_v15.py hwpx_writer_v15.py llm_client_v14.py credential_store.py
.\.venv_v15\Scripts\python.exe security_grade_classifier_v15.py --self-check .\build-v15\source-self-check.json
.\.venv_v15\Scripts\python.exe -m PyInstaller --noconfirm --workpath .\build-v15 --distpath .\dist-v15 '보안등급분류시뮬레이터_v15.spec'
$check = Start-Process -FilePath '.\dist-v15\보안등급분류시뮬레이터_v15.exe' -ArgumentList '--self-check', '.\build-v15\frozen-self-check.json' -WindowStyle Hidden -PassThru -Wait
$check.ExitCode
Get-Content -LiteralPath '.\build-v15\frozen-self-check.json' -Encoding UTF8
```

빌드 전 source 자체 확인의 실제 종료 코드 0과 새 JSON의 pass:true를 확인하고 빌드 후 실행 파일에서도 같은 두 조건과 frozen:true를 확인한다. 실행 파일은 dist-v15/보안등급분류시뮬레이터_v15.exe다. 자체 확인은 숨긴 실제 WebView와 합성 과제·가짜 키 저장소로 UI·9개 브리지·고시 자산·모의 단건/배치/재출력·외부 접근 차단을 검사한다. 실제 키·유료 API·사용자 문서는 쓰지 않는다. source 성공만으로 실행 파일 성공을 추정하지 않는다.

배포 자산은 ui_v15 전체와 폰트 라이선스, resources_v15/notices의 manifest·모든 원문/정규화/검수 파일, templates/v15의 두 파생 서식, 아이콘이다. WebView JS·관리 DLL·아키텍처별 WebView2Loader·Python.Runtime·clr_loader 및 SDK의 필요한 지연 모듈·데이터·메타데이터를 포함한다. 전체 가이드라인·실제 입력/감사/체크포인트·키·과거 실행 모듈·시험/개발 도구·독립 엑셀 열람기·모델 가중치는 제외한다. 실행 파일의 실제 아카이브 목록을 확인한다.

2026-10-23 v15 279개·v14 134개, 총 413개 회귀시험, 새 실행 경로 10개 파일 문법·의존성 검사, 최종 빌드·아카이브 검증·source/EXE 자체 확인을 실제 종료 코드 0으로 확인했다. source와 EXE 보고서는 pass:true이며 EXE는 frozen:true다. OpenAI SDK 2.47.0·Anthropic SDK 1.3.0 import와 UI 5개·고시 25개를 포함한 프로젝트 자산 33개의 바이트 일치를 확인했다. 확인한 EXE는 42,060,170바이트, SHA256 f93c9b7ffe464f5cb1aa05d918995d86a20d11455c5ab57bdcced83866b7ea00다. 재빌드한 실행 파일은 해시가 달라질 수 있다.

배포 파일 존재·숨긴 자체 확인·ZIP/XML 검증은 한글에서의 전체 표시나 실제 Windows 배율을 검증하지 않는다. 모든 HWPX 종류·긴 내용·종합 의견서의 한글 실열람과 실제 125%/150% 화면 확인은 사용자가 중단한 데스크톱 제어 재개 전까지 보류한다. 표시검수용 합성 문서는 실제 고시 판정·예시과제집 정답이 아니다. 이 상태를 전체 검증 완료나 운영 전환으로 표시하지 않는다.

## 과거 도구

v12는 별도 전환 전 운영 기준이며 기존 진입점과 .spec를 유지한다. v13_test·v14도 독립 검토 경로다. 각 버전의 기존 SDK·Tkinter·기타 의존성을 v15 requirements가 모두 충족한다고 가정하지 않는다. 과거 .spec로 빌드한 파일을 v15라고 표시하지 않는다.

excel_viewer.py는 PySide6·pandas 기반 독립 열람기다. .xls의 추가 엔진은 별도 확인 대상이며 그 의존성을 v15 필수에 추가하지 않는다.

## v16

v16은 requirements_v15.txt와 같은 의존성을 쓴다. 개발 확인 환경은 시뮬레이터 폴더의 `.dryforge/implementation/.dryforge/env-v15/Scripts/python.exe`(Python 3.14.6, 실행 의존성과 개발용 PyMuPDF 2.0·Playwright 1.64.0)이다. 이 경로는 커밋되지 않는 로컬 환경이므로, 다른 PC나 새 사본에서는 위 v15 절차로 환경을 만든 뒤 같은 버전의 PyMuPDF·Playwright를 개발 환경에만 설치한다. 아래 `$PY`는 그 Python이다.

```powershell
& $PY .\security_grade_classifier_v16.py
& $PY -m unittest discover -s tests -p "test_v16_*.py"
& $PY -m unittest discover -s tests -p "test_v15_*.py"
& $PY -m unittest discover -s tests -p "test_v14_*.py"
& $PY .\security_grade_classifier_v16.py --self-check .\build-v16\source-self-check.json
& $PY -m PyInstaller --noconfirm --workpath .\build-v16 --distpath .\dist-v16 '보안등급분류시뮬레이터_v16.spec'
$check = Start-Process -FilePath '.\dist-v16\보안등급분류시뮬레이터_v16.exe' -ArgumentList '--self-check', '.\build-v16\frozen-self-check.json' -WindowStyle Hidden -PassThru -Wait
$check.ExitCode
```

v16 기준본을 다시 만들 때는 생성 도구가 기본 위치(resources_v16/notices)를 바로 덮어쓰므로, 먼저 임시 폴더에 resources_v15/notices의 raw와 .gitattributes를 복사하고 `& $PY tools/build_notice_catalogue_v16.py --root <임시 폴더>`로 만든다. 그 결과의 raw·extracted·normalized·review가 resources_v15와 바이트까지 같을 때만 resources_v16/notices로 옮긴다. 다르면 옮기지 않는다. 생성 도구는 같은 고시번호 본문 HTML 머리글의 고시일·시행일을 정해 둔 값과 대조하며 다르면 실패한다.

배포 자산은 ui_v16 전체와 폰트 라이선스, resources_v16/notices 25개 파일, templates/v15 두 서식, 아이콘이다. v15 실행 모듈 8개, v14 이하 모듈, ui_v15·resources_v15, 시험·개발 도구, 가이드라인 원본, `_claude` 변형, 실제 입력·감사·중간 저장은 묶지 않는다. 2026-10-25 보완 2 최종 빌드는 42,099,127바이트, SHA256 ad8b8ecbd48e07253829fd77aab1a4d31471061d38b418f1e82407c3d3c96b44이며 아카이브 점검 통과, 실행 파일 자체 확인 3번 모두 pass:true·frozen:true다. 직전 빌드에서 빌드 직후 '앱 초기화 실패'가 간헐적으로 있었다(findings 참고). 다시 빌드하면 해시가 달라질 수 있다.

대량 점검(모의 응답, 실제 AI 호출 없음):

```powershell
& $PY tools/v16_bulk_check.py notice <입력.xlsx>            # 과제별 고시 후보·대조 상태 미리 보기
& $PY tools/v16_bulk_check.py run <입력.xlsx> <과제목록.json> <새 실행 폴더>
& $PY tools/v16_bulk_check.py stats <원본.xlsx>              # 형식 통계(숫자만)
```

`run`은 실행 파일과 같은 일괄 검토 경로를 모의 모델·메모리 키 저장소로 돌린 뒤, 의견서 검사와 분석 엑셀·요약 보고서를 만든다. 실행 폴더가 이미 있으면 멈춘다. 종료 코드는 다음과 같다.
- 0: 모두 통과
- 2: 끝났지만 문제 있음
- 1: 입력 오류
실제 과제 자료와 점검 결과는 `예시과제*/` 아래에만 둔다. 이 폴더는 커밋하지 않는다. 시뮬레이터 `.gitignore`에 들어 있다. 실제 자료의 행 원문은 화면이나 파일에 남기지 않는다.

v15 결과 엑셀을 v16 일괄 검토의 결과 파일로 고르면 덮어쓰지 않고 멈추므로 새 결과 경로를 고른다. v15 중간 저장 기록은 v16에서 재개에 쓰이지 않는다.
