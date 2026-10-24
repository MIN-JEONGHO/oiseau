/* Public bridge contract (all calls are window.pywebview.api methods only).
 * Every response: success {ok:true,data:<below>,error:null}; failure
 * {ok:false,data:null,error:{code:string,message:string}}.
 * get_initial_state() => {defaults:RunOptions.to_dict(),
 * criteria:[{id,name,security_refs,sensitive_refs,rubric}],
 * credential_status:{claude:boolean,openai:boolean},
 * catalogue:{catalogue_id,fingerprint,status:'ready',sources,
 * families:[{family,total_clauses,interpreted_clauses,unsupported_clauses}]},
 * guideline:{id,definitions,principles}}. Missing counts remain unconfirmed.
 * select_path('input_excel'|'output_excel'|'output_directory') =>
 * {cancelled,path_token,display_name}; cancellation has both latter values null.
 * save_key(provider,key), delete_key(provider) => {provider,stored:boolean}.
 * start_single({task,options,output_dir_token:null|string}) => {job_id}.
 * start_batch({input_token,output_token,output_dir_token,options,
 * workers:1..8 (default 3),resume:boolean,make_forms:boolean}) => {job_id}.
 * get_job(job_id,after_sequence) => {job_id,state,events,result};
 * cancel_job(job_id) => {job_id,state}. State queued/running/cancelling/done/
 * cancelled/failed. Events {sequence,stage,message,completed,total}; sequence
 * increases, stages preflight/facts/notices/candidate/criteria/agents/summary/
 * documents/persistence. Only sequences after the last consumed one are polled.
 * Single result is the schema-2 DTO root from v15_domain. Batch result is
 * {results,counts?,paths?,warnings?,persistence?}. A partial batch result may
 * accompany cancellation/failure and must remain inspectable.
 * start_export({job_id,task_fingerprint,output_dir_token}) => NEW {job_id}; its
 * completed result is the updated SAME schema-2 DTO root, not a wrapper.
 * Export transmits identifiers only; the server owns the saved DTO.
 * No credentials are returned or retained in options, storage, markup or logs.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const all = query => [...document.querySelectorAll(query)];
  const familyNames = {advanced:'국가첨단전략기술',core:'국가핵심기술',dual_use:'전략물자 · 별표 2 이중용도',military:'전략물자 · 별표 3 군용'};
  const stages = {preflight:'입력·기준 확인',facts:'현재·목표 사실 확인',notices:'고시 대조',candidate:'검토 대상 확인',criteria:'공통항목 대조',agents:'AI 에이전트 검토',summary:'종합 검토',documents:'의견서 생성',persistence:'결과 기록 저장'};
  const jobNames = {queued:'대기',running:'진행',cancelling:'취소 중',done:'완료',cancelled:'취소',failed:'오류'};
  const assessmentNames = {satisfied:'충족',not_satisfied:'불충족',insufficient_info:'정보 부족',not_provided:'미제공'};
  const basisNames = {current:'현재',target:'목표',both:'현재·목표 공통',unspecified:'시점 불명'};
  const sourceNames = {source_id:'출처 식별값',title:'고시명',notice_number:'고시번호',announcement_version:'공고 버전',effective_date:'시행일',retrieved_at:'확인일',official_url:'공식 원문 출처',relative_path:'보존 원문',sha256:'원문 지문',review_status:'원문 검토 상태',coverage:'원문 범위',review_note:'원문 검토 메모',families:'고시 범주'};
  const state = {initial:null,method:'impact',selection:'auto',busy:false,ready:false,initializing:false,active:null,epoch:0,records:[],recordIndex:0,tab:'summary',view:'input',credentials:{claude:false,openai:false},paths:{single:null,input:null,output:null,directory:null,export:null}};
  function node(tag, text, cls) { const element=document.createElement(tag); if(text!==undefined && text!==null) element.textContent=String(text); if(cls)element.className=cls; return element; }
  function append(parent,...children) { children.flat().forEach(child=>{if(child)parent.append(child);});return parent; }
  function clear(element) { element.replaceChildren();return element; }
  function textValue(value) { if(value===null || value===undefined || value==='') return '미확인'; if(Array.isArray(value))return value.map(textValue).join(' · '); if(typeof value==='object')return Object.entries(value).map(([key,val])=>`${key}: ${textValue(val)}`).join('\n'); return String(value); }
  // One display formatter; all scores and assessments are supplied by the DTO.
  function number(value) { return value===null || value===undefined ? '미산출' : String(value); }
  function message(text='') { $('message').textContent=text;$('message').hidden=!text; }
  function fail(error) { message(error && error.message ? error.message : '앱과 연결하지 못했습니다. 작업 상태를 확인한 뒤 다시 시도하세요.'); }
  async function call(name,...args) {
    const api=window.pywebview && window.pywebview.api;
    if(!api || typeof api[name]!=='function')throw new Error('앱 연결을 기다리고 있습니다. 설치된 앱에서 다시 열어주세요.');
    const response=await api[name](...args);
    if(!response || typeof response.ok!=='boolean' || (response.ok && response.error!==null) || (!response.ok && response.data!==null))throw new Error('앱 응답을 확인할 수 없습니다.');
    if(!response.ok)throw new Error(response.error && response.error.message || '요청을 처리하지 못했습니다.');
    return response.data;
  }
  function show(view) {
    state.view=view;all('.screen').forEach(el=>{el.hidden=el.id!==`screen-${view}`;});
    all('.nav [data-view]').forEach(button=>{const selected=button.dataset.view===view;button.classList.toggle('active',selected);if(selected)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
    $('breadcrumb').textContent={input:'과제 검토',batch:'일괄 검토',result:'검토 결과',settings:'모델·설정'}[view];
    if(view==='batch')renderOptionsSummary();window.scrollTo(0,0);
  }
  function metric(parent,label,value) { return append(parent,append(node('div',null,'metric'),node('span',label),node('span',textValue(value)))); }
  function panel(title,cls='') { const element=node('section',null,`panel ${cls}`);element.append(node('h2',title));return element; }
  function paragraph(parent,text,cls='long-text') { if(text!==null && text!==undefined && text!=='')parent.append(node('p',text,cls)); }
  function list(parent,label,values) { parent.append(node('h3',label,'data-label'));if(!values || !values.length){paragraph(parent,'없음','mini-text');return;} const ul=node('ul',null,'data-list');values.forEach(value=>ul.append(node('li',textValue(value))));parent.append(ul); }
  function longText(parent,title,text) { if(!text){metric(parent,title,'미기재');return;}const wrapper=node('div',null,'long-block');wrapper.append(node('h3',title,'data-label'));if(text.length>650){wrapper.append(node('p',text.slice(0,220)+'…','preview'));const details=node('details');append(details,node('summary',`${title} 전문 보기 (${text.length.toLocaleString('ko-KR')}자)`),node('p',text,'long-text'));wrapper.append(details);}else wrapper.append(node('p',text,'long-text'));parent.append(wrapper); }
  function table(parent,headers,rows) {const wrap=node('div',null,'table-wrap');wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label',headers.join(' · '));const t=node('table'),head=node('thead'),tr=node('tr');headers.forEach(h=>{const th=node('th',h);th.scope='col';tr.append(th);});head.append(tr);const body=node('tbody');rows.forEach(row=>{const r=node('tr');row.forEach((value,index)=>{const cell=node('td',null,index===row.length-1?'wide':'');if(value instanceof Node)cell.append(value);else cell.textContent=textValue(value);r.append(cell);});body.append(r);});append(t,head,body);wrap.append(t);parent.append(wrap);return wrap; }
  function basisLabel(basis) {return basisNames[basis] || '시점 미확인';}
  function disclosure(parent,title,cls='') {const details=node('details',null,`evidence-details ${cls}`);details.append(node('summary',title));parent.append(details);return details;}
  function foldText(parent,title,text,cls='long-text',detailsClass='') {
    if(!text)return;
    if(text.length<=650){parent.append(node(cls==='quote'?'blockquote':'p',text,cls));return;}
    const block=node('div',null,'folded-text');block.append(node('p',text.slice(0,180)+'…','preview'));
    const details=disclosure(block,`${title} (${text.length.toLocaleString('ko-KR')}자)`,detailsClass);
    details.append(node(cls==='quote'?'blockquote':'p',text,cls));parent.append(block);
  }
  function factQuote(fact) {const content=node('div',null,'fact-citation');paragraph(content,`${fact.source_field} [${fact.start}–${fact.end}]`,'mini-text');foldText(content,'입력 원문 인용 전문',fact.quote,'long-text','fact-quote');return content;}
  function factRows(facts) {return facts.map(fact=>[basisLabel(fact.basis),fact.fact_id,`${fact.subject} · ${fact.value_text}`,`${number(fact.number)} ${fact.unit||''}`,factQuote(fact)]);}
  function numericPredicates(condition,ids=new Set()) {if(!condition || typeof condition!=='object')return ids;if(condition.type==='numeric')ids.add(condition.predicate_id);else if(condition.type==='not')numericPredicates(condition.child,ids);else if(Array.isArray(condition.children))condition.children.forEach(child=>numericPredicates(child,ids));return ids;}
  function targetAssessment(comparison,clause) {
    if(comparison.target_assessment==='not_provided')return '목표 정보 미제공';
    if(comparison.target_assessment==='satisfied')return '목표 달성 시 해당 가능성';
    const numeric=numericPredicates(clause?.condition);
    if(comparison.target_assessment==='insufficient_info' && comparison.conditions.some(condition=>condition.basis==='target' && condition.assessment==='satisfied' && numeric.has(condition.predicate_id)))return '목표 조건 일부 충족·추가 확인';
    return assessmentNames[comparison.target_assessment] || '대조 결과 미확인';
  }
  function missingQuestions(parent,comparison) {
    const section=node('section',null,'missing-questions');section.append(node('h3','추가 확인','data-label'));
    if(!comparison.missing_information.length)paragraph(section,'없음','mini-text');
    else{const questions=node('ul',null,'data-list');comparison.missing_information.forEach(item=>{const row=node('li');row.append(node('strong',`${basisLabel(item.basis)} · ${item.question}`));const condition=comparison.conditions.find(condition=>condition.predicate_id===item.predicate_id && condition.basis===item.basis);paragraph(row,`연결 조건: ${condition?.condition_text || '조건 확인 필요'} (${item.predicate_id})`,'mini-text');questions.append(row);});section.append(questions);}
    parent.append(section);
  }
  function methodName(method) {return method==='checklist'?'체크리스트':'국가영향 지표';}
  function effectivePolicy() {return $('task-policy').value.trim() || $('common-policy').value.trim();}
  function updateControls() {
    all('[data-method]').forEach(button=>{const chosen=button.dataset.method===state.method;button.classList.toggle('chosen',chosen);button.setAttribute('aria-pressed',String(chosen));button.disabled=state.busy || !state.ready;});
    all('[data-selection]').forEach(button=>{const chosen=button.dataset.selection===state.selection;button.classList.toggle('chosen',chosen);button.setAttribute('aria-pressed',String(chosen));button.disabled=state.busy || !state.ready;});
    $('weight-guidance').textContent=state.method==='checklist'?'체크리스트 방식은 점수와 가중치를 사용하지 않습니다.':state.selection==='auto'?'자동선택 시 선택된 모든 항목의 가중치는 1.0으로 적용됩니다.':'직접 선택할 항목은 하나 이상, 가중치는 각각 0.8~1.2, 선택 항목 평균은 1.0이어야 합니다. 생략한 가중치는 1.0입니다.';
    $('selection-summary').textContent=state.selection==='auto'?'예정: AI가 검토항목을 선택합니다. 실제 선정 항목은 완료 결과에 표시됩니다.':'예정: 아래에서 직접 선택한 항목을 검토합니다. 실제 선정 항목은 완료 결과와 대조하세요.';
    (state.initial?.criteria || []).forEach(criterion=>{const check=$(`criterion-${criterion.id}`),weight=$(`weight-${criterion.id}`);const blocked=criterion.id===8 && !effectivePolicy();if(blocked)check.checked=false;check.disabled=state.busy || state.selection==='auto' || blocked;weight.disabled=state.busy || state.method==='checklist' || state.selection==='auto' || !check.checked;weight.readOnly=state.selection==='auto';if(state.selection==='auto')weight.value='1.0';});
    all('[data-score-rubric]').forEach(el=>{el.hidden=state.method==='checklist';});all('#criteria-controls summary').forEach(el=>{el.textContent=state.method==='checklist'?'관련 조항':'조항·점수 기준';});
    $('reviewer-description').textContent=$('reviewer-count').value==='1'?'AI 기술분야 전문가의 독립 의견과 종합 검토':'AI 기술분야 · 연구보안 · 기술사업화 전문가의 독립 의견과 종합 검토';
    $('model-summary').textContent=currentModel();renderOptionsSummary();
  }
  function renderCriteriaControls() {
    const area=clear($('criteria-controls'));
    state.initial.criteria.forEach(c=>{const row=node('div',null,'weight-row'),choice=node('div',null,'criteria-choice'),label=node('label');const check=node('input');check.type='checkbox';check.id=`criterion-${c.id}`;check.setAttribute('aria-label',`${c.id} ${c.name}`);check.addEventListener('change',updateControls);append(label,check,node('span',`${c.id} ${c.name}`));choice.append(label);const details=node('details');details.append(node('summary','조항·점수 기준'));list(details,'보안과제 관련 조항',c.security_refs);list(details,'민감과제 관련 조항',c.sensitive_refs);const rubric=node('ul',null,'data-list');rubric.dataset.scoreRubric='';Object.entries(c.rubric||{}).forEach(([score,description])=>rubric.append(node('li',`${score}점 · ${description}`)));details.append(rubric);choice.append(details);const weight=node('input');weight.id=`weight-${c.id}`;weight.type='text';weight.inputMode='decimal';weight.value='1.0';weight.setAttribute('aria-label',`${c.name} 가중치`);append(row,choice,weight);area.append(row);});
  }
  function currentModel() { const provider=$('provider').value;return provider==='claude'?'claude-sonnet-5-5':provider==='openai'?'gpt-6-luna':$('local-model').value.trim() || '로컬 모델 식별자 미입력'; }
  function renderProvider() { const provider=$('provider').value,local=provider==='ollama' || provider==='lmstudio';$('cloud-settings').hidden=local;$('local-settings').hidden=!local;$('cloud-model').value=local?'':currentModel();$('key-status').textContent=state.credentials[provider]?'API 키 저장됨 · 저장된 키 재사용':'API 키 저장되지 않음';$('model-summary').textContent=currentModel();renderOptionsSummary(); }
  function renderOptionsSummary() {const area=clear($('batch-options-summary'));metric(area,'분류 방식',methodName(state.method));metric(area,'항목 선택',state.selection==='auto'?'자동 선택 · 실제 항목은 결과에서 확인':'직접 선택');metric(area,'AI 에이전트',`${$('reviewer-count').value}개`);metric(area,'모델',currentModel());metric(area,'고시 기준본',state.initial?.catalogue?.catalogue_id || '미확인');}
  function buildOptions() {
    const provider=$('provider').value;const selected=state.selection==='manual'?state.initial.criteria.filter(c=>$(`criterion-${c.id}`).checked).map(c=>c.name):[];
    if(state.selection==='manual' && !selected.length)throw new Error('직접 선택할 검토항목을 하나 이상 선택하세요.');
    if(selected.includes(state.initial.criteria.find(c=>c.id===8)?.name) && !effectivePolicy())throw new Error('8번 항목에는 실제 부처 세부기준이 필요합니다.');
    const weights={};if(state.method==='impact' && state.selection==='manual'){
      state.initial.criteria.filter(c=>selected.includes(c.name)).forEach(c=>{const value=$(`weight-${c.id}`).value.trim();const parsed=value===''?1:Number(value);if(!Number.isFinite(parsed) || parsed<0.8 || parsed>1.2)throw new Error('가중치는 0.8~1.2 범위의 숫자여야 합니다.');weights[c.name]=parsed;});
      const average=Object.values(weights).reduce((sum,value)=>sum+value,0)/selected.length;if(Math.abs(average-1)>0.000001)throw new Error('선택된 항목의 가중치 평균은 1.0이어야 합니다.');
    }
    const local=provider==='ollama' || provider==='lmstudio';let base=local?$('local-url').value.trim():'';
    if(local){if(!$('local-model').value.trim())throw new Error('로컬 모델 식별자를 입력하세요.');try{const url=new URL(base);if(!['http:','https:'].includes(url.protocol)||!url.hostname||url.username||url.password||url.search||url.hash)throw new Error();}catch(_){throw new Error('로컬 서버 주소는 인증정보·쿼리 없는 HTTP(S) 주소로 입력하세요.');}}
    const defaults=state.initial.defaults;
    return {method:state.method,provider,model:currentModel(),num_reviewers:Number($('reviewer-count').value),selection_mode:state.selection,selected_items:selected,weights,ministry_policy:$('common-policy').value.trim(),local_base_url:base,guideline_id:defaults.guideline_id,catalogue_fingerprint:state.initial.catalogue.fingerprint,comparison_rules_version:defaults.comparison_rules_version};
  }
  function busy(value) {
    state.busy=value;const ids=['provider','api-key','save-key','delete-key','local-url','local-model','common-policy','reviewer-count','batch-workers','batch-resume','batch-forms','start-single','start-batch','single-directory','batch-input','batch-output','batch-directory','start-export','export-directory'];
    ids.forEach(id=>{$(id).disabled=value || !state.ready;});all('[data-task]').forEach(el=>{el.disabled=value||!state.ready;});updateControls();$('cancel-job').disabled=!state.active || state.active.state==='cancelling';
  }
  async function pick(purpose,slot,label) {if(state.busy)return;try{const result=await call('select_path',purpose);if(result.cancelled)return;if(typeof result.path_token!=='string' || !result.path_token)throw new Error('선택한 경로를 확인할 수 없습니다.');state.paths[slot]=result.path_token;$(label).textContent=result.display_name || '경로 선택됨';if(purpose==='output_directory'){state.paths.export=result.path_token;$('export-directory-name').textContent=result.display_name || '경로 선택됨';}message();}catch(error){fail(error);} }
  async function saveKey() {if(state.busy)return;const provider=$('provider').value;let key=$('api-key').value.trim();if(!key){message('새 API 키를 입력하세요.');return;}try{const pending=call('save_key',provider,key);$('api-key').value='';key='';const saved=await pending;state.credentials[saved.provider]=saved.stored;renderProvider();message('API 키를 보안 저장소에 저장했습니다.');}catch(error){fail(error);}finally{$('api-key').value='';key='';} }
  async function deleteKey() {if(state.busy)return;$('api-key').value='';try{const saved=await call('delete_key',$('provider').value);state.credentials[saved.provider]=saved.stored;renderProvider();message('저장된 API 키를 삭제했습니다.');}catch(error){fail(error);} }
  function step(stage) {const index=['facts','preflight'].includes(stage)?0:['notices','candidate','criteria'].includes(stage)?1:['agents','summary'].includes(stage)?2:3;all('#review-steps li').forEach((li,i)=>li.classList.toggle('current',i===index));}
  function consumeEvents(active,events) { const sorted=(events||[]).filter(event=>Number.isInteger(event.sequence) && event.sequence>active.sequence).sort((a,b)=>a.sequence-b.sequence);for(const event of sorted){if(event.sequence<=active.sequence)continue;active.sequence=event.sequence;$('job-status').textContent=`${stages[event.stage]||'검토 진행'} · ${event.message||''}`;const progress=$('job-progress');if(Number.isFinite(event.total)&&event.total>0&&Number.isFinite(event.completed)){progress.max=event.total;progress.value=event.completed;}else progress.removeAttribute('value');$('job-events').append(node('li',`${stages[event.stage]||'검토 진행'} · ${event.message||''}`));step(event.stage);} }
  async function start(kind) {
    if(state.busy || !state.ready)return;
    let payload;try{
      if(kind==='export'){const record=state.records[state.recordIndex];if(!record)throw new Error('완료된 검토 결과를 선택하세요.');if(!state.paths.export){await pick('output_directory','export','export-directory-name');if(!state.paths.export)return;}payload={job_id:record.jobId,task_fingerprint:record.dto.task_fingerprint,output_dir_token:state.paths.export};}
      else{const options=buildOptions();if(kind==='single'){const task={};all('[data-task]').forEach(el=>{task[el.dataset.task]=el.value;});if(!task['과제명'].trim())throw new Error('과제명은 필수입니다.');payload={task,options,output_dir_token:state.paths.single};}
        else{const workers=Number($('batch-workers').value);if(!Number.isInteger(workers)||workers<1||workers>8)throw new Error('동시 처리 수는 1~8의 정수여야 합니다.');if(!state.paths.input || !state.paths.output)throw new Error('입력 엑셀과 결과 엑셀을 선택하세요.');payload={input_token:state.paths.input,output_token:state.paths.output,output_dir_token:state.paths.directory,options,workers,resume:$('batch-resume').checked,make_forms:$('batch-forms').checked};}}
      message();busy(true);const started=await call(`start_${kind}`,payload);if(typeof started.job_id!=='string')throw new Error('작업 식별값을 확인할 수 없습니다.');
      const active={id:started.job_id,kind,state:'queued',sequence:0,epoch:++state.epoch,exportRecord:kind==='export'?state.records[state.recordIndex]:null};state.active=active;$('job-panel').hidden=false;$('job-state').textContent='대기';$('job-status').textContent='작업을 준비하고 있습니다.';clear($('job-events'));$('job-progress').removeAttribute('value');busy(true);poll(active);
    }catch(error){state.active=null;busy(false);fail(error);}
  }
  function isCurrent(active) {return state.active===active && state.epoch===active.epoch;}
  async function poll(active) {
    try{const job=await call('get_job',active.id,active.sequence);if(!isCurrent(active)||job.job_id!==active.id)return;active.state=job.state;consumeEvents(active,job.events);$('job-state').textContent=jobNames[job.state]||'미확인';
      if(['done','cancelled','failed'].includes(job.state)){finish(active,job);return;}
      $('cancel-job').disabled=job.state==='cancelling';setTimeout(()=>{if(isCurrent(active))poll(active);},350);
    }catch(error){if(!isCurrent(active))return;active.state='unknown';$('job-state').textContent='상태 확인 오류';$('job-status').textContent='작업은 진행 중일 수 있습니다. 상태를 다시 확인합니다.';fail(error);setTimeout(()=>{if(isCurrent(active))poll(active);},1200);}
  }
  function finish(active,job) {
    if(job.result){if(active.kind==='batch'){renderBatchReport(job.result);if(Array.isArray(job.result.results))job.result.results.forEach(dto=>saveResult(dto,active.id));}else saveResult(job.result,active.id,active.exportRecord);}
    state.active=null;state.epoch++;busy(false);$('cancel-job').disabled=true;
    if(job.state==='done'){if(!job.result)message('작업은 완료되었으나 결과가 전달되지 않았습니다.');else if(state.records.length){state.tab='summary';renderResult();show('result');}}
    if(job.state==='cancelled')message('작업이 취소되었습니다. 전달된 완료 결과는 보존했습니다.');
    if(job.state==='failed')message('작업 중 오류가 발생했습니다. 진행 기록과 저장 상태를 확인하세요.');
  }
  async function cancel() {const active=state.active;if(!active || active.state==='cancelling')return;active.state='cancelling';$('job-state').textContent='취소 중';$('cancel-job').disabled=true;try{const response=await call('cancel_job',active.id);if(!isCurrent(active)||response.job_id!==active.id)return;if(['cancelled','failed','done'].includes(response.state)){
      // The cancellation response invalidates an outstanding old poll. Retrieve
      // the terminal snapshot once so completed batch rows stay available.
      active.epoch=++state.epoch;const terminalEpoch=active.epoch;$('job-state').textContent=jobNames[response.state];finish(active,{...response,result:null});
      const snapshot=await call('get_job',active.id,active.sequence);
      if(state.active || state.epoch!==terminalEpoch+1 || snapshot.job_id!==active.id)return;
      if(snapshot.result){if(active.kind==='batch'){renderBatchReport(snapshot.result);(snapshot.result.results||[]).forEach(dto=>saveResult(dto,active.id));}else saveResult(snapshot.result,active.id,active.exportRecord);renderResult();}
    }else{active.state=response.state;$('job-state').textContent=jobNames[response.state]||'취소 중';}}
    catch(error){if(!isCurrent(active))return;fail(error);active.state='running';$('cancel-job').disabled=false;poll(active);} }
  function saveResult(dto,jobId,replaced) {if(!dto || dto.schema_version!==2 || !dto.task_fingerprint){message('저장 결과의 형식을 확인할 수 없습니다.');return;}if(replaced){const index=state.records.indexOf(replaced);if(index>=0){state.records[index]={dto,jobId};state.recordIndex=index;return;}}state.records.push({dto,jobId});state.recordIndex=state.records.length-1;}
  function renderBatchReport(report) {const area=clear($('batch-report')),p=panel('일괄 검토 · 저장 현황');if(report.counts)Object.entries(report.counts).forEach(([key,value])=>metric(p,{total:'전체',completed:'완료',failed:'오류',cancelled:'취소',needs_review:'검토 필요'}[key]||key,value));if(report.paths)Object.entries(report.paths).forEach(([key,value])=>metric(p,{output_excel:'결과 엑셀',input_excel:'입력 엑셀',checkpoint:'중간 저장',audit:'감사 기록',output_dir:'의견서 폴더'}[key]||key,value));if(report.persistence)renderPersistence(p,report.persistence);list(p,'저장 경고',report.warnings||[]);area.append(p);}
  function renderPersistence(parent,persistence) {const labels={status:'결과 기록 상태',checkpoint:'중간 저장',workbook:'결과 엑셀',audit:'감사 기록'};Object.entries(persistence).forEach(([key,value])=>{if(key==='warnings')list(parent,'기록 경고',value);else metric(parent,labels[key]||key,value);});}
  function documents(parent,dto) {const p=panel(dto.documents.status==='일부실패'?'문서 일부 실패':'의견서 저장 상태');metric(p,'문서 상태',dto.documents.status);metric(p,'예정 의견서 수',dto.documents.expected_files);if(dto.documents.files.length)table(p,['구분','AI 에이전트','저장 상태','저장 경로','오류'],dto.documents.files.map(file=>[file.kind==='summary'?'AI 종합 검토의견서':'에이전트별 검토의견서',file.reviewer_id,file.status,file.path,file.error||'없음']));list(p,'문서 생성 오류',dto.documents.errors);parent.append(p);}
  function renderSummary(parent,dto) {const p=panel('종합 검토');metric(p,'과제명',dto.task_name);metric(p,'분류 방식',methodName(dto.method));metric(p,'분류 상태',dto.status);metric(p,'AI 참고 등급',dto.final_grade || '등급 미확정');metric(p,'신뢰도',dto.confidence);if(dto.method==='impact'){metric(p,'국가영향 지표 평균',number(dto.overall_avg));metric(p,'수치 구간 참고 등급',dto.rule_grade);}else paragraph(p,'체크리스트 방식은 점수와 가중치를 사용하지 않습니다.','notice');metric(p,'검토 대상',dto.candidate.is_candidate===true?'검토 대상':dto.candidate.is_candidate===false?'후보 제외':'확인 필요');longText(p,'검토 대상 근거',dto.candidate.reason);longText(p,'검토 대상 불확실성',dto.candidate.uncertainty);list(p,'실제 선정 항목',dto.selected_items);if(dto.method==='impact')table(p,['실제 선정 항목','적용 가중치'],dto.selected_items.map(item=>[item,number(dto.weights[item])]));longText(p,'종합 근거',dto.rationale);longText(p,'논의할 사항',dto.discussion_points);list(p,'미완료·추가 확인 사유',dto.unresolved_reasons);parent.append(p);documents(parent,dto);const snapshot=panel('실행 당시 입력·기준');Object.entries(dto.task_snapshot).forEach(([key,value])=>longText(snapshot,key,value));metric(snapshot,'모델',`${dto.provider} · ${dto.model}`);metric(snapshot,'가이드라인',dto.guideline_id);metric(snapshot,'고시 기준 지문',dto.catalogue_fingerprint);metric(snapshot,'입력 지문',dto.task_fingerprint);metric(snapshot,'설정 지문',dto.options_fingerprint);parent.append(snapshot);}
  function renderCriteria(parent,dto) {const p=panel('공통 검토항목 대조');list(p,'실제 선정 항목',dto.selected_items);paragraph(p,dto.method==='checklist'?'체크리스트 방식은 점수와 가중치를 사용하지 않습니다.':'점수와 가중치는 평가 결과의 값을 그대로 표시합니다.','notice');table(p,['공통항목','판단','관련 조항','대조한 기준','근거·전문 검토'],dto.criteria.map(c=>[c.item,c.level,c.law_refs,c.matched_reference||'없음',`${c.note}\n${c.needs_expert_review?'추가 전문 검토 필요':'전문 검토 필요 표시 없음'}`]));if(dto.method==='impact')table(p,['실제 선정 항목','가중치'],dto.selected_items.map(item=>[item,number(dto.weights[item])]));parent.append(p);}
  function sourceRecord(parent,source) {const record=node('section',null,'source-record');record.append(node('h3',source.title || source.source_id));Object.entries(sourceNames).forEach(([key,label])=>{if(key in source)append(record,node('p',`${label} · ${textValue(source[key])}`,key==='sha256'?'fingerprint':''));});parent.append(record);}
  function renderEvidence(parent,dto) {
    const review=dto.notice_review,overview=panel('고시 자동 대조 범위');
    metric(overview,'고시 기준본',review.catalogue_id);
    metric(overview,'대조 상태',{complete:'전체 탐색 완료',needs_info:'추가 확인 필요',error:'오류'}[review.status]||'상태 미확인');
    paragraph(overview,'자동 탐색 완료는 판단 정확성을 보증하지 않습니다. ‘후보 없음(자동 탐색)’은 공식적인 비해당 판정이 아닙니다. 복잡한 적용·예외 조건은 추가 전문 검토가 필요합니다.','notice');
    const inventory=review.catalogue_manifest?.clause_inventory;
    const familyTable=table(overview,['고시 범주','탐색 상태','확인 범위','후보 탐색'],review.families.map(family=>{
      const complete=family.status==='complete';
      const total=Array.isArray(inventory)?inventory.filter(clause=>clause.family===family.family).length:null;
      const remaining=total===null?null:total-family.screened_ids.length;
      const status={complete:'전체 탐색 완료',partial:'일부 탐색 · 탐색 미완료',not_run:'시작 전 · 탐색 미완료',error:'탐색 오류 · 탐색 미완료'}[family.status]||'탐색 상태 미확인 · 추가 확인';
      const candidate=family.candidate_ids.length?`${family.candidate_ids.length}개 후보${complete?'':' · 추가 확인'}`:complete?'후보 없음(자동 탐색)':'후보 여부 미확인 · 추가 확인';
      return [familyNames[family.family]||family.family,status,`대조 ${family.screened_ids.length} / 전체 ${total===null?'미확인':total}\n남은 ${remaining===null?'범위 미확인':`${remaining}개`}`,candidate];
    }));
    familyTable.classList.add('family-table');
    familyTable.querySelectorAll('tbody tr').forEach((row,index)=>{row.classList.add('family-summary');row.dataset.family=review.families[index].family;});
    review.families.forEach(family=>{
      const title=familyNames[family.family]||family.family;
      if(family.candidate_ids.length){const candidates=disclosure(overview,`${title} · 후보 조항 ${family.candidate_ids.length}개`,'family-candidates');list(candidates,'후보 조항 식별값',family.candidate_ids);}
      if(family.excluded.length){const excluded=disclosure(overview,`${title} · 후보 제외 근거 ${family.excluded.length}개`,'excluded-details');excluded.dataset.family=family.family;list(excluded,'전체 제외 근거',family.excluded.map(item=>`${item.clause_id} · ${item.reason}`));}
      if(family.errors.length)list(overview,`${title} · 탐색 오류`,family.errors);
    });
    if(review.blocking_reasons.length)list(overview,'검토를 막는 미확인 사항',review.blocking_reasons);
    const identity=disclosure(overview,'검토 기준본 식별·지문');metric(identity,'고시 기준본',review.catalogue_id);metric(identity,'기준 지문',review.catalogue_fingerprint);
    parent.append(overview);
    const factsById=new Map(review.facts.map(fact=>[fact.fact_id,fact]));
    review.comparisons.forEach(comparison=>{
      const clause=review.clause_snapshots.find(c=>c.clause_id===comparison.clause_id),p=node('section',null,'panel evidence'),head=node('div',null,'evidence-header'),heading=node('div');
      append(heading,node('div',`${familyNames[comparison.family]||comparison.family} · ${comparison.clause_id}`,'overline'),node('h2',clause?.title||comparison.clause_id));
      append(head,heading,node('span',`현재 · ${assessmentNames[comparison.current_assessment]||'미확인'}`,'status-chip'));p.append(head);
      const body=node('div',null,'evidence-body');
      // Clause -> original conditions -> provided facts -> result -> evidence/questions.
      body.append(node('h3','고시 조항','data-label'));
      if(clause){
        paragraph(body,`${clause.code||'원문에 번호 없음'} · ${clause.field} · ${clause.source_anchor}`,'mini-text');
        foldText(body,'고시 원문 전문',clause.text,'quote','clause-original');
        if(clause.qualifier_refs.length){const refs=disclosure(body,`함께 적용하는 연결 조항 ${clause.qualifier_refs.length}개`,'candidate-references');list(refs,'연결 조항 식별값',clause.qualifier_refs);paragraph(refs,'연결 조항의 원문은 아래 ‘연결된 참조조항 원문’에서 모두 확인할 수 있습니다.','mini-text');}
      }
      body.append(node('h3','원문 조건','data-label'));
      Array.from(new Set(comparison.conditions.map(condition=>`${condition.condition_text} · ${condition.source_anchor}`))).forEach(condition=>foldText(body,'원문 조건 전문',condition));
      const provided=node('section');provided.dataset.factTable='provided';provided.append(node('h3','제공한 사양·인용','data-label'));
      const referenced=Array.from(new Set(comparison.conditions.flatMap(condition=>condition.fact_ids))).map(id=>factsById.get(id)).filter(Boolean);
      if(referenced.length)table(provided,['구분','사실 식별값','제공 사양','수치·단위','입력 위치·원문 인용'],factRows(referenced));else paragraph(provided,'대조 가능한 사양이 제공되지 않았습니다.','mini-text');
      body.append(provided);body.append(node('h3','조건별 결과','data-label'));
      table(body,['구분','원문 조건','변환한 사양','결과','근거·인용 위치'],comparison.conditions.map(condition=>{
        const evidence=node('div');foldText(evidence,'대조 근거 전문',condition.reason);paragraph(evidence,`${condition.source_anchor}\n사실 연결: ${condition.fact_ids.join(', ')||'없음'}`,'mini-text');
        const original=node('div');foldText(original,'원문 조건 전문',condition.condition_text);
        return [basisLabel(condition.basis),original,`${number(condition.normalized_value)} ${condition.normalized_unit||''}`,assessmentNames[condition.assessment]||'미확인',evidence];
      }));
      metric(body,'현재 사양 대조 결과',assessmentNames[comparison.current_assessment]||'대조 결과 미확인');
      append(body,append(node('div',null,'metric target-assessment'),node('span','목표 사양 대조 결과'),node('strong',targetAssessment(comparison,clause))));
      if(comparison.target_assessment!=='not_provided')paragraph(body,'목표 조건의 충족은 현재 확보한 기술이나 공식 지정의 확정이 아닙니다.','target');
      longText(body,'대조 근거',comparison.rationale);missingQuestions(body,comparison);
      list(body,'영향을 검토할 공통항목',comparison.affected_items.map(id=>state.initial.criteria.find(c=>c.id===id)?.name||id));
      const details=disclosure(body,'대조·출처 식별값');metric(details,'대조 식별값',comparison.comparison_id);metric(details,'출처 식별값',comparison.source_id);
      p.append(body);parent.append(p);
    });
    const appendix=panel('전체 근거·원문 확인');
    const facts=disclosure(appendix,`추출한 현재·목표 사실 전체 (${review.facts.length}건)`,'all-facts');
    table(facts,['구분','사실 식별값','사양·값','수치·단위','입력 위치·원문 인용'],factRows(review.facts));
    const remaining=review.clause_snapshots.filter(clause=>!review.comparisons.some(comparison=>comparison.clause_id===clause.clause_id));
    if(remaining.length){const references=disclosure(appendix,`연결된 참조조항 원문 (${remaining.length}개)`,'reference-clauses');remaining.forEach(clause=>{const reference=node('section',null,'reference-record');reference.append(node('h3',`${clause.clause_id} · ${clause.title}`));paragraph(reference,`${clause.code||'원문에 번호 없음'} · ${clause.source_anchor}`,'mini-text');foldText(reference,'참조조항 원문 전문',clause.text,'quote');list(reference,'이 조항에서 다시 연결하는 조항',clause.qualifier_refs);references.append(reference);});}
    const sources=disclosure(appendix,`공식 원문·버전 상세 (${review.sources.length}개 출처)`,'evidence-sources');review.sources.forEach(source=>sourceRecord(sources,source));
    parent.append(appendix);
  }
  function renderAgents(parent,dto) {dto.reviewers.forEach(reviewer=>{const p=panel(reviewer.persona);metric(p,'독립 의견 상태',reviewer.status);metric(p,'참고 등급',reviewer.grade);metric(p,'신뢰도',reviewer.confidence);if(dto.method==='impact')metric(p,'개인 국가영향 지표',number(reviewer.reviewer_score));longText(p,'개인 근거',reviewer.rationale);longText(p,'개인 논의할 사항',reviewer.discussion_points);list(p,'개인 미완료·추가 확인 사유',reviewer.unresolved_reasons);table(p,dto.method==='impact'?['항목','판단','점수','관련 조항','개인 근거']:['항목','판단','관련 조항','개인 근거'],reviewer.item_reviews.map(item=>dto.method==='impact'?[item.item,item.level,number(reviewer.scores[item.item]),item.law_refs,item.note]:[item.item,item.level,item.law_refs,item.note]));list(p,'고시 대조에 대한 개인 의견',reviewer.notice_comments.map(comment=>`${comment.comparison_id}\n${comment.comment}`));metric(p,'AI 에이전트 식별값',reviewer.reviewer_id);parent.append(p);});if(!dto.reviewers.length){parent.append(panel('AI 에이전트 개별 검토 미실시'));} }
  function renderResult() {const record=state.records[state.recordIndex];if(!record)return;const dto=record.dto;$('empty-result').hidden=true;$('saved-results').hidden=false;const picker=clear($('result-picker'));state.records.forEach((item,index)=>{const option=node('option',`${index+1}. ${item.dto.task_name} · ${item.dto.status}`);option.value=String(index);picker.append(option);});picker.value=String(state.recordIndex);$('result-heading').textContent=dto.task_name;$('result-status').textContent=`${dto.status==='검토필요'?'검토 필요':dto.status} · ${methodName(dto.method)} · ${dto.reviewers.length}개 AI 에이전트`;$('result-grade').textContent=dto.final_grade||'등급 미확정';all('[data-result-tab]').forEach(button=>{const chosen=button.dataset.resultTab===state.tab;button.classList.toggle('chosen',chosen);button.setAttribute('aria-pressed',String(chosen));});const parent=clear($('result-content'));({summary:renderSummary,evidence:renderEvidence,criteria:renderCriteria,agents:renderAgents}[state.tab])(parent,dto);}
  function renderCatalogue() {const catalogue=state.initial.catalogue,area=clear($('catalogue-info'));metric(area,'기준본',catalogue.catalogue_id);metric(area,'상태',catalogue.status==='ready'?'준비됨':catalogue.status);catalogue.families.forEach(family=>{const p=node('section',null,'source-record');p.append(node('h3',familyNames[family.family]||family.family));metric(p,'보존 원문 조항',family.total_clauses??'미확인');metric(p,'자동 조건해석 지원',family.interpreted_clauses??'미확인');metric(p,'추가 전문 검토 범위',family.unsupported_clauses??'미확인');area.append(p);});paragraph(area,'보존 원문 조항 수와 자동 조건해석 지원 수를 구분합니다. 수치는 실제 기준본의 메타정보입니다. 집계가 없으면 미확인으로 표시합니다.','mini-text');metric(area,'기준 지문',catalogue.fingerprint);catalogue.sources.forEach(source=>sourceRecord(area,source));}
  function openGuideline() {const guideline=state.initial?.guideline;if(!guideline)return;const area=clear($('guideline-content'));Object.entries(guideline.definitions).forEach(([grade,definition])=>append(area,node('h3',grade),node('p',definition)));list(area,'분류 원칙',guideline.principles);metric(area,'가이드라인 식별값',guideline.id);$('guideline-dialog').showModal();}
  async function initialize() {if(state.ready || state.initializing)return;state.initializing=true;try{const initial=await call('get_initial_state');if(!initial.defaults||!Array.isArray(initial.criteria)||!initial.catalogue||!Array.isArray(initial.catalogue.families)||!initial.credential_status||!initial.guideline)throw new Error('앱의 초기 설정을 확인할 수 없습니다.');state.initial=initial;state.credentials={...initial.credential_status};state.method=initial.defaults.method;state.selection=initial.defaults.selection_mode;$('provider').value=initial.defaults.provider;$('reviewer-count').value=String(initial.defaults.num_reviewers);$('common-policy').value=initial.defaults.ministry_policy||'';$('local-url').value=initial.defaults.local_base_url||'';if(['ollama','lmstudio'].includes(initial.defaults.provider))$('local-model').value=initial.defaults.model;renderCriteriaControls();initial.criteria.forEach(c=>{if(initial.defaults.selected_items?.includes(c.name))$(`criterion-${c.id}`).checked=true;const weight=initial.defaults.weights?.[c.name];if(weight!==undefined)$(`weight-${c.id}`).value=String(weight);});state.ready=true;renderProvider();renderCatalogue();busy(false);$('connection-status').textContent='고시 기준본 연결됨';document.body.dataset.ready='true';message();}catch(error){$('connection-status').textContent='앱 연결 필요';fail(error);busy(false);}finally{state.initializing=false;} }
  all('[data-view]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.view)));
  all('[data-method]').forEach(button=>button.addEventListener('click',()=>{state.method=button.dataset.method;updateControls();}));all('[data-selection]').forEach(button=>button.addEventListener('click',()=>{state.selection=button.dataset.selection;updateControls();}));
  ['task-policy','common-policy','reviewer-count','local-model','local-url'].forEach(id=>$(id).addEventListener('input',updateControls));$('provider').addEventListener('change',()=>{$('api-key').value='';renderProvider();});
  $('save-key').addEventListener('click',saveKey);$('delete-key').addEventListener('click',deleteKey);$('start-single').addEventListener('click',()=>start('single'));$('start-batch').addEventListener('click',()=>start('batch'));$('start-export').addEventListener('click',()=>start('export'));$('cancel-job').addEventListener('click',cancel);
  $('single-directory').addEventListener('click',()=>pick('output_directory','single','single-directory-name'));$('batch-input').addEventListener('click',()=>pick('input_excel','input','batch-input-name'));$('batch-output').addEventListener('click',()=>pick('output_excel','output','batch-output-name'));$('batch-directory').addEventListener('click',()=>pick('output_directory','directory','batch-directory-name'));$('export-directory').addEventListener('click',()=>pick('output_directory','export','export-directory-name'));
  all('[data-result-tab]').forEach(button=>button.addEventListener('click',()=>{state.tab=button.dataset.resultTab;renderResult();}));$('result-picker').addEventListener('change',()=>{state.recordIndex=Number($('result-picker').value);renderResult();});$('open-guideline').addEventListener('click',openGuideline);$('settings-guideline').addEventListener('click',openGuideline);$('close-guideline').addEventListener('click',()=>$('guideline-dialog').close());
  window.addEventListener('pywebviewready',initialize);busy(false);if(window.pywebview?.api)initialize();
})();
