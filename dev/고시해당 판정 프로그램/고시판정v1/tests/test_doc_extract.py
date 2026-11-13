"""doc_extract 시험. 첨부 글 꺼내기(HWPX·DOCX·PDF)와 목표 발췌.

시험 자료는 모두 임시 폴더 안에서 합성해 만든다. 실제 과제 자료는 쓰지 않는다.
"""
import io
import logging
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

import doc_extract
from doc_extract import DocumentError, GoalSection, extract_text, find_goal_sections


# ---------------------------------------------------------------------------
# 합성 자료 만들기
# ---------------------------------------------------------------------------
HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _hp_para(text: str) -> str:
    return f'<hp:p id="1" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run></hp:p>'


def _hp_table(rows: list[list[str]]) -> str:
    trs = []
    for row in rows:
        tcs = []
        for cell in row:
            paras = "".join(_hp_para(line) for line in cell.split("\n"))
            tcs.append(f'<hp:tc name="" header="0"><hp:subList id="">{paras}</hp:subList></hp:tc>')
        trs.append("<hp:tr>" + "".join(tcs) + "</hp:tr>")
    tbl = f'<hp:tbl id="9" rowCnt="{len(rows)}" colCnt="{len(rows[0])}">' + "".join(trs) + "</hp:tbl>"
    # 실제 HWPX처럼 표는 문단의 run 안에 들어간다.
    return f'<hp:p id="2" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">{tbl}</hp:run></hp:p>'


def make_hwpx(path: Path, paragraphs: list[str], table_rows: list[list[str]] | None = None, extra_xml: str = "",
              with_section: bool = True) -> Path:
    body = "".join(_hp_para(t) for t in paragraphs)
    if table_rows:
        body += _hp_table(table_rows)
    body += extra_xml
    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec xmlns:hs="{HS_NS}" xmlns:hp="{HP_NS}">{body}</hs:sec>'
    )
    hpf = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        '</opf:manifest><opf:spine><opf:itemref idref="header"/><opf:itemref idref="section0"/></opf:spine>'
        '</opf:package>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("Contents/header.xml", '<?xml version="1.0" encoding="UTF-8"?><hh:head xmlns:hh="x"/>')
        z.writestr("Contents/content.hpf", hpf)
        if with_section:
            z.writestr("Contents/section0.xml", section)
    return path


def _w_para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _w_table(rows: list[list[str]]) -> str:
    trs = []
    for row in rows:
        tcs = "".join(f"<w:tc>{''.join(_w_para(line) for line in cell.split(chr(10)))}</w:tc>" for cell in row)
        trs.append(f"<w:tr>{tcs}</w:tr>")
    return "<w:tbl>" + "".join(trs) + "</w:tbl>"


def make_docx(path: Path, paragraphs: list[str], table_rows: list[list[str]] | None = None, extra_xml: str = "",
              with_document: bool = True) -> Path:
    body = "".join(_w_para(t) for t in paragraphs)
    if table_rows:
        body += _w_table(table_rows)
    body += extra_xml
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", content_types)
        if with_document:
            z.writestr("word/document.xml", document)
    return path


def _build_pdf(objects: list[bytes]) -> bytes:
    """객체 목록(1번부터, 1번이 Catalog)으로 xref가 맞는 최소 PDF를 조립한다."""
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for idx, body in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{idx} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return buf.getvalue()


def _stream(data: bytes, extra: bytes = b"") -> bytes:
    return b"<< /Length " + str(len(data)).encode() + b" " + extra + b" >>\nstream\n" + data + b"\nendstream"


def make_korean_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Type0 글꼴(Identity-H, 글꼴 미내장) + ToUnicode로 한글 줄을 쓴 PDF. 추출 검증용."""
    tounicode = (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        b"1 beginbfrange\n<0000> <FFFF> <0000>\nendbfrange\n"
        b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    )
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # Pages, 아래에서 채움
        b"<< /Type /Font /Subtype /Type0 /BaseFont /MalgunGothic /Encoding /Identity-H "
        b"/DescendantFonts [4 0 R] /ToUnicode 5 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /MalgunGothic "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 6 0 R /DW 1000 /CIDToGIDMap /Identity >>",
        _stream(tounicode),
        b"<< /Type /FontDescriptor /FontName /MalgunGothic /Flags 4 /FontBBox [0 -200 1000 900] "
        b"/ItalicAngle 0 /Ascent 900 /Descent -200 /CapHeight 700 /StemV 80 >>",
    ]
    kids = []
    for lines in pages:
        page_num = len(objects) + 1
        content_num = page_num + 1
        kids.append(f"{page_num} 0 R")
        if lines:
            objects.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {content_num} 0 R >>".encode("ascii")
            )
            ops = [b"BT /F1 12 Tf 50 750 Td 16 TL"]
            for line in lines:
                ops.append(b"<" + line.encode("utf-16-be").hex().encode("ascii") + b"> Tj T*")
            ops.append(b"ET")
            objects.append(_stream(b"\n".join(ops)))
        else:
            objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode("ascii")
    path.write_bytes(_build_pdf(objects))
    return path


def make_image_only_pdf(path: Path) -> Path:
    img = bytes([0xFF, 0x00, 0x00, 0xFF])  # 2x2 회색 이미지
    path.write_bytes(_build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        _stream(img, b"/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8"),
        _stream(b"q 200 0 0 200 100 500 cm /Im1 Do Q"),
    ]))
    return path


def make_encrypted_pdf(path: Path, src: Path, password: str) -> Path:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(str(src)))
    writer.encrypt(password, algorithm="RC4-128")  # RC4는 추가 암호 라이브러리 없이 동작
    with open(path, "wb") as f:
        writer.write(f)
    return path


# ---------------------------------------------------------------------------
# 시험
# ---------------------------------------------------------------------------
class ExtractBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class ConstantsTest(unittest.TestCase):
    def test_supported_extensions(self):
        self.assertEqual(set(doc_extract.SUPPORTED_EXTENSIONS), {".hwpx", ".docx", ".pdf"})

    def test_goal_headings_cover_spec(self):
        for word in ("최종 목표", "연구개발 목표", "최종 연구목표", "정량적 목표", "성능지표", "핵심 성능지표", "평가 항목"):
            self.assertIn(word, doc_extract.GOAL_HEADINGS)

    def test_no_agpl_pdf_library(self):
        import sys

        import doc_extract as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(fitz|pymupdf|pdfminer)\b", source, re.MULTILINE))
        self.assertIsNone(re.search(r"import_module\(\s*['\"](fitz|pymupdf)", source))
        self.assertNotIn("fitz", sys.modules)
        self.assertNotIn("pymupdf", sys.modules)


class HwpxTest(ExtractBase):
    def test_paragraphs_and_table_cells(self):
        path = make_hwpx(self.tmp / "a.hwpx", ["과제명: 합성 과제", "3. 최종 연구목표", "추력 120 kN급 엔진 개발"],
                         table_rows=[["항목", "목표치"], ["비추력", "300 초"]])
        result = extract_text(path)
        self.assertEqual(result.kind, "hwpx")
        self.assertIsNone(result.page_count)
        self.assertEqual(result.warnings, [])
        lines = result.text.split("\n")
        self.assertIn("과제명: 합성 과제", lines)
        self.assertIn("3. 최종 연구목표", lines)
        self.assertIn("항목 | 목표치", lines)
        self.assertIn("비추력 | 300 초", lines)
        # 문단 순서 유지
        self.assertLess(lines.index("3. 최종 연구목표"), lines.index("추력 120 kN급 엔진 개발"))
        self.assertLess(lines.index("추력 120 kN급 엔진 개발"), lines.index("항목 | 목표치"))

    def test_multiline_cell_keeps_lines(self):
        path = make_hwpx(self.tmp / "b.hwpx", [], table_rows=[["최종 목표", "목표 하나\n목표 둘"]])
        result = extract_text(path)
        self.assertIn("최종 목표 | 목표 하나\n목표 둘", result.text)

    def test_unparsed_elements_are_warned_not_dropped_silently(self):
        pic = ('<hp:p id="5" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">'
               '<hp:pic id="77"><hp:img binaryItemIDRef="image1"/></hp:pic></hp:run></hp:p>')
        path = make_hwpx(self.tmp / "c.hwpx", ["본문"], extra_xml=pic)
        result = extract_text(path)
        self.assertIn("본문", result.text)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("그림", result.warnings[0])

    def test_multiple_sections_in_order(self):
        path = make_hwpx(self.tmp / "d.hwpx", ["첫째 구역"])
        with zipfile.ZipFile(path, "a") as z:
            z.writestr("Contents/section1.xml",
                       f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="{HS_NS}" xmlns:hp="{HP_NS}">'
                       f'{_hp_para("둘째 구역")}</hs:sec>')
        result = extract_text(path)
        self.assertLess(result.text.index("첫째 구역"), result.text.index("둘째 구역"))

    def test_zip_without_section_is_corrupt(self):
        path = make_hwpx(self.tmp / "e.hwpx", ["x"], with_section=False)
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "corrupt")


class DocxTest(ExtractBase):
    def test_paragraphs_and_table_cells(self):
        path = make_docx(self.tmp / "a.docx", ["과제명: 합성 과제", "3. 최종 연구목표", "추력 120 kN급 엔진 개발"],
                         table_rows=[["항목", "목표치"], ["비추력", "300 초"]])
        result = extract_text(path)
        self.assertEqual(result.kind, "docx")
        self.assertIsNone(result.page_count)
        self.assertEqual(result.warnings, [])
        lines = result.text.split("\n")
        self.assertIn("3. 최종 연구목표", lines)
        self.assertIn("항목 | 목표치", lines)
        self.assertIn("비추력 | 300 초", lines)
        self.assertLess(lines.index("추력 120 kN급 엔진 개발"), lines.index("항목 | 목표치"))

    def test_runs_tabs_and_breaks_join(self):
        xml = ('<w:p><w:r><w:t>최종</w:t></w:r><w:r><w:t xml:space="preserve"> 목표</w:t></w:r>'
               '<w:r><w:tab/><w:t>120</w:t><w:br/><w:t>둘째 줄</w:t></w:r></w:p>')
        path = make_docx(self.tmp / "b.docx", [], extra_xml=xml)
        result = extract_text(path)
        self.assertIn("최종 목표\t120\n둘째 줄", result.text)

    def test_drawing_is_warned(self):
        xml = '<w:p><w:r><w:drawing><wp:inline xmlns:wp="x"/></w:drawing></w:r></w:p>'
        path = make_docx(self.tmp / "c.docx", ["본문"], extra_xml=xml)
        result = extract_text(path)
        self.assertIn("본문", result.text)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("그림", result.warnings[0])

    def test_zip_without_document_is_corrupt(self):
        path = make_docx(self.tmp / "d.docx", ["x"], with_document=False)
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "corrupt")


class PdfTest(ExtractBase):
    def test_korean_text_pdf(self):
        path = make_korean_pdf(self.tmp / "a.pdf", [["3. 최종 연구목표", "추력 120 kN급 엔진 개발"], ["둘째 쪽 본문"]])
        result = extract_text(path)
        self.assertEqual(result.kind, "pdf")
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.warnings, [])
        self.assertIn("3. 최종 연구목표\n추력 120 kN급 엔진 개발", result.text)
        self.assertIn("둘째 쪽 본문", result.text)

    def test_empty_page_is_warned(self):
        path = make_korean_pdf(self.tmp / "b.pdf", [["글이 있는 쪽"], []])
        result = extract_text(path)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("2", result.warnings[0])

    def test_blank_pdf_is_no_text(self):
        path = make_korean_pdf(self.tmp / "c.pdf", [[], []])
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "no_text")
        self.assertIn("PDF", ctx.exception.message)

    def test_image_only_pdf_is_no_text(self):
        path = make_image_only_pdf(self.tmp / "d.pdf")
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "no_text")

    def test_encrypted_pdf(self):
        src = make_korean_pdf(self.tmp / "src.pdf", [["비밀"]])
        path = make_encrypted_pdf(self.tmp / "e.pdf", src, "pw")
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "encrypted")

    def test_garbage_pdf_is_corrupt(self):
        path = self.tmp / "f.pdf"
        path.write_bytes(b"this is not a pdf at all")
        logger = logging.getLogger("pypdf")
        previous = logger.level
        logger.setLevel(logging.ERROR)  # pypdf가 깨진 머리글을 경고 로그로 찍는 것을 시험 출력에서 뺀다
        try:
            with self.assertRaises(DocumentError) as ctx:
                extract_text(path)
        finally:
            logger.setLevel(previous)
        self.assertEqual(ctx.exception.reason_code, "corrupt")


class RejectTest(ExtractBase):
    def test_hwp_is_unsupported(self):
        path = self.tmp / "old.hwp"
        path.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 16)
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "unsupported_format")
        self.assertIn("HWP", ctx.exception.message)

    def test_other_extension_is_unsupported(self):
        path = self.tmp / "memo.txt"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(DocumentError) as ctx:
            extract_text(path)
        self.assertEqual(ctx.exception.reason_code, "unsupported_format")

    def test_extension_case_insensitive(self):
        path = make_docx(self.tmp / "UPPER.DOCX", ["대문자 확장자"])
        self.assertIn("대문자 확장자", extract_text(path).text)

    def test_missing_file(self):
        with self.assertRaises(DocumentError) as ctx:
            extract_text(self.tmp / "없음.hwpx")
        self.assertEqual(ctx.exception.reason_code, "not_found")

    def test_broken_zip(self):
        for name in ("broken.hwpx", "broken.docx"):
            path = self.tmp / name
            path.write_bytes(b"PK\x03\x04 broken bytes " + b"\x00" * 40)
            with self.assertRaises(DocumentError) as ctx:
                extract_text(path)
            self.assertEqual(ctx.exception.reason_code, "corrupt", name)

    def test_error_message_is_korean(self):
        with self.assertRaises(DocumentError) as ctx:
            extract_text(self.tmp / "없음.pdf")
        self.assertTrue(any("가" <= ch <= "힣" for ch in str(ctx.exception)))


class GoalSectionTest(unittest.TestCase):
    def test_finds_section_under_numbered_heading(self):
        text = "\n".join([
            "1. 연구개발 개요",
            "본 과제는 합성 과제이다.",
            "2. 연구 필요성",
            "필요하다.",
            "3. 최종 연구목표",
            "추력 120 kN급 엔진 개발",
            "비추력 300초 달성",
            "4. 추진 체계",
            "체계 설명",
        ])
        sections = find_goal_sections(text)
        self.assertEqual(len(sections), 1)
        sec = sections[0]
        self.assertIsInstance(sec, GoalSection)
        self.assertEqual(sec.heading, "3. 최종 연구목표")
        self.assertEqual(text[sec.start:sec.end], sec.body)
        self.assertTrue(sec.body.startswith("3. 최종 연구목표"))
        self.assertIn("비추력 300초 달성", sec.body)
        self.assertNotIn("4. 추진 체계", sec.body)
        self.assertNotIn("체계 설명", sec.body)

    def test_no_heading_returns_empty(self):
        text = "이 글에는 제목이 없다.\n그저 본문만 있다.\n목표라는 말이 문장 속에 들어 있어도 제목은 아니다."
        self.assertEqual(find_goal_sections(text), [])

    def test_two_headings_give_two_sections(self):
        text = "\n".join([
            "□ 최종 목표",
            "- 엔진 개발",
            "- 시험 완료",
            "□ 정량적 목표",
            "- 추력 120 kN",
            "□ 추진 전략",
            "- 단계별 추진",
        ])
        sections = find_goal_sections(text)
        self.assertEqual([s.heading for s in sections], ["□ 최종 목표", "□ 정량적 목표"])
        self.assertIn("- 시험 완료", sections[0].body)
        self.assertNotIn("- 추력 120 kN", sections[0].body)
        self.assertIn("- 추력 120 kN", sections[1].body)
        self.assertNotIn("단계별 추진", sections[1].body)
        self.assertLess(sections[0].end, sections[1].start)

    def test_table_row_heading(self):
        text = "과제 개요 | 합성 과제\n최종 목표 | 추력 120 kN급 엔진 개발\n연구 기간 | 3년"
        sections = find_goal_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("추력 120 kN급 엔진 개발", sections[0].body)
        self.assertNotIn("연구 기간", sections[0].body)

    def test_long_section_is_capped(self):
        text = "3. 최종 연구목표\n" + "\n".join(f"목표 설명 줄 {i}" for i in range(500))
        sections = find_goal_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertLessEqual(len(sections[0].body), doc_extract.MAX_SECTION_CHARS)
        self.assertEqual(text[sections[0].start:sections[0].end], sections[0].body)

    def test_heading_words_in_long_sentence_are_not_headings(self):
        text = "본 연구의 최종 목표는 매우 긴 문장 속에서 설명되므로 제목으로 보지 않아야 하며 이 줄은 충분히 길다.\n다음 줄"
        self.assertEqual(find_goal_sections(text), [])


if __name__ == "__main__":
    unittest.main()
