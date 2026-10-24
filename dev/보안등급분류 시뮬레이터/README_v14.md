# 연구보안 등급분류 시뮬레이터 v14

최종 가이드라인에 따라 체크리스트 또는 국가영향 지표 한 방식을 선택하고, AI 에이전트별 의견과 종합 AI 참고 의견을 확인하는 Windows/Tkinter 도구다. 실제 위원회 의결·서명·중앙행정기관 확정을 대신하지 않는다. v12는 사용자의 별도 전환 결정 전까지 실제 운영 기준이며 v13과 이전 파일은 보존한다.

## 설치와 실행

프로젝트 폴더에서 Tkinter를 포함한 64비트 Python으로 실행한다. 확인 환경은 Windows, Python 3.14.6, Tk 8.6.15다. 아래 명령은 새 가상환경용이며 기존 환경을 덮어쓸 필요는 없다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements_v14.txt
.\.venv\Scripts\python.exe .\security_grade_classifier_v14.py
```

실행 의존성은 lxml 6.1.1, openpyxl 3.1.5, requests 2.34.2, OpenAI SDK 2.47.0, Anthropic SDK 1.3.0이고 빌드는 PyInstaller 6.21.0을 사용한다. Anthropic의 필수 httpx2 등 전이 의존성은 pip가 설치한다. pandas·python-docx·PySide6·모델 가중치는 v14 실행 요건이 아니다.

## 사용

기능명은 ‘AI 에이전트 검토’다. 1개 구성은 AI 기술분야 전문가, 3개 구성은 AI 기술분야 전문가·AI 연구보안 전문가·AI 기술사업화 전문가다. 출력은 에이전트별 검토의견서와 AI 종합 검토의견서이며 실제 사람의 심의·의결과 구분한다.

1. 설정에서 Claude Sonnet 5.5 (`claude-sonnet-5-5`), OpenAI GPT-6 Luna (`gpt-6-luna`), Ollama 또는 LM Studio를 선택한다. 외부 모델은 다른 이름으로 자동 대체하지 않는다. 계정 권한·실제 인증 성공은 별도다.
2. 새 키를 입력하고 설정을 적용하면 앱이 Windows 보안 저장소에 제공자별로 자동 저장한다. 같은 PC·Windows 계정의 다음 실행에 불러오며 별도 Windows 창 조작이나 저장 비밀번호가 필요 없다. 교체·삭제도 앱에서 한다. 저장 실패 시 상태를 확인하고 이번 실행의 메모리 입력을 사용할 수 있다.
3. 과제명·연구목표·연구내용·기대효과를 입력하거나 엑셀 양식을 생성해 대량 입력한다. 세부사업명·추가 검토정보·부처 세부기준은 선택 입력이다. 과제명은 필수다.
4. 체크리스트는 점수·가중치를 만들지 않는다. 국가영향 지표는 공통 항목과 가중치로 AI 에이전트 1개 또는 3개를 독립 평가한다. 8번 항목은 실제 부처 세부기준이 있어야 적용된다. 엄격도는 마지막 종합 의견에만 적용된다.
5. 참고 등급과 함께 `완료/검토필요/후보제외/오류`, 에이전트별 근거, 문서 상태를 확인한다. 부족한 응답은 임의 점수·등급으로 메우지 않는다. 단건은 HWPX 저장으로 위치를 선택하고 대량은 기본으로 개별 의견서와 AI 종합 검토의견서를 생성한다. 문서 다시 저장은 보존한 결과로 수행하며 모델을 다시 호출하지 않는다.

국가영향 가중치는 0.8~1.2, 선택 항목 평균 1.0이어야 한다. 에이전트 점수는 `Σ(가중치×정수점수)/선택항목수`, 에이전트 평균은 전체 예정 에이전트의 평균이다. 중간 반올림 없이 계산하고 표시 때 반올림한다. 3.5·4.5 구간은 우선 검토 참고이며 법적 정의를 자동 대체하지 않는다.

대량 결과는 결과 엑셀, `<결과경로>.checkpoint.jsonl`, `<결과경로>.audit.jsonl`, `<결과명>_HWPX/<실행식별자>/`에 남는다. 재개는 과제 내용·비밀을 제외한 옵션·기준 식별이 일치하는 완료 평가만 재사용한다. 구버전·손상 기록은 경고 후 재사용하지 않는다. 입력 엑셀과 다른 결과 경로를 선택하고 결과 파일을 다른 프로그램에서 닫는다.

외부 전송은 입력한 과제요약과 추가 검토정보·부처 기준, 판단·참조 정보에 한한다. 전송할 수 없는 정보는 로컬 모델로 처리하며 설정한 서버 주소의 실제 목적지를 확인한다. API 키는 소스·결과·체크포인트·문서·로그에 기록하지 않는다. 환경변수 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`는 저장 키가 없을 때 사용할 수 있으나 자동 영구 저장하지 않는다. 앱의 키 삭제는 제공자 계정의 키 폐기가 아니다.

## 오프라인 확인과 빌드

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m py_compile security_grade_classifier_v14.py v14_domain.py classification_v14.py llm_client_v14.py credential_store.py batch_v14.py hwpx_writer.py
.\.venv\Scripts\python.exe security_grade_classifier_v14.py --self-check .\build\source-self-check.json
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm '보안등급분류시뮬레이터_v14.spec'
$check = Start-Process -FilePath '.\dist\보안등급분류시뮬레이터_v14.exe' -ArgumentList '--self-check', '.\build\frozen-self-check.json' -WindowStyle Hidden -PassThru -Wait
$check.ExitCode
Get-Content -LiteralPath '.\build\frozen-self-check.json' -Encoding UTF8
```

자체 확인은 숨긴 Tk 창·가짜 키 저장소로 v14 제목, 지정 모델, 두 SDK import와 두 템플릿 ZIP을 검사한다. 네트워크·실제 자격증명을 사용하지 않는다. 종료 코드 0과 새 보고서의 `status: passed`를 함께 확인한다. 빌드는 v14 진입점·아이콘·두 파생 템플릿·필수 SDK만 포함하는 단일 실행 파일이며 원본 가이드라인·과거 스크립트·실제 입력·감사·키를 포함하지 않는다.

## 확인 수준과 남은 범위

2026-10-20 기준 새 명칭·점수 표시를 반영한 오프라인 회귀검증 134개, 7개 모듈 문법 확인, 새 실행 파일 빌드와 소스·실행 파일의 숨김 자체 확인을 통과했다. 실행 파일은 일반 Windows 세션에서 두 SDK와 두 템플릿을 불러왔다. 두 실제 SDK를 모의 HTTP로 호출한 요청 형식 검증, 가짜 전용 이름을 사용한 Windows 키 저장·재로드·교체·제공자 분리·삭제도 확인했다. 숨긴 화면의 로직과 글꼴 배율 1/1.25/1.5 검사는 실제 Windows 배율의 시각 확인과 다르다.

명칭·점수 표시 변경 전 출력에 대해 한글 2024에서 국가영향 지표·1개 에이전트별 검토의견서 합성 출력은 복구 경고 없이 열리고 3쪽 및 첫 페이지 표 텍스트를 확인했다. 다른 방식·3개·AI 종합 검토의견서·긴 문서의 구조 검증은 통과했으나 전체 실제 열람, 정상·오류 화면의 육안 확인, 작은 화면·Windows 125%/150% 배율 확인은 남아 있다. 사용자의 데스크톱 제어 중단에 따라 추가 직접 확인을 보류했다. 따라서 전체 검증 완료·운영 전환 완료로 표시하지 않는다. 유료 API·실제 계정 접근·실무 분류 정확도는 시험하지 않았다. 기관별 보관·접근·삭제·감사 필수 정책과 예시과제집 검토·공개 범위는 미정이다.
