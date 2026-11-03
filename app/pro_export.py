"""Editable DOCX export for authored manuscripts; manuscript text stays on server."""
from io import BytesIO
from fastapi import APIRouter,Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from docx import Document
from docx.shared import Cm,Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .db import get_db
from .models import User,Section
from . import main as core

router=APIRouter(prefix="/api/pro-export",tags=["professional-export"])
def rtl(p):
 p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
 ppr=p._p.get_or_add_pPr()
 el=OxmlElement('w:bidi');el.set(qn('w:val'),'1');ppr.append(el)
def paragraph(doc,value):
 p=doc.add_paragraph();rtl(p);p.add_run(value);return p
@router.get("/projects/{pid}/docx")
def export_docx(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
 project=core.owned_project(db,user,pid)
 sections=db.scalars(select(Section).where(Section.project_id==pid).order_by(Section.position,Section.id)).all()
 doc=Document()
 sec=doc.sections[0];sec.top_margin=Cm(2.2);sec.bottom_margin=Cm(2.2);sec.left_margin=Cm(2.4);sec.right_margin=Cm(2.4)
 style=doc.styles['Normal'];style.font.name='Arial';style.font.size=Pt(12)
 title=doc.add_paragraph();rtl(title);title.alignment=WD_ALIGN_PARAGRAPH.CENTER;run=title.add_run(project.title);run.bold=True;run.font.size=Pt(20)
 for idx,s in enumerate(sections):
  if idx:doc.add_page_break()
  heading=doc.add_paragraph();rtl(heading);r=heading.add_run(s.title);r.bold=True;r.font.size=Pt(15)
  if project.kind=="screenplay":
   blocks=core._json(s.blocks,[])
   for block in blocks:
    kind=block.get("type","");value=block.get("text","")
    if not value:continue
    p=paragraph(doc,value)
    if kind in ("heading","character"):p.runs[0].bold=True
    if kind in ("character","dialogue","parenthetical"):p.paragraph_format.left_indent=Cm(1.6)
  else:
   for part in s.body.split("\n"):paragraph(doc,part)
 out=BytesIO();doc.save(out);out.seek(0)
 return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
   headers={"Content-Disposition":f'attachment; filename="writer-project-{pid}.docx"',"Cache-Control":"no-store"})
