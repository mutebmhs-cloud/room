"""Right-to-left editable screenplay DOCX composition for Arabic authors.

Preserves the author's screenplay blocks and distinguishes scene headings,
action, dialogue and parentheticals. This is a professional draft layout,
not an assertion of compliance with every production company's house style.
"""
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def apply_rtl(paragraph):
    ppr=paragraph._p.get_or_add_pPr()
    bidi=OxmlElement("w:bidi")
    bidi.set(qn("w:val"),"1")
    ppr.append(bidi)
    for run in paragraph.runs:
        rpr=run._r.get_or_add_rPr()
        rtl=OxmlElement("w:rtl")
        rtl.set(qn("w:val"),"1")
        rpr.append(rtl)

def paragraph(doc,text,kind):
    p=doc.add_paragraph()
    p.style=doc.styles["Normal"]
    p.paragraph_format.space_before=Pt(0)
    p.paragraph_format.space_after=Pt(5 if kind in ("action","dialogue") else 2)
    p.paragraph_format.keep_together=True
    p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.left_indent=Cm(0)
    p.paragraph_format.right_indent=Cm(0)
    if kind=="heading":
        p.paragraph_format.space_before=Pt(12)
        p.paragraph_format.keep_with_next=True
    elif kind=="character":
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next=True
    elif kind=="dialogue":
        p.paragraph_format.left_indent=Cm(2.8)
        p.paragraph_format.right_indent=Cm(2.8)
    elif kind=="parenthetical":
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.left_indent=Cm(3)
        p.paragraph_format.right_indent=Cm(3)
        p.paragraph_format.keep_with_next=True
    elif kind=="transition":
        p.alignment=WD_ALIGN_PARAGRAPH.LEFT
    elif kind=="note":
        p.paragraph_format.left_indent=Cm(1.5)
    run=p.add_run(str(text))
    run.font.name="Arial"
    run.font.size=Pt(12)
    run.bold=kind in ("heading","character","transition")
    run.italic=kind in ("parenthetical","note")
    apply_rtl(p)
    return p

def render_screenplay(doc, project, sections,decode_blocks):
    s=doc.sections[0]
    s.page_height=Cm(29.7)
    s.page_width=Cm(21.0)
    s.top_margin=Cm(2.3)
    s.bottom_margin=Cm(2.3)
    s.left_margin=Cm(2.5)
    s.right_margin=Cm(2.5)
    title=doc.add_paragraph()
    title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after=Pt(22)
    run=title.add_run(project.title)
    run.bold=True;run.font.size=Pt(18);run.font.name="Arial"
    apply_rtl(title)
    for section in sections:
        blocks=decode_blocks(section.blocks,[])
        if not any(x.get("type")=="heading" for x in blocks):
            paragraph(doc,section.title,"heading")
        if section.body.strip():
            for line in section.body.splitlines():
                paragraph(doc,line,"action")
        for block in blocks:
            kind=block.get("type")
            body=str(block.get("text",""))
            if not body.strip():
                continue
            if kind not in {"heading","action","character","dialogue",
                            "parenthetical","transition","note"}:
                kind="action"
            for line in body.splitlines():
                paragraph(doc,line,kind)
