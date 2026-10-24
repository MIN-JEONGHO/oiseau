"""Rebuild the fixed official-source bundle locally; no network/model calls.

Maintainer dependencies: PyMuPDF 2.0 and lxml. Runtime loader is stdlib-only.
Unknown legal conditions remain explicit unsupported leaves. Source layout and
all bilingual page text remain available for audit; no representative summaries.
"""
import argparse
from bisect import bisect_right
from collections import Counter
import difflib
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from notice_catalogue_v15 import canonical_hash, load_catalogue

ROOT=Path(__file__).resolve().parents[1]/"resources_v15/notices"
# Acquisition/content verification completed at this captured UTC clock time.
# Kept fixed so a regeneration never rewrites provenance timestamps.
RETRIEVED="2026-10-20T08:28:15+00:00"
PDF_NAMES=("advanced","core","dual-use","military")


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def unsupported(identifier,text,anchor,reason="원문 조건의 정성·수치·예외·교차참조 전체 해석을 자동 확정하지 않음"):
    return dict(type="unsupported",predicate_id=identifier+":unparsed",text=text,
        source_anchor=anchor,subject="원문 전체 적용조건",reason=reason)


def clause(identifier,source,family,code,title,field,anchor,text,refs=()):
    return dict(clause_id=identifier,source_id=source,family=family,code=code,title=title,
        field=field,source_anchor=anchor,text=text,qualifier_refs=list(refs),
        condition=unsupported(identifier,text,anchor))


def lines_on_page(page,columns=None):
    output=[]
    for block in page.get_text("rawdict"if columns else"dict")["blocks"]:
        for line in block.get("lines",[]):
            # The PDF library can merge both language columns into one line.
            # Split actual glyph spans at the ruled column boundaries first.
            groups={}
            for span in line["spans"]:
                atoms=[dict(text=c["c"],bbox=c["bbox"],origin=c["origin"])for c in span["chars"]]if columns else[span]
                for atom in atoms:
                    x=atom["bbox"][0]
                    column=2 if columns and x>=columns[2]-.3 else 1 if columns and x>=columns[1]-.3 else 0
                    groups.setdefault(column,[]).append(atom)
            for spans in groups.values():
                text="".join(span["text"]for span in spans).strip()
                if not text:continue
                bbox=[min(s["bbox"][0]for s in spans),min(s["bbox"][1]for s in spans),
                    max(s["bbox"][2]for s in spans),max(s["bbox"][3]for s in spans)]
                output.append(dict(bbox=[round(x,3)for x in bbox],text=text,
                    baseline=round(max(span["origin"][1]for span in spans),3)))
    return sorted(output,key=lambda line:(round(line["bbox"][1],1),line["bbox"][0]))


def table_columns(page):
    """Read actual ruled-table geometry, rather than assuming a text x cutoff."""
    segments=[]
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0]=="l" and abs(item[1].x-item[2].x)<0.3 and abs(item[1].y-item[2].y)>100:
                segments.append((round(item[1].x,3),abs(item[1].y-item[2].y)))
    coordinates=[x for x,_ in segments]
    columns=[]
    for value in sorted(coordinates):
        if not columns or value-columns[-1]>0.3:columns.append(value)
    if len(columns)>4:
        # Embedded performance tables on pp. 162–168 have their own vertical
        # rules. The four outer table rules span the full page-height frame;
        # the nested table rules are shorter, even on nearly full-page tables.
        longest=max(length for _,length in segments)
        columns=sorted({x for x,length in segments if abs(length-longest)<0.3})
    if len(columns)!=4:raise ValueError(f"Expected three-column official table geometry, got {columns}")
    return columns


def logical_rows(lines,tolerance=2.5):
    """Group a physical text row before its code is allowed to change ownership.

    Font ascenders and isotope superscripts alter bbox tops independently of the
    baseline. Code/first sentence top ordering must never determine ownership.
    """
    rows=[]
    for line in sorted(lines,key=lambda line:(line.get("baseline",sum(line["bbox"][1::2])/2),line["bbox"][0])):
        position=line.get("baseline",sum(line["bbox"][1::2])/2)
        if rows and abs(position-rows[-1]["baseline"])<=tolerance:
            rows[-1]["lines"].append(line)
        else:rows.append(dict(baseline=position,lines=[line]))
    for row in rows:row["lines"].sort(key=lambda line:line["bbox"][0])
    return rows


def row_codes(row,columns,family):
    pattern=r"[0-9][ABCDE]\d{3}(?:\.[a-z0-9]+)*\.?" if family=="dual_use" else r"ML\s*\d+\.?"
    result=[]
    categories={line["text"]for line in row["lines"]if columns[0]<=line["bbox"][0]<columns[1]
        and re.fullmatch(r"[0-9][ABCDE]",line["text"])}
    for line in row["lines"]:
        text=line["text"];code=None;style=None
        if columns[0]<=line["bbox"][0]<columns[1] and re.fullmatch(pattern,text):
            code=re.sub(r"\s+","",text).rstrip(".");style="code_column"
        elif family=="dual_use" and columns[1]<=line["bbox"][0]<=columns[1]+3:
            match=re.match(r"^([0-9][ABCDE]\d{3})(?:\s|$)",text)
            if match and match[1][:2]in categories:
                code=match[1];style="inline_category_heading"
        if code:result.append(dict(code=code,root_code=code[:5]if family=="dual_use"else code,
            bbox=line["bbox"],style=style))
    return result


def is_category_title(text,category,language):
    """Recognize the literal section title in its own language column.

    The code column and the two text columns can have different paragraph
    heights. A category code is therefore not a boundary for either text flow.
    These are the exact headings in the fixed source, not substring matches.
    """
    titles={
        "ko":{
            "A":("시스템, 장비 및 구성품","시스템, 장비 및 부품"),
            "B":("시험, 측정 및 생산 장비","시험, 검사 및 생산 장비","시험, 검사 및 생산용 장비","시험, 검사 및 생산장비"),
            "C":("소재","물질"),"D":("소프트웨어",),"E":("기술",)},
        "en":{
            "A":("Systems, Equipment and Components",),
            "B":("Test, Inspection and Production Equipment",),
            "C":("Materials",),"D":("Software",),"E":("Technology",)}}
    normalize=lambda value:re.sub(r"\s+","",value).rstrip(".")
    return normalize(text)in{normalize(value)for value in titles[language][category[-1]]}


def extract_pages(root):
    import pymupdf
    output={}
    for name in PDF_NAMES:
        with pymupdf.open(root/"raw"/(name+"-annex.pdf")) as document:
            pages=[]
            for i,page in enumerate(document):
                columns=table_columns(page)if name in("dual-use","military")else None
                pages.append(dict(page=i+1,width=page.rect.width,height=page.rect.height,
                    text=page.get_text(sort=True),lines=lines_on_page(page,columns),
                    **({"columns":columns}if columns else {})))
            write_json(root/"extracted"/(name+".pages.json"),pages)
            output[name]=pages
    return output


def table_clauses(root):
    import pymupdf
    result=[];positions=[]
    for family in ("advanced","core"):
        index=0;field="";field_counts=Counter()
        with pymupdf.open(root/"raw"/(family+"-annex.pdf")) as document:
            for page_no,page in enumerate(document,1):
                for table_no,table in enumerate(page.find_tables().tables,1):
                    for row_no,row in enumerate(table.rows,1):
                        if len(row.cells)!=2 or row.cells[1] is None:continue
                        left=page.get_text(clip=pymupdf.Rect(row.cells[0]),sort=True).strip() if row.cells[0] else ""
                        text=page.get_text(clip=pymupdf.Rect(row.cells[1]),sort=True).strip()
                        if text=="기술명":continue
                        if family=="advanced" and text and not text.startswith("ㅇ"):
                            if not result or result[-1]["family"]!=family:raise ValueError("Unanchored advanced row continuation")
                            previous=result[-1]
                            previous["text"]+="\n"+text
                            previous["title"]=previous["text"]
                            previous["source_anchor"]+=f"&continued_page={page_no}&continued_row={row_no}"
                            previous["condition"]=unsupported(previous["clause_id"],previous["text"],previous["source_anchor"])
                            positions.append(dict(clause_id=previous["clause_id"],page=page_no,table=table_no,row=row_no,item=1,
                                bbox=list(row.cells[1]),text_sha256=sha_text(text)))
                            continue
                        if left:field=re.sub(r"\s+|\(\d+개\)","",left)
                        if not field:raise ValueError("Missing technology field")
                        parts=re.split(r"\n\s*\n",text) if family=="core" else [text]
                        if family=="core" and field=="자동차ㆍ철도":
                            # The source has intentionally unequal paragraph gaps.
                            # Split using literal item starts, checked against its 10-item field count.
                            starts=("가솔린 직접분사식","하이브리드 및 전력기반","수소전기자동차","LPG 직접분사식",
                                "Euro 6 기준","자동차 엔진ㆍ자동변속기","복합소재를 이용한","고속철도차량의 동력시스템",
                                "고속철도차량의 차체","자율주행자동차 핵심")
                            squashed=re.sub(r"[ \t]+"," ",text)
                            markers=[m.start() for m in re.finditer(r"(?m)^(?:"+"|".join(re.escape(x) for x in starts)+")",squashed)]
                            # A PDF line can contain double spacing before the literal start.
                            if not markers and text:raise ValueError("Unmatched automotive row")
                            parts=[squashed[start:stop].strip() for start,stop in zip(markers,markers[1:]+[len(squashed)])]
                        for part_no,part in enumerate(parts,1):
                            if not part.strip():continue
                            index+=1;field_counts[field]+=1
                            identifier=f"{family}:item:{index:03d}"
                            anchor=f"raw/{family}-annex.pdf#page={page_no}&table={table_no}&row={row_no}&item={part_no}"
                            text=part.removeprefix("ㅇ").strip()
                            result.append(clause(identifier,family+"-annex",family,"",text,field,anchor,text,
                                refs=["advanced:article:4"] if family=="advanced" else []))
                            positions.append(dict(clause_id=identifier,page=page_no,table=table_no,row=row_no,item=part_no,
                                bbox=list(row.cells[1]),text_sha256=sha_text(text)))
        expected=19 if family=="advanced" else 79
        if index!=expected:raise ValueError(f"{family}: expected {expected} designated items, extracted {index}; {dict(field_counts)}")
        expected_fields={"반도체":8,"디스플레이":4,"이차전지":3,"바이오":2,"로봇":1,"방산":1} if family=="advanced" else {
            "반도체":11,"디스플레이":2,"전기전자":5,"자동차ㆍ철도":10,"금속":10,"조선":8,"원자력":4,"정보통신":7,
            "우주":5,"생명공학":4,"기계":8,"로봇":3,"수소":2}
        if dict(field_counts)!=expected_fields:raise ValueError(f"Changed official field inventory: {family}: {dict(field_counts)}")
    return result,positions


def sha_text(text):return hashlib.sha256(text.encode("utf-8")).hexdigest()


def independent_pdf_inventory(root,family):
    """Independent word-level source inventory, not the assembler's line filter.

    Exact word tokens in the ruled code column are controls. A full code in the
    body column is a heading only when the same physical row also bears its
    matching category in the code column (e.g. category 0D / heading 0D001).
    """
    import pymupdf
    source="dual-use"if family=="dual_use"else"military"
    first,last=(4,553)if family=="dual_use"else(1,41)
    pattern=r"[0-9][ABCDE]\d{3}(?:\.[a-z0-9]+)*\.?"if family=="dual_use"else r"ML\d+\.?"
    positions=[];outside=[]
    with pymupdf.open(root/"raw"/(source+"-annex.pdf"))as document:
        for number in range(first,last+1):
            page=document[number-1];columns=table_columns(page);words=page.get_text("words")
            categories=[word for word in words if columns[0]<=word[0]<columns[1]and re.fullmatch(r"[0-9][ABCDE]",word[4])]
            for word in words:
                text=word[4]
                if not re.fullmatch(pattern,text):continue
                style=None
                if columns[0]<=word[0]<columns[1]:style="code_column_word"
                elif family=="dual_use" and columns[1]<=word[0]<=columns[1]+3 and re.fullmatch(r"[0-9][ABCDE]\d{3}",text):
                    if any(category[4]==text[:2] and abs((category[1]+category[3]-word[1]-word[3])/2)<=2.5 for category in categories):style="inline_category_word"
                    outside.append(dict(page=number,code=text,bbox=[round(v,3)for v in word[:4]],disposition=style or"body_reference_not_control_heading"))
                if style:
                    code=text.rstrip(".")
                    positions.append(dict(page=number,code=code,root_code=code[:5]if family=="dual_use"else code,
                        bbox=[round(v,3)for v in word[:4]],style=style))
    return dict(positions=positions,outside_code_column_candidates=outside)


HP={"hp":"http://www.hancom.co.kr/hwpml/2011/paragraph"}
STRUCTURED_RETRIEVED={"dual-use-hwpx":"2026-10-21T00:21:27.333652+00:00",
    "military-hwpx":"2026-10-21T00:21:26.799048+00:00"}


def alignment_text(text):
    """Only for locating source paragraphs; never a classification transform."""
    text=unicodedata.normalize("NFKC",text).translate(str.maketrans({
        "“":'"',"”":'"',"‘":"'","’":"'","\uf063":"χ"}))
    return re.sub(r"\s+","",text).replace("\u00ad","").replace("\u200b","").replace("-","")


def render_hwpx_paragraph(paragraph,include_tables=True):
    """Preserve body text, original equation scripts and nested table cells.

    Floating shape labels are recorded separately from legal body paragraphs.
    They include the repeated ML watermark rectangles in the official original.
    """
    pieces=[];raw=[];equations=[];tables=[];drawings=[]
    for run in paragraph.findall("hp:run",HP):
        for child in run:
            kind=child.tag.rsplit("}",1)[-1]
            if kind=="t":
                value="".join(child.itertext())
                pieces.append(value);raw.append(value)
            elif kind=="equation":
                script="".join(child.xpath("./hp:script/text()",namespaces=HP))
                equations.append(dict(id=child.get("id"),script=script))
                pieces.append("⟦원문 수식: "+script+"⟧")
            elif kind=="tbl":
                if not include_tables:continue
                rows=[]
                for ri,row in enumerate(child.findall("hp:tr",HP),1):
                    cells=[]
                    for ci,cell in enumerate(row.findall("hp:tc",HP),1):
                        values=[render_hwpx_paragraph(p)for p in cell.findall("hp:subList/hp:p",HP)]
                        texts=[v["text"]for v in values if v["text"].strip()]
                        cells.append(dict(column=ci,paragraphs=texts,
                            paragraph_records=[dict(paragraph=i,text=v["text"],sha256=sha_text(v["text"]))for i,v in enumerate(values,1)],
                            cell_address=dict(cell.find("hp:cellAddr",HP).attrib)))
                        raw.extend(v["raw_text"]for v in values)
                        equations.extend(e for v in values for e in v["equations"])
                        drawings.extend(d for v in values for d in v["drawings"])
                    rows.append(dict(row=ri,cells=cells))
                tables.append(dict(id=child.get("id"),rows=rows))
                pieces.append("\n⟦원문 표 "+str(child.get("id"))+"⟧\n"+"\n".join(
                    " | ".join("\n".join(c["paragraphs"])for c in r["cells"])for r in rows)+"\n⟦표 끝⟧\n")
            else:
                texts=child.xpath(".//hp:drawText//hp:t/text()",namespaces=HP)
                if texts:drawings.append(dict(type=kind,id=child.get("id"),text="".join(texts)))
    return dict(text="".join(pieces),raw_text="".join(raw),equations=equations,tables=tables,drawings=drawings)


def read_structured_source(root,family):
    from lxml import etree
    name="dual-use"if family=="dual_use"else"military"
    path=root/"raw"/(name+"-annex.hwpx")
    with zipfile.ZipFile(path)as archive:
        if archive.read("mimetype").strip()!=b"application/hwp+zip":raise ValueError("Invalid official HWPX mimetype")
        document=etree.fromstring(archive.read("Contents/section0.xml"),
            parser=etree.XMLParser(resolve_entities=False,no_network=True))
    rows=[];preface=[]
    for pi,p in enumerate(document.findall("hp:p",HP),1):
        content=render_hwpx_paragraph(p,include_tables=False)
        if content["text"].strip():
            preface.append(dict(paragraph_id=f"{family}:document:p{pi}",
                source_anchor=f"raw/{name}-annex.hwpx#Contents/section0.xml&document_paragraph={pi}",
                paragraph=pi,linesegs=[],**content))
    for ti,table in enumerate(document.xpath("./hp:p/hp:run/hp:tbl",namespaces=HP),1):
        for ri,row in enumerate(table.findall("hp:tr",HP),1):
            cells=[]
            for ci,cell in enumerate(row.findall("hp:tc",HP),1):
                paragraphs=cell.findall("hp:subList/hp:p",HP);records=[];blank=[]
                for pi,p in enumerate(paragraphs,1):
                    content=render_hwpx_paragraph(p)
                    if not content["text"].strip()and not content["drawings"]:
                        blank.append(pi);continue
                    identifier=f"{family}:t{ti}:r{ri}:c{ci}:p{pi}"
                    anchor=f"raw/{name}-annex.hwpx#Contents/section0.xml&table={ti}&row={ri}&cell={ci}&paragraph={pi}"
                    records.append(dict(paragraph_id=identifier,source_anchor=anchor,
                        paragraph=pi,**content,linesegs=[dict(seg.attrib)for seg in p.findall("hp:linesegarray/hp:lineseg",HP)]))
                cells.append(dict(column=ci,paragraph_count=len(paragraphs),blank_paragraphs=blank,paragraphs=records))
            if len(cells)!=3:raise ValueError("Official source outer table must have three columns")
            rows.append(dict(table=ti,row=ri,cells=cells))
    partition=Counter();layout=[]
    for p in document.xpath("//hp:p",namespaces=HP):
        ancestors=[a.tag.rsplit("}",1)[-1]for a in p.iterancestors()]
        if "drawText"in ancestors:kind="floating_shape"
        elif "header"in ancestors or "footer"in ancestors:kind="header_footer"
        elif ancestors.count("tbl")>1:kind="nested_table_cell"
        elif "tbl"in ancestors:kind="outer_table_cell"
        elif p.getparent()is document:kind="document"
        else:kind="other_layout"
        partition[kind]+=1
        if kind in("header_footer","other_layout"):
            text="".join(p.xpath("./hp:run/hp:t/text()",namespaces=HP))
            if text.strip():layout.append(dict(type=kind,text=text))
    return dict(relative_path=f"raw/{name}-annex.hwpx",sha256=sha(path),rows=rows,preface=preface,
        xml_paragraph_partition=dict(partition),layout_text=layout)


def pdf_column_streams(pages):
    streams={1:[],2:[]};positions={1:[],2:[]};lengths={1:0,2:0}
    for page in pages:
        columns=page["columns"]
        for row in logical_rows(page["lines"]):
            for line in row["lines"]:
                if re.fullmatch(r"-\s*\d+\s*-",line["text"]):continue
                column=1 if columns[1]<=line["bbox"][0]<columns[2]else 2 if line["bbox"][0]>=columns[2]else None
                if column is None:continue
                value=alignment_text(line["text"])
                start=lengths[column];lengths[column]+=len(value);streams[column].append(value)
                positions[column].append(dict(start=start,end=lengths[column],page=page["page"],
                    baseline=line["baseline"],bbox=line["bbox"],text=line["text"]))
    return {key:"".join(value)for key,value in streams.items()},positions


def project_paragraphs(source,pages):
    """Bind whole XML paragraphs to PDF text, recording every expression difference."""
    streams,positions=pdf_column_streams(pages);differences=[]
    for ci in (1,2):
        records=[p for row in source["rows"]for p in row["cells"][ci]["paragraphs"]if p["text"].strip()]
        stream=streams[ci];offset=0
        starts=[line["start"]for line in positions[ci]]
        for p in records:
            value=alignment_text(p["raw_text"])
            start=stream.find(value,offset)if value else -1
            if start<0:continue
            p["projection"]=dict(start=start,end=start+len(value),method="whole_paragraph_text")
            offset=start+len(value)
        # The finite exceptions are equation glyphs, nested tables, private-use
        # symbols and layout-only hyphenation. Keep their exact source elements.
        for index,p in enumerate(records):
            if "projection"in p:continue
            prior=next((q["projection"]["end"]for q in reversed(records[:index])if "projection"in q),0)
            following=next((q["projection"]["start"]for q in records[index+1:]if "projection"in q),len(stream))
            value=alignment_text(p["raw_text"]);found=None
            for size in (48,32,24,16,12,8):
                prefix=value[:size]
                if len(prefix)<8:continue
                at=stream.find(prefix,prior,following)
                if at>=0 and stream.find(prefix,at+1,following)<0:found=(at,len(prefix));break
            if found is None:
                raise ValueError(f"Cannot locate entire source paragraph {p['paragraph_id']}: {p['raw_text'][:100]!r}")
            p["projection"]=dict(start=found[0],end=found[0]+found[1],method="source_prefix_with_recorded_expression_difference")
        for index,p in enumerate(records):
            if p["projection"]["method"]=="whole_paragraph_text":continue
            # A prefix locates the paragraph, but is not its full extent. The
            # following source paragraph also bounds equations and six-page
            # nested tables, without dropping their PDF locations from audit.
            projection=p["projection"]
            projection["end"]=records[index+1]["projection"]["start"]if index+1<len(records)else len(stream)
            projection["end_method"]="next_source_paragraph_start"
            expected=alignment_text(p["raw_text"])
            window=stream[projection["start"]:projection["end"]]
            operations=[dict(kind=kind,original=expected[a:b],pdf=window[c:d])
                for kind,a,b,c,d in difflib.SequenceMatcher(a=expected,b=window,autojunk=False).get_opcodes()if kind!="equal"]
            kinds=[]
            if p["equations"]:kinds.append("equation_script_rendering")
            if p["tables"]:kinds.append("nested_table_cell_flow")
            if "\uf063"in p["raw_text"]:kinds.append("private_use_symbol_rendering")
            if kinds==["equation_script_rendering"]and any(op["kind"]!="insert"for op in operations):
                raise ValueError(f"Source body changed beyond equation glyph insertion: {p['paragraph_id']}")
            if kinds==["private_use_symbol_rendering"]and any(op!={"kind":"replace","original":"χ","pdf":"c"}for op in operations):
                raise ValueError(f"Unreviewed private-use symbol difference: {p['paragraph_id']}")
            if not kinds and source["relative_path"]=="raw/military-annex.hwpx":
                row=next(row for row in source["rows"]if p in row["cells"][ci]["paragraphs"])
                code=row["cells"][0]["paragraphs"][0]["text"].strip()
                if operations and all(op["kind"]=="insert"and Counter(op["pdf"])==Counter(code)for op in operations):
                    kinds.append("floating_military_code_overlay")
            if not kinds:raise ValueError(f"Unreviewed PDF/source expression difference: {p['paragraph_id']}: {operations}")
            differences.append(dict(paragraph_id=p["paragraph_id"],source_anchor=p["source_anchor"],
                original_text=p["text"],original_text_sha256=sha_text(p["text"]),raw_text_sha256=sha_text(p["raw_text"]),
                equations=p["equations"],nested_tables=p["tables"],difference_kinds=kinds,alignment_operations=operations,
                pdf_window=window,pdf_window_sha256=sha_text(window),projection=projection))
        for p in records:
            at=p["projection"]["start"]
            line=positions[ci][bisect_right(starts,at)-1]
            p["projection"].update(page=line["page"],baseline=line["baseline"],bbox=line["bbox"])
            last=positions[ci][bisect_right(starts,max(at,p["projection"]["end"]-1))-1]
            p["projection"].update(end_page=last["page"],end_baseline=last["baseline"])
        for difference in differences:
            if difference.get("pdf_lines")is None:
                projection=difference["projection"]
                difference["pdf_lines"]=[line for line in positions[ci]
                    if line["end"]>projection["start"]and line["start"]<projection["end"]]
    return differences


def category_letter(text,language):
    value=alignment_text(text)
    for letter in "ABCDE":
        if is_category_title(text,"0"+letter,language):return letter
    if (value.startswith("소재")and "해당"in value)or value.casefold().startswith("materialsnone"):
        return "C"
    if value.startswith("0D001소프트웨어")or value=="SOFTWARE":return "D"
    return None


def export_clauses(pages,family,independent,root):
    source=read_structured_source(root,family)
    differences=project_paragraphs(source,pages)
    source_id="dual-use-hwpx"if family=="dual_use"else"military-hwpx"
    pdf_name="dual-use-annex"if family=="dual_use"else"military-annex"
    groups={};assignments=[];crossings=[];category_checks=[];supplemental_ranges=[]
    expected={r["root_code"]for r in independent["positions"]}
    first_codes={}
    for r in independent["positions"]:first_codes.setdefault(r["root_code"],r)
    def position(p):return (p["projection"]["page"],p["projection"]["baseline"])
    @lru_cache(maxsize=None)
    def code_position(code):
        r=first_codes[code]
        # Font ascent differences change bbox tops. Match the code's own line.
        page=pages[r["page"]-1]
        candidates=[line for line in page["lines"]if re.sub(r"\s+","",line["text"]).rstrip(".")==r["code"]]
        baseline=candidates[0]["baseline"]if candidates else r["bbox"][3]-2
        return (r["page"],baseline)
    def attach(owner,p,language):
        if not p["text"].strip():return
        groups.setdefault(owner,[]).append((p,language))
        assignments.append(dict(paragraph_id=p["paragraph_id"],source_anchor=p["source_anchor"],owner=owner,language=language,
            text_sha256=sha_text(p["text"]),projection=p.get("projection")))
    actual_roots=set()
    for p in source["preface"]:attach(f"{family}:notes:document",p,"ko")
    for row in source["rows"]:
        ti=row["table"];ri=row["row"]
        common=f"{family}:notes:t{ti:02d}:r{ri:02d}"
        is_main=(family=="dual_use"and ti==1 and ri in(3,*range(5,14)))or(family=="military"and ti==1 and 3<=ri<=24)
        if not is_main:
            for ci,cell in enumerate(row["cells"]):
                for p in cell["paragraphs"]:attach(common,p,("code","ko","en")[ci])
            continue
        if family=="military":
            code=row["cells"][0]["paragraphs"][0]["text"].strip()
            if not re.fullmatch(r"ML(?:[1-9]|1\d|2[0-2])",code):raise ValueError("Invalid structured military row")
            actual_roots.add(code)
            for ci,cell in enumerate(row["cells"]):
                for p in cell["paragraphs"]:attach(f"{family}:control:{code}",p,("code","ko","en")[ci])
            continue
        roots=[];categories=[];owner=common
        for p in row["cells"][0]["paragraphs"]:
            text=p["text"].strip()
            if re.fullmatch(r"[0-9][ABCDE]\d{3}(?:\.[a-z0-9]+)*\.?",text):
                code=text[:5]
                if code not in roots:roots.append(code)
                owner=f"{family}:control:{code}"
            elif re.fullmatch(r"[0-9][ABCDE]",text):categories.append(text);owner=common
            attach(owner,p,"code")
        if ri==13:roots.insert(roots.index("0E001"),"0D001")
        actual_roots.update(roots)
        events=sorted((code_position(code),code)for code in roots)
        for ci,language in ((1,"ko"),(2,"en")):
            ps=row["cells"][ci]["paragraphs"]
            supplement=None
            if ri==5:
                # The official 2E003.f note explicitly places its table and
                # technical notes after 2E503.g. Physical order is not legal
                # ownership; keep this complete bilingual supplement together.
                marker="소재공정표증착기술"if language=="ko"else"TABLEDEPOSITIONTECHNIQUES"
                starts=[p for p in ps if alignment_text(p["text"])==marker]
                note="표와기술해설은2E503.g이후"if language=="ko"else"ThetableandTechnicalNoteappearafterentry2E503.g"
                if len(starts)!=1 or not any(note in alignment_text(p["text"])for p in ps):
                    raise ValueError(f"Missing reviewed 2E003.f supplement placement note: {language}")
                supplement=starts[0]["paragraph"]
                supplemental_ranges.append(dict(owner=f"{family}:control:2E003",language=language,
                    first_paragraph=starts[0]["paragraph_id"],last_paragraph=ps[-1]["paragraph_id"],
                    source_anchor=starts[0]["source_anchor"],reason="2E003.f explicitly places its table and technical notes after 2E503.g"))
            titles=[(p,category_letter(p["text"].strip(),language))for p in ps]
            titles=[(p,letter)for p,letter in titles if letter]
            if [letter for _,letter in titles]!=[c[-1]for c in categories]:
                raise ValueError(f"Category paragraph inventory mismatch row {ri} {language}: {[x[1]for x in titles]} vs {categories}")
            sections=[]
            for (p,letter),category in zip(titles,categories):
                start=position(p)
                target=next((code for pos,code in events if pos>=start and code[:2]==category),None)
                # A section header can share the first code's row or follow it
                # while the column title is vertically displaced.
                if target is None:target=next((code for pos,code in events if code[:2]==category and pos[0]==start[0]),None)
                end=code_position(target)if target else None
                sections.append((p["paragraph"],start,end,category))
                category_checks.append(dict(category=category,language=language,source_anchor=p["source_anchor"],
                    paragraph_id=p["paragraph_id"],position=start,first_control=target))
            for p in ps:
                if not p["text"].strip():continue
                pos=position(p);eligible=[code for at,code in events if at[0]<pos[0]or(at[0]==pos[0]and at[1]<=pos[1]+2.5)]
                owner=f"{family}:control:{eligible[-1]}"if eligible else common
                active=next((section for section in reversed(sections)if section[0]<=p["paragraph"]),None)
                if active:
                    is_title=p["paragraph"]==active[0]
                    if is_title or active[2]is None or pos<active[2]:owner=common
                    if p["text"].strip().startswith("0D001"):owner=f"{family}:control:0D001"
                if supplement is not None and p["paragraph"]>=supplement:owner=f"{family}:control:2E003"
                attach(owner,p,language)
    if actual_roots!=expected:raise ValueError(f"XML/PDF root inventory differs: {expected-actual_roots}, {actual_roots-expected}")
    note_ids=[identifier for identifier in groups if ":notes:"in identifier]
    clauses=[]
    for identifier,parts in groups.items():
        code=identifier.rsplit(":",1)[-1]if ":control:"in identifier else""
        text="";offsets={}
        for language,title in (("code","통제번호·원문 메타정보"),("ko","국문 원문"),("en","영문 원문")):
            selected=[p for p,lang in parts if lang==language]
            if not selected:continue
            text+=("\n"if text else"")+"["+title+"]\n"
            for p in selected:
                start=len(text);text+=p["text"]+"\n";offsets[p["paragraph_id"]]=(start,start+len(p["text"]))
        projected=[number for p,_ in parts if p.get("projection")for number in(p["projection"]["page"],p["projection"]["end_page"])]
        if code:projected.append(first_codes[code]["page"])
        page_anchor=f"raw/{pdf_name}.pdf#pages={min(projected)}-{max(projected)}"if projected else""
        anchor=source["relative_path"]+"#Contents/section0.xml&paragraphs="+",".join(p["paragraph_id"]for p,_ in parts)+";"+page_anchor
        clauses.append(clause(identifier,source_id,family,code,f"{code} 통제기준 원문"if code else"공통정의·주석 원문",
            "이중용도품목"if code and family=="dual_use"else"군용물자목록"if code else"공통정의·주석",anchor,text,note_ids if code else()))
        for assignment in assignments:
            if assignment["owner"]==identifier:
                assignment["clause_text_start"],assignment["clause_text_end"]=offsets[assignment["paragraph_id"]]
                assert sha_text(text[assignment["clause_text_start"]:assignment["clause_text_end"]])==assignment["text_sha256"]
    semantic=source["preface"]+[p for row in source["rows"]for cell in row["cells"]for p in cell["paragraphs"]if p["text"].strip()]
    assigned=[a["paragraph_id"]for a in assignments]
    if len(set(assigned))!=len(assigned)or set(assigned)!={p["paragraph_id"]for p in semantic}:raise ValueError("Source paragraphs lost or multiply assigned")
    nested_assignments=[]
    by_assignment={a["paragraph_id"]:a for a in assignments}
    for difference in differences:difference["owner"]=by_assignment[difference["paragraph_id"]]["owner"]
    for p in semantic:
        for table in p["tables"]:
            for row in table["rows"]:
                for cell in row["cells"]:
                    for nested in cell["paragraph_records"]:
                        nested_assignments.append(dict(parent_paragraph=p["paragraph_id"],owner=by_assignment[p["paragraph_id"]]["owner"],
                            source_anchor=p["source_anchor"]+f"&nested_table={table['id']}&nested_row={row['row']}&nested_cell={cell['column']}&nested_paragraph={nested['paragraph']}",
                            text=nested["text"],sha256=nested["sha256"]))
    if len({n["source_anchor"]for n in nested_assignments})!=len(nested_assignments):raise ValueError("Repeated nested paragraph ownership")
    if len(nested_assignments)!=source["xml_paragraph_partition"].get("nested_table_cell",0):raise ValueError("Nested source paragraphs not fully accounted for")
    if family=="dual_use":
        for p in semantic:
            projection=p.get("projection")
            if not projection or projection["method"]!="whole_paragraph_text":continue
            start=(projection["page"],projection["baseline"]);end=(projection["end_page"],projection["end_baseline"])
            for code in sorted(actual_roots,key=code_position):
                at=code_position(code)
                if start<at<=end:
                    crossings.append(dict(code=code,owner=by_assignment[p["paragraph_id"]]["owner"],
                        paragraph_id=p["paragraph_id"],source_anchor=p["source_anchor"],text=p["text"],pdf_position=at))
    write_json(root/"extracted"/(pdf_name.replace("-annex","")+".paragraphs.json"),source)
    normalized={item["code"]for item in clauses if item["code"]}
    boundary_checks=[];boundary_failures=[]
    for code in sorted(expected):
        owner=f"{family}:control:{code}"
        starts={}
        for language in("ko","en"):
            first=next((a for a in assignments if a["owner"]==owner and a["language"]==language),None)
            if first is None:boundary_failures.append(dict(code=code,language=language,reason="Missing source language paragraph"))
            else:starts[language]={key:first[key]for key in("paragraph_id","source_anchor","text_sha256","projection")}
        boundary_checks.append(dict(code=code,owner=owner,language_starts=starts))
    category_failures=[]
    for check in category_checks:
        check["owner"]=by_assignment[check["paragraph_id"]]["owner"]
        if ":notes:"not in check["owner"]and not(check["category"]=="0D"and check["owner"]=="dual_use:control:0D001"):
            category_failures.append(check)
    if boundary_failures or category_failures:raise ValueError(f"Incomplete bilingual control/category ownership: {boundary_failures}, {category_failures}")
    audit=dict(root_code_count=len(expected),code_position_count=len(independent["positions"]),
        missing_from_normalized=sorted(expected-normalized),unexpected_normalized=sorted(normalized-expected),
        checked_boundaries=len(boundary_checks),boundary_checks=boundary_checks,boundary_failures=boundary_failures,
        independent_source_positions=independent["positions"],outside_code_column_candidates=independent["outside_code_column_candidates"],
        checked_category_transitions=len(category_checks),category_assignment_failures=category_failures,category_transition_checks=category_checks,
        paragraph_count=len(semantic),whole_paragraph_assignments=assignments,whole_paragraph_assignment_failures=[],
        nested_paragraph_assignments=nested_assignments,xml_paragraph_partition=source["xml_paragraph_partition"],
        numbered_boundary_crossings=crossings,
        source_expression_differences=differences,
        source_expression_difference_counts=dict(Counter(kind for difference in differences for kind in difference["difference_kinds"])),
        reviewed_supplemental_ranges=supplemental_ranges,
        original_equation_count=sum(len(p["equations"])for p in semantic),
        nested_table_count=sum(len(p["tables"])for p in semantic),
        decorative_shape_labels=[dict(paragraph_id=p["paragraph_id"],source_anchor=p["source_anchor"],drawings=p["drawings"])
            for row in source["rows"]for cell in row["cells"]for p in cell["paragraphs"]if p["drawings"]])
    return clauses,independent["positions"],audit


def advanced_scope(root):
    from lxml import html
    document=html.fromstring((root/"raw/advanced-body.html").read_text(encoding="utf-8"))
    paragraph=document.xpath("//label[@for='Y0004000000']/ancestor::p")[0]
    text=paragraph.text_content().strip()
    anchor="raw/advanced-body.html#Y0004000000"
    item=clause("advanced:article:4","advanced-body","advanced","","제4조(국가첨단전략기술의 범위)","공통정의·주석",anchor,text)
    item["condition"]=dict(type="qualitative",predicate_id="advanced:article:4:production",text=text,
        source_anchor=anchor,subject="지정기술 특화 및 양산 목적 개발 또는 양산 사용",reason="본문 제4조의 지정기술 특화·양산 범위를 모두 확인")
    return item


def body_definitions(root):
    from lxml import html
    output=[]
    for filename,source,families in (("core-body.html","core-body",("core",)),
        ("strategic-current-body.html","strategic-body",("dual_use","military"))):
        document=html.fromstring((root/"raw"/filename).read_text(encoding="utf-8"))
        groups=document.xpath("//label[@for='Y0002000000']/ancestor::div[@class='pgroup']")
        if len(groups)!=1:raise ValueError("Missing official definitions article")
        text="\n".join(paragraph.text_content().strip()for paragraph in groups[0].xpath(".//p")if paragraph.text_content().strip())
        for family in families:
            output.append(clause(family+":article:2",source,family,"","본문 제2조 정의","공통정의·주석",
                "raw/"+filename+"#Y0002000000",text))
    return output


def add_reviewed_conditions(clauses):
    by_id={clause["clause_id"]:clause for clause in clauses}
    # Narrow reviewed cases only; never extract every digit heuristically.
    definitions=[("advanced:item:001","16","nm","le","D램 공정노드","16나노 이하급"),
        ("advanced:item:002","16","nm","le","D램 공정노드","16나노 이하급"),
        ("advanced:item:003","128","단","ge","3D 낸드 적층수","128단 이상"),
        ("advanced:item:004","128","단","ge","3D 낸드 적층수","128단 이상"),
        ("advanced:item:005","0.8","um","le","이미지센서 픽셀 크기","0.8㎛ 이하"),
        ("advanced:item:007","14","nm","le","파운드리 공정노드","14나노급 이하"),
        ("advanced:item:014","80","%","gt","양극소재 니켈함량","80% 초과"),
        ("core:item:001","30","nm","le","D램 공정노드","30나노 이하급"),
        ("core:item:003","64","단","ge","3D 낸드 적층수","64단 이상"),
        ("core:item:008","300","mm","ge","반도체 웨이퍼 직경","300mm 이상"),
        ("core:item:009","1","um","le","이미지센서 픽셀 크기","1㎛ 이하")]
    evidence=[]
    for identifier,threshold,unit,operator,subject,literal in definitions:
        item=by_id[identifier]
        if literal not in item["text"]:raise ValueError(f"Reviewed literal absent: {identifier}, {literal}")
        numeric=dict(type="numeric",predicate_id=identifier+":numeric",text=literal,
            source_anchor=item["source_anchor"],subject=subject,operator=operator,threshold=threshold,unit=unit)
        # Preserve the remaining technology activity/scope and exceptions instead
        # of pretending that a matching number alone proves designation.
        children=[numeric,dict(type="qualitative",predicate_id=identifier+":activity",text=item["text"],
            source_anchor=item["source_anchor"],subject="해당 기술종류와 설계·공정·소자·조립·검사 등 원문 기술활동",
            reason="수치 외 기술범위 전부를 원문과 입력 근거로 대조")]
        if item["family"]=="advanced":
            children.append(dict(type="qualitative",predicate_id=identifier+":production",text=by_id["advanced:article:4"]["text"],
                source_anchor=by_id["advanced:article:4"]["source_anchor"],subject="지정기술 특화 및 양산 목적 개발 또는 양산 사용",
                reason="단순 연구성능 수치만으로 제4조의 특화·양산 범위를 충족했다고 간주하지 않음"))
        item["condition"]=dict(type="all",children=children)
        evidence.append(dict(clause_id=identifier,source_anchor=item["source_anchor"],literal=literal,
            operator=operator,threshold=threshold,unit=unit))
    # Real branched thresholds and exclusions, explicitly transcribed from the
    # fixed source. These branches are not created by a generic digit extractor.
    for identifier in ("advanced:item:010","advanced:item:012","advanced:item:013"):
        item=by_id[identifier];anchor=item["source_anchor"];prefix=identifier+":"
        def numeric(key,literal,operator,threshold,unit,subject):
            if literal not in item["text"]:raise ValueError(f"Missing literal {identifier}: {literal}")
            evidence.append(dict(clause_id=identifier,source_anchor=anchor,literal=literal,
                operator=operator,threshold=threshold,unit=unit))
            return dict(type="numeric",predicate_id=prefix+key,text=literal,source_anchor=anchor,
                subject=subject,operator=operator,threshold=threshold,unit=unit)
        def qualitative(key,text,subject):
            return dict(type="qualitative",predicate_id=prefix+key,text=text,source_anchor=anchor,
                subject=subject,reason="원문에 명시된 기술 범위·형태·예외를 입력의 직접 근거와 대조")
        activity=qualitative("activity",item["text"],"원문에 명시된 기술의 종류 및 설계·제조·공정·구동/평가 활동")
        scope=dict(type="qualitative",predicate_id=prefix+"production",text=by_id["advanced:article:4"]["text"],
            source_anchor=by_id["advanced:article:4"]["source_anchor"],subject="지정기술 특화 및 양산 목적 개발 또는 양산 사용",reason="본문 제4조의 특화·양산 범위 조건")
        if identifier.endswith("010"):
            nodes=[numeric("linewidth","40nm 이하","le","40","nm","QD 반치폭"),
                numeric("colour","90% 이상","ge","90","%","REC2020 기준 색재현율"),
                dict(type="not",child=qualitative("excluded-lcd","LCD와 모듈기술은 제외","LCD 기술 여부")),
                dict(type="not",child=qualitative("excluded-module","LCD와 모듈기술은 제외","모듈기술 여부"))]
        elif identifier.endswith("012"):
            nodes=[numeric("size","1㎛ 이하","le","1","um","나노 LED 크기"),
                dict(type="not",child=qualitative("excluded-module","모듈기술은 제외","모듈기술 여부"))]
        else:
            branches=[]
            for key,kind,energy,literal in (("pouch","파우치형","280","280Wh/kg 이상인 파우치형"),
                ("prismatic","각형","252","252Wh/kg 이상인 각형")):
                branches.append(dict(type="all",children=[qualitative(key+"-type",kind,"배터리 형상: "+kind),
                    numeric(key+"-energy",literal,"ge",energy,"Wh/kg",kind+" 배터리 에너지밀도")]))
            for key,operator,energy,literal in (("small-cylinder","le","280","280Wh/kg"),("large-cylinder","gt","260","260Wh/kg")):
                branches.append(dict(type="all",children=[qualitative(key+"-type","원통형 배터리","배터리 형상: 원통형"),
                    numeric(key+"-diameter","21mm","le" if operator=="le" else "gt","21","mm","원통형 배터리 지름"),
                    numeric(key+"-energy",literal,"ge",energy,"Wh/kg","원통형 배터리 에너지밀도")]))
            nodes=[dict(type="any",children=branches)]
        item["condition"]=dict(type="all",children=[activity,scope,*nodes])
    # ML22's positive technology scope remains unsupported, but all three
    # explicit exemption branches are visible. A proven exception cannot produce
    # a satisfied technology-control result merely because "military" appears.
    item=by_id["military:control:ML22"]
    original=item["condition"]
    exclusions=[]
    for key,literal,subject in (("service","최소한의", "비통제품목/수출허가 품목의 설치·운용·유지·보수에 필요한 최소한의 기술"),
        ("public","일반에 공개된 정보","일반공개 정보 또는 기초과학연구 또는 특허출원 최소 필요정보인 기술"),
        ("civil","자력 유도","민간 수송차량 연속 추진 자력유도 기술")):
        if literal not in item["text"]:raise ValueError("Missing ML22 exemption")
        exclusions.append(dict(type="qualitative",predicate_id="military:control:ML22:exception:"+key,
            text=item["text"],source_anchor="raw/military-annex.pdf#page=41&control=ML22&note=2",subject=subject,
            reason="ML22 주2의 예외 전체 한정조건을 직접 근거로 확인"))
    item["condition"]=dict(type="all",children=[original,dict(type="not",child=dict(type="any",children=exclusions))])
    # Curated unambiguous non-numeric technology/activity designations. Digits
    # in names such as 5G are identifiers, not delegated threshold arithmetic.
    qualitative_ids=("advanced:item:006","advanced:item:008",*(f"core:item:{i:03d}"for i in
        (2,4,6,7,10,11,13,19,20,21,22,25,26,27,29,36,38,39,40,43,44,45,46,47,48,49,50,
         51,52,53,54,55,56,57,58,59,64,67,70,71,72,73,74,75,76,77)))
    for identifier in qualitative_ids:
        item=by_id[identifier]
        leaf=dict(type="qualitative",predicate_id=identifier+":scope",text=item["text"],source_anchor=item["source_anchor"],
            subject="원문에 지정된 기술종류·용도·활동 및 열거된 한정범위",reason="수치 문턱값 없는 지정 범위를 원문 및 입력의 직접 인용 근거와 대조")
        children=[leaf]
        if item["family"]=="advanced":
            children.append(dict(type="qualitative",predicate_id=identifier+":production",text=by_id["advanced:article:4"]["text"],
                source_anchor=by_id["advanced:article:4"]["source_anchor"],subject="지정기술 특화 및 양산 목적 개발 또는 양산 사용",reason="본문 제4조의 특화·양산 범위 조건"))
        if identifier=="core:item:013":
            children.append(dict(type="not",child=dict(type="qualitative",predicate_id=identifier+":module-exception",
                text="모듈조립 공정 기술은 제외",source_anchor=item["source_anchor"],subject="모듈조립 공정 기술 여부",reason="원문의 모듈조립 공정 제외 조건")))
        item["condition"]=dict(type="all",children=children) if len(children)>1 else leaf
    extra_numeric={
        "advanced:item:016":[("1만리터 이상","ge","10000","L","다회용 바이오리액터 세포배양 규모")],
        "advanced:item:017":[("100","ge","100","dose/lot","자가 및 동종 오가노이드 재생치료제 배양 규모"),
            ("80% 이상","ge","80","%","장기별 오가노이드 목적 세포 구성률"),("80% 이상","ge","80","%","장기별 오가노이드 생존율")],
        "advanced:item:018":[("3.3m/s 이상","ge","3.3","m/s","휴머노이드 로봇 최고 이동속도"),("20kg 이상","ge","20","kg","전신 조작을 통해 운반할 수 있는 중량")],
        "advanced:item:019":[("15,000lbf급 이상","ge","15000","lbf","유·무인기용 첨단 항공엔진 추력 등급")],
        "core:item:005":[("30나노급 이하","le","30","nm","파운드리 공정노드")],
        "core:item:015":[("80% 초과","gt","80","%","양극소재 Ni 함량")],
        "core:item:016":[("500kV급 이상","ge","500","kV","전력케이블 시스템 전압 등급")],
        "core:item:018":[("21uF/mm3이상","ge","21","uF/mm3","MLCC 용량밀도")],
        "core:item:024":[("양산 후 2년 이내","le","2","년","양산 후 경과기간")],
        "core:item:028":[("상용화 3년 이내","le","3","년","상용화 후 경과기간")],
        "core:item:031":[("10wt.% Mn 이상","ge","10","wt.%","특수강 Mn 함량")],
        "core:item:032":[("4wt.%이하","le","4","wt.%","철강판재 합금원소 총량")],
        "core:item:033":[("100톤이상급","ge","100","톤","대형 주·단강제품 단품 질량 등급")],
        "core:item:034":[("3wt.% Ni이하","le","3","wt.%","스테인리스강 Ni 함량"),("0.4wt.% N이상","ge","0.4","wt.%","스테인리스강 N 함량")],
        "core:item:037":[("600MPa 이상","ge","600","MPa","강판 인장강도")],
        "core:item:041":[("3천톤 이상","ge","3000","톤","선박·해양구조물 규모")],
        "core:item:060":[("500Km기준","eq","500","km","해상도 기준 위성 고도"),("50cm이하급","le","50","cm","고도 500km 기준 광학위성 해상도")],
        "core:item:061":[("1m이상","ge","1","m","위성탑재 전자광학 카메라 구경")],
        "core:item:062":[("1m이하","le","1","m","SAR 탑재체 해상도")],
        "core:item:063":[("1만 리터급 이상","ge","10000","L","동물세포 배양·정제 공정 규모")],
        "core:item:066":[("3종 이상","ge","3","종","감염질환용 면역 분석 종류수"),("95% 이상","ge","95","%","민감도"),("95% 이상","ge","95","%","특이도")],
        "core:item:068":[("5축","eq","5","축","머시닝센터 축수")],
        "core:item:069":[("20톤급 이상","ge","20","톤","중대형 굴착기 등급")],
        "core:item:078":[("1.0A/cm2 이상","ge","1.0","A/cm2","연료전지 전류밀도"),("4시간 이상","ge","4","시간","해당 전류밀도에서 연속운전 시간"),("10kW급 이상","ge","10","kW","건설·산업기계용 연료전지 출력")],
        "core:item:079":[("35% 이상","ge","35","%","고정형 연료전지 발전효율"),("4만 시간 이상","ge","40000","시간","고정형 연료전지 내구성 시간")],
    }
    for identifier,values in extra_numeric.items():
        item=by_id[identifier];children=[]
        for number,(literal,operator,threshold,unit,subject) in enumerate(values,1):
            if literal not in item["text"]:raise ValueError(f"Missing reviewed numeric literal {identifier}: {literal}")
            children.append(dict(type="numeric",predicate_id=identifier+f":value:{number}",text=literal,source_anchor=item["source_anchor"],
                subject=subject,operator=operator,threshold=threshold,unit=unit))
            evidence.append(dict(clause_id=identifier,source_anchor=item["source_anchor"],literal=literal,operator=operator,threshold=threshold,unit=unit))
        children.append(dict(type="qualitative",predicate_id=identifier+":activity",text=item["text"],source_anchor=item["source_anchor"],
            subject="원문 기술종류·활동·용도 및 나머지 한정조건",reason="별도 수치 leaf의 산술판정과 독립적으로 해당 기술 범위와 직접 근거를 확인"))
        if item["family"]=="advanced":
            children.append(dict(type="qualitative",predicate_id=identifier+":production",text=by_id["advanced:article:4"]["text"],
                source_anchor=by_id["advanced:article:4"]["source_anchor"],subject="지정기술 특화 및 양산 목적 개발 또는 양산 사용",reason="본문 제4조의 특화·양산 범위 조건"))
        item["condition"]=dict(type="all",children=children)
    # A taxonomic list of live plant-pathogen cultures has no performance
    # thresholds; enumeration numbers are identifiers, not numeric conditions.
    item=by_id["dual_use:control:1C354"]
    item["condition"]=dict(type="qualitative",predicate_id=item["clause_id"]+":identity-and-form",text=item["text"],
        source_anchor=item["source_anchor"],subject="열거된 식물병원체의 정확한 종 및 살아있는 분리배양체/의도 접종·감염된 살아있는 물질 형태",
        reason="단순 식물 연구 키워드가 아니라 열거된 병원체 정체와 원문 생물학적 형태를 모두 직접 근거로 확인")
    def q(item,key,subject):
        return dict(type="qualitative",predicate_id=item["clause_id"]+":"+key,text=item["text"],source_anchor=item["source_anchor"],
            subject=subject,reason="원문에 명시된 해당 범위만 입력의 직접 근거로 대조")
    def n(item,key,literal,operator,threshold,unit,subject):
        if literal not in item["text"]:raise ValueError(f"Missing export literal: {item['code']}: {literal}")
        evidence.append(dict(clause_id=item["clause_id"],source_anchor=item["source_anchor"],literal=literal,operator=operator,threshold=threshold,unit=unit))
        return dict(type="numeric",predicate_id=item["clause_id"]+":"+key,text=literal,source_anchor=item["source_anchor"],
            subject=subject,operator=operator,threshold=threshold,unit=unit)
    item=by_id["dual_use:control:1A003"]
    item["condition"]=dict(type="all",children=[q(item,"form","비가용성 방향족 폴리이미드 제조품이며 필름·판·테입·리본 형태"),
        dict(type="any",children=[n(item,"thickness","0.254 mm 를 초과","gt","0.254","mm","제조품 두께"),
            q(item,"coated","탄소·흑연·금속·자성물질로 코팅 또는 적층된 제조품")]),
        dict(type="not",child=dict(type="all",children=[q(item,"copper","구리로 코팅 또는 적층된 제조품"),q(item,"pcb","전자인쇄회로 기판 생산을 위해 설계된 제품")]))])
    item["qualifier_refs"].append("dual_use:control:1C008")
    item=by_id["dual_use:control:1A006"]
    equipment=dict(type="all",children=[q(item,"dedicated","급조폭발장치 처리를 위해 전용 설계 또는 개조된 장비 자체"),
        dict(type="any",children=[q(item,"remote","장비 자체가 원격조종장비"),q(item,"disruptor","장비 자체가 액체·고체·무른 발사체로 폭발물 작동을 막기 위해 전용설계된 디스럽터")]),
        dict(type="not",child=q(item,"accompanies","조작자가 수반되는 장비"))])
    components=dict(type="all",children=[q(item,"component-dedicated","상기 급조폭발장치 처리 장비를 위해 전용 설계된 구성품 또는 부속품(구성품 자체가 원격조종장비나 디스럽터일 필요는 없음)"),
        unsupported(item["clause_id"]+":components",item["text"],item["source_anchor"],
            "전용 구성품·부속품의 상위 장비가 1A006 양의 장비범위에 해당하고 동반 조작자 예외를 적용받지 않는지 설계 추적 근거 추가 대조 필요")])
    item["condition"]=dict(type="any",children=[equipment,components])
    item["qualifier_refs"].append("military:control:ML4")
    item=by_id["dual_use:control:3A102"]
    item["condition"]=dict(type="all",children=[q(item,"thermal","일회용 배터리로 비전도 고체 무기염 전해질과 점화시 전해질을 녹여 작동하는 열분해 소재를 사용하는 열전지"),
        q(item,"missile-use","완성체 로켓시스템 또는 무인항공기시스템용으로 설계 또는 개조됨"),
        n(item,"range","300km초과","gt","300","km","설계·개조 대상 완성체 로켓/무인항공기시스템 사거리 능력")])
    item=by_id["military:control:ML14"]
    item["condition"]=dict(type="all",children=[dict(type="any",children=[q(item,"military-training","주3에 정의된 군사훈련용 특수장비 또는 군 시나리오 시뮬레이션용 특수장비(주1의 군용 전용 영상발생·상호작용 모의환경 포함)"),
        dict(type="all",children=[q(item,"weapon-training","ML1 또는 ML2 화기·무기 사용훈련을 위해 전용 설계된 시뮬레이터"),
            unsupported(item["clause_id"]+":weapons",item["text"],item["source_anchor"],"ML1·ML2의 대상 화기·무기 통제범위 추가 대조 필요")]),
        dict(type="all",children=[q(item,"components","상기 특수장비·시뮬레이터용으로 전용 설계된 구성품·부속품"),
            unsupported(item["clause_id"]+":components",item["text"],item["source_anchor"],"전용 구성품의 상위 장비가 ML14 양의 범위에 해당하는지 추가 대조 필요")])]),
        dict(type="not",child=q(item,"hunting-sport","사냥 또는 스포츠 무기의 사용 훈련을 목적으로 전용 설계된 장치"))])
    item["qualifier_refs"].extend(("military:control:ML1","military:control:ML2"))
    return evidence


def condition_kinds(node):
    kinds=[node["type"]]
    for child in node.get("children",[]):kinds.extend(condition_kinds(child))
    if "child" in node:kinds.extend(condition_kinds(node["child"]))
    return kinds


def sources(root):
    entries=[("advanced-annex",["advanced"],"국가첨단전략기술 지정 등에 관한 고시 별표","산업통상자원부고시 제2025-71호","2025-05-18","https://www.law.go.kr/LSW/flDownload.do?flSeq=151737083&bylClsCd=200201","raw/advanced-annex.pdf"),
        ("advanced-body",["advanced"],"국가첨단전략기술 지정 등에 관한 고시 본문 제4조","산업통상자원부고시 제2025-71호","2025-05-18","https://www.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000258826","raw/advanced-body.html"),
        ("core-annex",["core"],"국가핵심기술 지정 등에 관한 고시 별표","산업통상부고시 제2025-2호","2025-10-02","https://www.law.go.kr/LSW/flDownload.do?flSeq=160938377&bylClsCd=200201","raw/core-annex.pdf"),
        ("core-body",["core"],"국가핵심기술 지정 등에 관한 고시 정의","산업통상부고시 제2025-2호","2025-10-02","https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000272798","raw/core-body.html"),
        ("strategic-body",["dual_use","military"],"전략물자수출입고시 본문 정의","산업통상부고시 제2026-101호","2026-09-01","https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000284150","raw/strategic-current-body.html"),
        ("dual-use-annex",["dual_use"],"전략물자수출입고시 별표 2 이중용도품목","산업통상부고시 제2026-101호","2026-09-01","https://www.law.go.kr/LSW/flDownload.do?flSeq=169180601&bylClsCd=200201","raw/dual-use-annex.pdf"),
        ("military-annex",["military"],"전략물자수출입고시 별표 3 군용물자목록","산업통상부고시 제2026-101호","2026-09-01","https://www.law.go.kr/LSW/flDownload.do?flSeq=169181245&bylClsCd=200201","raw/military-annex.pdf"),
        ("dual-use-hwpx",["dual_use"],"전략물자수출입고시 별표 2 확정 원본 문단·표·수식","산업통상부고시 제2026-101호","2026-09-01","https://www.law.go.kr/LSW/flDownload.do?flSeq=169179371&bylClsCd=200201","raw/dual-use-annex.hwpx"),
        ("military-hwpx",["military"],"전략물자수출입고시 별표 3 확정 원본 문단·표·수식","산업통상부고시 제2026-101호","2026-09-01","https://www.law.go.kr/LSW/flDownload.do?flSeq=169181147&bylClsCd=200201","raw/military-annex.hwpx")]
    return [dict(source_id=identifier,families=families,title=title,notice_number=number,
        announcement_version="제38차 개정" if identifier in ("dual-use-annex","military-annex","dual-use-hwpx","military-hwpx") else number,
        effective_date=effective,official_url=url,retrieved_at=STRUCTURED_RETRIEVED.get(identifier,RETRIEVED),relative_path=path,sha256=sha(root/path),
        review_status="reviewed",coverage="full",review_note="원본 전체·페이지·지정항목/통제번호·좌표·주석 보존 구조 검수. 미해석 조건은 unsupported이며 자동 충족 판정 금지. 자세한 한계는 review/review.json 참조.")
        for identifier,families,title,number,effective,url,path in entries]


def build(root=ROOT, extract=True):
    root=Path(root)
    pages=extract_pages(root) if extract else {name:json.loads((root/"extracted"/(name+".pages.json")).read_text(encoding="utf-8"))for name in PDF_NAMES}
    clauses,table_positions=table_clauses(root)
    clauses.append(advanced_scope(root))
    code_positions={};control_audits={}
    for name,family in (("dual-use","dual_use"),("military","military")):
        independent=independent_pdf_inventory(root,family)
        items,positions,audit=export_clauses(pages[name],family,independent,root)
        clauses.extend(items);code_positions[family]=positions;control_audits[family]=audit
    body=(root/"raw/strategic-current-body.html").read_text(encoding="utf-8")
    pairs=[]
    for name,identifier,original,pdf in (("dual-use","dual-use-hwpx","169179371","169180601"),("military","military-hwpx","169181147","169181245")):
        if original not in body or pdf not in body:raise ValueError("Original/PDF attachments must belong to the captured final notice")
        pairs.append(dict(source_id=identifier,original_relative_path=f"raw/{name}-annex.hwpx",
            original_url=f"https://www.law.go.kr/LSW/flDownload.do?flSeq={original}&bylClsCd=200201",
            original_sha256=sha(root/f"raw/{name}-annex.hwpx"),retrieved_at=STRUCTURED_RETRIEVED[identifier],
            paired_pdf=f"raw/{name}-annex.pdf",paired_pdf_sha256=sha(root/f"raw/{name}-annex.pdf"),
            paired_pdf_url=f"https://www.law.go.kr/LSW/flDownload.do?flSeq={pdf}&bylClsCd=200201",
            same_final_notice_links_present=True))
    write_json(root/"review/structured-source-verification.json",dict(notice_number="산업통상부고시 제2026-101호",
        effective_date="2026-09-01",captured_body="raw/strategic-current-body.html",captured_body_sha256=sha(root/"raw/strategic-current-body.html"),pairs=pairs,
        method="원본 HWPX 표·셀·문단 전체 보존. PDF는 독립 통제번호·원문 위치 대조에 사용. 수식 스크립트·중첩표·표시 차이를 별도 기록.",
        alignment_only_normalizations=["NFKC","공백","인용부호 모양","줄끝 하이픈","Symbol U+F063 위치 대조"],
        warning="대조용 문자 정규화는 원문 저장이나 분류 수치 판정에 적용하지 않음"))
    definitions=body_definitions(root)
    for item in clauses:
        if item["field"]!="공통정의·주석" and item["family"]in("core","dual_use","military"):
            item["qualifier_refs"].append(item["family"]+":article:2")
    clauses.extend(definitions)
    evidence=add_reviewed_conditions(clauses)
    write_json(root/"normalized/clauses.json",clauses)
    write_json(root/"review/source-positions.json",dict(table_positions=table_positions,control_positions=code_positions))
    write_json(root/"review/numeric-evidence.json",evidence)
    write_json(root/"review/control-boundaries.json",control_audits)
    report=dict(review_kind="source-coverage-and-conservative-normalization",source_page_counts={name:len(value)for name,value in pages.items()},
        family_clause_counts=dict(Counter(item["family"]for item in clauses)),
        designated_technology_counts={"advanced":19,"core":79},control_root_counts={family:audit["root_code_count"]for family,audit in control_audits.items()},
        independent_control_audit={family:{key:audit[key]for key in("root_code_count","code_position_count","missing_from_normalized","unexpected_normalized","checked_boundaries","boundary_failures","checked_category_transitions","category_assignment_failures")}for family,audit in control_audits.items()},
        designated_field_counts={family:dict(Counter(item["field"]for item in clauses if item["family"]==family and item["field"]!="공통정의·주석"))for family in("advanced","core")},
        code_position_counts={family:len(value)for family,value in code_positions.items()},
        structured_source_counts={family:{key:audit[key]for key in("paragraph_count","original_equation_count","nested_table_count","xml_paragraph_partition")}for family,audit in control_audits.items()},
        source_expression_difference_counts={family:audit["source_expression_difference_counts"]for family,audit in control_audits.items()},
        reviewed_supplemental_ranges={family:audit["reviewed_supplemental_ranges"]for family,audit in control_audits.items()},
        preserved_notes="일반/기술/소프트웨어 해설, 핵기술 해설, 민감/초민감 부록 및 양 별표 용어집 전체. 원문 로컬 주·예외는 해당 통제번호 본문에 포함.",
        limitations=["원문 전체 범위 보존은 법률 전문가 판정 또는 모든 조건의 완전한 기계 해석을 뜻하지 않음.",
            "복잡한 수치·정성·예외·타 조항 참조 조건은 unsupported로 보존하며 정보 부족으로 취급해야 함.",
            "별표 2·3 본문은 확정 원본 HWPX의 완결 문단·셀·수식 스크립트를 보존한다. PDF는 독립 번호와 위치 대조에 사용한다. 수식·표·기호 등 표시 차이는 별도 검수기록에 남긴다.",
            "2E003.f의 명시적 위치 안내에 따라 2E503.g 뒤에 배치된 코팅공정 표·주·기술해설은 2E003 소속으로 보존한다.",
            "YESTRADE 38차 공지의 '전략물자수출입고시_최종.hwpx'는 실제로 제2026-496호 행정예고 초안이어서 실행 기준에서 제외. 법제처 제2026-101호 통합 별표로 대체.",
            "상황허가·국가별 제재·수출허가 최종 판단은 범위에서 제외."],
        selected_checks=["첨단19개/핵심79개를 표의 분야별 건수 및 원본 행 좌표와 대조",
            "이중용도 부록의 축약 반복코드를 본표의 독립 통제 항목으로 중복 추가하지 않음",
            "군용 ML1~ML22와 42~48쪽 용어집 구분; ML22 주2의 공개정보/기초과학연구 예외 원문 보존",
            "첨단 제4조의 각 기술 특화 및 양산 목적 개발/사용 범위 조건 보존"],
        numeric_examples=evidence)
    decisions=[item for item in clauses if item["field"]!="공통정의·주석"]
    report["condition_node_counts"]=dict(Counter(kind for item in clauses for kind in condition_kinds(item["condition"])))
    report["support_counts"]={"designation_or_control_items":len(decisions),
        "complete_numeric_and_qualitative_ast":sum("numeric"in condition_kinds(item["condition"]) and "unsupported"not in condition_kinds(item["condition"])for item in decisions),
        "complete_qualitative_ast":sum("numeric"not in condition_kinds(item["condition"]) and "unsupported"not in condition_kinds(item["condition"])for item in decisions),
        "partially_structured_with_unsupported":sum("unsupported"in condition_kinds(item["condition"]) and len(condition_kinds(item["condition"]))>1 for item in decisions),
        "uninterpreted_original":sum(item["condition"]["type"]=="unsupported" for item in decisions)}
    report["excluded_draft"]={"official_url":"https://www.yestrade.go.kr/api/user/boards/69/posts/23257/files/3167282",
        "sha256":"7ac7c95621584be46c02b422e8f8c1ec481bf76382754d9ce24fda13019538bb",
        "actual_content":"산업통상부 공고 제2026-496호(2026-07-13), 일부개정(안) 행정예고",
        "reason":"첨부 파일명 최종과 달리 확정 고시가 아니므로 실행 기준본에서 제외"}
    write_json(root/"review/review.json",report)
    # Only intentionally selected resources are part of the executable catalogue.
    paths=["raw/advanced-annex.pdf","raw/advanced-body.html","raw/core-annex.pdf","raw/core-body.html",
        "raw/strategic-current-page.html","raw/strategic-current-body.html","raw/dual-use-annex.pdf","raw/military-annex.pdf",
        "raw/dual-use-annex.hwpx","raw/military-annex.hwpx","extracted/dual-use.paragraphs.json","extracted/military.paragraphs.json",
        "review/structured-source-verification.json",
        "normalized/clauses.json","review/source-positions.json","review/numeric-evidence.json","review/control-boundaries.json","review/review.json","README.md",".gitattributes"]
    paths += [f"extracted/{name}.pages.json" for name in PDF_NAMES]
    manifest=dict(catalogue_schema_version=1,catalogue_id="kr-notices-2026-10-21-v3",sources=sources(root),
        files=[dict(relative_path=path,sha256=sha(root/path))for path in sorted(paths)],
        clause_inventory=[dict(clause_id=item["clause_id"],family=item["family"],sha256=canonical_hash(item))for item in clauses])
    write_json(root/"manifest.json",manifest)
    catalogue=load_catalogue(root)
    print(json.dumps(dict(fingerprint=catalogue.fingerprint,clauses=len(clauses),**report),ensure_ascii=False,indent=2))
    return catalogue


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--reuse-extracted",action="store_true",help="Skip PDF line extraction; table geometry is still rebuilt")
    arguments=parser.parse_args()
    build(arguments.root,not arguments.reuse_extracted)
