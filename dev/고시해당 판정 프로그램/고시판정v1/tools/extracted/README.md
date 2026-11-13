# 기준값 추출 파일 작성 지침

이 폴더의 `*.json`은 고시 원문에서 손(또는 AI)으로 뽑은 기준값이다. `tools/build_threshold_table.py`가 이 파일들과
고시 자료의 숫자 조건(structured)을 합쳐 `resources/thresholds.json`(기준값 표)을 만든다.
표는 판정 엔진이 그대로 쓰므로, 여기 적힌 수·단위·인용이 틀리면 판정이 틀린다. 아래 규칙을 그대로 따른다.

## 파일 하나의 형식

```json
{
  "scope": {"families": ["dual_use"], "code_prefixes": ["0", "1", "2"]},
  "items": [ ...항목 기록... ]
}
```

- `scope`: 이 파일이 **맡은 범위**. 도구는 이 범위 안의 실제 검토 항목(`notice_catalogue.clause_index`)이 모두
  `items`에 있는지 확인한다(누락 검사). 범위 밖 항목이 들어 있으면 오류다.
  - `families`: `advanced`(국가첨단전략기술) · `core`(국가핵심기술) · `dual_use`(이중용도) · `military`(군용) 중 하나 이상.
  - `code_prefixes`: 이중용도(`dual_use`)에만 쓴다. 통제번호 첫 글자(`"0"`~`"9"`) 목록. 없으면 그 범위 전부.
    군용·첨단·핵심은 `families`만 적는다.
- `items[]`: 항목 기록. 범위 안의 항목은 **숫자 기준이 없어도** 넣는다(`"branches": []`). 그래야 "검토했지만 숫자 기준이
  없다"와 "아직 안 봤다"가 구분된다. 예외: 아래 '이미 structured로 들어간 41개 항목'은 빼도 된다.

### 항목 기록

```text
clause_id   기준본의 항목 ID (예: "dual_use:control:1A003", "core:item:060", "military:control:ML1", "advanced:item:013")
title       선택. 색인용 짧은 제목. 없으면 도구가 채운다(첨단·핵심은 항목 제목, 이중용도·군용은 [국문 원문] 첫 줄).
branches[]  갈래(OR). 하나만 맞으면 되는 대안. 숫자 기준이 없으면 빈 목록.
  branch_id   선택. 없으면 도구가 "<clause_id>:b<n>"으로 붙인다. 적는다면 같은 꼴로, 표 전체에서 유일하게.
  label       갈래 설명 원문(예: "a." 또는 "파우치형"). 없으면 "".
  thresholds[] 갈래 안 기준(AND). 모두 맞아야 그 갈래가 맞는다. 숫자 없는 갈래면 빈 목록.
    subject      물리량 이름(짧게. 예: "제조품 두께", "에너지밀도")
    operator     "ge"(이상) | "gt"(초과) | "le"(이하) | "lt"(미만)
    value        10진수 **문자열**. 예: "0.254", "15000". 원문이 "15,000"이어도 수는 "15000". 단위 환산은 하지 않는다.
    unit         단위. 원문 표기 그대로 적어도 된다(㎛·um·나노·리터·톤 …). 도구가 `units.py` 별칭표로 표준화한다.
                 단위가 없으면 "". 별칭표에 없는 단위는 채택되지 않는다(아래 검증 3).
    quote        원문 인용. 수·단위·비교어가 모두 들어가게 **원문 그대로** 짧게 자른다.
    quote_source "항목 본문" | 연결된 공통 정의·주석의 clause_id (항목의 qualifier_refs에 있는 것만)
  text        숫자 없는 갈래의 원문 인용. 숫자 갈래면 "" (쓰지 않는다).
checks[]    숫자 외 확인 조건(형태·용도·제외 규정 등). 각각 quote(원문 인용)와 source("항목 본문" | 연결된 조항 ID).
```

`origin`·`rejected`·`numeric_status`는 적지 않는다. 도구가 채운다.

## 작성 규칙

1. **원문 그대로 인용한다.** `quote`·`text`·`checks.quote`는 출처 원문에 이어진 구간으로 있어야 한다. 도구는 공백·줄바꿈만
   연속 공백 하나로 맞춰 비교하고 다른 글자는 그대로 비교한다. 원문이 "기\n\n 술"처럼 끊겨 있으면 그 부분을 피해서 자르거나
   줄바꿈을 포함해 그대로 적는다. 요약·의역·오타 수정은 하지 않는다.
2. **수를 바꾸지 않는다.** `value`는 인용 안의 수와 같아야 한다. 쉼표 자리 구분("15,000"→"15000")과 만·천·억
   ("1만"→"10000", "3천"→"3000", "1만5천"→"15000")만 같은 수로 본다. 단위 환산(1㎛→1000nm)은 하지 않는다.
3. **기준이 수가 아니면 `checks`로.** "FHD 이상", "4K 이상", "REC2020 기준" 같은 것은 기준값이 아니라 확인 조건이다.
   값이 10진수가 아니면 도구가 채택하지 않는다.
4. **비교어와 operator를 맞춘다.** 이상·or more·at least→`ge`, 초과·넘는·exceeding·more than→`gt`,
   이하·이내·or less·not exceeding→`le`, 미만·못 미치는·less than→`lt`. 인용 안의 비교어 방향이 operator와 다르면 채택되지 않는다.
5. **하위 항목 a/b/c마다 기준이 다르면 갈래로 나눈다.** `label`에 "a."처럼 하위 항목 번호를 적는다.
   한 하위 항목 안에서 "그리고(and)"로 묶인 기준은 같은 갈래의 `thresholds`에 함께 넣는다.
6. **관계가 불분명하면 OR 갈래로 나누고 `label`에 하위 항목 번호를 적는다.** AND로 묶어 놓치는 것보다 OR로 넓게 잡는 쪽이
   안전하다(기준을 넘는 쪽을 놓치지 않는 원칙).
7. **공통 정의·주석에서 인용할 때**는 `quote_source`에 그 조항 ID를 적는다. 그 ID가 항목의 `qualifier_refs`에 없으면 채택되지 않는다.
   항목의 `qualifier_refs`는 `notice_catalogue.clause_record(catalogue, clause_id)["qualifier_refs"]`로 본다.
8. **같은 항목을 두 파일에 넣지 않는다.** 겹치면 도구가 오류로 멈춘다.
9. **이미 structured로 들어간 41개 항목**은 고시 자료의 숫자 조건이 그대로 표에 들어간다. 이 항목은 파일에서 빼도 되고,
   넣는다면 structured에 없는 갈래·확인 조건만 더한다. structured와 같은 값(operator·value·unit)을 다시 적으면 중복으로
   '채택 실패'에 남는다(표에는 structured 쪽만 둔다).
   - advanced:item: 001, 002, 003, 004, 005, 007, 010, 012, 013, 014, 016, 017, 018, 019
   - core:item: 001, 003, 005, 008, 009, 015, 016, 018, 024, 028, 031, 032, 033, 034, 037, 041, 060, 061, 062, 063, 066, 068, 069, 078, 079
   - dual_use:control: 1A003, 3A102
10. 첨단(advanced) 항목의 본문 제4조(양산 목적) 조건은 도구가 `checks`에 항상 넣는다. 따로 적지 않아도 된다.

## 도구가 하는 검증(spec 4.2) — 어긋나면 채택하지 않고 '채택 실패'에 사유와 함께 남긴다

1. `quote`가 `quote_source` 원문 안에 이어진 구간으로 있다(공백·줄바꿈만 하나로 맞춤).
2. `quote` 안에 `value`와 같은 수가 있다(쉼표·만·천·억 표기 허용).
3. `quote` 안에 `unit`이나 그 별칭(`units.py` 별칭표)이 있다. `unit`이 ""이면 보지 않는다.
4. `quote` 안에 비교어가 있고 그 뜻이 `operator`와 같다.
5. `quote_source`가 공통 정의·주석이면 그 ID가 항목의 `qualifier_refs`에 있다.
6. `checks`의 인용도 1번 방식으로 `source` 원문에 있고, `source`가 항목 본문이거나 `qualifier_refs`에 있다.

채택 실패가 있어도 전체 생성은 되지만(항목은 `기준값 채택 실패`로 표시) **고쳐서 없애는 것이 원칙**이다.

## 확인 방법

파일 하나를 쓴 뒤 프로그램 폴더(`고시판정v1`)에서 아래를 실행한다. 아무 파일도 쓰지 않고, 그 파일 범위의 누락·채택 실패·
형식 오류를 출력한다. 문제가 있으면 종료 코드가 0이 아니다.

```text
python tools/build_threshold_table.py --check tools/extracted/dual_use_2.json
```

모든 파일이 통과하면 전체 생성: `python tools/build_threshold_table.py` → `resources/thresholds.json`과
`tools/output/기준값_검수.xlsx`(기준값·확인 조건·숫자 기준 없음·채택 실패·누락·범위별 건수)를 쓴다. 507개 항목이 하나라도
빠지면 표를 쓰지 않는다.

## 예시

이중용도 1A003(가상의 축약 원문 기준. 실제 작성 때는 기준본 원문을 그대로 인용한다):

```json
{
  "scope": {"families": ["dual_use"], "code_prefixes": ["1"]},
  "items": [
    {
      "clause_id": "dual_use:control:1A003",
      "title": "비가용성 방향족 폴리이미드 제조품",
      "branches": [
        {
          "label": "a.",
          "thresholds": [
            {
              "subject": "제조품 두께",
              "operator": "gt",
              "value": "0.254",
              "unit": "mm",
              "quote": "두께가 0.254 mm 를 초과하는 것",
              "quote_source": "항목 본문"
            }
          ],
          "text": ""
        },
        {
          "label": "b.",
          "thresholds": [],
          "text": "탄소, 흑연, 금속, 또는 자성 물질로 코팅되었거나 적층구조물로 만들어진 것"
        }
      ],
      "checks": [
        {"quote": "필름, 판, 테입, 리본 형태의 비\"가용성\" 방향족 폴리이미드의 제조품", "source": "항목 본문"},
        {"quote": "구리로 코팅되거나 적층되었으며, 전자인쇄회로 기판의 \"생산\"을 위해 설계된 제품은 통제하지 않는다", "source": "항목 본문"}
      ]
    },
    {
      "clause_id": "dual_use:control:1A004",
      "branches": [],
      "checks": [
        {"quote": "방호 및 탐지 장비와 구성품", "source": "항목 본문"}
      ]
    }
  ]
}
```

(1A003은 structured 항목이라 실제로는 빼도 된다. 형식을 보이기 위한 예시다. 1A004의 인용도 예시이며 실제 원문과 다를 수 있다.)
