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
body{background:var(--paper);color:var(--ink);font-family:var(--font-body);
  font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}
button,input,select,textarea{font:inherit;color:inherit}
svg.ic{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;
  stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px}
svg.ic.sm{width:13px;height:13px;stroke-width:1.8}
svg.ic.lg{width:22px;height:22px;stroke-width:1.4}
.wrap{max-width:1180px;margin:0 auto;padding:28px 24px 64px}

.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
  padding-bottom:14px;border-bottom:2px solid var(--ink)}
.eyebrow{font-family:var(--font-data);font-size:11px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 6px}
h1{margin:0;font-size:29px;font-weight:800;letter-spacing:-.035em}
h1 span{color:var(--ink-3);font-weight:700}
.criteria{font-family:var(--font-data);font-size:11px;color:var(--ink-2);
  border:1px solid var(--rule);background:var(--surface);padding:5px 9px;white-space:nowrap}

.step{margin-top:26px}
.step-label{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.step-num{font-family:var(--font-data);font-size:11px;color:var(--ink-3);
  border:1px solid var(--rule);padding:2px 6px}
.step-title{font-weight:800;letter-spacing:-.02em}
.hint{color:var(--ink-2);font-size:12.5px;margin:0}

.drop{background:var(--surface);border:1px dashed var(--rule);padding:20px 22px;
  display:flex;align-items:center;justify-content:space-between;gap:18px;
  transition:border-color .15s, background .15s}
.drop.on{border-color:var(--review);background:#EEF4F8}
.drop .lead{display:flex;align-items:center;gap:12px;color:var(--ink-2);font-size:13px}
.drop .lead svg{color:var(--ink-3)}
.btn{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--ink);
  background:var(--ink);color:#fff;padding:9px 15px;font-weight:700;cursor:pointer;
  letter-spacing:-.01em}
.btn:hover{background:#000}
.btn:focus-visible,.chip:focus-visible,summary:focus-visible,.tab:focus-visible,
input:focus-visible{outline:2px solid var(--review);outline-offset:2px}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--rule)}
.btn.ghost:hover{border-color:var(--ink);background:var(--surface-2)}
.btn.sm{padding:5px 10px;font-size:12px;font-weight:700}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:14px}

.files{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:1px}
.files li{background:var(--surface);border:1px solid var(--rule-2);padding:7px 12px;
  display:flex;justify-content:space-between;gap:12px;font-size:13px;align-items:center}
.files .fname{display:flex;align-items:center;gap:8px;font-weight:700}
.files .fname svg{color:var(--ink-3)}
.files .fmeta{display:flex;align-items:center;gap:10px;font-family:var(--font-data);
  font-size:11.5px;color:var(--ink-3)}
.files button{border:0;background:none;color:var(--ink-3);cursor:pointer;padding:2px;
  display:inline-flex}
.files button:hover{color:var(--reject)}

details.meta{background:var(--surface);border:1px solid var(--rule-2)}
details.meta summary{cursor:pointer;padding:12px 14px;font-weight:700;list-style:none;
  display:flex;justify-content:space-between;align-items:center;gap:8px}
details.meta summary::-webkit-details-marker{display:none}
details.meta summary .caret{transition:transform .18s;color:var(--ink-3)}
details.meta[open] summary .caret{transform:rotate(180deg)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
  gap:12px 16px;padding:4px 14px 18px}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:11.5px;font-family:var(--font-data);letter-spacing:.06em;color:var(--ink-2)}
.field input,.field select,.field textarea{border:1px solid var(--rule);background:#fff;
  padding:7px 9px;font-size:13px;width:100%}
.field textarea{resize:vertical;min-height:62px}
.field input:focus,.field select:focus,.field textarea:focus{outline:2px solid var(--review);outline-offset:-1px}
.field.wide{grid-column:1/-1}

#result{margin-top:30px}
.tabs{display:flex;gap:1px;border-bottom:1px solid var(--rule)}
.tab{display:flex;align-items:center;gap:7px;background:var(--surface-2);
  border:1px solid var(--rule);border-bottom:0;padding:8px 14px;cursor:pointer;
  font-size:13px;color:var(--ink-2);max-width:280px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.tab[aria-selected="true"]{background:var(--surface);color:var(--ink);font-weight:800}
.tab .dot{display:inline-block;width:7px;height:7px;border-radius:50%;flex:none}
.panel{background:var(--surface);border:1px solid var(--rule);border-top:0;
  display:grid;grid-template-columns:264px 1fr}
.rail{border-right:1px solid var(--rule-2);padding:20px 18px}
.body{padding:18px 20px 26px;min-width:0}

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
.tally li{display:flex;justify-content:space-between;align-items:center;
  padding:6px 0;border-bottom:1px solid var(--rule-2)}
.tally .lb{display:flex;align-items:center;gap:7px}
.tally b{font-family:var(--font-data);font-size:17px}
.facts{list-style:none;margin:0;padding:0;font-size:12.5px}
.facts li{display:flex;justify-content:space-between;gap:8px;padding:4px 0;color:var(--ink-2)}
.facts span{font-family:var(--font-data);color:var(--ink);text-align:right;word-break:break-all}

.map-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 8px}
.map-title{display:flex;align-items:center;gap:7px;font-family:var(--font-data);
  font-size:11px;letter-spacing:.12em;color:var(--ink-3)}
.map-read{font-family:var(--font-data);font-size:11px;color:var(--ink-2);min-width:120px;
  text-align:right}
.legend{display:flex;gap:10px;font-family:var(--font-data);font-size:10.5px;color:var(--ink-2)}
.legend i{display:inline-block;width:8px;height:8px;margin-right:4px}
.map{overflow:auto;max-height:340px;border:1px solid var(--rule-2);background:#fff;
  margin-bottom:18px}
.map canvas{display:block;cursor:crosshair}

.fixbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:var(--surface-2);
  border:1px solid var(--rule-2);padding:10px 12px;margin-bottom:16px}
.fixbar .lead{display:flex;align-items:center;gap:7px;font-weight:700;font-size:13px}
.fixbar .sel{font-family:var(--font-data);font-size:11.5px;color:var(--ink-2);margin-left:auto}
.fixnote{font-size:12px;color:var(--ink-2);margin:0 0 14px;padding-left:2px}
.fixdone{border:1px solid var(--pass);border-left:3px solid var(--pass);background:#fff;
  padding:11px 13px;margin-bottom:16px;font-size:13px}
.fixdone b{color:var(--pass)}
.fixdone .path{font-family:var(--font-data);font-size:11.5px;color:var(--ink-2);
  word-break:break-all;display:block;margin-top:3px}

.group-label{display:flex;align-items:center;gap:8px;font-family:var(--font-data);
  font-size:11px;letter-spacing:.12em;color:var(--ink-3);margin:18px 0 8px}
.group-label .line{flex:1;height:1px;background:var(--rule-2)}
.finding{border:1px solid var(--rule-2);border-left:3px solid currentColor;
  background:#fff;padding:11px 13px;margin-bottom:8px}
.finding.flash{animation:flash 1.1s ease-out}
@keyframes flash{0%,40%{background:#FFF6D6}100%{background:#fff}}
.finding .top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.finding .top input[type=checkbox]{width:14px;height:14px;accent-color:var(--ink);margin:0;cursor:pointer}
.rule{font-family:var(--font-data);font-size:11px;font-weight:700;letter-spacing:.04em;
  border:1px solid currentColor;padding:1px 6px}
.item{font-size:11.5px;color:var(--ink-2)}
.cnt{font-family:var(--font-data);font-size:11px;color:var(--ink-3);margin-left:auto}
.msg{color:var(--ink);font-weight:700;margin:0 0 5px;letter-spacing:-.01em}
.fix{color:var(--ink-2);font-size:13px;margin:0;display:flex;gap:6px}
.fix .tag{font-family:var(--font-data);font-size:10.5px;letter-spacing:.1em;
  color:var(--ink-3);flex:none;padding-top:2px}
.manual{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ink-3);
  margin-top:7px}
.refs{display:flex;flex-wrap:wrap;gap:4px;margin-top:9px}
.chip{font-family:var(--font-data);font-size:10.5px;background:var(--surface-2);
  border:1px solid var(--rule-2);padding:2px 6px;cursor:pointer}
.chip:hover{border-color:var(--ink);background:#fff}
.chip.more{cursor:default;color:var(--ink-3)}
.samples{font-family:var(--font-data);font-size:11.5px;color:var(--ink-2);
  background:var(--surface-2);padding:7px 9px;margin-top:9px;word-break:break-all}

.empty{background:var(--surface);border:1px solid var(--rule-2);padding:34px 22px;text-align:center}
.empty svg{color:var(--ink-3);margin-bottom:8px}
.empty p{margin:0 0 4px;font-weight:700}
.empty small{color:var(--ink-3)}
.working{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-data);
  font-size:12px;color:var(--ink-2)}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--ink);
  color:#fff;padding:9px 16px;font-size:13px;box-shadow:var(--shadow);opacity:0;
  pointer-events:none;transition:opacity .18s;max-width:80%}
.toast.on{opacity:1}
@media (prefers-reduced-motion:reduce){.finding.flash{animation:none}}
@media (max-width:820px){.panel{grid-template-columns:1fr}
  .rail{border-right:0;border-bottom:1px solid var(--rule-2)}}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div>
      <p class="eyebrow">공공데이터포털 · 파일데이터 등록</p>
      <h1>등록 전 반려 사유 <span>미리 확인</span></h1>
    </div>
    <div class="criteria" id="criteria">기준 26.2~</div>
  </header>

  <section class="step">
    <div class="step-label"><span class="step-num">01</span>
      <span class="step-title">파일 올리기</span></div>
    <div class="drop" id="drop">
      <span class="lead"><span id="dropIcon"></span><span id="dropText">CSV · XLSX · JSON · ZIP 파일을 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.</span></span>
      <button class="btn" id="pick"></button>
    </div>
    <ul class="files" id="files"></ul>
  </section>

  <section class="step">
    <div class="step-label"><span class="step-num">02</span>
      <span class="step-title">등록 메타정보</span></div>
    <p class="hint">비워 두면 파일 내용만 검사합니다. 입력하면 목록명·데이터명·키워드·설명 기준까지 함께 검토합니다.</p>
    <details class="meta">
      <summary><span>목록명 · 데이터명 · 키워드 · 설명 등 16개 항목</span><span class="caret" id="caret"></span></summary>
      <div class="grid" id="metaGrid"></div>
    </details>
    <div class="btn-row">
      <button class="btn" id="run" disabled></button>
      <button class="btn ghost" id="saveXlsx" disabled></button>
      <span class="working" id="working"></span>
    </div>
  </section>

  <section id="result"></section>
</div>
<div class="toast" id="toast"></div>

<script>
const IC={
 upload:'<path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/><path d="M12 3v13"/><path d="m7 8 5-5 5 5"/>',
 file:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
 folder:'<path d="M4 6h5l2 2h9v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z"/>',
 x:'<path d="M6 6l12 12M18 6 6 18"/>',
 caret:'<path d="m6 9 6 6 6-6"/>',
 scan:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/><path d="m8.5 11 2 2 4-4"/>',
 grid:'<rect x="3" y="3" width="18" height="18" rx="1.5"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
 sheet:'<rect x="3" y="3" width="18" height="18" rx="1.5"/><path d="M3 9h18M9 9v12"/>',
 wand:'<path d="M15 4V2M15 10V8M12 6h-2M20 6h-2M17.8 8.8l1.4 1.4M17.8 3.2l1.4-1.4M12.2 3.2 10.8 1.8"/><path d="m3 21 9-9 2 2-9 9z"/>',
 check:'<path d="M20 6 9 17l-5-5"/>',
 alert:'<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 17a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
 flag:'<path d="M4 21V4h9l1 2h6v9h-7l-1-2H4"/>',
 eye:'<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z"/><circle cx="12" cy="12" r="2.5"/>',
 lock:'<rect x="4" y="10" width="16" height="10" rx="1.5"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
 spin:'<path d="M12 3a9 9 0 1 0 9 9"/>',
 clear:'<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
};
const svg=(k,c)=>`<svg class="ic ${c||''}" viewBox="0 0 24 24" aria-hidden="true">${IC[k]}</svg>`;
const LEVELS=["반려","보완필요","확인권장"];
const LVICON={"반려":"alert","보완필요":"flag","확인권장":"eye","적합":"check"};
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
const MAP={GUT:34,HDR:15,CW:11,CH:11,MAXC:50,MAXR:1000};
let files=[], results=[], active=0, picked={}, fixInfo={}, mapFocus=null;

const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(m){const t=$("toast");t.textContent=m;t.classList.add("on");
  clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("on"),2600);}
const selOf=i=>(picked[i]=picked[i]||new Set());
const cssVar=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();

$("dropIcon").innerHTML=svg("upload","lg");
$("pick").innerHTML=svg("folder")+"파일 선택";
$("run").innerHTML=svg("scan")+"검토 실행";
$("saveXlsx").innerHTML=svg("sheet")+"엑셀로 저장";
$("caret").innerHTML=svg("caret","sm");
$("result").innerHTML=`<div class="empty">${svg("grid","lg")}
  <p>아직 검토한 파일이 없습니다.</p>
  <small>파일을 올리고 검토를 실행하면 기준 조항별 지적사항과 해당 셀 위치가 표시됩니다.</small></div>`;

$("metaGrid").innerHTML=META_FIELDS.map(([k,t,ph])=>{
  const wide=t==="textarea"?" wide":"";
  let ctrl;
  if(t==="select"){ctrl=`<select id="m_${k}"><option value=""></option>`+
    ph.split("|").map(o=>`<option>${o}</option>`).join("")+`</select>`;}
  else if(t==="textarea"){ctrl=`<textarea id="m_${k}" placeholder="${ph}"></textarea>`;}
  else{ctrl=`<input id="m_${k}" placeholder="${ph}">`;}
  return `<div class="field${wide}"><label for="m_${k}">${k}</label>${ctrl}</div>`;
}).join("");
const readMeta=()=>{const o={};META_FIELDS.forEach(([k])=>{const v=$("m_"+k).value.trim();if(v)o[k]=v;});return o;};

function renderFiles(){
  $("files").innerHTML=files.map((f,i)=>
    `<li><span class="fname">${svg("file","sm")}${esc(f.split(/[\\/]/).pop())}</span>
     <span class="fmeta">${esc(f)}
     <button data-i="${i}" aria-label="목록에서 제거">${svg("x","sm")}</button></span></li>`).join("");
  $("files").querySelectorAll("button").forEach(b=>b.onclick=()=>{
    files.splice(+b.dataset.i,1);renderFiles();});
  $("run").disabled=files.length===0;
  $("dropText").textContent=files.length
    ? `${files.length}개 파일이 준비되었습니다. 더 올리려면 끌어다 놓으세요.`
    : "CSV · XLSX · JSON · ZIP 파일을 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.";
}
function addFiles(list){
  let added=0;(list||[]).forEach(p=>{if(p&&!files.includes(p)){files.push(p);added++;}});
  renderFiles();
  if(!added)toast("추가된 파일이 없습니다. 경로를 확인하세요.");
}
$("pick").onclick=async()=>addFiles(await window.pywebview.api.pick_files());
const drop=$("drop");
["dragenter","dragover"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("on");}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("on");}));
drop.addEventListener("drop",ev=>{
  const paths=[...(ev.dataTransfer.files||[])].map(f=>f.pywebviewFullPath||f.path||"").filter(Boolean);
  paths.length?addFiles(paths):toast("이 창에서는 경로를 읽지 못했습니다. 파일 선택 버튼을 사용하세요.");
});

$("run").onclick=async()=>{
  $("run").disabled=true;$("working").innerHTML=svg("spin","sm")+"검토 중…";
  try{
    results=await window.pywebview.api.run(files,readMeta());
    active=0;picked={};fixInfo={};render();
    $("saveXlsx").disabled=false;
    $("working").textContent=`${results.length}개 파일 검토 완료`;
  }catch(e){$("working").textContent="";toast("검토 중 오류: "+e);}
  $("run").disabled=false;
};
$("saveXlsx").onclick=async()=>{
  const p=await window.pywebview.api.save_report();
  toast(p?`저장했습니다: ${p}`:"저장을 취소했습니다.");
};

function render(){
  if(!results.length)return;
  const tabs=results.map((r,i)=>
    `<div class="tab" role="tab" data-i="${i}" tabindex="0" aria-selected="${i===active}">
      <span class="dot bg-${r.verdict}"></span>${esc(r.file_name)}</div>`).join("");
  $("result").innerHTML=`<div class="tabs" role="tablist">${tabs}</div>${panel(results[active])}`;
  $("result").querySelectorAll(".tab").forEach(t=>{
    t.onclick=()=>{active=+t.dataset.i;mapFocus=null;render();};
    t.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();t.click();}};
  });
  bind();
  drawMap(results[active]);
}
function panel(r){
  const c=r.counts;
  const facts=[["형식",(r.ext||"").toUpperCase()||"-"],["규모",`${r.rows}행 × ${r.cols}열`],
    ["인코딩",r.encoding||"-"],["구분자",r.delimiter||"-"],
    ["용량",(r.file_size/1024).toFixed(0)+" KB"],["기준일 후보",r.suggested_base_date||"-"]];
  const groups=LEVELS.map(lv=>{
    const fs=r.findings.filter(f=>f.level===lv);
    if(!fs.length)return "";
    const n=fs.filter(f=>f.fixable).length;
    return `<div class="group-label">${svg(LVICON[lv],"sm")}<span class="lv-${lv}">${lv} ${fs.length}건</span>
      <span class="line"></span>${n?`<button class="btn ghost sm" data-lv="${lv}">${svg("wand","sm")}이 등급 ${n}건 선택</button>`:""}</div>`
      +fs.map(card).join("");
  }).join("");
  return `<div class="panel" role="tabpanel">
    <aside class="rail">
      <div class="stamp lv-${r.verdict}">${r.verdict}<small>사전검토</small></div>
      <ul class="tally">${LEVELS.map(lv=>
        `<li class="lv-${lv}"><span class="lb">${svg(LVICON[lv],"sm")}${lv}</span><b>${c[lv]}</b></li>`).join("")}</ul>
      <ul class="facts">${facts.map(([k,v])=>`<li>${k}<span>${esc(v)}</span></li>`).join("")}</ul>
    </aside>
    <div class="body">${minimap(r)}${fixBar(r)}${fixResult()}
      ${groups||`<div class="empty">${svg("check","lg")}<p>기준을 모두 충족합니다.</p>
        <small>지적사항 없이 등록 가능한 상태입니다.</small></div>`}
    </div></div>`;
}
function card(f){
  const shown=f.locations.slice(0,24);
  const more=f.count>shown.length?`<span class="chip more">외 ${f.count-shown.length}건</span>`:"";
  const on=selOf(active).has(f.rule_id);
  const box=f.fixable
    ? `<input type="checkbox" class="fx" data-rule="${esc(f.rule_id)}" ${on?"checked":""}
        aria-label="${esc(f.rule_id)} 픽스 대상으로 선택">`
    : "";
  const manual=f.fixable?"":`<span class="manual">${svg("lock","sm")}자동 수정 불가 — ${esc(f.manual_reason||"담당자가 직접 수정해야 합니다.")}</span>`;
  return `<article class="finding lv-${f.level}" id="f_${esc(f.rule_id)}">
    <div class="top">${box}<span class="rule">${esc(f.rule_id)}</span>
      <span class="item">${esc(f.item)}</span><span class="cnt">${f.count}건</span></div>
    <p class="msg">${esc(f.message)}</p>
    ${f.fix?`<p class="fix"><span class="tag">조치</span><span>${esc(f.fix)}</span></p>`:""}
    ${manual}
    ${shown.length?`<div class="refs">${shown.map(l=>
      `<button class="chip" data-ref="${esc(l)}">${esc(l)}</button>`).join("")}${more}</div>`:""}
    ${f.samples.length?`<div class="samples">${f.samples.map(esc).join(" · ")}</div>`:""}
  </article>`;
}
function fixBar(r){
  const n=r.findings.filter(f=>f.fixable).length;
  if(!n)return "";
  const sel=selOf(active).size;
  return `<div class="fixbar">
      <span class="lead">${svg("wand")}픽스</span>
      <button class="btn ghost sm" id="selAll">전체 ${n}건 선택</button>
      <button class="btn ghost sm" id="selNone">${svg("clear","sm")}선택 해제</button>
      <button class="btn sm" id="doFix" ${sel?"":"disabled"}>${svg("check","sm")}선택 ${sel}건 수정본 저장</button>
      <span class="sel">${r.ext.toUpperCase()} 형식 그대로 저장됩니다</span>
    </div>
    <p class="fixnote">체크한 조항만 자동 수정합니다. 원본 파일은 그대로 두고 수정본을 새로 저장한 뒤, 수정본을 다시 검토해 결과 탭으로 추가합니다.</p>`;
}
function fixResult(){
  const fx=fixInfo[active];
  if(!fx)return "";
  const list=fx.applied.map(a=>`${a.label} ${a.count}건`).join(" · ")||"변경 없음";
  const after=results[active].counts["반려"];
  return `<div class="fixdone">${svg("check","sm")} <b>${esc(fx.from)}의 수정본입니다.</b>
    반려 ${fx.before}건 → ${after}건 · ${esc(list)}${fx.removed_rows?` · 행 ${fx.removed_rows}개 삭제`:""}
    <span class="path">${esc(fx.out_path)}</span></div>`;
}
function bind(){
  document.querySelectorAll(".chip[data-ref]").forEach(b=>b.onclick=()=>{
    const m=/^([A-Z]+)(\d+)$/.exec(b.dataset.ref);
    if(!m){toast(`${b.dataset.ref}은 행 단위 지적사항입니다.`);return;}
    mapFocus=b.dataset.ref;drawMap(results[active],true);
  });
  document.querySelectorAll(".fx").forEach(cb=>cb.onchange=()=>{
    const s=selOf(active);cb.checked?s.add(cb.dataset.rule):s.delete(cb.dataset.rule);
    refreshFixBar();
  });
  document.querySelectorAll("[data-lv]").forEach(b=>b.onclick=()=>{
    const s=selOf(active);
    results[active].findings.filter(f=>f.level===b.dataset.lv&&f.fixable)
      .forEach(f=>s.add(f.rule_id));
    render();
  });
  const all=$("selAll"), none=$("selNone"), go=$("doFix");
  if(all)all.onclick=()=>{const s=selOf(active);
    results[active].findings.filter(f=>f.fixable).forEach(f=>s.add(f.rule_id));render();};
  if(none)none.onclick=()=>{picked[active]=new Set();render();};
  if(go)go.onclick=runFix;
}
function refreshFixBar(){
  const go=$("doFix");if(!go)return;
  const n=selOf(active).size;
  go.disabled=!n;go.innerHTML=svg("check","sm")+`선택 ${n}건 수정본 저장`;
}
async function runFix(){
  const rules=[...selOf(active)];
  if(!rules.length)return;
  const go=$("doFix");go.disabled=true;go.innerHTML=svg("spin","sm")+"수정 중…";
  try{
    const res=await window.pywebview.api.fix(results[active].file_path,rules);
    if(res.cancelled){toast("저장을 취소했습니다.");refreshFixBar();return;}
    if(res.error){toast(res.error);refreshFixBar();return;}
    const before=results[active].counts["반려"], from_=results[active].file_name;
    results.push(res.after);
    active=results.length-1;
    fixInfo[active]={...res.report, from:from_, before:before};
    mapFocus=null;render();
    toast(`수정본 저장 완료 · 반려 ${before} → ${res.after.counts["반려"]}건`);
  }catch(e){toast("수정 중 오류: "+e);refreshFixBar();}
}

/* 셀 위치 지도 — 캔버스 (최대 50열 × 1000행) */
function minimap(r){
  if(!r.cols||!r.rows)return "";
  const cut=(r.cols>MAP.MAXC||r.rows>MAP.MAXR)
    ?` · 앞쪽 ${Math.min(r.cols,MAP.MAXC)}열 ${Math.min(r.rows,MAP.MAXR)}행 표시`:"";
  return `<div class="map-head">
      <span class="map-title">${svg("grid","sm")}셀 위치 지도 — 1행은 항목명${cut}</span>
      <span class="legend">${LEVELS.map(l=>`<span><i class="bg-${l}"></i>${l}</span>`).join("")}</span>
      <span class="map-read" id="mapRead">셀 위로 이동</span>
    </div><div class="map" id="mapBox"><canvas id="mapCv"></canvas></div>`;
}
function colName(i){let s="";i++;while(i){const m=(i-1)%26;s=String.fromCharCode(65+m)+s;i=Math.floor((i-1)/26);}return s;}
function refToXY(ref){
  const m=/^([A-Z]+)(\d+)$/.exec(ref);if(!m)return null;
  let c=0;for(const ch of m[1])c=c*26+(ch.charCodeAt(0)-64);
  return {c:c-1,r:+m[2]-1};
}
function drawMap(r,scroll){
  const cv=$("mapCv");if(!cv)return;
  const maxC=Math.min(r.cols,MAP.MAXC), maxR=Math.min(r.rows,MAP.MAXR);
  const W=MAP.GUT+maxC*MAP.CW, H=MAP.HDR+maxR*MAP.CH;
  const dpr=window.devicePixelRatio||1;
  cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+"px";cv.style.height=H+"px";
  const g=cv.getContext("2d");g.setTransform(dpr,0,0,dpr,0,0);
  const C={base:cssVar("--rule-2"),line:"#fff",txt:cssVar("--ink-3"),ink:cssVar("--ink")};
  const LC={"반려":cssVar("--reject"),"보완필요":cssVar("--action"),"확인권장":cssVar("--review")};
  g.clearRect(0,0,W,H);
  g.fillStyle=C.base;g.fillRect(MAP.GUT,MAP.HDR,maxC*MAP.CW,maxR*MAP.CH);
  g.strokeStyle=C.line;g.lineWidth=1;g.beginPath();
  for(let c=0;c<=maxC;c++){const x=MAP.GUT+c*MAP.CW+.5;g.moveTo(x,MAP.HDR);g.lineTo(x,H);}
  for(let rw=0;rw<=maxR;rw++){const y=MAP.HDR+rw*MAP.CH+.5;g.moveTo(MAP.GUT,y);g.lineTo(W,y);}
  g.stroke();
  Object.entries(r.grid).forEach(([ref,lv])=>{
    const p=refToXY(ref);if(!p||p.c>=maxC||p.r>=maxR)return;
    g.fillStyle=LC[lv]||C.txt;
    g.fillRect(MAP.GUT+p.c*MAP.CW+1,MAP.HDR+p.r*MAP.CH+1,MAP.CW-2,MAP.CH-2);
  });
  g.fillStyle=C.txt;g.font='8px Consolas, monospace';g.textAlign="center";
  for(let c=0;c<maxC;c++)g.fillText(colName(c),MAP.GUT+c*MAP.CW+MAP.CW/2,MAP.HDR-5);
  g.textAlign="right";
  for(let rw=0;rw<maxR;rw++){
    if(rw===0||(rw+1)%5===0)g.fillText(String(rw+1),MAP.GUT-5,MAP.HDR+rw*MAP.CH+8);
  }
  if(mapFocus){
    const p=refToXY(mapFocus);
    if(p&&p.c<maxC&&p.r<maxR){
      g.strokeStyle=C.ink;g.lineWidth=1.5;
      g.strokeRect(MAP.GUT+p.c*MAP.CW-.5,MAP.HDR+p.r*MAP.CH-.5,MAP.CW+1,MAP.CH+1);
      if(scroll){const box=$("mapBox");
        box.scrollTop=Math.max(0,MAP.HDR+p.r*MAP.CH-box.clientHeight/2);
        box.scrollLeft=Math.max(0,MAP.GUT+p.c*MAP.CW-box.clientWidth/2);}
      $("mapRead").textContent=`${mapFocus} · ${r.grid[mapFocus]||"지적 없음"}`;
    }else if(scroll){toast(`${mapFocus}은 지도 표시 범위를 벗어났습니다.`);}
  }
  cv.onmousemove=ev=>{
    const b=cv.getBoundingClientRect();
    const c=Math.floor((ev.clientX-b.left-MAP.GUT)/MAP.CW);
    const rw=Math.floor((ev.clientY-b.top-MAP.HDR)/MAP.CH);
    const el=$("mapRead");if(!el)return;
    if(c<0||rw<0||c>=maxC||rw>=maxR){el.textContent="셀 위로 이동";return;}
    const ref=colName(c)+(rw+1);
    el.textContent=`${ref} · ${r.grid[ref]||"지적 없음"}`;
  };
  cv.onclick=ev=>{
    const b=cv.getBoundingClientRect();
    const c=Math.floor((ev.clientX-b.left-MAP.GUT)/MAP.CW);
    const rw=Math.floor((ev.clientY-b.top-MAP.HDR)/MAP.CH);
    if(c<0||rw<0||c>=maxC||rw>=maxR)return;
    const ref=colName(c)+(rw+1);
    if(!r.grid[ref])return;
    mapFocus=ref;drawMap(r);
    const hit=r.findings.find(f=>f.locations.includes(ref));
    if(hit){const el=$("f_"+hit.rule_id);
      if(el){el.scrollIntoView&&el.scrollIntoView({block:"center",behavior:"smooth"});
        el.classList.remove("flash");void el.offsetWidth;el.classList.add("flash");}}
  };
}
window.addEventListener("pywebviewready",async()=>{
  try{$("criteria").textContent=await window.pywebview.api.criteria();}catch(e){}
});
</script>
</body>
</html>
"""
