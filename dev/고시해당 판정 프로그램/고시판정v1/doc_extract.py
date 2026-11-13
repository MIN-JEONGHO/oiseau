"""첨부 글 꺼내기와 목표 발췌.

과제 첨부파일(HWPX·DOCX·PDF) 한 개에서 글을 꺼내고, 그 글에서 '최종 목표'·'성능지표' 같은
제목이 붙은 부분을 찾아 돌려준다. 모든 처리는 PC 안에서 끝나며 네트워크를 쓰지 않는다.

형식별 방법
- HWPX·DOCX: zip 안의 XML을 표준 라이브러리(xml.etree)로 읽는다. 표 안의 글도 포함한다.
  표는 한 행이 한 줄이고, 셀은 ' | '로 구분한다. 셀 안의 여러 문단은 줄바꿈으로 구분한다.
- PDF: pypdf로 쪽마다 글을 꺼낸다. 글이 전혀 없으면(스캔 이미지·빈 쪽) '글을 읽을 수 없는 PDF'로 거부한다.
- 예전 HWP(바이너리)는 지원하지 않는 형식으로 거부한다.

PDF 라이브러리 선택(pypdf, BSD)
- 후보는 MIT·BSD 계열인 pypdf와 pdfminer.six 두 가지였다. AGPL인 PyMuPDF(fitz)는 import도 하지 않는다.
- 합성 PDF(영문 Helvetica, 한글 Type0/Identity-H+ToUnicode, 빈 쪽, 이미지만 있는 쪽, 암호)와
  공개 고시 별표 PDF(3쪽, 한글)로 둘을 비교했다. 한글 복원은 둘 다 정확했다(대체 문자 0건).
- pypdf를 고른 이유: (1) 같은 고시 PDF에서 2배 이상 빨랐다(1.8초 대 4.2초). (2) 순수 파이썬이고
  추가 의존성이 없다(pdfminer.six는 cryptography·charset-normalizer를 함께 끌어온다). (3) 내용 스트림 순서로
  글을 내놓아 표의 행 머리글과 내용이 같이 붙어 나온다(pdfminer는 배치 기준으로 재정렬해 머리글이 떨어진다).
  (4) 암호 파일을 열기 전에 판별할 수 있다(`is_encrypted`).
- pdfminer.six가 나은 점: 낱말 사이 공백을 조금 더 잘 지킨다("FO-WLP, FO-PLP"가 pypdf에서는 "FO-WLP,FO-PLP").
  판정 목적에는 영향이 작다고 보았다.

해석하지 못한 요소(그림·차트·OLE·수식 등)는 조용히 버리지 않고 `warnings`에 건수와 함께 남긴다.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# 지원하는 확장자(소문자). 예전 HWP는 포함하지 않는다.
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".hwpx", ".docx", ".pdf")

# 목표 부분의 제목에 들어가는 낱말. 띄어쓰기는 무시하고 비교하므로 '최종목표'도 '최종 목표'와 같게 본다.
# 필요하면 여기에 더하거나 뺀다.
GOAL_HEADINGS: tuple[str, ...] = (
    "최종 목표",
    "연구개발 목표",
    "최종 연구목표",
    "연구 목표",
    "정량적 목표",
    "성능지표",
    "핵심 성능지표",
    "평가 항목",
)

# 제목 줄로 볼 최대 글자 수(번호·기호를 뺀 뒤). 이보다 길면 문장으로 본다.
HEADING_MAX_CHARS = 40
# 목표 부분 하나의 최대 길이(제목 포함). 다음 제목을 못 찾으면 이 길이 안에서 줄 단위로 자른다.
MAX_SECTION_CHARS = 3000

# PDF 추출 결과에 대체 문자(U+FFFD)가 이 비율 이상이면 글꼴 해석 문제로 경고한다.
_REPLACEMENT_WARN_RATIO = 0.02

_CELL_SEPARATOR = " | "


class DocumentError(Exception):
    """첨부파일을 읽을 수 없을 때. reason_code는 다음 중 하나다.

    unsupported_format: 지원하지 않는 형식(HWP 등)
    no_text:            글이 없는 PDF(스캔 이미지·빈 쪽)
    encrypted:          암호가 걸린 파일
    corrupt:            깨졌거나 구조가 맞지 않는 파일
    not_found:          파일 없음
    """

    REASON_CODES = ("unsupported_format", "no_text", "encrypted", "corrupt", "not_found")

    def __init__(self, reason_code: str, message: str):
        if reason_code not in self.REASON_CODES:
            raise ValueError(f"알 수 없는 reason_code: {reason_code}")
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


@dataclass
class ExtractResult:
    """꺼낸 글. text는 문단을 줄바꿈으로, 표 셀을 ' | '로 구분한다. page_count는 PDF만 채운다."""

    text: str
    kind: str  # hwpx | docx | pdf
    warnings: list[str] = field(default_factory=list)
    page_count: int | None = None


@dataclass
class GoalSection:
    """목표 부분 후보. start·end는 text 안의 위치이고 body == text[start:end]이다."""

    heading: str
    start: int
    end: int
    body: str


# ---------------------------------------------------------------------------
# 들머리
# ---------------------------------------------------------------------------
def extract_text(path: str | Path) -> ExtractResult:
    """첨부파일에서 글을 꺼낸다. 읽을 수 없으면 DocumentError를 던진다."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise DocumentError("not_found", f"파일을 찾을 수 없음: {path.name}")
    ext = path.suffix.lower()
    if ext == ".hwp":
        raise DocumentError("unsupported_format",
                            f"지원하지 않는 형식(HWP): {path.name}. 한글에서 HWPX 또는 PDF로 저장한 파일 필요")
    if ext not in SUPPORTED_EXTENSIONS:
        raise DocumentError("unsupported_format",
                            f"지원하지 않는 형식({ext or '확장자 없음'}): {path.name}. HWPX·DOCX·PDF만 가능")
    if ext == ".hwpx":
        return _extract_hwpx(path)
    if ext == ".docx":
        return _extract_docx(path)
    return _extract_pdf(path)


# ---------------------------------------------------------------------------
# zip 공통
# ---------------------------------------------------------------------------
def _open_zip(path: Path, label: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise DocumentError("corrupt", f"깨진 {label} 파일(zip 구조 아님): {path.name}") from None
    except OSError as exc:
        raise DocumentError("corrupt", f"{label} 파일을 열 수 없음: {path.name} ({exc})") from None


def _read_xml(zf: zipfile.ZipFile, name: str, path: Path, label: str) -> ET.Element:
    try:
        data = zf.read(name)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise DocumentError("corrupt", f"{label} 파일 안의 {name}을(를) 읽을 수 없음: {path.name} ({exc})") from None
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise DocumentError("corrupt", f"{label} 파일 안의 {name}이(가) 올바른 XML이 아님: {path.name} ({exc})") from None


def _local(tag: str) -> str:
    """'{namespace}name' → 'name'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _join_rows(rows: list[list[str]]) -> list[str]:
    """표 행을 줄 목록으로. 셀은 ' | '로 구분하고 셀 안의 여러 문단은 줄바꿈을 그대로 둔다."""
    return [_CELL_SEPARATOR.join(cells) for cells in rows]


class _Counter:
    """해석하지 못한 요소를 종류별로 센다."""

    def __init__(self):
        self.counts: dict[str, int] = {}

    def add(self, label: str) -> None:
        self.counts[label] = self.counts.get(label, 0) + 1

    def warnings(self) -> list[str]:
        return [f"{label} {n}개: 글로 읽지 못해 제외" for label, n in self.counts.items()]


# ---------------------------------------------------------------------------
# HWPX
# ---------------------------------------------------------------------------
_HWPX_SKIP_LABELS = {
    "pic": "그림",
    "container": "그리기 개체",
    "ole": "OLE 개체",
    "chart": "차트",
    "video": "동영상",
}
# 글이 없고 서식만 있는 요소. 경고 없이 지나간다.
_HWPX_FORMAT_ONLY = {
    "secPr", "ctrl", "linesegarray", "lineseg", "colPr", "fwSpace", "pageNum", "bookmark", "header", "footer",
    "footNote", "endNote", "autoNum", "newNum", "pageHiding", "pageNumCtrl", "indexmark", "hiddenComment",
    "fieldBegin", "fieldEnd", "dutmal", "compose", "sz", "pos", "outMargin", "inMargin", "cellAddr", "cellSpan",
    "cellSz", "cellMargin", "markpenBegin", "markpenEnd", "tab", "lineBreak", "hyphen", "nbSpace", "fwSpace",
    "insertBegin", "insertEnd", "deleteBegin", "deleteEnd", "switch", "case", "default", "label", "caption",
}


def _hwpx_section_names(zf: zipfile.ZipFile, path: Path) -> list[str]:
    """본문 구역 파일 이름을 순서대로. content.hpf의 spine을 따르고, 없으면 section 번호 순."""
    names = set(zf.namelist())
    ordered: list[str] = []
    if "Contents/content.hpf" in names:
        try:
            root = ET.fromstring(zf.read("Contents/content.hpf"))
            hrefs = {}
            for item in root.iter():
                if _local(item.tag) == "item":
                    hrefs[item.get("id")] = item.get("href")
            for ref in root.iter():
                if _local(ref.tag) == "itemref":
                    href = hrefs.get(ref.get("idref"))
                    if href and re.search(r"section\d+\.xml$", href):
                        name = href if href in names else "Contents/" + href
                        if name in names:
                            ordered.append(name)
        except ET.ParseError:
            ordered = []

    def key(n: str) -> int:
        m = re.search(r"section(\d+)\.xml$", n)
        return int(m.group(1)) if m else 0

    # spine에 빠진 구역 파일이 있으면 번호 순으로 뒤에 붙인다(조용히 버리지 않음).
    listed = set(ordered)
    ordered.extend(sorted((n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n) and n not in listed),
                          key=key))
    if not ordered:
        raise DocumentError("corrupt", f"HWPX 파일에 본문 구역(Contents/section*.xml)이 없음: {path.name}")
    return ordered


def _hwpx_paragraph(p: ET.Element, counter: _Counter) -> list[str]:
    """hp:p 하나를 줄 목록으로. 글은 한 줄로 모으고, 표를 만나면 줄을 끊고 행을 줄로 내놓는다."""
    lines: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            lines.append("".join(buf))
            buf.clear()

    def walk(el: ET.Element):
        for child in el:
            name = _local(child.tag)
            if name == "t":
                buf.append(child.text or "")
                # hp:t 안에 하위 요소(탭·줄바꿈 등)가 올 수 있다.
                for sub in child:
                    subname = _local(sub.tag)
                    if subname == "tab":
                        buf.append("\t")
                    elif subname == "lineBreak":
                        flush()
                    buf.append(sub.tail or "")
            elif name == "run":
                walk(child)
            elif name == "tbl":
                flush()
                lines.extend(_hwpx_table(child, counter))
            elif name == "equation":
                script = child.find("{%s}script" % _ns_of(child.tag))
                text = (script.text or "").strip() if script is not None else ""
                if text:
                    buf.append(text)
                else:
                    counter.add("수식")
            elif name in _HWPX_SKIP_LABELS:
                # 그림 등 안의 글상자(subList)는 글이므로 꺼내고, 개체 자체는 경고한다.
                counter.add(_HWPX_SKIP_LABELS[name])
                inner = _hwpx_sublist_lines(child, counter)
                if inner:
                    flush()
                    lines.extend(inner)
            elif name == "subList":
                flush()
                lines.extend(_hwpx_sublist_lines(child, counter, direct=True))
            elif name in _HWPX_FORMAT_ONLY:
                continue
            else:
                counter.add(f"알 수 없는 요소({name})")

    walk(p)
    flush()
    return lines


def _ns_of(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _hwpx_sublist_lines(el: ET.Element, counter: _Counter, direct: bool = False) -> list[str]:
    """요소 아래의 subList(글상자·셀 본문)들을 줄 목록으로. direct=True면 el 자체가 subList."""
    lines: list[str] = []
    sublists = [el] if direct else [s for s in el.iter() if _local(s.tag) == "subList"]
    for sub in sublists:
        for p in sub:
            if _local(p.tag) == "p":
                lines.extend(_hwpx_paragraph(p, counter))
    return lines


def _hwpx_table(tbl: ET.Element, counter: _Counter) -> list[str]:
    rows: list[list[str]] = []
    for tr in tbl:
        if _local(tr.tag) != "tr":
            continue
        cells: list[str] = []
        for tc in tr:
            if _local(tc.tag) != "tc":
                continue
            cell_lines: list[str] = []
            for sub in tc:
                if _local(sub.tag) == "subList":
                    cell_lines.extend(_hwpx_sublist_lines(sub, counter, direct=True))
            cells.append("\n".join(line for line in cell_lines if line.strip()))
        rows.append(cells)
    return _join_rows(rows)


def _extract_hwpx(path: Path) -> ExtractResult:
    counter = _Counter()
    lines: list[str] = []
    with _open_zip(path, "HWPX") as zf:
        for name in _hwpx_section_names(zf, path):
            root = _read_xml(zf, name, path, "HWPX")
            for p in root:
                if _local(p.tag) == "p":
                    lines.extend(_hwpx_paragraph(p, counter))
    text = _finish_lines(lines)
    warnings = counter.warnings()
    if not text.strip():
        warnings.append("본문에 글이 없음")
    return ExtractResult(text=text, kind="hwpx", warnings=warnings)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
_DOCX_SKIP_LABELS = {
    "drawing": "그림",
    "pict": "그림",
    "object": "개체",
    "oMath": "수식",
    "oMathPara": "수식",
}


def _docx_paragraph(p: ET.Element, counter: _Counter) -> list[str]:
    lines: list[str] = []
    buf: list[str] = []

    def flush():
        lines.append("".join(buf))
        buf.clear()

    def walk(el: ET.Element):
        for child in el:
            name = _local(child.tag)
            if name == "t":
                buf.append(child.text or "")
            elif name == "tab":
                buf.append("\t")
            elif name in ("br", "cr"):
                flush()
            elif name in _DOCX_SKIP_LABELS:
                counter.add(_DOCX_SKIP_LABELS[name])
                # 그림 안의 글상자(txbxContent)는 글이므로 꺼낸다.
                for box in child.iter():
                    if _local(box.tag) == "txbxContent":
                        lines.extend(_docx_body_lines(box, counter))
            elif name in ("r", "hyperlink", "smartTag", "sdt", "sdtContent", "ins", "fldSimple", "customXml"):
                walk(child)
            else:
                # rPr·pPr·bookmark·proofErr 등 서식·표식 요소
                continue

    walk(p)
    flush()
    return lines


def _docx_body_lines(body: ET.Element, counter: _Counter) -> list[str]:
    lines: list[str] = []
    for child in body:
        name = _local(child.tag)
        if name == "p":
            lines.extend(_docx_paragraph(child, counter))
        elif name == "tbl":
            lines.extend(_docx_table(child, counter))
        elif name in ("sdt", "sdtContent", "customXml"):
            lines.extend(_docx_body_lines(child, counter))
        elif name in ("sectPr", "bookmarkStart", "bookmarkEnd", "sdtPr", "sdtEndPr", "proofErr", "tblPr", "tblGrid",
                      "trPr", "tcPr", "customXmlPr"):
            continue
        else:
            counter.add(f"알 수 없는 요소({name})")
    return lines


def _docx_table(tbl: ET.Element, counter: _Counter) -> list[str]:
    rows: list[list[str]] = []
    for tr in tbl:
        if _local(tr.tag) != "tr":
            continue
        cells: list[str] = []
        for tc in tr:
            if _local(tc.tag) != "tc":
                continue
            cell_lines = _docx_body_lines(tc, counter)
            cells.append("\n".join(line for line in cell_lines if line.strip()))
        rows.append(cells)
    return _join_rows(rows)


def _extract_docx(path: Path) -> ExtractResult:
    counter = _Counter()
    with _open_zip(path, "DOCX") as zf:
        if "word/document.xml" not in zf.namelist():
            raise DocumentError("corrupt", f"DOCX 파일에 본문(word/document.xml)이 없음: {path.name}")
        root = _read_xml(zf, "word/document.xml", path, "DOCX")
    body = next((c for c in root if _local(c.tag) == "body"), None)
    if body is None:
        raise DocumentError("corrupt", f"DOCX 본문에 w:body가 없음: {path.name}")
    lines = _docx_body_lines(body, counter)
    text = _finish_lines(lines)
    warnings = counter.warnings()
    if not text.strip():
        warnings.append("본문에 글이 없음")
    return ExtractResult(text=text, kind="docx", warnings=warnings)


# ---------------------------------------------------------------------------
# PDF (pypdf)
# ---------------------------------------------------------------------------
def _extract_pdf(path: Path) -> ExtractResult:
    try:
        from pypdf import PdfReader
        from pypdf import errors as pypdf_errors
    except ImportError:
        raise DocumentError("corrupt", "PDF 읽기 라이브러리(pypdf)가 설치되어 있지 않음") from None

    try:
        reader = PdfReader(str(path))
    except pypdf_errors.PdfReadError as exc:
        raise DocumentError("corrupt", f"깨진 PDF 파일: {path.name} ({exc})") from None
    except (OSError, ValueError, TypeError) as exc:
        raise DocumentError("corrupt", f"PDF 파일을 열 수 없음: {path.name} ({exc})") from None

    if reader.is_encrypted:
        # 열람 암호가 비어 있는 파일(편집 제한만 걸린 경우)은 빈 암호로 풀어 본다.
        try:
            opened = reader.decrypt("")
        except Exception:  # noqa: BLE001 - 암호 라이브러리 부재 등 어떤 이유든 암호 파일로 본다
            opened = 0
        if not opened:
            raise DocumentError("encrypted", f"암호가 걸린 PDF: {path.name}. 암호를 푼 파일 필요")

    try:
        page_count = len(reader.pages)
    except pypdf_errors.PdfReadError as exc:
        raise DocumentError("corrupt", f"깨진 PDF 파일(쪽 목록 없음): {path.name} ({exc})") from None
    if page_count == 0:
        raise DocumentError("no_text", f"글을 읽을 수 없는 PDF(쪽이 없음): {path.name}")

    page_texts: list[str] = []
    warnings: list[str] = []
    empty_pages: list[int] = []
    failed_pages: list[int] = []
    for idx in range(page_count):
        try:
            page_text = reader.pages[idx].extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - 쪽 하나가 깨져도 나머지는 이어 간다
            failed_pages.append(idx + 1)
            warnings.append(f"{idx + 1}쪽: 글 꺼내기 실패 ({type(exc).__name__})")
            page_texts.append("")
            continue
        if not page_text.strip():
            empty_pages.append(idx + 1)
        page_texts.append(page_text.strip("\n"))

    if empty_pages:
        warnings.append(f"글이 없는 쪽 {len(empty_pages)}개: {_page_list(empty_pages)}쪽")
    if failed_pages and len(failed_pages) == page_count:
        raise DocumentError("corrupt", f"깨진 PDF 파일(모든 쪽에서 글 꺼내기 실패): {path.name}")

    text = "\n".join(page_texts)
    if not text.strip():
        raise DocumentError("no_text",
                            f"글을 읽을 수 없는 PDF: {path.name}. 스캔 이미지이거나 빈 쪽만 있음(전체 {page_count}쪽)")

    replaced = text.count("�")
    if replaced and replaced / max(len(text), 1) >= _REPLACEMENT_WARN_RATIO:
        warnings.append(f"읽지 못한 글자 {replaced}자(글꼴 정보 부족): 추출 품질 확인 필요")
    return ExtractResult(text=text, kind="pdf", warnings=warnings, page_count=page_count)


def _page_list(pages: list[int], limit: int = 10) -> str:
    shown = ", ".join(str(p) for p in pages[:limit])
    return shown + (" …" if len(pages) > limit else "")


# ---------------------------------------------------------------------------
# 공통 마무리
# ---------------------------------------------------------------------------
def _finish_lines(lines: list[str]) -> str:
    """줄 끝 공백을 지우고 빈 줄이 셋 이상 이어지지 않게 한다."""
    cleaned = [line.rstrip() for line in lines]
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


# ---------------------------------------------------------------------------
# 목표 발췌
# ---------------------------------------------------------------------------
# 제목 앞의 번호·기호. kind는 같은 급인지 비교하는 데 쓴다.
_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"(?P<arabic>\d{1,2}(?:[.\-]\d{1,2})*)\s*[.)]"
    r"|(?P<paren>\(\s*\d{1,2}\s*\))"
    r"|(?P<kor>[가나다라마바사아자차카타파하])\s*[.)]"
    r"|(?P<korparen>\(\s*[가나다라마바사아자차카타파하]\s*\))"
    r"|(?P<roman>[IVXⅠ-Ⅻ]{1,4})\s*[.)]"
    r"|(?P<circled>[①-⑳])"
    r"|(?P<bullet>[□■○●◦▪◇◆▶►•※◎▣\-ㆍ·])"
    r"|(?P<bracket>[\[【][^\]】]{1,20}[\]】])"
    r")\s*"
)
# 목록 줄 앞에 흔히 오는 기호. 번호 없는 제목 아래의 부분을 끝내지 않는다.
_LIST_BULLETS = set("-•◦▪ㆍ·")


def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s)


_GOAL_KEYS = tuple(_normalize(h) for h in GOAL_HEADINGS)


def _split_marker(line: str) -> tuple[str | None, str]:
    """(번호·기호 종류, 나머지 글). 종류는 'arabic:2'처럼 깊이를 붙이기도 한다."""
    m = _MARKER_RE.match(line)
    if not m:
        return None, line.strip()
    kind = m.lastgroup
    if kind == "arabic":
        kind = f"arabic:{m.group('arabic').count('.') + m.group('arabic').count('-') + 1}"
    elif kind == "bullet":
        # 기호마다 급이 다르다('□ 제목' 아래 '- 항목'은 같은 급이 아님).
        kind = f"bullet:{m.group('bullet')}"
    return kind, line[m.end():].strip()


def _is_table_row(line: str) -> bool:
    return _CELL_SEPARATOR in line or "\t" in line


def _first_cell(line: str) -> str:
    """표 행이면 첫 셀만. 아니면 줄 전체."""
    if _CELL_SEPARATOR in line:
        return line.split(_CELL_SEPARATOR, 1)[0]
    if "\t" in line:
        return line.split("\t", 1)[0]
    return line


def _classify(line: str) -> tuple[bool, bool, str | None]:
    """(제목 같은 줄인가, 목표 제목인가, 번호 종류)."""
    head = _first_cell(line).strip()
    if not head:
        return False, False, None
    kind, rest = _split_marker(head)
    if not rest or len(rest) > HEADING_MAX_CHARS:
        return False, False, kind
    norm = _normalize(rest)
    is_goal = any(key in norm for key in _GOAL_KEYS)
    # 문장(마침표·'다.'로 끝남)은 제목이 아니다.
    if re.search(r"(다|요)\.?$", rest) and not is_goal:
        return False, False, kind
    heading_like = kind is not None or is_goal
    return heading_like, is_goal, kind


def _same_or_higher_level(kind: str | None, base: str | None) -> bool:
    """kind 급의 제목이 base 급의 부분을 끝내는가."""
    if base is None:
        return kind is not None and not (kind.startswith("bullet:") and kind[-1] in _LIST_BULLETS)
    if kind is None:
        return False
    if base.startswith("arabic:") and kind.startswith("arabic:"):
        return int(kind.split(":")[1]) <= int(base.split(":")[1])
    return kind == base


def find_goal_sections(text: str) -> list[GoalSection]:
    """목표 부분 후보를 찾는다. 제목 줄부터 다음 같은 급 제목(또는 다른 목표 제목) 앞까지, 최대 MAX_SECTION_CHARS."""
    if not text:
        return []
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    infos = [_classify(line) for line in lines]
    sections: list[GoalSection] = []
    i = 0
    while i < len(lines):
        heading_like, is_goal, kind = infos[i]
        if not is_goal:
            i += 1
            continue
        start = offsets[i]
        end = start + len(lines[i])
        in_table = _is_table_row(lines[i])
        j = i + 1
        while j < len(lines):
            h_like, g, k = infos[j]
            if g or (h_like and _same_or_higher_level(k, kind)):
                break
            # 표 행에서 찾은 제목이면 첫 셀이 채워진 다음 행에서 끝난다(첫 셀이 빈 행은 이어지는 내용).
            if in_table and _is_table_row(lines[j]) and _first_cell(lines[j]).strip():
                break
            candidate_end = offsets[j] + len(lines[j])
            if candidate_end - start > MAX_SECTION_CHARS:
                break
            end = candidate_end
            j += 1
        # 끝에 붙은 빈 줄은 뺀다.
        body = text[start:end].rstrip()
        end = start + len(body)
        sections.append(GoalSection(heading=lines[i].strip(), start=start, end=end, body=body))
        i = j if j > i else i + 1
    return sections
