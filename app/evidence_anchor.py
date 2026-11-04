"""Conservative grounding of model-proposed Arabic evidence in literal source text.

Only an actual contiguous excerpt in the submitted source may be returned.
Unicode presentation forms, vowel marks, whitespace and surrounding quotation
marks can vary; paraphrases are NEVER accepted as quotations.
"""
import re
import unicodedata

_QUOTES=' \\t\\r\\n«»“”\"\'‘’‹›'

def _normalize_positions(source):
    chars=[]
    positions=[]
    for i,char in enumerate(source):
        for unit in unicodedata.normalize('NFKC',char):
            if unit=='ـ' or unicodedata.category(unit)=='Mn':
                continue
            if unit.isspace():
                if chars and chars[-1]==' ':
                    continue
                unit=' '
            chars.append(unit)
            positions.append(i)
    return ''.join(chars),positions

def _candidates(raw):
    raw=raw.strip()
    if not raw:return []
    parts=[raw,raw.strip(_QUOTES)]
    parts += re.findall(r'«([^»]{4,500})»|“([^”]{4,500})”|\"([^\"]{4,500})\"',raw)
    flattened=[]
    for part in parts:
        if isinstance(part,tuple):
            part=next((x for x in part if x),'')
        part=part.strip(_QUOTES)
        if part and part not in flattened:
            flattened.append(part)
    return flattened

def literal_anchor(source: str, proposed: str) -> str:
    if not isinstance(proposed,str) or not isinstance(source,str):
        return ''
    choices=_candidates(proposed)
    if not choices:return ''
    for choice in choices:
        if choice in source:
            return choice
    canonical,positions=_normalize_positions(source)
    for choice in choices:
        normalized,_=_normalize_positions(choice)
        normalized=normalized.strip()
        if len(normalized)<12:
            continue
        start=canonical.find(normalized)
        if start>=0 and positions:
            end=start+len(normalized)-1
            if end<len(positions):
                return source[positions[start]:positions[end]+1]
    return ''
