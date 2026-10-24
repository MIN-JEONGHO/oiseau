# 제재통계

NTIS 제재정보 rawdata 하나로 국가R&D 제재통계 두 가지를 만든다.
- 연구수행 기준: 과제 단위, 총연구기간 연도 축. 원본은 `제재정보분석.workflow`다.
- 처분연도 기준: 제재 레코드 단위, 처분연도 축. 원본은 `월별통계 제재통계 자동 분석.xlsx`다.

결과는 각각 엑셀 집계표와 hwpx 표준양식이다. 두 통계의 숫자가 서로 맞지 않는 것이 정상이다.

## 범위
- **현재 버전**: `통계v6/`(`app.py`의 `APP_VERSION = "v1.1.1"`).
- **보존만 하는 것**(수정·삭제 금지, 더 이상 쓰지 않음)
  - 맨 위의 `sanction_stats.py`·`README.md`·`원자료_입력템플릿.xlsx`: 단독 9시트 스크립트
  - `복합통계v1/`, `복합통계v2/`, `통계v2/`~`통계v5/`

## 구조 (현재 버전)
- `app.py`: 127.0.0.1 임의 포트 `ThreadingHTTPServer`, `ui/index.html`과 `/api/*`를 제공한다. 엔드포인트는 `state`, `upload`, `analyze`, `export`, `pick-folder`, `set-path`, `download-bundled`, `reveal`, `open`, `quit`이다.
  - 분석은 탭(kind)별 작업 스레드에서 돈다. 두 탭의 결과는 서로 지우지 않는다.
  - 연구수행 기준 검산 4종은 여기(`_cause_integrity()`)에서만 계산한다.
  - 내장 파일 내려받기(`download_bundled()`)는 저장 폴더의 `참조데이터_기본값.xlsx`·`연구수행기준_표준양식.hwpx`·`처분연도기준_표준양식.hwpx`를 묻지 않고 덮어쓴다.
  - 소스 실행에서 pywebview가 없으면 기본 브라우저로 연다.
- `sanction_pipeline.py`: 연구수행 기준
  - 헤더 탐지(`detect_header_row`) → python-calamine으로 한 행씩 읽으며 필요한 열만 담기 → `transform` → `preprocess` → `analyze_periods` → `aggregate` → `load_reference`
  - 열 별칭 `REQUIRED_COLUMNS`·`OPTIONAL_COLUMNS`. 소관부처·부처명 둘 다 없으면 `KeyError`로 멈춘다
  - 부처 개편 표 `MINISTRY_RENAME_CONFIRMED`·`MINISTRY_RENAME_INFERRED`와 연쇄 해석 `resolve_rename_chains()`
- `monthly_pipeline.py`: 처분연도 기준
  - 11열 `preprocess`(`parse_money` 포함) → `AXES`(`AxisSpec`) 기반 표 → `integrity`·`cross_checks`
  - 열 별칭 `M_REQUIRED`·`M_OPTIONAL`(연구수행 기준 사전과 따로 있음)
  - 분류 상수: `REASON_GROUPS`, `ORG_LABELS`, `ORG_ALIAS`, `MINISTRY_LABELS`
- `excel_writer.py`·`hwpx_writer.py`: 연구수행 기준 출력. `monthly_excel.py`·`monthly_hwpx.py`: 처분연도 기준 출력
  - `hwpx_writer.py`는 양식의 **첫 번째 표**를 쓰고, 머리 행 다음의 7행 블록(`BLOCK_ROWS`, `ROW_MINISTRY_START`)을 부처마다 복제한다.
  - `monthly_hwpx.py`는 양식의 표를 **문서 순서대로** 통계 1~9번에 대응시킨다(`zip(tbls, stats)`). 표가 9개보다 적을 때만 멈춘다.
- `run_report.py`: 연구수행 기준 명령줄(기본 접두어 `제재처분집계`). 검산은 하지 않는다. `--template`이 없으면 rawdata 폴더·현재 폴더·출력 폴더의 아무 `*.hwpx`나 양식으로 집는다(세 폴더 모두 없을 때만 내장 `template.hwpx`)
- `ui/index.html`: 화면 전체 단일 파일. 그림(SVG)과 PNG 저장(`vizPng()`)도 여기 있다
- 내장 자원: `template.hwpx`, `template_monthly.hwpx`, `reference.xlsx`(`app.spec` datas)

## 경계
- `monthly_pipeline.py`는 `sanction_pipeline.py`의 헤더 탐지·연도 추출·부처명 치환을 import해서 쓴다.
  - 반대 방향 import를 만들지 않는다.
  - 같은 기능을 따로 구현하지 않는다. 두 통계가 같은 raw를 다르게 읽게 된다.
  - 열 별칭 사전은 두 파일에 따로 있다. 별칭을 더하거나 고칠 때 두 곳을 함께 고친다(지금도 '부처명'의 별칭 `소관기관`은 연구수행 기준에만 있다).
- 화면 JS는 서버가 준 표의 수를 그대로 그린다. 집계·검산을 JS에 다시 구현하지 않는다.
- 서버 바인딩을 127.0.0.1 밖으로 넓히지 않는다.
- 화면에 외부 CDN·웹폰트·브라우저 저장소를 쓰지 않는다. 글꼴은 Windows 기본(맑은 고딕, Cascadia Mono·Consolas)만 쓴다.
- 파일 선택을 네이티브 대화상자로 되돌리지 않는다. pywebview가 없을 때 tkinter 창을 워커 스레드에서 띄우면 아무것도 안 뜬다.
- 산출 숫자를 바꾸는 기본값(과제 묶기 `과제명`, 과제유형 `전체`, 과제수행연도 하한 2017 등)은 사용자 확인 없이 바꾸지 않는다.

## 지켜야 할 것
- **부처명 치환**
  - 치환은 항상 `MINISTRY_RENAME`(연쇄 해석 결과)으로 한다. `Series.replace`를 한 번 거는 방식으로 새로 치환하지 않는다.
  - rawdata·표준 부처 목록·참조데이터 세 곳에 같은 치환을 건다.
  - 실제 적용된 치환만 건수와 함께 알린다.
  - 새 개편은 확인된 표에 실제 개편 한 단계만 추가한다.
  - `MINISTRY_RENAME_INFERRED`의 분할 부처 3건(교육과학기술부·국토해양부·농림수산식품부)은 이름과 달리 사용자 확인을 마친 매핑이다(2026-10-23). 지우지 않는다.
- **연구수행 기준**
  - 판정 ①②③은 정해진 대로 둔다. 환수금만 있는 과제는 뺀다.
  - 합계는 연도별 단순 합이다.
  - 연도 축은 올해를 넘기지 않는다.
  - 과제유형 필터는 그룹 결측 보완 뒤, 과제 묶기 앞에서 건다.
    - `세부만`은 과제유형이 빈 행도 빼고, `공동위탁제외`는 남긴다.
    - `전체`가 아닌데 과제유형이 모두 비어 있거나 필터 뒤 남는 행이 없으면 예외로 멈춘다.
  - `app.py`의 검산 4종(연도별 소계 = 연도 전개 합, 부처별 합 = 합계 행, ①+②+③ = 소계, 합계 열 = 연도별 열 합)을 유지한다.
- **처분연도 기준**
  - 처분일에서 연도를 뽑는 것은 처분연도 열 전체가 비었을 때뿐이다. 처분연도가 빈 행은 빼고 건수를 알린다.
  - 금액은 `parse_money()`를 거친다. 변환 실패 건수와 값은 결과에 남긴다.
  - 기관유형은 `ORG_LABELS` 7개 밖으로 내보내지 않는다(목록 밖·공란은 `기타`, 값별 건수 보고).
  - `REASON_GROUPS` 밖 제재사유는 그 표에서만 빼고 알린다.
  - 고른 축의 원천 열이 통째로 비면 멈춘다.
  - 표준 3축이 1~9번을 차지하고 추가 축은 10번부터다.
  - `-`(부과 없음)와 `0.0`(완납)을 구분한다. 이 표기 규칙은 엑셀·hwpx·화면이 같아야 한다.
- **hwpx 출력**
  - 표를 위치로 찾으므로, 양식의 표 개수·순서·행 구조를 바꾸면 경고 없이 다른 표에 값이 들어간다. 양식이나 출력기를 고쳤으면 합성 자료로 만든 hwpx를 한글로 열어 표마다 제목과 값을 대조한다.
  - 행·열을 늘리고 줄인 뒤 `rowAddr`·`colAddr`·`rowCnt`·`colCnt`·셀 병합·열 너비 합(원래 표 너비)을 맞춘다.
  - 처분연도 각주의 `’yy.mm.dd`는 파일명 날짜로만 채우고, 못 찾으면 자리표시자를 그대로 둔다.
- **그림 PNG**
  - `data:image/svg+xml`은 XML로 읽힌다. PNG로 바꾸기 직전에 마크업이 든 속성(`data-tip` 등)을 걷어낸다.
  - SVG에 최종 `width`·`height`를 적는다.
  - 새 속성에 마크업을 담으면 `vizPng()`에서 함께 걷어낸다.
- **성능**: 10만 행 기준 연구수행 약 28초, 처분연도 약 19초다. 집계에 `iterrows()`나 그룹 반복 슬라이싱을 다시 들이지 않는다. 엑셀 쓰기는 xlsxwriter `write_row`를 쓴다.

## 시험
- 자동 시험은 없다. 바꾼 뒤에는 합성 rawdata로 **화면(`python app.py`)에서** 두 통계를 모두 돌린다. 연구수행 기준 검산은 화면에서만 계산되기 때문이다. 명령줄은 `python run_report.py 합성_20260101.xlsx --template template.hwpx`처럼 양식을 지정해 따로 확인한다.
- 합성 자료에 넣을 경우
  - 1행 그룹 머리·2행 열 이름
  - 텍스트 금액(`18,873,603`, `₩12,000`, `(1,000)`, `해당없음`)
  - 9분류 밖 제재사유, 두 열 모두 빈 연구수행주체, `정부부처`·`무분류` 기관유형
  - 연쇄 개편 부처명(`지식경제부`), 참조데이터에 없는 부처
  - 과제유형 열이 있는 경우와 없는 경우, 빈 과제유형, 종료일 없음·종료 < 시작
  - 처분연도가 빈 행
- 확인할 것
  - 화면의 두 탭과 통계판이 모두 ✓
  - 처분연도 기준 엑셀 `검산` 시트의 표 간·표 안 검산
  - 의도적으로 틀린 자료에서 빠진 건수가 맞게 표시되는지
  - hwpx를 한글로 열었을 때 표마다 제목과 값이 맞는지
- 두 탭을 번갈아 실행해 결과가 서로 지워지지 않는지 본다.
- 빌드: 이 폴더에서 `build_exe.bat`을 실행한다(배치에 폴더 이동이 없음) → `dist\제재통계.exe`.
