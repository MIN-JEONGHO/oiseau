# -*- coding: utf-8 -*-
"""GUI 화면(HTML/CSS/JS). exe 패키징을 위해 외부 리소스 없이 단일 문자열로 내장.

화면은 두 구분(파일데이터 · OPEN API)을 색인탭으로 나눈다. 안내 매뉴얼이 둘로
나뉘어 있고 조항 번호가 서로 겹치므로(파일 10-라 ↔ API 10-나), 화면에서도 갈라
두어야 검토자가 조항을 잘못 읽지 않는다.
"""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>공공데이터 등록 사전검토</title>
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
[hidden]{display:none !important}

.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
  padding-bottom:14px;border-bottom:2px solid var(--ink)}
.eyebrow{font-family:var(--font-data);font-size:11px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 6px}
h1{margin:0;font-size:29px;font-weight:800;letter-spacing:-.035em}
h1 span{color:var(--ink-3);font-weight:700}
.criteria{font-family:var(--font-data);font-size:11px;color:var(--ink-2);
  border:1px solid var(--rule);background:var(--surface);padding:5px 9px;white-space:nowrap}

/* 구분 색인탭 — 문서철 간지처럼 본문 위에 얹힌다 */
.dtabs{display:flex;gap:3px;margin-top:-2px;padding-top:2px}
.dtab{position:relative;display:flex;flex-direction:column;gap:1px;
  background:var(--surface-2);border:1px solid var(--rule);
  padding:9px 20px 10px;cursor:pointer;text-align:left;min-width:200px;
  transition:background .14s, border-color .14s, transform .14s}
.dtab:hover{background:var(--surface)}
.dtab .dtab-k{font-family:var(--font-data);font-size:9.5px;letter-spacing:.2em;
  color:var(--ink-3)}
.dtab .dtab-t{font-weight:800;letter-spacing:-.02em;font-size:15px;color:var(--ink-2)}
.dtab .dtab-s{font-family:var(--font-data);font-size:10px;color:var(--ink-3);
  letter-spacing:.02em}
.dtab.is-on{background:var(--ink);border-color:var(--ink);transform:translateY(-2px)}
.dtab.is-on .dtab-t{color:#fff}
.dtab.is-on .dtab-k,.dtab.is-on .dtab-s{color:#9AA6B2}
.dtab:focus-visible{outline:2px solid var(--review);outline-offset:2px}
.sheet{border-top:2px solid var(--ink)}

.step{margin-top:26px}
.step-label{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.step-num{font-family:var(--font-data);font-size:11px;color:var(--ink-3);
  border:1px solid var(--rule);padding:2px 6px}
.step-title{font-weight:800;letter-spacing:-.02em}
.step-opt{font-family:var(--font-data);font-size:10px;letter-spacing:.1em;
  color:var(--ink-3);border:1px solid var(--rule-2);padding:1px 5px}
.hint{color:var(--ink-2);font-size:12.5px;margin:0 0 10px}

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
.btn-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:16px}

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

details.meta{background:var(--surface);border:1px solid var(--rule-2);margin-top:12px}
details.meta summary{cursor:pointer;padding:12px 14px;font-weight:700;list-style:none;
  display:flex;justify-content:space-between;align-items:center;gap:8px}
details.meta summary::-webkit-details-marker{display:none}
details.meta summary .caret{transition:transform .18s;color:var(--ink-3)}
details.meta[open] summary .caret{transform:rotate(180deg)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
  gap:12px 16px;padding:4px 14px 18px}
.grid.bare{background:var(--surface);border:1px solid var(--rule-2);padding:16px 14px}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:11.5px;font-family:var(--font-data);letter-spacing:.06em;color:var(--ink-2)}
.field label i{color:var(--reject);font-style:normal;margin-left:3px}
.field input,.field select,.field textarea{border:1px solid var(--rule);background:#fff;
  padding:7px 9px;font-size:13px;width:100%}
.field textarea{resize:vertical;min-height:62px}
.field input:focus,.field select:focus,.field textarea:focus{outline:2px solid var(--review);outline-offset:-1px}
.field.wide{grid-column:1/-1}

.probebox{background:var(--surface);border:1px solid var(--rule-2);
  border-left:3px solid var(--action);padding:13px 15px}
.probebox .pb-top{display:flex;align-items:center;gap:9px;font-weight:700;font-size:13px;
  cursor:pointer}
.probebox .pb-top input{width:15px;height:15px;accent-color:var(--ink);margin:0;cursor:pointer}
.probebox p{margin:7px 0 0;font-size:12px;color:var(--ink-2)}
.probebox .pb-key{margin-top:10px}
.probebox .pb-key input{width:100%;border:1px solid var(--rule);background:#fff;
  padding:6px 9px;font-family:var(--font-data);font-size:12px}
.probebox .pb-key input[disabled]{background:var(--surface-2);color:var(--ink-3)}

#result{margin-top:30px}
.tabs{display:flex;gap:1px;border-bottom:1px solid var(--rule);flex-wrap:wrap}
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
.map{position:relative;overflow:auto;max-height:360px;border:1px solid var(--rule-2);
  background:#fff;margin-bottom:18px}
.map canvas{position:absolute;top:0;left:0;display:block;cursor:crosshair}
.map .spacer{width:1px;height:1px}

/* 오퍼레이션 대장 — 읽어 들인 명세를 그대로 펼쳐 놓는다 */
.ledger{border:1px solid var(--rule-2);background:#fff;margin-bottom:18px}
.led-head{display:grid;grid-template-columns:56px 1fr 54px 54px;
  background:var(--surface-2);border-bottom:1px solid var(--rule-2);
  font-family:var(--font-data);font-size:10px;letter-spacing:.1em;color:var(--ink-3)}
.led-head span{padding:6px 9px;text-align:center}
.led-head span:nth-child(2){text-align:left}
.led-head span+span{border-left:1px solid var(--rule-2)}
.led-row{display:grid;grid-template-columns:56px 1fr 54px 54px;
  border-bottom:1px solid var(--rule-2)}
.led-row:last-child{border-bottom:0}
.led-row:hover{background:var(--surface-2)}
.method{font-family:var(--font-data);font-size:9.5px;font-weight:700;letter-spacing:.06em;
  display:flex;align-items:center;justify-content:center;color:var(--pass)}
.method.post,.method.put,.method.delete,.method.patch{color:var(--reject)}
.led-name{padding:8px 10px;border-left:1px solid var(--rule-2);min-width:0}
.led-name b{font-weight:700;letter-spacing:-.01em;display:block;font-size:13px}
.led-name small{font-family:var(--font-data);font-size:10.5px;color:var(--ink-3);
  display:block;word-break:break-all;margin-top:1px}
.led-n{font-family:var(--font-data);font-size:13px;display:flex;align-items:center;
  justify-content:center;border-left:1px solid var(--rule-2)}
.led-n.zero{color:var(--ink-3)}

.probelog{border:1px solid var(--rule-2);background:#fff;margin-bottom:18px}
.pl-row{display:grid;grid-template-columns:1fr 60px 64px;border-bottom:1px solid var(--rule-2)}
.pl-row:last-child{border-bottom:0}
.pl-u{padding:7px 10px;font-family:var(--font-data);font-size:11px;
  word-break:break-all;color:var(--ink-2)}
.pl-s,.pl-t{font-family:var(--font-data);font-size:11.5px;display:flex;
  align-items:center;justify-content:center;border-left:1px solid var(--rule-2)}
.pl-s.bad,.pl-t.bad{color:var(--reject);font-weight:700}
.pl-s.ok{color:var(--pass)}

.specnote{background:var(--surface-2);border:1px solid var(--rule-2);
  border-left:3px solid var(--review);padding:10px 13px;margin-bottom:16px;
  font-size:12.5px;color:var(--ink-2)}
.specnote b{color:var(--ink)}
.specnote.warn{border-left-color:var(--action)}

.fixbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:var(--surface-2);
  border:1px solid var(--rule-2);padding:10px 12px;margin-bottom:16px}
.fixbar .lead{display:flex;align-items:center;gap:7px;font-weight:700;font-size:13px}
.fixbar .sel{font-family:var(--font-data);font-size:11.5px;color:var(--ink-2);margin-left:auto}
.fixnote{font-size:12px;color:var(--ink-2);margin:0 0 14px;padding-left:2px}
.helpq{display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;
  border:1px solid var(--rule);background:#fff;color:var(--ink-2);font-family:var(--font-data);
  font-size:11px;font-weight:700;cursor:pointer;padding:0}
.helpq:hover{border-color:var(--ink);color:var(--ink)}
.helpq[aria-expanded="true"]{background:var(--ink);color:#fff;border-color:var(--ink)}
.helpbox{border:1px solid var(--rule-2);background:#fff;padding:13px 15px;margin-bottom:16px;
  font-size:12.5px;color:var(--ink-2)}
.helpbox dl{margin:0;display:grid;grid-template-columns:88px 1fr;gap:7px 12px}
.helpbox dt{font-family:var(--font-data);font-size:11px;letter-spacing:.06em;color:var(--ink);
  display:flex;align-items:center;gap:6px}
.helpbox dd{margin:0}
.helpbox .tail{margin:11px 0 0;padding-top:9px;border-top:1px solid var(--rule-2);color:var(--ink-3)}
.tier{font-family:var(--font-data);font-size:10px;letter-spacing:.08em;padding:1px 5px;
  border:1px solid currentColor}
.t-서식{color:var(--review)} .t-내용{color:var(--action)}
.fixdone{border:1px solid var(--pass);border-left:3px solid var(--pass);background:#fff;
  padding:11px 13px;margin-bottom:16px;font-size:13px}
.fixdone b{color:var(--pass)}
.fixdone .path{font-family:var(--font-data);font-size:11.5px;color:var(--ink-2);
  word-break:break-all;display:block;margin-top:3px}

/* 픽스 대조표 — 무엇이 무엇으로 바뀌었는지 그대로 보여 준다 */
.diff{list-style:none;margin:10px 0 0;padding:0;display:flex;flex-direction:column;gap:1px}
.diff li{display:grid;grid-template-columns:96px 1fr;gap:10px;background:var(--surface-2);
  padding:7px 10px;font-size:12.5px;align-items:baseline}
.diff .df{font-family:var(--font-data);font-size:10.5px;letter-spacing:.06em;color:var(--ink-3)}
.diff .dv{min-width:0;word-break:break-all}
.diff .db{color:var(--ink-3);text-decoration:line-through}
.diff .da{color:var(--ink);font-weight:700}
.diff .arrow{color:var(--ink-3);margin:0 6px;font-family:var(--font-data)}
.manual-list{list-style:none;margin:10px 0 0;padding:0;font-size:12px;color:var(--action)}
.manual-list li{padding:3px 0;display:flex;gap:6px}

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
.chip.more,.chip.flat{cursor:default;color:var(--ink-3)}
.chip.flat{color:var(--ink-2)}
.chip.flat:hover{border-color:var(--rule-2);background:var(--surface-2)}
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
.colophon{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:36px;
  padding-top:14px;border-top:1px solid var(--rule);font-family:var(--font-data);
  font-size:11px;color:var(--ink-3);letter-spacing:.04em}
.colophon .brand{color:var(--ink);font-weight:700;letter-spacing:.14em}
.colophon .sep{color:var(--rule)}
@media (prefers-reduced-motion:reduce){.finding.flash{animation:none}
  .dtab{transition:none} .dtab.is-on{transform:none}}
@media (max-width:900px){.panel{grid-template-columns:1fr}
  .rail{border-right:0;border-bottom:1px solid var(--rule-2)}
  .dtab{min-width:0;flex:1;padding:9px 12px}}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div>
      <p class="eyebrow" id="eyebrow">공공데이터포털 · 파일데이터 등록</p>
      <h1>등록 전 반려 사유 <span>미리 확인</span></h1>
    </div>
    <div class="criteria" id="criteria">기준 26.2~</div>
  </header>

  <nav class="dtabs" role="tablist" aria-label="검토 구분">
    <button class="dtab is-on" data-dom="file" role="tab" aria-selected="true">
      <span class="dtab-k">구분 01</span>
      <span class="dtab-t">파일데이터</span>
      <span class="dtab-s">CSV · XLSX · JSON · ZIP / 17개 항목</span>
    </button>
    <button class="dtab" data-dom="api" role="tab" aria-selected="false">
      <span class="dtab-k">구분 02</span>
      <span class="dtab-t">OPEN API</span>
      <span class="dtab-s">기술문서 · 등록정보 / 23개 항목</span>
    </button>
  </nav>
  <div class="sheet"></div>

  <!-- ═══════════ 파일데이터 ═══════════ -->
  <div id="paneFile">
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
        <span class="step-title">등록 메타정보</span>
        <span class="step-opt">선택</span></div>
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
  </div>

  <!-- ═══════════ OPEN API ═══════════ -->
  <div id="paneApi" hidden>
    <section class="step">
      <div class="step-label"><span class="step-num">01</span>
        <span class="step-title">기술문서 업로드</span>
        <span class="step-opt">선택</span></div>
      <p class="hint">Swagger·OpenAPI JSON 또는 오퍼레이션 파일(xlsx · csv)을 올리면
        오퍼레이션·파라미터·에러코드까지 읽어 12~22번 항목을 검토합니다.
        기술문서를 올리지 않으면 등록 정보만으로 검토합니다.</p>
      <div class="drop" id="dropSpec">
        <span class="lead"><span id="specIcon"></span><span id="specText">기술문서를 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.</span></span>
        <button class="btn" id="pickSpec"></button>
      </div>
      <ul class="files" id="specFile"></ul>
    </section>

    <section class="step">
      <div class="step-label"><span class="step-num">02</span>
        <span class="step-title">등록 정보</span>
        <span class="step-opt">* 필수 입력 항목</span></div>
      <p class="hint">목록등록관리시스템에 넣을 값을 그대로 적으세요. 기술문서와 다른 값이 있으면 12-나(기술문서 ↔ 등록내용 상이) 기준으로 판단합니다.</p>
      <div class="grid bare" id="apiGridCore"></div>
      <details class="meta">
        <summary><span>그 밖의 등록 정보 — 공공누리 · 제공신청 · 담당자 · 링크 등</span><span class="caret" id="caret2"></span></summary>
        <div class="grid" id="apiGridMore"></div>
      </details>
    </section>

    <section class="step">
      <div class="step-label"><span class="step-num">03</span>
        <span class="step-title">endPoint 실호출</span>
        <span class="step-opt">선택</span></div>
      <div class="probebox">
        <label class="pb-top"><input type="checkbox" id="probeOn">
          <span id="probeIcon"></span>기재한 URL 을 호출해서 검사합니다</label>
        <p>19번(호출 오류 · 상태코드 · 응답 지연 · 항목명 일치)과 16번(Content-Type)은
          실제로 불러 봐야 알 수 있습니다. <b>외부 서버로 실제 요청이 나갑니다.</b>
          내부망에서 외부 호출이 막혀 있으면 열어 두세요.(외부망 이용 권고)
          최대 5개 URL 을 GET 으로 한 번씩만 호출합니다.</p>
        <div class="pb-key">
          <input id="svcKey" disabled
            placeholder="인증키(serviceKey) — URL 에 이미 붙어 있으면 비워 두세요">
        </div>
      </div>
      <div class="btn-row">
        <button class="btn" id="runApi"></button>
        <button class="btn ghost" id="saveXlsx2" disabled></button>
        <span class="working" id="working2"></span>
      </div>
    </section>
  </div>

  <section id="result"></section>

  <footer class="colophon">
    <span class="brand">Powered by MIN</span>
    <span class="sep">·</span><span id="cfVer">v3.0.0</span>
    <span class="sep">·</span><span id="cfDate">배포 2026-08-03</span>
  </footer>
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
 doc:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
 plug:'<path d="M9 3v6M15 3v6"/><path d="M7 9h10v3a5 5 0 0 1-10 0z"/><path d="M12 17v4"/>',
 book:'<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20"/>',
};
const svg=(k,c)=>`<svg class="ic ${c||''}" viewBox="0 0 24 24" aria-hidden="true">${IC[k]}</svg>`;
const LEVELS=["반려","보완필요","확인권장"];
const LVICON={"반려":"alert","보완필요":"flag","확인권장":"eye","적합":"check"};
const TIERLB={"서식":"서식 정리","내용":"내용 변경"};
const MAP={GUT:40,HDR:16,CW:11,CH:11,MAXC:100,MAXR:10000};

const META_FIELDS=[
 ["목록명","text","예: 공공데이터_지자체별 미세먼지 현황"],
 ["데이터명","text","기관명 + 직관적 데이터 명칭"],
 ["기관명","text","등록 기관명"],
 ["키워드","text","콤마로 구분(3~8개)"],
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
/* [이름, 입력형태, 안내, 핵심여부] — 핵심은 접지 않고 늘 펼쳐 둔다 */
const API_FIELDS=[
 ["목록명","text","예: 공공데이터활용지원센터_지자체별 미세먼지 현황",1],
 ["기관명","text","등록 기관명",1],
 ["기관코드","text","URL 첫 구분자. 예: 15012345",1],
 ["API명(영문)","text","URL 둘째 구분자. 예: AQIService",1],
 ["등록유형","select","PUBC|GW|멀티클라우드|링크",1],
 ["서비스URL","text","apis.data.go.kr/기관코드/API명(영문)/오퍼레이션명(영문)",1],
 ["응답포맷","select","JSON|XML|JSON+XML",1],
 ["전송방식","select","GET|POST",1],
 ["키워드","text","콤마로 구분(3~8개)",1],
 ["설명","textarea","생성·수집 목적과 활용성을 50자 이상",1],
 ["인증모듈적용","select","아니오|예",0],
 ["TESTKEY","text","PUBC 호출 테스트용 키",0],
 ["기술문서검토","select","미요청|완료",0],
 ["공공누리유형","select","제1유형|제2유형|제3유형|제4유형",0],
 ["저작권포함","select","아니오|예",0],
 ["제공신청여부","select","아니오|예",0],
 ["제공번호","text","제공신청 시 필수",0],
 ["부담당자","text","오류 발생 시 즉시 연락 가능한 담당자",0],
 ["담당자연락처","text","02-1234-5678",0],
 ["링크URL","text","링크형태로 등록하는 경우",0],
 ["중복확인","select","미확인|완료",0],
 ["타기관데이터포함","select","아니오|예",0],
 ["비정형포함","select","아니오|예",0],
 ["일시정지요청","select","아니오|예",0],
 ["응답형태","select","XML·JSON|이미지|엑셀|파일",0],
];
const EYEBROW={file:"공공데이터포털 · 파일데이터 등록", api:"공공데이터포털 · OPEN API 등록"};

let dom="file";
const S={
  file:{files:[],results:[],active:0,picked:{},fixInfo:{}},
  api :{spec:"",results:[],active:0,picked:{},fixInfo:{}},
};
const st=()=>S[dom];
let mapFocus=null, mapIndex={}, mapRaf=0, helpOpen=false;

const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(m){const t=$("toast");t.textContent=m;t.classList.add("on");
  clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("on"),2800);}
const selOf=i=>(st().picked[i]=st().picked[i]||new Set());
const cssVar=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const base=p=>String(p||"").split(/[\\/]/).pop();

/* ── 아이콘·정적 문구 ─────────────────────────────────────── */
$("dropIcon").innerHTML=svg("upload","lg");
$("specIcon").innerHTML=svg("doc","lg");
$("probeIcon").innerHTML=svg("plug","sm");
$("pick").innerHTML=svg("folder")+"파일 선택";
$("pickSpec").innerHTML=svg("folder")+"기술문서 선택";
$("run").innerHTML=svg("scan")+"검토 실행";
$("runApi").innerHTML=svg("scan")+"검토 실행";
$("saveXlsx").innerHTML=svg("sheet")+"엑셀로 저장";
$("saveXlsx2").innerHTML=svg("sheet")+"엑셀로 저장";
$("caret").innerHTML=svg("caret","sm");
$("caret2").innerHTML=svg("caret","sm");

/* ── 입력 폼 ──────────────────────────────────────────────── */
function fieldHtml(pfx,f){
  const k=f[0], t=f[1], ph=f[2], core=f[3];
  const wide=t==="textarea"?" wide":"";
  const id=pfx+k;
  let ctrl;
  if(t==="select"){ctrl=`<select id="${id}"><option value=""></option>`+
    ph.split("|").map(o=>`<option>${esc(o)}</option>`).join("")+`</select>`;}
  else if(t==="textarea"){ctrl=`<textarea id="${id}" placeholder="${esc(ph)}"></textarea>`;}
  else{ctrl=`<input id="${id}" placeholder="${esc(ph)}">`;}
  const mark=core?'<i title="검토에 꼭 필요한 항목">*</i>':"";
  return `<div class="field${wide}"><label for="${id}">${esc(k)}${mark}</label>${ctrl}</div>`;
}
$("metaGrid").innerHTML=META_FIELDS.map(f=>fieldHtml("m_",f)).join("");
$("apiGridCore").innerHTML=API_FIELDS.filter(f=>f[3]).map(f=>fieldHtml("a_",f)).join("");
$("apiGridMore").innerHTML=API_FIELDS.filter(f=>!f[3]).map(f=>fieldHtml("a_",f)).join("");

const readForm=(pfx,fields)=>{const o={};fields.forEach(f=>{
  const el=$(pfx+f[0]);const v=el?el.value.trim():"";if(v)o[f[0]]=v;});return o;};
const readMeta=()=>readForm("m_",META_FIELDS);
const readApiMeta=()=>readForm("a_",API_FIELDS);

/* ── 구분 전환 ────────────────────────────────────────────── */
document.querySelectorAll(".dtab").forEach(t=>{
  t.onclick=()=>{
    if(dom===t.dataset.dom)return;
    dom=t.dataset.dom;
    document.querySelectorAll(".dtab").forEach(x=>{
      const on=x.dataset.dom===dom;
      x.classList.toggle("is-on",on);x.setAttribute("aria-selected",String(on));
    });
    $("paneFile").hidden=dom!=="file";
    $("paneApi").hidden=dom!=="api";
    $("eyebrow").textContent=EYEBROW[dom];
    mapFocus=null;helpOpen=false;
    render();
  };
});

/* ── 파일데이터 입력 ──────────────────────────────────────── */
function renderFiles(){
  const f=S.file.files;
  $("files").innerHTML=f.map((p,i)=>
    `<li><span class="fname">${svg("file","sm")}${esc(base(p))}</span>
     <span class="fmeta">${esc(p)}
     <button data-i="${i}" aria-label="목록에서 제거">${svg("x","sm")}</button></span></li>`).join("");
  $("files").querySelectorAll("button").forEach(b=>b.onclick=()=>{
    f.splice(+b.dataset.i,1);renderFiles();});
  $("run").disabled=f.length===0;
  $("dropText").textContent=f.length
    ? `${f.length}개 파일이 준비되었습니다. 더 올리려면 끌어다 놓으세요.`
    : "CSV · XLSX · JSON · ZIP 파일을 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.";
}
function addFiles(list){
  let added=0;(list||[]).forEach(p=>{if(p&&!S.file.files.includes(p)){S.file.files.push(p);added++;}});
  renderFiles();
  if(!added)toast("추가된 파일이 없습니다. 경로를 확인하세요.");
}
$("pick").onclick=async()=>addFiles(await window.pywebview.api.pick_files());
function wireDrop(el,onPaths){
  ["dragenter","dragover"].forEach(e=>el.addEventListener(e,ev=>{ev.preventDefault();el.classList.add("on");}));
  ["dragleave","drop"].forEach(e=>el.addEventListener(e,ev=>{ev.preventDefault();el.classList.remove("on");}));
  el.addEventListener("drop",ev=>{
    const paths=[...(ev.dataTransfer.files||[])].map(f=>f.pywebviewFullPath||f.path||"").filter(Boolean);
    paths.length?onPaths(paths):toast("이 창에서는 경로를 읽지 못했습니다. 선택 버튼을 사용하세요.");
  });
}
wireDrop($("drop"),addFiles);

/* ── OPEN API 입력 ────────────────────────────────────────── */
function renderSpec(){
  const p=S.api.spec;
  $("specFile").innerHTML=p
    ? `<li><span class="fname">${svg("doc","sm")}${esc(base(p))}</span>
        <span class="fmeta">${esc(p)}
        <button aria-label="기술문서 제거">${svg("x","sm")}</button></span></li>` : "";
  const btn=$("specFile").querySelector("button");
  if(btn)btn.onclick=()=>{S.api.spec="";renderSpec();};
  $("specText").textContent=p
    ? "기술문서가 준비되었습니다. 다른 문서를 올리면 교체됩니다."
    : "기술문서를 이 영역에 끌어다 놓거나, 오른쪽에서 선택하세요.";
}
$("pickSpec").onclick=async()=>{
  const p=await window.pywebview.api.pick_spec();
  if(p){S.api.spec=p;renderSpec();}
};
wireDrop($("dropSpec"),ps=>{S.api.spec=ps[0];renderSpec();});
$("probeOn").onchange=e=>{$("svcKey").disabled=!e.target.checked;};

/* ── 실행 ─────────────────────────────────────────────────── */
$("run").onclick=async()=>{
  $("run").disabled=true;$("working").innerHTML=svg("spin","sm")+"검토 중…";
  try{
    S.file.results=await window.pywebview.api.run(S.file.files,readMeta());
    S.file.active=0;S.file.picked={};S.file.fixInfo={};render();
    $("saveXlsx").disabled=false;$("saveXlsx2").disabled=false;
    $("working").textContent=`${S.file.results.length}개 파일 검토 완료`;
  }catch(e){$("working").textContent="";toast("검토 중 오류: "+e);}
  $("run").disabled=false;
};
$("runApi").onclick=async()=>{
  const on=$("probeOn").checked;
  $("runApi").disabled=true;
  $("working2").innerHTML=svg("spin","sm")+(on?"호출하며 검토 중…":"검토 중…");
  try{
    S.api.results=await window.pywebview.api.run_api(
      readApiMeta(),S.api.spec,on,$("svcKey").value.trim());
    S.api.active=0;S.api.picked={};S.api.fixInfo={};render();
    $("saveXlsx").disabled=false;$("saveXlsx2").disabled=false;
    $("working2").textContent="검토 완료";
  }catch(e){$("working2").textContent="";toast("검토 중 오류: "+e);}
  $("runApi").disabled=false;
};
const doSave=async()=>{
  const p=await window.pywebview.api.save_report();
  toast(p?`저장했습니다: ${p}`:"저장을 취소했습니다.");
};
$("saveXlsx").onclick=doSave;
$("saveXlsx2").onclick=doSave;

/* ── 결과 ─────────────────────────────────────────────────── */
function emptyBox(){
  const t=dom==="file"
    ? ["아직 검토한 파일이 없습니다.",
       "파일을 올리고 검토를 실행하면 기준 조항별 지적사항과 해당 셀 위치가 표시됩니다."]
    : ["아직 검토한 API 가 없습니다.",
       "등록 정보를 넣고 검토를 실행하면 23개 항목의 지적사항이 표시됩니다. 기술문서를 함께 올리면 오퍼레이션·파라미터까지 검사합니다."];
  return `<div class="empty">${svg(dom==="file"?"grid":"book","lg")}
    <p>${t[0]}</p><small>${t[1]}</small></div>`;
}
function render(){
  const s=st();
  if(!s.results.length){$("result").innerHTML=emptyBox();return;}
  if(s.active>=s.results.length)s.active=0;
  const tabs=s.results.map((r,i)=>
    `<div class="tab" role="tab" data-i="${i}" tabindex="0" aria-selected="${i===s.active}">
      <span class="dot bg-${r.verdict}"></span>${esc(r.file_name)}</div>`).join("");
  $("result").innerHTML=`<div class="tabs" role="tablist">${tabs}</div>${panel(s.results[s.active])}`;
  $("result").querySelectorAll(".tab").forEach(t=>{
    t.onclick=()=>{s.active=+t.dataset.i;mapFocus=null;render();};
    t.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();t.click();}};
  });
  bind();
  if(dom==="file"){buildIndex(s.results[s.active]);drawMap(s.results[s.active]);}
}
function facts(r){
  if(r.domain==="api"){
    const a=r.api||{};
    return [["등록유형",a.reg_type||"-"],["오퍼레이션",`${a.operations||0}개`],
      ["요청 파라미터",`${a.request_params||0}개`],
      ["응답 파라미터",`${a.response_params||0}개`],
      ["에러코드",`${a.error_codes||0}개`],
      ["응답 포맷",(a.formats||[]).join(" + ")||"-"],
      ["기술문서",a.source_name||"올리지 않음"]];
  }
  return [["형식",(r.ext||"").toUpperCase()||"-"],["규모",`${r.rows}행 × ${r.cols}열`],
    ["인코딩",r.encoding||"-"],["구분자",r.delimiter||"-"],
    ["용량",(r.file_size/1024).toFixed(0)+" KB"],["기준일 후보",r.suggested_base_date||"-"]];
}
function panel(r){
  const c=r.counts;
  const groups=LEVELS.map(lv=>{
    const fs=r.findings.filter(f=>f.level===lv);
    if(!fs.length)return "";
    const n=fs.filter(f=>f.fixable&&f.fix_tier==="서식").length;
    return `<div class="group-label">${svg(LVICON[lv],"sm")}<span class="lv-${lv}">${lv} ${fs.length}건</span>
      <span class="line"></span>${n?`<button class="btn ghost sm" data-lv="${lv}">${svg("wand","sm")}서식 ${n}건 선택</button>`:""}</div>`
      +fs.map(card).join("");
  }).join("");
  const head=r.domain==="api"?specNote(r)+ledger(r)+probeLog(r):minimap(r);
  return `<div class="panel" role="tabpanel">
    <aside class="rail">
      <div class="stamp lv-${r.verdict}">${r.verdict}<small>사전검토</small></div>
      <ul class="tally">${LEVELS.map(lv=>
        `<li class="lv-${lv}"><span class="lb">${svg(LVICON[lv],"sm")}${lv}</span><b>${c[lv]}</b></li>`).join("")}</ul>
      <ul class="facts">${facts(r).map(kv=>`<li>${esc(kv[0])}<span>${esc(kv[1])}</span></li>`).join("")}</ul>
    </aside>
    <div class="body">${head}${fixBar(r)}${fixResult()}
      ${groups||`<div class="empty">${svg("check","lg")}<p>기준을 모두 충족합니다.</p>
        <small>지적사항 없이 등록 가능한 상태입니다.</small></div>`}
    </div></div>`;
}
function card(f){
  const shown=f.locations.slice(0,24);
  const more=f.count>shown.length?`<span class="chip more">외 ${f.count-shown.length}건</span>`:"";
  const on=f.fixable&&selOf(st().active).has(f.fix_key);
  const box=f.fixable
    ? `<input type="checkbox" class="fx" data-rule="${esc(f.fix_key)}" data-tier="${esc(f.fix_tier)}"
        ${on?"checked":""} aria-label="${esc(f.rule_id)} ${esc(f.fix_label)} 선택">
       <span class="tier t-${esc(f.fix_tier)}" title="${esc(f.fix_note||"")}">${esc(TIERLB[f.fix_tier]||"")}</span>`
    : "";
  const manual=f.fixable?"":`<span class="manual">${svg("lock","sm")}자동 수정 불가 — ${esc(f.manual_reason||"담당자가 직접 수정해야 합니다.")}</span>`;
  const cls=dom==="file"?"chip":"chip flat";
  return `<article class="finding lv-${f.level}" id="f_${esc(f.rule_id)}">
    <div class="top">${box}<span class="rule">${esc(f.rule_id)}</span>
      <span class="item">${esc(f.item)}</span><span class="cnt">${f.count}건</span></div>
    <p class="msg">${esc(f.message)}</p>
    ${f.fix?`<p class="fix"><span class="tag">조치</span><span>${esc(f.fix)}</span></p>`:""}
    ${manual}
    ${shown.length?`<div class="refs">${shown.map(l=>
      `<button class="${cls}" data-ref="${esc(l)}">${esc(l)}</button>`).join("")}${more}</div>`:""}
    ${f.samples.length?`<div class="samples">${f.samples.map(esc).join(" · ")}</div>`:""}
  </article>`;
}

/* ── OPEN API 전용 표시 ───────────────────────────────────── */
function specNote(r){
  const a=r.api||{};
  if(a.parse_error)
    return `<div class="specnote warn">${svg("alert","sm")} <b>기술문서를 읽지 못했습니다.</b>
      ${esc(a.parse_error)}</div>`;
  if(!a.source_name)
    return `<div class="specnote">${svg("doc","sm")} <b>등록 정보만으로 검토했습니다.</b>
      기술문서를 올리면 오퍼레이션·파라메터·에러코드 기준(12~22번)까지 검사합니다.</div>`;
  return `<div class="specnote">${svg("doc","sm")} <b>${esc(a.source_name)}</b>
    ${esc((a.notes||[]).join(" · ")||"읽었습니다.")}</div>`;
}
function ledger(r){
  const ops=(r.api||{}).ops||[];
  if(!ops.length)return "";
  return `<div class="map-head"><span class="map-title">${svg("book","sm")}오퍼레이션 대장 — ${ops.length}개</span></div>
    <div class="ledger">
      <div class="led-head"><span>방식</span><span>오퍼레이션</span><span>요청</span><span>응답</span></div>
      ${ops.map(o=>{
        const rq=(o.request||[]).length, rs=(o.response||[]).length;
        const m=String(o.method||"").toLowerCase();
        return `<div class="led-row">
          <span class="method ${esc(m)}">${esc(o.method||"—")}</span>
          <span class="led-name"><b>${esc(o.name_ko||o.name_en||"(이름없음)")}</b>
            <small>${esc(o.name_en||"")}${o.url?" · "+esc(o.url):""}</small></span>
          <span class="led-n ${rq?"":"zero"}">${rq}</span>
          <span class="led-n ${rs?"":"zero"}">${rs}</span></div>`;
      }).join("")}
    </div>`;
}
function probeLog(r){
  const ps=(r.api||{}).probes||[];
  if(!ps.length)return "";
  return `<div class="map-head"><span class="map-title">${svg("plug","sm")}실호출 기록 — ${ps.length}건</span>
      <span class="legend"><span>상태코드 · 응답시간</span></span></div>
    <div class="probelog">${ps.map(p=>{
      const bad=!p.ok||(p.status&&p.status!==200);
      return `<div class="pl-row">
        <span class="pl-u">${esc(p.called||p.url)}${p.error?" — "+esc(p.error):""}</span>
        <span class="pl-s ${bad?"bad":"ok"}">${p.status||"—"}</span>
        <span class="pl-t ${p.slow?"bad":""}">${Number(p.elapsed||0).toFixed(2)}s</span></div>`;
    }).join("")}</div>`;
}

/* ── 픽스 ─────────────────────────────────────────────────── */
function fixBar(r){
  const api=r.domain==="api";
  const fmt=r.findings.filter(f=>f.fixable&&f.fix_tier==="서식").length;
  const con=r.findings.filter(f=>f.fixable&&f.fix_tier==="내용").length;
  if(!fmt&&!con)return "";
  const sel=selOf(st().active).size;
  const where=api?"고친 값을 JSON 으로":`${(r.ext||"").toUpperCase()} 형식 그대로`;
  return `<div class="fixbar">
      <span class="lead">${svg("wand")}픽스</span>
      <button class="helpq" id="helpBtn" aria-expanded="${helpOpen}"
        aria-controls="helpBox" aria-label="픽스 기준 설명">?</button>
      ${fmt?`<button class="btn ghost sm" id="selFmt">서식 정리 ${fmt}건 선택</button>`:""}
      <button class="btn ghost sm" id="selNone">${svg("clear","sm")}선택 해제</button>
      <button class="btn sm" id="doFix" ${sel?"":"disabled"}>${svg("check","sm")}선택 ${sel}건 ${api?"고치기":"수정본 저장"}</button>
      <span class="sel">${esc(where)} 저장</span>
    </div>
    ${helpOpen?helpBox():""}
    <p class="fixnote">${api
      ? "체크한 조항만 등록 정보를 고칩니다. 고친 값은 '전 → 후' 로 보여 주고 JSON 으로도 저장하므로, 그대로 포털 등록 화면에 붙여 넣으면 됩니다. 기술문서 자체는 고치지 않습니다."
      : "체크한 조항만 자동 수정합니다. 원본은 그대로 두고 수정본을 새로 저장한 뒤, 수정본을 다시 검토해 결과 탭으로 추가합니다."}${con?` 내용 변경 ${con}건은 하나씩 확인하고 직접 체크하세요.`:""}</p>`;
}
function helpBox(){
  const api=dom==="api";
  const tail=api
    ? "기술문서(Swagger·명세표)는 어떤 경우에도 고치지 않습니다. 기관이 배포한 문서를 말없이 바꾸면 등록 내용과 어긋나기 때문이며, 문서에서 고쳐야 할 값은 따로 알려 줍니다."
    : "원본 파일은 어떤 경우에도 수정하지 않습니다. 수정본은 입력한 형식과 확장자 그대로 새 파일로 저장됩니다.";
  return `<div class="helpbox" id="helpBox"><dl>
    <dt><span class="tier t-서식">서식 정리</span></dt>
    <dd>값의 뜻은 그대로 두고 표기만 기준에 맞춥니다. ${api
      ? "목록명 특수문자, 중복 키워드, 연속 띄어쓰기, 연락처 하이픈, URL 에 붙은 요청 파라메터 같은 것들입니다."
      : "날짜 구분기호, 천 단위 콤마, 지수표기, 셀 안 줄바꿈, 항목명 단위기호 같은 것들입니다."} 전체 선택 대상입니다.</dd>
    <dt><span class="tier t-내용">내용 변경</span></dt>
    <dd>${api
      ? "목록명에서 주기·연도 표기를 지우거나 에러코드 행을 삭제합니다. 원래 값이 사라지므로"
      : "행이나 값을 지우거나 바꿉니다. 집계·주석 행 삭제, 수식 오류값 비우기, 개인정보 마스킹처럼 원래 값이 사라지는 작업이라"} 하나씩 확인하고 체크해야 합니다.</dd>
    <dt>${svg("lock","sm")}수정 불가</dt>
    <dd>${api
      ? "오퍼레이션명 작명, 항목 설명·샘플 작성, 인증모듈·포트·페이징처럼 API 구현을 고쳐야 하는 일은 프로그램이 손대지 않습니다."
      : "빈 항목명이나 빈 데이터값을 임의로 채우는 일, 깨진 글자 복원, 영문 항목명의 한글화, 공란 사유 기재는 담당자의 판단이 필요해 프로그램이 손대지 않습니다."}</dd>
  </dl><p class="tail">${tail}</p></div>`;
}
function fixResult(){
  const s=st(), fx=s.fixInfo[s.active];
  if(!fx)return "";
  const after=s.results[s.active].counts["반려"];
  const list=(fx.applied||[]).map(a=>`${a.label} ${a.count}건`).join(" · ")||"변경 없음";
  const diff=(fx.changes||[]).length
    ? `<ul class="diff">${fx.changes.map(c=>
        `<li><span class="df">${esc(c.field)}</span><span class="dv">
          <span class="db">${esc(c.before)}</span><span class="arrow">→</span>
          <span class="da">${esc(c.after)}</span></span></li>`).join("")}</ul>` : "";
  const codes=(fx.removed_codes||[]).length
    ? `<ul class="diff"><li><span class="df">에러코드 삭제</span>
        <span class="dv db">${esc(fx.removed_codes.join(" · "))}</span></li></ul>` : "";
  const manual=(fx.manual||[]).length
    ? `<ul class="manual-list">${fx.manual.map(m=>
        `<li>${svg("alert","sm")}<span>${esc(m)}</span></li>`).join("")}</ul>` : "";
  const unit=dom==="api"?"에러코드":"행";
  return `<div class="fixdone">${svg("check","sm")} <b>${esc(fx.from)}의 수정본입니다.</b>
    반려 ${fx.before}건 → ${after}건 · ${esc(list)}${fx.removed_rows?` · ${unit} ${fx.removed_rows}개 삭제`:""}
    ${fx.out_path?`<span class="path">${esc(fx.out_path)}</span>`:""}
    ${diff}${codes}${manual}</div>`;
}
function bind(){
  const s=st();
  document.querySelectorAll(".chip[data-ref]").forEach(b=>b.onclick=()=>{
    if(dom!=="file")return;
    if(!/^[A-Z]+\d+$/.test(b.dataset.ref)){toast(`${b.dataset.ref}은 행 단위 지적사항입니다.`);return;}
    mapFocus=b.dataset.ref;drawMap(s.results[s.active],true);
  });
  document.querySelectorAll(".fx").forEach(cb=>cb.onchange=()=>{
    const sel=selOf(s.active);cb.checked?sel.add(cb.dataset.rule):sel.delete(cb.dataset.rule);
    refreshFixBar();
  });
  document.querySelectorAll("[data-lv]").forEach(b=>b.onclick=()=>{
    const sel=selOf(s.active);
    s.results[s.active].findings
      .filter(f=>f.level===b.dataset.lv&&f.fixable&&f.fix_tier==="서식")
      .forEach(f=>sel.add(f.fix_key));
    render();
  });
  const fmt=$("selFmt"), none=$("selNone"), go=$("doFix"), help=$("helpBtn");
  if(fmt)fmt.onclick=()=>{const sel=selOf(s.active);
    s.results[s.active].findings.filter(f=>f.fixable&&f.fix_tier==="서식").forEach(f=>sel.add(f.fix_key));
    render();};
  if(none)none.onclick=()=>{s.picked[s.active]=new Set();render();};
  if(go)go.onclick=runFix;
  if(help)help.onclick=()=>{helpOpen=!helpOpen;render();};
}
function refreshFixBar(){
  const go=$("doFix");if(!go)return;
  const n=selOf(st().active).size;
  go.disabled=!n;
  go.innerHTML=svg("check","sm")+`선택 ${n}건 ${dom==="api"?"고치기":"수정본 저장"}`;
}
async function runFix(){
  const s=st(), rules=[...selOf(s.active)];
  if(!rules.length)return;
  const go=$("doFix");go.disabled=true;go.innerHTML=svg("spin","sm")+"수정 중…";
  try{
    const cur=s.results[s.active];
    const res=dom==="api"
      ? await window.pywebview.api.fix_api(s.active,rules)
      : await window.pywebview.api.fix(cur.file_path,rules);
    if(res.cancelled){toast("저장을 취소했습니다.");refreshFixBar();return;}
    if(res.error){toast(res.error);refreshFixBar();return;}
    const before=cur.counts["반려"], from_=cur.file_name;
    s.results.push(res.after);
    s.active=s.results.length-1;
    s.fixInfo[s.active]={...res.report, from:from_, before:before};
    mapFocus=null;render();
    toast(`수정 완료 · 반려 ${before} → ${res.after.counts["반려"]}건`);
  }catch(e){toast("수정 중 오류: "+e);refreshFixBar();}
}

/* ── 셀 위치 지도 (파일데이터 전용) ────────────────────────── */
function mapSize(r){
  return {cols:Math.min(r.cols||0,MAP.MAXC), rows:Math.min(r.rows||0,MAP.MAXR)};
}
function minimap(r){
  if(!r.cols||!r.rows)return "";
  const {cols,rows}=mapSize(r);
  const cut=(r.cols>cols||r.rows>rows)?` · 앞쪽 ${cols}열 ${rows}행 표시`:"";
  return `<div class="map-head">
      <span class="map-title">${svg("grid","sm")}셀 위치 지도 — ${cols}열 × ${rows}행, 1행은 항목명${cut}</span>
      <span class="legend">${LEVELS.map(l=>`<span><i class="bg-${l}"></i>${l}</span>`).join("")}</span>
      <span class="map-read" id="mapRead">셀 위로 이동</span>
    </div>
    <div class="map" id="mapBox"><div class="spacer" id="mapSpacer"></div>
      <canvas id="mapCv"></canvas></div>`;
}
function colName(i){let s="";i++;while(i){const m=(i-1)%26;s=String.fromCharCode(65+m)+s;i=Math.floor((i-1)/26);}return s;}
function refToXY(ref){
  const m=/^([A-Z]+)(\d+)$/.exec(ref);if(!m)return null;
  let c=0;for(const ch of m[1])c=c*26+(ch.charCodeAt(0)-64);
  return {c:c-1,r:+m[2]-1};
}
function buildIndex(r){
  mapIndex={};
  Object.entries(r.grid||{}).forEach(([ref,lv])=>{
    const p=refToXY(ref);if(!p)return;
    (mapIndex[p.r]=mapIndex[p.r]||[]).push([p.c,lv]);
  });
}
function drawMap(r,scrollTo){
  const box=$("mapBox"), cv=$("mapCv"), sp=$("mapSpacer");
  if(!box||!cv||!sp)return;
  const {cols,rows}=mapSize(r);
  const W=MAP.GUT+cols*MAP.CW, H=MAP.HDR+rows*MAP.CH;
  sp.style.width=W+"px";sp.style.height=H+"px";

  if(scrollTo&&mapFocus){
    const p=refToXY(mapFocus);
    if(p&&p.c<cols&&p.r<rows){
      box.scrollTop=Math.max(0,MAP.HDR+p.r*MAP.CH-box.clientHeight/2);
      box.scrollLeft=Math.max(0,MAP.GUT+p.c*MAP.CW-box.clientWidth/2);
    }else{toast(`${mapFocus}은 지도 표시 범위를 벗어났습니다.`);}
  }

  const sx=box.scrollLeft, sy=box.scrollTop;
  const vw=Math.max(1,Math.min(box.clientWidth,W)), vh=Math.max(1,Math.min(box.clientHeight,H));
  const dpr=window.devicePixelRatio||1;
  cv.style.left=sx+"px";cv.style.top=sy+"px";
  cv.style.width=vw+"px";cv.style.height=vh+"px";
  cv.width=Math.round(vw*dpr);cv.height=Math.round(vh*dpr);
  const g=cv.getContext("2d");if(!g)return;
  g.setTransform(dpr,0,0,dpr,0,0);
  const C={base:cssVar("--rule-2"),line:"#fff",txt:cssVar("--ink-3"),ink:cssVar("--ink")};
  const LC={"반려":cssVar("--reject"),"보완필요":cssVar("--action"),"확인권장":cssVar("--review")};
  const X=c=>MAP.GUT+c*MAP.CW-sx, Y=rw=>MAP.HDR+rw*MAP.CH-sy;
  const c0=Math.max(0,Math.floor(sx/MAP.CW)), c1=Math.min(cols,Math.ceil((sx+vw-MAP.GUT)/MAP.CW)+1);
  const r0=Math.max(0,Math.floor(sy/MAP.CH)), r1=Math.min(rows,Math.ceil((sy+vh-MAP.HDR)/MAP.CH)+1);

  g.clearRect(0,0,vw,vh);
  g.fillStyle=C.base;
  g.fillRect(MAP.GUT,MAP.HDR,Math.min(vw-MAP.GUT,X(cols)-MAP.GUT),
             Math.min(vh-MAP.HDR,Y(rows)-MAP.HDR));
  g.strokeStyle=C.line;g.lineWidth=1;g.beginPath();
  for(let c=c0;c<=c1;c++){const x=X(c)+.5;if(x>=MAP.GUT&&x<=vw){g.moveTo(x,MAP.HDR);g.lineTo(x,Math.min(vh,Y(rows)));}}
  for(let rw=r0;rw<=r1;rw++){const y=Y(rw)+.5;if(y>=MAP.HDR&&y<=vh){g.moveTo(MAP.GUT,y);g.lineTo(Math.min(vw,X(cols)),y);}}
  g.stroke();

  for(let rw=r0;rw<r1;rw++){
    const hits=mapIndex[rw];if(!hits)continue;
    const y=Y(rw);
    hits.forEach(([c,lv])=>{
      if(c<c0||c>=c1)return;
      g.fillStyle=LC[lv]||C.txt;
      g.fillRect(X(c)+1,y+1,MAP.CW-2,MAP.CH-2);
    });
  }
  if(mapFocus){
    const p=refToXY(mapFocus);
    if(p&&p.c>=c0&&p.c<c1&&p.r>=r0&&p.r<r1){
      g.strokeStyle=C.ink;g.lineWidth=1.5;
      g.strokeRect(X(p.c)-.5,Y(p.r)-.5,MAP.CW+1,MAP.CH+1);
    }
  }

  g.fillStyle="#fff";
  g.fillRect(0,0,vw,MAP.HDR);g.fillRect(0,0,MAP.GUT,vh);
  g.fillStyle=C.txt;g.font="8px Consolas, monospace";
  g.textAlign="center";
  for(let c=c0;c<c1;c++){const x=X(c)+MAP.CW/2;if(x>MAP.GUT)g.fillText(colName(c),x,MAP.HDR-5);}
  g.textAlign="right";
  for(let rw=r0;rw<r1;rw++){
    if(rw!==0&&(rw+1)%5!==0)continue;
    const y=Y(rw)+8;if(y>MAP.HDR)g.fillText(String(rw+1),MAP.GUT-6,y);
  }

  box.onscroll=()=>{if(mapRaf)return;
    mapRaf=requestAnimationFrame(()=>{mapRaf=0;drawMap(st().results[st().active]);});};
  cv.onmousemove=ev=>{
    const el=$("mapRead");if(!el)return;
    const p=pointToCell(ev,cv,box,cols,rows);
    el.textContent=p?`${p.ref} · ${r.grid[p.ref]||"지적 없음"}`:"셀 위로 이동";
  };
  cv.onclick=ev=>{
    const p=pointToCell(ev,cv,box,cols,rows);
    if(!p||!r.grid[p.ref])return;
    mapFocus=p.ref;drawMap(r);
    const hit=r.findings.find(f=>f.locations.includes(p.ref));
    if(hit){const el=$("f_"+hit.rule_id);
      if(el&&el.scrollIntoView){el.scrollIntoView({block:"center",behavior:"smooth"});
        el.classList.remove("flash");void el.offsetWidth;el.classList.add("flash");}}
  };
}
function pointToCell(ev,cv,box,cols,rows){
  const b=cv.getBoundingClientRect();
  const vx=ev.clientX-b.left, vy=ev.clientY-b.top;
  if(vx<MAP.GUT||vy<MAP.HDR)return null;
  const c=Math.floor((vx+box.scrollLeft-MAP.GUT)/MAP.CW);
  const rw=Math.floor((vy+box.scrollTop-MAP.HDR)/MAP.CH);
  if(c<0||rw<0||c>=cols||rw>=rows)return null;
  return {c,r:rw,ref:colName(c)+(rw+1)};
}

renderFiles();renderSpec();render();
window.addEventListener("pywebviewready",async()=>{
  try{
    $("criteria").textContent=await window.pywebview.api.criteria();
    const a=await window.pywebview.api.about();
    $("cfVer").textContent="v"+a.version;
    $("cfDate").textContent="배포 "+a.release;
  }catch(e){}
});
</script>
</body>
</html>
"""
