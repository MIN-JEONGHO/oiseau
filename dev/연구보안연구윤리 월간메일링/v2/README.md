# 연구보안·연구윤리 월간 리포트 자동 발송 프로그램

버튼 하나로 **① AI 웹조사 → ② HTML 리포트 생성 → ③ 메일 발송 → ④ 엑셀 누적 기록**까지
한 번에 처리합니다.

---

## 1. 처리 흐름

```
[실행 버튼]
   ↓
① 수집   prompts/*.txt 를 LLM(웹검색 켜짐)에 보내 이슈를 JSON 으로 받아옴
   ↓      · URL 형식 검증, 대상국 검증, 국가별 건수 상한, 중복 URL 제거
② 렌더링 JSON → G-Cloud 호환 HTML (기존 템플릿 디자인 그대로)
   ↓      output/security_2026-07.html 로 저장
③ 발송   SMTP(Gmail·네이버 등)로 수신자에게 HTML 메일 발송
   ↓      (기본값: 미리보기 확인 후 발송)
④ 기록   data/동향_모니터링_누적.xlsx → '누적데이터' 시트에 행 추가
```

기존 방식(프롬프트를 붙여넣고 LLM이 HTML을 직접 편집)과 달리,
**LLM은 사실 수집만 하고 HTML 조립은 파이썬이 담당**합니다.
덕분에 태그 깨짐·플레이스홀더 잔존이 발생하지 않고, 메일 본문과 엑셀 기록이 항상 일치합니다.

---

## 2. 설치 (Windows 기준)

1. [python.org](https://www.python.org/downloads/) 에서 Python 3.10 이상 설치
   (설치 화면에서 **Add Python to PATH** 체크)
2. 이 폴더에서 `최초설치.bat` 더블클릭
3. `실행_GUI.bat` 더블클릭 → **[설정]** 탭에서 아래 항목 입력 후 저장

| 항목 | 설명 |
|---|---|
| Provider / 모델 / API 키 | 아래 3-1 참조 |
| 메일 서비스 | gmail / naver / daum / outlook / custom |
| 계정·비밀번호 | 아래 3-2 참조 |
| 수신자 | 리포트별로 쉼표 구분 입력 |

---

## 3. 사전 준비

### 3-1. AI(LLM) API 키

| provider | 준비물 | 비고 |
|---|---|---|
| `gemini` (기본) | Google AI Studio API 키 | 모델 예: `gemini-2.5-pro` |
| `vertex` | GCP 프로젝트 + `gcloud auth login` | `config.json` 의 `llm.gcp_project` 필요 |
| `anthropic` | Anthropic API 키 | 모델 예: `claude-opus-5`, `claude-sonnet-5` |
| `openai` | OpenAI API 키 | 모델 예: `gpt-4.1` |

어느 쪽이든 **웹 검색 도구가 켜진 상태로 호출**됩니다(`enable_web_search: true`).
웹 검색을 지원하지 않는 모델을 지정하면 조사가 불가능하니 주의하세요.

> **모델명은 정확히 입력해야 합니다.** 예를 들어 `opus-5` 는 존재하지 않는 이름이라
> `HTTP 404: model: opus-5` 로 실패합니다. 올바른 이름은 `claude-opus-5` 입니다.

#### temperature 설정에 대해

`claude-opus-5`, `claude-sonnet-5`, `claude-opus-4-7/4-8` 등 최신 Claude 모델은
`temperature` 파라미터를 **아예 받지 않습니다**(요청하면 HTTP 400).
v2 는 모델명을 보고 이런 모델에는 처음부터 `temperature` 를 보내지 않으며,
목록에 없는 신규 모델이 거부하더라도 오류 메시지를 읽고 해당 항목만 빼서 자동으로 다시
호출합니다. 따라서 `config.json` 의 `llm.temperature` 는 그대로 두어도 되고,
구형 모델(`claude-sonnet-4-5`, Gemini 등)에서는 계속 적용됩니다.

### 3-2. 메일 계정

* **Gmail**: 2단계 인증을 켠 뒤 [앱 비밀번호] 16자리를 발급받아 비밀번호 칸에 입력
  (일반 계정 비밀번호로는 로그인되지 않습니다)
* **네이버**: 메일 → 환경설정 → POP3/IMAP 설정 → **SMTP 사용 ON**,
  2단계 인증을 쓰면 애플리케이션 비밀번호 사용
* 사내 메일 서버라면 `custom` 선택 후 호스트/포트/보안방식 직접 입력

> 비밀번호를 파일에 저장하고 싶지 않다면 환경변수를 쓰세요.
> `RM_SMTP_USER`, `RM_SMTP_PASSWORD`, `RM_LLM_API_KEY` 가 `config.json` 값보다 우선합니다.

설정을 마쳤으면 먼저 발송 점검을 권합니다.

```
python run_cli.py --test-mail
```

---

## 4. 사용법

### GUI (권장)

`실행_GUI.bat` → **[실행]** 탭

* **수집 대상 월**: 비우면 지난달. `2026-07` 처럼 직접 지정 가능
* **메일 발송 / 엑셀 누적 기록**: 개별로 끌 수 있음
* **발송 전 미리보기·확인**: 켜두면 브라우저로 리포트를 열어 보여준 뒤 발송 여부를 물어봄
  (실수 발송 방지를 위해 기본 ON)
* 처음에는 **메일 발송 체크를 끄고** 한 번 돌려 결과 HTML을 확인해 보세요.

### 명령줄

```bash
python run_cli.py                        # 지난달, 두 리포트 모두 수집·발송
python run_cli.py --report security      # 연구보안만
python run_cli.py --month 2026-07        # 특정 월
python run_cli.py --no-send              # 발송 없이 HTML 미리보기만 생성
python run_cli.py --no-excel             # 엑셀 기록 생략
python run_cli.py --report ethics --data output/ethics_2026-07.json
                                         # 이미 수집한 JSON으로 재렌더링·재발송
python run_cli.py --test-mail            # SMTP 점검용 테스트 메일
```

### 매월 자동 실행 (Windows 작업 스케줄러)

1. 작업 스케줄러 → **작업 만들기**
2. [트리거] 새로 만들기 → 매월 → 1일 → 오전 12:05
3. [동작] 프로그램 시작 → `실행_자동발송.bat` 선택,
   시작 위치는 이 폴더 경로로 지정
4. 연구윤리를 2일에 따로 보내려면 트리거를 나눠 두 개의 작업으로 만들고,
   각각 `run_cli.py --report security` / `--report ethics` 를 실행하도록 배치 파일을 복사·수정

> 자동 실행 시에는 미리보기 확인 없이 곧바로 발송됩니다.
> 첫 1~2개월은 수동 실행으로 결과를 확인한 뒤 스케줄러에 등록하는 편을 권합니다.

---

## 5. 폴더 구성

```
research_monitor/
├─ 실행_GUI.bat / 실행_자동발송.bat / 최초설치.bat
├─ run_gui.py            GUI 진입점
├─ run_cli.py            명령줄 진입점(스케줄러용)
├─ config.json           설정(최초설치 시 example 에서 복사)
├─ prompts/              ★ 조사 지시문 — 수집 범위·규칙을 바꾸려면 여기 수정
│   ├─ security_collection.txt
│   └─ ethics_collection.txt
├─ rmonitor/
│   ├─ profiles.py       ★ 리포트 디자인·카테고리·국가 목록 정의
│   ├─ collector.py      LLM 호출 + 응답 검증
│   ├─ renderer.py       JSON → HTML
│   ├─ mailer.py         SMTP 발송
│   ├─ excel_log.py      누적 엑셀 기록
│   ├─ llm.py / config.py / pipeline.py / utils.py
├─ templates/            원본 프롬프트 txt 보관(참고용)
├─ data/
│   ├─ _양식_동향_모니터링.xlsx   원본 양식(누적 파일 최초 생성 시 복사됨)
│   ├─ 동향_모니터링_누적.xlsx    ← 실제로 쌓이는 파일
│   └─ sample_*.json              API 없이 동작 확인용 예시 데이터
├─ output/               생성된 HTML·JSON·LLM 원문 보관
└─ logs/                 실행 로그
```

### API 키 없이 동작 확인하기

```bash
python run_cli.py --report security --month 2026-07 --no-send --data data/sample_security.json
python run_cli.py --report ethics  --month 2026-07 --no-send --data data/sample_ethics.json
```

`output/` 의 HTML을 브라우저로 열어 보고, `data/동향_모니터링_누적.xlsx` 에 행이 쌓였는지 확인하세요.

---

## 6. 엑셀 누적 규칙

* 시트 `누적데이터`, 열 구성은 원본 양식 그대로:
  `번호 | 발간일 | 국가 | 기관 | 제목 | 주요내용 | 자료 출처(URL) | n대분류 | 원문제목`
* `번호`는 기존 마지막 번호에서 이어서 자동 부여
* `자료 출처(URL)`가 이미 있는 행과 같으면 건너뜁니다
  (재실행해도 중복이 쌓이지 않음 — `config.json` 의 `skip_duplicate_url` 로 끌 수 있음)
* `발간일`은 발행일(실행일) 기준

---

## 7. 수집 규칙을 바꾸고 싶을 때

* **조사 범위·작성 규칙**: `prompts/*.txt` 수정 (원본 프롬프트의 규칙을 그대로 옮겨 둠)
* **카테고리·진행상태 선택지, 국가 목록, 국가당 최대 건수**: `rmonitor/profiles.py`
* **메일 디자인**: `rmonitor/renderer.py`
  (G-Cloud 제약 유지 — `<style>`·class·미디어쿼리·`border-radius`·`<ul>`·`<hr>`·`<h1~h6>` 사용 금지,
   모든 CSS는 인라인)

---

## 8. 알아둘 점

* **결과 검수는 사람이 해야 합니다.** LLM이 링크나 날짜를 잘못 가져올 수 있어,
  프로그램은 URL 형식·중복·대상국만 자동으로 걸러냅니다.
  발송 전 미리보기 확인을 켜 두고, 특히 민감한 연구부정행위 사안은 원문 링크를 직접 확인하세요.
* 검증에서 제외된 항목은 로그와 `output/*.json` 의 `dropped` 목록에 남습니다.
* LLM 원문 응답은 `output/*_raw.txt` 에 저장되므로, 파싱 실패 시 원인 확인에 쓸 수 있습니다.
* 수집 결과가 0건이면 '특이사항 없음' 리포트가 생성됩니다.

---

## 9. v2 변경 사항 (`rmonitor/llm.py`)

v1 을 최신 Claude 모델(`claude-opus-5` 등)로 돌리면 아래 오류로 100% 실패했습니다.

```
HTTP 400: {"type":"invalid_request_error","message":"`temperature` is deprecated for this model."}
```

| 변경 | 내용 |
|---|---|
| **temperature 자동 처리** | 최신 모델에는 처음부터 보내지 않음. 목록에 없는 신규 모델이 거부해도 오류 메시지에서 문제 파라미터를 읽어 제거 후 즉시 재호출 (`top_p`·`top_k`·`thinking` 도 동일) |
| **4xx 즉시 실패** | v1 은 400/404 를 3회 반복해 시간만 낭비했습니다. 이제 요청 오류는 1회로 끝내고, 500·429·타임아웃만 재시도합니다 |
| **web_search 도구 버전** | 모델에 맞는 버전을 선택하고(`web_search_20260209` / `20250305`), 거부되면 구버전으로 1회 자동 대체 |
| **잘린 응답 감지** | `stop_reason: max_tokens` 를 잡아 "출력 길이에서 잘렸다"고 알려줍니다. v1 은 잘린 JSON 이 그대로 파서로 넘어가 엉뚱한 오류가 났습니다 |
| **거부 응답 감지** | `stop_reason: refusal` (안전상 거부)을 사유와 함께 표시 |
| **출력 토큰 하한** | `claude-opus-5` 계열은 사고 과정도 `max_tokens` 를 함께 쓰므로 최소 32,000 토큰을 확보 |

`config.json` 형식은 v1 과 100% 동일합니다. v1 폴더의 `config.json` 을 그대로 복사해 써도 됩니다.
