/* 연구보안 등급분류 분류기준(고시) 검토(옛 이름: 고시 수준 검토) 화면 스크립트. 표시만 하고 판정·집계 계산과 숫자 해석은 하지 않는다.
 *
 * 연결 약속(bridge.PUBLIC_METHODS, 모두 window.pywebview.api의 함수): 응답은 성공 {ok:true,data}
 * 또는 실패 {ok:false,code,message}. 화면은 message를 그대로 보이고 스스로 판단하지 않는다.
 *  get_initial_state() => {program:{name,version}, catalogue:{catalogue_id,fingerprint,item_count,notices},
 *    table:{fingerprint,near_percent,record_count}, families:[{id,label,count}],
 *    providers:[{id,default_model,needs_key,default_base_url}], key_state:{claude,openai:{has_key,stored,source,warning}},
 *    settings:{provider,model,base_url}, note, supported_extensions, workers, job}
 *  select_path(kind) => {cancelled,token,name}  (kind: attachment|batch_input|save_report|save_template)
 *  extract_attachment(token) => {name,kind,page_count,warnings,text,text_length,sections:[{heading,start,end,body}]}
 *    실패 코드: unsupported_format|no_text|encrypted|corrupt|not_found
 *  estimate(families,is_batch,row_count) => {families,count,per_task:[low,high],total:[low,high]}
 *  run_single({title,final_goal,rnd_content,utilization,excerpt,attachment_name,rnd_stage,gov_fund}, families)
 *    => 작업 스냅샷 + option_warnings:[{row_number,field,value,message}]  (지원금 글은 Python이 확인)
 *  read_batch(token) => {name,count,total_rows,blank_rows,excluded:[{row_number,reason,value}],
 *    option_warnings:[{row_number,field,value,message}], rows:[{row_number,title,rnd_stage}]}
 *  run_batch(token, families) => 작업 스냅샷;  cancel() => {state}
 *  poll_progress(after_sequence) => {state,kind,events:[{sequence,stage,label,message,completed,total}],result,message,completed,total}
 *    state: idle|running|cancelling|done|cancelled|failed. result는 끝난 뒤에만.
 *  save_report(token,'single'|'batch') => {saved,name,which,count};  save_template(token) => {saved,name}
 *  get_key_state() / save_key(provider,key) / delete_key(provider) => 키 유무만(원문 없음)
 *  set_model_settings(provider,model,base_url) => 실제 쓰는 {provider,model,base_url}
 *  고시 검색(읽기만 함. 검토 작업 중에도 응답):
 *  get_initial_state().search => {available,message,status,filters:[{id,label}],default_filter,max_query_chars,
 *    default_limit,footer,similar_notice}
 *  search_notices(query,family,limit,offset,similar_offset) => {mode,family,family_label,
 *    results:{items,total,offset,limit,remaining,has_more,visible,empty_message,next_offset}, similar:{...같음, notice},
 *    status:{dictionary:{available,reason,reviewed_on,notice},semantic:{state,available,reason,notice}}, footer, empty_message}
 *    item: {clause_id,family,family_label,code,title,field,reason,reasons,snippet,highlights:[[시작,끝]]}  (점수 없음)
 *  get_notice_detail(clause_id,query) => {clause_id,family,family_label,code,title,field,source_anchor,text,highlights,
 *    criteria:{numeric_status,has_numeric,message,branches:[{branch_id,label,numeric,thresholds,text}],checks,rejected}}
 *  검색·순위·찾은 이유('외 N' 포함)·강조 위치·다음 위치(next_offset)는 Python이 정한다. 화면은 받은 값을 그대로 보인다.
 *  간단한 결과(1.4.0): 개별 결과와 일괄 결과의 행마다 brief => {overall, reason, group, families:{advanced,core,dual_use,military},
 *    hints:[글], empty_message, focus:[조항], under:[조항], review:[{family_label,code,title,clause_id,reason,…}],
 *    counts:{over,near,under,review,hidden,detail_match_dropped}, semantic}.
 *    조항 = {verdict,family_label,code,title,clause_id,flags:[글],lines:[{display_reason,…}],others}. focus는 초과·근접 조항
 *    (사양마다 한 줄), under는 미달 조항(한 줄).
 *    일괄 결과에는 tally:[{kind,label,count}](종합 건수), groups:{focus,unjudged,other}(rows의 위치, 그릴 순서),
 *    tally_members:{over,near,under,unjudged}(종합 건수마다 그 건수에 든 rows의 위치 — 건수를 누르면 이 과제만 보인다),
 *    focus_label·other_label·unjudged_label(묶음 제목 글, 빈 글이면 그 묶음을 숨김), focus_empty_message, hints:[글]도 있다.
 *    판정 이름·사유 문장·안내 줄·건수·묶음·순서·인용 자르기는 모두 Python이 만들었다. 화면은 그 글을 그대로 넣고,
 *    1.2.0 화면은 '상세 보기'로 접어 둔다.
 * 화면에 넣는 글은 모두 textContent로만 넣는다.
 */
(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const all = query => [...document.querySelectorAll(query)];
    const VIEW_TITLES = {single: '연구개발과제 개별 검토', batch: '연구개발과제 일괄 검토', search: '고시 검색', settings: '설정'};
    const JOB_NAMES = {idle: '대기', running: '진행', cancelling: '취소 중', done: '완료', cancelled: '취소', failed: '오류'};
    const OPERATOR_LABELS = {ge: '이상', gt: '초과', le: '이하', lt: '미만'};
    const ORIGIN_LABELS = {structured: '정리된 기준', extracted: 'AI가 읽은 기준값'};
    const COUNT_LABELS = {total: '전체', done: '완료', no_facts: '목표 수치 없음', no_candidates: '관련 고시 항목 없음',
        error: '오류', cancelled: '취소', excluded: '제외 행', blank_rows: '빈 행(모든 칸이 빈 행)', option_warnings: '선택 칸 경고'};
    // 과제요약정보 세 칸: [화면 칸 id, 이름]
    const SUMMARY_FIELDS = [['task-final-goal', '최종목표'], ['task-rnd-content', '연구개발내용'], ['task-utilization', '활용계획 및 기대효과']];
    const NOT_GIVEN = '(없음)';
    const TERMINAL = ['done', 'cancelled', 'failed'];
    const state = {initial: null, ready: false, busy: false, view: 'single', active: null,
        settings: null, keyState: {}, attachment: null, extraction: null, confirmedExcerpt: null,
        batch: {token: null, read: null}, result: {single: null, batch: null},
        // 일괄 결과에서 지금 눌려 있는 종합 건수 단추(없으면 null — 처음 화면)
        tallyPick: null,
        // 고시 검색: 마지막 검색어·고시(더 보기용, 화면 메모리에만), 묶음별 다음 위치(Python이 준 값), 엔진 상태
        search: {available: false, status: null, pending: false, query: null, family: null, empty: false,
            next: {results: 0, similar: 0}}};
    const SEARCH_GROUPS = {results: 'search-results', similar: 'search-similar'};
    const SEARCH_FALLBACK_LIMIT = 20;

    // ── 작은 도우미 ────────────────────────────────────────────────────
    function node(tag, text, cls) { const el = document.createElement(tag); if (text !== undefined && text !== null) el.textContent = String(text); if (cls) el.className = cls; return el; }
    function append(parent, ...children) { children.flat().forEach(child => { if (child) parent.append(child); }); return parent; }
    function clear(el) { el.replaceChildren(); return el; }
    function textValue(value) { if (value === null || value === undefined || value === '') return '—'; if (Array.isArray(value)) return value.length ? value.map(textValue).join(' · ') : '없음'; return String(value); }
    function givenValue(value) { return value === null || value === undefined || value === '' ? NOT_GIVEN : String(value); }
    function metric(parent, label, value) { return append(parent, append(node('div', null, 'metric'), node('span', label), node('span', textValue(value)))); }
    function list(parent, label, values) { parent.append(node('h3', label, 'data-label')); if (!values || !values.length) { parent.append(node('p', '없음', 'mini-text')); return; } const ul = node('ul', null, 'data-list'); values.forEach(v => ul.append(node('li', textValue(v)))); parent.append(ul); }
    function table(parent, headers, rows) { const wrap = node('div', null, 'table-wrap'); const t = node('table'), head = node('thead'), tr = node('tr'); headers.forEach(h => { const th = node('th', h); th.scope = 'col'; tr.append(th); }); head.append(tr); const body = node('tbody'); rows.forEach(row => { const r = node('tr'); row.forEach(value => { const cell = node('td'); if (value instanceof Node) cell.append(value); else cell.textContent = textValue(value); r.append(cell); }); body.append(r); }); append(t, head, body); wrap.append(t); parent.append(wrap); return wrap; }
    function message(text = '') { $('message').textContent = text; $('message').hidden = !text; }
    function fail(error) { message(error && error.message ? error.message : '앱 연결 실패. 작업 상태 확인 뒤 다시 시도'); }
    async function call(name, ...args) {
        const api = window.pywebview && window.pywebview.api;
        if (!api || typeof api[name] !== 'function') throw new Error('앱 연결 대기 중. 설치된 앱에서 다시 열기 필요');
        const response = await api[name](...args);
        if (!response || typeof response.ok !== 'boolean') throw new Error('앱 응답 확인 불가');
        if (!response.ok) { const error = new Error(response.message || '요청 처리 실패'); error.code = response.code; throw error; }
        return response.data;
    }
    function familyLabel(id) { const found = (state.initial?.families || []).find(f => f.id === id); return found ? found.label : id; }
    function warningMessages(warnings) { return (warnings || []).map(w => w.message); }
    function show(view) {
        state.view = view;
        all('.screen').forEach(el => { el.hidden = el.id !== `screen-${view}`; });
        all('.nav [data-view]').forEach(button => { const selected = button.dataset.view === view; button.classList.toggle('active', selected); if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); });
        $('breadcrumb').textContent = VIEW_TITLES[view];
        window.scrollTo(0, 0);
    }

    // ── 검토 대상 고시 선택·예상 호출 수 ─────────────────────────────────
    function renderFamilies(areaId, prefix) {
        const area = clear($(areaId));
        state.initial.families.forEach(family => {
            const label = node('label'), check = node('input');
            check.type = 'checkbox'; check.checked = true; check.value = family.id; check.id = `${prefix}-${family.id}`;
            check.addEventListener('change', () => { refreshEstimates(); updateControls(); });
            append(label, check, node('span', family.label), node('small', `${family.count}개 조항`));
            area.append(label);
        });
    }
    function selectedFamilies(areaId) { return all(`#${areaId} input:checked`).map(input => input.value); }
    async function refreshEstimates() {
        const single = selectedFamilies('single-families');
        if (!single.length) $('single-estimate').textContent = '검토 대상 고시 하나 이상 선택 필요';
        else { try { const e = await call('estimate', single, false, 1); $('single-estimate').textContent = `예상 AI 호출 수 최소 ${e.per_task[0]}회 ~ 최대 ${e.per_task[1]}회`; } catch (error) { $('single-estimate').textContent = error.message; } }
        const batch = selectedFamilies('batch-families'), count = state.batch.read ? state.batch.read.count : 0;
        if (!batch.length) $('batch-estimate').textContent = '검토 대상 고시 하나 이상 선택 필요';
        else if (!count) $('batch-estimate').textContent = '입력 엑셀 선택 뒤 예상 호출 수 표시';
        else { try { const e = await call('estimate', batch, true, count); $('batch-estimate').textContent = `건당 최소 ${e.per_task[0]}회 ~ 최대 ${e.per_task[1]}회 · ${e.count}건 합계 최소 ${e.total[0]}회 ~ 최대 ${e.total[1]}회`; } catch (error) { $('batch-estimate').textContent = error.message; } }
    }

    // ── 설정·키 ──────────────────────────────────────────────────────────
    function providerInfo(id) { return (state.initial?.providers || []).find(p => p.id === id); }
    function renderRunInfo() {
        ['single-run-info', 'batch-run-info'].forEach(id => {
            const area = clear($(id)), s = state.settings || {};
            metric(area, '제공자', s.provider); metric(area, '모델', s.model);
            if (s.base_url) metric(area, '로컬 주소', s.base_url);
            const info = providerInfo(s.provider);
            if (info && info.needs_key) metric(area, 'API 키', state.keyState[s.provider]?.has_key ? '있음' : '없음 · 설정에서 저장 필요');
        });
    }
    function renderSettingsForm() {
        const provider = $('provider').value, info = providerInfo(provider);
        $('model').placeholder = info ? `기본값 ${info.default_model}` : '';
        $('base-url-field').hidden = !info || info.needs_key;
        $('base-url').placeholder = info ? info.default_base_url : '';
        $('key-panel').hidden = !info || !info.needs_key;
        renderKeyStatus();
    }
    function renderKeyStatus() {
        const provider = $('provider').value, key = state.keyState[provider];
        if (!key) { $('key-status').textContent = '키 사용 안 함(로컬 제공자)'; $('key-warning').textContent = ''; return; }
        const source = {saved: '보안 저장소의 키 사용', session: '이번 실행의 입력 키 사용', environment: '환경변수 키 사용', missing: ''}[key.source] || '';
        $('key-status').textContent = key.has_key ? `API 키 있음 · ${source}` : 'API 키 없음';
        $('key-warning').textContent = key.warning || '';
    }
    async function applySettings(quiet) {
        try {
            const data = await call('set_model_settings', $('provider').value, $('model').value, $('base-url').value);
            state.settings = data; $('model').value = ''; $('base-url').value = data.base_url || '';
            $('settings-status').textContent = `적용됨 · ${data.provider} · ${data.model}${data.base_url ? ' · ' + data.base_url : ''}`;
            renderRunInfo(); if (!quiet) message();
        } catch (error) { $('settings-status').textContent = ''; fail(error); }
    }
    async function saveKey() {
        if (state.busy) return;
        const provider = $('provider').value; let key = $('api-key').value.trim();
        if (!key) { message('새 API 키 입력 필요'); return; }
        try { const pending = call('save_key', provider, key); $('api-key').value = ''; key = ''; const saved = await pending; state.keyState[saved.provider] = saved; renderKeyStatus(); renderRunInfo(); message('API 키 저장 완료'); }
        catch (error) { fail(error); } finally { $('api-key').value = ''; key = ''; }
    }
    async function deleteKey() {
        if (state.busy) return; $('api-key').value = '';
        try { const saved = await call('delete_key', $('provider').value); state.keyState[saved.provider] = saved; renderKeyStatus(); renderRunInfo(); message('저장된 API 키 삭제 완료'); }
        catch (error) { fail(error); }
    }
    function renderCatalogue() {
        const area = clear($('catalogue-info')), c = state.initial.catalogue, t = state.initial.table;
        metric(area, '기준본', c.catalogue_id); metric(area, '고시 조항 수', c.item_count); metric(area, '고시 기준 사양 표 조항 수', t.record_count);
        (c.notices || []).forEach(n => { const p = node('p', null, 'mini-text'); p.textContent = `${n.title} · ${n.notice_number} · 고시일 ${n.announcement_date} · 시행일 ${n.effective_date}`; area.append(p); });
    }

    // ── 개별 검토: 첨부·발췌 ──────────────────────────────────────────────
    function setExcerptConfirmed(value) {
        state.confirmedExcerpt = value;
        $('excerpt-status').textContent = value === null ? '발췌 미확인 · 발췌 확인 뒤 AI로 전달' : (value ? `발췌 확인됨 · ${value.length.toLocaleString('ko-KR')}자` : '발췌 확인됨 · 빈 발췌(첨부 글 미전달)');
        updateControls();
    }
    function clearAttachment() {
        state.attachment = null; state.extraction = null; $('attachment-name').textContent = '선택하지 않음'; $('clear-attachment').hidden = true;
        $('extract-panel').hidden = true; $('excerpt').value = ''; clear($('goal-sections')); clear($('extract-warnings')); $('full-text').value = '';
        setExcerptConfirmed(null);
    }
    function appendExcerpt(text) {
        const area = $('excerpt'), current = area.value.trimEnd();
        area.value = current ? `${current}\n\n${text.trim()}` : text.trim();
        setExcerptConfirmed(null);
    }
    async function pickAttachment() {
        if (state.busy) return;
        try {
            const picked = await call('select_path', 'attachment');
            if (picked.cancelled) return;
            clearAttachment();
            state.attachment = {token: picked.token, name: picked.name};
            $('attachment-name').textContent = picked.name; $('clear-attachment').hidden = false;
            message('첨부 글 꺼내는 중');
            const data = await call('extract_attachment', picked.token);
            state.extraction = data; renderExtraction(data); message();
        } catch (error) {
            // 글 없는 PDF·암호·깨진 파일·HWP: 사유를 보이고 첨부가 없는 것으로 둔다(발췌 없음, 세 칸 필수).
            state.extraction = null; $('extract-panel').hidden = true;
            if (state.attachment) $('attachment-name').textContent = `${state.attachment.name} · 읽기 실패`;
            fail(error); updateControls();
        }
    }
    function renderExtraction(data) {
        $('extract-panel').hidden = false;
        $('extract-kind').textContent = `${data.kind.toUpperCase()}${data.page_count ? ` · ${data.page_count}쪽` : ''} · ${data.text_length.toLocaleString('ko-KR')}자`;
        const warnings = clear($('extract-warnings'));
        if (data.warnings.length) list(warnings, '읽기 경고(결과 엑셀 처리내역(숨김 시트)에도 기록)', data.warnings);
        const sections = clear($('goal-sections'));
        data.sections.forEach(section => {
            const item = node('div', null, 'section-item'), head = node('div');
            append(head, node('strong', section.heading), node('small', ` · ${section.body.length.toLocaleString('ko-KR')}자`));
            const button = node('button', '발췌에 다시 넣기', 'text-link'); button.type = 'button'; button.addEventListener('click', () => appendExcerpt(section.body));
            append(item, head, button); sections.append(item);
        });
        $('excerpt').value = data.sections.map(s => s.body).join('\n\n');
        $('full-text').value = data.text; $('full-text-length').textContent = `전체 ${data.text_length.toLocaleString('ko-KR')}자`;
        if (data.sections.length) { $('sections-note').textContent = `목표 부분 후보 ${data.sections.length}개를 발췌에 넣음. 고치거나 지우거나 전체 글에서 더 골라 붙인 뒤 '발췌 확인' 필요`; $('full-text-details').open = false; }
        else { $('sections-note').textContent = '목표 부분 제목을 찾지 못함. 전체 글에서 목표 부분을 끌어 선택해 발췌에 추가한 뒤 \'발췌 확인\' 필요'; $('full-text-details').open = true; }
        setExcerptConfirmed(null);
    }
    function addSelection() {
        const area = $('full-text'), text = area.value.slice(area.selectionStart, area.selectionEnd);
        if (!text.trim()) { message('전체 글에서 추가할 부분을 먼저 끌어 선택 필요'); return; }
        appendExcerpt(text); message();
    }
    // 선택 칸 경고(Python이 확인한 결과)를 지원금 칸 아래에 보인다. 빈칸으로 검토하며 막지 않는다.
    function renderOptionNote(warnings) {
        const messages = warningMessages(warnings), note = $('gov-fund-note');
        note.textContent = messages.length ? `${messages.join(' · ')} · 빈칸으로 검토(처리내역(숨김 시트)에 기록)` : '';
        note.hidden = !messages.length;
    }

    // ── 작업 진행 ──────────────────────────────────────────────────────────
    function hasConfirmedExcerpt() { return typeof state.confirmedExcerpt === 'string' && state.confirmedExcerpt.length > 0; }
    function updateControls() {
        const busy = state.busy || !state.ready;
        ['pick-attachment', 'clear-attachment', 'confirm-excerpt', 'add-selection', 'save-template', 'pick-batch-input', 'save-key', 'delete-key', 'apply-settings', 'provider', 'model', 'base-url', 'api-key', 'save-single', 'save-batch', 'task-title', 'task-final-goal', 'task-rnd-content', 'task-utilization', 'task-rnd-stage', 'task-gov-fund', 'excerpt'].forEach(id => { $(id).disabled = busy; });
        all('.check-list input').forEach(input => { input.disabled = busy; });
        // 시작 조건: 연구개발과제명 있음 그리고 (세 칸 모두 있음 또는 확인한 발췌 있음). 최종 확인은 Python이 한다.
        const title = $('task-title').value.trim(), families = selectedFamilies('single-families');
        const missing = SUMMARY_FIELDS.filter(([id]) => !$(id).value.trim()).map(([, name]) => name);
        let hint = '', soft = '';
        if (!title) hint = '연구개발과제명 입력 필요';
        else if (missing.length && !hasConfirmedExcerpt()) hint = `${missing.join('·')} 입력 필요` + (state.extraction ? ' 또는 첨부 발췌 확인 필요' : ' 또는 첨부파일 선택 뒤 발췌 확인 필요');
        else if (!families.length) hint = '검토 대상 고시 하나 이상 선택 필요';
        else if (state.extraction && state.confirmedExcerpt === null) soft = '첨부 발췌 미확인. 과제요약정보만으로 검토(첨부 미전달)하거나 발췌 확인 필요';
        $('single-hint').textContent = hint || soft || '검토 시작 가능 · 연구개발과제명·과제요약정보와 확인한 발췌만 AI로 전달(연구개발단계·지원금 미전달)';
        $('start-single').disabled = busy || Boolean(hint);
        const read = state.batch.read, batchFamilies = selectedFamilies('batch-families');
        let batchHint = '';
        if (!read) batchHint = '입력 엑셀을 읽어 처리 건수를 확인한 뒤 시작 가능';
        else if (!read.count) batchHint = '처리할 행 없음. 입력 엑셀의 연구개발과제명·과제요약정보 확인 필요';
        else if (!batchFamilies.length) batchHint = '검토 대상 고시 하나 이상 선택 필요';
        $('batch-hint').textContent = batchHint || `${read.count}건 시작 가능 · 제외 ${read.excluded.length}건·선택 칸 경고 ${read.option_warnings.length}건은 처리내역(숨김 시트)에 기록`;
        $('start-batch').disabled = busy || Boolean(batchHint);
        $('cancel-job').disabled = !state.active || state.active.state !== 'running';
        updateSearchControls();
    }
    function setBusy(value) { state.busy = value; updateControls(); }
    function consumeEvents(active, events) {
        (events || []).filter(e => Number.isInteger(e.sequence) && e.sequence > active.sequence).sort((a, b) => a.sequence - b.sequence).forEach(event => {
            active.sequence = event.sequence;
            const line = event.message && event.message !== event.label ? `${event.label} · ${event.message}` : event.label;
            $('job-status').textContent = line;
            const progress = $('job-progress');
            if (Number.isFinite(event.total) && event.total > 0 && Number.isFinite(event.completed)) { progress.max = event.total; progress.value = event.completed; } else progress.removeAttribute('value');
            $('job-events').append(node('li', line));
        });
    }
    async function start(kind) {
        if (state.busy || !state.ready) return;
        try {
            let snapshot;
            if (kind === 'single') {
                const families = selectedFamilies('single-families');
                const excerpt = hasConfirmedExcerpt() ? state.confirmedExcerpt : '';
                // 지원금은 쓴 글 그대로 보낸다(쉼표·소수·잘못된 값의 확인은 Python 공용 정리 함수가 한다).
                const task = {title: $('task-title').value.trim(), final_goal: $('task-final-goal').value.trim(),
                    rnd_content: $('task-rnd-content').value.trim(), utilization: $('task-utilization').value.trim(),
                    excerpt: excerpt, attachment_name: state.attachment && state.extraction && excerpt ? state.attachment.name : '',
                    rnd_stage: $('task-rnd-stage').value, gov_fund: $('task-gov-fund').value};
                message(); renderOptionNote([]); setBusy(true);
                snapshot = await call('run_single', task, families);
                renderOptionNote(snapshot.option_warnings);
            } else {
                message(); setBusy(true);
                snapshot = await call('run_batch', state.batch.token, selectedFamilies('batch-families'));
            }
            const active = {kind, state: snapshot.state, sequence: 0};
            state.active = active; $('job-panel').hidden = false; $('job-state').textContent = JOB_NAMES[snapshot.state] || snapshot.state;
            $('job-status').textContent = '작업 준비 중'; clear($('job-events')); $('job-progress').removeAttribute('value');
            consumeEvents(active, snapshot.events); setBusy(true); poll(active);
        } catch (error) { state.active = null; setBusy(false); fail(error); }
    }
    async function poll(active) {
        try {
            const job = await call('poll_progress', active.sequence);
            if (state.active !== active) return;
            active.state = job.state; consumeEvents(active, job.events); $('job-state').textContent = JOB_NAMES[job.state] || job.state;
            if (TERMINAL.includes(job.state)) { finish(active, job); return; }
            updateControls(); setTimeout(() => { if (state.active === active) poll(active); }, 300);
        } catch (error) { if (state.active !== active) return; fail(error); setTimeout(() => { if (state.active === active) poll(active); }, 1200); }
    }
    function finish(active, job) {
        state.active = null; setBusy(false); $('cancel-job').disabled = true;
        if (job.state === 'failed') { message(job.message || '작업 처리 실패'); return; }
        if (active.kind === 'single') {
            if (!job.result) { message(job.message || '검토 결과 없음'); return; }
            state.result.single = job.result; renderSingleResult(job.result); message();
        } else {
            if (!job.result) { message(job.message || '일괄 검토 결과 없음'); return; }
            state.result.batch = job.result; renderBatchResult(job.result); message(job.state === 'cancelled' ? job.message : '');
        }
    }
    async function cancel() {
        const active = state.active; if (!active || active.state !== 'running') return;
        try { const response = await call('cancel'); active.state = response.state; $('job-state').textContent = JOB_NAMES[response.state] || response.state; updateControls(); }
        catch (error) { fail(error); }
    }

    // ── 간단한 결과(brief) ────────────────────────────────────────────────────
    // 판정 이름·사유 문장·안내 줄·건수·묶음·순서·인용 자르기는 Python(brief 모듈)이 만들었다. 받은 글을 textContent로 넣기만 한다.
    // 판정 이름별 색은 받은 이름으로 class 이름만 고른다(다시 계산하지 않음).
    const VERDICT_CLASSES = {'고시 사양 초과': 'over', '고시 사양 근접': 'near', '고시 사양 미달': 'under'};
    function chip(text) { return node('span', textValue(text), `chip ${VERDICT_CLASSES[text] || 'other'}`); }
    function briefRow(parent, label, value, asChip) { const row = node('div', null, 'brief-row'); append(row, node('span', label, 'brief-label'), asChip ? chip(value) : node('span', textValue(value), 'brief-value')); parent.append(row); return row; }
    function briefLines(area, lines, cls) { clear(area); (lines || []).forEach(text => area.append(node('p', text, cls))); area.hidden = !area.childElementCount; return area; }
    function briefOverview(area, result, brief) {
        clear(area);
        briefRow(area, '연구개발과제명', result.title);
        if (result.status !== '완료') briefRow(area, '상태', result.status);
        briefRow(area, '종합 결과', brief.overall, true);
        if (brief.reason) briefRow(area, '사유', brief.reason);
        area.append(node('div', '고시별 결과', 'brief-group'));
        (state.initial?.families || []).forEach(f => briefRow(area, f.label, (brief.families || {})[f.id], true));
        if (result.error_reason) briefRow(area, '오류 사유', result.error_reason);
    }
    // 조항 하나: 판정·고시·통제번호·조항명 / 확인 표시(있을 때) / 사양 줄마다 화면용 사유(인용 80자 자르기는 Python이 함).
    // 초과·근접 조항은 사양마다 한 줄, 미달 조항은 한 줄이다(줄 수와 순서는 Python이 정함). withSearch는 개별 화면에서만 참.
    function clauseBlock(clause, withSearch) {
        const row = node('div', null, 'brief-item'), head = node('div', null, 'brief-item-head');
        append(head, chip(clause.verdict), node('span', clause.family_label, 'family'), clause.code ? node('span', clause.code, 'code') : null,
            node('strong', clause.title || clause.clause_id, 'title'));
        row.append(head);
        if ((clause.flags || []).length) row.append(node('p', `확인: ${clause.flags.join(' · ')}`, 'brief-flags'));
        (clause.lines || []).forEach(line => row.append(node('p', line.display_reason, 'brief-reason')));
        if (withSearch) row.append(searchButton(clause.clause_id));
        return row;
    }
    // 일괄 '중점 검토 과제'의 과제 하나: 종합 결과·행 번호·연구개발과제명·(있으면) 추가 검토 건수와 그 과제의 초과·근접 조항 전부.
    function focusCard(row) {
        const brief = row.brief || {}, counts = brief.counts || {};
        const card = node('div', null, 'focus-card'), head = node('div', null, 'focus-card-head');
        append(head, chip(brief.overall), node('span', `${textValue(row.row_number)}행`, 'row-number'), node('strong', row.title, 'title'),
            counts.review ? node('span', `추가 검토 ${counts.review}건`, 'review-count') : null);
        card.append(head);
        (brief.focus || []).forEach(clause => card.append(clauseBlock(clause, false)));
        return card;
    }
    // 접힌 묶음: 닫아 두고, 내용이 없으면 숨긴다. 제목 글은 받은 글(또는 받은 건수) 그대로.
    function fold(detailsId, titleId, title, shown) { const el = $(detailsId); el.open = false; el.hidden = !shown; $(titleId).textContent = title; }
    // 접힌 묶음의 제목 글(건수는 Python이 센 값 그대로). 개별 화면과 일괄의 과제 카드가 같이 쓴다.
    function underTitle(counts) { return `미달 조항 ${textValue(counts.under)}건`; }
    function reviewTitle(counts) { return `추가 검토 필요 ${textValue(counts.review)}건`; }
    // 추가 검토 필요 한 줄: '· 고시 통제번호 조항명 — 사유'(사유는 Python이 만든 '남긴 이유, 비교하지 못한 이유')
    // withSearch는 개별 화면에서만 참(일괄 결과에는 '고시 검색에서 열기'를 두지 않는다).
    function reviewItem(entry, withSearch) {
        const li = node('li', null, 'review-item'), head = node('span', null, 'review-head');
        append(head, node('span', entry.family_label, 'family'), entry.code ? node('span', entry.code, 'code') : null,
            node('strong', entry.title || entry.clause_id, 'title'));
        append(li, head, node('span', ` — ${entry.reason}`, 'review-reason'), withSearch ? searchButton(entry.clause_id) : null);
        return li;
    }
    // 과제 카드 안의 접힌 묶음 하나(닫힌 채로): 제목 글과 내용.
    function foldBlock(title, content) { return append(node('details', null, 'brief-fold'), node('summary', title), content); }
    // 일괄 결과에서 종합 건수를 눌렀을 때의 과제 하나: 종합 결과·행 번호·연구개발과제명 / 사유·오류 사유·안내 줄 /
    // 초과·근접 조항(펼침) / 미달 조항·추가 검토 필요(접힘). 개별 화면의 간단한 결과와 같은 글(brief)을 그대로 놓는다.
    function taskCard(row) {
        const brief = row.brief || {}, counts = brief.counts || {};
        const card = node('div', null, `focus-card ${VERDICT_CLASSES[brief.overall] || 'other'}`), head = node('div', null, 'focus-card-head');
        append(head, chip(brief.overall), node('span', `${textValue(row.row_number)}행`, 'row-number'), node('strong', row.title, 'title'));
        card.append(head);
        if (brief.reason) card.append(node('p', `사유: ${brief.reason}`, 'task-reason'));
        if (row.error_reason) card.append(node('p', `오류 사유: ${row.error_reason}`, 'task-reason'));
        (brief.hints || []).forEach(text => card.append(node('p', text, 'hint')));
        (brief.focus || []).forEach(clause => card.append(clauseBlock(clause, false)));
        const under = (brief.under || []).map(clause => clauseBlock(clause, false));
        if (under.length) card.append(foldBlock(underTitle(counts), under));
        const review = (brief.review || []).map(entry => reviewItem(entry, false));
        if (review.length) card.append(foldBlock(reviewTitle(counts), append(node('ul', null, 'review-list'), review)));
        return card;
    }
    function renderBrief(result) {
        const brief = result.brief || {}, counts = brief.counts || {};
        briefOverview($('single-overview'), result, brief);
        briefLines($('single-hints'), brief.hints, 'hint');
        // 초과·근접 고시 조항(펼침). 없으면 Python이 준 빈 목록 문구(오류·취소면 빈 글이라 묶음을 숨긴다).
        const focus = clear($('single-focus-items'));
        (brief.focus || []).forEach(clause => focus.append(clauseBlock(clause, true)));
        if (!focus.childElementCount && brief.empty_message) focus.append(node('p', brief.empty_message, 'empty-message'));
        $('single-focus').hidden = !focus.childElementCount;
        // 미달 조항·추가 검토 필요(접힘). 제목의 건수는 Python이 센 값 그대로.
        const under = clear($('single-under-items'));
        (brief.under || []).forEach(clause => under.append(clauseBlock(clause, true)));
        fold('single-under', 'single-under-title', underTitle(counts), under.childElementCount);
        const review = clear($('single-review-list'));
        (brief.review || []).forEach(entry => review.append(reviewItem(entry, true)));
        fold('single-review', 'single-review-title', reviewTitle(counts), review.childElementCount);
    }

    // ── 결과 표시(개별 검토) ─────────────────────────────────────────────────
    function renderSingleResult(result) {
        $('single-result').hidden = false;
        renderBrief(result);
        // 상세 보기(접힘): 1.2.0 결과 화면 그대로(내부 값)와 간단한 결과에서 감춘 것의 건수.
        $('single-detail').open = false;
        const summary = clear($('single-summary'));
        metric(summary, '연구개발과제명', result.title);
        metric(summary, '연구개발단계', givenValue(result.rnd_stage));
        metric(summary, '정부지원연구개발비(백만원)', givenValue(result.gov_fund));
        metric(summary, '입력 정보', result.input_description);
        metric(summary, '상태', result.status);
        metric(summary, '종합 검토 결과', result.overall);
        summary.append(node('h3', '고시별 검토 결과', 'data-label'));
        Object.entries(result.families || {}).forEach(([family, verdict]) => metric(summary, `${familyLabel(family)} 검토 결과`, verdict));
        summary.append(node('h3', '건수', 'data-label'));
        Object.entries(result.counts || {}).forEach(([label, value]) => metric(summary, `${label} 조항 수`, value));
        metric(summary, '확인 표시 조항 수', result.flagged_clause_count);
        const counts = (result.brief || {}).counts || {};
        summary.append(node('h3', '간단한 결과에서 감춘 고시 조항', 'data-label'));
        metric(summary, '간단한 결과에 넣지 않은 관련 조항 수', counts.hidden);
        metric(summary, '세부 기술 일치로 답했지만 남기지 않은 조항 수', counts.detail_match_dropped);
        if (result.error_reason) metric(summary, '오류 사유', result.error_reason);
        metric(summary, 'AI 호출 수', `${result.calls.total}회 (최종목표 사양 추출 ${result.calls.extract} · 관련 고시 조항 선별 ${result.calls.screen} · 매핑 ${result.calls.pair})`);
        metric(summary, '실행', `${result.run.provider} · ${result.run.model} · ${result.run.run_time}`);
        const items = clear($('single-items'));
        const judge = result.judge;
        if (!judge || !judge.clauses.length) items.append(node('p', result.status === '완료' ? '대조한 고시 조항 없음' : `${result.status} · 고시 조항 대조 없음`, 'mini-text'));
        else {
            const byClause = new Map();
            (judge.comparisons || []).forEach(comp => { if (!byClause.has(comp.clause_id)) byClause.set(comp.clause_id, []); byClause.get(comp.clause_id).push(comp); });
            judge.clauses.forEach(clause => {
                const comps = byClause.get(clause.clause_id) || [];
                if (!comps.length) items.append(itemDetails(clause, null));
                else comps.forEach(comp => items.append(itemDetails(clause, comp)));
            });
        }
        const extra = clear($('single-extra'));
        if ((result.option_warnings || []).length) list(extra, '선택 칸 경고(빈칸으로 검토, 결과 엑셀 처리내역(숨김 시트)에도 기록)', warningMessages(result.option_warnings));
        list(extra, '추출한 최종목표 사양', (result.facts || []).map(f => `${f.subject} · ${f.value_text}${f.unit ? ' ' + f.unit : ''} · ${f.source_field} · "${f.quote}"`));
        list(extra, '버린 최종목표 사양·매핑(사유와 함께)', (result.dropped || []).map(d => `[${d.stage}] ${d.kind} ${d.ids}: ${d.reason}`));
        if (judge && judge.skipped_clauses && judge.skipped_clauses.length) list(extra, '검토하지 않은 관련 고시 조항', judge.skipped_clauses.map(s => `${s.clause_id} · ${s.reason}`));
    }
    function itemDetails(clause, comp) {
        const details = node('details', null, 'item'), summary = node('summary');
        const verdict = comp ? comp.verdict : clause.verdict;
        const chip = node('span', verdict, 'verdict' + (clause.flags && clause.flags.length ? ' warn' : ''));
        const title = node('div'); append(title, node('div', clause.title || clause.clause_id), node('div', clause.code ? `${clause.code} · ${clause.clause_id}` : clause.clause_id, 'mini-text'));
        if (clause.flags && clause.flags.length) title.append(node('div', `확인 표시: ${clause.flags.join(' · ')}`, 'flags'));
        const basis = comp ? `${comp.subject} ${OPERATOR_LABELS[comp.operator] || comp.operator} ${comp.threshold_value} ${comp.threshold_unit}` : '수치 기준 없음';
        const target = comp ? `${comp.value_text}${comp.converted_value ? ` → ${comp.converted_value} ${comp.threshold_unit}` : ''}` : '—';
        const gap = comp && comp.gap_percent_display ? `${comp.gap_percent_display} %` : '—';
        append(summary, node('span', familyLabel(clause.family)), node('span', `${basis}\n최종목표 ${target}\n차이 ${gap}`), title, chip);
        const body = node('div', null, 'item-body');
        metric(body, '조항 검토 결과', clause.verdict); if (clause.reason) metric(body, '사유', clause.reason);
        if (comp) {
            metric(body, '갈래', comp.branch_label || '—'); metric(body, '고시 기준 출처', ORIGIN_LABELS[comp.origin] || comp.origin);
            body.append(node('h3', '고시 기준 원문 인용', 'data-label')); body.append(node('p', comp.threshold_quote || '—', 'quote'));
            body.append(node('h3', `최종목표 인용 (${comp.source_field})`, 'data-label')); body.append(node('p', comp.fact_quote || '—', 'quote'));
            metric(body, '사용한 값', `${comp.used_value} ${comp.fact_unit}`); metric(body, '사양 비교 결과', comp.verdict);
            if (comp.pair_reason) { body.append(node('h3', '매핑 근거', 'data-label')); body.append(node('p', comp.pair_reason, 'quote')); }
        }
        if (clause.missing_subjects && clause.missing_subjects.length) list(body, '빠진 고시 기준', clause.missing_subjects);
        if (clause.branch_texts && clause.branch_texts.length) list(body, '갈래 설명', clause.branch_texts);
        if (clause.checks && clause.checks.length) list(body, '추가 확인 조건 원문', clause.checks.map(c => c.quote));
        if (clause.rejected && clause.rejected.length) list(body, '고시 기준 사양 채택 실패(원문 확인 필요)', clause.rejected.map(r => `${r.subject}: "${r.quote}" · ${r.reason}`));
        body.append(searchButton(clause.clause_id));
        append(details, summary, body);
        return details;
    }
    // 고시 검색 탭으로 옮겨 그 조항의 원문·고시 기준 사양 목록을 연다. 개별 검토 결과(초과·근접 조항·미달 조항·추가 검토 필요·상세
    // 카드)에만 둔다(일괄 검토 결과 표에는 두지 않는다).
    function searchButton(clauseId) {
        const open = node('button', '고시 검색에서 열기', 'text-link open-search'); open.type = 'button';
        open.addEventListener('click', () => openInSearch(clauseId));
        return open;
    }

    // ── 03 고시 검색(읽기만 함. 검토 작업 중에도 사용 가능) ─────────────────────
    // 받은 강조 범위([시작, 끝))대로 글을 잘라 textContent로 넣는다. 범위 계산은 Python이 했다.
    function highlighted(parent, text, spans) {
        let position = 0;
        (spans || []).forEach(span => {
            const start = span[0], end = span[1];
            if (start < position || end <= start) return;
            if (start > position) parent.append(document.createTextNode(text.slice(position, start)));
            parent.append(node('mark', text.slice(start, end)));
            position = end;
        });
        parent.append(document.createTextNode(text.slice(position)));
        return parent;
    }
    function searchLimit() { return state.initial?.search?.default_limit || SEARCH_FALLBACK_LIMIT; }
    function updateSearchControls() {
        // 검토 작업과 무관하다(작업 중에도 검색 가능). 검색 요청이 진행 중이면 다시 누르지 않게만 한다.
        $('search-button').disabled = !state.ready || state.search.pending;
        ['search-results-more', 'search-similar-more'].forEach(id => { $(id).disabled = !state.ready || state.search.pending; });
    }
    // 의미 유사 꺼짐·관련어 사전 사용 불가 안내(엔진 status의 notice 글 그대로)와 검색 준비 실패 안내.
    function renderSearchNotices(status) {
        if (status) state.search.status = status;
        const area = clear($('search-notices')), info = state.initial?.search;
        if (!state.search.available && info && info.message) area.append(node('p', info.message, 'search-notice'));
        const current = state.search.status;
        if (current) [current.dictionary?.notice, current.semantic?.notice].filter(Boolean).forEach(text => area.append(node('p', text, 'search-notice')));
    }
    function renderSearchInitial() {
        const info = state.initial.search, select = clear($('search-family'));
        const filters = info && Array.isArray(info.filters) ? info.filters : [{id: '전체', label: '전체'}];
        filters.forEach(f => { const option = node('option', f.label); option.value = f.id; select.append(option); });
        if (info) {
            select.value = info.default_filter; $('search-query').maxLength = info.max_query_chars;
            $('search-footer').textContent = info.footer; $('search-similar-notice').textContent = info.similar_notice;
        }
        state.search.available = Boolean(info && info.available);
        renderSearchNotices(info ? info.status : null);
    }
    function renderGroup(name, group, replace) {
        const base = SEARCH_GROUPS[name], area = $(base);
        if (replace) clear(area);
        group.items.forEach(item => area.append(searchItem(item)));
        $(`${base}-group`).hidden = !group.visible || state.search.empty;
        $(`${base}-count`).textContent = `${group.total}건`;
        $(`${base}-empty`).textContent = group.empty_message || ''; $(`${base}-empty`).hidden = !group.empty_message;
        const more = $(`${base}-more`); more.hidden = !group.has_more; more.textContent = `더 보기 · 남은 ${group.remaining}건`;
        state.search.next[name] = group.next_offset;
    }
    function renderSearchResult(data) {
        renderSearchNotices(data.status);
        $('search-footer').textContent = data.footer;
        state.search.empty = Boolean(data.empty_message);
        $('search-empty').textContent = data.empty_message || ''; $('search-empty').hidden = !data.empty_message;
        if (data.similar.notice) $('search-similar-notice').textContent = data.similar.notice;
        renderGroup('results', data.results, true); renderGroup('similar', data.similar, true);
        const parts = [`${data.family_label} · 검색 결과 ${data.results.total}건`];
        if (data.similar.visible) parts.push(`비슷한 뜻(참고) ${data.similar.total}건`);
        $('search-status').textContent = parts.join(' · ');
    }
    async function runSearch() {
        if (!state.ready || state.search.pending) return;
        const query = $('search-query').value, family = $('search-family').value;
        // 의미 유사 모델은 첫 검색 때 불러오므로 몇 초 걸릴 수 있다.
        const preparing = state.search.status?.semantic?.state === 'pending';
        state.search.pending = true; updateSearchControls();
        $('search-status').textContent = preparing ? '검색 준비 중 · 처음 검색은 의미 유사 모델을 불러오느라 몇 초 걸림' : '검색 중';
        try {
            const data = await call('search_notices', query, family, searchLimit(), 0, 0);
            state.search.query = query; state.search.family = family; state.search.available = true;
            renderSearchResult(data);
        } catch (error) { $('search-status').textContent = error.message || '고시 검색 처리 실패'; }
        finally { state.search.pending = false; updateSearchControls(); }
    }
    async function searchMore(name) {
        if (!state.ready || state.search.pending || state.search.query === null) return;
        state.search.pending = true; updateSearchControls();
        try {
            const next = state.search.next;
            const data = await call('search_notices', state.search.query, state.search.family, searchLimit(),
                name === 'results' ? next.results : 0, name === 'similar' ? next.similar : 0);
            renderSearchNotices(data.status); renderGroup(name, data[name], false);
        } catch (error) { $('search-status').textContent = error.message || '고시 검색 처리 실패'; }
        finally { state.search.pending = false; updateSearchControls(); }
    }
    function searchItem(item) {
        const details = node('details', null, 'search-item'), summary = node('summary');
        const row = node('div', null, 'search-row'), title = node('div');
        append(title, node('strong', item.title || item.clause_id), item.field ? node('div', `분야 ${item.field}`, 'mini-text') : null);
        append(row, node('span', item.family_label), node('span', item.code || '', 'code'), title, node('span', item.reason, 'reason'));
        append(summary, row, highlighted(node('p', null, 'snippet'), item.snippet || '', item.highlights));
        const body = node('div', null, 'item-body');
        append(details, summary, body);
        // 펼칠 때 한 번 상세를 받는다(검색어·관련어 강조는 Python이 정함).
        details.addEventListener('toggle', () => { if (details.open && !details.dataset.loaded) loadDetail(details, body, item.clause_id, state.search.query || ''); });
        return details;
    }
    async function loadDetail(details, body, clauseId, query) {
        details.dataset.loaded = 'loading';
        clear(body).append(node('p', '원문 불러오는 중', 'mini-text'));
        try { renderNoticeDetail(clear(body), await call('get_notice_detail', clauseId, query)); details.dataset.loaded = 'true'; }
        catch (error) { clear(body).append(node('p', error.message || '고시 조항 상세 확인 불가', 'mini-text')); delete details.dataset.loaded; }
    }
    // 조항 상세: 원문 전체(강조), 고시 기준 사양 목록(갈래·물리량·비교어·값·단위·출처·확인 표시), 숫자 없는 갈래 원문,
    // 추가 확인 조건 원문, 채택 실패. 숫자 기준이 없으면 '수치 기준 없음' 안내.
    function renderNoticeDetail(area, detail) {
        metric(area, '검토 대상 고시', detail.family_label); metric(area, '통제번호', detail.code);
        metric(area, '조항 제목', detail.title); metric(area, '분야', detail.field);
        metric(area, '조항 ID', detail.clause_id); metric(area, '원문 위치', detail.source_anchor);
        area.append(node('h3', '고시 원문(국문·영문)', 'data-label'));
        area.append(highlighted(node('p', null, 'quote notice-text'), detail.text || '', detail.highlights));
        const criteria = detail.criteria;
        area.append(node('h3', '고시 기준 사양 목록', 'data-label'));
        if (!criteria.has_numeric) area.append(node('p', criteria.message, 'notice'));
        const rows = [];
        criteria.branches.forEach(branch => branch.thresholds.forEach(t => rows.push([branch.label || branch.branch_id, t.subject,
            t.operator_label, t.value, t.unit, t.origin_label, t.quote, t.flag])));
        if (rows.length) table(area, ['갈래', '물리량', '비교어', '값', '단위', '출처', '원문 인용', '확인 표시'], rows);
        const textBranches = criteria.branches.filter(branch => !branch.numeric && branch.text);
        if (textBranches.length) list(area, '숫자 없는 갈래 원문', textBranches.map(branch => branch.label ? `${branch.label}: ${branch.text}` : branch.text));
        if (criteria.checks.length) list(area, '추가 확인 조건 원문', criteria.checks.map(check => check.from_body ? check.quote : `${check.quote} (출처 ${check.source})`));
        if (criteria.rejected.length) list(area, '고시 기준 사양 채택 실패(원문 확인 필요)', criteria.rejected.map(r => `${r.subject}: "${r.quote}" · ${r.reason}`));
        return area;
    }
    // 개별 검토 결과의 '고시 검색에서 열기': 03 탭으로 옮겨 그 조항의 상세를 연다.
    async function openInSearch(clauseId) {
        show('search');
        const panel = $('search-focus'), body = clear($('search-focus-body'));
        panel.hidden = false; $('search-focus-note').textContent = '개별 검토 결과에서 연 고시 조항';
        body.append(node('p', '원문 불러오는 중', 'mini-text'));
        try { renderNoticeDetail(clear(body), await call('get_notice_detail', clauseId, '')); }
        catch (error) { clear(body).append(node('p', error.message || '고시 조항 상세 확인 불가', 'mini-text')); }
        panel.scrollIntoView({block: 'start'});
    }
    function closeFocus() { $('search-focus').hidden = true; clear($('search-focus-body')); }

    // ── 일괄 검토 ────────────────────────────────────────────────────────────
    async function saveTemplate() {
        if (state.busy) return;
        try { const picked = await call('select_path', 'save_template'); if (picked.cancelled) return; const saved = await call('save_template', picked.token); $('template-name').textContent = saved.name; message('입력 양식 저장 완료'); }
        catch (error) { fail(error); }
    }
    async function pickBatchInput() {
        if (state.busy) return;
        try {
            const picked = await call('select_path', 'batch_input'); if (picked.cancelled) return;
            state.batch = {token: picked.token, read: null}; $('batch-input-name').textContent = picked.name; $('batch-read').hidden = true; $('batch-result').hidden = true;
            const read = await call('read_batch', picked.token); state.batch.read = read; renderBatchRead(read); message();
        } catch (error) { state.batch.read = null; $('batch-read').hidden = true; fail(error); }
        refreshEstimates(); updateControls();
    }
    function renderBatchRead(read) {
        $('batch-read').hidden = false;
        const metrics = clear($('batch-read-metrics'));
        metric(metrics, '처리 건수', read.count); metric(metrics, '전체 행(머리글 제외)', read.total_rows); metric(metrics, '빈 행(모든 칸이 빈 행)', read.blank_rows);
        metric(metrics, '제외 행', read.excluded.length); metric(metrics, '선택 칸 경고', read.option_warnings.length);
        const excluded = clear($('batch-excluded'));
        if (read.excluded.length) table(excluded, ['행', '사유', '값'], read.excluded.map(e => [e.row_number, e.reason, e.value]));
        const warnings = clear($('batch-warnings'));
        if (read.option_warnings.length) list(warnings, '선택 칸 경고(빈칸으로 검토, 처리내역(숨김 시트)에도 기록)', warningMessages(read.option_warnings));
    }
    // 종합 건수 단추를 눌렀을 때: 그 건수에 든 과제(Python이 준 위치 그대로)만 과제 카드로 보이고 처음 화면의 묶음은 숨긴다.
    // button이 없으면(같은 단추를 다시 눌렀거나 '전체 보기') 처음 화면으로 돌아간다. 화면은 과제를 고르거나 세지 않는다.
    function showTally(button, title, rows) {
        state.tallyPick = button || null;
        all('#batch-tally .tally-item').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
        $('batch-default').hidden = Boolean(button); $('batch-picked').hidden = !button;
        const items = clear($('batch-picked-items'));
        $('batch-picked-title').textContent = button ? title : '';
        if (!button) return;
        rows.forEach(row => items.append(taskCard(row)));
        $('batch-picked').scrollIntoView({block: 'nearest'});
    }
    function renderBatchResult(result) {
        $('batch-result').hidden = false;
        const rows = result.rows || [], groups = result.groups || {}, members = result.tally_members || {};
        // Python이 정한 묶음(rows의 위치, 그릴 순서)대로 행을 꺼낸다. 화면은 묶거나 세지 않는다.
        const pick = positions => (positions || []).map(position => rows[position]).filter(Boolean);
        // 간단한 결과: 처리 건수 한 줄, 종합 건수, 안내 줄, 중점 검토 과제, 판정하지 못한 과제, 접힌 그 밖의 과제(모두 Python 글 그대로)
        $('batch-count-line').textContent = Object.entries(result.counts || {}).map(([key, value]) => `${COUNT_LABELS[key] || key} ${textValue(value)}`).join(' · ');
        // 종합 건수는 단추다. 누르면 그 건수에 든 과제(tally_members의 위치)만 보이고, 다시 누르면 처음 화면이다.
        const tally = clear($('batch-tally'));
        showTally(null);
        (result.tally || []).forEach(entry => {
            const title = `${entry.label} ${textValue(entry.count)}건`, button = node('button', title, `tally-item ${entry.kind}`);
            const picked = pick(members[entry.kind]);
            button.type = 'button'; button.disabled = !picked.length; button.setAttribute('aria-pressed', 'false');
            button.addEventListener('click', () => showTally(state.tallyPick === button ? null : button, title, picked));
            tally.append(button);
        });
        briefLines($('batch-hints'), result.hints, 'hint');
        $('batch-focus-title').textContent = textValue(result.focus_label);
        const focus = clear($('batch-focus-items'));
        pick(groups.focus).forEach(row => focus.append(focusCard(row)));
        if (result.focus_empty_message) focus.append(node('p', result.focus_empty_message, 'empty-message'));
        $('batch-unjudged-title').textContent = result.unjudged_label || '';
        $('batch-unjudged').hidden = !result.unjudged_label;
        table(clear($('batch-unjudged-rows')), ['입력 행 번호', '연구개발과제명', '상태', '오류 사유'], pick(groups.unjudged).map(r => [r.row_number, r.title, r.status, r.error_reason]));
        fold('batch-other', 'batch-other-title', result.other_label || '', result.other_label);
        table(clear($('batch-other-rows')), ['입력 행 번호', '연구개발과제명', '사유', '추가 검토 필요'], pick(groups.other).map(r => {
            const brief = r.brief || {}, counts = brief.counts || {};
            return [r.row_number, r.title, brief.reason, counts.review];
        }));
        // 상세 보기(접힘): 1.2.0 일괄 결과 그대로(건수·실행·선택 칸 경고·과제 표)와 과제마다 간단한 결과에서 감춘 것의 건수·안내.
        $('batch-detail').open = false;
        const countArea = clear($('batch-counts'));
        Object.entries(result.counts || {}).forEach(([key, value]) => metric(countArea, COUNT_LABELS[key] || key, value));
        metric(countArea, '실행', `${result.run.provider} · ${result.run.model} · ${result.run.run_time}`);
        if ((result.option_warnings || []).length) list(countArea, '선택 칸 경고(빈칸으로 검토, 처리내역(숨김 시트)에도 기록)', warningMessages(result.option_warnings));
        table(clear($('batch-rows')), ['입력 행 번호', '연구개발과제명', '연구개발단계', '상태', '종합 검토 결과', '고시별 검토 결과', '확인 표시', 'AI 호출', '오류 사유', '넣지 않은 관련 조항 수', '남기지 않은 세부 일치 수', '안내'], rows.map(r => {
            const brief = r.brief || {}, counts = brief.counts || {};
            return [r.row_number, r.title, givenValue(r.rnd_stage), r.status, r.overall,
                Object.entries(r.families || {}).map(([f, v]) => `${familyLabel(f)} ${v}`).join('\n'), r.flagged_clause_count, r.calls.total, r.error_reason,
                counts.hidden, counts.detail_match_dropped, (brief.hints || []).join('\n')];
        }));
    }
    async function saveReport(which) {
        if (state.busy) return;
        try { const picked = await call('select_path', 'save_report'); if (picked.cancelled) return; const saved = await call('save_report', picked.token, which); message(`결과 엑셀 저장 완료 · ${saved.name} · 과제 ${saved.count}건`); }
        catch (error) { fail(error); }
    }

    // ── 시작 ────────────────────────────────────────────────────────────────
    async function initialize() {
        if (state.ready) return;
        try {
            const initial = await call('get_initial_state');
            if (!initial || !Array.isArray(initial.families) || !Array.isArray(initial.providers) || !initial.settings || !initial.table) throw new Error('앱 초기 설정 확인 불가');
            state.initial = initial; state.settings = initial.settings; state.keyState = {...initial.key_state};
            $('sidebar-version').textContent = `v${initial.program.version}`;
            $('bottom-note').textContent = initial.note;
            const provider = clear($('provider'));
            initial.providers.forEach(p => { const option = node('option', `${p.id} · 기본 ${p.default_model}`); option.value = p.id; provider.append(option); });
            provider.value = initial.settings.provider; $('base-url').value = initial.settings.base_url || '';
            renderFamilies('single-families', 'single'); renderFamilies('batch-families', 'batch');
            renderSettingsForm(); renderRunInfo(); renderCatalogue(); renderSearchInitial();
            state.ready = true; setBusy(false); refreshEstimates();
            $('connection-status').textContent = '고시DB 연결됨'; document.body.dataset.ready = 'true'; message();
        } catch (error) { $('connection-status').textContent = '앱 연결 필요'; fail(error); setBusy(false); }
    }
    all('[data-view]').forEach(button => button.addEventListener('click', () => show(button.dataset.view)));
    ['task-title', 'task-final-goal', 'task-rnd-content', 'task-utilization'].forEach(id => $(id).addEventListener('input', updateControls));
    $('task-gov-fund').addEventListener('input', () => renderOptionNote([]));
    $('excerpt').addEventListener('input', () => setExcerptConfirmed(null));
    $('confirm-excerpt').addEventListener('click', () => setExcerptConfirmed($('excerpt').value.trim()));
    $('pick-attachment').addEventListener('click', pickAttachment); $('clear-attachment').addEventListener('click', clearAttachment);
    $('add-selection').addEventListener('click', addSelection);
    $('start-single').addEventListener('click', () => start('single')); $('start-batch').addEventListener('click', () => start('batch'));
    $('cancel-job').addEventListener('click', cancel);
    $('save-single').addEventListener('click', () => saveReport('single')); $('save-batch').addEventListener('click', () => saveReport('batch'));
    $('save-template').addEventListener('click', saveTemplate); $('pick-batch-input').addEventListener('click', pickBatchInput);
    $('provider').addEventListener('change', () => { $('api-key').value = ''; $('model').value = ''; $('base-url').value = ''; renderSettingsForm(); applySettings(true); });
    $('apply-settings').addEventListener('click', () => applySettings(false));
    $('save-key').addEventListener('click', saveKey); $('delete-key').addEventListener('click', deleteKey);
    $('search-button').addEventListener('click', runSearch);
    $('search-query').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); runSearch(); } });
    $('search-results-more').addEventListener('click', () => searchMore('results'));
    $('search-similar-more').addEventListener('click', () => searchMore('similar'));
    $('search-focus-close').addEventListener('click', closeFocus);
    $('batch-picked-close').addEventListener('click', () => showTally(null));
    window.addEventListener('pywebviewready', initialize); setBusy(false); if (window.pywebview?.api) initialize();
})();
