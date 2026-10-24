# 연구보안 등급분류 시뮬레이터 v16

- Windows 설치형 앱 한 창에서 과제정보·고시 근거·AI 에이전트 참고 의견·HWPX 의견서 확인
- 브라우저 창·웹사이트 배포 없음. 화면 자산과 글꼴은 실행 파일 안의 로컬 자산만 사용
- 출력물은 기관 심의·의결·등급 확정을 위한 참고자료. 위원회 의결·서명·행정기관 확정을 대신하지 않음
- 실제 운영 기준은 계속 v12. v16 완료는 운영 전환이 아님
- v12~v15와 그 이전 파일은 그대로 보존. v15는 2026-10-23 인계 상태 유지

## v16에서 바뀐 것

- 화면 문구
  - 화면에만 보이는 문구를 명사형 종결 개조식으로 변경(제목·설명·안내·버튼·오류·진행 메시지)
  - 프로그램 이름 '연구보안 등급분류 시뮬레이터'로 통일. 창 제목 `연구보안 등급분류 시뮬레이터 · v16`
  - 영문 소제목·상단 표어·'研'·'연구보안 검토실' 표시 제거
  - 메뉴 5개: 01 연구개발과제 검토, 02 연구개발과제 일괄 검토, 03 검토 결과, 04 참고 고시, 05 모델·설정
- 화면 용어
  - 「연구보안 등급분류 가이드라인」 용어로 맞춤(예: 공통 검토항목→검토항목, 참고 등급→보안등급(AI 참고), 후보 제외→대상 제외)
  - 화면에만 적용. 엑셀·HWPX·저장값의 용어는 v15 그대로
- 참고 고시 화면(새 메뉴 04)
  - 고시별 카드: 고시명·고시번호·고시일·시행일·범위별 조항 수·공식 출처 주소
  - 571개 조항 검색(공백·줄바꿈·대소문자 무시), 범위 선택, 더 보기, 펼쳐서 원문 보기
  - 원문은 글자로만 표시. 외부 탐색·새 창은 v15처럼 차단
  - 검색 결과 없음은 비해당 판정이 아님
- 고시일과 새 고정본
  - 새 고정본 `kr-notices-v16-1`(`resources_v16/notices`). 출처마다 고시일(`announcement_date`) 추가
  - 원문·추출·정규화·검수 파일은 v15와 바이트까지 같음. `manifest.json`·`README.md`만 새로 작성
  - 기준본 내부 이름·확인값은 접힌 상세 정보로 이동. '확인일'은 '원문 수집일'로 이름 변경
- 화면-프로그램 연결 함수 9개→11개: 읽기 전용 `search_notice_clauses`, `get_notice_clause` 추가
- 가이드라인 창: 법·시행령·가이드라인 원문 그대로 표시(표시 전용)
- 저장 결과 schema 3. v15(schema 2) 이하 결과·중간 저장은 재사용·재출력하지 않음
- 결과 엑셀 `고시기준본` 시트에 `고시일` 열 추가(`시행일` 바로 앞). HWPX 출처 부록에 고시일 줄 추가
- 일괄 검토에서 이전 버전 결과 보호
  - 고른 결과 엑셀이 v16 결과가 아닌 기존 파일이거나 중간 저장에 v15·v14 기록이 있으면 쓰기 전 중단
  - 재개 여부와 무관. 기존 중간 저장·결과 엑셀·감사 기록은 그대로 남음
  - 화면 안내: '기존 결과 파일 보호를 위해 중단. 새 결과 엑셀 경로 선택 필요'

## 판정 방식 동일

- 분류 규칙·산식·상태 판정·고시 조건 해석·AI 지시문(시스템 지시문과 요청 구성)은 v15와 같음
- 결과에 저장되는 프로그램 문장(미해결 사유·부족정보 질문·오류 사유 등)과 AI 의견 문체도 v15 그대로
- v15와 같은 결과는 보장하지 않음
  - 새 고정본 때문에 AI에 함께 보내는 고시 정보(기준본 이름·확인값·출처별 날짜)가 달라짐
  - 같은 과제라도 AI 응답과 결과가 v15와 다를 수 있음

## 고시 기준본

| 범위 | 고시 | 고시일 | 시행일 |
| --- | --- | --- | --- |
| 국가첨단전략기술 | 산업통상자원부고시 제2025-71호 | 2025-05-12 | 2025-05-18 |
| 국가핵심기술 | 산업통상부고시 제2025-2호 | 2025-10-02 | 2025-10-02 |
| 전략물자 이중용도·군용 | 산업통상부고시 제2026-101호 별표 2·3 | 2026-08-31 | 2026-09-01 |

- 기준본 ID `kr-notices-v16-1`, 기준본 지문(manifest 정규 해시) `ed1cd61bda96d7e8fb577fd91561407fb5331f15304c5c297ebf150715952d6b`
- 출처·원문·검수 범위: [고시 기준본 설명](resources_v16/notices/README.md)
- 조항 571개(지정·통제 검토단위 507개, 공통 정의·주석 64개). 원문 보존과 자동 조건해석 지원 범위는 다름
- 관련 미해석 조건·부족한 사양은 `정보 부족`으로 남김. 고시 대조 결과가 보안등급이나 수출허가를 자동 결정하지 않음
- 실행 중 웹 갱신 없음. 해시·검수 자료가 다르면 시작 거부

## 실행 환경과 설치

- 확인 환경: Windows AMD64, Python 3.14.6, pywebview 6.2.1, Microsoft Edge WebView2 Runtime
- PC에 WebView2 Runtime과 .NET Framework 4.6.2 이상 필요. WebView2Loader.dll 포함이 런타임 설치를 대신하지 않음
- 의존성은 v15와 같음(`requirements_v15.txt`). v16 전용 requirements 없음
- 아래 명령의 `$PY`는 검증에 쓴 Python 경로. 새로 만든 환경이면 그 환경의 `python.exe`로 바꿔 사용

```powershell
$PY = 'C:\Users\민정호-PC\Documents\GitHub\oiseau\dev\보안등급분류 시뮬레이터\.dryforge\implementation\.dryforge\env-v15\Scripts\python.exe'
# 새 환경을 만들 때
python -m venv .venv_v16
.\.venv_v16\Scripts\python.exe -m pip install -r requirements_v15.txt
# 소스 실행(프로젝트 폴더에서)
& $PY -X utf8 -B .\security_grade_classifier_v16.py
```

- WebView2를 쓸 수 없으면 고정 설치 안내 후 종료. 구형 Internet Explorer 엔진으로 전환하지 않음

## 사용 순서

1. **05 모델·설정**: 모델 선택(Claude Sonnet 5.5 `claude-sonnet-5-5`, OpenAI GPT-6 Luna `gpt-6-luna`, Ollama, LM Studio)
   - 외부 모델 키는 현재 Windows 계정 자격 증명 관리자에 제공자별 자동 저장, 다음 실행에 재사용
   - 화면에는 저장 여부만 표시. 저장됨 표시는 인증 성공이 아님
2. **01 연구개발과제 검토**: 과제명·요약 입력. 현재 기술사양과 개발목표 사양 구분 입력
   - 법적 정의·기준 체크리스트 또는 국가영향 수준 지표 중 하나 선택
   - 검토항목 자동 선정 시 선택 항목 가중치 모두 1.0. 직접 선정 시 0.8~1.2, 평균 1.0 검사
   - 마지막 의견 엄격도는 항상 표준
3. AI 에이전트 1명(AI 기술분야 전문가) 또는 3명(AI 연구보안 전문가·AI 기술사업화 전문가 추가)의 독립 의견 확인
4. **03 검토 결과**: 근거·부족정보·에이전트 의견·저장 상태 확인. 저장 결과로 의견서 재생성 가능
5. **04 참고 고시**: 고시별 정보 확인, 조항 원문 검색
6. **02 연구개발과제 일괄 검토**: 9열 입력 엑셀(`분류대상` 시트, `과제명` 필수)과 입력과 다른 새 결과 경로 선택
   - 결과: 결과 엑셀(5개 시트), `<결과경로>.checkpoint.jsonl`, `<결과경로>.audit.jsonl`, 의견서 폴더
   - 재개는 과제 내용·옵션·모델·가이드라인·고시 지문이 일치하는 v16 완료 결과만 재사용
   - v15 결과 엑셀을 결과 경로로 고르면 쓰기 전 중단. 새 결과 경로 선택 필요

입력 양식 만들기:

```powershell
& $PY -X utf8 -B -c "from batch_v16 import make_template; make_template('입력양식_v16.xlsx')"
```

## 자료와 API 키

- 선택한 외부 모델에 과제요약·기술사양·추가 검토정보·부처 기준·판단에 필요한 고시 근거 전송. v15와 같은 범위
- 외부 전송 불가 자료는 기관에서 허용한 로컬 모델 사용
- 키 원문은 소스·설정·배포 파일·결과·로그에 저장하지 않음. 환경변수 키는 자동 영구 저장하지 않음
- 참고 고시 검색·원문 보기는 읽기 전용. 파일·키·작업 상태를 바꾸지 않고 모델을 부르지 않음

## 시험·빌드·자체 확인

프로젝트 폴더(`dev/보안등급분류 시뮬레이터/`)에서 실행.

```powershell
& $PY -m unittest discover -s tests -p "test_v16_*.py"
& $PY -m unittest discover -s tests -p "test_v15_*.py"
& $PY -m unittest discover -s tests -p "test_v14_*.py"
& $PY -m py_compile security_grade_classifier_v16.py desktop_bridge_v16.py v16_domain.py notice_catalogue_v16.py notice_review_v16.py classification_v16.py batch_v16.py hwpx_writer_v16.py llm_client_v14.py credential_store.py
& $PY security_grade_classifier_v16.py --self-check build-v16/source-self-check.json
& $PY -m PyInstaller --noconfirm --workpath build-v16 --distpath dist-v16 '보안등급분류시뮬레이터_v16.spec'
$check = Start-Process -FilePath '.\dist-v16\보안등급분류시뮬레이터_v16.exe' -ArgumentList '--self-check', '.\build-v16\frozen-self-check.json' -WindowStyle Hidden -PassThru -Wait
$check.ExitCode
Get-Content -LiteralPath '.\build-v16\frozen-self-check.json' -Encoding UTF8
```

- 실행 파일: `dist-v16/보안등급분류시뮬레이터_v16.exe`. `build-v16/`·`dist-v16/`는 커밋하지 않음
- 자체 확인은 숨긴 WebView2 창에서 합성 과제·가짜 키 저장소·가짜 모델 사용. 실제 키·유료 API 사용 없음
- 판정 기준: 실제 종료 코드 0과 새 보고서의 `pass:true`. 실행 파일은 `frozen:true`도 확인
- v16 자체 확인 추가 범위: 새 함수 2개 정상 응답, 잘못된 인자 거부, 진행 중 작업이 있을 때 호출, 허용 목록 정확히 11개
- 실행 파일에 묶는 것: `ui_v16/` 전체와 폰트 라이선스, `resources_v16/notices` 25개 파일, `templates/v15/` 파생 서식 2개, 아이콘, 모델 SDK와 WebView2 구성요소
- 묶지 않는 것: v15 실행 모듈 8개, v14 이하 실행 모듈, `ui_v15/`·`resources_v15/`, `tests/`·`tools/`, PyMuPDF·Playwright, PySide6·pandas, `…_claude.py`·`embedded_key.py`, 가이드라인 원본, 실제 입력·감사·중간 저장

## 실제로 확인한 것 (2026-10-24, 작업 사본)

- 모두 합성 과제·모의 모델·가짜 키 저장소 사용. 각 명령의 실제 종료 코드로 판단
- 회귀시험(종료 코드 모두 0)
  - v16 393개 통과(`test_v16_*`, 새 통합 시험 17개 포함)
  - v15 279개, v14 134개 통과(손대지 않은 이전 버전 회귀)
  - 총 805개
- 문법 검사: v16 실행 경로 8개 파일과 `llm_client_v14.py`·`credential_store.py`의 `py_compile` 종료 코드 0
- 지시문 동일(`tests/test_v16_integration.py`)
  - v15 브리지와 v16 브리지에 같은 합성 과제를 단건·일괄로 넣고 모의 모델이 받은 요청 비교
  - 시스템 지시문 바이트 일치. 사용자 요청은 기준본 파생값(기준본 ID·지문·비교 ID·옵션 지문) 치환과 manifest·고시일 정규화 뒤 일치
  - 설치 기준본(`resources_v15/notices`와 `resources_v16/notices`) 단건 흐름도 같은 방식으로 일치
  - 저장 문장 동일은 배치·HWPX 단위 시험(`test_v16_batch.py`·`test_v16_hwpx.py`)에서 확인
- 문체 검사: 브리지 고정 오류·진행 문구, 호스트 시작 안내, 배치 경고·상태 문구, 분류·고시 대조 진행 문구, `ui_v16` 화면 문구에서 '니다·세요·주세요·해요·어요·아요·에요·예요·까요' 종결 없음
- 가져오기 경계: v16 실행 모듈은 v15·v14 모듈을 가져오지 않음(`llm_client_v14`만 예외)
- 소스 자체 확인: `security_grade_classifier_v16.py --self-check` 종료 코드 0, `pass:true`
- 빌드: PyInstaller 6.21.0 종료 코드 0
- 실행 파일 자체 확인(숨김 실행): 종료 코드 0, `pass:true`, `frozen:true`, WebView2 155.0.4283.62
- 실행 파일 묶음 목록(PyInstaller 아카이브 직접 열람)
  - 프로젝트 자산 33개(`ui_v16` 5개·폰트 라이선스 포함, 고시 25개, 파생 서식 2개, 아이콘) 포함, 원본과 바이트 일치
  - 프로젝트 모듈은 v16 실행 모듈 8개와 `credential_store`·`llm_client_v14`만 포함
  - v15 실행 모듈 8개, v14 이하 실행 모듈, `ui_v15`·`resources_v15`, `tests`·`tools`, PyMuPDF·Playwright·PySide6·pandas, `…_claude`·`embedded_key`, `.dryforge`·가이드라인 파일 없음
- 확인한 실행 파일: 42,079,521바이트, SHA256 `c7f918f03275eb331ebf929df06613b375c4a90b78063e880f671c1b00b5690d`
  - 통합 브랜치에서 빌드한 파일. 다시 빌드하면 해시가 달라질 수 있음

## 미확인

- 한글 프로그램에서 HWPX 실열람·인쇄
- 전경 화면 확인(사용자 화면에서 앱 직접 조작)
- 실제 Windows 125%·150% 배율 화면
- 실제 유료 모델 호출(외부 API 인증·실제 모델 응답)
- 사유: 사용자가 데스크톱 제어를 멈춰 둔 상태. 숨긴 자체 확인과 headless Edge 시험은 위 항목을 대신하지 않음
