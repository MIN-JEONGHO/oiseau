# 고시판정v1 작업 지침 (화면 이름: 연구보안 등급분류 분류기준(고시) 검토 1.4.2)

연구개발과제의 최종 목표 수치를 세 고시(국가첨단전략기술·국가핵심기술·전략물자 이중용도·군용)의 숫자 기준과 대조해 초과·근접·미달을 내는 Windows 도구다. 참고 대조이며 공식 판정이 아니다. 기준을 충족하면 초과, 못 미친 차이가 기준값의 10% 이하이면 근접, 그보다 크면 미달이며, 숫자 외 조건(용도·양산·예외)은 판정을 바꾸지 않고 확인 조건으로 보인다. 1.4.0부터 결과는 초과·근접 중심의 간단한 결과를 먼저 보인다 — 세 판정 `고시 사양 초과`·`고시 사양 근접`·`고시 사양 미달`과 과제 사유 한 줄, 초과·근접 조항은 넘거나 근접한 사양마다 정해진 틀의 사유 한 줄, 미달 조항과 정해진 경우의 '추가 검토 필요'는 그 뒤에 접어 둔다. 일괄 검토는 세 판정별 과제 수(종합 건수)와 중점 검토 과제(종합이 초과·근접)를 위에 보인다. 조항별 상세(판정 엔진의 값 그대로)는 접힌 '상세 보기'와 결과 엑셀 `고시 조항별 상세` 시트에 남긴다. 판정 규칙·결과 형식·값 집합의 전체는 `README.md`에 있다. 저장소 전체 규칙(키·업무 자료·커밋·현재 버전 폴더만 수정)은 그대로 적용된다.

## 현재 버전

`고시해당 판정 프로그램/고시판정v1/`. 새 버전은 폴더를 통째로 복사해 만들며(사용자가 정함), 복사본에서 build·dist·`__pycache__`·`tools/output`을 지운다.

1.3.2부터 프로그램 이름이 바뀌었다. 보이는 이름은 `연구보안 등급분류 분류기준(고시) 검토`(옛 이름 `고시 수준 검토`), 파일 이름에 쓰는 말은 `연구보안등급분류_분류기준고시검토`(옛 `고시수준검토` — 결과 엑셀·일괄 입력 양식의 기본 이름, 설치 파일 이름, 새로 설치할 때의 폴더)다. 소스 폴더 이름, 실행 파일 이름 `고시판정v1.exe`, 설치 스크립트 파일 이름 `installer/고시수준검토.iss`, AppId, 키 저장 이름 `NoticeLevelJudge/api-key`, 01 화면의 결과 제목 `고시 수준 검토 결과(AI 참고)`는 일부러 그대로 두었다. 판정 규칙·AI에 보내는 것·결과 엑셀 시트와 열은 바뀌지 않았다.

1.3.3(2026-11-12)은 단위 환산 결함 두 건(`units.py` — Wh 계열을 J 기준 3600배로, 환산 인자를 정확한 분수로)을 고치고 화면 문구 두 곳(04 설정 '고시 기준본'에서 `근접 기준(%)` 줄과 `지문 보기`를 뺌, 01 첨부파일 안내 `※ RFP나 연구개발계획서(HWPX, PDF, DOCX 중 하나)를 업로드해주세요`)을 바꾼 판이다. 판정 규칙(초과·근접·미달, 10%)·기준값 표·AI에 보내는 것·결과 엑셀 시트와 열, 이름·파일 이름·덮어 설치 동작은 1.3.2와 같다. 근접 기준과 두 지문은 결과 엑셀 `처리내역`에 그대로 나온다. 1.3.2 설치 파일은 빌드만 했고 동료에게 내보내지 않았다(환산 결함이 들어 있음).

1.4.0(2026-11-13)은 결과를 초과·근접 중심으로 다시 짠 판이다(결정 0011의 1.4.0 덧붙임). 판정 이름을 세 가지(`고시 사양 초과`·`고시 사양 근접`·`고시 사양 미달`)로 통일해, 1.3.x까지의 `사양 미달 또는 무관`과 판정 이름으로서의 `최종목표 수치 없음`을 더 쓰지 않는다(목표 수치 없음·관련 고시 항목 없음 과제도 `고시 사양 미달`이고 왜 미달인지는 과제 사유에 적는다. 오류·취소는 따로 두고 미달로 세지 않는다). 결과마다 되풀이하던 공통 안내 세 줄을 결과 화면과 결과 엑셀에서 뺐고(화면 맨 아래 한 줄은 그대로), 대신 조항에 확인 표시 `추가 확인 조건`을 붙여 보인다. 초과·근접 조항은 대표 하나가 아니라 초과·근접한 사양마다 한 줄이다. 화면은 일괄이 건수 줄 → 종합 건수 → 안내 줄 → 중점 검토 과제 → 판정하지 못한 과제 → 접힌 그 밖의 과제 → 접힌 상세 보기, 개별이 과제명·종합 결과와 사유 → 안내 줄 → 초과·근접 고시 조항 → 접힌 미달 조항 → 접힌 추가 검토 필요 → 접힌 상세 보기다. 결과 엑셀은 보이는 시트 셋(`초과·근접 조항`·`과제별 검토 결과`·`고시 조항별 상세`)과 숨김 시트 `처리내역`으로 정리했다(1.3.x까지의 `검토 결과 요약`·`해당 고시 조항` 시트는 없앴고, `처리내역`은 마지막 `참고` 줄만 빠진 채 기록 항목이 그대로다. 엑셀의 '시트 숨기기 취소'로 본다). 판정 계산(초과·근접·미달, 10%, AND/OR, 환산)·판정 엔진의 값 집합·과제 상태 값·기준값 표·AI에 보내는 것과 요청 수·입력 양식·기본 저장 파일 이름·`고시 조항별 상세` 시트의 열과 값·03 고시 검색·04 설정은 1.3.3과 같다. 상세 보기 안의 내용도 같고, 그 안에서 `처리내역`을 말하는 두 곳만 `처리내역(숨김 시트)`로 적는다.

1.4.1(2026-11-13)은 1.4.0을 써 본 사용자의 세 가지 손질 요청이다. 판정 계산·AI 요청은 그대로다.

- **종합 건수 단추**: 일괄 결과의 종합 건수를 누르면 그 건수에 든 과제만 과제 카드로 보인다. 어느 과제인지는 `brief.tally_briefs`가 주는 `members`(종합 건수 항목마다 과제 위치)를 연결 함수가 `tally_members`로 그대로 옮기고, 화면(`ui/app.js`의 `showTally`·`taskCard`)은 그 위치의 행을 그리기만 한다(화면이 판정 이름을 비교해 고르거나 세지 않는다 — 시험 `test_tally_counts_are_buttons_that_show_their_tasks`). 과제 카드는 개별 화면과 같은 `brief` 글을 놓는다. 접힌 묶음 제목 글(`미달 조항 n건`·`추가 검토 필요 n건`)은 `underTitle`·`reviewTitle` 한 곳에서 만든다.
- **결과 엑셀 행 높이**: 모든 시트의 글 있는 행은 `excel_report.ROW_HEIGHT`(16.5)로 고정한다(`_append`). 값·줄바꿈은 그대로다. 높이를 다시 자동으로 두면 `추가 검토 필요`가 많은 과제의 행이 크게 늘어난다(사용자가 고쳐 달라고 한 문제).
- **낱말 '매핑'**: 화면·결과 엑셀·진행 표시·코드 주석의 '짝'은 모두 '매핑'이다(`judge_engine.FLAG_PAIR` `매핑 확인 필요`, `REASON_NO_FACT` `매핑된 최종목표 사양 없음`, `ai_stages.STAGE_LABELS`·`pipeline.DROP_STAGE_PAIR` `매핑`, `excel_report.DETAIL_COLUMNS`의 `매핑 근거`, `brief.HINT_DROPPED`). '짝'이 남은 곳은 AI에 보내는 지시문 `ai_stages._SYSTEM_PAIR`뿐이다 — 지시문을 바꾸면 AI 응답이 달라질 수 있어 사용자 확인과 실제 AI 확인 없이 바꾸지 않는다. 새 글에 '짝'을 쓰지 않는다(시험 `test_pair_wording_is_mapping_everywhere_the_user_sees`가 막는다). 변수·키 이름(`pair`·`pair_reason`·`pairs`)은 그대로다.

1.4.2(2026-11-13)는 차이 문구만 바꿨다(사용자 요청 — '여유'가 초과인지 헷갈린다). `brief.py`의 `DIFFERENCE_MET` `기준보다 {}% 초과`, `DIFFERENCE_MET_ZERO` `기준 초과`, `DIFFERENCE_SHORT` `기준보다 {}% 미달`, `DIFFERENCE_EQUAL` `기준값과 같음(같은 값은 초과 아님)`. '초과'는 고시 사양을 넘어섰다는 뜻이라 이하·미만 기준에서는 값이 더 작은 쪽이다. 차이 글에 '여유'·'충족'·'못 미침'을 다시 쓰지 않는다(시험 `test_difference_wording_is_over_or_under`). 과제 사유 `기준에 못 미침`(`REASON_UNDER`)과 판정 계산·`차이 %` 값은 그대로다.

## 반드시 지킬 것

- **AI는 초과·근접·미달을 정하지 않는다.** 판정은 `judge_engine.py`의 계산이다. 간단한 결과의 판정 이름·과제 사유·과제 묶음·초과·근접 조항과 미달 조항·사유 문장·건수, 실행 한 번의 종합 건수와 과제 순서는 `brief.py`가 만들고, 화면 스크립트와 결과 엑셀은 받은 `brief` 글과 `brief.tally_briefs`의 결과를 그대로 넣는다(화면은 textContent로만). 화면 스크립트에 판정·집계·사유·묶음·순서 계산을 두지 않는다. AI 선별의 `detail_match`(세부 기술 일치)는 '추가 검토 필요'에만 쓰고 판정·조항 목록(초과·근접 조항, 미달 조항)에는 쓰지 않는다.
- **외부 전송 범위**(`ai_stages.py`): 연구개발과제명·최종목표·연구개발내용·활용계획 및 기대효과·사용자가 확인한 목표 발췌·고시 조항 색인·관련 고시 조항의 기준 기록과 원문·고정 지시문뿐이다. 연구개발단계·정부지원연구개발비는 보내지 않고 판정에도 쓰지 않는다(결과 표시만). 첨부파일 자체·발췌하지 않은 글·결과·키를 보내지 않는다. 새 전송 대상을 만들지 않는다. 선별 응답의 `detail_match`는 받는 칸이 하나 늘어난 것이며 보내는 내용·요청 수·묶음 크기는 같다. '추가 검토 필요'용 PC 안 의미 검색 글(연구개발과제명·최종목표·연구개발내용 또는 목표 발췌)은 PC 밖으로 보내지 않고 파일·결과·로그에 남기지 않는다.
- **키**: `credential_store.py`(이 프로그램 전용 이름 `NoticeLevelJudge/api-key`)에만 저장한다. 소스·로그·결과·화면·예외 메시지에 키 원문을 넣지 않는다. 시험은 가짜 저장소로 한다.
- **숫자를 조용히 바꾸지 않는다.** 제외 행, 버린 목표 수치·매핑, 기준값 채택 실패, 단위 환산, 오류·취소 건수는 화면·결과 엑셀·검수 엑셀에 드러난다. 간단한 결과에서 감춘 관련 조항 수와 남기지 않은 세부 기술 일치 수는 상세 보기와 처리내역에, 의미 검색을 쓸 수 없었던 사실은 안내 줄과 처리내역에 드러난다. 오류·취소 과제는 `고시 사양 미달`로 세지 않고 따로 보이며, 종합 건수의 합은 처리한 과제 수와 같아야 한다. 대응표에 없는 판정 값·모르는 묶음 값·사양 줄 규칙이 깨진 조항은 다른 값으로 바꾸지 않고 오류로 드러낸다. 결과 엑셀의 시트 구성은 보이는 셋(`초과·근접 조항`·`과제별 검토 결과`·`고시 조항별 상세`)과 숨김 시트 `처리내역`이다(1.4.0). `처리내역`은 숨기기만 하며(엑셀의 '시트 숨기기 취소'로 보는 보통 숨김) 기록 항목(기준본 이름·지문, 고시 기준 사양 표 지문, AI 제공자·모델, 근접 기준, 검토 대상 고시, 제외 행, 빈 행 건수, 선택 칸 경고, 버린 최종목표 사양·매핑, 파일 읽기 경고, 오류·취소 건수, AI 호출 수, 의미 검색 줄)을 줄이지 않는다. 일괄 검토의 버린 최종목표 사양·매핑과 사유는 화면에 건수만 나오므로 이 시트가 유일한 자리다. 상세(화면 '상세 보기' 안의 내용 전부와 `고시 조항별 상세` 시트의 열·값)를 지우지 않는다.
- **고시 자료 `resources/notices/`와 기준값 표 `resources/thresholds.json`은 손으로 고치지 않는다.** 자료는 시뮬레이터 `resources_v16/notices`의 바이트 복사본이고, 표는 `tools/build_threshold_table.py`만 쓴다. 실행 중 갱신하지 않는다.
- 시뮬레이터 폴더·다른 프로그램 폴더를 import하거나 실행 중에 읽지 않는다. 이 폴더 안 파일만으로 실행·빌드한다.
- 화면은 인터넷 없이 뜬다. 외부 CDN·웹폰트·원격 자원 없음, 자산 서버는 127.0.0.1에만, 외부 탐색·새 창 차단, 허용 함수 목록(`bridge.PUBLIC_METHODS`, 17개) 밖은 노출하지 않는다.
- 만든 사람 표시 `powered by min · min@kistep.re.kr`은 화면(`ui/index.html` 왼쪽 메뉴 아래 고정 글, 링크 없음)과 설치 화면(`installer/고시수준검토.iss`의 `BeveledLabel`·`AppPublisher`·`AppContact`)에만 둔다. AI 요청·결과 엑셀·처리내역·로그에는 넣지 않는다(`tests/test_app_assets.py`가 확인).
- PDF 라이브러리는 pypdf(BSD)다. PyMuPDF(AGPL)는 import도, exe 포함도 하지 않는다.
- 시험은 합성 자료·모의 AI 응답(`tests/mock_model.py`)으로만 한다. 실제 유료 AI·실제 과제 자료는 사용자가 그 작업에서 요청할 때만 쓰고 결과를 자동 검증과 구분해 보고한다.

## 규칙을 바꾸는 자리

| 규칙 | 자리 |
|---|---|
| 초과·근접·미달 계산, 근접 기준 10%, AND/OR 집계, 과제 판정, 값 집합 | `judge_engine.py`(`NEAR_PERCENT` — 판정과 결과 엑셀 `처리내역`이 이 값을 쓴다. 연결 함수의 처음 상태 응답에도 이 값이 실리지만 1.3.3부터 화면에는 보이지 않는다. 표의 `near_percent`는 참고값, `VERDICT_*`·`FLAG_*`·`FAMILY_VERDICT_*`) |
| 단위 별칭·종류·환산 | `units.py`(`ALIASES`, `_SI_BASES`, `_OTHER_UNITS`). 배수는 10진수 글자나 `'분자/분모'` 글자로 적고 `_factor`가 정확한 분수(`fractions.Fraction`)로 읽는다. `convert`는 분수로 계산해 유한 소수이면 정확한 값(끝의 0 없이), 끝나지 않는 소수이면 계산 정밀도 28자리에서 반올림한 값을 돌려주고, 유한하지 않은 값(NaN·무한대)은 `UnitError`다(1.3.3). Wh 계열은 `_SI_BASES`에서 J 기준 `"3600"`. rad·mrad·μrad는 원주율 때문에 어림값. 바꾸면 `docs-local/business-rules.md`도 |
| 기준값(고시 항목별 숫자 기준·확인 조건) | `tools/extracted/*.json` → `python tools/build_threshold_table.py`. 표 검증 규칙(인용·수·단위·비교어)은 도구 안 |
| AI 지시문·묶음 크기·응답 검증 | `ai_stages.py`(`system_prompt`, `SCREEN_BATCH_SIZE`, `PAIR_BATCH_CLAUSES`) |
| 최종목표 사양 추출의 응답 키·인용 찾기 | `ai_stages.py`(`FACT_FIELDS` — 응답·요청 `fact_fields`의 여덟 키, 1.3.1부터 `start`·`end`를 묻지 않고 보내도 쓰지 않음. `FACT_RECORD_FIELDS` — 수치 기록의 열 키. `_check_fact` — `source_field` 글에서만 `quote`를 글자 그대로 찾아 첫 위치를 기록의 `start`·`end`로 담고, 못 찾으면 `인용이 글에 없음`, 빈 `quote`는 `quote가 비어 있음`으로 버림). 응답 키를 바꾸면 추출 지시문의 응답 모양과 `docs-local/contracts.md`도 |
| AI 출력 한도(제공자별 토큰) | `bridge.MAX_OUTPUT_TOKENS`(1.3.1: claude·openai 32000, ollama·lmstudio 8000, `make_client`가 넘겨 세 단계 모두에 적용). 로컬은 모델 서버가 문맥 길이보다 큰 한도를 거부할 수 있어 낮게 둔다. `llm_client.py`의 기본값은 바꾸지 않는다. 대기 시간 600초·재시도는 따로 바꾸지 않는다 |
| 세부 기술 일치(선별 응답의 `detail_match`) 지시문·모양 규칙 | `ai_stages.py`(선별 지시문의 뜻과 예, `DECISION_FIELDS`, `screen_candidates`의 응답 검증 — 없음·참/거짓 아님·candidate 거짓인데 참은 모양 오류). 보내는 내용·요청 수는 바꾸지 않는다(결정 0010) |
| 간단한 결과(1.4.0): 세 판정 이름과 대응표(과제 상태별 포함), 과제 사유, 과제 묶음, 초과·근접 조항과 미달 조항 나누기·순서, 사양 줄(초과·근접 조항은 사양마다 한 줄, 미달 조항은 한 줄과 `외 N건`), 사유 틀·차이 표현·숫자 표시, 조항에 붙이는 확인 표시 일곱 가지, 추가 검토 필요 규칙(이중용도 / 세부 기술 일치 + 같은 고시 안 상위 순위), 비교하지 못한 이유 낱말, 건수, 안내 줄, 빈 목록 문구, 종합 건수와 과제 순서 | `brief.py`(`VERDICT_*`·`_SIMPLE`·`_COMPARED`·`_STATUS_VERDICT`, `REASON_*`·`_STATUS_REASON`, `GROUP_*`, `_FOCUS_ORDER`·`_focus_lines`·`_reason_comparison`, `DIFFERENCE_*`·`OTHERS_TAIL`·`format_number`·`format_converted`, `CLAUSE_FLAGS`, `KEPT_*`·`WHY_*`·`DETAIL_MATCH_FAMILIES`, `HINT_*`·`EMPTY_MESSAGE`, `TALLY_*`·`_OVERALL_TALLY`·`tally_briefs`·`tally_text`, 키 이름 `BRIEF_KEYS`·`CLAUSE_KEYS`·`LINE_KEYS`·`REVIEW_KEYS`·`COUNT_KEYS`, 조정 값 `TOP_RANK`=5·`QUOTE_LIMIT`=80·`CONVERTED_DIGITS`=4). 화면·결과 엑셀·일괄 결과는 다시 계산하지 않는다. 공통 안내는 1.4.0에서 없앴다(1.3.x까지의 `NOTICES`·`REASON_FLAGS`·`SUMMARY_LIMIT`은 없다). 바꾸면 `docs-local/business-rules.md`·`docs-local/contracts.md`도 종합 건수의 표시 틀 `{이름} {n}건`은 `brief.TALLY_ITEM_TEXT`(결과 엑셀 `종합 결과` 줄)와 화면 스크립트 `ui/app.js`의 `renderBatchResult`(종합 건수 줄) 두 곳에 있으므로 함께 고친다 |
| 일괄 결과의 묶음 제목 글·빈 경우 글·실행 안내 줄 | `bridge.py`(`BATCH_FOCUS_LABEL`·`BATCH_OTHER_LABEL`·`BATCH_UNJUDGED_LABEL`·`BATCH_FOCUS_EMPTY_MESSAGE`·`BATCH_OPTION_HINT`, `_batch_overview` — `tally`·`groups`는 `brief.tally_briefs`의 결과를 그대로 옮긴다. 여기서 판정 이름을 비교해 세지 않는다). 바꾸면 `docs-local/contracts.md`도 |
| 검토용 의미 검색 순위(세부 기술 일치 확인) | `notice_search.SearchEngine.semantic_ranking`(같은 고시 안 실제 검토 항목 전체, 조각별 최고 유사도, 같은 값은 고시·통제번호 순, 관련어 사전 안 씀, 쓸 수 없으면 `available` 거짓). 검색 글은 `brief.semantic_text`. 처리내역 지문은 `semantic_model_fingerprint`·`semantic_vectors_fingerprint` |
| 목표 발췌 제목 단어 | `doc_extract.py`(`GOAL_HEADINGS`) |
| 입력 칸·개별 검토 시작 조건·과제 상태 | `pipeline.py`(`validate_task`; 과제 키 `title`·`final_goal`·`rnd_content`·`utilization`·`excerpt`·`attachment_name`·`rnd_stage`·`gov_fund`·`row_number`) |
| 연구개발단계·정부지원연구개발비 정리(줄임말·쉼표·소수, 잘못된 값은 빈칸+경고) | `pipeline.normalize_rnd_stage`·`pipeline.normalize_gov_fund` — 일괄 읽기와 연결 함수가 같이 쓴다. 화면 스크립트에서 숫자를 해석하지 않는다 |
| 일괄 입력 양식 시트·머리글·제외 규칙·동시 처리 수 | `batch.py` |
| 화면·양식·결과 엑셀에 보이는 이름(가이드라인·혁신법 용어) | `ui/`·`bridge.py`(메시지)·`batch.py`(양식)·`excel_report.py`(시트·열)·`pipeline.py`(고시 이름)·`ai_stages.py`(단계 이름)·`app.py`(창 제목·기본 파일 이름). 칸에 들어가는 판정 값·확인 표시·상태 문구는 바꾸지 않는다(기준값 표와 같은 낱말) |
| 결과 엑셀 시트·열 이름, 실행 정보 줄, 숨김 처리내역 | `excel_report.py`(명세 글자 그대로; 시트 이름 `SHEET_FOCUS`·`SHEET_SUMMARY`·`SHEET_DETAIL`·`SHEET_LOG`, 열 `FOCUS_COLUMNS`·`SUMMARY_COLUMNS`·`DETAIL_COLUMNS`·`LOG_COLUMNS`, `과제별 검토 결과` 표 아래 실행 정보 줄 `RUN_INFO_LABELS`·`RUN_MODEL_TEXT`·`RUN_EXCLUDED_COUNT`, 추가 검토 필요 칸 `REVIEW_LINE`·`REVIEW_SEPARATOR`, 처리내역의 간단한 결과 줄 `SEMANTIC_LOG_*`·`RANK_LOG`·`HIDDEN_LOG`·`_COUNT_TOTALS`, 숨김은 `write_report`의 `sheet_state`(보통 숨김). 종합 건수·과제 순서는 `brief.tally_briefs`·`brief.tally_text`를 쓰고 이 모듈에서 세지 않는다. 화면 맨 아래 한 줄의 글 `NOTE_TEXT`는 연결 함수가 쓰며 결과 엑셀에는 쓰지 않는다; 바꾸면 `docs-local/contracts.md`도) |
| 고시 검색: 통제번호 모양·넓히기 단계 가중치·순위·찾은 이유 값·최소 의미 유사도(`0.32`)·검색어 길이 상한 | `notice_search.py`(상수와 `SearchEngine`). 화면 스크립트에 점수 계산을 두지 않는다 |
| 고시 검색 관련어 사전 | `tools/synonyms/*.json` → `python tools/build_search_dictionary.py`(`--check`·`--apply-review <엑셀> --reviewed-on 날짜`). 낱말은 고시 원문 근거 필수, 사전 파일을 손으로 고치지 않는다 |
| 고시 검색 의미 모델·조항 벡터 | 모델 `resources/search_model/`(`MODEL_INFO.json`; 다시 고르려면 `tools/fetch_search_model.py`·`compare_search_models.py`·`pack_search_model.py`, 라이선스 MIT·Apache·BSD만), 조항 벡터 `python tools/build_search_vectors.py`(`--check`). 모델을 바꾸면 벡터를 다시 만든다 |
| 배포(설치 파일) | `고시판정v1.spec`(폴더형), `installer/고시수준검토.iss`(AppId 바꾸지 않음, 만든 사람 표시 `BeveledLabel`·게시자·연락처. 스크립트 파일 이름은 1.3.2에서 프로그램 이름이 바뀐 뒤에도 일부러 `고시수준검토.iss` 그대로다. 덮어 설치 때 옛 이름 바로가기는 `OldAppName`·`[InstallDelete]`·`UsePreviousGroup=no`가 처리한다 — 옛 이름의 시작 메뉴 바로가기 둘과 바탕화면 바로가기를 지우고, 옛 묶음 폴더는 비었을 때만 지우며, 시작 메뉴 묶음은 새 이름으로 만든다. 설치 폴더는 전의 것을 그대로 쓴다), `build_exe.bat` |
| 프로그램 버전 | `paths.PROGRAM_VERSION`(창 제목·화면·결과 엑셀의 실행 정보 줄과 처리내역이 쓴다)과 `installer/고시수준검토.iss`의 `AppVersion`(설치 파일 이름), `build_exe.bat` 끝의 설치 파일 이름 안내 줄, 버전 글자를 단언하는 시험(`tests/test_app_assets.py`·`tests/test_bridge.py`) |
| 과제 상태와 상태별 범위 판정 | `pipeline.py` |

## 검증

- 이 폴더에서 `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -t .` 종료 코드 0(`-I`·`-s` 없이 `python` 3.14).
- 추출 파일을 고쳤으면 `python tools/build_threshold_table.py --check tools/extracted/<파일>.json` 종료 코드 0을 본 뒤 전체 생성을 돌린다. 생성 뒤 표 지문이 바뀌므로 exe를 다시 빌드한다.
- 빌드를 바꿨으면 `build_exe.bat`(소스 자체 확인 → 폴더형 빌드 → 빌드한 프로그램 자체 확인 → 설치 파일 만들기) 종료 코드 0과, 설치 파일로 임시 위치에 조용히 설치(`/VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR=임시폴더`) → 설치된 `고시판정v1.exe --selfcheck` 통과 → 제거(끝날 때까지 기다린 뒤 폴더 없음 확인)를 확인한다. 폴더형이라 `고시판정v1.exe`만 따로 떼어 실행하면 안 된다(`_internal`이 함께 있어야 함). 설치 시험 전에 이 PC에 같은 AppId의 실제 설치 등록이 있는지 본다(있으면 멈추고 사용자에게 묻는다 — `docs-local/engineering-notes.md`).
- 실제 창·네이티브 파일 창·실제 AI 응답은 자동 시험으로 확인하지 않는다. 확인하지 않은 것은 '미확인'으로 적는다.

## 함정

- 콘솔 코드페이지가 cp949라 한글 출력이 깨져 보인다. `PYTHONIOENCODING=utf-8`을 붙인다. `.bat`은 `chcp 65001` 뒤에 실행한다.
- `tests/test_threshold_table.py`의 실제 복사본 시험은 실제 `resources/thresholds.json`을 새로 만들거나 고치지 않는지 본다. 시험 중 표를 만들면 실패한다.
- `llm_client.py`는 claude·openai에서 기본 모델만 받는다. 설정 화면도 그렇게 막아 둔다.
- 긴 첨부 목표 발췌에서는 최종목표 사양 추출 응답이 길어진다(2026-11-10 합성 발췌 6,202자·최종 목표 표 줄 56개를 실제 Claude로 돌렸을 때 1.3.1 응답 출력 7,527토큰, 그중 생각 2,386). `llm_client.py`는 출력 한도에서 잘린 응답과 JSON 객체 하나가 아닌 응답을 같은 오류로 내므로, 한도가 작으면 잘린 응답이 `재요청 뒤에도 응답 모양이 틀림: JSON 객체 하나를 받지 못함`처럼 보일 수 있다(가능성 — 1.3.0에서 사용자가 본 이 오류의 원인은 확정되지 않았고 합성 글로는 재현되지 않았다). 출력 한도를 줄이거나 1단계 응답 키를 늘릴 때 이 길이를 본다.
- `pipeline.py`는 `brief`를 함수 안에서 import한다(`brief`가 `pipeline`의 상태·고시 이름을 쓰므로 순환 import를 피함). PyInstaller가 놓치지 않게 `고시판정v1.spec`의 `hiddenimports`에 `'brief'`를 적어 두었다. 새 모듈을 함수 안에서만 import하면 여기에 더한다.
- `build_exe.bat`은 CRLF 줄끝으로 둔다. LF만 쓰면 cmd가 `chcp 65001` 뒤 한글이 든 줄과 `( … )` 블록을 토막 내 명령으로 실행하고 종료 코드 0으로 끝난다(2026-11-10 확인, 빌드가 되지 않았는데 성공처럼 보임). 도구 PowerShell에서는 PATH에 System32가 없어 `chcp`·`where`를 못 찾으므로 `$env:Path`를 `$env:SystemRoot\System32;`로 시작하게 한 뒤 `& "$env:SystemRoot\System32\cmd.exe" /c '"<배치 절대 경로>" <nul'`로 부른다. 끝나면 `dist\연구보안등급분류_분류기준고시검토_설치_v<버전>.exe`(1.3.1까지는 `고시수준검토_설치_v<버전>.exe`)가 새로 생겼는지 직접 본다.
- 빌드는 `build`·`dist`를 통째로 지운다. 이전 버전 설치 파일을 남기려면 빌드 전에 다른 곳에 복사해 두었다가 되돌린다.
- 원문의 지수 표기·음수·수식·범위 표기는 도구가 수로 읽지 못한다. 추출 파일에서 `checks`로 두어야 하며, 억지로 수로 바꾸지 않는다.
- `units.py`의 환산 배수에 3600·60으로 나누는 계수를 끊긴 소수(`0.2777777777777778` 같은 것)로 적지 않는다. `'1/3.6'`·`'1/3600'`처럼 분자/분모로 적는다. 끊긴 소수로 적으면 환산한 값이 기준값과 정확히 같은 목표에서 초과·근접이 뒤바뀐다(1.3.2까지 `2160 km/h`가 600 m/s 초과 기준에 `초과`로 나왔다 — 1.3.3에서 고침). 새 단위를 더할 때 Wh처럼 종류 기준 단위와 배수가 다른 단위는 배수를 빠뜨리지 않는다(1.3.2까지 1 Wh = 1 J였다).
