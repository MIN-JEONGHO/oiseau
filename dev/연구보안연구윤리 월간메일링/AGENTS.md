# 연구보안·연구윤리 동향 리포트

해외 연구보안·연구윤리 동향을 월간(직전 달) 또는 주간(직전 주 월~일)으로 AI 웹조사해 모은다. 결과는 HTML 리포트, 누적 엑셀, 실행 이력이다. 폴더 이름은 '월간메일링'이지만 v3부터 메일 발송 기능이 없다.

## 범위
- **현재 버전**: `v4/`(`rmonitor/__init__.py`의 `__version__ = "4.0.0"`, 모델 `claude-sonnet-5-5`).
- **보존만 하는 폴더**(수정·삭제 금지)
  - `v1/`, `v2/`: SMTP 메일 발송판. `config.json`에 LLM 키와 SMTP 비밀번호가 평문으로 들어 있다.
  - `v3/`: Sonnet 5.5 전환판
- `v4/dist`의 exe 이름은 `연구보안연구윤리_모니터링v5.exe`지만, 프로그램 표기는 4.0.0이다.

## 구조 (현재 버전)
- `run_gui.py` → `rmonitor/gui.py`: 127.0.0.1 임의 포트 HTTP 서버와 pywebview 창. 화면은 `ui/index.html`이며 실행·설정·이력 세 화면이다.
- `run_cli.py`: 명령줄과 예약 실행. 실행 배치는 `실행_자동발송.bat`·`실행_자동발송_주간.bat`이다.
- `rmonitor/pipeline.py`: 리포트별로 수집 → 렌더링 → 누적 → 이력을 진행한다. `--data`면 수집을 건너뛴다.
- `rmonitor/collector.py`
  - `build_prompt()`: `prompts/*.txt`의 `{{START_DATE}}` 같은 자리표시자를 채운다.
  - `normalize()`: 응답 JSON을 검증·정규화한다.
- `rmonitor/llm.py`: Anthropic Messages API 호출(`requests`). 키·모델·요청 정책이 여기 있다.
- `rmonitor/renderer.py`: JSON → HTML(표 기반, 인라인 스타일). `{mode}`·`{mode_label}` 자리를 채운다.
- `rmonitor/profiles.py`: 리포트 두 종류의 정의
  - 국가 목록, 카테고리·진행상태 목록, 국가별 상한
  - 제목 문구 템플릿, 분석 항목
- `rmonitor/excel_log.py`: 누적 엑셀. `rmonitor/history.py`: `history.jsonl`과 이력 엑셀
- `rmonitor/config.py`: `config.json` 읽기와 저장(기본값과 합침). `rmonitor/utils.py`: 기간(`Period`), JSON 추출, URL 검사
- `rmonitor/_secrets.py`(커밋 금지)·`_secrets.example.py`(견본)
- `prompts/`: 실제로 쓰는 수집 지시문. `templates/`: 예전 원본 프롬프트(참고용)
- `data/_양식_동향_모니터링.xlsx`: 누적 파일 양식. `data/sample_*.json`: API 없이 확인하는 예시

## 경계
- 키는 `rmonitor/_secrets.py`와 환경변수 `RM_LLM_API_KEY`(우선)에서만 읽는다. `config.json`·화면·로그·출력에 키를 쓰지 않는다. `_secrets.py`를 시험 자료로 읽거나 출력하지 않는다.
- 모델·도구 버전·요청 매개변수는 `llm.py` 상수에서만 정한다(`MODEL`, `WEB_SEARCH_TOOL_TYPE`, `MAX_TOKENS_FLOOR`). 설정 파일이나 화면에 모델 선택을 만들지 않는다.
- 메일 발송(SMTP) 코드를 다시 들이지 않는다. 다시 넣으려면 사용자의 결정이 먼저다.
- HTML 조립은 `renderer.py`의 일이다. 프롬프트로 LLM이 HTML을 만들게 하지 않는다.
- 읽기 전용 번들 자원(`prompts`, 양식, 화면)과 쓰기 가능한 앱 폴더를 섞지 않는다. 쓰기 가능한 앱 폴더는 exe 옆의 `config.json`·`output`·`logs`·`history`·`data`다. exe로 실행하면 번들 자원은 임시 폴더에 풀리므로 그곳에 쓰면 사라진다.
- 서버 바인딩을 127.0.0.1 밖으로 넓히지 않는다. 화면에 외부 CDN·웹폰트를 쓰지 않는다.

## 지켜야 할 것
- **요청**
  - `temperature`·`top_p`·`top_k`를 넣지 않는다.
  - thinking은 `{"type": "adaptive"}`만 쓴다.
  - 출력 상한 하한은 32,000이다.
  - 웹 검색 도구는 항상 켠다(`max_uses` 20).
  - 4xx는 다시 시도하지 않는다(429·408·5xx만 재시도).
  - `_post_pruning`은 400 오류 문구에서 거부된 매개변수를 읽어 빼고 다시 보낸다. 다만 `_STRIPPABLE = ("thinking",)`이라 `thinking`에만 적용된다. 이 동작을 유지하고, 다른 매개변수가 거부되면 재시도 없이 실패한다는 점을 전제로 둔다.
  - `stop_reason`이 `max_tokens`·`refusal`이면 원인을 드러낸다.
- **응답 처리**
  - 원문은 `output/<리포트>_<기간>_raw.txt`에 먼저 저장한 뒤 파싱한다.
  - `normalize()`를 통과한 이슈만 렌더링·누적한다. 뺀 이슈는 `dropped`에 사유와 함께 남긴다.
  - `normalize()`는 빈 카테고리를 첫 카테고리로, 빈 진행상태(연구윤리만 `has_status`)를 '정책 발표'로 채운다. 목록 밖의 값은 바꾸지 않고 그대로 통과시킨다.
- **누적 엑셀**
  - 마지막 행 다음에 이어 쓰고 바로 저장한다. 기존 행을 덮어쓰지 않는다.
  - 같은 출처 URL은 건너뛴다(대소문자·끝 슬래시 무시, `excel.skip_duplicate_url`).
  - 열 순서 `번호 | 구분 | 발간일 | 국가 | 기관 | 제목 | 주요내용 | 자료 출처(URL) | n대분류 | 원문제목`을 바꾸지 않는다. 이미 쌓인 파일과 어긋난다.
- **기간**: 월간 태그는 `YYYY-MM`, 주간 태그는 ISO 주 `YYYY-Www`(월~일)다. 지정하지 않으면 직전 기간이다.
- **명령줄**: 리포트 하나라도 실패하면 종료 코드 1이다(예약 실행 로그에서 실패를 알아보는 기준).
- **예약 실행 배치**: 출력을 `logs\schedule.log`로 넘기는데 cmd는 폴더를 만들지 않는다. 소스 폴더에 `logs`가 없으면 첫 예약 실행이 기록 없이 실패한다.
- **설정 파일**
  - `config.py`는 모르는 항목도 기본값에 합친다. `gui.py`의 `GET /api/config`는 설정 전체를 화면으로 보내고, `POST`는 받은 그대로 저장한다.
  - 그래서 v1·v2의 `config.json`(평문 키·SMTP 비밀번호)을 이 버전으로 옮기면 그 값이 화면에 나오고 계속 저장된다. 옮기지 않는다.

## 시험
- 자동 시험은 없다. API 없이 확인할 때는 `v4` 폴더를 임시 위치로 복사하고 그 복사본에서 실행한다. 실제 누적 파일과 이력을 오염시키지 않기 위해서다.
  ```
  python run_cli.py --report security --period-mode monthly --month 2026-07 --data data/sample_security.json
  python run_cli.py --report ethics --period-mode weekly --week 2026-W27 --data data/sample_ethics.json
  ```
  `output`의 HTML(월간·주간 문구 치환), 누적 엑셀 행과 중복 건너뛰기, `history.jsonl` 한 줄 추가를 확인한다.
- 수집·검증을 고쳤으면 LLM 호출을 모킹해 확인한다.
  - 대상 밖 국가, 제목 없음, 잘못된 URL, 중복 URL
  - 국가별 상한 초과, 빈 카테고리·목록 밖 카테고리(그대로 남는지), 0건 응답
  - JSON이 아닌 응답, `max_tokens` 응답
- 실제 API 호출은 사용자가 그 작업에서 요청할 때만 한다. 업무 자료가 없는 확인용 프롬프트로 하며, 키를 출력하지 않는다. 실패를 성공으로 보고하지 않는다.
- 빌드: 이 폴더에서 `build_exe.bat`을 실행한다(배치에 폴더 이동이 없음) → `dist\연구보안연구윤리_모니터링.exe`. exe 안에 내장 키가 들어간다.
