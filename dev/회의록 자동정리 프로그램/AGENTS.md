# 회의록 자동정리

회의 녹음을 전사하고, 발언자를 맞추고, 기관별로 요약한다. 사람이 각 단계를 고친 뒤 KISTEP 회의록 양식(`template.hwpx`)을 채운다. 전사는 OpenAI `whisper-1`, 매칭·요약은 `gpt-6-luna`가 하며 키는 하나다.

## 범위
- **현재 버전**: `회의록정리v3.1/`(`app.py`의 `APP_VERSION = "v3.1.0"`).
  - 이 폴더는 **자체 git 저장소**다. 커밋은 이 폴더 안에서 하고, 상위 저장소에서는 다루지 않는다.
- **보존만 하는 폴더**(수정·삭제 금지)
  - `회의록정리v1/`, `회의록정리v2/`
  - `회의록정리v3/`: 모델 `gpt-5.6-luna`. v3.1에 문제가 생기면 이 폴더의 exe로 되돌린다.

## 구조 (현재 버전)
- `app.py`: 127.0.0.1 임의 포트 HTTP 서버와 pywebview 창, 처리 상태(`ST`), 세션 저장·복원, 명령줄(`--cli`, `--session`)
- `config.py`: 모델 상수(`STT_MODEL`, `SUMMARY_MODEL`), 키 결정(`api_key()`: 내장 키 → 환경변수), 설정 파일(`%APPDATA%\KISTEP회의록정리\config.json`, `DEFAULTS` 키만 저장)
- `audio.py`: `MAX_UPLOAD_BYTES`(24MiB) 이하이면서 확장자가 `OPENAI_EXTS`(flac·mp3·mp4·mpeg·mpga·m4a·ogg·wav·webm)인 파일만 그대로 올린다. 그 밖은 16kHz 모노 WAV로 바꿔 `CHUNK_SECONDS`(10분) 단위로 나눈다(PyAV 또는 ffmpeg 필요)
- `stt.py`: Whisper 호출, `verbose_json` 구간, 표준 라이브러리 스트리밍 multipart 업로드
- `summarizer.py`: Chat Completions 호출, strict JSON 스키마
  - 발언자 매칭: `SPEAKER_BATCH = 400`구간씩
  - 기관별 요약, 연결 확인(ping)
- `hwpx_writer.py`: 자리표시자 치환, 기관별 요약 표 재구성, 전사문 txt
- `selftest.py`: API 없이 hwpx 생성 점검. `tests/test_summary_model.py`: 모의 HTTP 응답 시험
- `ui/index.html`: 화면 전체(설정 → 전사 → 참석자·발언자 → 요약 → 문서)
- `embedded_key.py`: 내장 키(커밋 금지, 상위 저장소 `.gitignore`와 이 저장소 `.gitignore` 모두에 등록)

## 경계
- HTTP는 표준 라이브러리 `urllib`로만 한다. `openai`·`requests` SDK를 들이지 않는다. exe 크기와 오류 본문 그대로 보여 주기 때문이다.
- 키는 `embedded_key.py`와 환경변수 `OPENAI_API_KEY`에서만 읽는다.
  - 키를 화면 상태·설정 파일·세션·로그로 내보내지 않는다(`settings()`는 키를 빼고 보낸다).
  - 화면에 키 입력란을 다시 만들지 않는다.
- 모델은 `config.py` 상수에서만 정한다.
  - `STT_MODEL`은 `whisper-1` 고정이다. 구간 시각을 주는 모델이 이것뿐이라 바꾸면 발언자 매칭이 깨진다.
  - 모델 선택 화면이나 자동 대체 모델을 만들지 않는다.
- 녹음 파일은 전사 단계에만 보낸다. 매칭·요약에는 텍스트만 보낸다.
- `embedded_key.py`와 실제 회의 녹음·전사문을 시험 자료로 읽지 않는다.

## 지켜야 할 것
- **요청 형식**
  - 엔드포인트 `POST https://api.openai.com/v1/chat/completions`
  - `response_format.type=json_schema`, `strict=true`, 세 스키마 모두 `additionalProperties=false`
  - `max_completion_tokens`: 매칭 16,000, 요약 32,000, 연결 확인 2,000
  - 요청 제한 시간 900초
  - `reasoning_effort`·샘플링 매개변수는 넣지 않는다.
  - 400 오류가 `max_completion_tokens`를 모른다고 하면, 같은 값을 `max_tokens`로 바꿔 한 번 더 보내는 처리를 유지한다(구형 모델 대응).
- **매칭 결과**: `turns[{from, to, speaker}]`를 구간에 반영한다. 명단에 없는 이름은 `미상`이다.
- **요약 결과**
  - `title`·`agenda`·`implications`·`feedback_plan`·`institutions[{name, items[{topic, content}]}]` 형식이다.
  - 이름이나 항목이 빈 기관은 지운다. 남는 기관이 없거나 전사문이 비어 있으면 실패로 끝낸다.
  - 공문서체로 쓰고, 근거 없는 수치·기관·계획을 만들지 않는다(프롬프트 규칙).
- **오류 처리**: 인증·한도·접근(404)·거부·길이 초과·빈 응답·JSON 오류는 사람이 읽을 수 있는 안내로 실패시킨다.
- **세션**
  - 화면에서 불러오면 전사를 건너뛰고, 불러온 요약을 자동으로 다시 요약하지 않는다.
  - 명령줄 `run_cli()`의 `--session`은 전사만 건너뛴다.
    - 참석자(`--attendees`, 없으면 세션의 명단)가 있으면 매칭을 다시 하고, 요약은 항상 다시 한다(유료 호출, 세션의 요약을 덮어씀).
    - 세션의 회의 정보는 `--title`·`--date`·`--place`보다 나중에 적용되어 이긴다.
    - 이 동작을 바꾸려면 사용자에게 먼저 확인한다.
- **hwpx 기관별 요약 표**
  - 원형 행 세 개(첫 블록 시작행, 블록 안쪽 행, 둘째 이후 블록 시작행)를 복제한다.
  - 복제한 뒤 `rowAddr`·`rowCnt`·`cellSpan@rowSpan`·`cellSz@height`·표 `sz@height`를 다시 계산한다.
  - 셀 안 줄바꿈은 첫 문단을 본떠 문단을 복제한다.
- **산출물 이름**: `<YYYYMMDD>_<제목>_회의록.hwpx`·`_전사문.txt`·`_세션.json`.

## 시험
- 이 폴더에서 실행한다.
  ```
  python -m unittest discover -s tests -p test_summary_model.py
  python selftest.py
  ```
  둘 다 종료 코드 0이어야 한다. `selftest.py`는 합성 자료로 기관 3곳(항목 3·2·1개 → rowSpan 3·2·1, 7행)을 검증하고 `_selftest_*` 파일을 만든다. 이 파일들은 검증용이다.
- 요청·응답 처리를 고쳤으면 모의 HTTP 응답으로 확인한다.
  - 정상 JSON, 거부, 길이 초과, 빈 응답, 잘못된 JSON, 모델 접근 불가(404)
  - 400구간 경계를 넘는 매칭
- 실제 API 확인은 자동 시험에 넣지 않는다. 배포 전에 사람이 확인한다.
  - 새 exe에서 [요약 모델 연결 테스트]를 실행한다(소액 과금).
  - 합성 회의 자료로 매칭 → 요약 → 수정 → 세션 저장·복원 → hwpx를 진행한다.
  - 구간 누락·중복, 명단 밖 화자, 근거 없는 수치·계획, 주요 발언 누락, 기관 혼합을 본다. 하나라도 있으면 배포를 미룬다.
- 빌드: `build_exe.bat`(폴더로 이동한 뒤 빌드) 또는 `python -m PyInstaller --noconfirm --clean 회의록자동정리.spec` → `dist\회의록자동정리v3.1.exe`.
  - `embedded_key.py`의 키와 (있으면) PyAV가 함께 묶인다.
  - 모델을 바꿨으면 반드시 다시 빌드한다.
