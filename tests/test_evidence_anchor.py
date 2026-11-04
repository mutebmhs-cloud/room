"""Evidence anchoring must never manufacture or paraphrase quotations."""
from app.evidence_anchor import literal_anchor
from app.writer_intelligence import CRITIQUE_SCHEMA

def test_literal_anchor_keeps_writer_words():
    source='قالت سلمى: «أحرقت هند الرسالة الأصلية». وبعدها دخلت الغرفة.'
    assert literal_anchor(source,'«أحرقت هند الرسالة الأصلية»')=='أحرقت هند الرسالة الأصلية'
    assert literal_anchor(source,'أحرقت هند الرسالة الأصلية')=='أحرقت هند الرسالة الأصلية'
    assert literal_anchor(source,'وصلت هند إلى الغرفة')==''
    assert literal_anchor(source,'غَيَّرت هند رأيها')==''

def test_unicode_diacritics_and_whitespace_only():
    source='في صباح الإثنين قال سامر صراحة إنه يبلغ اثنين وثلاثين عامًا.'
    quote='قال سامر صراحة إنه يبلغ اثنين وثلاثين عاما'
    result=literal_anchor(source,quote)
    assert result in source and result.startswith('قال سامر')
    assert literal_anchor('سلّمت هند الكتاب إلى مها','سلمت هند الكتاب إلى مها') in ('سلّمت هند الكتاب إلى مها','')

def test_critical_structured_schema_is_focused_and_closed():
    assert CRITIQUE_SCHEMA['required']==['feedback']
    assert CRITIQUE_SCHEMA['additionalProperties'] is False
    assert CRITIQUE_SCHEMA['properties']['feedback']['items']['additionalProperties'] is False
