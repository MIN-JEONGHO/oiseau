"""Offline renderer regressions: real Edge DOM, fake public bridge, no accounts.

Run with the v15 development environment (Playwright is a test-only tool).
The browser uses a fresh profile, never the person's browser or credentials.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

import v15_domain as domain
from tests.test_v15_domain import synthetic_result

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui_v15" / "index.html"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# Exact public get_initial_state shape (RunOptions.to_dict defaults):
# {defaults,criteria:[{id,name,security_refs,sensitive_refs,rubric}],
# credential_status:{claude:bool,openai:bool},
# catalogue:{catalogue_id,fingerprint,status:'ready',sources,
# families:[{family,total_clauses,interpreted_clauses,unsupported_clauses}]},
# guideline:{id,definitions,principles}}. Counts here are synthetic test metadata.
# No key value is returned. Single result is the schema-2 DTO root; batch is
# {results,counts?,paths?,warnings?,persistence?}. Export returns a new job_id;
# that job's result is the updated same DTO root, never a renderer-supplied DTO.
INITIAL = {
    "defaults": domain.normalize_options().to_dict(),
    "criteria": [dict(c) | {"rubric": dict(c["rubric"])} for c in domain.CRITERIA],
    "credential_status": {"claude": False, "openai": True},
    "catalogue": {"catalogue_id": "synthetic-only", "fingerprint": "a" * 64,
                  "status": "ready", "sources": [],
                  "families": [{"family": f, "total_clauses": 17 + i,
                                "interpreted_clauses": 4 + i, "unsupported_clauses": 13}
                               for i, f in enumerate(domain.FAMILIES)]},
    "guideline": {"id": domain.GUIDELINE_ID, "definitions": dict(domain.LEGAL_DEFINITIONS),
                  "principles": list(domain.CLASSIFICATION_PRINCIPLES)},
}
RESULT, _ = synthetic_result(count=3)
RESULT = deepcopy(RESULT)
RESULT["rationale"] = '<script>window.injected=1</script><img src=x onerror="window.injected=2">' + "긴 한글 근거 " * 600
RESULT["notice_review"]["comparisons"][0]["conditions"][0]["reason"] = '<svg onload="window.injected=3">합성 비교 근거</svg>'
RESULT["documents"].update(status="일부실패", files=[
    {"kind": "reviewer", "reviewer_id": "reviewer-1", "path": "C:/synthetic/의견서.hwpx", "status": "완료", "error": ""},
    {"kind": "summary", "reviewer_id": None, "path": "C:/synthetic/종합.hwpx", "status": "오류", "error": "합성 파일 잠금"},
], errors=["합성 파일 잠금"])


def evidence_result(*, bases=False, statuses=None, target="none", candidates=1, long=False):
    """Validated schema-2 variants, including real enum and question shapes."""
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
 const calls = []; let next = 0; const jobs = {}; const deferred = [];
 const h = window.testHarness = {calls,jobs,deferred,mode:'normal',failNext:null, cancelledPicker:false,result:RESULT};
 const record = (name,args) => {calls.push({name,args}); if(h.failNext===name){h.failNext=null;return {ok:false,data:null,error:{code:'busy',message:'이미 작업이 진행 중입니다.'}};} return null;};
 window.pywebview = {api:{
  get_initial_state:async()=>ok(INITIAL),
  select_path:async purpose=>{record('select_path',[purpose]);return ok(h.cancelledPicker?{cancelled:true,path_token:null,display_name:null}:{cancelled:false,path_token:'token-'+purpose,display_name:'합성 '+purpose});},
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
   if(h.mode==='failed')return ok({job_id,state:'failed',events:[{sequence:1,stage:'preflight',message:'합성 기준 로드 오류',completed:0,total:1}],result:null});
   if(job.polls===1)return ok({job_id,state:'running',events:[{sequence:1,stage:'facts',message:'합성 사실 확인',completed:1,total:4}],result:null});
   const base=h.result;
   const exported={...base,documents:{...base.documents,status:'완료',errors:[],files:base.documents.files.map(f=>({...f,status:'완료',error:''}))}};
   const result=job.type==='batch'?{results:[base],counts:{total:1,completed:1},paths:{output_excel:'C:/synthetic/결과.xlsx'},warnings:['합성 감사 일부 실패'],persistence:{status:'일부실패',checkpoint:'완료',workbook:'완료',audit:'오류'}}:job.type==='export'?exported:base;
   return ok({job_id,state:'done',events:[{sequence:2,stage:'documents',message:'합성 의견서 처리',completed:4,total:4}],result});
  },
  cancel_job:async job_id=>{record('cancel_job',[job_id]);jobs[job_id].cancelled=true;return ok({job_id,state:'cancelled'});}
 }};
})();
"""


class FrontendStaticTests(unittest.TestCase):
    def test_offline_assets_and_safe_renderer(self):
        self.assertTrue(PAGE.exists(), "v15 entry page must exist")
        html = PAGE.read_text(encoding="utf-8")
        script = PAGE.with_name("app.js").read_text(encoding="utf-8")
        css = PAGE.with_name("styles.css").read_text(encoding="utf-8")
        self.assertNotRegex(html, r'(?:src|href)=["\']https?://')
        self.assertNotRegex(script, r'\.innerHTML\s*=|insertAdjacentHTML|eval\(|localStorage|sessionStorage|fetch\(')
        self.assertNotRegex(html, r'(?i)strictness|엄격|관대')
        self.assertIn("prefers-reduced-motion", css)
        font = PAGE.parent / "assets" / "PretendardVariable.woff2"
        self.assertEqual(hashlib.sha256(font.read_bytes()).hexdigest(), "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4")
        self.assertTrue((font.parent / "Pretendard-LICENSE.txt").is_file())


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
        self.page.add_init_script("const INITIAL=" + json.dumps(INITIAL, ensure_ascii=False) + ";const RESULT=" + json.dumps(RESULT, ensure_ascii=False) + ";" + FAKE)
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
        self.menu("과제 검토")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='완료' && !document.querySelector('#start-single').disabled")
        self.wait_result()
        self.page.get_by_role("button", name="고시 대조 근거", exact=True).click()

    def test_navigation_preserves_input_and_all_nine_fields(self):
        for label in domain.TASK_COLUMNS + domain.OPTIONAL_TASK_COLUMNS:
            self.page.get_by_label(label, exact=True).fill("합성 " + label)
        self.menu("일괄 검토")
        self.assertTrue(self.page.get_by_role("heading", name="여러 과제를, 하나의 기준으로.").is_visible())
        self.menu("모델·설정")
        self.assertIn("17", self.page.locator("#catalogue-info").inner_text())
        self.assertIn("자동 조건해석", self.page.locator("#catalogue-info").inner_text())
        self.menu("검토 결과")
        self.assertTrue(self.page.get_by_text("아직 완료된 검토가 없습니다.", exact=True).is_visible())
        self.menu("과제 검토")
        for label in domain.TASK_COLUMNS + domain.OPTIONAL_TASK_COLUMNS:
            self.assertEqual(self.page.get_by_label(label, exact=True).input_value(), "합성 " + label)
        self.assertEqual(self.page.locator('[name="strictness"]').count(), 0)

    def test_modes_auto_payload_and_manual_validation(self):
        self.page.get_by_role("button", name="직접 선택", exact=True).click()
        self.start()
        self.assertEqual(self.calls("start_single"), [])
        self.assertIn("하나 이상", self.page.locator("#message").inner_text())
        self.page.get_by_label("1 군사·안보 활용성", exact=True).check()
        self.page.get_by_label("군사·안보 활용성 가중치", exact=True).fill("1.2")
        self.page.get_by_role("button", name="AI 에이전트 검토 시작", exact=True).click()
        self.assertEqual(self.calls("start_single"), [])
        self.assertIn("평균", self.page.locator("#message").inner_text())
        self.page.get_by_label("군사·안보 활용성 가중치", exact=True).fill("bogus")
        self.page.get_by_role("button", name="자동 선택", exact=True).click()
        self.assertIn("자동선택 시 선택된 모든 항목의 가중치는 1.0으로 적용됩니다.", self.page.locator("#weight-guidance").inner_text())
        self.assertTrue(self.page.get_by_label("군사·안보 활용성 가중치", exact=True).is_disabled())
        self.start()
        self.wait_result()
        options = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual(options["selected_items"], [])
        self.assertEqual(options["weights"], {})
        self.assertNotIn("strictness", options)

    def test_checklist_and_conditional_item_eight(self):
        self.page.get_by_role("button", name="체크리스트", exact=True).click()
        self.page.get_by_role("button", name="직접 선택", exact=True).click()
        item = self.page.get_by_label("8 부처 정책상 관리 필요성", exact=True)
        self.assertTrue(item.is_disabled())
        self.page.get_by_label("부처 세부기준", exact=True).fill("합성 과제별 정책")
        self.assertFalse(item.is_disabled())
        item.check()
        self.assertIn("체크리스트 방식은 점수와 가중치를 사용하지 않습니다.", self.page.locator("#weight-guidance").inner_text())
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
        self.menu("과제 검토")
        self.start()
        self.wait_result()
        opts = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual((opts["provider"], opts["model"], opts["local_base_url"]), ("ollama", "synthetic-local-model", "http://127.0.0.1:11434"))

    def test_job_progress_freeze_cancel_and_busy_error(self):
        self.page.evaluate("testHarness.failNext='start_single'")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#message').textContent.includes('진행 중')")
        self.page.evaluate("testHarness.mode='hold'")
        self.start()
        self.page.wait_for_function("() => document.querySelector('#job-status').textContent.includes('고시 대조')")
        self.assertTrue(self.page.get_by_role("button", name="체크리스트", exact=True).is_disabled())
        self.menu("모델·설정")
        self.assertTrue(self.page.get_by_label("모델 제공자", exact=True).is_disabled())
        self.menu("일괄 검토")
        self.assertTrue(self.page.get_by_role("button", name="일괄 검토 시작", exact=True).is_disabled())
        self.page.get_by_role("button", name="작업 취소", exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#job-state').textContent==='취소'")
        self.assertEqual(len(self.calls("cancel_job")), 1)
        self.menu("과제 검토")
        self.assertFalse(self.page.get_by_role("button", name="체크리스트", exact=True).is_disabled())
        self.assertEqual(self.page.get_by_label("과제명", exact=True).input_value(), "오프라인 합성 과제")

    def test_complete_evidence_and_safe_long_text(self):
        self.start()
        self.wait_result()
        text = self.page.locator("#result-content").inner_text()
        for expected in ("민감과제", "실제 선정 항목", "군사·안보 활용성", "문서 일부 실패", "C:/synthetic/의견서.hwpx", "합성 파일 잠금"):
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
        self.menu("일괄 검토")
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
        self.menu("과제 검토")
        self.page.get_by_label("AI 에이전트 구성", exact=True).select_option("1")
        self.start()
        self.wait_result()
        opts = self.calls("start_single")[0]["args"][0]["options"]
        self.assertEqual((opts["provider"], opts["model"], opts["num_reviewers"]), ("openai", "gpt-6-luna", 1))
        self.menu("모델·설정")
        self.page.get_by_label("모델 제공자", exact=True).select_option("lmstudio")
        self.page.get_by_label("로컬 서버 주소", exact=True).fill("http://127.0.0.1:1234/v1")
        self.page.get_by_label("로컬 모델 식별자", exact=True).fill('<img src=x onerror="window.injected=1">')
        self.menu("과제 검토")
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
        self.menu("과제 검토")
        self.page.get_by_role("button", name="직접 선택", exact=True).click()
        self.page.get_by_label("1 군사·안보 활용성", exact=True).check()
        self.page.get_by_label("군사·안보 활용성 가중치", exact=True).fill("")
        self.page.get_by_label("8 부처 정책상 관리 필요성", exact=True).check()
        self.page.get_by_label("부처 세부기준", exact=True).fill("합성 과제별 부처기준")
        self.page.get_by_label("추가 검토정보", exact=True).fill('<script>window.injected=1</script><svg onload="window.injected=2">')
        self.menu("일괄 검토")
        self.menu("과제 검토")
        self.assertTrue(self.page.get_by_label("8 부처 정책상 관리 필요성", exact=True).is_checked())
        self.start()
        self.wait_result()
        payload = self.calls("start_single")[0]["args"][0]
        self.assertEqual(payload["options"]["weights"], {domain.ITEM_NAMES[0]: 1, domain.ITEM_NAMES[7]: 1})
        self.assertEqual(payload["options"]["ministry_policy"], "합성 공통 부처기준")
        self.assertEqual(payload["task"]["부처 세부기준"], "합성 과제별 부처기준")
        self.assertIsNone(self.page.evaluate("window.injected"))
        self.menu("과제 검토")
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
        capture = ROOT / ".dryforge" / "ui-v15-captures"
        capture.mkdir(parents=True, exist_ok=True)
        tops = self.page.locator(".field-row").first.locator("label").evaluate_all("els=>els.map(el=>el.getBoundingClientRect().top)")
        self.assertEqual(tops[0], tops[1])
        self.page.screenshot(path=str(capture / "input-1366.png"), full_page=True)
        self.menu("모델·설정")
        self.page.screenshot(path=str(capture / "settings-1366.png"), full_page=True)
        self.menu("과제 검토")
        self.start()
        self.wait_result()
        self.page.get_by_role("button", name="고시 대조 근거", exact=True).click()
        self.page.screenshot(path=str(capture / "evidence-1366.png"), full_page=True)
        for width in (820, 600, 390):
            self.page.set_viewport_size({"width": width, "height": 620})
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
            wrap = self.page.locator("#result-content .table-wrap").first
            self.assertTrue(wrap.evaluate("el=>el.scrollWidth>el.clientWidth"))
        self.page.screenshot(path=str(capture / "evidence-390.png"), full_page=True)

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
                    self.assertIn("합성 적용 용도와 예외 조건을 확인해 주세요.", questions.inner_text())
                    self.assertIn("합성 적용 용도 조건", questions.inner_text())
                    self.assertIn("usage", questions.text_content())
                    for raw_key in ("basis:", "predicate_id:", "question:"):
                        self.assertNotIn(raw_key, questions.inner_text())

    def test_long_evidence_folds_preserve_all_content_and_keyboard_scroll(self):
        capture = ROOT / ".dryforge" / "ui-v15-captures"
        capture.mkdir(parents=True, exist_ok=True)
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
            self.page.screenshot(path=str(capture / f"evidence-long-{candidates}-1366.png"), full_page=True)
        self.page.set_viewport_size({"width": 390, "height": 620})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth>innerWidth"))
        self.page.screenshot(path=str(capture / "evidence-long-3-390.png"), full_page=True)
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


if __name__ == "__main__":
    unittest.main()
