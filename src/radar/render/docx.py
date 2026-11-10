"""Write a Document as a Word file (A4, CJK fonts, internal links, shaded tables)."""
from __future__ import annotations

from pathlib import Path

from docx import Document as new_docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .blocks import Bullets, Card, Code, Document, Heading, Image, Inline, Link, Para, Ref, Table

NAVY = RGBColor(0x1B, 0x3A, 0x4B)
TEAL = RGBColor(0x2A, 0x9D, 0x8F)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x5C, 0x6B, 0x73)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_BG = "1B3A4B"
ALT_BG = "F4F1EA"
TONE_BG = {"make": "D5F5E3", "watch": "FCF3CF", "skip": "FADBD8"}
LINK_COLOR = "1B6CA8"
EAST_ASIA = "Noto Sans CJK SC"
LATIN = "Calibri"


def _fonts(rpr) -> None:
    rfonts = rpr.get_or_add_rFonts()
    for attr, name in (("w:ascii", LATIN), ("w:hAnsi", LATIN), ("w:eastAsia", EAST_ASIA), ("w:cs", LATIN)):
        rfonts.set(qn(attr), name)


def _run(para, text: str, size=11, bold=False, color=INK, italic=False):
    r = para.add_run(text)
    r.bold, r.italic = bold, italic
    r.font.size, r.font.color.rgb, r.font.name = Pt(size), color, LATIN
    _fonts(r._element.get_or_add_rPr())
    return r


def _hyperlink(para, text: str, *, url: str | None = None, anchor: str | None = None, size=10):
    h = OxmlElement("w:hyperlink")
    if url:
        h.set(qn("r:id"), para.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
    else:
        h.set(qn("w:anchor"), anchor)
        h.set(qn("w:history"), "1")
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    for tag, val in (("w:color", LINK_COLOR), ("w:u", "single"), ("w:sz", str(int(size * 2)))):
        el = OxmlElement(tag)
        el.set(qn("w:val"), val)
        rpr.append(el)
    rf = OxmlElement("w:rFonts")
    rf.set(qn("w:ascii"), LATIN)
    rf.set(qn("w:hAnsi"), LATIN)
    rf.set(qn("w:eastAsia"), EAST_ASIA)
    rpr.insert(0, rf)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    h.append(run)
    para._p.append(h)


def _inline(para, x: Inline, size=11, color=INK):
    if isinstance(x, Link):
        _hyperlink(para, x.text, url=x.url, size=size)
    elif isinstance(x, Ref):
        _hyperlink(para, x.text, anchor=x.anchor, size=size)
    else:
        _run(para, x, size=size, color=color)


class _Bookmarks:
    def __init__(self):
        self.n = 0

    def add(self, para, name: str) -> None:
        self.n += 1
        start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
        start.set(qn("w:id"), str(self.n))
        start.set(qn("w:name"), name)
        end.set(qn("w:id"), str(self.n))
        ppr = para._p.find(qn("w:pPr"))
        if ppr is not None:
            ppr.addnext(start)
        else:
            para._p.insert(0, start)
        para._p.append(end)


def _shade(cell, fill: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    shd.set(qn("w:val"), "clear")
    tcpr.append(shd)


def _cell(cell, x: Inline, size=9, bold=False, color=INK, fill: str | None = None):
    if fill:
        _shade(cell, fill)
    cell.text = ""
    para = cell.paragraphs[0]
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(2)
    if isinstance(x, str):
        _run(para, x, size=size, bold=bold, color=color)
    else:
        _inline(para, x, size=size)


def _no_split(table) -> None:
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))


def _table(doc, headers: list[str], rows: list[list[Inline]]):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        _cell(t.cell(0, i), h, bold=True, color=WHITE, fill=HEADER_BG)
    for r, row in enumerate(rows, 1):
        for c, val in enumerate(row):
            _cell(t.cell(r, c), val, fill=ALT_BG if r % 2 == 0 else None)
    _no_split(t)
    return t


def _para(doc, text="", size=11, color=INK, italic=False, after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    if text:
        _run(p, text, size=size, color=color, italic=italic)
    return p


def _setup(doc) -> None:
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(s, side, Cm(1.6))
    for name, size, color in (("Normal", 11, INK), ("Heading 1", 18, NAVY), ("Heading 2", 14, TEAL),
                              ("Heading 3", 13, NAVY), ("Heading 4", 11, NAVY)):
        st = doc.styles[name]
        st.font.size, st.font.color.rgb, st.font.name = Pt(size), color, LATIN
        st.font.bold = name != "Normal"
        _fonts(st.element.get_or_add_rPr())
        if name != "Normal":
            st.paragraph_format.keep_with_next = True


def to_docx(document: Document, path: Path) -> Path:
    doc = new_docx()
    _setup(doc)
    marks = _Bookmarks()
    header = doc.sections[0].header.paragraphs[0]
    _run(header, document.title, size=9, bold=True, color=NAVY)
    _run(header, "  ·  " + document.subtitle, size=9, color=MUTED)
    _run(_para(doc, after=2), document.title, size=24, bold=True, color=NAVY)
    _para(doc, document.subtitle, size=12, color=TEAL, after=10)

    for b in document.blocks:
        if isinstance(b, Heading):
            h = doc.add_heading(b.text, level=min(b.level, 4))
            if b.anchor:
                marks.add(h, b.anchor)
        elif isinstance(b, Para):
            _para(doc, b.text, size=10 if b.muted else 11, color=MUTED if b.muted else INK, italic=b.muted)
        elif isinstance(b, Bullets):
            for prefix, content in b.items:
                p = doc.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(2)
                if prefix:
                    _run(p, prefix, bold=True, color=NAVY)
                _inline(p, content)
        elif isinstance(b, Table):
            _table(doc, b.headers, b.rows)
            _para(doc, b.caption, size=9, color=MUTED, italic=True, after=10)
        elif isinstance(b, Card):
            t = doc.add_table(rows=len(b.rows), cols=2)
            t.style = "Table Grid"
            for i, (k, v) in enumerate(b.rows):
                fill = TONE_BG.get(b.tone) if i == 0 else None
                _cell(t.cell(i, 0), k, bold=True, color=NAVY, fill=fill)
                _cell(t.cell(i, 1), v, fill=fill)
                t.cell(i, 0).width, t.cell(i, 1).width = Cm(3.6), Cm(14.2)
            _no_split(t)
            _para(doc, after=6)
        elif isinstance(b, Image):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(str(b.path), width=Cm(16.8))
            if b.caption:
                _para(doc, b.caption, size=9, color=MUTED, italic=True, after=10)
        elif isinstance(b, Code):
            p = _para(doc, after=8)
            p.paragraph_format.left_indent = Cm(0.3)
            _run(p, b.text, size=9)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path
