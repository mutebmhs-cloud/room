"""Conservative Fountain parser for the supported subset.
Rejects ambiguous advanced syntax; never silently drops a nonempty line.
"""
import re
class FountainError(ValueError): pass

def parse(text):
    if not isinstance(text,str) or not text.strip() or len(text)>500_000: raise FountainError('ملف Fountain فارغ أو طويل جدًا')
    lines=text.replace('\r\n','\n').replace('\r','\n').split('\n')
    if any(re.match(r'^\s*(?:/\*|\*/|\[\[|~|#{1,6}\s)',line) for line in lines): raise FountainError('صيغة Fountain متقدمة غير مدعومة؛ لا يمكن استيرادها بأمان')
    scenes=[]; current=None; state='none'; in_header=True
    for i,raw in enumerate(lines,1):
        line=raw.strip()
        if not line:
            state='none'; continue
        if in_header and re.match(r'^(Title|Author|Credit|Draft date|Contact|Source|Notes):',line,re.I): continue
        # Forced heading (.scene) and common English slugline; allow Arabic INT/EXT without dot.
        forced=line.startswith('.') and len(line)>1
        usual=bool(re.match(r'^(?:INT|EXT|INT/EXT|I/E)\.?\s+',line,re.I))
        if forced or usual:
            heading=line[1:].strip() if forced else line
            if not heading: raise FountainError(f'عنوان مشهد فارغ في السطر {i}')
            current={'title':heading[:240],'body':'','blocks':[{'type':'heading','text':heading}]}; scenes.append(current); in_header=False;state='none';continue
        if current is None: raise FountainError(f'سطر خارج المشهد في موضع {i}; لا يمكن تجاهله')
        if raw!=raw.strip(): raise FountainError(f'مسافات بادئة أو لاحقة غير مدعومة في السطر {i}; راجع النص قبل الاستيراد')
        if line.startswith('@'):
            kind,val='character',line[1:];state='speaker'
        elif line.startswith('!'):
            kind,val='action',line[1:];state='none'
        elif line.startswith('>'):
            kind,val='transition',line[1:];state='none'
        elif re.fullmatch(r'\(.+\)',line) and state in ('speaker','dialogue'):
            kind,val='parenthetical',line[1:-1];state='speaker'
        elif state in ('speaker','dialogue'):
            kind,val='dialogue',raw;state='dialogue'
        else:
            if re.fullmatch(r'[\u0600-\u06FF\s]{2,30}',line) and i<len(lines) and lines[i].strip():
                raise FountainError(f'سطر عربي ملتبس قد يمثل اسم شخصية عند السطر {i}; أضف @ للشخصية أو ! للحركة')
            kind,val='action',raw;state='none'
        if not val.strip(): raise FountainError(f'عنصر فارغ في السطر {i}')
        if len(val)>15000: raise FountainError(f'عنصر طويل في السطر {i}')
        if kind=='dialogue' and current['blocks'][-1]['type']=='dialogue':
            new=current['blocks'][-1]['text']+'\n'+val
            if len(new)>15000: raise FountainError(f'الحوار طويل عند السطر {i}')
            current['blocks'][-1]['text']=new
        else: current['blocks'].append({'type':kind,'text':val})
        if len(current['blocks'])>900: raise FountainError(f'المشهد يتجاوز عدد العناصر عند السطر {i}')
    if not scenes: raise FountainError('لم يُعثر على مشاهد')
    if len(scenes)>400: raise FountainError('عدد المشاهد يتجاوز الحد')
    return scenes
