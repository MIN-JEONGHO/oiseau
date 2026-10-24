# v15 입력과 산출물 규약

인터페이스는 설치형 웹 UI의 로컬 비동기 브리지, 엑셀, Python 함수와 자체 확인 CLI다. 공개 웹 API·기관 로그인은 없다. v12~v14는 독립된 과거 규약을 유지하며 schema2 결과를 과거 결과 구조로 읽지 않는다.

## 과제 입력과 실행 옵션

과제 스냅샷은 세부사업명·과제명·연구목표·연구내용·기대효과·추가 검토정보·부처 세부기준·현재 기술사양·개발목표 사양의 9개 문자열 열이다. 과제명은 필수이고 누락 선택 열은 빈 문자열로 정규화한다. 현재/목표 전용 열을 구분해 입력하며 다른 열에 적힌 시점 불명확 문구를 임의의 현재 사양으로 읽지 않는다.

엑셀은 분류대상 시트가 있으면 선택하고 없으면 첫 시트를 읽는다. 제목의 (필수)·(선택)과 앞뒤 공백을 제거한다. 과제명 열 누락·관련 열 중복은 오류다. 빈 과제명·(예시) 시작 행·같은 과제명 중복은 제외하고 각 수를 안내한다. 같은 이름은 세부사업명이 달라도 첫 행만 채택한다. 셀은 수식 평가 없이 문자열화하므로 계산식 대신 확인한 사실 텍스트를 입력한다.

한 실행의 옵션은 시작 전에 고정한다. API 키·클라이언트 객체는 옵션·지문·결과에 넣지 않는다. `options`는 사전 또는 불변 `RunOptions`이며 `normalize_options`로 검사한다. 잘못된 옵션은 모델 호출과 출력 저장 전에 ValueError로 거부한다.

| 옵션 | 허용값·기본값 |
| --- | --- |
| method | impact(기본) 또는 checklist |
| provider | claude(기본), openai, ollama, lmstudio |
| model | 외부는 claude-sonnet-5-5 또는 gpt-6-luna의 제공자별 정확한 식별자. 생략 시 제공자 기본값. 로컬은 설치 모델 식별자 |
| num_reviewers | 정수 1 또는 3(기본), bool 불가 |
| strictness | 표준만 허용. UI 선택 없음. 다른 값 직접 전달은 거부 |
| selection_mode | auto(기본) 또는 manual |
| selected_items | 직접 선택 시 항목명 또는 1~8 식별자 목록, 비어 있을 수 없음. auto에서는 잔존값을 버림 |
| weights | 지표 직접 선택 시 항목명/식별자→가중치. 누락 선택 항목 1.0, 각각 0.8~1.2, 선택 평균 1.0. auto 잔존값은 버리고 실제 선택 항목 모두 1.0. 체크리스트 결과는 빈 사전 |
| weight_tolerance | 지표 직접 선택 시 0~0.000001, 기본 0.000001. 다른 경우 잔존값을 버리고 기본값으로 고정 |
| ministry_policy | 실행 공통 부처 세부기준, 기본 빈 문자열. 과제별 값이 있으면 그 값 우선 |
| guideline_id | research-security-final-a67e47f5ac8ee07d만 허용 |
| local_base_url | 기본 빈 문자열. 지정 시 인증정보·쿼리·fragment 없는 HTTP(S) 주소 |
| catalogue_fingerprint | 기본 빈 문자열. 실행 때 설치 기준본의 64자리 소문자 SHA256으로 고정하며 명시값이 다르면 거부 |
| comparison_rules_version | 문자열 "1"만 허용 |

8번 직접 선택은 해당 과제의 유효한 부처 세부기준이 있어야 한다. 배치도 모든 행의 조건을 검증한 뒤 모델·출력 처리를 시작한다.

## 로컬 비동기 브리지

호출은 `await window.pywebview.api.함수명(...)` 형태이며 성공은 `{ok:true,data:값,error:null}`, 실패는 `{ok:false,data:null,error:{code,message}}`다. 오류 code는 validation·catalogue·credential·busy·not_found·io·runtime이며 message는 재입력·재설치·저장 권한 등 대응을 안내하는 고정 한국어다. 예외 원문·스택·키를 반환하지 않는다. 노출되지 않은 함수·비공개 속성·내장 함수는 네이티브 메시지 경계에서 거부한다.

| 함수와 입력 | 성공 data | 오류 조건 |
| --- | --- | --- |
| get_initial_state() | defaults, criteria, credential_status, catalogue, guideline | 키 저장소·기준본 로드 실패 |
| select_path(purpose) | cancelled, path_token, display_name | 실행 중·잘못된 용도/확장자/경로. 취소는 오류가 아닌 cancelled:true·나머지 null |
| save_key(provider,key) | provider, stored:true | 외부 제공자 이외·빈/마스킹 입력·저장 실패. 실패 후에도 유효 입력은 해당 세션 메모리에 남을 수 있음 |
| delete_key(provider) | provider, stored:false | 잘못된 제공자·삭제 실패 |
| start_single({task,options,output_dir_token}) | job_id | 입력/옵션/기준본/키/토큰 오류·진행 작업 존재 |
| start_batch({input_token,output_token,output_dir_token,options,workers,resume,make_forms}) | job_id | 입력/옵션/키/토큰 오류·동일 입출력·진행 작업 존재. workers 정수 1~8, resume·make_forms bool |
| get_job(job_id,after_sequence) | job_id, state, events, result | 없는 작업·음수 또는 정수 아닌 sequence |
| cancel_job(job_id) | job_id, state | 없는 작업 |
| start_export({job_id,task_fingerprint,output_dir_token}) | 새 job_id | 세션에 없는 완료 결과·지문 불일치·임의 결과 사전/추가 키·잘못된 토큰·진행 작업 존재 |

purpose는 input_excel·output_excel·output_directory다. 네이티브 선택창에서 얻은 토큰은 해당 용도와 앱 세션에만 유효하며 문자열 경로로 대체할 수 없다. 단건 output_dir_token은 null이면 문서를 생성하지 않는다. 배치도 null이면 기본 문서 위치를 사용하고 make_forms가 생성 여부를 정한다. 내보내기는 유효한 저장 폴더 토큰이 필수다.

초기 상태의 credential_status는 제공자별 저장 키 유무 bool이며 원문 키가 아니다. catalogue는 catalogue_id·fingerprint·status·sources와 family별 total_clauses·interpreted_clauses·unsupported_clauses를 갖는다. guideline은 id·definitions·principles다.

작업 state는 queued → running → done/failed, 취소 요청 시 cancelling → cancelled다. 시작 호출은 job_id만 반환하며 상태는 get_job으로 조회한다. 한 번에 활성 작업 하나이며 완료 결과는 앱 세션에서 계속 조회할 수 있다. get_job은 after_sequence보다 큰 이벤트만 반환한다. 이벤트는 sequence·stage·message·completed·total이고 sequence는 작업 안에서 단조 증가한다. stage는 preflight·facts·notices·candidate·criteria·agents·summary·documents·persistence다. 실행 중 result는 null이다. 결과가 보존된 종료 작업의 result는 단건/내보내기이면 결과 사전, 배치이면 results·counts·paths·warnings·persistence를 담는다. 결과를 만들기 전에 실패하거나 취소하면 종료 상태에서도 result가 null일 수 있다. 취소는 완료된 결과를 보존하며 서버 측 이미 진행 중인 추론의 즉시 중단을 보장하지 않는다.

내보내기는 화면이 만든 결과 사전 대신 이전 작업 식별자와 과제 지문으로 Python에 보존된 결과를 찾는다. 완료 후 새 내보내기 작업 식별자를 사용해 다시 내보낼 수 있다. 문서 생성 성공과 배치 기록 갱신 실패는 별도 진행 메시지로 확인한다.

## 저장 결과 schema2

루트 키는 schema_version·guideline_id·catalogue_fingerprint·task_snapshot·task_fingerprint·options_fingerprint·task_name·method·provider·model·status·candidate·criteria·selected_items·weights·reviewers·overall_avg·rule_grade·final_grade·confidence·rationale·discussion_points·unresolved_reasons·documents·notice_review의 25개로 고정한다. schema_version은 정수 2다. 키·전체 실행 옵션·클라이언트·별도 persistence 키를 루트에 추가하지 않는다.

status는 완료·검토필요·후보제외·오류다. final_grade는 보안과제·민감과제·일반과제 또는 null이며 상태를 등급 문자열에 섞지 않는다. confidence는 높음·보통·낮음 또는 null이다. criteria는 정확한 8개 항목별 item·level·note·law_refs·matched_reference·needs_expert_review다. level은 해당·일부·미해당·판단곤란·미검토다. 고시와 연결된 matched_reference 문자열 안에는 정확한 `{comparison_id,source_id}` 목록을 JSON으로 넣으며 없는 ID를 만들지 않는다.

reviewers는 reviewer_id·persona·status·item_reviews·scores·reviewer_score·grade·confidence·rationale·discussion_points·unresolved_reasons·notice_comments다. ID는 reviewer-1부터 순서대로, persona는 예정 전문가 역할이다. 에이전트 상태는 완료·검토필요·미실시다. scores는 항목명→1~5 정수이며 체크리스트에서는 빈 사전, 점수·전체 평균은 null이다. 완료 에이전트의 notice_comments는 모든 비교 ID에 대해 정확히 하나의 의견을 보존한다.

candidate는 is_candidate(bool 또는 null)·reason·uncertainty다. 후보제외는 개인 평가·수치·참고 등급 없이 이유를 남긴다. 검토필요·오류의 final_grade도 null이다. overall_avg·rule_grade는 완전한 지표 평가에서만 계산한다. rationale·discussion_points는 문자열, unresolved_reasons·law_refs는 문자열 목록이다.

notice_review는 catalogue_id·catalogue_fingerprint·catalogue_manifest·sources·clause_snapshots·facts·families·comparisons·status·blocking_reasons다. manifest와 후보의 전체 전이 참조 원문·조건 스냅샷을 함께 보존한다. family는 advanced·core·dual_use·military이고 범위별 status는 complete·partial·not_run·error, 전체 고시 status는 complete·needs_info·error다. complete는 고정 목록의 처리 완전성이며 법적 판단 정확도 보증이 아니다.

사실은 fact_id·basis·subject·value_text·number·unit·source_field·start·end·quote다. basis는 current·target·both·unspecified이며 quote는 정규화 입력 필드의 `[start:end]`와 정확히 같아야 한다. number는 유한 십진수 문자열 또는 null이다. 조건별 근거는 predicate_id·basis(current/target)·condition_text·fact_ids·normalized_value·normalized_unit·assessment·reason·source_anchor다. assessment는 satisfied·not_satisfied·insufficient_info다.

비교는 comparison_id·family·clause_id·source_id·current_assessment·target_assessment·conditions·missing_information·rationale·affected_items다. 목표 정보가 없으면 target_assessment는 not_provided, 있으면 동일한 세 가지 assessment를 사용한다. 부족정보는 basis·predicate_id·question이며 활성 미해결 조건마다 질문을 남긴다. 미해석 조건·근거 없는 정성 판단을 충족으로 저장할 수 없다.

documents는 status·expected_files·files·errors다. 전체 상태는 미생성·완료·일부실패·실패, 파일 상태는 완료·오류다. 각 파일은 kind(reviewer/summary)·reviewer_id(종합 null)·path·status·error다. 정상 평가의 예상 수는 예정 에이전트 수+1, 개인 평가가 없는 후보 제외는 종합 안내 1개다. 미선택은 성공 0의 미생성으로 남기며 분류 완료와 문서 완료를 구분한다.

## 엑셀·재개·재출력

결과 엑셀은 분류결과·요약·고시대조·조건별근거·고시기준본 5개 시트다. 고시 원문·조건·근거·출처·지문을 보존하고 긴 셀은 이어쓰기 행으로 나눈다. 수식처럼 보이는 출력도 문자열로 저장한다. 상세 입력·평가는 결과경로.checkpoint.jsonl, 원문 없는 감사는 결과경로.audit.jsonl에 UTF-8 JSONL로 남는다.

재개는 schema2 구조·기준/대조규칙·9개 입력 스냅샷과 지문·옵션 지문이 일치하는 완료 평가만 재사용한다. 모델·방식·에이전트 수·항목·유효 가중치·정책·로컬 주소·고시 기준이 바뀌면 불일치 결과를 재사용하지 않는다. 자동 모드의 무시한 수동 잔존값이나 키 변경은 지문을 바꾸지 않는다. 손상/구버전 구조는 경고 후 이전 완료 평가를 모두 재사용하지 않는다. 새 기록은 기존 결과를 검증해 원자적으로 초기화하며 v12~v14 체크포인트와 호환되지 않는다.

대량 HWPX 기본 위치는 결과명_HWPX/실행식별자 아래다. 과제 지문·에이전트 식별자·충돌 방지값을 경로에 포함한다. 현재/목표 대조·부족정보·전체 참조 원문을 편집 가능한 표·부록으로 보존하고 실제 사람 서명란은 비워 둔다. 임시 ZIP 완성 후 파일별로 교체하고 일부 실패를 성공으로 세지 않는다. 1,000건 초과라는 이유로 선택한 문서를 끄지 않는다.

재생성은 저장된 manifest·원문 스냅샷을 검증해 사용하며 모델·키·현재 설치 고시 조회가 0회다. 대량 기록 갱신은 분류 내용 불변, 원본 입력 및 순서·옵션·고시 지문 일치, 보고서의 문서 상태까지 최신 체크포인트와 일치를 확인한다. 오래된 보고서는 쓰기 전에 거부하고 기존 기록을 보존한다.

## Python 경계와 CLI

client는 `ask_json(system_prompt,user_prompt,temperature=None)`를 제공한다. client_factory는 인자 없이 새 과제 워커마다 독립 클라이언트를 반환하며 완료 평가 재사용·문서 재생성에는 호출하지 않는다.

| 호출 | 입력 → 반환·오류 |
| --- | --- |
| classify_task(task,options,client,progress_callback=None,*,catalogue=None) | 입력·옵션·주입 JSON 클라이언트 → schema2 결과. 잘못된 옵션은 ValueError, 실행/응답 문제는 안전한 오류 결과 |
| review_notices(task,client,*,catalogue=None,progress=None,chunk_chars=24000,max_calls=None) | 9열 과제·고정 기준본 → notice_review. 손상 기준본은 모델 호출 전 CatalogueError |
| load_catalogue(root=None) | 설치 또는 명시 경로 → 불변 Catalogue. manifest/검수/원문 불일치는 CatalogueError |
| make_template(path) | 저장 위치 → 9열 엑셀 양식 |
| run_excel(in_path,out_path,options,client_factory,*,resume=True,workers=3,make_forms=True,progress_cb=None,status_cb=None,cancel_event=None,catalogue=None,output_dir=None) | 엑셀·고정 옵션 → 순서 있는 결과·집계·경로·감사 상태. 전역 읽기/저장 오류는 BatchError |
| export_documents(result,output_dir) | 검증 결과 → documents 상태. 검증 실패는 ValueError, 파일별 쓰기 실패는 documents에 기록 |
| regenerate_documents(saved_result,output_dir) | 검증 결과 → documents를 갱신한 결과 사본 |
| persist_regenerated_documents(report,saved_result,regenerated_result) | 원래 보고서·전후 결과 → result·report·persistence. 분류 내용 변경은 BatchError, 저장 불일치/실패는 개별 상태와 경고 |

분류 진행 콜백은 안전한 사전 이벤트를 받고 배치 진행·상태 콜백은 문자열 한 개를 받는다. 워커에서 호출될 수 있으므로 UI 직접 변경에 사용하지 않는다. 과제별 모델·문서 실패는 다른 성공 결과를 지우지 않으며 감사 실패를 별도 경고한다.

대량 재출력 persistence는 전체 status와 checkpoint·workbook·audit의 완료/실패/미시도 및 warnings를 반환한다. 체크포인트 추가 → 엑셀 원자 교체 → 감사 추가 순서이며 엑셀 잠금으로 실패해도 성공한 체크포인트를 되돌렸다고 표시하지 않는다. 세 파일의 일괄 원자 저장을 보장하지 않는다.

`security_grade_classifier_v15.py --self-check 보고서.json`과 같은 실행 파일 옵션은 숨긴 실제 WebView·가짜 저장소·모의 모델로 자체 확인하며 JSON의 pass와 프로세스 종료 코드로 결과를 알린다. 실제 API 인증·계정 권한·한글 표시·Windows 배율 검증을 대신하지 않는다.

## v16 변경

v16은 위 v15 규약을 그대로 따르고 아래만 다르다. v16 결과·기록을 v15 경로로, v15 결과를 v16 경로로 읽지 않는다.

- 기준본: resources_v16/notices, `catalogue_id` `kr-notices-v16-1`. manifest 출처 키는 v15 키에 `announcement_date`(고시일, ISO)를 더한 집합과 정확히 같고, 키 순서에서 `effective_date` 바로 앞이다. 로더(notice_catalogue_v16)와 도메인 검증(v16_domain.validate_manifest) 모두 다음을 거부한다: ISO가 아닌 날짜, 고시일 > 시행일, 같은 고시번호의 날짜 불일치, 고시명 표(`NOTICE_TITLES`)에 없는 고시번호, 고시마다 `-body`로 끝나는 본문 출처가 정확히 하나가 아닌 경우. 로더의 고시명 표 사본은 도메인 표와 같아야 한다.
- 저장 결과: `schema_version` 3. 루트 키 25개·나머지 구조는 schema2와 같고 `notice_review`의 manifest·출처에 `announcement_date`가 있다. schema 3이 아닌 결과는 검증·재출력에서 거부한다.
- 브리지 함수 11개: v15의 9개에 아래 읽기 전용 2개를 더한다. 둘 다 모델·키·파일·작업 상태를 건드리지 않고, 진행 중인 작업이 있어도 호출할 수 있으며, 기준본을 읽지 못하면 `catalogue` 오류다.

  | 함수와 입력 | 성공 data | 오류 |
  | --- | --- | --- |
  | search_notice_clauses({query?,family?,offset?,limit?}) | total, offset, limit, items(clause_id·family·source_id·notice_number·code·title·field, 원문 없음) | 사전 아님·정의되지 않은 키·bool 정수·query 201자 이상(정규화 전)·family 오타·offset 음수·limit 0 또는 101 → validation |
  | get_notice_clause(clause_id) | clause_id, family, source_id, notice_number, notice_title, announcement_date, effective_date, official_url(그 조항 출처의 URL), code, title, field, source_anchor, text(원문 그대로) | 문자열 아님 → validation, 없는 조항 → not_found |

  검색은 검색어와 조항의 clause_id·code·title·field·text를 NFKC → 모든 공백 문자 제거 → casefold로 정규화한 뒤 부분 문자열로 비교한다. 기본값은 query "", family null(전체), offset 0, limit 50이고 순서는 기준본 조항 순서다. 정규화는 비교에만 쓰고 반환값은 원문 그대로다. 검색 결과 없음은 비해당 판정이 아니다.
- get_initial_state: `catalogue.sources`에 `announcement_date`, 새 키 `catalogue.notices`(고시번호별 notice_number·title·announcement_date·effective_date·families·source_ids·official_url, 기준본 출처 순서의 첫 등장 순서, official_url은 본문 출처의 URL)와 `catalogue.notice_titles`(고시번호→고시명 전체 표). `guideline`은 `{id, definitions:[{heading,text}], principles:[{title,details:[문자열]}]}`이며 내용은 법 제21조④⑤·시행령 제45조①②·가이드라인 일반과제 설명·분류 원칙 4개의 원문 인용이다.
- 고정 오류 문구와 진행 이벤트는 브리지 `_MESSAGES`·`_EVENTS`의 명사형 개조식 문구다. 오류 code 집합은 v15와 같다.
- 결과 엑셀: 시트·열 이름은 v15와 같고 `고시기준본` 시트에만 `고시일` 열이 `시행일` 바로 앞에 들어간다. 그 뒤 열은 한 칸씩 밀린다.
- HWPX: 서식은 templates/v15 그대로. 출처 부록 제목은 `출처 및 버전·고시일·시행일·URL·SHA256`, 출처별 `고시일` 항목이 `시행일` 앞에 온다. 그 밖의 의견서 문구는 v15와 같다.
- 일괄 검토 결과 보호: 결과 경로 옆 중간 저장 파일에 정수 `schema_version`이 3 미만인 기록이 하나라도 있거나, 결과 엑셀이 이미 있는데 열 수 있고 `고시기준본` 시트 머리 행에 `고시일`이 있는 v16 결과로 확인되지 않으면 `batch_v16.PreviousResultError`(BatchError 하위)로 멈춘다. 재개 여부와 관계없고, 중간 저장 초기화·엑셀 교체·감사·모델 호출 전에 멈추며 기존 세 파일은 바이트까지 그대로다. 브리지는 오류 code `io`를 유지하고 진행 이벤트에 `batch_v16.PREVIOUS_RESULT_MESSAGE`를 남긴 뒤 작업을 `failed`로 끝낸다(취소 요청이 먼저 있었어도 failed). 해독할 수 없는 줄·정수가 아닌 버전 값은 이전 버전 근거로 보지 않고 v15처럼 경고 후 새로 처리한다.
- 실행 파일: `dist-v16/보안등급분류시뮬레이터_v16.exe`, 결과 엑셀 기본 이름 `v16_검토결과.xlsx`. `--self-check`는 v15 범위에 새 함수 2개의 정상·오류 응답, 진행 중 호출, 허용 목록 정확히 11개를 더해 확인한다.
