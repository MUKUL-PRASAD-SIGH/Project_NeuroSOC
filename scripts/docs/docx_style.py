"""Small python-docx helpers that reproduce the look of the NeuroSOC Technical Specification Series
(Volumes 1 to 3): Segoe UI headings in navy, Calibri body, Consolas listings, navy table headers, shaded
label columns, and a 'Confidential' header with a page-numbered footer on US Letter with 1 inch margins."""

from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Twips

NAVY, DEEP, TEAL, TEXT, CODE = "1B365D", "2B3A67", "0D5C75", "2D3748", "1E293B"
BAND, LABEL, NOTE_FILL = "F4F7FA", "F8FAFC", "EAF2F7"


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def new_document() -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Twips(12240), Twips(15840)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Twips(1440))
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    return doc


def _run(paragraph, text: str, *, font="Calibri", size=10.5, bold=False, italic=False, color=TEXT):
    run = paragraph.add_run(text)
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:hAnsi"), font)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = rgb(color)
    return run


def _spacing(paragraph, before=0, after=80, line=None):
    fmt = paragraph.paragraph_format
    fmt.space_before, fmt.space_after = Pt(before / 20), Pt(after / 20)
    if line:
        fmt.line_spacing = line / 240


def shade(cell_or_paragraph, fill: str) -> None:
    props = cell_or_paragraph._tc.get_or_add_tcPr() if hasattr(cell_or_paragraph, "_tc") else cell_or_paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def _cell_margins(cell, top=80, bottom=80, left=120, right=120):
    props = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for name, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{name}")
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    props.append(mar)


def _borders(cell, **edges):
    props = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        node = OxmlElement(f"w:{edge}")
        spec = edges.get(edge)
        if spec:
            node.set(qn("w:val"), "single")
            node.set(qn("w:sz"), str(spec[0]))
            node.set(qn("w:color"), spec[1])
        else:
            node.set(qn("w:val"), "nil")
        borders.append(node)
    props.append(borders)


def _field(paragraph, instruction: str):
    for kind, text in (("begin", None), (None, instruction), ("end", None)):
        run = paragraph.add_run()
        run.font.size = Pt(8.5)
        run.font.color.rgb = rgb("7A869A")
        if kind:
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), kind)
        else:
            node = OxmlElement("w:instrText")
            node.set(qn("xml:space"), "preserve")
            node.text = text
        run._r.append(node)


def header_footer(doc: Document) -> None:
    section = doc.sections[0]
    head = section.header.paragraphs[0]
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(head, "NeuroSOC Enterprise Technical Specification | Confidential", size=8.5, color="7A869A")
    foot = section.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(foot, "Project NeuroSOC — Neuromorphic AI Security Operations Center — Page ", size=8.5, color="7A869A")
    _field(foot, "PAGE")


# ── content blocks ────────────────────────────────────────────────────────────────────────────
def title_block(doc: Document, kicker: str, title: str, subtitle: str) -> None:
    p = doc.add_paragraph()
    _spacing(p, 720, 240)
    _run(p, kicker, font="Segoe UI", size=11, bold=True, color=TEAL)
    p = doc.add_paragraph()
    _spacing(p, 0, 160)
    _run(p, title, font="Cambria", size=28, bold=True, color=NAVY)
    p = doc.add_paragraph()
    _spacing(p, 0, 480)
    _run(p, subtitle, size=15, color=DEEP)
    p = doc.add_paragraph()
    _spacing(p, 0, 400)
    _run(p, "―" * 24, size=14, color=TEAL)


def spec_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=0, cols=2)
    table.autofit = False
    for label, value in rows:
        cells = table.add_row().cells
        for cell, width in zip(cells, (Twips(3168), Twips(6192))):
            cell.width = width
            _cell_margins(cell)
            _borders(cell)
        shade(cells[0], LABEL)
        shade(cells[1], LABEL)
        cells[0].paragraphs[0].text = ""
        _spacing(cells[0].paragraphs[0], 40, 40)
        _run(cells[0].paragraphs[0], label, bold=True, size=9.5, color=DEEP)
        _spacing(cells[1].paragraphs[0], 40, 40)
        _run(cells[1].paragraphs[0], value, size=9.5)
    doc.add_paragraph()


def h1(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    _spacing(p, 360, 120)
    _run(p, text, font="Segoe UI", size=17, bold=True, color=NAVY)


def h2(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    _spacing(p, 280, 80)
    _run(p, text, font="Segoe UI", size=13.5, bold=True, color=DEEP)


def para(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    _spacing(p, 0, 80, 276)
    _run(p, text)


def bullets(doc: Document, items: list[tuple[str, str] | str]) -> None:
    """Each item is 'Lead text' or ('Lead', 'rest'); the lead is set in bold like the existing volumes."""
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        _spacing(p, 0, 40, 276)
        p.paragraph_format.left_indent = Twips(360)
        if isinstance(item, tuple):
            _run(p, item[0] + " — ", bold=True)
            _run(p, item[1])
        else:
            _run(p, item)


def caption(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    _spacing(p, 160, 40)
    _run(p, text, font="Segoe UI", size=9.5, bold=True, color=NAVY)


def table(doc: Document, header: list[str], rows: list[list[str]], widths: list[int]) -> None:
    t = doc.add_table(rows=1, cols=len(header))
    t.autofit = False
    for cell, text, width in zip(t.rows[0].cells, header, widths):
        cell.width = Twips(width)
        shade(cell, NAVY)
        _cell_margins(cell, 120, 120, 140, 140)
        cell.paragraphs[0].text = ""
        _spacing(cell.paragraphs[0], 40, 40)
        _run(cell.paragraphs[0], text, font="Segoe UI", size=9, bold=True, color="FFFFFF")
    for index, row in enumerate(rows):
        cells = t.add_row().cells
        for cell, text, width in zip(cells, row, widths):
            cell.width = Twips(width)
            _cell_margins(cell, 80, 80, 140, 140)
            _borders(cell, bottom=(4, "D8DEE6"))
            if index % 2:
                shade(cell, BAND)
            cell.paragraphs[0].text = ""
            _spacing(cell.paragraphs[0], 20, 20)
            _run(cell.paragraphs[0], text, size=8.5)
    for row in t.rows:   # never split a row across two pages
        node = OxmlElement("w:cantSplit")
        node.set(qn("w:val"), "true")
        row._tr.get_or_add_trPr().append(node)
    # a header row that repeats across pages
    trpr = t.rows[0]._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    trpr.append(node)
    doc.add_paragraph()


MAX_CODE_COLS = 88   # what fits on the page at Consolas 8.5 pt


def code(doc: Document, text: str) -> None:
    for line in text.strip("\n").split("\n"):
        if len(line) > MAX_CODE_COLS:
            print(f"WARNING: code line is {len(line)} columns (max {MAX_CODE_COLS}): {line[:60]}...")
        p = doc.add_paragraph()
        _spacing(p, 0, 20, 252)
        p.paragraph_format.left_indent = Twips(160)
        shade(p, "F1F5F9")
        _run(p, line if line else " ", font="Consolas", size=8.5, color=CODE)
    doc.add_paragraph()


def callout(doc: Document, label: str, title: str, body: str) -> None:
    t = doc.add_table(rows=1, cols=1)
    t.autofit = False
    cell = t.rows[0].cells[0]
    cell.width = Twips(9360)
    shade(cell, NOTE_FILL)
    _cell_margins(cell, 140, 140, 200, 200)
    _borders(cell, left=(24, TEAL))
    p = cell.paragraphs[0]
    _spacing(p, 40, 60)
    _run(p, f"[{label}]  {title}", font="Segoe UI", size=10, bold=True, color=NAVY)
    p.add_run().add_break()
    _run(p, body, size=9.5)
    doc.add_paragraph()


def _hyperlink(paragraph, url: str, text: str, size: float = 8.5) -> None:
    """A real, clickable external hyperlink (blue, underlined) in a paragraph."""
    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "Calibri")
    fonts.set(qn("w:hAnsi"), "Calibri")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    for node in (fonts, color, underline, sz):
        props.append(node)
    run.append(props)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def link_table(doc: Document, header: list[str], rows: list[tuple[str, str, str]], widths: list[int]) -> None:
    """Rows are (name, url, notes). The url column is clickable; a row whose url is empty shows 'not available'."""
    t = doc.add_table(rows=1, cols=3)
    t.autofit = False
    for cell, text, width in zip(t.rows[0].cells, header, widths):
        cell.width = Twips(width)
        shade(cell, NAVY)
        _cell_margins(cell, 120, 120, 140, 140)
        cell.paragraphs[0].text = ""
        _spacing(cell.paragraphs[0], 40, 40)
        _run(cell.paragraphs[0], text, font="Segoe UI", size=9, bold=True, color="FFFFFF")
    for index, (name, url, notes) in enumerate(rows):
        cells = t.add_row().cells
        for cell, width in zip(cells, widths):
            cell.width = Twips(width)
            _cell_margins(cell, 80, 80, 140, 140)
            _borders(cell, bottom=(4, "D8DEE6"))
            if index % 2:
                shade(cell, BAND)
            cell.paragraphs[0].text = ""
            _spacing(cell.paragraphs[0], 20, 20)
        _run(cells[0].paragraphs[0], name, size=8.5, bold=True, color=DEEP)
        if url.startswith("http"):
            _hyperlink(cells[1].paragraphs[0], url, url)
        else:
            _run(cells[1].paragraphs[0], url, size=8.5)
        _run(cells[2].paragraphs[0], notes, size=8.5)
    for row in t.rows:
        node = OxmlElement("w:cantSplit")
        node.set(qn("w:val"), "true")
        row._tr.get_or_add_trPr().append(node)
    trpr = t.rows[0]._tr.get_or_add_trPr()
    head = OxmlElement("w:tblHeader")
    head.set(qn("w:val"), "true")
    trpr.append(head)
    doc.add_paragraph()
