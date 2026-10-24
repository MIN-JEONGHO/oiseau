"""Offline v16 renderer regressions: real Edge DOM, fake public bridge, no accounts.

Run with the v15 development environment (Playwright is a test-only tool).
The browser uses a fresh profile, never the person's browser or credentials.
The bridge (desktop_bridge_v16) is mocked with exactly the 12 public functions
(the 11 of the first v16 spec plus save_input_template, follow-up spec 4.5).
"""
from copy import deepcopy
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import unittest

import v16_domain as domain
from tests.test_v16_domain import synthetic_notice, synthetic_result

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui_v16" / "index.html"
V15_UI = ROOT / "ui_v15"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CAPTURE = ROOT / ".dryforge" / "ui-v16-captures"
PROGRAM_NAME = "연구보안 등급분류 시뮬레이터"
BRIDGE_FUNCTIONS = ("get_initial_state", "select_path", "save_key", "delete_key", "start_single", "start_batch",
                    "get_job", "cancel_job", "start_export", "search_notice_clauses", "get_notice_clause",
                    "save_input_template")
# Follow-up spec 4.4/4.5: template download, shown name and the protected-path message.
TEMPLATE_BUTTON = "입력 양식 내려받기"
TEMPLATE_NAME = "v16_일괄검토_입력양식.xlsx"
PROTECTED_MESSAGE = "검토에 쓰는 파일 보호를 위해 저장 중단. 다른 파일 이름 선택 필요"
# Follow-up spec 4.6: composition options in order, footnote and summary names.
REVIEWER_OPTIONS = (("1", "AI 기술분야 전문가 1개"), ("3", "AI 분야별* 전문가 3개"))
REVIEWER_FOOTNOTE = "* AI 기술분야 · 연구보안 · 기술사업화 전문가"
REVIEWER_SUMMARIES = {"1": "AI 기술분야 전문가 1개", "3": "AI 분야별 전문가 3개"}
BATCH_GUIDANCE = "입력 엑셀은 기본 5개 항목 필수, 추가 4개 항목 선택. 과제명이 빈 행은 제외"
# Follow-up spec 4.2: CSS viewport × device scale factor (start windows and one maximized).
VIEWPORTS = (
    ("1920x1080-125-start", 1350, 754, 1.25),
    ("1920x1080-125-maximized", 1536, 790, 1.25),
    ("1920x1080-150-start", 1232, 617, 1.5),
    ("1366x768-125-start", 1044, 505, 1.25),
    ("1366x768-100-start", 1318, 649, 1.0),
)
# Per menu: the bottom button that must be reachable by vertical scrolling.
BOTTOM_BUTTONS = (
    ("연구개발과제 검토", "input", "start-single"),
    ("연구개발과제 일괄 검토", "batch", "start-batch"),
    ("검토 결과", "result", "start-export"),
    ("참고 고시", "notices", "notice-more"),
    ("모델·설정", "settings", "save-key"),
)
# Sidebar name, menus, buttons, summary labels and notice date lines.
WORD_TARGETS = (".brand, .nav button, #job-panel:not([hidden]) button, .screen:not([hidden]) button, "
                ".screen:not([hidden]) .metric > span:first-child, .screen:not([hidden]) .notice-list small, "
                ".screen:not([hidden]) .notice-card .metric")
# Each whitespace-separated word of each visible text node must sit on one line.
SPLIT_WORDS_JS = r"""
selector => {
 const split=[];
 for(const element of document.querySelectorAll(selector)){
  // Closed details content keeps layout boxes, so visibility is checked explicitly.
  const box=element.getBoundingClientRect();if(!box.width || !box.height || !element.checkVisibility())continue;
  const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);
  for(let text=walker.nextNode();text;text=walker.nextNode()){
   if(!text.parentElement.checkVisibility())continue;
   const pattern=/\S+/gu;let match;
   while((match=pattern.exec(text.data))){
    const range=document.createRange();range.setStart(text,match.index);range.setEnd(text,match.index+match[0].length);
    const rects=[...range.getClientRects()].filter(rect=>rect.width>0 && rect.height>0);if(!rects.length)continue;
    const middles=rects.map(rect=>(rect.top+rect.bottom)/2),height=Math.min(...rects.map(rect=>rect.height));
    if(Math.max(...middles)-Math.min(...middles)>height/2)split.push(`${match[0]} @ ${element.id || element.className || element.tagName}`);
   }
  }
 }
 return split;
}
"""
# The element is scrolled into view, lies inside the viewport and receives the hit.
REACH_JS = r"""
id => {
 const element=document.getElementById(id);if(!element || element.closest('[hidden]'))return 'missing';
 element.scrollIntoView({block:'center',inline:'nearest'});
 const box=element.getBoundingClientRect();if(!box.width || !box.height)return 'not rendered';
 if(box.top<0 || box.left<0 || box.bottom>innerHeight || box.right>document.documentElement.clientWidth)return 'outside '+JSON.stringify(box);
 const hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
 return hit && (hit===element || element.contains(hit)) ? 'ok' : 'covered by '+(hit ? hit.id || hit.className || hit.tagName : 'nothing');
}
"""
# After scrolling to the page end the sidebar still covers the whole viewport height.
SIDEBAR_JS = r"""
() => {
 window.scrollTo(0,document.documentElement.scrollHeight);
 const sidebar=document.querySelector('.sidebar'),box=sidebar.getBoundingClientRect();
 const hits=[1,innerHeight/2,innerHeight-1].map(y=>{const hit=document.elementFromPoint(4,y);return !!(hit && hit.closest('.sidebar'));});
 const style=getComputedStyle(sidebar);
 // Sidebar content never spills past its background: it fits or scrolls inside the sidebar.
 const contained=sidebar.scrollHeight<=sidebar.clientHeight || ['auto','scroll'].includes(style.overflowY);
 const result={top:box.top,bottom:box.bottom,height:innerHeight,hits,background:style.backgroundColor,contained};
 window.scrollTo(0,0);return result;
}
"""
MENUS = (
    ("01", "연구개발과제 검토", "input"),
    ("02", "연구개발과제 일괄 검토", "batch"),
    ("03", "검토 결과", "result"),
    ("04", "참고 고시", "notices"),
    ("05", "모델·설정", "settings"),
)
SLOGANS = ("좋은 판단은, 충분한 근거에서.", "여러 과제를, 하나의 기준으로.", "검토의 결론보다, 근거를 먼저.",
           "한 번 설정하고, 검토에 집중하세요.")
ENGLISH_LABELS = ("RESEARCH SECURITY", "WORKSPACE", "REVIEW WORKSPACE", "BATCH REVIEW", "REVIEW REPORT",
                  "MODEL & PREFERENCES")
NOTICE_NOTES = ("본문 전체는 공식 출처 참조(고정본은 대조에 쓰는 조항만 수록)", "검색 결과 없음은 비해당 판정 아님",
                "원문 보존과 자동 조건해석 지원 범위는 다름")
STYLE_ENDINGS = ("니다", "세요", "주세요", "해요", "어요", "아요", "에요", "예요", "까요")
STYLE_PATTERN = re.compile("(?:" + "|".join(STYLE_ENDINGS) + r")[)\]」』’”'\"]*(?=$|[\s.!?,…:;])")
GUIDELINE_SOURCE = "출처: 「국가연구개발혁신법」 및 같은 법 시행령(2026.8.20. 시행), 「연구보안 등급분류 가이드라인」 최종본."

# Spec 부록 A, copied into this test source character for character (never read from .dryforge).
APPENDIX_A_DEFINITIONS = [
    {"heading": "법 제21조제4항(보안과제)",
     "text": "④ 중앙행정기관의 장은 외부로 유출될 경우 기술적･재산적 가치에 상당한 손실이 예상되거나 국가안보를 위하여 별도로 높은 수준의 보안이 필요하다고 인정하는 연구개발과제를 보안과제로 분류할 수 있다."},
    {"heading": "법 제21조제5항(민감과제)",
     "text": "⑤ 중앙행정기관의 장은 제4항의 보안과제로 분류하지 아니하였으나 유출 시 국가에 미치는 영향을 고려하여 추가적인 관리가 필요하다고 인정하는 연구개발과제를 민감과제로 분류할 수 있다."},
    {"heading": "시행령 제45조제1항(보안과제 분류 기준)",
     "text": "① 중앙행정기관의 장은 법제21조제4항에 따라 다음 각 호의 연구개발과제를 보안과제로 분류할 수 있다.\n"
             "1. 「방위사업법」 제3조제1호에 따른 방위력개선사업과 관련된 연구개발과제\n"
             "2. 다음 각 목의 어느 하나에 해당하는 기술과 관련된 연구개발과제\n"
             "가. 외국에서 기술이전을 거부하여 국산화를 추진 중인 기술\n"
             "나. 중앙행정기관의 장이 보호의 필요성이 있다고 인정하는 미래핵심기술\n"
             "다. 「산업기술의 유출방지 및 보호에 관한 법률」 제2조제2호에 따른 국가핵심기술\n"
             "라. 「대외무역법」 제19조에 따른 수출허가 등 제한이 필요한 기술\n"
             "3. 그 밖에 중앙행정기관의 장이 보안과제로 분류할 필요가 있다고 인정하는 연구개발과제"},
    {"heading": "시행령 제45조제2항(민감과제 분류 기준)",
     "text": "② 중앙행정기관의 장은 법 제21조제5항에 따라 보안과제로 분류하지 않는 연구개발과제 중에서 다음 각 호의 사항을 종합적으로 고려하여 추가적인 관리가 필요하다고 인정하는 연구개발과제를 민감과제로 분류할 수 있다.\n"
             "1. 국가안보･외교 등을 위한 전략적 필요성\n"
             "2. 기술적･재산적 가치\n"
             "3. 그 밖에 연구개발과제의 수행 과정 및 결과의 유출 시 국가 전체에 미치는 영향의 정도"},
    {"heading": "일반과제(가이드라인)",
     "text": "보안과제 또는 민감과제에 해당하지 않으며, 통상적인 연구관리 및 기본 보안관리 조치 하에서 수행 가능한 연구개발과제"},
]
APPENDIX_A_PRINCIPLES = [
    {"title": "국가 차원의 보호 필요성에 비례한 종합적 판단",
     "details": ["보안등급 분류는 ‘참여자･특정주제･기술수준’ 등 단일 요건이 아닌 연구성과 유출 시 국가에 미치는 영향 수준을 종합적으로 고려",
                 "국가안보를 위해 법령에 따라 지정된 보안과제를 최우선 식별･분류하되 그 외 중앙행정기관의 기술보호･육성 지정 법령 준수"]},
    {"title": "협력적･전문적 의사결정",
     "details": ["보안등급 분류는 다양한 이해관계자의 전문성을 기반으로 한 집단적 의사결정 체계를 기반으로 실시",
                 "보안등급분류위원회의 심의･의결을 통해 투명성･객관성･책임성 확보",
                 "전문 기술판정 필요 시 관계 기관에 문의",
                 "※ 예시: 전략물자(무역안보관리원･한국원자력통제기술원･방위사업청),국가핵심기술 및 첨단전략기술(산업기술기획평가원 기술안보센터)",
                 "연구개발기관이 보안등급 의견을 제시하도록 하여 현장 전문성 반영(붙임2 자가점검서 양식 참고)",
                 "국가정보원･과학기술정보통신부 및 관계 중앙행정기관은 관련 정보를 공유하고 역할을 분담하여 공동책임 기반의 보안관리 체계 구축"]},
    {"title": "예측 가능성 및 절차적 안정성 원칙",
     "details": ["R&D 기획･공고･협약단계에서 보안등급을 분류하거나 안내하여 예측 가능성을 높이되 상황에 따라 전 주기상 보안등급 지정･변경 추진",
                 "대외환경 변화 또는 연구 성격･활용계획 변경 등으로 보안등급 변경이 필요한 경우 이해관계자 간 사전 협의를 거쳐 다시 분류 여부 검토"]},
    {"title": "과제 단위 분류",
     "details": ["연구개발과제의 특성(목표･성과활용 계획)을 고려한 과제 단위 분류",
                 "주관･공동･위탁연구개발기관이 수행하는 연구개발과제의 보안등급은 주관 연구개발기관의 연구개발과제를 기준으로 일괄 지정하기보다, 각 연구개발기관의 연구수행 범위와 성과 활용계획 등을 고려하여 개별적으로 지정할 것을 권고",
                 "국가 전략적 중요도가 높거나 보안 민감성이 큰 사업군의 경우 중앙행정기관의 판단에 따라 사업 단위 보안등급 분류도 검토 가능"]},
]


def catalogue_notices(sources):
    """Spec 4.6 catalogue.notices: first-appearance order, family union, '-body' URL."""
    notices = {}
    for source in sources:
        entry = notices.setdefault(source["notice_number"], {
            "notice_number": source["notice_number"], "title": domain.NOTICE_TITLES[source["notice_number"]],
            "announcement_date": source["announcement_date"], "effective_date": source["effective_date"],
            "families": [], "source_ids": [], "official_url": None})
        entry["families"].extend(f for f in source["families"] if f not in entry["families"])
        entry["source_ids"].append(source["source_id"])
        if source["source_id"].endswith(domain.BODY_SOURCE_SUFFIX):
            entry["official_url"] = source["official_url"]
    return list(notices.values())


# Installed synthetic catalogue: real notice numbers, one '-body' source per notice, ISO dates.
CATALOGUE_ID = "synthetic-catalogue-v16"
CATALOGUE_FINGERPRINT = "a" * 64
INSTALLED_SOURCES = deepcopy(synthetic_notice()["catalogue_manifest"]["sources"])
for _source in INSTALLED_SOURCES:
    _source.update(official_url="https://example.gov.test/" + _source["source_id"],
                   title="합성 출처 " + _source["source_id"], retrieved_at="2026-10-21T09:00:00Z")
FAMILY_COUNTS = [{"family": f, "total_clauses": 17 + i, "interpreted_clauses": 4 + i, "unsupported_clauses": 13}
                 for i, f in enumerate(domain.FAMILIES)]

# Exact public get_initial_state shape (spec 4.6). Counts are synthetic metadata.
# No key value is returned. Single result is the schema-3 DTO root; batch is
# {results,counts?,paths?,warnings?,persistence?}. Export returns a new job_id;
# that job's result is the updated same DTO root, never a renderer-supplied DTO.
INITIAL = {
    "defaults": domain.normalize_options().to_dict(),
    "criteria": [dict(c) | {"rubric": dict(c["rubric"])} for c in domain.CRITERIA],
    "credential_status": {"claude": False, "openai": True},
    "catalogue": {"catalogue_id": CATALOGUE_ID, "fingerprint": CATALOGUE_FINGERPRINT,
                  "status": "ready", "sources": INSTALLED_SOURCES, "families": FAMILY_COUNTS,
                  "notices": catalogue_notices(INSTALLED_SOURCES), "notice_titles": dict(domain.NOTICE_TITLES)},
    "guideline": domain.guideline_display(),
}


def synthetic_clauses():
    """120 synthetic clauses; text is returned only by get_notice_clause."""
    source_of = {source["families"][0]: source for source in INSTALLED_SOURCES}
    counts = {"advanced": 30, "core": 25, "dual_use": 45, "military": 20}
    clauses = []
    for family, count in counts.items():
        source = source_of[family]
        for index in range(1, count + 1):
            clauses.append({"clause_id": f"{family}:{index}", "family": family, "source_id": source["source_id"],
                            "notice_number": source["notice_number"], "code": f"SYN-{family[:2].upper()}-{index:03d}",
                            "title": f"합성 {family} 조항 {index}", "field": "합성 분야",
                            "source_anchor": f"합성 별표 {index}", "text": f"합성 원문 {family} {index}"})
    by_id = {clause["clause_id"]: clause for clause in clauses}
    by_id["advanced:1"].update(title="기\n\n 술 합성 조항")
    by_id["advanced:2"].update(title="합성 장문 조항", text="가나다라마바사아자차카타파하" * 5200 + "끝")
    by_id["core:1"].update(title="악성 태그 합성 조항",
                           text='<script>window.injected=1</script><img src=x onerror="window.injected=2">합성 원문 끝')
    by_id["dual_use:1"].update(code="1A001", text="합성 이중용도 원문 낱말 초정밀가공 장치")
    return clauses


CLAUSES = synthetic_clauses()
RESULT, _ = synthetic_result(count=3)
RESULT = deepcopy(RESULT)
RESULT["rationale"] = '<script>window.injected=1</script><img src=x onerror="window.injected=2">' + "긴 한글 근거 " * 600
RESULT["notice_review"]["comparisons"][0]["conditions"][0]["reason"] = '<svg onload="window.injected=3">합성 비교 근거</svg>'
RESULT["documents"].update(status="일부실패", files=[
    {"kind": "reviewer", "reviewer_id": "reviewer-1", "path": "C:/synthetic/의견서.hwpx", "status": "완료", "error": ""},
    {"kind": "summary", "reviewer_id": None, "path": "C:/synthetic/종합.hwpx", "status": "오류", "error": "합성 파일 잠금"},
], errors=["합성 파일 잠금"])


def evidence_result(*, bases=False, statuses=None, target="none", candidates=1, long=False):
    """Validated schema-3 variants, including real enum and question shapes."""
    result, _ = synthetic_result(count=3)
    notice = result["notice_review"]
    snapshot = result["task_snapshot"]
    clause = notice["clause_snapshots"][0]
    comparison = notice["comparisons"][0]
    manifest = notice["catalogue_manifest"]
    notice["sources"] = deepcopy(manifest["sources"])
    inventory = manifest["clause_inventory"]
    if bases:
        snapshot["추가 검토정보"] = "속도 20 GHz"
        snapshot["개발목표 사양"] = "속도 30 GHz"
        for identity, basis, field, value in (
            ("fact-both", "both", "추가 검토정보", "20"),
            ("fact-unspecified", "unspecified", "추가 검토정보", "20"),
            ("fact-target", "target", "개발목표 사양", "30"),
        ):
            quote = snapshot[field]
            notice["facts"].append({"fact_id": identity, "basis": basis, "subject": "속도",
                "value_text": value + " GHz", "number": value, "unit": "GHz", "source_field": field,
                "start": 0, "end": len(quote), "quote": quote})
        comparison["conditions"][0]["fact_ids"] = ["fact-both"]
        comparison["conditions"][1].update(fact_ids=["fact-target"], assessment="satisfied",
            normalized_value="30", normalized_unit="GHz", reason="합성 목표 속도 충족")
        comparison["target_assessment"] = "satisfied"
    elif target != "none":
        snapshot["개발목표 사양"] = "속도 30 GHz"
        quote = snapshot["개발목표 사양"]
        notice["facts"].append({"fact_id": "fact-target", "basis": "target", "subject": "속도",
            "value_text": "30 GHz", "number": "30", "unit": "GHz", "source_field": "개발목표 사양",
            "start": 0, "end": len(quote), "quote": quote})
        comparison["conditions"][1].update(fact_ids=["fact-target"], assessment="satisfied",
            normalized_value="30", normalized_unit="GHz", reason="합성 목표 속도 충족")
        comparison["target_assessment"] = "satisfied"
        if target == "partial":
            predicate = {"type": "qualitative", "predicate_id": "usage", "text": "합성 적용 용도 조건",
                         "source_anchor": "합성 제1항 용도", "subject": "용도", "reason": "합성 용도 확인 필요"}
            clause["condition"] = {"type": "all", "children": [clause["condition"], predicate]}
            comparison["current_assessment"] = comparison["target_assessment"] = "insufficient_info"
            for basis in ("current", "target"):
                comparison["conditions"].append({"predicate_id": "usage", "basis": basis,
                    "condition_text": predicate["text"], "fact_ids": [], "normalized_value": None,
                    "normalized_unit": None, "assessment": "insufficient_info", "reason": "합성 용도 미확인",
                    "source_anchor": predicate["source_anchor"]})
                comparison["missing_information"].append({"basis": basis, "predicate_id": "usage",
                    "question": "합성 적용 용도와 예외 조건을 확인해 주세요."})
            notice.update(status="needs_info", blocking_reasons=["합성 용도 추가 확인"])
            result.update(status="검토필요", final_grade=None, unresolved_reasons=["합성 용도 추가 확인"])
    if long:
        clause["text"] += "\n" + "고시 원문 장문을 생략하지 않고 보존하는 합성 설명입니다. " * 80
        snapshot["현재 기술사양"] = (snapshot["현재 기술사양"] + "\n" + "확인한 기술사양의 상세 인용문을 보존합니다. " * 80).strip()
        fact = notice["facts"][0]
        fact.update(quote=snapshot["현재 기술사양"], end=len(snapshot["현재 기술사양"]))
        # Four original sources plus five more versions, all metadata retained.
        for index in range(5):
            source = deepcopy(notice["sources"][0])
            source.update(source_id=f"synthetic-extra-{index}", title=f"합성 추가 원문 {index}",
                          relative_path=f"extra-{index}.txt")
            notice["sources"].append(source)
            manifest["sources"].append(deepcopy(source))
            manifest["files"].append({"relative_path": source["relative_path"], "sha256": source["sha256"]})
        for index in range(64):
            reference = deepcopy(clause)
            identity = f"advanced:note-{index + 1}"
            reference.update(clause_id=identity, title=f"합성 연결 주석 {index + 1}",
                             text=f"합성 주석 {index + 1} 전문 " + "연결된 참조조항도 끝까지 보존합니다. " * 40,
                             qualifier_refs=[])
            notice["clause_snapshots"].append(reference)
            inventory.append({"clause_id": identity, "family": "advanced", "sha256": domain.canonical_hash(reference)})
            clause["qualifier_refs"].append(identity)
            notice["families"][0]["screened_ids"].append(identity)
            notice["families"][0]["excluded"].append({"clause_id": identity, "reason": "독립 후보 제외 · 연결 주석으로 검토"})
        # Exactly 571 exclusions in the core family, including its existing one.
        for index in range(570):
            identity = f"core:excluded-{index + 1}"
            inventory.append({"clause_id": identity, "family": "core", "sha256": "1" * 64})
            notice["families"][1]["screened_ids"].append(identity)
            notice["families"][1]["excluded"].append({"clause_id": identity, "reason": f"합성 제외 상세 근거 {index + 1}"})
    for index in range(1, candidates):
        another = deepcopy(clause)
        identity = f"advanced:candidate-{index + 1}"
        another.update(clause_id=identity, title=f"합성 추가 후보 {index + 1}")
        notice["clause_snapshots"].append(another)
        inventory.append({"clause_id": identity, "family": "advanced", "sha256": domain.canonical_hash(another)})
        notice["families"][0]["screened_ids"].append(identity)
        notice["families"][0]["candidate_ids"].append(identity)
        another_comparison = deepcopy(comparison)
        another_comparison["clause_id"] = identity
        notice["comparisons"].append(another_comparison)
    if statuses:
        for family in notice["families"]:
            family["status"] = statuses.get(family["family"], "complete")
            if family["status"] in ("not_run", "error") or family["status"] == "partial" and not family["candidate_ids"]:
                family.update(screened_ids=[], excluded=[], candidate_ids=[])
            if family["status"] == "error":
                family["errors"] = ["합성 탐색 중단"]
        has_error = "error" in statuses.values()
        notice.update(status="error" if has_error else "needs_info", blocking_reasons=["합성 탐색 미완료"])
        result.update(status="오류" if has_error else "검토필요", final_grade=None,
                      unresolved_reasons=["합성 탐색 미완료"])
    inventory[0]["sha256"] = domain.canonical_hash(clause)
    fingerprint = domain.canonical_hash(manifest)
    notice["catalogue_fingerprint"] = result["catalogue_fingerprint"] = fingerprint
    result["task_fingerprint"] = domain.task_fingerprint(snapshot)
    result["options_fingerprint"] = domain.options_fingerprint(domain.normalize_options({"num_reviewers": 3,
        "catalogue_fingerprint": fingerprint}))
    for comp in notice["comparisons"]:
        comp["comparison_id"] = domain.comparison_id(fingerprint, comp["clause_id"])
    for index, item in enumerate(result["criteria"], 1):
        links = [{"comparison_id": comp["comparison_id"], "source_id": comp["source_id"]}
                 for comp in notice["comparisons"] if index in comp["affected_items"]]
        item["matched_reference"] = json.dumps(links) if links else ""
    for reviewer in result["reviewers"]:
        reviewer["notice_comments"] = [{"comparison_id": comp["comparison_id"], "comment": "합성 개별 대조 의견"}
                                      for comp in notice["comparisons"]]
    domain.validate_result(result)
    return result


FAKE = r"""
(() => {
 const ok = data => ({ok:true,data,error:null});
 const bad = (code,message) => ({ok:false,data:null,error:{code,message}});
 const calls = []; let next = 0; const jobs = {}; const deferred = [];
 const h = window.testHarness = {calls,jobs,deferred,mode:'normal',failNext:null, cancelledPicker:false,result:RESULT,templateMode:'normal'};
 const busyError = () => bad('busy','진행 중인 작업 있음. 완료 또는 취소 후 다시 시작');
 const record = (name,args) => {calls.push({name,args}); if(h.failNext===name){h.failNext=null;return busyError();} return null;};
 const invalid = () => bad('validation','입력 또는 실행 설정 확인 후 다시 시도');
 // Spec 4.5: purpose-bound tokens; an unknown purpose is a validation error.
 const purposes = ['input_excel','output_excel','output_directory','input_template'];
 const TEMPLATE_NAME = 'v16_일괄검토_입력양식.xlsx';
 const PROTECTED = '검토에 쓰는 파일 보호를 위해 저장 중단. 다른 파일 이름 선택 필요';
 const running = () => Object.values(jobs).some(job=>!job.cancelled && !job.done);
 const families = ['advanced','core','dual_use','military'];
 const integer = value => typeof value==='number' && Number.isInteger(value);
 const normal = value => String(value).normalize('NFKC').replace(/\s/gu,'').toLowerCase();
 const sources = Object.fromEntries(INITIAL.catalogue.sources.map(source=>[source.source_id,source]));
 window.pywebview = {api:{
  get_initial_state:async()=>{record('get_initial_state',[]);return ok(INITIAL);},
  select_path:async purpose=>{record('select_path',[purpose]);if(!purposes.includes(purpose))return invalid();return ok(h.cancelledPicker?{cancelled:true,path_token:null,display_name:null}:{cancelled:false,path_token:'token-'+purpose,display_name:purpose==='input_template'?TEMPLATE_NAME:'합성 '+purpose});},
  save_key:async(provider,key)=>{const fail=record('save_key',[provider,key]);if(fail)return fail;return ok({provider,stored:true});},
  delete_key:async provider=>{const fail=record('delete_key',[provider]);if(fail)return fail;return ok({provider,stored:false});},
  start_single:async payload=>{const fail=record('start_single',[payload]);if(fail)return fail;const job_id='job-'+(++next);jobs[job_id]={type:'single',polls:0};return ok({job_id});},
  start_batch:async payload=>{const fail=record('start_batch',[payload]);if(fail)return fail;const job_id='job-'+(++next);jobs[job_id]={type:'batch',polls:0};return ok({job_id});},
  start_export:async payload=>{const fail=record('start_export',[payload]);if(fail)return fail;const job_id='job-'+(++next);jobs[job_id]={type:'export',polls:0};return ok({job_id});},
  get_job:async(job_id,after_sequence)=>{
   record('get_job',[job_id,after_sequence]);const job=jobs[job_id];job.polls++;
   if(h.mode==='deferred'){return await new Promise(resolve=>deferred.push(()=>resolve(ok({job_id,state:'done',events:[{sequence:99,stage:'summary',message:'이전 작업 지연 응답',completed:1,total:1}],result:{...RESULT,task_name:'이전 작업 지연 결과'}}))));}
   if(job.cancelled)return ok({job_id,state:'cancelled',events:[],result:null});
   if(h.mode==='hold')return ok({job_id,state:'running',events:[{sequence:job.polls,stage:'notices',message:'합성 고시 대조 진행',completed:1,total:4}],result:null});
   if(h.mode==='failed'){job.done=true;return ok({job_id,state:'failed',events:[{sequence:1,stage:'preflight',message:'합성 기준 로드 오류',completed:0,total:1}],result:null});}
   if(job.polls===1)return ok({job_id,state:'running',events:[{sequence:1,stage:'facts',message:'합성 사실 확인',completed:1,total:4}],result:null});
   const base=h.result;
   const exported={...base,documents:{...base.documents,status:'완료',errors:[],files:base.documents.files.map(f=>({...f,status:'완료',error:''}))}};
   const result=job.type==='batch'?{results:[base],counts:{total:1,completed:1,failed:0,cancelled:0,needs_review:0,excluded:0},paths:{output_excel:'C:/synthetic/결과.xlsx'},warnings:['합성 감사 일부 실패'],persistence:{status:'일부실패',checkpoint:'완료',workbook:'완료',audit:'오류'}}:job.type==='export'?exported:base;
   job.done=true;
   return ok({job_id,state:'done',events:[{sequence:2,stage:'documents',message:'합성 의견서 처리',completed:4,total:4}],result});
  },
  cancel_job:async job_id=>{record('cancel_job',[job_id]);jobs[job_id].cancelled=true;return ok({job_id,state:'cancelled'});},
  search_notice_clauses:async request=>{
   const fail=record('search_notice_clauses',[request]);if(fail)return fail;
   if(!request || typeof request!=='object' || Array.isArray(request))return invalid();
   if(Object.keys(request).some(key=>!['query','family','offset','limit'].includes(key)))return invalid();
   const query=request.query===undefined?'':request.query,family=request.family===undefined?null:request.family;
   const offset=request.offset===undefined?0:request.offset,limit=request.limit===undefined?50:request.limit;
   if(typeof query!=='string' || query.length>200 || (family!==null && !families.includes(family)) || !integer(offset) || offset<0 || !integer(limit) || limit<1 || limit>100)return invalid();
   const needle=normal(query);
   const matched=CLAUSES.filter(clause=>(family===null || clause.family===family) && (!needle || ['clause_id','code','title','field','text'].some(key=>normal(clause[key]).includes(needle))));
   return ok({total:matched.length,offset,limit,items:matched.slice(offset,offset+limit).map(clause=>({clause_id:clause.clause_id,family:clause.family,source_id:clause.source_id,notice_number:clause.notice_number,code:clause.code,title:clause.title,field:clause.field}))});
  },
  get_notice_clause:async clause_id=>{
   const fail=record('get_notice_clause',[clause_id]);if(fail)return fail;
   if(typeof clause_id!=='string')return invalid();
   const clause=CLAUSES.find(item=>item.clause_id===clause_id);if(!clause)return bad('not_found','조항 없음');
   const source=sources[clause.source_id];
   return ok({clause_id:clause.clause_id,family:clause.family,source_id:clause.source_id,notice_number:clause.notice_number,notice_title:INITIAL.catalogue.notice_titles[clause.notice_number],announcement_date:source.announcement_date,effective_date:source.effective_date,official_url:source.official_url,code:clause.code,title:clause.title,field:clause.field,source_anchor:clause.source_anchor,text:clause.text});
  },
  // Spec 4.5: only an input_template token; busy while a job runs; protected path
  // is a validation error with its own fixed message; success {saved,display_name}.
  save_input_template:async request=>{
   const fail=record('save_input_template',[request]);if(fail)return fail;
   if(!request || typeof request!=='object' || Array.isArray(request) || Object.keys(request).join()!=='output_token' || request.output_token!=='token-input_template')return invalid();
   if(running())return busyError();
   if(h.templateMode==='protected')return bad('validation',PROTECTED);
   if(h.templateMode==='io')return bad('io','파일 처리 실패. 저장 위치·권한과 열린 파일 확인 후 다시 시도');
   return ok({saved:true,display_name:TEMPLATE_NAME});
  }
 }};
})();
"""


class _VisibleText(HTMLParser):
    """Visible text plus placeholder/aria-label/title attributes of a static page."""

    def __init__(self):
        super().__init__()
        self.texts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if name in ("placeholder", "aria-label", "title") and value:
                self.texts.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.texts.append(data.strip())


def visible_html_texts(html):
    parser = _VisibleText()
    parser.feed(html)
    return parser.texts


def js_string_literals(source):
    """Every string/template literal (static parts) of a script, comments skipped."""
    found, index, size = [], 0, len(source)
    while index < size:
        char = source[index]
        if source.startswith("//", index):
            end = source.find("\n", index)
            index = size if end < 0 else end
            continue
        if source.startswith("/*", index):
            index = source.index("*/", index) + 2
            continue
        if char in "'\"`":
            cursor, parts = index + 1, []
            while cursor < size and source[cursor] != char:
                if source[cursor] == "\\":
                    parts.append(source[cursor:cursor + 2])
                    cursor += 2
                    continue
                if char == "`" and source.startswith("${", cursor):
                    depth, start = 1, cursor + 2
                    cursor = start
                    while depth:
                        depth += {"{": 1, "}": -1}.get(source[cursor], 0)
                        cursor += 1
                    found.extend(js_string_literals(source[start:cursor - 1]))
                    parts.append("\0")
                    continue
                parts.append(source[cursor])
                cursor += 1
            found.append("".join(parts))
            index = cursor + 1
            continue
        index += 1
    return found


def style_violations(texts):
    return [text for text in texts if re.search("[가-힣]", text) and STYLE_PATTERN.search(text)]


class FrontendStaticTests(unittest.TestCase):
    def test_offline_assets_and_safe_renderer(self):
        self.assertTrue(PAGE.exists(), "v16 entry page must exist")
        html = PAGE.read_text(encoding="utf-8")
        script = PAGE.with_name("app.js").read_text(encoding="utf-8")
        css = PAGE.with_name("styles.css").read_text(encoding="utf-8")
        self.assertNotRegex(html, r'(?:src|href)=["\']https?://')
        self.assertNotRegex(css, r'url\(\s*["\']?https?:|@import')
        self.assertNotRegex(script, r'\.innerHTML\s*=|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function|localStorage|sessionStorage|indexedDB|fetch\(|XMLHttpRequest|window\.open')
        self.assertNotRegex(html, r'(?i)strictness|엄격|관대')
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'none'", html)
        font = PAGE.parent / "assets" / "PretendardVariable.woff2"
        self.assertEqual(hashlib.sha256(font.read_bytes()).hexdigest(), "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4")
        self.assertTrue((font.parent / "Pretendard-LICENSE.txt").is_file())

    def test_assets_are_byte_copies_of_v15(self):
        v15_assets = sorted(p.name for p in (V15_UI / "assets").iterdir())
        v16_assets = sorted(p.name for p in (PAGE.parent / "assets").iterdir())
        self.assertEqual(v16_assets, v15_assets)
        for name in v15_assets:
            with self.subTest(asset=name):
                self.assertEqual((PAGE.parent / "assets" / name).read_bytes(), (V15_UI / "assets" / name).read_bytes())

    def test_single_name_no_english_labels_mark_or_slogans(self):
        html = PAGE.read_text(encoding="utf-8")
        script = PAGE.with_name("app.js").read_text(encoding="utf-8")
        self.assertIn(f"<title>{PROGRAM_NAME} · v16</title>", html)
        texts = visible_html_texts(html) + js_string_literals(script)
        joined = "\n".join(texts)
        for forbidden in ("研", "연구보안 검토실") + ENGLISH_LABELS + SLOGANS:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html)
                self.assertNotIn(forbidden, joined)
        # No upper-case English section label of any wording on screen.
        self.assertEqual(re.findall(r"\b[A-Z]{5,}\b", joined), [])
        self.assertNotRegex(html, r'class="(?:eyebrow|section-label|mark)"')

    def test_style_check_detects_sentence_endings(self):
        for bad in ("확인하세요.", "다시 시도해 주세요", "저장했습니다.", "있어요", "괜찮아요?", "필요해요", "무엇일까요?",
                    "보존합니다. 다음 문장", "아니에요", "예요"):
            with self.subTest(bad=bad):
                self.assertEqual(style_violations([bad]), [bad])
        for good in ("확인 필요", "작업 진행 중", "검색 결과 없음", "저장 완료", "입력 또는 실행 설정 확인 후 다시 시도",
                     "필요", "보안등급(AI 참고)", "합성 ‘후보 없음(자동 탐색)’은 공식 비해당 판정 아님"):
            with self.subTest(good=good):
                self.assertEqual(style_violations([good]), [])

    def test_screen_text_uses_noun_ending_style(self):
        html = PAGE.read_text(encoding="utf-8")
        script = PAGE.with_name("app.js").read_text(encoding="utf-8")
        html_texts = visible_html_texts(html)
        script_texts = [text for text in js_string_literals(script) if re.search("[가-힣]", text)]
        self.assertGreater(len(html_texts), 80)
        self.assertGreater(len(script_texts), 150)
        self.assertEqual(style_violations(html_texts), [])
        self.assertEqual(style_violations(script_texts), [])

    def test_term_mapping_on_screen_only(self):
        html = PAGE.read_text(encoding="utf-8")
        script = PAGE.with_name("app.js").read_text(encoding="utf-8")
        texts = "\n".join(visible_html_texts(html) + js_string_literals(script))
        for old in ("공통 검토항목", "공통항목", "논의할 사항", "종합 근거", "참고 등급", "자동 선택", "직접 선택"):
            with self.subTest(old=old):
                self.assertNotIn(old, texts)
        for new in ("검토항목", "법적 정의·기준 체크리스트", "국가영향 수준 지표", "영향수준 점수", "검토항목 자동·직접 선정",
                    "보안등급(AI 참고)", "등급분류 대상", "대상 제외", "중점 논의사항", "종합 의견", "후보 조항", "AI 에이전트"):
            with self.subTest(new=new):
                self.assertIn(new, texts)

    def test_korean_word_break_rules(self):
        # Follow-up spec 4.2: keep-all for the whole screen, anywhere for long strings, never break-word.
        css = PAGE.with_name("styles.css").read_text(encoding="utf-8")
        compact = re.sub(r"\s+", "", css)
        self.assertRegex(compact, r"(?:^|[};])(?:html|body)[^{}]*\{[^}]*word-break:keep-all")
        self.assertIn("overflow-wrap:anywhere", compact)
        self.assertNotIn("break-word", compact)

    def test_mock_initial_state_matches_spec_shapes(self):
        guideline = INITIAL["guideline"]
        self.assertEqual(set(guideline), {"id", "definitions", "principles"})
        self.assertEqual(guideline["definitions"], APPENDIX_A_DEFINITIONS)
        self.assertEqual(guideline["principles"], APPENDIX_A_PRINCIPLES)
        notices = INITIAL["catalogue"]["notices"]
        self.assertEqual([n["notice_number"] for n in notices], list(domain.NOTICE_TITLES))
        for notice in notices:
            self.assertEqual(set(notice), {"notice_number", "title", "announcement_date", "effective_date", "families",
                                           "source_ids", "official_url"})
            self.assertTrue(notice["official_url"].endswith("-body"))
        self.assertEqual(notices[2]["families"], ["dual_use", "military"])
        self.assertTrue(all("announcement_date" in source for source in INITIAL["catalogue"]["sources"]))
        self.assertEqual(RESULT["schema_version"], domain.SCHEMA_VERSION)


class FrontendBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(EDGE), headless=True,
                                                     args=["--disable-background-networking", "--no-first-run"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1366, "height": 768}, reduced_motion="reduce")
        self.external_requests = []
        self.context.route("**/*", self.route_request)
        self.page = self.context.new_page()
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.page.add_init_script("const INITIAL=" + json.dumps(INITIAL, ensure_ascii=False) + ";const RESULT="
                                  + json.dumps(RESULT, ensure_ascii=False) + ";const CLAUSES="
                                  + json.dumps(CLAUSES, ensure_ascii=False) + ";" + FAKE)
        self.page.goto(PAGE.as_uri())
        self.page.wait_for_selector('[data-ready="true"]')

    def route_request(self, route):
        if route.request.url.startswith(("file:", "data:")):
            route.continue_()
        else:
            self.external_requests.append(route.request.url)
            route.abort()

    def tearDown(self):
        self.assertEqual(self.external_requests, [])
        self.assertEqual(self.page_errors, [])
        self.context.close()

    def menu(self, name):
        self.page.get_by_role("navigation", name="주요 메뉴").get_by_role("button", name=name, exact=True).click()

    def calls(self, name):
        return self.page.evaluate("name=>testHarness.calls.filter(c=>c.name===name)", name)

    def start(self):
        self.page.get_by_label("과제명", exact=True).fill("오프라인 합성 과제")
        self.page.get_by_role("button", name="AI 에이전트 검토 시작", exact=True).click()

    def wait_result(self):
        self.page.wait_for_function("() => document.querySelector('#result-heading')?.textContent.includes('합성 과제')")

    def show_evidence(self, result):
        self.page.evaluate("result => {testHarness.result=result;}", result)
        self.menu("연구개발과제 검토")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='완료' && !document.querySelector('#start-single').disabled")
        self.wait_result()
        self.page.get_by_role("button", name="고시 대조 근거", exact=True).click()

    def assert_only_in_closed_details(self, scope, text):
        """Every element holding ``text`` sits inside a collapsed details element."""
        holders = self.page.locator(scope).get_by_text(text, exact=False)
        self.assertGreater(holders.count(), 0, text)
        for index in range(holders.count()):
            holder = holders.nth(index)
            self.assertTrue(holder.evaluate("el=>!!el.closest('details:not([open])')"), text)
            self.assertFalse(holder.is_visible(), text)

    def open_notices(self):
        self.menu("참고 고시")
        self.page.wait_for_function("() => document.querySelectorAll('#notice-results details').length>0")

    def search(self, query, family=""):
        before = len(self.calls("search_notice_clauses"))
        self.page.get_by_label("조항 검색어", exact=True).fill(query)
        self.page.get_by_label("고시 범위", exact=True).select_option(family)
        self.page.get_by_role("button", name="검색", exact=True).click()
        self.page.wait_for_function("n => testHarness.calls.filter(c=>c.name==='search_notice_clauses').length>n", arg=before)
        self.page.wait_for_function("() => !document.querySelector('#notice-summary').textContent.includes('검색 중')")

    def test_navigation_preserves_input_and_all_nine_fields(self):
        for label in domain.TASK_COLUMNS + domain.OPTIONAL_TASK_COLUMNS:
            self.page.get_by_label(label, exact=True).fill("합성 " + label)
        self.menu("연구개발과제 일괄 검토")
        self.assertTrue(self.page.get_by_role("heading", name="연구개발과제 일괄 검토").is_visible())
        self.menu("모델·설정")
        self.assertIn("17", self.page.locator("#catalogue-info").inner_text())
        self.assertIn("자동 조건해석", self.page.locator("#catalogue-info").inner_text())
        self.menu("검토 결과")
        self.assertTrue(self.page.get_by_text("완료된 검토 없음", exact=True).is_visible())
        self.menu("참고 고시")
        self.menu("연구개발과제 검토")
        for label in domain.TASK_COLUMNS + domain.OPTIONAL_TASK_COLUMNS:
            self.assertEqual(self.page.get_by_label(label, exact=True).input_value(), "합성 " + label)
        self.assertEqual(self.page.locator('[name="strictness"]').count(), 0)

    def test_modes_auto_payload_and_manual_validation(self):
        self.page.get_by_role("button", name="직접 선정", exact=True).click()
        self.start()
        self.assertEqual(self.calls("start_single"), [])
        self.assertIn("하나 이상", self.page.locator("#message").inner_text())
        self.page.get_by_label("1 군사·안보 활용성", exact=True).check()
        self.page.get_by_label("군사·안보 활용성 가중치", exact=True).fill("1.2")
        self.page.get_by_role("button", name="AI 에이전트 검토 시작", exact=True).click()
        self.assertEqual(self.calls("start_single"), [])
        self.assertIn("평균", self.page.locator("#message").inner_text())
        self.page.get_by_label("군사·안보 활용성 가중치", exact=True).fill("bogus")
        self.page.get_by_role("button", name="자동 선정", exact=True).click()
        self.assertIn("검토항목 자동 선정 시 선정된 모든 항목의 가중치 1.0 적용", self.page.locator("#weight-guidance").inner_text())
        self.assertTrue(self.page.get_by_label("군사·안보 활용성 가중치", exact=True).is_disabled())
        self.start()
        self.wait_result()
        options = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual(options["selected_items"], [])
        self.assertEqual(options["weights"], {})
        self.assertNotIn("strictness", options)

    def test_checklist_and_conditional_item_eight(self):
        self.page.get_by_role("button", name="법적 정의·기준 체크리스트", exact=True).click()
        self.page.get_by_role("button", name="직접 선정", exact=True).click()
        item = self.page.get_by_label("8 부처 정책상 관리 필요성", exact=True)
        self.assertTrue(item.is_disabled())
        self.page.get_by_label("부처 세부기준", exact=True).fill("합성 과제별 정책")
        self.assertFalse(item.is_disabled())
        item.check()
        self.assertIn("법적 정의·기준 체크리스트 방식은 영향수준 점수·가중치 미사용", self.page.locator("#weight-guidance").inner_text())
        self.assertTrue(self.page.get_by_label("부처 정책상 관리 필요성 가중치", exact=True).is_disabled())
        self.start()
        self.wait_result()
        options = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual(options["method"], "checklist")
        self.assertEqual(options["selected_items"], [domain.ITEM_NAMES[7]])
        self.assertEqual(options["weights"], {})

    def test_provider_keys_clear_and_local_destination(self):
        self.menu("모델·설정")
        key = self.page.get_by_label("새 API 키", exact=True)
        key.fill("synthetic-secret-never-return")
        self.page.get_by_role("button", name="키 저장", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#api-key').value===''")
        self.assertEqual(self.calls("save_key")[0]["args"], ["claude", "synthetic-secret-never-return"])
        self.assertNotIn("synthetic-secret-never-return", self.page.locator("body").inner_text())
        self.assertNotIn("synthetic-secret-never-return", self.page.content())
        key.fill("synthetic-unsaved")
        self.page.get_by_label("모델 제공자", exact=True).select_option("openai")
        self.assertEqual(key.input_value(), "")
        self.assertIn("저장됨", self.page.locator("#key-status").inner_text())
        self.page.get_by_role("button", name="저장 키 삭제", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#key-status').textContent.includes('저장되지 않음')")
        self.page.get_by_label("모델 제공자", exact=True).select_option("ollama")
        self.page.get_by_label("로컬 서버 주소", exact=True).fill("http://127.0.0.1:11434")
        self.page.get_by_label("로컬 모델 식별자", exact=True).fill("synthetic-local-model")
        self.menu("연구개발과제 검토")
        self.start()
        self.wait_result()
        opts = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual((opts["provider"], opts["model"], opts["local_base_url"]), ("ollama", "synthetic-local-model", "http://127.0.0.1:11434"))
        self.assertEqual(self.page.evaluate("JSON.stringify(Object.keys(localStorage))+JSON.stringify(Object.keys(sessionStorage))"), "[][]")

    def test_job_progress_freeze_cancel_and_busy_error(self):
        self.page.evaluate("testHarness.failNext='start_single'")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#message').textContent.includes('진행 중')")
        self.page.evaluate("testHarness.mode='hold'")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-status').textContent.includes('고시 대조')")
        self.assertTrue(self.page.get_by_role("button", name="법적 정의·기준 체크리스트", exact=True).is_disabled())
        self.menu("모델·설정")
        self.assertTrue(self.page.get_by_label("모델 제공자", exact=True).is_disabled())
        self.menu("연구개발과제 일괄 검토")
        self.assertTrue(self.page.get_by_role("button", name="일괄 검토 시작", exact=True).is_disabled())
        self.page.get_by_role("button", name="작업 취소", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='취소'")
        self.assertEqual(len(self.calls("cancel_job")), 1)
        self.menu("연구개발과제 검토")
        self.assertFalse(self.page.get_by_role("button", name="법적 정의·기준 체크리스트", exact=True).is_disabled())
        self.assertEqual(self.page.get_by_label("과제명", exact=True).input_value(), "오프라인 합성 과제")

    def test_complete_evidence_and_safe_long_text(self):
        self.start()
        self.wait_result()
        text = self.page.locator("#result-content").inner_text()
        for expected in ("민감과제", "실제 선정 항목", "군사·안보 활용성", "문서 일부 실패", "C:/synthetic/의견서.hwpx", "합성 파일 잠금",
                         "보안등급(AI 참고)", "종합 의견", "중점 논의사항", "등급분류 대상"):
            self.assertIn(expected, text)
        self.page.get_by_role("button", name="고시 대조 근거", exact=True).click()
        # Source versions and full evidence are intentionally folded by default.
        self.page.locator("#result-content details").evaluate_all("els=>els.forEach(el=>{el.open=true})")
        evidence = self.page.locator("#result-content").inner_text()
        for expected in ("합성 속도 기준", "속도 10 GHz 이상", "20 GHz", "GHz", "현재", "목표", "추가 확인", "후보 없음(자동 탐색)", "synthetic-advanced", "https://example.gov.test/source"):
            self.assertIn(expected, evidence)
        comparison_id = RESULT["notice_review"]["comparisons"][0]["comparison_id"]
        self.assertIn(comparison_id, self.page.locator("#result-content").text_content())
        self.assertEqual(self.page.locator("#result-content script,#result-content img,#result-content svg").count(), 0)
        self.assertIsNone(self.page.evaluate("window.injected"))
        self.page.get_by_role("button", name="AI 개별 의견", exact=True).click()
        for persona in domain.PERSONAS:
            self.assertIn(persona, self.page.locator("#result-content").inner_text())
        self.page.get_by_role("button", name="종합 검토", exact=True).click()
        self.assertIn(RESULT["rationale"], self.page.locator("#result-content").text_content())
        self.assertGreater(self.page.locator("#result-content details").count(), 0)
        after = [c["args"][1] for c in self.calls("get_job")]
        self.assertEqual(after[:2], [0, 1])

    def test_batch_paths_picker_cancel_and_saved_result_export(self):
        self.menu("연구개발과제 일괄 검토")
        self.page.evaluate("testHarness.cancelledPicker=true")
        self.page.get_by_role("button", name="입력 엑셀 선택", exact=True).click()
        self.assertIn("선택하지 않음", self.page.locator("#batch-input-name").inner_text())
        self.page.evaluate("testHarness.cancelledPicker=false")
        for name in ("입력 엑셀 선택", "결과 엑셀 선택", "의견서 폴더 선택"):
            self.page.get_by_role("button", name=name, exact=True).click()
        self.page.get_by_label("동시 처리 수", exact=True).fill("8")
        self.page.get_by_role("button", name="일괄 검토 시작", exact=True).click()
        self.wait_result()
        payload = self.calls("start_batch")[0]["args"][0]
        self.assertEqual(payload["input_token"], "token-input_excel")
        self.assertEqual(payload["output_token"], "token-output_excel")
        self.assertEqual(payload["workers"], 8)
        self.assertIn("합성 감사 일부 실패", self.page.locator("#batch-report").inner_text())
        report_text = self.page.locator("#batch-report").inner_text()
        self.assertIn("대상 제외", report_text)
        self.assertNotRegex(report_text, r"\b(total|completed|failed|cancelled|needs_review|excluded)\b")
        self.page.get_by_role("button", name="저장 결과로 의견서 재생성", exact=True).click()
        self.page.wait_for_function("() => testHarness.calls.some(c=>c.name==='start_export')")
        export = self.calls("start_export")[0]["args"][0]
        self.assertEqual(export, {"job_id": "job-1", "task_fingerprint": RESULT["task_fingerprint"], "output_dir_token": "token-output_directory"})
        self.assertEqual(len(self.calls("start_single")), 0)
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='완료' && !document.querySelector('#result-content').textContent.includes('문서 일부 실패')")
        self.assertIn("의견서 저장 상태", self.page.locator("#result-content").inner_text())
        self.assertEqual(self.page.locator("#result-picker option").count(), 1)
        self.assertNotIn("result", export)

    def test_one_agent_openai_and_lmstudio_settings(self):
        self.menu("모델·설정")
        self.page.get_by_label("모델 제공자", exact=True).select_option("openai")
        self.menu("연구개발과제 검토")
        self.page.get_by_label("AI 에이전트 구성", exact=True).select_option("1")
        self.start()
        self.wait_result()
        opts = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual((opts["provider"], opts["model"], opts["num_reviewers"]), ("openai", "gpt-6-luna", 1))
        self.menu("모델·설정")
        self.page.get_by_label("모델 제공자", exact=True).select_option("lmstudio")
        self.page.get_by_label("로컬 서버 주소", exact=True).fill("http://127.0.0.1:1234/v1")
        self.page.get_by_label("로컬 모델 식별자", exact=True).fill('<img src=x onerror="window.injected=1">')
        self.menu("연구개발과제 검토")
        self.assertIn("<img", self.page.locator("#model-summary").inner_text())
        self.assertEqual(self.page.locator("#model-summary img").count(), 0)
        self.assertIsNone(self.page.evaluate("window.injected"))
        self.start()
        self.page.wait_for_function("() => testHarness.calls.filter(c=>c.name==='start_single').length===2")
        opts = self.calls("start_single")[1]["args"][0]["options"]
        self.assertEqual((opts["provider"], opts["local_base_url"]), ("lmstudio", "http://127.0.0.1:1234/v1"))

    def test_manual_omission_policy_priority_and_tab_persistence(self):
        self.menu("모델·설정")
        self.page.get_by_label("공통 부처 세부기준", exact=True).fill("합성 공통 부처기준")
        self.menu("연구개발과제 검토")
        self.page.get_by_role("button", name="직접 선정", exact=True).click()
        self.page.get_by_label("1 군사·안보 활용성", exact=True).check()
        self.page.get_by_label("군사·안보 활용성 가중치", exact=True).fill("")
        self.page.get_by_label("8 부처 정책상 관리 필요성", exact=True).check()
        self.page.get_by_label("부처 세부기준", exact=True).fill("합성 과제별 부처기준")
        self.page.get_by_label("추가 검토정보", exact=True).fill('<script>window.injected=1</script><svg onload="window.injected=2">')
        self.menu("연구개발과제 일괄 검토")
        self.menu("연구개발과제 검토")
        self.assertTrue(self.page.get_by_label("8 부처 정책상 관리 필요성", exact=True).is_checked())
        self.start()
        self.wait_result()
        payload = self.calls("start_single")[0]["args"][0]
        self.assertEqual(payload["options"]["weights"], {domain.ITEM_NAMES[0]: 1, domain.ITEM_NAMES[7]: 1})
        self.assertEqual(payload["options"]["ministry_policy"], "합성 공통 부처기준")
        self.assertEqual(payload["task"]["부처 세부기준"], "합성 과제별 부처기준")
        self.assertIsNone(self.page.evaluate("window.injected"))
        self.menu("연구개발과제 검토")
        self.assertIn("<script>", self.page.get_by_label("추가 검토정보", exact=True).input_value())
        self.menu("검토 결과")
        self.assertIn("합성 과제", self.page.locator("#result-heading").inner_text())

    def test_key_failure_clears_and_keyboard_dialog_focus(self):
        self.page.get_by_role("button", name="등급분류 가이드라인 ↗", exact=True).click()
        self.assertTrue(self.page.get_by_role("dialog").is_visible())
        self.page.keyboard.press("Escape")
        self.assertFalse(self.page.get_by_role("dialog").is_visible())
        self.assertTrue(self.page.locator("#open-guideline").evaluate("el=>el===document.activeElement"))
        self.menu("모델·설정")
        self.page.evaluate("testHarness.failNext='save_key'")
        self.page.get_by_label("새 API 키", exact=True).fill("synthetic-key-failure")
        self.page.get_by_role("button", name="키 저장", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#api-key').value===''")
        self.assertNotIn("synthetic-key-failure", self.page.content())
        self.assertIn("진행 중", self.page.locator("#message").inner_text())

    def test_layout_alignment_scroll_and_captures(self):
        CAPTURE.mkdir(parents=True, exist_ok=True)
        tops = self.page.locator(".field-row").first.locator("label").evaluate_all("els=>els.map(el=>el.getBoundingClientRect().top)")
        self.assertEqual(tops[0], tops[1])
        self.page.screenshot(path=str(CAPTURE / "input-1366.png"), full_page=True)
        self.menu("모델·설정")
        self.page.screenshot(path=str(CAPTURE / "settings-1366.png"), full_page=True)
        self.menu("연구개발과제 검토")
        self.start()
        self.wait_result()
        self.page.get_by_role("button", name="고시 대조 근거", exact=True).click()
        self.page.screenshot(path=str(CAPTURE / "evidence-1366.png"), full_page=True)
        for width in (820, 600, 390):
            self.page.set_viewport_size({"width": width, "height": 620})
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
            wrap = self.page.locator("#result-content .table-wrap").first
            self.assertTrue(wrap.evaluate("el=>el.scrollWidth>el.clientWidth"))
        self.page.screenshot(path=str(CAPTURE / "evidence-390.png"), full_page=True)

    def test_fact_basis_labels_in_both_fact_tables(self):
        self.show_evidence(evidence_result(bases=True))
        evidence = self.page.locator("#result-content")
        self.assertIn("현재·목표 공통", evidence.inner_text())
        provided = evidence.locator("[data-fact-table='provided']")
        self.assertIn("현재·목표 공통", provided.inner_text())
        self.assertIn("목표", provided.inner_text())
        all_facts = evidence.locator("details.all-facts")
        all_facts.locator("summary").click()
        labels = all_facts.locator("tbody tr td:first-child").all_text_contents()
        self.assertEqual(labels, ["현재", "현재·목표 공통", "시점 불명", "목표"])
        # Defensive handling of an unsupported future value must not imply current.
        malformed = evidence_result(bases=True)
        malformed["notice_review"]["facts"][2]["basis"] = "future-unknown"
        self.show_evidence(malformed)
        all_facts = self.page.locator("details.all-facts")
        all_facts.locator("summary").click()
        self.assertIn("시점 미확인", all_facts.locator("tbody tr").nth(2).inner_text())

    def test_four_family_search_states_and_incomplete_candidates(self):
        result = evidence_result(statuses={"core": "partial", "dual_use": "not_run", "military": "error"})
        self.show_evidence(result)
        for family, expected in (("advanced", "전체 탐색 완료"), ("core", "일부 탐색"),
                                 ("dual_use", "시작 전"), ("military", "탐색 오류")):
            row = self.page.locator(f".family-summary[data-family='{family}']")
            self.assertEqual(row.count(), 1)
            self.assertIn(expected, row.inner_text())
            self.assertIn("남은", row.inner_text())
            if family != "advanced":
                self.assertIn("탐색 미완료", row.inner_text())
                self.assertNotIn("후보 없음(자동 탐색)", row.inner_text())
        self.show_evidence(evidence_result(statuses={"advanced": "partial"}))
        row = self.page.locator(".family-summary[data-family='advanced']")
        self.assertIn("1개 후보", row.inner_text())
        self.assertIn("탐색 미완료", row.inner_text())
        self.assertIn("추가 확인", row.inner_text())
        complete_empty = self.page.locator(".family-summary[data-family='core']")
        self.assertIn("후보 없음(자동 탐색)", complete_empty.inner_text())

    def test_target_none_partial_full_and_readable_questions(self):
        for target, expected in (("none", "목표 정보 미제공"), ("partial", "목표 조건 일부 충족·추가 확인"),
                                 ("full", "목표 달성 시 해당 가능성")):
            with self.subTest(target=target):
                self.show_evidence(evidence_result(target=target))
                metric = self.page.locator(".target-assessment")
                self.assertEqual(metric.count(), 1)
                self.assertIn(expected, metric.inner_text())
                if target == "partial":
                    questions = self.page.locator(".missing-questions")
                    self.assertIn("현재", questions.inner_text())
                    self.assertIn("목표", questions.inner_text())
                    # Stored program sentences are displayed exactly as received.
                    self.assertIn("합성 적용 용도와 예외 조건을 확인해 주세요.", questions.inner_text())
                    self.assertIn("합성 적용 용도 조건", questions.inner_text())
                    self.assertIn("usage", questions.text_content())
                    for raw_key in ("basis:", "predicate_id:", "question:"):
                        self.assertNotIn(raw_key, questions.inner_text())

    def test_long_evidence_folds_preserve_all_content_and_keyboard_scroll(self):
        CAPTURE.mkdir(parents=True, exist_ok=True)
        for candidates in (1, 3):
            result = evidence_result(long=True, candidates=candidates)
            self.show_evidence(result)
            self.assertEqual(self.page.locator("section.evidence").count(), candidates)
            original = self.page.locator("details.clause-original").first
            self.assertEqual(original.count(), 1)
            self.assertFalse(original.evaluate("el=>el.open"))
            references = self.page.locator("details.reference-clauses")
            self.assertFalse(references.evaluate("el=>el.open"))
            self.assertIn("64", references.locator("summary").first.inner_text())
            excluded = self.page.locator("details.excluded-details[data-family='core']")
            self.assertFalse(excluded.evaluate("el=>el.open"))
            self.assertIn("571", excluded.locator("summary").inner_text())
            self.assertEqual(excluded.locator("li").count(), 571)
            sources = self.page.locator("details.evidence-sources")
            self.assertFalse(sources.evaluate("el=>el.open"))
            self.assertIn("9", sources.locator("summary").first.inner_text())
            self.assertIn(result["notice_review"]["clause_snapshots"][0]["text"], original.text_content())
            self.assertIn("합성 제외 상세 근거 570", excluded.text_content())
            self.assertLess(self.page.evaluate("document.documentElement.scrollHeight"), 9500)
            self.page.screenshot(path=str(CAPTURE / f"evidence-long-{candidates}-1366.png"), full_page=True)
        self.page.set_viewport_size({"width": 390, "height": 620})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
        self.page.screenshot(path=str(CAPTURE / "evidence-long-3-390.png"), full_page=True)
        references.locator("summary").first.focus()
        self.page.keyboard.press("Enter")
        self.assertTrue(references.evaluate("el=>el.open"))
        self.assertIn("합성 주석 64 전문", references.inner_text())
        sources.locator("summary").first.focus()
        self.page.keyboard.press("Enter")
        self.assertIn("synthetic-extra-4", sources.inner_text())
        wrap = self.page.locator("[data-fact-table='provided'] .table-wrap").first
        wrap.focus()
        self.page.keyboard.press("ArrowRight")
        self.page.wait_for_timeout(150)
        self.assertGreater(wrap.evaluate("el=>el.scrollLeft"), 0)
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))

    def test_stale_poll_never_replaces_new_job(self):
        self.page.evaluate("testHarness.mode='deferred'")
        self.start()
        self.page.wait_for_function("() => testHarness.deferred.length===1")
        self.page.get_by_role("button", name="작업 취소", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='취소'")
        self.page.evaluate("testHarness.mode='normal'")
        self.start()
        self.wait_result()
        self.page.evaluate("testHarness.deferred[0]()")
        self.page.wait_for_timeout(100)
        self.assertNotIn("이전 작업 지연", self.page.locator("body").inner_text())

    def test_failed_job_and_small_window_actions(self):
        self.page.set_viewport_size({"width": 820, "height": 620})
        self.page.evaluate("testHarness.mode='failed'")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='오류'")
        self.assertIn("합성 기준 로드 오류", self.page.locator("#job-status").inner_text())
        self.assertTrue(self.page.get_by_role("button", name="AI 에이전트 검토 시작", exact=True).is_enabled())
        self.assertEqual(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"), False)

    # v16 additions -----------------------------------------------------------------

    def test_v16_name_menus_titles_and_descriptions(self):
        self.assertEqual(self.page.title(), f"{PROGRAM_NAME} · v16")
        self.assertEqual(self.page.locator(".brand").inner_text().strip(), PROGRAM_NAME)
        buttons = self.page.get_by_role("navigation", name="주요 메뉴").get_by_role("button")
        self.assertEqual(buttons.count(), 5)
        for index, (number, title, view) in enumerate(MENUS):
            with self.subTest(menu=title):
                button = buttons.nth(index)
                self.assertEqual(button.get_attribute("data-view"), view)
                self.assertEqual(button.inner_text().split(), [number] + title.split())
                button.click()
                screen = self.page.locator(f"#screen-{view}")
                self.assertTrue(screen.is_visible())
                self.assertEqual(screen.locator("h1").inner_text(), title)
                self.assertEqual(screen.locator(".hero .sub").count(), 1)
                description = screen.locator(".hero .sub").inner_text()
                self.assertTrue(description and "\n" not in description)
                self.assertEqual(self.page.locator("#breadcrumb").inner_text(), title)
                body = self.page.locator("body").inner_text()
                for forbidden in ("研", "연구보안 검토실") + ENGLISH_LABELS + SLOGANS:
                    self.assertNotIn(forbidden, body)
        self.assertEqual(self.page.locator(".eyebrow,.section-label,.mark").count(), 0)

    def test_notice_dates_everywhere_and_identity_folded(self):
        notices = INITIAL["catalogue"]["notices"]
        def assert_dates(scope):
            text = self.page.locator(scope).inner_text()
            for notice in notices:
                for value in (notice["title"], notice["notice_number"], notice["announcement_date"], notice["effective_date"]):
                    self.assertIn(value, text, scope)
            self.assertIn("고시일", text)
            self.assertIn("시행일", text)
        assert_dates("#input-notices")
        link = self.page.locator("#screen-input").get_by_role("button", name="참고 고시에서 조항 원문 확인 →", exact=True)
        self.menu("모델·설정")
        assert_dates("#catalogue-info")
        self.assert_only_in_closed_details("#catalogue-info", CATALOGUE_ID)
        self.assert_only_in_closed_details("#catalogue-info", CATALOGUE_FINGERPRINT)
        self.assert_only_in_closed_details("#catalogue-info", "원문 수집일")
        self.assertNotIn("확인일", self.page.locator("#catalogue-info").text_content())
        self.page.locator("#catalogue-info details.catalogue-identity > summary").click()
        self.assertIn("원문 수집일 · 2026-10-21T09:00:00Z", self.page.locator("#catalogue-info").inner_text())
        self.assertIn("고시일 · 2025-05-12", self.page.locator("#catalogue-info").inner_text())
        self.menu("연구개발과제 일괄 검토")
        assert_dates("#batch-options-summary")
        self.assert_only_in_closed_details("#batch-options-summary", CATALOGUE_ID)
        self.menu("연구개발과제 검토")
        link.click()
        self.assertTrue(self.page.locator("#screen-notices").is_visible())

    def test_result_shows_stored_notices_grouped_with_title_fallback(self):
        result = deepcopy(RESULT)
        # Stored sources differ from the installed catalogue; the result must show its own.
        for source in result["notice_review"]["sources"]:
            source["announcement_date"] = {"산업통상자원부고시 제2025-71호": "2025-05-01"}.get(source["notice_number"], source["announcement_date"])
        result["notice_review"]["sources"].append(dict(result["notice_review"]["sources"][0], source_id="synthetic-unlisted-body",
            notice_number="합성고시 제2099-1호", title="합성 미등록 고시 출처", announcement_date="2099-01-02", effective_date="2099-01-03"))
        self.show_evidence(result)
        stored = self.page.locator("#result-content .stored-notices").first
        items = stored.locator("li")
        self.assertEqual(items.count(), 4)
        texts = items.all_inner_texts()
        self.assertIn("국가첨단전략기술 지정 등에 관한 고시", texts[0])
        self.assertIn("2025-05-01", texts[0])
        self.assertIn("국가핵심기술 지정 등에 관한 고시", texts[1])
        self.assertIn("전략물자수출입고시", texts[2])
        self.assertIn("2026-08-31", texts[2])
        self.assertIn("2026-09-01", texts[2])
        self.assertIn("합성 미등록 고시 출처", texts[3])
        self.assertIn("합성고시 제2099-1호", texts[3])
        self.assertNotIn("2025-05-12", stored.inner_text())
        self.assert_only_in_closed_details("#result-content", result["notice_review"]["catalogue_fingerprint"])
        self.assert_only_in_closed_details("#result-content", "원문 수집일")
        self.page.get_by_role("button", name="종합 검토", exact=True).click()
        summary = self.page.locator("#result-content .stored-notices").first
        self.assertIn("전략물자수출입고시", summary.inner_text())
        self.assert_only_in_closed_details("#result-content", result["notice_review"]["catalogue_id"])

    def test_candidate_excluded_status_displayed_as_target_excluded(self):
        result = deepcopy(RESULT)
        result.update(status="후보제외", final_grade=None)
        result["candidate"] = {"is_candidate": False, "reason": "합성 대상 제외 사유", "uncertainty": ""}
        self.page.evaluate("result => {testHarness.result=result;}", result)
        self.start()
        self.wait_result()
        self.assertIn("대상 제외", self.page.locator("#result-status").inner_text())
        self.assertIn("대상 제외", self.page.locator("#result-picker").inner_text())
        self.assertIn("대상 제외", self.page.locator("#result-content").inner_text())
        self.assertNotIn("후보제외", self.page.locator("#saved-results").inner_text())
        self.assertIn("합성 대상 제외 사유", self.page.locator("#result-content").inner_text())

    def test_reference_notice_cards_notes_and_copyable_urls(self):
        self.open_notices()
        screen = self.page.locator("#screen-notices")
        notes = screen.locator("#notice-notes li").all_inner_texts()
        self.assertEqual(notes, list(NOTICE_NOTES))
        cards = screen.locator(".notice-card")
        self.assertEqual(cards.count(), 3)
        # Follow-up spec 4.3: title, number, dates and official source only; no range or clause counts.
        for index, notice in enumerate(INITIAL["catalogue"]["notices"]):
            card = cards.nth(index)
            text = card.text_content()
            self.assertEqual(card.locator("h2").inner_text(), notice["title"])
            labels = card.locator(".metric > span:first-child").all_inner_texts()
            values = card.locator(".metric > span:last-child").all_inner_texts()
            self.assertEqual(labels, ["고시번호", "고시일", "시행일"])
            self.assertEqual(values, [notice["notice_number"], notice["announcement_date"], notice["effective_date"]])
            self.assertEqual(card.locator("h3").all_inner_texts(), ["공식 출처 주소"])
            self.assertIn(notice["official_url"], text)
            for removed in ("범위", "조항", "자동 해석", "미해석", "이중용도", "군용"):
                self.assertNotIn(removed, text)
        # The search keeps its range filter; result lines and opened clauses keep the range.
        family = screen.get_by_label("고시 범위", exact=True)
        self.assertEqual(family.locator("option").all_inner_texts(),
                         ["전체", "국가첨단전략기술", "국가핵심기술", "전략물자 · 별표 2 이중용도", "전략물자 · 별표 3 군용"])
        first = self.page.locator("#notice-results details.clause-item").first
        self.assertIn("국가첨단전략기술", first.locator(".clause-meta").inner_text())
        first.locator("summary").click()
        first.locator(".clause-text").wait_for()
        pairs = first.locator(".clause-body .metric").evaluate_all(
            "rows=>rows.map(row=>[...row.children].map(cell=>cell.textContent))")
        self.assertIn(["범위", "국가첨단전략기술"], pairs)
        self.assertEqual(screen.locator("a").count(), 0)
        url = cards.nth(0).locator(".url-text")
        self.assertEqual(url.inner_text(), INITIAL["catalogue"]["notices"][0]["official_url"])
        self.assertEqual(url.evaluate("el=>getComputedStyle(el).userSelect"), "all")

    def test_reference_search_paging_family_whitespace_and_zero_results(self):
        self.open_notices()
        first = self.calls("search_notice_clauses")
        self.assertEqual(first[0]["args"], [{"query": "", "family": None, "offset": 0, "limit": 50}])
        results = self.page.locator("#notice-results details.clause-item")
        self.assertEqual(results.count(), 50)
        more = self.page.get_by_role("button", name="더 보기", exact=True)
        self.assertTrue(more.is_visible())
        self.assertIn("120", self.page.locator("#notice-summary").inner_text())
        more.click()
        self.page.wait_for_function("() => document.querySelectorAll('#notice-results details').length===100")
        more.click()
        self.page.wait_for_function("() => document.querySelectorAll('#notice-results details').length===120")
        self.assertFalse(more.is_visible())
        offsets = [call["args"][0]["offset"] for call in self.calls("search_notice_clauses")]
        self.assertEqual(offsets, [0, 50, 100])
        first_item = results.first.locator("summary").inner_text()
        for expected in ("SYN-AD-001", "국가첨단전략기술", "산업통상자원부고시 제2025-71호"):
            self.assertIn(expected, first_item)
        self.search("", "dual_use")
        self.assertEqual(self.calls("search_notice_clauses")[-1]["args"][0], {"query": "", "family": "dual_use", "offset": 0, "limit": 50})
        self.assertEqual(results.count(), 45)
        self.assertFalse(more.is_visible())
        self.assertTrue(all("이중용도" in text for text in results.locator("summary").all_inner_texts()))
        self.search("기술")
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first.get_attribute("data-clause-id"), "advanced:1")
        self.search("초정밀 가공", "dual_use")
        self.assertEqual(self.calls("search_notice_clauses")[-1]["args"][0]["query"], "초정밀 가공")
        self.assertEqual(results.first.get_attribute("data-clause-id"), "dual_use:1")
        self.assertIn("1A001", results.first.inner_text())
        self.search("존재하지 않는 합성 검색어")
        self.assertEqual(results.count(), 0)
        empty = self.page.locator("#notice-empty")
        self.assertTrue(empty.is_visible())
        self.assertIn("검색 결과 없음", empty.inner_text())
        self.assertIn("검색 결과 없음은 비해당 판정 아님", empty.inner_text())
        self.assertFalse(more.is_visible())
        self.search("   ")
        self.assertEqual(results.count(), 50)
        self.assertFalse(empty.is_visible())

    def test_reference_clause_text_is_plain_text_and_long_text_wraps(self):
        self.open_notices()
        malicious = self.page.locator("details.clause-item[data-clause-id='core:1']")
        malicious.locator("summary").click()
        body = malicious.locator(".clause-text")
        body.wait_for()
        self.assertEqual(self.calls("get_notice_clause")[-1]["args"], ["core:1"])
        clause = next(c for c in CLAUSES if c["clause_id"] == "core:1")
        self.assertEqual(body.text_content(), clause["text"])
        self.assertEqual(self.page.locator("#screen-notices script,#screen-notices img,#screen-notices svg").count(), 0)
        self.assertIsNone(self.page.evaluate("window.injected"))
        details = malicious.inner_text()
        for value in ("국가핵심기술 지정 등에 관한 고시", "산업통상부고시 제2025-2호", "2025-10-02", "합성 별표 1",
                      "https://example.gov.test/synthetic-core-body"):
            self.assertIn(value, details)
        spaced = self.page.locator("details.clause-item[data-clause-id='advanced:1']")
        self.assertIn("기\n\n 술", spaced.locator(".clause-title").text_content())
        CAPTURE.mkdir(parents=True, exist_ok=True)
        long_item = self.page.locator("details.clause-item[data-clause-id='advanced:2']")
        long_item.locator("summary").click()
        long_text = long_item.locator(".clause-text")
        long_text.wait_for()
        self.assertEqual(len(long_text.text_content()), 14 * 5200 + 1)
        for width in (1366, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 720})
                self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                self.assertLessEqual(long_text.evaluate("el=>el.scrollWidth-el.clientWidth"), 1)
                box = long_text.bounding_box()
                self.assertLessEqual(box["x"] + box["width"], width)
                self.page.screenshot(path=str(CAPTURE / f"notices-{width}.png"), full_page=False)
        # A clause from another source shows its own source URL, as returned.
        self.search("", "military")
        annex = self.page.locator("details.clause-item[data-clause-id='military:1']")
        annex.locator("summary").click()
        annex.locator(".clause-text").wait_for()
        self.assertIn("https://example.gov.test/synthetic-military-annex", annex.inner_text())
        self.assertIn("전략물자수출입고시", annex.inner_text())

    def test_reference_search_works_while_job_runs(self):
        self.page.evaluate("testHarness.mode='hold'")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-status').textContent.includes('고시 대조')")
        self.open_notices()
        self.assertTrue(self.page.get_by_label("조항 검색어", exact=True).is_enabled())
        self.search("SYN-CO-002")
        results = self.page.locator("#notice-results details.clause-item")
        self.assertEqual(results.first.get_attribute("data-clause-id"), "core:2")
        results.first.locator("summary").click()
        results.first.locator(".clause-text").wait_for()
        self.assertEqual(self.page.locator("#job-state").inner_text(), "진행")
        self.assertEqual(self.calls("cancel_job"), [])
        self.assertTrue(self.page.get_by_role("button", name="작업 취소", exact=True).is_enabled())

    def test_guideline_window_matches_appendix_a(self):
        self.page.get_by_role("button", name="등급분류 가이드라인 ↗", exact=True).click()
        dialog = self.page.get_by_role("dialog")
        self.assertTrue(dialog.is_visible())
        self.assertEqual(dialog.locator(".guideline-source").text_content(), GUIDELINE_SOURCE)
        definitions = dialog.locator(".guideline-definition")
        self.assertEqual(definitions.count(), len(APPENDIX_A_DEFINITIONS))
        for index, expected in enumerate(APPENDIX_A_DEFINITIONS):
            self.assertEqual(definitions.nth(index).locator("h4").text_content(), expected["heading"])
            self.assertEqual(definitions.nth(index).locator("p").text_content(), expected["text"])
        principles = dialog.locator(".guideline-principle")
        self.assertEqual(principles.count(), len(APPENDIX_A_PRINCIPLES))
        for index, expected in enumerate(APPENDIX_A_PRINCIPLES):
            self.assertEqual(principles.nth(index).locator("h4").text_content(), expected["title"])
            self.assertEqual(principles.nth(index).locator("li").all_text_contents(), expected["details"])
        text = dialog.text_content()
        self.assertNotIn("대체값으로 사용하지 않는다", text)
        for constant in domain.CLASSIFICATION_PRINCIPLES:
            self.assertNotIn(constant, text)
        self.assertIn(domain.GUIDELINE_ID, text)
        self.assertLessEqual(dialog.evaluate("el=>el.scrollWidth-el.clientWidth"), 1)
        self.page.get_by_role("button", name="닫기", exact=True).click()
        self.menu("모델·설정")
        self.page.get_by_role("button", name="가이드라인 정의·원칙 보기 →", exact=True).click()
        self.assertEqual(dialog.locator(".guideline-definition").count(), len(APPENDIX_A_DEFINITIONS))

    def test_twelve_function_mock_wiring(self):
        self.assertEqual(sorted(self.page.evaluate("Object.keys(window.pywebview.api)")), sorted(BRIDGE_FUNCTIONS))
        self.menu("모델·설정")
        self.page.get_by_label("새 API 키", exact=True).fill("synthetic-wiring-key")
        self.page.get_by_role("button", name="키 저장", exact=True).click()
        self.page.wait_for_function("() => testHarness.calls.some(c=>c.name==='save_key')")
        self.page.get_by_role("button", name="저장 키 삭제", exact=True).click()
        self.page.wait_for_function("() => testHarness.calls.some(c=>c.name==='delete_key')")
        self.menu("연구개발과제 일괄 검토")
        self.page.get_by_role("button", name=TEMPLATE_BUTTON, exact=True).click()
        self.page.wait_for_function("() => testHarness.calls.some(c=>c.name==='save_input_template')")
        for name in ("입력 엑셀 선택", "결과 엑셀 선택", "의견서 폴더 선택"):
            self.page.get_by_role("button", name=name, exact=True).click()
        self.page.get_by_role("button", name="일괄 검토 시작", exact=True).click()
        self.wait_result()
        self.page.get_by_role("button", name="저장 결과로 의견서 재생성", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='완료' && testHarness.calls.some(c=>c.name==='start_export') && !document.querySelector('#start-single').disabled")
        self.page.evaluate("testHarness.mode='hold'")
        self.menu("연구개발과제 검토")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-status').textContent.includes('고시 대조')")
        self.page.get_by_role("button", name="작업 취소", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='취소'")
        self.open_notices()
        self.page.locator("details.clause-item").first.locator("summary").click()
        self.page.locator("details.clause-item .clause-text").first.wait_for()
        called = set(self.page.evaluate("testHarness.calls.map(c=>c.name)"))
        self.assertEqual(called, set(BRIDGE_FUNCTIONS))
        self.assertEqual(self.calls("get_initial_state"), [{"name": "get_initial_state", "args": []}])
        self.assertNotIn("synthetic-wiring-key", self.page.content())
        script = PAGE.with_name("app.js").read_text(encoding="utf-8")
        named = set(re.findall(r"call\('([a-z_]+)'", script))
        self.assertLessEqual(named, set(BRIDGE_FUNCTIONS))
        self.assertIn("search_notice_clauses", named)
        self.assertIn("get_notice_clause", named)
        self.assertIn("save_input_template", named)

    def test_notice_screen_widths_390_and_1366(self):
        CAPTURE.mkdir(parents=True, exist_ok=True)
        for width in (1366, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 760})
                self.open_notices()
                self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                for selector in (".notice-card", "#notice-query", "#notice-results"):
                    box = self.page.locator(selector).first.bounding_box()
                    self.assertLessEqual(box["x"] + box["width"], width, selector)
                self.page.screenshot(path=str(CAPTURE / f"notices-cards-{width}.png"), full_page=True)
                for menu in ("연구개발과제 검토", "연구개발과제 일괄 검토", "검토 결과", "모델·설정"):
                    self.menu(menu)
                    self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"), menu)
                self.page.screenshot(path=str(CAPTURE / f"settings-{width}.png"), full_page=True)

    # v16 follow-up additions --------------------------------------------------------

    def test_template_button_sits_at_top_of_batch_file_panel(self):
        self.menu("연구개발과제 일괄 검토")
        panel = self.page.locator("#screen-batch section.panel").filter(
            has=self.page.get_by_role("heading", name="일괄 검토 파일", exact=True))
        self.assertEqual(panel.count(), 1)
        buttons = panel.locator("button").all_inner_texts()
        self.assertEqual(buttons[:2], [TEMPLATE_BUTTON, "입력 엑셀 선택"])
        self.assertEqual(panel.locator(".mini-text").first.inner_text(), BATCH_GUIDANCE)
        template = panel.get_by_role("button", name=TEMPLATE_BUTTON, exact=True)
        self.assertTrue(template.is_enabled())
        self.assertLess(template.bounding_box()["y"], panel.get_by_role("button", name="입력 엑셀 선택", exact=True).bounding_box()["y"])

    def test_template_download_flow_cancel_save_protected_and_busy(self):
        self.menu("연구개발과제 일괄 검토")
        button = self.page.get_by_role("button", name=TEMPLATE_BUTTON, exact=True)
        name = self.page.locator("#batch-template-name")
        initial_name = name.inner_text()
        # Cancelling the save dialog does nothing: no save call, no message.
        self.page.evaluate("testHarness.cancelledPicker=true")
        button.click()
        self.page.wait_for_function("() => testHarness.calls.some(c=>c.name==='select_path')")
        self.page.wait_for_timeout(100)
        self.assertEqual(self.calls("select_path")[-1]["args"], ["input_template"])
        self.assertEqual(self.calls("save_input_template"), [])
        self.assertEqual(name.inner_text(), initial_name)
        self.assertTrue(self.page.locator("#message").is_hidden())
        # A chosen path is saved with its own token; only the file name is shown.
        self.page.evaluate("testHarness.cancelledPicker=false")
        button.click()
        self.page.wait_for_function("() => document.querySelector('#batch-template-name').textContent.includes('xlsx')")
        self.assertEqual(self.calls("save_input_template")[0]["args"], [{"output_token": "token-input_template"}])
        self.assertEqual(name.inner_text(), TEMPLATE_NAME)
        self.assertNotIn("token-input_template", self.page.locator("body").inner_text())
        # The saved template is never selected as the input workbook.
        self.assertEqual(self.page.locator("#batch-input-name").inner_text(), "선택하지 않음")
        self.page.get_by_role("button", name="결과 엑셀 선택", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#batch-output-name').textContent.includes('output_excel')")
        self.page.get_by_role("button", name="일괄 검토 시작", exact=True).click()
        self.page.wait_for_function("() => !document.querySelector('#message').hidden")
        self.assertEqual(self.page.locator("#message").inner_text(), "입력 엑셀과 결과 엑셀 선택 필요")
        self.assertEqual(self.calls("start_batch"), [])
        # Protected path: the bridge message is shown exactly as sent.
        self.page.evaluate("testHarness.templateMode='protected'")
        button.click()
        self.page.wait_for_function("m => document.querySelector('#message').textContent===m", arg=PROTECTED_MESSAGE)
        self.assertEqual(len(self.calls("save_input_template")), 2)
        # Busy from the bridge is shown too.
        self.page.evaluate("testHarness.templateMode='normal';testHarness.failNext='save_input_template'")
        button.click()
        self.page.wait_for_function("() => document.querySelector('#message').textContent.includes('진행 중')")
        # A running job disables the button like the other file pickers.
        self.page.evaluate("testHarness.mode='hold'")
        self.menu("연구개발과제 검토")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-status').textContent.includes('고시 대조')")
        self.menu("연구개발과제 일괄 검토")
        self.assertTrue(button.is_disabled())
        self.assertTrue(self.page.get_by_role("button", name="입력 엑셀 선택", exact=True).is_disabled())
        direct = self.page.evaluate("window.pywebview.api.save_input_template({output_token:'token-input_template'})")
        self.assertEqual(direct["error"]["code"], "busy")
        self.page.get_by_role("button", name="작업 취소", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='취소'")
        self.assertTrue(button.is_enabled())

    def test_template_mock_rejects_wrong_token_and_purpose(self):
        api = "window.pywebview.api"
        for request in ("{output_token:'token-output_excel'}", "{}", "{output_token:'token-input_template',extra:1}", "null"):
            with self.subTest(request=request):
                response = self.page.evaluate(f"{api}.save_input_template({request})")
                self.assertEqual(response["error"]["code"], "validation")
        self.assertEqual(self.page.evaluate(f"{api}.select_path('unknown')")["error"]["code"], "validation")

    def test_reviewer_composition_options_footnote_and_summary(self):
        select = self.page.get_by_label("AI 에이전트 구성", exact=True)
        options = select.locator("option").evaluate_all("els=>els.map(el=>[el.value,el.textContent])")
        self.assertEqual([tuple(option) for option in options], list(REVIEWER_OPTIONS))
        self.assertEqual(select.input_value(), "3")
        footnote = self.page.locator("#reviewer-footnote")
        self.assertEqual(self.page.locator("#reviewer-description").count(), 0)
        self.assertEqual(self.page.locator("#review-settings").get_by_text("독립 의견과 종합 검토").count(), 0)
        for value in ("3", "1", "3"):
            with self.subTest(value=value):
                select.select_option(value)
                self.assertTrue(footnote.is_visible())
                self.assertEqual(footnote.inner_text(), REVIEWER_FOOTNOTE)
                # The footnote sits directly below the select box.
                below = footnote.evaluate("el=>el.previousElementSibling && el.previousElementSibling.contains(document.getElementById('reviewer-count'))")
                self.assertTrue(below)
                self.assertGreaterEqual(footnote.bounding_box()["y"], select.bounding_box()["y"] + select.bounding_box()["height"] - 1)
                self.menu("연구개발과제 일괄 검토")
                pairs = self.page.locator("#batch-options-summary > .metric").evaluate_all(
                    "rows=>rows.map(row=>[...row.children].map(cell=>cell.textContent))")
                agent = [pair[1] for pair in pairs if pair[0] == "AI 에이전트"]
                self.assertEqual(agent, [REVIEWER_SUMMARIES[value]])
                self.assertNotIn("*", agent[0])
                self.menu("연구개발과제 검토")
        select.select_option("1")
        self.start()
        self.wait_result()
        self.assertEqual(self.calls("start_single")[0]["args"][0]["options"]["num_reviewers"], 1)

    def test_required_marks_and_start_rule_unchanged(self):
        def marks(column):
            return self.page.locator(f"[data-task='{column}']").evaluate(
                "el=>[...el.closest('label').querySelectorAll(':scope > span em')].map(em=>em.textContent)")
        for column in domain.TASK_COLUMNS:
            with self.subTest(column=column):
                found = marks(column)
                self.assertIn("*", found)
                self.assertNotIn("선택", found)
        for column in domain.OPTIONAL_TASK_COLUMNS:
            with self.subTest(column=column):
                found = marks(column)
                self.assertIn("선택", found)
                self.assertNotIn("*", found)
        # The marks are guidance only: an empty 과제명 blocks, the other base fields do not.
        for column in domain.TASK_COLUMNS:
            if column != "과제명":
                self.page.get_by_label(column, exact=True).fill("합성 " + column)
        self.page.get_by_role("button", name="AI 에이전트 검토 시작", exact=True).click()
        self.page.wait_for_function("() => !document.querySelector('#message').hidden")
        self.assertEqual(self.page.locator("#message").inner_text(), "과제명 필수 입력")
        self.assertEqual(self.calls("start_single"), [])
        for column in domain.TASK_COLUMNS:
            self.page.get_by_label(column, exact=True).fill("")
        self.start()
        self.wait_result()
        task = self.calls("start_single")[0]["args"][0]["task"]
        self.assertEqual(task["과제명"], "오프라인 합성 과제")
        self.assertEqual(task["연구목표"], "")


class FrontendViewportTests(unittest.TestCase):
    """Follow-up spec 4.2: five CSS viewport × scale conditions, all five menus (headless Edge)."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(EDGE), headless=True,
                                                     args=["--disable-background-networking", "--no-first-run"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def check_viewport(self, label, width, height, scale):
        context = self.browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale,
                                           reduced_motion="reduce")
        external, errors = [], []
        def route(request_route):
            if request_route.request.url.startswith(("file:", "data:")):
                request_route.continue_()
            else:
                external.append(request_route.request.url)
                request_route.abort()
        context.route("**/*", route)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("const INITIAL=" + json.dumps(INITIAL, ensure_ascii=False) + ";const RESULT="
                             + json.dumps(RESULT, ensure_ascii=False) + ";const CLAUSES="
                             + json.dumps(CLAUSES, ensure_ascii=False) + ";" + FAKE)
        try:
            page.goto(PAGE.as_uri())
            page.wait_for_selector('[data-ready="true"]')
            self.assertEqual(page.evaluate("devicePixelRatio"), scale)
            # A saved result, so the result screen shows its regenerate button.
            page.get_by_label("과제명", exact=True).fill("오프라인 합성 과제")
            page.get_by_role("button", name="AI 에이전트 검토 시작", exact=True).click()
            page.wait_for_function("() => document.querySelector('#result-heading')?.textContent.includes('합성 과제')"
                                   " && !document.querySelector('#start-single').disabled")
            for menu, view, bottom in BOTTOM_BUTTONS:
                with self.subTest(viewport=label, menu=menu):
                    page.get_by_role("navigation", name="주요 메뉴").get_by_role("button", name=menu, exact=True).click()
                    page.wait_for_selector(f"#screen-{view}:not([hidden])")
                    if view == "notices":
                        page.wait_for_function("() => document.querySelectorAll('#notice-results details').length===50"
                                               " && !document.querySelector('#notice-more').hidden")
                    overflow = page.evaluate("[document.documentElement.scrollWidth,document.documentElement.clientWidth]")
                    self.assertLessEqual(overflow[0], overflow[1], "page horizontal overflow")
                    self.assertEqual(page.evaluate(REACH_JS, bottom), "ok", bottom)
                    self.assertEqual(page.evaluate(SPLIT_WORDS_JS, WORD_TARGETS), [])
                    sidebar = page.evaluate(SIDEBAR_JS)
                    self.assertLessEqual(sidebar["top"], 0.5, sidebar)
                    self.assertGreaterEqual(sidebar["bottom"], sidebar["height"] - 0.5, sidebar)
                    self.assertEqual(sidebar["hits"], [True, True, True], sidebar)
                    self.assertNotIn(sidebar["background"], ("rgba(0, 0, 0, 0)", "transparent"))
                    self.assertTrue(sidebar["contained"], sidebar)
                    if view == "batch":
                        links = page.locator("#screen-batch .aside .text-link")
                        self.assertEqual(links.all_inner_texts(), ["검토항목 설정 →", "모델·공통 부처기준 설정 →"])
                        first, second = links.nth(0).bounding_box(), links.nth(1).bounding_box()
                        self.assertGreaterEqual(second["y"], first["y"] + first["height"] - 1)
            self.assertEqual(external, [])
            self.assertEqual(errors, [])
        finally:
            context.close()

    def test_viewport_1920x1080_125_start_window(self):
        self.check_viewport(*VIEWPORTS[0])

    def test_viewport_1920x1080_125_maximized(self):
        self.check_viewport(*VIEWPORTS[1])

    def test_viewport_1920x1080_150_start_window(self):
        self.check_viewport(*VIEWPORTS[2])

    def test_viewport_1366x768_125_start_window(self):
        self.check_viewport(*VIEWPORTS[3])

    def test_viewport_1366x768_100_start_window(self):
        self.check_viewport(*VIEWPORTS[4])


if __name__ == "__main__":
    unittest.main()
