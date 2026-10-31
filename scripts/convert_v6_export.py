"""Convert V6 local backups (schema=4) to individual cloud beta imports.
Does NOT mutate input. Explicitly errors for unsupported genres, oversized projects,
or metadata that cannot be preserved in supported target fields.
"""
import json,sys,re,argparse
from pathlib import Path
KINDS={'novel','short','flash','children','screenplay'}
BLOCKS={'action','character','dialogue','parenthetical','transition'}
def convert_one(p):
    if p['genre'] not in KINDS: raise ValueError('نوع غير مدعوم حاليًا')
    sections=[];source_map={}
    for i,d in enumerate(p.get('docs',[])):
        if d.get('kind') not in ('prose','screenplay'): raise ValueError('نوع مقطع غير معروف')
        if d.get('kind')=='screenplay' and p['genre']!='screenplay': raise ValueError('تعارض النوع')
        body=d.get('body',''); blocks=[]
        if d.get('kind')=='screenplay':
            scene=d.get('scene') or {}
            heading=f"{scene.get('interior','INT')}. {scene.get('location','')} - {scene.get('time','')}"
            blocks.append({'type':'heading','text':heading})
            for b in d.get('blocks',[]):
                if b.get('type') not in BLOCKS: raise ValueError('عنصر سيناريو غير مدعوم')
                blocks.append({'type':b['type'],'text':b['text']})
        sections.append({'id':d['id'],'title':d['title'],'body':body,'blocks':blocks,'position':i})
        source_map[d['id']]=body+'\n'+'\n'.join(b['text'] for b in blocks)
    state=p.get('assistantState') or {};cp=state.get('checkpoint') or {}
    checkpoint={'section_id':cp.get('docId'),'summary':cp.get('done',''),'next':cp.get('next',''),'question':cp.get('question','')}
    notes='\n'.join('ملاحظة: '+n.get('text','') for n in p.get('notes',[]))
    tasks='\n'.join('مهمة: '+t.get('text','')+(' [منجزة]' if t.get('done') else '') for t in p.get('tasks',[]))
    scratchpad='\n\n'.join(x for x in [state.get('freeInput',''),notes,tasks] if x)
    facts=[]
    for f in p.get('facts',[]):
        old_sid=f.get('docId')
        quote=f.get('quote','')
        evidence=quote if old_sid in source_map and quote in source_map[old_sid] else ''
        facts.append({'subject':f.get('subject',''),'predicate':f.get('attribute','غير محدد'), 'value':f.get('value',''),'evidence':evidence,'section_id':old_sid if evidence else None})
    return {'format':'writer-cloud-v1', 'project':{'kind':p['genre'],'title':p['title'],'premise':str(p.get('intent','')),'scratchpad':scratchpad,'structure':p.get('structure') or {},'checkpoint':checkpoint}, 'sections':sections,'facts':facts}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('input');parser.add_argument('--outdir',default='converted_v6');args=parser.parse_args()
    raw=json.loads(Path(args.input).read_text(encoding='utf-8'))
    if raw.get('schema')!=4 or not isinstance(raw.get('projects'),list): raise SystemExit('Not a recognized V6 export (schema=4)')
    target=Path(args.outdir);target.mkdir(parents=True,exist_ok=True)
    report=[]
    for i,p in enumerate(raw['projects'],1):
        try:
            converted=convert_one(p)
            payload=json.dumps(converted,ensure_ascii=False,indent=2)
            if len(payload.encode())>50_000_000: raise ValueError('حجم الملف يتجاوز حد الاستيراد')
            path=target/f'project_{i:03d}.json';path.write_text(payload,encoding='utf-8')
            report.append(f'OK {p.get("title")} → {path.name} [مراجعة بيانات الشواهد مطلوبة]')
        except (ValueError,TypeError,KeyError) as e: report.append(f'SKIPPED {p.get("title","عمل غير معروف")}: {e}')
    (target/'conversion_report.txt').write_text('\n'.join(report),encoding='utf-8')
    print('\n'.join(report))
    print('Keep original V6 backup: prior chat/exercise/version archives are NOT migrated and must remain accessible there.')
if __name__=='__main__':main()
