# 연구보안 등급분류 시뮬레이터 작업 지침

중앙행정기관·연구관리 전문기관이 보안등급 심의를 준비하는 Windows 도구다. v15는 단일 WebView2 창의 웹 UI와 Python 분류·고시 대조·엑셀/HWPX 출력을 연결한다. AI 에이전트의 참고 의견은 실제 위원회 의결·서명·행정기관 확정을 대신하지 않는다. 실제 운영 기준은 별도 사용자 전환 결정 전까지 v12이며 v13·v14와 과거 파일은 보존한다.

## 전체 구조

```text
보안등급분류 시뮬레이터/
├── AGENTS.md                               → 작업 진입점·루트 기능별 경계
├── CLAUDE.md                               → AGENTS.md와 바이트까지 동일한 지침
├── README_v15.md                           → v15 설치·사용·실제 검증 수준
├── requirements_v15.txt                    → v15 실행·빌드 고정 의존성
├── security_grade_classifier_v15.py        → WebView2 호스트·로컬 자산·네이티브 경계·자체 확인
├── desktop_bridge_v15.py                   → 9개 비동기 API·작업·경로 토큰·결과 보존
├── v15_domain.py                           → 기준·계산·9열 입력·옵션·schema2 근거 규약
├── notice_catalogue_v15.py                 → 고정 공식 고시·검수·manifest 검증
├── notice_review_v15.py                    → 사실·색인·후보·조건/예외/참조 대조
├── classification_v15.py                   → 고시 근거와 두 방식·독립 에이전트·표준 의견 연결
├── hwpx_writer_v15.py                      → 저장된 근거의 편집 가능한 개별·종합 HWPX
├── batch_v15.py                            → 9열 엑셀·동시 처리·5시트·재개·감사·재출력
├── credential_store.py                     → 현재 Windows 계정의 제공자별 키 저장·재사용
├── llm_client_v14.py                        → 재사용 모델 SDK·로컬 요청·안전한 오류
├── ui_v15/                                 → 호스트가 로드하는 화면·로컬 폰트 자산
│   ├── index.html                          → 입력·설정·진행·결과 화면 구조
│   ├── styles.css                          → 회녹·아이보리·teal 디자인·작은 화면
│   ├── app.js                              → 비동기 브리지·상태·현재/목표 근거 표시
│   └── assets/                             → Pretendard 폰트와 라이선스
├── resources_v15/
│   └── notices/                            → 해시 고정 원문·정규화 조건·검수·manifest 자산
├── templates/
│   ├── reviewer_opinion.hwpx               → 보존된 v14 개인 서식
│   ├── committee_summary.hwpx              → 보존된 v14 종합 서식
│   └── v15/                                → 고시 근거 부록을 포함한 두 파생 서식
├── tests/                                  → 합성 입력·모의 모델·실제 Edge의 오프라인 검증
├── tools/                                  → 고시 기준본의 재현·검수 보조 도구
├── book_icon.ico                           → 공용 아이콘
├── 보안등급분류시뮬레이터_v15.spec           → v15 호스트·자산·SDK·WebView 구성요소 빌드
├── README_v14.md                           → 과거 v14 사용·검증 기록 보존
├── requirements_v14.txt                    → 과거 v14 환경 보존
├── security_grade_classifier_v14.py        → 보존된 Tkinter 검토 앱
├── v14_domain.py                           → 보존된 schema1·계산 규약
├── classification_v14.py                   → 보존된 v14 분류
├── hwpx_writer.py                          → 보존된 v14 출력
├── batch_v14.py                            → 보존된 v14 배치
├── security_grade_classifier_v12.py        → 실제 운영 기준의 기존 통합 앱
├── security_grade_classifier_v13_test.py   → 엄격도 선택을 둔 기존 검토 앱
├── security_grade_classifier_v10.py        → 과거 버전 보존
├── security_grade_classifier_v9.py         → 과거 버전 보존
├── security_grade_classifier_v8.py         → 과거 버전 보존
├── security_grade_classifier_v7.5.py       → 과거 버전 보존
├── security_grade_classifier_v7.py         → 과거 버전 보존
├── security_grade_classifier_v6.py         → 과거 버전 보존
├── security_grade_classifier_v5.py         → 과거 버전 보존
├── reference_lists.py                      → 독립 참조 자료·과거 내부 목록과 자동 연결 아님
├── excel_viewer.py                         → 별도 PySide6·pandas 열람기
├── 보안등급분류시뮬레이터_v14.spec           → 과거 v14 빌드 보존
├── 보안등급분류시뮬레이터_v12.spec           → 기존 v12 빌드 보존
├── 보안등급분류시뮬레이터_v12_claude.spec    → 기존 변형 설정 보존·새 배포 제외
├── 보안등급분류시뮬레이터_v10.spec           → 과거 빌드 보존
├── 보안등급분류시뮬레이터_v10_claude.spec    → 과거 변형 설정 보존·새 배포 제외
├── 보안등급분류시뮬레이터_v8.spec            → 과거 빌드 보존
├── 보안등급분류시뮬레이터_v7.5.spec          → 과거 빌드 보존
├── 보안등급분류시뮬레이터_v7.spec             → 과거 빌드 보존
└── docs/
    ├── architecture.md                    → 구성요소·의존 방향·데이터 흐름
    ├── business-rules.md                  → 본문 기준·두 방식·산식·고시·현재/목표
    ├── security.md                        → 전송·키·네이티브 접근·기록·배포 경계
    ├── standards.md                       → 변경·검증·커밋·모듈 경계 규칙
    ├── engineering-notes.md               → 네이티브·분할 요청·재출력·문서 검증의 함정
    ├── operations.md                      → 설치·실행·자체 확인·빌드
    ├── contracts.md                       → 9열·9API·schema2·고시 근거·저장/재개 계약
    └── tracking/
        ├── status.md                      → 구현·검증·남은 작업
        ├── findings.md                    → 보류 검증·미해석 조건·기관 정책·과거 한계
        └── decisions/
            ├── index.md                   → 확정 결정과 버전별 적용 범위
            ├── 0001-operating-version.md  → 운영 기준과 검토 경로 구분
            ├── 0002-summary-transfer.md   → 외부 전송·로컬 선택
            ├── 0003-opinion-strictness.md  → 과거 엄격도 선택·수치 분리
            ├── 0004-body-formula.md       → 본문 정의·산식 우선
            ├── 0005-exclusive-method.md   → 두 방식 중 하나
            ├── 0006-native-key-store.md   → 앱의 자동 Windows 키 저장
            ├── 0007-agent-naming.md       → AI 검토와 실제 사람 심의 구분
            ├── 0008-installed-web-ui.md   → 단일 창 설치형 웹 UI
            ├── 0009-frozen-notice-review.md → 고정 고시·현재/목표·부족정보
            └── 0010-standard-review-options.md → 표준 의견·자동 가중치 1.0
```

소스는 루트의 평면 모듈이며 가상의 패키지 폴더를 만들지 않는다. ui_v15·resources_v15·templates는 호스트·출력기가 소비하는 자산이므로 지침 파일을 무심코 추가해 서버·번들 목록이나 고시 지문을 바꾸지 않는다. build/dist·환경·입력·감사·체크포인트는 소스와 분리한다. 과거 Claude 변형은 키 형태 리터럴 위험으로 새 작업 사본·빌드에서 제외하며 사용자 원본을 임의 복원·삭제하지 않는다.

## 반드시 지킬 경계

- 실제 운영 v12와 과거 파일을 보존한다. 새 버전 검증을 운영 전환·과거 파일의 해결로 표시하지 않는다.
- AI 참고 의견과 사람의 심의·서명·행정기관 확정을 구분한다. 정보 부족을 임의 점수·일반과제로 채우지 않는다.
- 키를 소스·로그·결과·배포에 넣지 않는다. 실제 민감 자료와 전체 가이드라인을 커밋·배포하지 않으며 업무 산출물은 기관 방침에 맞게 보호한다. 입력 및 파일 접근은 승인된 경로와 전송 범위로 제한한다.
- 저장 결과·고시 근거는 공통 검증을 통과시킨다. 다른 입력·기준·설정의 결과나 오래된 문서 상태를 재사용하지 않는다.
- 사용자가 중단한 데스크톱 제어를 명시적 재개 전 시작하지 않는다. 숨긴 화면·구조 검증을 실제 한글·Windows 배율 검증으로 표시하지 않는다.

## 작업 전 확인

docs/standards.md와 docs/engineering-notes.md를 먼저 읽는다. 기준·가중치·고시 조건 변경 전 docs/business-rules.md, 입력·저장 구조·브리지 변경 전 docs/contracts.md, 키·전송·네이티브 메시지 변경 전 docs/security.md, 환경·빌드 변경 전 docs/operations.md를 확인한다. 최종 가이드라인은 이미 승인됐으며 사례 불일치보다 본문 법령·정의·산식을 적용한다. 한국어 UTF-8·4칸 Python 들여쓰기를 유지하고 무관한 재서식화를 하지 않는다.

## 루트 기능별 작업 경계

- v15_domain.py는 유일한 계산·정규화·schema2 검증 기준이다. 자동 선택의 잔존 수동 값 무시·가중치 1.0, 직접 가중치 검증·조건부 8번·표준 고정을 우회하지 않는다. 3.5/4.5 경계·NaN·누락·시점·단위·근거 스냅샷의 회귀를 확인한다.
- notice_catalogue_v15.py와 tools의 기준본 도구는 공식 원문·검수·manifest를 함께 관리한다. 고시 자산 내부에 임의 지침·시험 파일을 넣지 않는다. 원문 확보와 조건 의미 지원을 구분하고 런타임 자동 갱신을 넣지 않는다.
- notice_review_v15.py는 주입 JSON 클라이언트로 사실·전체 색인·후보 조건 및 참조를 대조한다. 실제 요청을 손실 없이 분할하고 호출 사이 기억을 가정하지 않는다. 숫자·단위·속성·시점 근거와 세 값 조건식을 검증하며 미해석 조건을 모델 추정으로 해소하지 않는다.
- classification_v15.py는 고시 근거와 정확한 모델을 고정한 뒤 독립 에이전트와 표준 의견을 연결한다. 한 에이전트 실패를 빼고 정상 평균을 만들지 않으며 고시 오류·미해결 상태를 숨기지 않는다.
- llm_client_v14.py와 credential_store.py는 재사용 경계다. 정확한 두 외부 모델을 대체하지 않고 원문 키를 renderer·설정·로그에 넣지 않는다. 시험은 가짜 저장소로 하며 실제 사용자 자격증명을 열거·읽기·변경하지 않는다. 저장 실패의 세션 메모리 사용 정책을 평문 저장으로 확대하지 않는다.
- desktop_bridge_v15.py는 정확한 9API·경로 토큰·한 활성 작업·단조 이벤트·이전 결과와 최신 배치 문맥을 소유한다. renderer가 만든 결과나 경로를 신뢰하지 않는다. 인자 바인딩부터 안전한 오류 경계로 감싸고 A→B→A 재출력과 잘못된 토큰·취소·키 비노출을 시험한다.
- security_grade_classifier_v15.py는 고정 로컬 자산·첫 로드 이전 네이티브 원본/패킷/9함수 검사·외부 요청/탐색/새 창 차단·WebView2 강제를 소유한다. js_api 객체 노출·구형 엔진 자동 전환을 넣지 않는다. 실제 WebView에서 정상 API와 private/dunder/builtin 거부를 함께 검사한다.
- ui_v15는 화면과 브리지 소비만 소유한다. 분류 계산·고시 판정·키 저장·파일 쓰기를 JavaScript에 복제하지 않는다. 원문을 HTML로 삽입하거나 키를 DOM/브라우저 저장소에 재주입하지 않는다. 자동 1.0 안내·표준 고정·AI 전문가 명칭·현재/목표·부족 질문·새 내보내기 작업 ID를 유지하며 tests/test_v15_frontend.py의 실제 Edge·390/1366 폭·장문·악성 태그·모의 9API를 확인한다. 외부 CDN·새 창·원격 리소스를 추가하지 않는다.
- hwpx_writer_v15.py는 검증된 저장 결과와 두 파생 서식만 사용한다. 모델·키·현재 설치 기준본 조회 없이 개인별 실제 의견·전체 고시 참조·AI 표시·빈 사람 서명을 보존한다. 문서별 실패와 ZIP/XML·긴 한글·부록을 확인한다.
- batch_v15.py는 모든 행 검증 뒤 독립 작업을 시작하고 조정자만 저장한다. schema2 지문·수식 텍스트·긴 셀 이어쓰기·5개 시트·오래된 보고서 거부·수량 제한 없는 문서 요청을 유지한다. 체크포인트·엑셀·감사를 하나의 원자 저장으로 표시하지 않는다.
- reference_lists.py·과거 앱 내부 목록·excel_viewer.py는 새 고시와 자동 연결되지 않는다. 독립 열람기의 PySide6·pandas를 v15 빌드에 추가하지 않는다. requirements_v15.txt·v15 .spec·README_v15.md와 실제 실행 경로·자산 목록을 함께 확인한다.

## 검증과 문제 처리

합성 과제·모의 모델·가짜 저장소의 unittest, 문법 검사, source·실행 파일의 숨긴 실제 WebView 자체 확인을 사용한다. 종료 코드와 새 보고서의 pass를 모두 확인한다. 구조·모의 SDK·실제 Edge 렌더링·숨긴 네이티브 WebView·한글 실열람·전경 UI·실제 Windows 배율·빌드를 구분한다. 실제 계정·유료 API·실무 정확도는 자동 회귀로 검증하지 않는다.

의도하지 않은 외부 전송, 키·민감 자료 노출, 임의 파일 접근·비공개 브리지 호출, 다른 입력 결과 재사용, AI 의견의 공식 확정 오표시는 즉시 알린다. 실제 활성 키 노출이면 제공자 측 폐기가 필요하다. 그 밖의 미해결 문제는 재현 조건·영향·해결하지 못한 이유·실제 검증 범위를 docs/tracking/findings.md에 남긴다. 기관별 보관·접근·삭제·감사 필수 정책과 예시과제집 정답·공개 범위를 추측해 정하지 않는다.
