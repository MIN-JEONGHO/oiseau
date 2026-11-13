"""화면 자산과 호스트 자체 확인 시험. 실제 WebView 창은 띄우지 않는다.

확인하는 것: ui 파일에 외부 참조(http://·https://·//cdn)가 없음, CSP 메타가 있음, 허용 함수 목록이 브리지와 같음,
화면 용어가 가이드라인·혁신법 이름이고 옛 이름이 남지 않음, 창 제목·프로그램 이름·기본 파일 이름,
`python app.py --selfcheck`가 창 없이 JSON을 내고 종료 코드 0으로 끝남(고시 검색 지문·시험 질의 포함),
03 고시 검색·04 설정 메뉴와 검색 탭 자산, 개별 검토 결과에만 있는 '고시 검색에서 열기', 화면에 검색 점수 없음.
간단한 결과(1.3.0): 개별·일괄 결과의 순서와 자리(간단한 결과 → 접힌 '상세 보기' 안에 1.2.0 화면), 일괄 표 열 이름,
간단한 결과를 그리는 부분이 brief 글만 넣고 판정·사유·건수·자르기 계산이 없음, HTML 삽입 함수 없음(정적 검사).
만든 사람 표시(1.3.0): 화면 왼쪽 메뉴 아래 고정 글과 설치 스크립트(BeveledLabel·게시자·연락처, AppId 그대로)에 있고,
실행 코드·AI 요청·결과 사전·결과 엑셀·자체 확인 출력에는 없음.
실제 화면 그리기는 헤드리스 Edge로 따로 확인한다(시험 폴더 밖 임시 스크립트).
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

import app
import bridge
import paths

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
EXTERNAL = re.compile(r"https?://|//cdn|<link[^>]+href=[\"']//", re.IGNORECASE)
UI_FILES = ("index.html", "styles.css", "app.js")
# spec 4.2의 '지금' 쪽 이름. 화면 파일 어디에도 남지 않아야 한다.
OLD_NAMES = ("한 건 판정", "일괄 판정", "과제번호", "고시 해당 판정", "판정 시작")
# 그 밖에 바뀐 옛 표기(새 이름 연구개발과제명·과제요약정보를 지운 뒤 찾는다).
OLD_TERMS = ("고시 범위", "후보 조항", "후보 항목", "범위별 판정", "종합 판정", "판정 결과", "항목 판정", "비교 판정", "기준값 표",
             "목표 수치 추출", "과제명", "과제요약", "task-number", "task-summary", "task_no")
# 만든 사람 표시(spec 7.3, 1.3.0): 화면 왼쪽 메뉴 아래와 설치 화면에만 둔다.
CREDIT = "powered by min · min@kistep.re.kr"
CREDIT_MARKERS = ("powered by min", "min@kistep.re.kr")
INSTALLER = ROOT / "installer" / "고시수준검토.iss"
APP_ID = "AppId={{6F3C2A51-9B7E-4D6A-8E21-0C4B7F9D1A35}"


def ui_text(name):
    return (UI / name).read_text(encoding="utf-8")


class AssetTests(unittest.TestCase):
    def test_ui_files_exist_and_have_no_external_references(self):
        for name in ("index.html", "styles.css", "app.js"):
            path = UI / name
            self.assertTrue(path.is_file(), name)
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(EXTERNAL.search(text), f"{name}: 외부 참조 발견")
        html = (UI / "index.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertIn("connect-src 'none'", html)
        self.assertIn(bridge.NOTE_TEXT, html)
        self.assertEqual(paths.ui_root(), UI)
        self.assertTrue((ROOT / "resources" / "book_icon.ico").is_file())

    def test_host_allowlist_equals_bridge_and_bridge_has_them(self):
        self.assertEqual(tuple(app.PUBLIC_METHODS), tuple(bridge.PUBLIC_METHODS))
        for name in app.PUBLIC_METHODS:
            self.assertTrue(callable(getattr(bridge.Bridge, name)), name)

    def test_javascript_has_no_judgement_arithmetic_on_result_values(self):
        # 화면은 표시만 한다: 판정·건수·차이 %를 JavaScript에서 다시 계산하지 않고, 지원금 글도 숫자로 해석하지 않는다.
        script = (UI / "app.js").read_text(encoding="utf-8")
        for forbidden in ("gap_percent_display=", "verdict=", "counts[", "near_percent*", "Number(comp.", "parseFloat(",
                          "parseInt(", "Number(", "isNaN(", "valueAsNumber", "Math."):
            self.assertNotIn(forbidden, script, forbidden)
        self.assertNotIn("innerHTML", script)

    def test_old_names_are_gone_from_screen_files(self):
        for name in UI_FILES:
            text = ui_text(name)
            for old in OLD_NAMES:
                self.assertNotIn(old, text, f"{name}: {old}")
            stripped = text.replace("연구개발과제명", "").replace("과제요약정보", "")
            for old in OLD_TERMS:
                self.assertNotIn(old, stripped, f"{name}: {old}")

    def test_new_names_on_screen(self):
        html, script = ui_text("index.html"), ui_text("app.js")
        for label in ("<title>연구보안 등급분류 분류기준(고시) 검토</title>", "연구개발과제 개별 검토", "연구개발과제 일괄 검토", "검토 대상 고시", ">검토 시작<",
                      "연구개발과제명", "과제요약정보", "최종목표", "연구개발내용", "활용계획 및 기대효과", "연구개발단계",
                      "정부지원연구개발비(백만원)", "고시 수준 검토 결과(AI 참고)", "일괄 검토 결과"):
            self.assertIn(label, html, label)
        for label in ("종합 검토 결과", "고시별 검토 결과", "입력 행 번호", "연구개발과제명", "연구개발단계", "입력 정보",
                      "정부지원연구개발비(백만원)", "(없음)", "검토 대상 고시 하나 이상 선택 필요", "연구개발과제명 입력 필요",
                      "선택 칸 경고", "사양 비교 결과", "조항 검토 결과", "최종목표 사양 추출", "관련 고시 조항 선별"):
            self.assertIn(label, script, label)
        # 연구개발단계는 목록에서 고른다. 지원금은 숫자 전용이 아닌 글 칸이다.
        stage = re.search(r'<select id="task-rnd-stage"[^>]*>(.*?)</select>', html, re.S)
        self.assertIsNotNone(stage)
        options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', stage.group(1))
        self.assertEqual(options, [("", "선택 안 함"), ("기초연구", "기초연구"), ("응용연구", "응용연구"), ("개발연구", "개발연구")])
        fund = re.search(r'<input id="task-gov-fund"[^>]*>', html)
        self.assertIsNotNone(fund)
        self.assertNotIn('type="number"', fund.group(0))
        self.assertIn('id="gov-fund-note"', html)
        for field_id in ("task-title", "task-final-goal", "task-rnd-content", "task-utilization"):
            self.assertIn(f'id="{field_id}"', html)
        # 화면이 보내는 과제 입력 키는 브리지의 키와 같다.
        for key in bridge.TASK_KEYS:
            self.assertIn(f"{key}:", script, key)

    def test_window_title_program_name_and_default_file_names(self):
        self.assertEqual(paths.PROGRAM_NAME, "연구보안 등급분류 분류기준(고시) 검토")
        self.assertEqual(paths.PROGRAM_VERSION, "1.4.2")
        self.assertEqual(app.TITLE, "연구보안 등급분류 분류기준(고시) 검토 · v1.4.2")
        self.assertEqual(app.REPORT_FILENAME, "연구보안등급분류_분류기준고시검토_결과.xlsx")
        self.assertEqual(app.TEMPLATE_FILENAME, "연구보안등급분류_분류기준고시검토_일괄검토입력양식.xlsx")

    # ── 1.3.2: 이름 바꾸기와 화면 문구 정리 ─────────────────────────────────
    def test_renamed_program_on_screen_1_3_2(self):
        html, script, css = ui_text("index.html"), ui_text("app.js"), ui_text("styles.css")
        # 왼쪽 맨 위는 고정된 두 줄, 상단 줄은 전체 이름.
        self.assertIn('<div class="brand"><span>연구보안 등급분류</span><span>분류기준(고시) 검토</span></div>', html)
        self.assertIn(".brand span{display:block", css)
        self.assertIn(f'<div class="topbar-path">{paths.PROGRAM_NAME} <span aria-hidden="true"> / </span>', html)
        # 버전 줄은 번호만(프로그램이 준 값), 처음 글은 그대로.
        self.assertIn("$('sidebar-version').textContent = `v${initial.program.version}`;", script)
        self.assertNotIn("initial.program.name", script)
        self.assertIn('<span id="sidebar-version">버전 확인 중</span>', html)
        # 프로그램 이름 자리에 옛 이름이 남지 않는다. 결과 제목만 그대로 둔다.
        self.assertEqual(html.count("고시 수준 검토"), 1)
        self.assertIn("<h2>고시 수준 검토 결과(AI 참고)</h2>", html)
        for source in ("paths.py", "bridge.py", "pipeline.py", "excel_report.py", "batch.py", "brief.py"):
            self.assertNotIn("고시 수준 검토", (ROOT / source).read_text(encoding="utf-8"), source)
        self.assertNotIn("고시수준검토", (ROOT / "app.py").read_text(encoding="utf-8"))

    def test_screen_wording_1_3_2(self):
        html, script = ui_text("index.html"), ui_text("app.js")
        # 상단 상태 표시: 성공 글에 기준본 이름을 붙이지 않는다. 나머지 상태 글은 그대로.
        self.assertIn("$('connection-status').textContent = '고시DB 연결됨';", script)
        self.assertNotIn("고시 기준본 ${", script)
        self.assertEqual(script.count("연결됨"), 1)
        self.assertIn('id="connection-status">앱 연결 확인 중</span>', html)
        self.assertIn("'앱 연결 필요'", script)
        # 01 과제요약정보 문구(동작은 그대로: 칸별 표시와 아래 안내 줄이 남는다).
        self.assertIn('<h3 class="data-label">과제요약정보 <small class="mini-text">※첨부파일 미 업로드 시 필수 입력사항</small></h3>', html)
        self.assertNotIn("확인한 첨부 발췌가 없으면 세 칸 모두 필수", html)
        self.assertEqual(html.count("<em>* 발췌 확인 시 선택</em>"), 3)
        self.assertIn("연구개발과제명과 과제요약정보 세 칸(또는 확인한 첨부 발췌)이 있을 때 검토 가능", html)
        # 이번 실행 설정에는 근접 기준 줄이 없다(1.3.3부터 설정 화면의 고시 기준본 칸에도 없다 — 아래 1.3.3 시험).
        run_info = script[script.index("function renderRunInfo()"):script.index("function renderSettingsForm()")]
        self.assertNotIn("근접", run_info)
        self.assertNotIn("near_percent", run_info)
        for label in ("'제공자'", "'모델'", "'로컬 주소'", "'API 키'"):
            self.assertIn(label, run_info, label)
        # 02 입력 파일 칸의 설명 문단은 없고, 읽은 뒤의 건수·제외·경고 자리는 그대로다.
        batch = html[html.index('id="screen-batch"'):html.index('id="screen-search"')].replace("\r\n", "\n")
        self.assertNotIn("1행 머리글", batch)
        self.assertNotIn("사유와 함께 제외", batch)
        self.assertNotIn('<p class="mini-text"></p>', batch)
        self.assertIn('<section class="panel"><h2>입력 파일</h2>\n            <div class="picker-row"><button type="button" id="save-template"', batch)
        for element_id in ("batch-read-metrics", "batch-excluded", "batch-warnings"):
            self.assertIn(f'id="{element_id}"', batch)

    # ── 1.3.3: 설정 '고시 기준본'과 01 첨부파일 문구 ─────────────────────────
    def test_catalogue_panel_and_attachment_wording_1_3_3(self):
        html, script = ui_text("index.html"), ui_text("app.js")
        # 설정 '고시 기준본': 근접 기준(%) 줄과 '지문 보기'(두 지문)를 보이지 않는다. 나머지 줄은 그대로.
        catalogue = script[script.index("function renderCatalogue()"):script.index("function setExcerptConfirmed(")]
        for gone in ("근접", "near_percent", "지문", "fingerprint", "details"):
            self.assertNotIn(gone, catalogue, gone)
        for label in ("'기준본'", "'고시 조항 수'", "'고시 기준 사양 표 조항 수'"):
            self.assertIn(label, catalogue, label)
        self.assertIn("고시일 ${n.announcement_date} · 시행일 ${n.effective_date}", catalogue)
        self.assertNotIn("지문 보기", script)
        self.assertNotIn("근접 기준", script)
        # 값 자체는 결과 엑셀 처리내역에 그대로 나온다(화면에서만 뺐다).
        report = (ROOT / "excel_report.py").read_text(encoding="utf-8")
        for label in ('"근접 기준(%)"', '"기준본 지문"', '"고시 기준 사양 표 지문"'):
            self.assertIn(label, report, label)
        # 01 첨부파일 고르기 아래 안내.
        self.assertIn('<p class="mini-text">※ RFP나 연구개발계획서(HWPX, PDF, DOCX 중 하나)를 업로드해주세요</p>', html)
        self.assertNotIn("HWPX·PDF·DOCX 한 개", html)
        self.assertNotIn("글은 PC 안에서만 꺼내며", html)
        # 발췌 확인 뒤에만 AI로 간다는 상태 글과 시작 안내는 그대로 남는다.
        self.assertIn("'발췌 미확인 · 발췌 확인 뒤 AI로 전달'", script)
        self.assertIn("확인한 발췌만 AI로 전달(연구개발단계·지원금 미전달)", script)

    def test_installer_names_and_old_shortcut_cleanup_1_3_2(self):
        text = INSTALLER.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines()]
        self.assertIn(f'#define AppName "{paths.PROGRAM_NAME}"', lines)
        self.assertIn('#define OldAppName "고시 수준 검토"', lines)
        self.assertIn('#define AppExe "고시판정v1.exe"', lines)
        self.assertIn("AppName={#AppName}", lines)
        self.assertIn("UninstallDisplayName={#AppName}", lines)
        self.assertIn("DefaultGroupName={#AppName}", lines)
        self.assertIn("UsePreviousGroup=no", lines)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\연구보안등급분류_분류기준고시검토", lines)
        # 기존 설치는 전의 폴더를 그대로 쓰고 전의 바탕화면 선택을 기억한다(설치 프로그램 기본 동작을 끄지 않는다).
        for line in lines:
            self.assertFalse(line.startswith("UsePreviousAppDir"), line)
            self.assertFalse(line.startswith("UsePreviousTasks"), line)
        deletes = lines[lines.index("[InstallDelete]") + 1:]
        deletes = [line for line in deletes[:next(i for i, line in enumerate(deletes) if line.startswith("["))]
                   if line and not line.startswith(";")]
        # 지우는 것은 옛 이름 바로가기 둘·바탕화면 바로가기와, 비어 있을 때의 옛 묶음 폴더뿐이다.
        self.assertEqual(deletes, [
            r'Type: files; Name: "{autoprograms}\{#OldAppName}\{#OldAppName}.lnk"',
            r'Type: files; Name: "{autoprograms}\{#OldAppName}\{#OldAppName} 제거.lnk"',
            r'Type: dirifempty; Name: "{autoprograms}\{#OldAppName}"',
            r'Type: files; Name: "{autodesktop}\{#OldAppName}.lnk"',
        ])
        icons = lines[lines.index("[Icons]") + 1:]
        icons = icons[:next(i for i, line in enumerate(icons) if line.startswith("["))]
        self.assertIn(r'Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"', icons)
        self.assertIn(r'Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"', icons)
        self.assertIn(r'Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon', icons)
        # 빌드 배치: CRLF 줄끝(LF만 쓰면 빌드가 되지 않고도 종료 코드 0), 새 이름과 새 설치 파일 이름.
        raw = (ROOT / "build_exe.bat").read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        batch = raw.decode("utf-8")
        self.assertIn(f"echo  {paths.PROGRAM_NAME} - 설치 파일 빌드", batch)
        self.assertIn(rf"echo 완료: dist\연구보안등급분류_분류기준고시검토_설치_v{paths.PROGRAM_VERSION}.exe", batch)
        self.assertIn(r'"%ISCC%" /Q "installer\고시수준검토.iss"', batch)
        self.assertNotIn("고시 수준 검토", batch)

    def test_selfcheck_runs_without_a_window_and_passes(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        completed = subprocess.run([sys.executable, str(ROOT / "app.py"), "--selfcheck"], cwd=str(ROOT), env=env,
                                   capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIs(report["pass"], True)
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["checks"]["catalogue"]["catalogue_id"], "kr-notices-v16-1")
        self.assertEqual(report["checks"]["table"]["record_count"], 507)
        self.assertEqual(report["checks"]["bridge"]["public_methods"], list(bridge.PUBLIC_METHODS))
        self.assertIs(report["checks"]["ui"]["external_references"], False)
        self.assertEqual(report["program"], dict(name="연구보안 등급분류 분류기준(고시) 검토", version="1.4.2"))
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        # 만든 사람 표시는 화면·설치 화면에만 있다(자체 확인 출력에도 없음).
        for marker in CREDIT_MARKERS:
            self.assertNotIn(marker, completed.stdout + completed.stderr, marker)
        # 고시 검색: 관련어 사전·모델·조항 벡터 지문과 검색 시험 질의.
        search = report["checks"]["search"]
        self.assertEqual(search["clause_count"], 507)
        self.assertIs(search["dictionary"]["available"], True)
        self.assertRegex(search["dictionary"]["fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(search["semantic"]["state"], "ready")
        for key in ("model_fingerprint", "vectors_fingerprint", "vectors_sha256"):
            self.assertRegex(search["semantic"][key], r"^[0-9a-f]{64}$", key)
        self.assertEqual(set(search["queries"]), {app.SELFCHECK_DRAM[0], app.SELFCHECK_CODE[0], app.SELFCHECK_UNRELATED})
        self.assertIn(app.SELFCHECK_DRAM[1], search["queries"][app.SELFCHECK_DRAM[0]]["top"])
        self.assertEqual(search["queries"][app.SELFCHECK_CODE[0]]["top"][0], app.SELFCHECK_CODE[1])
        self.assertEqual(search["queries"][app.SELFCHECK_CODE[0]]["similar"], 0)
        self.assertEqual(search["queries"][app.SELFCHECK_UNRELATED]["results"], 0)
        self.assertIs(report["checks"]["bridge"]["search_available"], True)
        self.assertIs(report["checks"]["bridge"]["search_limits_refused"], True)
        self.assertEqual(report["checks"]["native_gate"]["accepted"], len(bridge.PUBLIC_METHODS))

    def test_search_tab_assets(self):
        html, script = ui_text("index.html"), ui_text("app.js")
        # 왼쪽 메뉴 순서와 번호(spec 2).
        menu = re.findall(r'<button type="button"[^>]*data-view="(\w+)"[^>]*><span aria-hidden="true">(\d\d)</span>([^<]+)</button>',
                          html)
        self.assertEqual(menu, [("single", "01", "연구개발과제 개별 검토"), ("batch", "02", "연구개발과제 일괄 검토"),
                                ("search", "03", "고시 검색"), ("settings", "04", "설정")])
        self.assertIn('id="screen-search"', html)
        self.assertIn("<!-- 03 고시 검색", html)
        self.assertIn("<!-- 04 설정 -->", html)
        for element in ('id="search-query"', 'id="search-family"', 'id="search-button"', 'id="search-results"',
                        'id="search-similar"', 'id="search-results-more"', 'id="search-similar-more"', 'id="search-empty"',
                        'id="search-notices"', 'id="search-focus"', 'id="search-footer"'):
            self.assertIn(element, html, element)
        for label in ("<h2>검색 결과</h2>", "<h2>비슷한 뜻(참고)</h2>", ">검색</button>", "검토 대상 고시", "고시 조항 상세"):
            self.assertIn(label, html, label)
        # 안내 문구는 엔진과 같은 글(초기 표시용. 실행 중에는 엔진 값으로 바꾼다).
        import notice_search
        self.assertIn(notice_search.NOTICE_SIMILAR, html)
        self.assertIn(notice_search.NOTICE_FOOTER, html)
        self.assertIn(notice_search.NOTICE_NO_RESULTS, html)
        # 화면은 두 검색 함수를 부르고, 엔터로도 검색하며, 첫 검색 준비 중을 알린다.
        for text in ("call('search_notices'", "call('get_notice_detail'", "'Enter'", "isComposing", "검색 준비 중",
                     "next_offset", "semantic?.notice", "dictionary?.notice", "data.footer", "고시 기준 사양 목록",
                     "추가 확인 조건 원문", "숫자 없는 갈래 원문", "고시 기준 사양 채택 실패(원문 확인 필요)", "criteria.message",
                     "'mark'", "search: '고시 검색'"):
            self.assertIn(text, script, text)
        # 검색 점수는 화면에 없다(결과에도 없다).
        for forbidden in ("score", "similarity", "toFixed("):
            self.assertNotIn(forbidden, script, forbidden)

    def test_open_in_search_only_on_single_review_items(self):
        script = ui_text("app.js")
        button = "node('button', '고시 검색에서 열기'"
        # 버튼은 한 곳(searchButton)에서만 만들고, 개별 검토의 초과·근접 조항·미달 조항·추가 검토 필요·상세 카드가 쓴다.
        self.assertEqual(script.count(button), 1)
        helper = script[script.index("function searchButton("):script.index("// ── 03 고시 검색")]
        self.assertIn(button, helper)
        self.assertIn("openInSearch(clauseId)", helper)
        single = script[script.index("// ── 간단한 결과"):script.index("// ── 03 고시 검색")]
        for use in ("searchButton(entry.clause_id)", "searchButton(clause.clause_id)"):
            self.assertIn(use, single, use)
        # 조항 줄의 단추는 개별 화면에서만 붙는다(일괄의 중점 과제 카드는 붙이지 않는다).
        self.assertIn("if (withSearch) row.append(searchButton(clause.clause_id));", single)
        card = script[script.index("function focusCard("):script.index("function fold(")]
        self.assertIn("clauseBlock(clause, false)", card)
        self.assertNotIn("searchButton", card)
        batch_render = script[script.index("function renderBatchResult("):script.index("async function saveReport(")]
        self.assertNotIn("openInSearch", batch_render)
        self.assertNotIn("searchButton", batch_render)
        self.assertNotIn("고시 검색에서 열기", batch_render)
        opener = script[script.index("async function openInSearch("):script.index("function closeFocus(")]
        self.assertIn("show('search')", opener)
        self.assertIn("call('get_notice_detail', clauseId, '')", opener)

    # ── 간단한 결과(1.3.0) ─────────────────────────────────────────────
    def test_no_html_insertion_anywhere_in_the_script(self):
        script = ui_text("app.js")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser",
                          "createContextualFragment", "srcdoc", "eval(", "new Function"):
            self.assertNotIn(forbidden, script, forbidden)

    def test_single_result_layout_puts_brief_first_and_folds_the_old_screen(self):
        html = ui_text("index.html")
        panel = html[html.index('<section class="panel" id="single-result"'):html.index("</section>",
                                                                                      html.index('id="single-result"'))]
        # 1.4.0 순서: 과제명·결과 → 안내 줄 → 초과·근접 고시 조항(펼침) → 미달 조항(접힘) → 추가 검토 필요(접힘) → 상세 보기(접힘)
        order = ["id=\"single-overview\"", "id=\"single-hints\"", "id=\"single-focus-items\"", "id=\"single-under\"",
                 "id=\"single-review\"", "id=\"single-detail\""]
        positions = [panel.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions))
        detail = panel[panel.index('id="single-detail"'):]
        self.assertRegex(detail, r'^id="single-detail"[^>]*>\s*<summary>상세 보기</summary>')
        self.assertNotRegex(panel, r'<details[^>]*id="single-detail"[^>]*\sopen')
        for inner in ('id="single-summary"', 'id="single-items"', 'id="single-extra"', "고시 조항별 검토 결과"):
            self.assertIn(inner, detail, inner)
        self.assertIn("초과·근접 고시 조항", panel)
        self.assertIn("추가 검토 필요", panel)
        # 미달 조항·추가 검토 필요는 스크립트 없이 열고 닫히는 접힘이고, 처음에는 닫혀 있으며 0건이면 숨는다.
        for fold_id, title_id, list_id in (("single-under", "single-under-title", "single-under-items"),
                                           ("single-review", "single-review-title", "single-review-list")):
            self.assertRegex(panel, rf'<details id="{fold_id}" class="brief-fold" hidden><summary id="{title_id}">')
            self.assertNotRegex(panel, rf'<details[^>]*id="{fold_id}"[^>]*\sopen')
            self.assertIn(f'id="{list_id}"', panel)
        # 공통 안내 칸과 옛 '해당 고시 조항' 묶음은 없다(화면 맨 아래 한 줄은 그대로).
        for gone in ('id="single-notices"', 'id="single-brief"', 'id="single-brief-items"', "brief-notices", "해당 고시 조항"):
            self.assertNotIn(gone, html, gone)
        self.assertIn('<p class="footer-note bottom-note" id="bottom-note">이 결과는 고시 수치 기준과의 참고 대조이며 고시 해당 여부의 '
                      '공식 판정이 아님.</p>', html)

    def test_batch_result_layout_and_table_columns(self):
        html, script = ui_text("index.html"), ui_text("app.js")
        panel = html[html.index('<section class="panel" id="batch-result"'):html.index("</section>",
                                                                                     html.index('id="batch-result"'))]
        # 1.4.0 순서: 건수 줄 → 종합 건수 → 안내 줄 → 중점 검토 과제 → 판정하지 못한 과제 → 그 밖의 과제(접힘) → 상세 보기(접힘)
        order = ['id="batch-count-line"', 'id="batch-tally"', "건수를 누르면 그 결과의 과제만 보임", 'id="batch-hints"',
                 'id="batch-picked"', 'id="batch-default"', 'id="batch-focus-items"',
                 'id="batch-unjudged"', 'id="batch-other"', "결과 엑셀 '초과·근접 조항' 시트", 'id="batch-detail"']
        positions = [panel.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions))
        detail = panel[panel.index('id="batch-detail"'):]
        self.assertRegex(detail, r'^id="batch-detail"[^>]*>\s*<summary>상세 보기</summary>')
        for inner in ('id="batch-counts"', 'id="batch-rows"'):
            self.assertIn(inner, detail, inner)
        # 판정하지 못한 과제는 접지 않는 묶음(없으면 숨김), 그 밖의 과제는 닫힌 접힘(없으면 숨김).
        self.assertIn('<div id="batch-unjudged" class="brief-block" hidden>', panel)
        self.assertRegex(panel, r'<details id="batch-other" class="brief-fold" hidden><summary id="batch-other-title">')
        self.assertNotRegex(panel, r'<details[^>]*id="batch-other"[^>]*\sopen')
        for element_id in ("batch-focus-title", "batch-unjudged-title", "batch-unjudged-rows", "batch-other-rows"):
            self.assertIn(f'id="{element_id}"', panel)
        # 1.4.1: 종합 건수를 누르면 보이는 묶음(처음에는 숨김)과 '전체 보기' 단추. 처음 화면의 세 묶음은 batch-default 안에 있다.
        self.assertIn('<div id="batch-picked" class="brief-block" hidden>', panel)
        self.assertIn('<button type="button" id="batch-picked-close" class="text-link">전체 보기</button>', panel)
        for element_id in ("batch-picked-title", "batch-picked-items"):
            self.assertIn(f'id="{element_id}"', panel)
        default = panel[panel.index('<div id="batch-default">'):panel.index("결과 엑셀 '초과·근접 조항' 시트")]
        for element_id in ("batch-focus", "batch-unjudged", "batch-other"):
            self.assertIn(f'id="{element_id}"', default)
        self.assertNotIn('id="batch-picked"', default)
        for gone in ('id="batch-notices"', 'id="batch-brief-rows"', "'해당 고시 조항' 시트"):
            self.assertNotIn(gone, html, gone)
        self.assertIn("초과·근접한 사양은 결과 엑셀 '초과·근접 조항' 시트, 모든 비교는 '고시 조항별 상세' 시트에서 확인", panel)
        self.assertIn("['입력 행 번호', '연구개발과제명', '상태', '오류 사유']", script)
        self.assertIn("['입력 행 번호', '연구개발과제명', '사유', '추가 검토 필요']", script)
        self.assertNotIn("'해당 조항'", script)
        # 1.2.0 일괄 표는 상세 보기 안에 그대로 남고, 5.4 건수 열이 붙는다.
        self.assertIn("['입력 행 번호', '연구개발과제명', '연구개발단계', '상태', '종합 검토 결과', '고시별 검토 결과', '확인 표시', "
                      "'AI 호출', '오류 사유'", script)

    def test_brief_rendering_only_places_python_text(self):
        script = ui_text("app.js")
        region = script[script.index("// ── 간단한 결과"):script.index("// ── 결과 표시(개별 검토)")]
        batch_render = script[script.index("function renderBatchResult("):script.index("async function saveReport(")]
        brief_batch = batch_render[:batch_render.index("// 상세 보기")]
        for part in (region, brief_batch):
            # 판정·사유·건수·묶음·순서·인용 자르기는 Python(brief)이 했다. 화면은 다시 계산하지 않는다.
            # ('judge'는 낱말로만 막는다 — 묶음 이름 unjudged는 Python이 준 키다.)
            self.assertNotRegex(part, r"\bjudge\b")
            for forbidden in ("comparisons", "gap_percent", "threshold", "operator", "facts", "dropped",
                              ".sort(", ".reduce(", ".filter(r", "slice(", "substr", "'…'", "+=", "+ 1", "- 1", ".length +",
                              ".length -", ".length}", "'초과'", "'근접'", "'미달'", "'수치 비교 불가'", "확인 필요)",
                              "상세 보기에서 확인", "처리내역에서 확인", "=== '고시", "== '고시", ".verdict ===", ".overall ===",
                              ".group ===", ".kind ==="):
                self.assertNotIn(forbidden, part, forbidden)
        for used in ("brief.overall", "brief.reason", "brief.families", "brief.hints", "brief.empty_message", "brief.focus",
                     "brief.under", "brief.review", "counts.under", "counts.review", "clause.verdict", "clause.family_label",
                     "clause.code", "clause.title", "clause.flags", "clause.lines", "line.display_reason", "entry.reason",
                     "entry.family_label"):
            self.assertIn(used, region, used)
        for used in ("result.tally", "entry.label", "entry.count", "entry.kind", "result.groups", "groups.focus",
                     "groups.unjudged", "groups.other", "result.focus_label", "result.focus_empty_message",
                     "result.unjudged_label", "result.other_label", "result.hints", "brief.reason", "counts.review",
                     "result.tally_members", "members[entry.kind]"):
            self.assertIn(used, brief_batch, used)
        # 간단한 결과의 없어진 키를 읽지 않는다(고시 기준본의 notices, 고시 검색·상세 보기의 items는 다른 것이라 그대로다).
        for gone in ("brief.notices", "result.notices", "brief.items", "brief.summary_cell", "summary_cell", "briefItem(",
                     "familyLines"):
            self.assertNotIn(gone, script, gone)
        # 판정 이름은 표시 색을 고르는 대응표 한 곳에만 있고, 옛 이름은 없다.
        self.assertIn("const VERDICT_CLASSES = {'고시 사양 초과': 'over', '고시 사양 근접': 'near', '고시 사양 미달': 'under'};", script)
        for name in ("고시 사양 초과", "고시 사양 근접", "고시 사양 미달"):
            self.assertEqual(script.count(f"'{name}'"), 1, name)
        for old in ("사양 미달 또는 무관", "최종목표 수치 없음"):
            self.assertNotIn(old, script, old)
            self.assertNotIn(old, ui_text("index.html"), old)
        # 5.4 감춘 것의 건수는 Python 숫자 그대로 상세 보기에 보인다.
        for label, value in (("간단한 결과에 넣지 않은 관련 조항 수", "counts.hidden"),
                             ("세부 기술 일치로 답했지만 남기지 않은 조항 수", "counts.detail_match_dropped")):
            self.assertIn(label, script, label)
            self.assertIn(value, script, value)

    def test_tally_counts_are_buttons_that_show_their_tasks(self):
        # 1.4.1: 종합 건수는 단추다. 누르면 그 건수에 든 과제(Python이 준 tally_members의 위치)만 과제 카드로 보이고,
        # 같은 단추를 다시 누르거나 '전체 보기'를 누르면 처음 화면으로 돌아간다. 화면은 과제를 고르거나 세지 않는다.
        script, css = ui_text("app.js"), ui_text("styles.css")
        batch_render = script[script.index("function renderBatchResult("):script.index("async function saveReport(")]
        self.assertIn("node('button', title, `tally-item ${entry.kind}`)", batch_render)
        self.assertIn("const picked = pick(members[entry.kind]);", batch_render)
        self.assertIn("button.disabled = !picked.length;", batch_render)                 # 과제가 없는 건수는 누를 수 없다
        self.assertIn("showTally(state.tallyPick === button ? null : button, title, picked)", batch_render)
        self.assertIn("showTally(null);", batch_render)                                  # 새 결과를 그리면 처음 화면부터
        self.assertIn("$('batch-picked-close').addEventListener('click', () => showTally(null));", script)
        show = script[script.index("function showTally("):script.index("function renderBatchResult(")]
        self.assertIn("$('batch-default').hidden = Boolean(button); $('batch-picked').hidden = !button;", show)
        self.assertIn("rows.forEach(row => items.append(taskCard(row)));", show)
        self.assertIn("aria-pressed", show)
        for forbidden in (".overall", ".verdict", ".kind", ".count", ".filter(", ".sort(", "'고시"):
            self.assertNotIn(forbidden, show, forbidden)
        # 과제 카드는 개별 화면의 간단한 결과와 같은 글을 놓는다: 사유·오류 사유·안내 줄·초과·근접 조항·접힌 미달 조항·추가 검토 필요.
        card = script[script.index("function taskCard("):script.index("function renderBrief(")]
        for used in ("brief.overall", "row.row_number", "row.title", "brief.reason", "row.error_reason", "brief.hints",
                     "brief.focus", "brief.under", "brief.review", "underTitle(counts)", "reviewTitle(counts)",
                     "clauseBlock(clause, false)", "reviewItem(entry, false)"):
            self.assertIn(used, card, used)
        for forbidden in ("searchButton", "openInSearch", "judge", "comparisons", "=== '", ".sort(", ".filter("):
            self.assertNotIn(forbidden, card, forbidden)
        # 접힌 묶음의 제목 글은 한 곳에서 만든다(개별 화면과 과제 카드가 같이 쓴다).
        self.assertEqual(script.count("`미달 조항 ${textValue(counts.under)}건`"), 1)
        self.assertEqual(script.count("`추가 검토 필요 ${textValue(counts.review)}건`"), 1)
        self.assertIn("reviewItem(entry, true)", script)
        for rule in ("button.tally-item{", 'button.tally-item[aria-pressed="true"]{', "button.tally-item:disabled{",
                     "button.tally-item:focus-visible{", ".picked-head{"):
            self.assertIn(rule, css, rule)

    def test_pair_wording_is_mapping_everywhere_the_user_sees(self):
        # 1.4.1: 화면·결과 엑셀·진행 글의 '짝'은 모두 '매핑'이다(AI에 보내는 지시문만 그대로 둔다).
        import ai_stages
        import brief
        import excel_report
        import judge_engine
        import pipeline
        for name in ("app.js", "index.html", "styles.css"):
            self.assertNotIn("짝", ui_text(name), name)
        script = ui_text("app.js")
        for text in ("'매핑 근거'", "· 매핑 ${result.calls.pair}", "'버린 최종목표 사양·매핑(사유와 함께)'"):
            self.assertIn(text, script, text)
        self.assertEqual(judge_engine.FLAG_PAIR, "매핑 확인 필요")
        self.assertEqual(judge_engine.REASON_NO_FACT, "매핑된 최종목표 사양 없음")
        self.assertEqual(ai_stages.STAGE_LABELS[ai_stages.STAGE_PAIR], "매핑")
        self.assertEqual(pipeline.DROP_STAGE_PAIR, "매핑")
        self.assertEqual(brief.HINT_DROPPED, "버린 최종목표 사양·매핑 {}건")
        self.assertEqual(excel_report.DETAIL_COLUMNS[-1], "매핑 근거")
        visible = (judge_engine.FLAGS + tuple(ai_stages.STAGE_LABELS.values()) + excel_report.DETAIL_COLUMNS
                   + excel_report.SUMMARY_COLUMNS + excel_report.FOCUS_COLUMNS + brief.CLAUSE_FLAGS)
        for text in visible:
            self.assertNotIn("짝", text, text)
        # 프로그램 코드에 '짝'이 남은 곳은 AI에 보내는 매핑 지시문(_SYSTEM_PAIR)뿐이다.
        folder = Path(excel_report.__file__).resolve().parent
        for path in sorted(folder.glob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            if path.name == "ai_stages.py":     # 지시문: '_SYSTEM_PAIR = """'로 시작하는 줄부터 '"""'만 있는 줄까지
                start = next(i for i, line in enumerate(lines) if line.startswith('_SYSTEM_PAIR = """'))
                end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == '"""')
                self.assertIn("짝", "\n".join(lines[start:end + 1]))     # 지시문은 바꾸지 않았다
                del lines[start:end + 1]
            self.assertNotIn("짝", "\n".join(lines), path.name)

    def test_hidden_sheet_wording_on_screen(self):
        # 처리내역은 숨김 시트다. 화면에서 그 이름을 말하는 글 여섯 곳은 모두 '처리내역(숨김 시트)'로 쓴다(일곱째는 연결 함수의 안내 줄).
        html, script = ui_text("index.html"), ui_text("app.js")
        self.assertEqual(script.count("처리내역(숨김 시트)"), 6)
        self.assertNotRegex(script, r"처리내역(?!\(숨김 시트\))")
        self.assertNotIn("처리내역", html)
        import bridge
        self.assertEqual(bridge.BATCH_OPTION_HINT, "선택 칸 경고 {}건 — 상세 보기·처리내역(숨김 시트)에서 확인")

    def test_result_workbook_has_three_visible_sheets_and_a_hidden_log(self):
        # 합성 과제를 모의 AI로 끝까지 돌려 저장한 엑셀: 보이는 시트 셋 + 숨김 처리내역, 공통 안내 세 줄은 어디에도 없다.
        import tempfile
        from openpyxl import load_workbook
        import excel_report
        import pipeline
        from tests.mock_model import MockModel
        from tests.test_pipeline import ALL_FAMILIES, FACTS, INDEX, TABLE, TASK
        model = MockModel(facts=FACTS, candidates={"advanced:item:001", "dual_use:control:1A003"})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "결과.xlsx"
            excel_report.write_report(path, [result], dict(run_time="2026-11-13 09:00:00"))
            book = load_workbook(path)
            names = book.sheetnames
            states = {sheet.title: sheet.sheet_state for sheet in book.worksheets}
            active = book.active.title
            cells = [str(cell.value) for sheet in book.worksheets for row in sheet.iter_rows() for cell in row
                     if cell.value is not None]
            book.close()
        self.assertEqual(names, ["초과·근접 조항", "과제별 검토 결과", "고시 조항별 상세", "처리내역"])
        self.assertEqual(states, {"초과·근접 조항": "visible", "과제별 검토 결과": "visible", "고시 조항별 상세": "visible",
                                  "처리내역": "hidden"})
        self.assertEqual(active, "초과·근접 조항")
        for notice in ("원문 확인이 필요함", "원문으로 확인이 필요함", "공식 판정이 아님"):
            self.assertFalse(any(notice in cell for cell in cells), notice)

    # ── 만든 사람 표시(1.3.0, spec 7.3) ───────────────────────────────────
    def test_creator_credit_on_screen_below_the_version(self):
        html, css, script = ui_text("index.html"), ui_text("styles.css"), ui_text("app.js")
        self.assertEqual(html.count(CREDIT), 1)
        sidebar = html[html.index('<aside class="sidebar">'):html.index("</aside>")]
        # 왼쪽 메뉴 아래, 프로그램 이름·버전 표시 바로 다음의 고정 글(링크·외부 연결 없음).
        self.assertIn(f'<div class="sidebar-credit">{CREDIT}</div>', sidebar)
        self.assertLess(sidebar.index('id="sidebar-version"'), sidebar.index(CREDIT))
        self.assertLess(sidebar.index("</nav>"), sidebar.index(CREDIT))
        self.assertNotIn("<a ", sidebar)
        self.assertNotIn("mailto:", html)
        self.assertIn(".sidebar-credit{", css)
        # 화면 스크립트는 이 글을 만들거나 바꾸지 않는다(정적 글).
        for marker in CREDIT_MARKERS + ("sidebar-credit",):
            self.assertNotIn(marker, script, marker)

    def test_creator_credit_in_installer_and_app_id_unchanged(self):
        text = INSTALLER.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines()]
        messages = lines[lines.index("[Messages]") + 1:]
        messages = messages[:next(i for i, line in enumerate(messages) if line.startswith("["))]
        self.assertIn(f"BeveledLabel={CREDIT}", messages)
        self.assertIn("AppPublisher=min", lines)
        self.assertIn("AppContact=min@kistep.re.kr", lines)
        self.assertEqual(lines.count(APP_ID), 1)
        self.assertIn(f'#define AppVersion "{paths.PROGRAM_VERSION}"', lines)
        self.assertIn("OutputBaseFilename=연구보안등급분류_분류기준고시검토_설치_v{#AppVersion}", lines)

    def test_creator_credit_not_in_ai_requests_results_or_program_code(self):
        # 실행 코드(AI 요청·결과 엑셀·처리내역을 만드는 Python)에는 이 글이 없다.
        for source in sorted(ROOT.glob("*.py")):
            text = source.read_text(encoding="utf-8")
            for marker in CREDIT_MARKERS:
                self.assertNotIn(marker, text, f"{source.name}: {marker}")
        # 합성 과제를 모의 AI로 끝까지 돌려도 AI 요청·결과 사전·결과 엑셀 어디에도 없다.
        import tempfile
        from openpyxl import load_workbook
        import excel_report
        import pipeline
        from tests.mock_model import MockModel
        from tests.test_pipeline import ALL_FAMILIES, FACTS, INDEX, TABLE, TASK
        model = MockModel(facts=FACTS, candidates={"advanced:item:001", "dual_use:control:1A003"})
        result = pipeline.run_task(TASK, ALL_FAMILIES, model, TABLE, INDEX)
        self.assertEqual(result.status, pipeline.STATUS_DONE)
        self.assertTrue(model.requests)
        requests = json.dumps([dict(system=r["system"], user=r["user"]) for r in model.requests], ensure_ascii=False)
        dumped = json.dumps(result.to_dict(), ensure_ascii=False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "결과.xlsx"
            excel_report.write_report(path, [result], dict(run_time="2026-11-10 09:00:00"))
            book = load_workbook(path)
            cells = [str(cell.value) for sheet in book.worksheets for row in sheet.iter_rows() for cell in row
                     if cell.value is not None]
            book.close()
        self.assertTrue(cells)
        for marker in CREDIT_MARKERS:
            self.assertNotIn(marker, requests, marker)
            self.assertNotIn(marker, dumped, marker)
            self.assertFalse(any(marker in cell for cell in cells), marker)


if __name__ == "__main__":
    unittest.main()
