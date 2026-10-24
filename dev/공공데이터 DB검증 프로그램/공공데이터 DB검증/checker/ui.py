# -*- coding: utf-8 -*-
"""GUI 화면(HTML/CSS/JS). exe 패키징을 위해 외부 리소스 없이 단일 문자열로 내장."""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>파일데이터 등록 사전검토</title>
<style>
:root{
  --paper:#DCE1E6; --surface:#FBFCFD; --surface-2:#F1F4F6;
  --ink:#141A22; --ink-2:#4C5866; --ink-3:#7A8794;
  --rule:#C2CAD3; --rule-2:#DDE3E8;
  --reject:#A81E32; --action:#A9660A; --review:#2E6285; --pass:#1E6349;
  --font-body:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
  --font-data:Consolas,"D2Coding","Courier New",monospace;
  --shadow:0 1px 0 rgba(20,26,34,.06), 0 8px 24px -18px rgba(20,26,34,.5);
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{
  background:var(--paper); color:var(--ink); font-family:var(--font-body);
  font-size:14px; line-height:1.55; -webkit-font-smoothing:antialiased;
}
button,input,select,textarea{font:inherit;color:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:28px 24px 64px}

/* ---------- 머리말 ---------- */
.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
  padding-bottom:14px;border-bottom:2px solid var(--ink)}
.eyebrow{font-family:var(--font-data);font-size:11px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 6px}
h1{margin:0;font-size:29px;font-weight:800;letter-spacing:-.035em}
.h1 span{color:var(--ink-3);font-weight:700}
.criteria{font-family:var(--font-data);font-size:11px;color:var(--ink-2);
  border:1px solid var(--rule);background:var(--surface);padding:5px 9px;white-space:nowrap}

/* ---------- 단계 ---------- */
.step{margin-top:26px}
.step-label{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.step-num{font-family:var(--font-data);font-size:11px;color:var(--ink-3);
  border:1px solid var(--rule);padding:2px 6px}
.step-title{font-weight:800;letter-spacing:-.02em}
.hint{color:var(--ink-2);font-size:12.5px;margin:0}

/* ---------- 드롭존 ---------- */
.drop{background:var(--surface);border:1px dashed var(--rule);padding:22px;
  display:flex;align-items:center;justify-content:space-between;gap:18px;
  transition:border-color .15s, background .15s}
.drop.on{border-color:var(--review);background:#EEF4F8}
.drop p{margin:0;color:var(--ink-2);font-size:13px}
.btn{border:1px solid var(--ink);background:var(--ink);color:#fff;padding:9px 16px;
  font-weight:700;cursor:pointer;letter-spacing:-.01em}
.btn:hover{background:#000}
.btn:focus-visible,.chip:focus-visible,summary:focus-visible{outline:2px solid var(--review);outline-offset:2px}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--rule)}
.btn.ghost:hover{border-color:var(--ink);background:var(--surface-2)}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:14px}

/* ---------- 파일 목록 ---------- */
.files{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:1px}
.files li{background:var(--surface);border:1px solid var(--rule-2);padding:8px 12px;
  display:flex;justify-content:space-between;gap:12px;font-size:13px}
.files .fname{font-weight:700}
.files .fmeta{font-family:var(--font-data);font-size:11.5px;color:var(--ink-3)}
.files button{border:0;background:none;color:var(--ink-3);cursor:pointer;padding:0 2px}
.files button:hover{color:var(--reject)}

/* ---------- 메타 입력 ---------- */
details.meta{background:var(--surface);border:1px solid var(--rule-2)}
details.meta summary{cursor:pointer;padding:12px 14px;font-weight:700;list-style:none;
  display:flex;justify-content:space-between;align-items:center}
details.meta summary::-webkit-details-marker{display:none}
details.meta summary::after{content:"펼치기";font-family:var(--font-data);font-size:11px;
  color:var(--ink-3);letter-spacing:.08em}
details.meta[open] summary::after{content:"접기"}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
  gap:12px 16px;padding:4px 14px 18px}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:11.5px;font-family:var(--font-data);letter-spacing:.06em;color:var(--ink-2)}
.field input,.field select,.field textarea{
  border:1px solid var(--rule);background:#fff;padding:7px 9px;font-size:13px;width:100%}
.field textarea{resize:vertical;min-height:62px}
.field input:focus,.field select:focus,.field textarea:focus{outline:2px solid var(--review);outline-offset:-1px}
.field.wide{grid-column:1/-1}

/* ---------- 결과 ---------- */
#result{margin-top:30px}
.tabs{display:flex;gap:1px;border-bottom:1px solid var(--rule);margin-bottom:0}
.tab{background:var(--surface-2);border:1px solid var(--rule);border-bottom:0;
  padding:8px 14px;cursor:pointer;font-size:13px;color:var(--ink-2);max-width:260px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tab[aria-selected="true"]{background:var(--surface);color:var(--ink);font-weight:800}
.tab .dot{display:inline-block;width:7px;height:7px;margin-right:7px;border-radius:50%}
.panel{background:var(--surface);border:1px solid var(--rule);border-top:0;
  display:grid;grid-template-columns:264px 1fr}
.rail{border-right:1px solid var(--rule-2);padding:20px 18px}
.body{padding:20px 20px 26px;min-width:0}

/* 판정 도장 */
.stamp{border:2.5px solid currentColor;padding:12px 10px;text-align:center;
  font-weight:800;font-size:26px;letter-spacing:.16em;transform:rotate(-3.5deg);
  width:fit-content;margin:2px auto 18px;opacity:.92}
.stamp small{display:block;font-family:var(--font-data);font-size:9.5px;letter-spacing:.2em;
  font-weight:700;opacity:.8;margin-top:2px}
.lv-반려{color:var(--reject)} .lv-보완필요{color:var(--action)}
.lv-확인권장{color:var(--review)} .lv-적합{color:var(--pass)}
.bg-반려{background:var(--reject)} .bg-보완필요{background:var(--action)}
.bg-확인권장{background:var(--review)} .bg-적합{background:var(--pass)}

.tally{list-style:none;margin:0 0 18px;padding:0}
.tally li{display:flex;justify-content:space-between;align-items:baseline;
  padding:6px 0;border-bottom:1px solid var(--rule-2)}
.tally b{font-family:var(--font-data);font-size:17px}
.facts{list-style:none;margin:0;padding:0;font-size:12.5px}
.facts li{display:flex;justify-content:space-between;gap:8px;padding:4px 0;color:var(--ink-2)}
.facts span{font-family:var(--font-data);color:var(--ink);text-align:right;word-break:break-all}

/* 셀 미니맵 (시그니처) */
.map-head{display:flex;align-items:baseline;justify-content:space-between;margin:0 0 8px}
.map-title{font-family:var(--font-data);font-size:11px;letter-spacing:.14em;color:var(--ink-3)}
.legend{display:flex;gap:10px;font-family:var(--font-data);font-size:10.5px;color:var(--ink-2)}
.legend i{display:inline-block;width:8px;height:8px;margin-right:4px}
.map{overflow:auto;max-height:190px;border:1px solid var(--rule-2);background:#fff;
  padding:6px;margin-bottom:22px}
.map table{border-collapse:collapse}
.map th{position:sticky;top:0;background:#fff;font-family:var(--font-data);font-size:9px;
  color:var(--ink-3);font-weight:400;padding:0 0 2px;min-width:11px}
.map td.rn{font-family:var(--font-data);font-size:9px;color:var(--ink-3);
  padding-right:5px;text-align:right;position:sticky;left:0;background:#fff}
.cell{width:11px;height:11px;background:var(--rule-2);border:.5px solid #fff}
.cell.hit{transform:scale(1)}
.cell.focus{outline:1.5px solid var(--ink);outline-offset:0}
@media (prefers-reduced-motion:no-preference){
  .cell{animation:pop .25s ease-out both}
  @keyframes pop{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}
  .finding{animation:rise .28s ease-out both}
  @keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
}

/* 지적사항 */
.group-label{font-family:var(--font-data);font-size:11px;letter-spacing:.14em;
  color:var(--ink-3);margin:18px 0 8px;display:flex;align-items:center;gap:8px}
.group-label::after{content:"";flex:1;height:1px;background:var(--rule-2)}
.finding{border:1px solid var(--rule-2);border-left:3px solid currentColor;
  background:#fff;padding:12px 14px;margin-bottom:8px}
.finding .top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.rule{font-family:var(--font-data);font-size:11px;font-weight:700;letter-spacing:.04em;
  border:1px solid currentColor;padding:1px 6px}
.item{font-size:11.5px;color:var(--ink-2)}
.cnt{font-family:var(--font-data);font-size:11px;color:var(--ink-3);margin-left:auto}
.msg{color:var(--ink);font-weight:700;margin:0 0 5px;letter-spacing:-.01em}
.fix{color:var(--ink-2);font-size:13px;margin:0}
.fix::before{content:"조치 ";font-family:var(--font-data);font-size:10.5px;
  letter-spacing:.1em;color:var(--ink-3)}
.refs{display:flex;flex-wrap:wrap;gap:4px;margin-top:9px}
.chip{font-family:var(--font-data);font-size:10.5px;background:var(--surface-2);
  border:1px solid var(--rule-2);padding:2px 6px;cursor:pointer}
.chip:hover{border-color:var(--ink);background:#fff}
.chip.more{cursor:default;color:var(--ink-3)}
.samples{font-family:var(--font-data);font-size:11.5px;color:var(--ink-2);
  background:var(--surface-2);padding:7px 9px;margin-top:9px;word-break:break-all}

/* 빈 상태 · 진행 */
.empty{background:var(--surface);border:1px solid var(--rule-2);padding:34px 22px;text-align:center}
.empty p{margin:0 0 4px;font-weight:700}
.empty small{color:var(--ink-3)}
.working{font-family:var(--font-data);font-size:12px;color:var(--ink-2)}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);
  background:var(--ink);color:#fff;padding:9px 16px;font-size:13px;box-shadow:var(--shadow);
  opacity:0;pointer-events:none;transition:opacity .18s}
.toast.on{opacity:1}
.footer{margin-top:40px;text-align:center;font-size:11.5px;color:var(--ink-3)}
@media (max-width:820px){
  .panel{grid-template-columns:1fr}
  .rail{border-right:0;border-bottom:1px solid var(--rule-2)}
}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div>
      <p class="eyebrow">공공데이터포털 · 파일데이터 등록</p>
      <h1 class="h1">등록 전 반려 사유 <span>미리 확인</span></h1>
    </div>
    <div class="criteria" id="criteria">기준 26.2~</div>
  </header>

  <section class="step">
    <div class="step-label"><span class="step-num">01</span>
      <span class="step-title">파일 올리기</span></div>
    <div class="drop" id="drop">
      <p id="dropText">CSV · XLSX · ZIP 파일을 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.</p>
      <button class="btn" id="pick">파일 선택</button>
    </div>
    <ul class="files" id="files"></ul>
  </section>

  <section class="step">
    <div class="step-label"><span class="step-num">02</span>
      <span class="step-title">등록 메타정보</span></div>
    <p class="hint">비워 두면 파일 내용만 검사합니다. 입력하면 목록명·데이터명·키워드·설명 기준까지 함께 검토합니다.</p>
    <details class="meta">
      <summary>목록명 · 데이터명 · 키워드 · 설명 등 15개 항목</summary>
      <div class="grid" id="metaGrid"></div>
    </details>
    <div class="btn-row">
      <button class="btn" id="run" disabled>검토 실행</button>
      <button class="btn ghost" id="saveXlsx" disabled>엑셀로 저장</button>
      <button class="btn ghost" id="saveMd" disabled>마크다운으로 저장</button>
      <span class="working" id="working"></span>
    </div>
  </section>

  <section id="result">
    <div class="empty">
      <p>아직 검토한 파일이 없습니다.</p>
      <small>파일을 올리고 검토를 실행하면 기준 조항별 지적사항과 해당 셀 위치가 표시됩니다.</small>
    </div>
  </section>

  <footer class="footer">powered by min</footer>
</div>
<div class="toast" id="toast"></div>

<script>
const META_FIELDS=[
 ["목록명","text","예: 공공데이터활용지원센터_자전거보관소 현황"],
 ["데이터명","text","기관명 + 직관적 데이터 명칭"],
 ["기관명","text","등록 기관"],
 ["키워드","text","콤마로 구분해 3~8개"],
 ["등록확장자","text","예: csv"],
 ["데이터기준일","text","YYYY-MM-DD"],
 ["갱신주기","select","연간|반기|분기|월간|수시"],
 ["차기등록예정일","text","YYYY-MM-DD"],
 ["공공누리유형","select","제1유형|제2유형|제3유형|제4유형"],
 ["저작권포함","select","아니오|예"],
 ["제공신청여부","select","아니오|예"],
 ["제공번호","text","제공신청 시 필수"],
 ["중복확인","select","미확인|완료"],
 ["링크URL","text","링크데이터로 등록하는 경우"],
 ["설명","textarea","생성·수집 목적과 활용성을 50자 이상"],
 ["기타유의사항","textarea","공란 사유, 단위, 기준일 상이 사유 등"],
];
const LEVELS=["반려","보완필요","확인권장"];
let files=[], results=[], active=0, focused=null;

const $=id=>document.getElementById(id);
function toast(m){const t=$("toast");t.textContent=m;t.classList.add("on");
  clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("on"),2200);}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

/* 메타 입력 폼 */
$("metaGrid").innerHTML=META_FIELDS.map(([k,t,ph])=>{
  const wide=t==="textarea"?" wide":"";
  let ctrl;
  if(t==="select"){
    ctrl=`<select id="m_${k}"><option value=""></option>`+
      ph.split("|").map(o=>`<option>${o}</option>`).join("")+`</select>`;
  }else if(t==="textarea"){
    ctrl=`<textarea id="m_${k}" placeholder="${ph}"></textarea>`;
  }else{
    ctrl=`<input id="m_${k}" placeholder="${ph}">`;
  }
  return `<div class="field${wide}"><label for="m_${k}">${k}</label>${ctrl}</div>`;
}).join("");
function readMeta(){const o={};META_FIELDS.forEach(([k])=>{
  const v=$("m_"+k).value.trim(); if(v)o[k]=v;});return o;}

/* 파일 목록 */
function renderFiles(){
  $("files").innerHTML=files.map((f,i)=>
    `<li><span class="fname">${esc(f.split(/[\\/]/).pop())}</span>
     <span class="fmeta">${esc(f)} <button data-i="${i}" title="목록에서 제거">제거</button></span></li>`).join("");
  $("files").querySelectorAll("button").forEach(b=>b.onclick=()=>{
    files.splice(+b.dataset.i,1);renderFiles();});
  $("run").disabled=files.length===0;
  $("dropText").textContent=files.length
    ? `${files.length}개 파일이 준비되었습니다. 더 올리려면 끌어다 놓으세요.`
    : "CSV · XLSX · ZIP 파일을 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.";
}
function addFiles(list){
  let added=0;
  (list||[]).forEach(p=>{if(p&&!files.includes(p)){files.push(p);added++;}});
  renderFiles();
  if(!added)toast("추가된 파일이 없습니다. 경로를 확인하세요.");
}

$("pick").onclick=async()=>{
  const got=await window.pywebview.api.pick_files();
  addFiles(got);
};
const drop=$("drop");
["dragenter","dragover"].forEach(e=>drop.addEventListener(e,ev=>{
  ev.preventDefault();drop.classList.add("on");}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{
  ev.preventDefault();drop.classList.remove("on");}));
drop.addEventListener("drop",ev=>{
  const paths=[...(ev.dataTransfer.files||[])]
    .map(f=>f.pywebviewFullPath||f.path||"").filter(Boolean);
  if(paths.length)addFiles(paths);
  else toast("이 창에서는 경로를 읽지 못했습니다. 파일 선택 버튼을 사용하세요.");
});

/* 검토 실행 */
$("run").onclick=async()=>{
  $("run").disabled=true;$("working").textContent="검토 중…";
  try{
    results=await window.pywebview.api.run(files,readMeta());
    active=0;focused=null;render();
    $("saveXlsx").disabled=$("saveMd").disabled=false;
    $("working").textContent=`${results.length}개 파일 검토 완료`;
  }catch(e){
    $("working").textContent="";toast("검토 중 오류: "+e);
  }
  $("run").disabled=false;
};
$("saveXlsx").onclick=()=>save("xlsx");
$("saveMd").onclick=()=>save("md");
async function save(kind){
  const p=await window.pywebview.api.save_report(kind);
  toast(p?`저장했습니다: ${p}`:"저장을 취소했습니다.");
}

/* 결과 렌더 */
function render(){
  if(!results.length)return;
  const tabs=results.map((r,i)=>
    `<div class="tab" role="tab" data-i="${i}" tabindex="0"
      aria-selected="${i===active}"><span class="dot bg-${r.verdict}"></span>${esc(r.file_name)}</div>`).join("");
  $("result").innerHTML=`<div class="tabs" role="tablist">${tabs}</div>${panel(results[active])}`;
  $("result").querySelectorAll(".tab").forEach(t=>{
    t.onclick=()=>{active=+t.dataset.i;focused=null;render();};
    t.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();t.click();}};
  });
  bindRefs();
}
function panel(r){
  const c=r.counts;
  const facts=[["형식",r.ext.toUpperCase()||"-"],["규모",`${r.rows}행 × ${r.cols}열`],
    ["인코딩",r.encoding||"-"],["구분자",r.delimiter||"-"],
    ["용량",(r.file_size/1024).toFixed(0)+" KB"],
    ["기준일 후보",r.suggested_base_date||"-"]];
  const groups=LEVELS.map(lv=>{
    const fs=r.findings.filter(f=>f.level===lv);
    if(!fs.length)return "";
    return `<div class="group-label">${lv} ${fs.length}건</div>`+fs.map(card).join("");
  }).join("");
  return `<div class="panel" role="tabpanel">
    <aside class="rail">
      <div class="stamp lv-${r.verdict}">${r.verdict}<small>사전검토</small></div>
      <ul class="tally">${LEVELS.map(lv=>
        `<li class="lv-${lv}"><span>${lv}</span><b>${c[lv]}</b></li>`).join("")}</ul>
      <ul class="facts">${facts.map(([k,v])=>
        `<li>${k}<span>${esc(v)}</span></li>`).join("")}</ul>
    </aside>
    <div class="body">
      ${minimap(r)}
      ${groups||`<div class="empty"><p>기준을 모두 충족합니다.</p>
        <small>지적사항 없이 등록 가능한 상태입니다.</small></div>`}
    </div></div>`;
}
function card(f){
  const shown=f.locations.slice(0,24);
  const more=f.count>shown.length?`<span class="chip more">외 ${f.count-shown.length}건</span>`:"";
  return `<article class="finding lv-${f.level}">
    <div class="top"><span class="rule">${esc(f.rule_id)}</span>
      <span class="item">${esc(f.item)}</span>
      <span class="cnt">${f.count}건</span></div>
    <p class="msg">${esc(f.message)}</p>
    ${f.fix?`<p class="fix">${esc(f.fix)}</p>`:""}
    ${shown.length?`<div class="refs">${shown.map(l=>
      `<button class="chip" data-ref="${esc(l)}">${esc(l)}</button>`).join("")}${more}</div>`:""}
    ${f.samples.length?`<div class="samples">${f.samples.map(esc).join(" · ")}</div>`:""}
  </article>`;
}
function minimap(r){
  const cells=Object.entries(r.grid).filter(([k])=>/^[A-Z]+\d+$/.test(k));
  if(!r.cols||!r.rows)return "";
  const maxC=Math.min(r.cols,40), maxR=Math.min(r.rows,120);
  const lv={};cells.forEach(([k,v])=>lv[k]=v);
  const L=i=>{let s="";i++;while(i){const m=(i-1)%26;s=String.fromCharCode(65+m)+s;i=Math.floor((i-1)/26);}return s;};
  let head="<tr><th></th>";
  for(let c=0;c<maxC;c++)head+=`<th>${L(c)}</th>`;
  head+="</tr>";
  let rows="";
  for(let rw=1;rw<=maxR;rw++){
    rows+=`<tr><td class="rn">${rw}</td>`;
    for(let c=0;c<maxC;c++){
      const ref=L(c)+rw, hit=lv[ref];
      rows+=`<td><div class="cell ${hit?"hit bg-"+hit:""}" data-cell="${ref}"
        title="${ref}${hit?" · "+hit:""}"></div></td>`;
    }
    rows+="</tr>";
  }
  const cut=(r.cols>maxC||r.rows>maxR)?` · 앞쪽 ${maxC}열 ${maxR}행만 표시`:"";
  return `<div class="map-head">
      <span class="map-title">셀 위치 지도 — 1행은 항목명${cut}</span>
      <span class="legend">${LEVELS.map(l=>
        `<span><i class="bg-${l}"></i>${l}</span>`).join("")}</span></div>
    <div class="map"><table>${head}${rows}</table></div>`;
}
function bindRefs(){
  document.querySelectorAll(".chip[data-ref]").forEach(b=>b.onclick=()=>{
    const ref=b.dataset.ref;
    document.querySelectorAll(".cell.focus").forEach(c=>c.classList.remove("focus"));
    const t=document.querySelector(`.cell[data-cell="${ref}"]`);
    if(t){t.classList.add("focus");
      if(t.scrollIntoView)t.scrollIntoView({block:"center",inline:"center"});}
    else toast(`${ref}은 지도 표시 범위를 벗어났습니다.`);
  });
}
window.addEventListener("pywebviewready",async()=>{
  try{$("criteria").textContent=await window.pywebview.api.criteria();}catch(e){}
});
</script>
</body>
</html>
"""
