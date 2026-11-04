"""RTL screenplay export retains text and differentiated editorial formatting."""
from io import BytesIO
from types import SimpleNamespace
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from app.screenplay_layout import render_screenplay

def test_screenplay_docx_writer_production_blocks():
    project=SimpleNamespace(title="مسرحية اختبارية - سيناريو")
    blocks=[
      {'type':'heading','text':'داخلي - مكتبة - نهار'},
      {'type':'action','text':'تضع سلمى المفتاح بجانب الكتاب.'},
      {'type':'character','text':'سلمى'},
      {'type':'parenthetical','text':'(بهمس)'},
      {'type':'dialogue','text':'هل سمعت صوت الباب؟'},
      {'type':'transition','text':'قطع إلى:'},
      {'type':'note','text':'ملاحظة تحريرية تابعة للمؤلف.'}
    ]
    import json
    chapters=[SimpleNamespace(title="المشهد الأول",body="",blocks=json.dumps(blocks,ensure_ascii=False))]
    doc=Document()
    render_screenplay(doc,project,chapters,lambda data,default:json.loads(data))
    out=BytesIO();doc.save(out)
    reopened=Document(BytesIO(out.getvalue()))
    para=reopened.paragraphs
    text="\n".join(p.text for p in para)
    for b in blocks:
        assert b['text'] in text,b
    assert project.title in text
    scene=next(p for p in para if "داخلي - مكتبة" in p.text)
    character=next(p for p in para if p.text=="سلمى")
    dialogue=next(p for p in para if p.text=="هل سمعت صوت الباب؟")
    assert scene.runs[0].bold
    assert character.alignment==WD_ALIGN_PARAGRAPH.CENTER
    assert dialogue.paragraph_format.right_indent.cm>2
    assert dialogue.paragraph_format.left_indent.cm>2
    assert 'w:bidi' in scene._p.xml
    assert 20.8 <= reopened.sections[0].page_width.cm <= 21.2
    assert 29.5 <= reopened.sections[0].page_height.cm <= 29.9
