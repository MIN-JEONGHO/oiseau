# 연구보안·연구윤리 리포트 자동 생성 프로그램 (v3)

버튼 하나로 **① AI 웹조사 → ② HTML 리포트 생성 → ③ 엑셀 누적 기록 → ④ 실행 이력 기록**까지
한 번에 처리합니다. 수집 기간은 **월간/주간** 중 고를 수 있고, 실행 시점 기준 이전 달/이전 주가
자동으로 선택됩니다.

> **v3부터 메일 발송 기능이 없습니다.** 사내 발송 권한 문제로 SMTP 연동을 제거했습니다.
> 대신 리포트는 항상 HTML 파일로 저장되며, GUI에서 "다른 이름으로 저장"으로 원하는 위치(공유
> 드라이브 등)에 내보낼 수 있습니다. 필요하다면 저장된 HTML을 열어 평소 쓰던 메일 프로그램으로
> 직접 붙여넣거나 첨부해서 보내세요.

---

## 1. 처리 흐름

```
[실행]
   ↓
① 수집   prompts/*.txt 를 LLM(웹검색 켜짐)에 보내 이슈를 JSON 으로 받아옴
   ↓      · URL 형식 검증, 대상국 검증, 국가별 건수 상한, 중복 URL 제거
② 렌더링 JSON → HTML 리포트 (기존 템플릿 디자인 그대로)
   ↓      output/security_2026-09.html 처럼 저장 (월간: YYYY-MM, 주간: YYYY-Www)
③ 엑셀 누적   data/동향_모니터링_누적.xlsx → '누적데이터' 시트에 이슈 행 추가
   ↓
④ 이력 기록   history/history.jsonl 에 이번 실행 결과(기간·건수·상태 등) 한 줄 추가
```

기존 방식(프롬프트를 붙여넣고 LLM이 HTML을 직접 편집)과 달리,
**LLM은 사실 수집만 하고 HTML 조립은 파이썬이 담당**합니다.
덕분에 태그 깨짐·플레이스홀더 잔존이 발생하지 않고, 리포트 내용과 엑셀 기록이 항상 일치합니다.

---

## 2. 설치 (Windows 기준)

두 가지 방법이 있습니다. **Python 없이 exe만 옮겨서 쓰려면 방법 B**를 쓰세요.

### 방법 A. Python으로 직접 실행 (개발·커스터마이즈에 유리)

1. [python.org](https://www.python.org/downloads/) 에서 Python 3.10 이상 설치
   (설치 화면에서 **Add Python to PATH** 체크)
2. 이 폴더에서 `최초설치.bat` 더블클릭 (`pywebview` 를 포함해 필요한 패키지를 설치합니다)
3. `실행_GUI.bat` 더블클릭 → **[설정]** 화면에서 아래 항목 입력 후 저장

### 방법 B. exe로 빌드해서 배포 (Python 설치 없이 다른 PC에서 실행)

1. 빌드용 PC에만 Python 3.10 이상 설치
2. 이 폴더에서 `build_exe.bat` 더블클릭 → `dist\연구보안연구윤리_모니터링.exe` 생성
3. 이 exe **파일 하나만** 다른 PC로 복사해도 실행됩니다(Python 설치 불필요).
   실행하면 exe가 있는 폴더에 `config.json`/`output`/`logs`/`history`/`data`가 자동으로
   생성됩니다 — exe와 그 폴더들을 통째로 옮기면 설정·이력도 그대로 이어집니다.
4. 대상 PC에 **Microsoft Edge WebView2 런타임**이 필요합니다(Windows 10 21H2 이상/Windows 11은
   기본 포함). 없으면 자동으로 기본 브라우저 창으로 열립니다.

> `실행_자동발송.bat`/`실행_자동발송_주간.bat`(작업 스케줄러 자동 실행)는 exe가 아니라
> `python run_cli.py`를 그대로 사용합니다 — 예약 실행을 쓰려면 대상 PC에도 Python이 필요합니다.

### 최초 설정 (방법 A/B 공통)

GUI를 처음 열면 **[설정]** 화면에서 **저장 위치 3가지(엑셀 누적 경로·출력물 폴더·로그
폴더)** 만 확인하고 저장하면 됩니다. 그 외에는 설정할 것이 없습니다:

* **LLM 연동**: Claude Sonnet 5.5로 고정, API 키도 내장되어 있어 화면 자체가 없습니다 — 아래 §3 참고.
* **기간모드(월간/주간)**: [설정]이 아니라 **[실행] 화면에서 실행할 때마다 선택**합니다.

---

## 3. LLM 연동 — Claude Sonnet 5.5 고정, API 키 내장

v3부터 LLM은 **Claude Sonnet 5.5(`claude-sonnet-5-5`) 하나로 고정**되어 있고, API 키도
프로그램에 **하드코딩**되어 있습니다(`rmonitor/_secrets.py`). Provider 선택, 모델 변경,
API 키 입력 화면이 전부 없습니다 — 설치 후 바로 리포트를 생성할 수 있습니다.

- 웹 검색 도구는 항상 켜져 있습니다(끌 수 없음 — 이 프로그램의 핵심 기능이라 필수).
- **temperature/top_p/top_k 는 보내지 않습니다.** Claude Sonnet 5.5는 이 파라미터들을 아예
  지원하지 않아(보내면 HTTP 400) 애초에 요청에 넣지 않도록 되어 있습니다(`rmonitor/llm.py`).
- extended thinking은 기본적으로 켜져 있는(adaptive) 모델이라, 사고 과정도 출력 토큰을
  함께 쓰는 점을 감안해 출력 토큰 하한(32,000)을 적용합니다.
- 그래도 Anthropic이 정책을 또 바꿔 특정 파라미터를 거부하면, 오류 메시지에서 문제
  파라미터를 읽어 자동으로 제거하고 즉시 재시도합니다(코드 수정 없이 흡수).

### API 키를 교체해야 할 때

1. **코드에서 직접 교체**: `rmonitor/_secrets.py` 를 열어 `ANTHROPIC_API_KEY` 값을 바꾸고
   저장(exe로 쓰는 중이면 `build_exe.bat` 로 다시 빌드).
2. **재빌드 없이 교체**: 환경변수 `RM_LLM_API_KEY` 를 지정하면 `_secrets.py` 값보다 우선
   적용됩니다.

> **보안 유의사항**: `rmonitor/_secrets.py` 는 `.gitignore` 에 등록되어 있어 git 저장소에는
> 올라가지 않지만, **exe(또는 소스 폴더)를 다른 사람/PC 에 배포하면 그 안에 하드코딩된
> API 키도 함께 넘어갑니다.** exe에서 문자열을 추출(`strings` 등)하면 키를 그대로 읽을 수
> 있으므로, 신뢰할 수 없는 대상에게 배포하지 마세요. 키가 외부에 노출된 적이 있다면
> Anthropic 콘솔에서 그 키를 폐기(rotate)하고 새 키로 교체하는 것을 권장합니다.

---

## 4. 사용법

### GUI (권장)

`실행_GUI.bat` → **[실행]** 화면

* **기간모드**: 월간/주간 토글. 자동으로 이전 달(월간) 또는 이전 주(주간, 월~일)가 선택되며,
  필요하면 우측에서 특정 월(`YYYY-MM`)이나 특정 주(`YYYY-Www`)를 직접 지정할 수 있습니다.
* **리포트 종류**: 연구보안/연구윤리 카드를 눌러 선택(복수 선택 가능)
* **엑셀 누적 기록**: 끌 수 있음
* 실행 후 결과 카드에서 **미리보기**(브라우저로 열기) / **다른 이름으로 저장**(파일 내보내기) 가능

**[설정]** 화면에서 LLM/엑셀/폴더/기본 기간모드를 관리합니다(메일 설정 없음).

**[이력]** 화면에서 지난 실행 기록을 유형·기간모드별로 필터링해 보고, **Excel로 내보내기** 로
엑셀 보고서를 만들 수 있습니다.

### 명령줄

```bash
python run_cli.py                                        # 기본 기간모드(config.json) 기준 자동 실행
python run_cli.py --period-mode monthly                  # 지난달, 활성화된 리포트 전부
python run_cli.py --period-mode weekly                   # 지난주(월~일)
python run_cli.py --report security                      # 연구보안만
python run_cli.py --period-mode monthly --month 2026-07  # 특정 월
python run_cli.py --period-mode weekly --week 2026-W27   # 특정 주(ISO)
python run_cli.py --no-excel                              # 엑셀 기록 생략
python run_cli.py --report ethics --data output/ethics_2026-07.json   # 이미 수집한 JSON 재렌더링
python run_cli.py --open                                  # 생성 후 HTML을 브라우저로 열기
python run_cli.py --history-report output/이력.xlsx        # 수집 없이 이력 엑셀 보고서만 생성
```

### 자동 실행 (Windows 작업 스케줄러)

월간·주간을 각각 독립적으로 예약할 수 있도록 배치 파일이 분리되어 있습니다.

| 배치 파일 | 트리거 예시 | 내용 |
|---|---|---|
| `실행_자동발송.bat` | 매월 1일 오전 12:05 | `run_cli.py --report all --period-mode monthly` |
| `실행_자동발송_주간.bat` | 매주 월요일 오전 08:00 | `run_cli.py --report all --period-mode weekly` |

1. 작업 스케줄러 → **작업 만들기**
2. [트리거] 새로 만들기 → 원하는 주기 선택
3. [동작] 프로그램 시작 → 위 표의 배치 파일 선택, 시작 위치는 이 폴더 경로로 지정

월간/주간을 둘 다 쓰고 싶다면 두 작업을 모두 등록하면 됩니다. 자동 실행 결과는
`logs/schedule.log` 와 `[이력]` 화면에서 확인하세요.

---

## 5. 폴더 구성

```
v3/
├─ 실행_GUI.bat / 실행_자동발송.bat / 실행_자동발송_주간.bat / 최초설치.bat / build_exe.bat
├─ 연구보안연구윤리_모니터링.spec   PyInstaller 빌드 설정(build_exe.bat 이 사용)
├─ run_gui.py            GUI 진입점(내부적으로 rmonitor/gui.py 실행)
├─ run_cli.py            명령줄 진입점(스케줄러용, exe로 패키징하지 않음)
├─ config.json           설정(최초설치 시 example 에서 복사, git 추적 제외)
├─ config.example.json   설정 템플릿
├─ ui/
│   └─ index.html        GUI 화면(정적 HTML/CSS/JS, 오프라인 동작)
├─ prompts/              ★ 조사 지시문 — 수집 범위·규칙을 바꾸려면 여기 수정
│   ├─ security_collection.txt
│   └─ ethics_collection.txt
├─ rmonitor/
│   ├─ profiles.py       ★ 리포트 디자인·카테고리·국가 목록 정의
│   ├─ collector.py      LLM 호출 + 응답 검증
│   ├─ renderer.py       JSON → HTML
│   ├─ excel_log.py      엑셀 누적 기록(수집된 이슈)
│   ├─ history.py        실행 이력 기록(history.jsonl) + 엑셀 이력 보고서 생성
│   ├─ gui.py             GUI 백엔드(로컬 HTTP 서버 + pywebview)
│   ├─ llm.py             ★ Claude Sonnet 5.5 호출(고정) — 모델 파라미터 정책은 여기
│   ├─ _secrets.py        하드코딩된 API 키(git 추적 제외, 없으면 아래 example 을 복사)
│   ├─ _secrets.example.py   API 키 템플릿(git 추적)
│   └─ config.py / pipeline.py / utils.py
├─ templates/            원본 프롬프트 txt 보관(참고용)
├─ data/
│   ├─ _양식_동향_모니터링.xlsx   원본 양식(누적 파일 최초 생성 시 복사됨)
│   ├─ 동향_모니터링_누적.xlsx    ← 실제로 쌓이는 파일(git 추적 제외)
│   └─ sample_*.json              API 없이 동작 확인용 예시 데이터
├─ history/              실행 이력(history.jsonl, git 추적 제외)
├─ output/               생성된 HTML·JSON·LLM 원문 보관(git 추적 제외)
├─ logs/                 실행 로그(git 추적 제외)
├─ build/                PyInstaller 중간 산출물(git 추적 제외)
└─ dist/
    └─ 연구보안연구윤리_모니터링.exe   build_exe.bat 실행 결과(git 추적 제외)
```

### API 키 없이 동작 확인하기

```bash
python run_cli.py --report security --period-mode monthly --month 2026-07 --data data/sample_security.json
python run_cli.py --report ethics   --period-mode weekly  --week 2026-W27  --data data/sample_ethics.json
```

`output/` 의 HTML을 브라우저로 열어 보고, `data/동향_모니터링_누적.xlsx` 와
`history/history.jsonl` 에 기록이 쌓였는지 확인하세요.

---

## 6. 엑셀 누적 규칙 (수집 이슈)

* 시트 `누적데이터`, 열 구성(v3에서 **`구분`** 열 추가):
  `번호 | 구분 | 발간일 | 국가 | 기관 | 제목 | 주요내용 | 자료 출처(URL) | n대분류 | 원문제목`
* **`구분`**: `연구보안` / `연구윤리` — 두 리포트가 같은 파일에 함께 쌓이므로 어느 쪽에서 나온
  이슈인지 엑셀에서 바로 필터링·구분할 수 있습니다.
* `번호`는 기존 마지막 번호에서 이어서 자동 부여
* **한 번 실행에서 연구보안 → 연구윤리 순서로 두 리포트를 모두 생성하면, 두 리포트의 이슈가
  모두 이어서 누적됩니다**(예: 각 3건씩 수집했다면 6행 모두 추가). 실행할 때마다 파일을 새로
  열어 마지막 행 다음부터 이어 쓰고 바로 저장하므로 앞서 쓴 내용을 덮어쓰지 않습니다.
* `자료 출처(URL)`가 이미 있는 행과 같으면 건너뜁니다(대소문자·끝 슬래시 차이는 같은 URL로
  간주) — 재실행해도 같은 이슈가 중복으로 쌓이지 않습니다. **"수집 N건 중 M건만 추가"로
  로그에 남는다면 나머지는 대부분 이미 파일에 있던(이전 실행에서 쌓인) 이슈와 URL이 같아서
  건너뛴 것**이지 놓친 게 아닙니다 — `data/동향_모니터링_누적.xlsx` 에서 직접 확인해 보세요.
  꺼두려면 `config.json` 의 `excel.skip_duplicate_url` 을 `false` 로.
* `발간일`은 발행일(실행일) 기준

## 6-1. 실행 이력 관리 (신규)

* `history/history.jsonl` — 실행 1건당 한 줄(JSON Lines)로 기록됩니다.
  보고서유형·기간모드·수집기간·이슈건수·생성일시·상태(성공/실패)·산출물 경로가 담깁니다.
* 위 §6 의 "엑셀 누적"(수집된 이슈 원문)과는 **별개**입니다 — 이쪽은 "언제 무엇을 얼마나
  생성했는지"에 대한 실행 감사 기록입니다.
* GUI **[이력]** 화면 또는 `python run_cli.py --history-report 출력.xlsx` 로 언제든 엑셀 보고서로
  내보내 확인할 수 있습니다.

---

## 7. 수집 규칙을 바꾸고 싶을 때

* **조사 범위·작성 규칙**: `prompts/*.txt` 수정 (원본 프롬프트의 규칙을 그대로 옮겨 둠)
* **카테고리·진행상태 선택지, 국가 목록, 국가당 최대 건수**: `rmonitor/profiles.py`
* **리포트 HTML 디자인**: `rmonitor/renderer.py` (기존 레이아웃 유지 — 표 기반, 인라인 스타일)
* **GUI 화면 디자인**: `ui/index.html`

### 월간/주간 문구가 자동으로 바뀌는 방식

리포트 제목·부제(`profiles.py` 의 `title_kr_tpl`/`title_en_tpl`/`subject_format`)와 종합분석
항목 라벨(`analysis_items`)은 `{mode}`/`{mode_label}` 자리표시자를 두고, 실제 리포트를 만들 때
`rmonitor/renderer.py` 가 그 자리에 "월간"/"주간"(영문은 "Monthly"/"Weekly")을 채워 넣습니다.
예: `"글로벌 연구보안 {mode} 이슈 리포트"` → 월간 실행 시 "…월간 이슈 리포트", 주간 실행 시
"…주간 이슈 리포트". 문구를 더 손보고 싶으면 이 템플릿 문자열들을 수정하면 됩니다(`{mode}` 는
그대로 남겨 두어야 함).

---

## 8. 알아둘 점

* **결과 검수는 사람이 해야 합니다.** LLM이 링크나 날짜를 잘못 가져올 수 있어,
  프로그램은 URL 형식·중복·대상국만 자동으로 걸러냅니다.
  특히 민감한 연구부정행위 사안은 원문 링크를 직접 확인하세요.
* 검증에서 제외된 항목은 로그와 `output/*.json` 의 `dropped` 목록에 남습니다.
* LLM 원문 응답은 `output/*_raw.txt` 에 저장되므로, 파싱 실패 시 원인 확인에 쓸 수 있습니다.
* 수집 결과가 0건이면 '특이사항 없음' 리포트가 생성됩니다.

---

## 9. v3 변경 사항

| 변경 | 내용 |
|---|---|
| **메일 발송 제거** | 사내 발송 권한 문제로 SMTP 연동(`mailer.py`, 설정, `--test-mail`)을 전부 제거. 리포트는 항상 HTML 파일로 저장 |
| **월간/주간 수집 기간** | `--period-mode monthly\|weekly` (GUI는 토글). 미지정 시 실행 시점 기준 이전 달/이전 주(월~일, ISO 주)를 자동 선택 |
| **실행 이력 관리** | `history/history.jsonl` 에 실행마다 기록, GUI **[이력]** 화면 및 `--history-report` 로 엑셀 보고서 생성 |
| **GUI 전면 개편** | tkinter → pywebview + 로컬 웹 화면(`ui/index.html`)으로 교체. 실행/설정/이력 3화면 구성 |
| **exe 패키징 지원** | `build_exe.bat`(PyInstaller)로 `dist\연구보안연구윤리_모니터링.exe` 단일 파일 생성. `config.json`/`output`/`logs`/`history`는 exe가 있는 폴더에 저장되므로(임시 폴더 아님) exe만 복사해도, 폴더째 옮겨도 안전하다 |
| **LLM을 Claude Sonnet 5.5로 고정 + API 키 하드코딩** | provider/모델 선택, API 키 입력 화면을 제거하고 `claude-sonnet-5-5` 하나로 고정. 키는 `rmonitor/_secrets.py`에 하드코딩(설정 화면 없음). 자세한 내용은 §3 |
| **월간/주간 문구 정비** | 리포트 제목·"핵심 요약"·종합분석 항목 라벨·무이슈 안내 문구가 실행한 기간모드에 맞게 자동으로 "월간/이달의/① 월간 트렌드" 또는 "주간/이번 주의/① 주간 트렌드"로 표시됨. 무이슈 안내는 연구보안·연구윤리 공통으로 "이번 달(또는 이번 주) 신규 이슈 없음"으로 통일 |
| **엑셀 누적에 `구분` 열 추가 + 다건 누적 확인** | 누적 파일에 `연구보안`/`연구윤리` 구분 열 추가(연구보안·연구윤리 이슈가 같은 파일에 함께 쌓이므로). 한 실행에서 여러 리포트를 생성해도 이슈가 모두 이어서 누적되는 것을 재확인·검증함(URL 중복 판정도 대소문자·끝 슬래시 차이를 흡수하도록 보강) |
| **설정 화면 최소화** | [설정]에는 저장 위치(엑셀 누적 경로·출력물 폴더·로그 폴더) 3가지만 남기고, LLM 연동·기간모드 기본값 등은 화면에서 제거(기간모드는 [실행] 화면에서 매번 선택) |

`config.json` 스키마가 v2 대비 변경되었습니다 — `smtp` 블록 제거, **`llm` 블록도 제거**(더 이상
설정 항목이 아님), `period`/`history` 블록 추가, `reports.*.recipients/cc/bcc` 제거. v2의
`config.json`을 그대로 복사해 쓸 수 없으니 `config.example.json` 기준으로 다시 설정하세요.

### 참고: Claude 모델 파라미터 정책 (`rmonitor/llm.py`)

Sonnet 5.5 전환은 [Anthropic 공식 전환 안내](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)를 기준으로 확인했습니다.

과거 v1→v2에서는 최신 Claude 모델(`claude-opus-5` 등)이 `temperature`를 거부하는 문제를
"모델명 목록"으로 판단해 여러 provider/모델을 오가며 대응했습니다. v3는 provider 선택 자체가
없어졌고 `claude-sonnet-5-5` 하나만 호출하므로, 그 모델의 정책만 정확히 반영하면 됩니다
(2026-10 기준):

| 항목 | Claude Sonnet 5.5 정책 | 반영 방식 |
|---|---|---|
| `temperature`/`top_p`/`top_k` | 아예 지원하지 않음(보내면 HTTP 400) | 요청에 처음부터 포함하지 않음 |
| extended thinking | 기본적으로 켜져 있음(adaptive). `budget_tokens` 방식은 제거(400) | `thinking: {"type": "adaptive"}` 로만 지정, 사고 과정도 쓰는 만큼 출력 토큰 하한(32,000) 적용 |
| 웹 검색 도구 | 동적 필터링 지원 최신 버전 사용 가능 | `web_search_20260209` 사용 |
| 4xx 오류 | 재시도해도 결과가 같음 | 즉시 실패 처리(429·408·5xx만 재시도) |

그래도 Anthropic이 정책을 또 바꿔 특정 파라미터를 거부하면, 오류 메시지에서 문제 파라미터를
읽어 제거하고 즉시 재시도하는 방어 로직은 남아 있습니다(`_post_pruning`, 코드 수정 없이 흡수).
`stop_reason: max_tokens`(잘린 응답)와 `stop_reason: refusal`(안전상 거부)도 감지해 원인을
표시합니다.
