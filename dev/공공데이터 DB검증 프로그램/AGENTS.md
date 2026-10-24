# 공공데이터 등록 사전검토

공공데이터포털에 등록하기 전에 반려 사유를 기준 조항·위치·조치 방법으로 알려 주고, 고를 수 있는 항목은 자동으로 고친다. 기준은 '26.2. 안내 매뉴얼 두 권(파일데이터 1~17번, OPEN API 1~23번)이다.

## 범위
- **현재 버전**: `공공데이터 DB검증v4/`. 프로그램 표기는 `checker/__init__.py`의 `__version__ = "3.0.0"`이다.
- **보존만 하는 폴더**(수정·삭제 금지): `공공데이터 DB검증/`(v1), `공공데이터 DB검증v2/`, `공공데이터 DB검증v3/`, `v4/`.
  - `v4/`는 이름과 달리 `DB검증v3`를 일부러 남긴 백업이다. 현재 버전이 아니다.

## 구조 (현재 버전)
- `main.py`: 인수가 없거나 `--gui`·`-g`면 `checker.gui`, 그 밖은 `checker.cli`
- `checker/models.py`: `Level`(반려·보완필요·확인권장·적합), `Finding`, `Result(domain="file"|"api")`
- `checker/engine.py`
  - `check()`: 파일데이터. `rules_file` → 형식별 판독 → `rules_csv.analyze_table` → `rules_meta` → 5·6번 안내
  - `check_api()`: OPEN API. `api_reader` → `api_probe`(선택) → `rules_api`
- `checker/readers.py`: 인코딩·구분자 추정, CSV·XLSX(첫 시트 20,000행)·JSON·ZIP 판독과 저장
- `checker/fixer.py`·`checker/api_fixer.py`: 자동수정 정책 표와 실행
- `checker/report.py`: 콘솔·엑셀 리포트(두 구분을 한 파일에)
- `checker/gui.py`: pywebview 창. `Api` 클래스 메서드를 JS가 직접 부른다. 구분별 결과를 따로 들고 있다
- `checker/ui.py`: 화면 HTML·CSS·JS 전체가 `INDEX_HTML` 문자열로 들어 있다(외부 파일·CDN 없음)
- `tests/`: `test_rules.py`(파일데이터), `test_api_rules.py`(OPEN API)
- `samples/`: 정상·위반 예시

## 경계
- 판정 로직은 `rules_*.py`와 `engine.py`에만 둔다. `ui.py`의 JS에 판정·수정 로직을 복제하지 않는다. 규칙 모듈은 `gui`·`cli`를 import하지 않는다.
- 파일데이터와 OPEN API는 조항 번호가 겹친다.
  - OPEN API 픽스 키에는 반드시 `api:` 접두어를 붙인다(`api:5-가`).
  - `Result.to_dict()`는 `domain`에 따라 `FIXABLE`과 `API_FIXABLE` 중 하나만 본다. 두 표를 합치거나 섞지 않는다.
- 사용자 기술문서(Swagger·명세표) 파일에 쓰는 코드를 만들지 않는다. 고칠 값은 `manual` 목록으로만 알린다.
- 실호출(`api_probe.py`)은 표준 라이브러리 `urllib`만 쓴다. 한도도 유지한다. 검토 도구가 대상 서버에 부하를 주면 안 된다.
  - 호출할 URL 수: `engine.py`의 `PROBE_LIMIT = 5`
  - URL마다 GET 1회, 응답은 `api_probe.py`의 `BODY_LIMIT`(256KB)까지만 읽고 `DEFAULT_TIMEOUT`(10초)에 끊는다
  - 지연 기준은 `api_probe.py`의 `SLOW_LIMIT`(5초)
- 인코딩 추정 패키지(chardet 등)를 들이지 않는다. exe 크기를 줄이려고 표준 라이브러리만 쓴다.

## 지켜야 할 것
- `Result.verdict`는 오류가 있으면 반려, 지적이 없으면 적합, 그 밖에는 가장 무거운 지적 등급이다.
- 자동 판정이 안 되는 항목은 `Level.REVIEW`(확인권장)로 남기고 지우지 않는다.
- `fix_file()`은 원본을 덮어쓰지 않는다. 원본 형식(csv·tsv·xlsx·json, json은 루트 키와 키 순서 유지)으로 `_수정` 사본을 만든다. 화면·명령줄 모두 사본을 다시 검토한 결과를 덧붙인다.
- 지적 카드의 '자동수정 가능'은 `Finding.fix_key`가 정책 표에 있을 때만 켜진다. 수정 불가 항목의 사유는 `NOT_FIXABLE_REASON`·`API_NOT_FIXABLE_REASON`에서 나온다.
- 화면·리포트에 남는 URL은 `mask_key()`를 거친다. 인증키 원문을 리포트·JSON·로그에 쓰지 않는다.
- 명령줄 종료 코드: 반려가 있으면 1, 없으면 0, 검토할 파일이 없으면 2.

## 새 규칙·수정 추가 방법
- **조항 판정**: 해당 `rules_*.py` 함수에서 `res.add(Finding(rule_id, item, level, message, fix, locations=…, samples=…, fix_key=…))`로 추가한다.
  - 셀 위치는 `cell_ref()` 형식(`C4`)으로 적는다. 행 단위는 `5행`처럼 적는다. 위치는 `MAX_LOC`(5,000)까지만 담는다.
  - OPEN API의 11·12·13·14번처럼 등록유형에 따라 갈리는 규칙은 해당 유형일 때만 돌린다.
- **파일데이터 자동수정**
  - `FIXABLE`에 `(표시명, 등급 "서식"|"내용", 적용범위, 설명)`을 추가한다.
  - 셀 단위면 `CELL_FIXERS`에 변환 함수를 추가한다.
  - 판정 쪽 `Finding`에 같은 `fix_key`를 단다.
  - 값의 뜻이 바뀌면 등급은 `내용`이다.
- **OPEN API 자동수정**: `API_FIXABLE`에 `api:` 키로 추가하고 `fix_api()`에 처리를 넣는다.
- 명세표 머리글 별칭을 더할 때 부분일치는 한글 낱말에만 허용한다. 영문을 부분일치로 넣으면 `code`가 `resultCode`에 걸려 응답 항목이 에러코드 표로 사라진다.

## 시험
- 버전 폴더에서 `python tests/test_rules.py`와 `python tests/test_api_rules.py`를 실행한다. 둘 다 종료 코드 0이어야 한다. pytest로도 돌릴 수 있다.
- 기준을 바꾸면 경계값 시험을 추가한다.
  - 공란 4·5셀
  - 키워드 2·3·8·9개
  - 설명 49·50자
  - 3열·5행 경계
  - 500MB 경계(크기만 흉내)
- 인코딩(CP949, BOM 없는 UTF-8, UTF-8 BOM, UTF-16), 깨진 파일, 형식 유지(csv·tsv·xlsx·json)를 회귀 시험으로 확인한다.
- 실호출은 모의 응답으로만 시험한다. 시험에서 실제 외부 서버에 요청하지 않는다.
- 화면을 고쳤으면 `python main.py`로 두 탭을 직접 열어 확인한다(`PDCHECK_DEBUG=1`이면 개발자 도구가 켜진다).
- 빌드: `build_exe.bat` → `dist\공공데이터_사전검토.exe`. 빈 폴더에서 단독 실행을 확인한다.
