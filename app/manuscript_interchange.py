"""Arabic manuscript DOCX interchange. Original manuscript text remains author-controlled."""
from io import BytesIO
import base64
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_BREAK
from docx.shared import Pt, Cm
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .db import get_db
from .models import User, Section
from . import main as core

router=APIRouter(prefix='/api/projects/{pid}/manuscript',tags=['manuscript-interchange'])

def rtl(paragraph):
    paragraph.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    ppr=paragraph._p.get_or_add_pPr()
    bidi=OxmlElement('w:bidi');bidi.set(qn('w:val'),'1');ppr.append(bidi)
    for run in paragraph.runs:
        rpr=run._r.get_or_add_rPr()
        rtl_tag=OxmlElement('w:rtl');rtl_tag.set(qn('w:val'),'1');rpr.append(rtl_tag)

def format_document(doc):
    sec=doc.sections[0]
    sec.top_margin=Cm(2.4);sec.bottom_margin=Cm(2.4)
    sec.left_margin=Cm(2.5);sec.right_margin=Cm(2.5)
    style=doc.styles['Normal']
    style.font.name='Arial';style.font.size=Pt(12)
    style.paragraph_format.space_after=Pt(7)
    style.paragraph_format.line_spacing=1.5

@router.get('/docx')
def export_docx(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    project=core.owned_project(db,user,pid)
    doc=Document();format_document(doc)
    title=doc.add_paragraph(style='Title');title.add_run(project.title);rtl(title)
    for section in db.scalars(select(Section).where(Section.project_id==pid).order_by(Section.position,Section.id)):
        h=doc.add_paragraph(style='Heading 1');h.add_run(section.title);rtl(h)
        blocks=core._json(section.blocks,[])
        content=section.body
        if blocks:
            content+='\n'+'\n'.join(str(b.get('text','')) for b in blocks if b.get('text'))
        for line in content.splitlines():
            p=doc.add_paragraph();p.add_run(line);rtl(p)
    buffer=BytesIO();doc.save(buffer);buffer.seek(0)
    return StreamingResponse(buffer,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':'attachment; filename="writer-manuscript.docx"',
                 'Cache-Control':'no-store'})

class DocxImport(BaseModel):
    filename:str=Field(min_length=5,max_length=120)
    content_base64:str=Field(min_length=50,max_length=9000000)

@router.post('/docx/import')
def import_docx(pid:int,data:DocxImport,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    project=core.owned_project(db,user,pid)
    if not data.filename.lower().endswith('.docx'):
        raise HTTPException(422,'يجب اختيار ملف DOCX')
    try:
        raw=base64.b64decode(data.content_base64,validate=True)
        if len(raw)>6_000_000 or len(raw)<100:
            raise ValueError('invalid file size')
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            if len(archive.namelist())>120 or sum(x.file_size for x in archive.infolist())>24_000_000:
                raise ValueError('oversized document')
        doc=Document(BytesIO(raw))
        entries=[];heading='نص مستورد';lines=[]
        for paragraph in doc.paragraphs:
            txt=paragraph.text
            if len(txt)>12000:raise ValueError('long paragraph')
            is_heading=paragraph.style and paragraph.style.name.lower().startswith(('heading 1','title 1','العنوان 1'))
            if is_heading and txt.strip():
                if lines:entries.append((heading,'\n'.join(lines)));lines=[]
                heading=txt.strip()[:240]
            else:lines.append(txt)
        if lines:entries.append((heading,'\n'.join(lines)))
        if not entries:raise ValueError('empty document')
        current=db.scalars(select(Section).where(Section.project_id==pid)).all()
        if len(current)+len(entries)>400:raise ValueError('too many chapters')
        added=sum(len(t.encode('utf-8')) for _,t in entries)
        existing=sum(len(x.body.encode('utf-8'))+len(x.blocks.encode('utf-8')) for x in current)
        if added+existing+len(project.scratchpad.encode('utf-8'))>25_000_000:raise ValueError('size limit')
        pos=max([s.position for s in current]+[-1])+1
        for idx,(chapter,body) in enumerate(entries):
            db.add(Section(project_id=pid,title=chapter or 'فصل مستورد',body=body,
                           blocks='[]',position=pos+idx))
        db.commit()
        return {'added_sections':len(entries),'warning':'راجع تقسيم الفصول والتنسيق بعد الاستيراد'}
    except (ValueError,TypeError,zipfile.BadZipFile,KeyError,IndexError) as exc:
        db.rollback()
        raise HTTPException(422,'ملف DOCX غير صالح أو يتجاوز حدود الاستيراد') from exc
