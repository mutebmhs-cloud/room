"""Minimal standards-oriented EPUB 3 for Arabic fiction (without external services).

Export only; DOCX remains the import path. XHTML escapes all manuscript content
and uses right-to-left direction. No AI or external calls are required.
"""
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
from html import escape
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, Section
from . import main as core

router=APIRouter(prefix='/api/projects/{pid}/manuscript',tags=['manuscript-epub'])

def xml_text(value):
    return escape(str(value or ''),quote=True)

def page(title,body):
    return ('<?xml version="1.0" encoding="utf-8"?>'
     '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"'
     ' xml:lang="ar" lang="ar" dir="rtl">'
     '<head><meta charset="utf-8"/><title>'+xml_text(title)+'</title>'
     '<link rel="stylesheet" type="text/css" href="../styles.css"/></head>'
     '<body>'+body+'</body></html>')

@router.get('/epub')
def export_epub(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    project=core.owned_project(db,user,pid)
    sections=db.scalars(select(Section).where(Section.project_id==pid)
                        .order_by(Section.position,Section.id)).all()
    title=project.title
    bookid='urn:uuid:'+str(uuid4())
    timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    chapters=[]
    for index,s in enumerate(sections,1):
        name='chapters/chapter-'+str(index)+'.xhtml'
        paragraphs=['<h1>'+xml_text(s.title)+'</h1>']
        lines=[s.body]
        blocks=core._json(s.blocks,[])
        for block in blocks:
            if isinstance(block,dict) and isinstance(block.get('text'),str):
                lines.append(block['text'])
        for part in '\n'.join(lines).split('\n'):
            if not part.strip():
                paragraphs.append('<p class="space">&#160;</p>')
            else:
                paragraphs.append('<p>'+xml_text(part)+'</p>')
        chapters.append((name,s.title,page(s.title,''.join(paragraphs))))
    nav='<nav epub:type="toc" id="toc"><h1>فهرس المحتويات</h1><ol>'+''.join(
        '<li><a href="'+name+'">'+xml_text(chapter_title)+'</a></li>'
        for name,chapter_title,_ in chapters)+'</ol></nav>'
    nav_page=('<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ar" lang="ar" dir="rtl">'
        '<head><meta charset="utf-8"/><title>فهرس المحتويات</title>'
        '<link rel="stylesheet" href="styles.css" type="text/css"/></head><body>'
        +nav+'</body></html>')
    manifest=['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
              '<item id="css" href="styles.css" media-type="text/css"/>']
    spine=[]
    for i,(name,_,_) in enumerate(chapters,1):
        manifest.append('<item id="c'+str(i)+'" href="'+name+
                        '" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="c'+str(i)+'"/>')
    content_opf=('<?xml version="1.0" encoding="utf-8"?>'
      '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
      ' unique-identifier="bookid" xml:lang="ar" dir="rtl">'
      '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
      '<dc:identifier id="bookid">'+xml_text(bookid)+'</dc:identifier>'
      '<dc:title>'+xml_text(title)+'</dc:title>'
      '<dc:language>ar</dc:language>'
      '<meta property="dcterms:modified">'+timestamp+'</meta>'
      '</metadata><manifest>'+''.join(manifest)+'</manifest>'
      '<spine page-progression-direction="rtl">'+''.join(spine)+'</spine></package>')
    buf=BytesIO()
    with ZipFile(buf,'w') as z:
        z.writestr('mimetype','application/epub+zip',compress_type=ZIP_STORED)
        z.writestr('META-INF/container.xml',
            '<?xml version="1.0" encoding="utf-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf"'
            ' media-type="application/oebps-package+xml"/></rootfiles></container>',
            compress_type=ZIP_DEFLATED)
        z.writestr('OEBPS/content.opf',content_opf,compress_type=ZIP_DEFLATED)
        z.writestr('OEBPS/nav.xhtml',nav_page,compress_type=ZIP_DEFLATED)
        z.writestr('OEBPS/styles.css','body{direction:rtl;text-align:right;font-family:serif;'
             'line-height:1.7;margin:1em}p{white-space:pre-wrap}h1{page-break-before:always}'
             '.space{min-height:.7em}',compress_type=ZIP_DEFLATED)
        for name,_,html in chapters:
            z.writestr('OEBPS/'+name,html,compress_type=ZIP_DEFLATED)
    buf.seek(0)
    return StreamingResponse(buf,media_type='application/epub+zip',
        headers={'Content-Disposition':'attachment; filename="writer-manuscript.epub"',
                 'Cache-Control':'no-store'})
