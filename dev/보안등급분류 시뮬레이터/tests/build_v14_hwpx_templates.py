"""Build small source-derived editable forms, never distribute the source book.

Developer-only: python tests/build_v14_hwpx_templates.py SOURCE.hwpx
The known source SHA is verified before extracting the actual opinion form styles.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from lxml import etree as E

SOURCE_SHA256 = "a67e47f5ac8ee07db4af584c38edc1f77f5d3243b538e61d3d2850c41e8e5cb3"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF = "http://www.idpf.org/2007/opf/"
NS = {"hp": HP, "hh": HH, "hs": HS, "opf": OPF}


def xml(root):
    return E.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def build(source):
    source = Path(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("The approved source SHA256 does not match.")
    with ZipFile(source) as zin:
        head = E.fromstring(zin.read("Contents/header.xml"))
        section = E.fromstring(zin.read("Contents/section0.xml"))
        source_table = section.xpath('.//hp:tbl[@id="1137197348"]', namespaces=NS)[0]
        # The second referenced table is the same editable 21 x 4 individual form.
        second = section.xpath('.//hp:tbl[@id="1137197437"]', namespaces=NS)[0]
        assert source_table.get("rowCnt") == second.get("rowCnt") == "21"
        assert source_table.get("colCnt") == second.get("colCnt") == "4"
        ref = head.find(f"{{{HH}}}refList")
        for name, ids in {"borderFills": ("1", "4", "30", "58"), "charProperties": ("191", "159"),
                          "tabProperties": ("0",), "paraProperties": ("19", "12"), "styles": ("0",)}.items():
            group = ref.find(f"{{{HH}}}{name}")
            kept = [deepcopy(next(x for x in group if x.get("id") == key)) for key in ids]
            group[:] = kept
            group.set("itemCnt", str(len(kept)))
            for index, element in enumerate(kept):
                element.set("id", str(index + 1 if name == "borderFills" else index))
        fonts = ref.find(f"{{{HH}}}fontfaces")
        for face in fonts:
            face[:] = [deepcopy(face[0])]
            face[0].set("id", "0")
            face.set("fontCnt", "1")
        # All retained chars use the source's first font in each language.
        for group in list(ref):
            if E.QName(group).localname in ("bullets",):
                group[:] = []
                group.set("itemCnt", "0")
        for element in head.iter():
            for key in list(element.attrib):
                if key in ("charPrIDRef", "paraPrIDRef", "nextStyleIDRef", "tabPrIDRef"):
                    element.set(key, "0")
                elif key == "borderFillIDRef":
                    element.set(key, "1")
        styles = ref.find(f"{{{HH}}}styles")
        styles[0].set("name", "바탕글")
        styles[0].set("engName", "Normal")
        for index, para in enumerate(ref.find(f"{{{HH}}}paraProperties")):
            para.find(f"{{{HH}}}align").set("horizontal", "LEFT")
            para.set("snapToGrid", "0")
            para.set("condense", "0")
        for char in ref.find(f"{{{HH}}}charProperties"):
            char.find(f"{{{HH}}}strikeout").set("shape", "NONE")
        # Copy page geometry only; remove the source book's master page and marks.
        secpr = deepcopy(section.find(f".//{{{HP}}}secPr"))
        secpr.set("masterPageCnt", "0")
        for master in secpr.findall(f"{{{HP}}}masterPage"):
            secpr.remove(master)
        for border in secpr.findall(f"{{{HP}}}pageBorderFill"):
            border.set("borderFillIDRef", "1")
        colpr = deepcopy(section.find(f".//{{{HP}}}colPr"))
        blank = E.Element(f"{{{HS}}}sec", nsmap=section.nsmap)
        p = E.SubElement(blank, f"{{{HP}}}p", id="0", paraPrIDRef="0", styleIDRef="0", pageBreak="0", columnBreak="0", merged="0")
        run = E.SubElement(p, f"{{{HP}}}run", charPrIDRef="0")
        run.append(secpr)
        ctrl = E.SubElement(run, f"{{{HP}}}ctrl")
        ctrl.append(colpr)
        E.SubElement(run, f"{{{HP}}}t").text = "{{TITLE}}"
        table_p = E.SubElement(blank, f"{{{HP}}}p", id="1", paraPrIDRef="0", styleIDRef="0", pageBreak="0", columnBreak="0", merged="0")
        table_run = E.SubElement(table_p, f"{{{HP}}}run", charPrIDRef="0")
        table = deepcopy(source_table)
        table.set("rowCnt", "1")
        table.set("repeatHeader", "0")
        table.set("zOrder", "0")
        table.set("borderFillIDRef", "2")
        table.find(f"{{{HP}}}sz").set("height", "0")
        for child in list(table):
            if E.QName(child).localname == "tr":
                table.remove(child)
        row = deepcopy(source_table.findall(f"{{{HP}}}tr")[0])
        cell = row[0]
        cell.set("borderFillIDRef", "4")
        cell.find(f"{{{HP}}}cellSz").set("height", "0")
        sub = cell.find(f"{{{HP}}}subList")
        sub.set("vertAlign", "TOP")
        sub[:] = []
        cp = E.SubElement(sub, f"{{{HP}}}p", id="2", paraPrIDRef="1", styleIDRef="0", pageBreak="0", columnBreak="0", merged="0")
        cr = E.SubElement(cp, f"{{{HP}}}run", charPrIDRef="1")
        E.SubElement(cr, f"{{{HP}}}t").text = "{{SECTION}}"
        table.append(row)
        table_run.append(table)
        package = E.Element(f"{{{OPF}}}package", nsmap={"opf": OPF}, version="", **{"unique-identifier": "", "id": ""})
        meta = E.SubElement(package, f"{{{OPF}}}metadata")
        E.SubElement(meta, f"{{{OPF}}}title").text = "AI 참고 의견서"
        E.SubElement(meta, f"{{{OPF}}}language").text = "ko"
        manifest = E.SubElement(package, f"{{{OPF}}}manifest")
        for key, href in (("header", "Contents/header.xml"), ("section0", "Contents/section0.xml"), ("settings", "settings.xml")):
            E.SubElement(manifest, f"{{{OPF}}}item", id=key, href=href, **{"media-type": "application/xml"})
        spine = E.SubElement(package, f"{{{OPF}}}spine")
        # Hangul expects the style header as the first spine resource, just as
        # in its native package. A manifest entry alone is insufficient.
        E.SubElement(spine, f"{{{OPF}}}itemref", idref="header", linear="yes")
        E.SubElement(spine, f"{{{OPF}}}itemref", idref="section0")
        container = E.fromstring(zin.read("META-INF/container.xml"))
        rootfiles = container[0]
        for rootfile in list(rootfiles):
            if rootfile.get("full-path") != "Contents/content.hpf":
                rootfiles.remove(rootfile)
        settings = E.fromstring(zin.read("settings.xml"))
        for position in settings:
            if E.QName(position).localname == "CaretPosition":
                position.set("listIDRef", "0")
                position.set("paraIDRef", "0")
                position.set("pos", "0")
        blobs = {"version.xml": zin.read("version.xml"), "Contents/header.xml": xml(head),
                 "Contents/section0.xml": xml(blank), "Contents/content.hpf": xml(package),
                 "settings.xml": xml(settings), "META-INF/container.xml": xml(container),
                 "META-INF/manifest.xml": zin.read("META-INF/manifest.xml")}
    output = Path(__file__).resolve().parents[1] / "templates"
    output.mkdir(exist_ok=True)
    for name in ("reviewer_opinion.hwpx", "committee_summary.hwpx"):
        with ZipFile(output / name, "w", ZIP_DEFLATED) as zout:
            zout.writestr("mimetype", b"application/hwp+zip", compress_type=ZIP_STORED)
            for member, data in blobs.items():
                zout.writestr(member, data)
        print(output / name)


if __name__ == "__main__":
    build(sys.argv[1])
