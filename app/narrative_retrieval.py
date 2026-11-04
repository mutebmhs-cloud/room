"""Deterministic Arabic passage retrieval with original-source offsets.

This is lexical retrieval, not semantic RAG and not a guarantee of coverage.
Never use a generated summary as an authoritative source quote.
"""
import re
import unicodedata
from collections import Counter

_MARKS=re.compile(r'[\u064b-\u065f\u0670\u0640]')
_WORDS=re.compile(r'[\w\u0600-\u06ff]+',re.UNICODE)
_STOP=frozenset(('الذي','التي','على','كانت','كان','ذلك','تلك','هذه','هذا',
 'حيث','إلى','الى','عندما','بعد','قبل','بين','كما','لكن','هناك','من','في','عن','مع',
 'وقد','لقد','حتى','سوف','أنا','أنت','نحن','كل','ثم','وهو','وهي','أو','هو','هي'))

def normalized(value):
    s=unicodedata.normalize('NFKC',str(value or ''))
    s=_MARKS.sub('',s)
    return s.translate(str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا','ى':'ي'})).casefold()

def terms(value):
    return [x for x in _WORDS.findall(normalized(value)) if len(x)>2 and x not in _STOP]

def salient_terms(value,max_terms=28):
    """Frequency-capped query vocabulary; excludes long stopword-like lists."""
    counts=Counter(terms(value))
    return set(k for k,_ in counts.most_common(max_terms))

def token_score(query_terms,passage):
    words=terms(passage)
    if not query_terms or not words:return 0
    matches=Counter(words)
    return sum(min(3,matches.get(t,0)) for t in query_terms)

def select_passage(text,query_terms,limit=1300):
    """Return the original unaltered substring and its exact character offset."""
    text=str(text or '')
    if len(text)<=limit:return text,0
    step=max(180,limit//2)
    candidates=list(range(0,len(text),step))
    candidates.append(max(0,len(text)-limit))
    ranked=[]
    for start in sorted(set(candidates)):
        start=min(start,len(text)-limit)
        if start<0:start=0
        part=text[start:start+limit]
        ranked.append((token_score(query_terms,part),-start,start,part))
    ranked.sort(reverse=True)
    best=ranked[0]
    return best[3],best[2]

def rank_chapters(sections,selected_id,query='',synopses=None,limit=8):
    """Rank by all chapter text, not only the opening paragraphs."""
    synopses=synopses or {}
    selected=next((s for s in sections if s.id==selected_id),None)
    if selected is None:return []
    query_terms=salient_terms(query or selected.body[:1500])
    ranked=[]
    for section in sections:
        if section.id==selected_id:continue
        full_text=section.body
        try:
            import json
            blocks=json.loads(section.blocks or '[]')
            full_text+='\n'+'\n'.join(str(b.get('text','')) for b in blocks)
        except (ValueError,TypeError,AttributeError):
            pass
        summary=synopses.get(section.id,'')
        score=token_score(query_terms,full_text)+min(5,token_score(query_terms,summary))
        ranked.append((score,section.position,section.id,section,full_text))
    ranked.sort(key=lambda item:(-item[0],item[1],item[2]))
    return [(s,raw,score) for score,_,_,s,raw in ranked[:limit]]
