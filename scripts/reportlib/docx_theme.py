# -*- coding: utf-8 -*-
"""python-docx theme helpers: fonts, tables, hyperlinks, images."""
from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsmap
from docx.shared import Inches, Pt, RGBColor, Cm, Emu, Twips
from docx.enum.style import WD_STYLE_TYPE
from docx.opc.constants import RELATIONSHIP_TYPE

NAVY = RGBColor(0x1B, 0x3A, 0x4B)
TEAL = RGBColor(0x2A, 0x9D, 0x8F)
CORAL = RGBColor(0xC0, 0x39, 0x2B)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x5C, 0x6B, 0x73)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_BG = "1B3A4B"
ALT_BG = "F4F1EA"
ACCENT_BG = "E8F6F3"
WARN_BG = "FDEDEC"

EAST_ASIA = "Noto Sans CJK SC"
LATIN = "Calibri"


def set_run_font(run, size=11, bold=False, color=INK, italic=False, name=LATIN):
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), EAST_ASIA)
    rfonts.set(qn("w:cs"), name)


def _style_font(style, size, bold, color, east=EAST_ASIA):
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = color
    style.font.name = LATIN
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), LATIN)
    rfonts.set(qn("w:hAnsi"), LATIN)
    rfonts.set(qn("w:eastAsia"), east)


def init_document():
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(1.6)
    section.right_margin = Cm(1.6)
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.6)
    section.header_distance = Cm(0.8)
    section.footer_distance = Cm(0.8)

    normal = doc.styles["Normal"]
    _style_font(normal, 11, False, INK)
    pf = normal.paragraph_format
    pf.space_after = Pt(6)
    pf.space_before = Pt(0)
    pf.line_spacing = 1.15

    h1 = doc.styles["Heading 1"]
    _style_font(h1, 18, True, NAVY)
    h1.paragraph_format.space_before = Pt(16)
    h1.paragraph_format.space_after = Pt(8)
    h1.paragraph_format.keep_with_next = True

    h2 = doc.styles["Heading 2"]
    _style_font(h2, 14, True, TEAL)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(6)
    h2.paragraph_format.keep_with_next = True

    h3 = doc.styles["Heading 3"]
    _style_font(h3, 12, True, NAVY)
    h3.paragraph_format.space_before = Pt(10)
    h3.paragraph_format.space_after = Pt(4)
    h3.paragraph_format.keep_with_next = True

    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    return doc


def add_header_footer(doc, title: str, subtitle: str):
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.clear()
    r = hp.add_run(title)
    set_run_font(r, 9, True, NAVY)
    r2 = hp.add_run("  ·  " + subtitle)
    set_run_font(r2, 9, False, MUTED)
    hp.paragraph_format.space_after = Pt(2)

    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.clear()
    fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = fp.add_run("数据未标明处均来自本日 Markdown 报告或 Creative Center CSV。热度混合口径，禁止跨指标横比。  ")
    set_run_font(r, 8, False, MUTED)
    # PAGE field
    run = fp.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "begin")
    run._r.append(fld)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    run._r.append(instr)
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld2)
    set_run_font(run, 8, False, MUTED)


def p(doc, text="", size=11, bold=False, color=INK, space_after=6, space_before=0, italic=False):
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.space_before = Pt(space_before)
    if text:
        run = para.add_run(text)
        set_run_font(run, size, bold, color, italic)
    return para


def add_runs(para, parts):
    """parts: list of (text, bold, color, size) or str."""
    for part in parts:
        if isinstance(part, str):
            run = para.add_run(part)
            set_run_font(run, 11, False, INK)
        else:
            text, bold, color, size = part
            run = para.add_run(text)
            set_run_font(run, size, bold, color)


def add_hyperlink(paragraph, text, url, size=10):
    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1B6CA8")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), LATIN)
    rFonts.set(qn("w:hAnsi"), LATIN)
    rFonts.set(qn("w:eastAsia"), EAST_ASIA)
    rPr.append(rFonts)
    rPr.append(color)
    rPr.append(u)
    rPr.append(sz)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


_bookmark_seq = 0


def add_bookmark(paragraph, name: str):
    """Wrap a paragraph with a Word bookmark (for internal hyperlinks)."""
    global _bookmark_seq
    _bookmark_seq += 1
    bid = str(_bookmark_seq)
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), bid)
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), bid)
    p_el = paragraph._p
    pPr = p_el.find(qn("w:pPr"))
    if pPr is not None:
        pPr.addnext(start)
    else:
        p_el.insert(0, start)
    p_el.append(end)
    return name


def add_internal_hyperlink(paragraph, text, anchor, size=10):
    """Jump to a bookmark inside the same document."""
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), anchor)
    hyperlink.set(qn("w:history"), "1")
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1B6CA8")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), LATIN)
    rFonts.set(qn("w:hAnsi"), LATIN)
    rFonts.set(qn("w:eastAsia"), EAST_ASIA)
    rPr.append(rFonts)
    rPr.append(color)
    rPr.append(u)
    rPr.append(sz)
    new_run.append(rPr)
    te = OxmlElement("w:t")
    te.set(qn("xml:space"), "preserve")
    te.text = text
    new_run.append(te)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def shade_cell(cell, hex_color: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:shd")):
        tcPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    vAlign = tcPr.find(qn("w:vAlign"))
    if vAlign is not None:
        vAlign.addprevious(shd)
    else:
        tcPr.append(shd)


def set_cell_border(cell, **kwargs):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.find(qn("w:tcBorders"))
    if tcBorders is None:
        tcBorders = OxmlElement("w:tcBorders")
        tcPr.append(tcBorders)
    for edge in ("top", "left", "bottom", "right"):
        if edge in kwargs:
            element = tcBorders.find(qn(f"w:{edge}"))
            if element is None:
                element = OxmlElement(f"w:{edge}")
                tcBorders.append(element)
            element.set(qn("w:val"), kwargs[edge].get("val", "single"))
            element.set(qn("w:sz"), kwargs[edge].get("sz", "4"))
            element.set(qn("w:color"), kwargs[edge].get("color", "D0D5D8"))
            element.set(qn("w:space"), "0")


def set_cell_text(cell, text, bold=False, size=10, color=INK, fill=None, align="left"):
    if fill:
        shade_cell(cell, fill)
    cell.text = ""
    para = cell.paragraphs[0]
    para.paragraph_format.space_before = Pt(3)
    para.paragraph_format.space_after = Pt(3)
    if align == "center":
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(text)
    set_run_font(run, size, bold, color)
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    if tcPr.find(qn("w:vAlign")) is None:
        vAlign = OxmlElement("w:vAlign")
        vAlign.set(qn("w:val"), "center")
        tcPr.append(vAlign)
    return para


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for i, h in enumerate(headers):
        set_cell_text(table.cell(0, i), h, bold=True, size=9, color=WHITE, fill=HEADER_BG, align="center")
    for r_i, row in enumerate(rows):
        fill = ALT_BG if r_i % 2 == 1 else "FFFFFF"
        for c_i, val in enumerate(row):
            set_cell_text(table.cell(r_i + 1, c_i), str(val), bold=False, size=9, color=INK, fill=fill)
    if col_widths:
        for row in table.rows:
            for idx, w in enumerate(col_widths):
                row.cells[idx].width = Cm(w)
    return table


def add_picture_fit(doc, path, width_cm=17.6):
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(10)
    run = para.add_run()
    run.add_picture(path, width=Cm(width_cm))
    return para


def prevent_row_split(table):
    for row in table.rows:
        tr = row._tr
        trPr = tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        trPr.append(cant)
