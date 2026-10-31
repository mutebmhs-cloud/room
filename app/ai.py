import os, json
import httpx
from fastapi import HTTPException

SCHEMA={"type":"object","properties":{
 "reply":{"type":"string"},
 "questions":{"type":"array","items":{"type":"string"}},
 "suggestions":{"type":"array","items":{"type":"object","properties":{"field":{"type":"string","enum":["premise","genre","theme","protagonist","goal","obstacle","audience","logline","next_step"]},"value":{"type":"string"},"reason":{"type":"string"}},"required":["field","value","reason"],"additionalProperties":False}}
},"required":["reply","questions","suggestions"],"additionalProperties":False}

def instruction(kind):
    unit = ('السيناريو: ركز على المشاهد، الفعل القابل للتصوير، الحوار، الدافع، الانتقال والسببية.' if kind=='screenplay' else
        'الرواية: ركز على الحبكة والسرد والتبئير والشخصيات والسببية.' if kind=='novel' else
        'القصة القصيرة: ركز على التكثيف والحدث الواحد والإيقاع والنهاية.' if kind in ['short','flash'] else
        'قصة الأطفال: راعِ مستوى اللغة والسياق العمري دون الجزم بالملاءمة.' )
    return ('أنت مستشار كتابة عربي متخصص. اسأل عند الغموض، قدّم ملاحظات محددة واقتراحات بيانات تنظيمية فقط. '
      'ممنوع كتابة قصة أو فصل أو مشهد أو حوار أو إعادة صياغة نص أدبي نيابة عن المؤلف، حتى إن طلب ذلك؛ بدلا منها اطرح أسئلة تدريبية ونقاط مراجعة. '
      'لا تدّع الاطلاع على أجزاء لم تُرسل. ميّز المؤكد والمحتمل. لا تعطِ درجة جودة رقمية. '
      'لا تضع محتوى مخطوط في suggestions. الرد باللغة العربية. ' + unit)

async def analyze(kind,message,context, history):
    key=os.getenv('OPENAI_API_KEY','')
    if not key: raise HTTPException(503,'الاتصال الذكي غير مفعّل على الخادم')
    model=os.getenv('OPENAI_MODEL','gpt-4.1-mini')
    messages=[]
    for x in history[-8:]:
        if x['role'] in ('user','assistant'):
            messages.append({'role':x['role'],'content':x['text'][:2400]})
    messages.append({'role':'user','content':'سياق وافق الكاتب على مشاركته:\n'+context[:10000]+'\nسؤال الكاتب:\n'+message[:4000]})
    payload={'model':model,'instructions':instruction(kind),'input':messages,'text':{'format':{'type':'json_schema','name':'writer_assistant','strict':True,'schema':SCHEMA}},'max_output_tokens':900,'store':False}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r=await client.post('https://api.openai.com/v1/responses',json=payload,headers={'Authorization':'Bearer '+key})
        if r.status_code!=200: raise HTTPException(502,'تعذر الحصول على رد من مزود الذكاء الاصطناعي')
        obj=r.json()
        text=''.join(c.get('text','') for out in obj.get('output',[]) if out.get('type')=='message' for c in out.get('content',[]) if c.get('type')=='output_text')
        data=json.loads(text)
        if not isinstance(data.get('reply'),str) or not isinstance(data.get('questions'),list) or not isinstance(data.get('suggestions'),list): raise ValueError('shape')
        return {'reply':data['reply'][:6000], 'questions':[str(q)[:300] for q in data['questions'][:4]],'suggestions':[s for s in data['suggestions'][:6] if isinstance(s,dict) and s.get('field') in {'premise','genre','theme','protagonist','goal','obstacle','audience','logline','next_step'} and isinstance(s.get('value'),str)]}
    except HTTPException: raise
    except (httpx.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError): raise HTTPException(502,'تعذر تحليل رد مزود الذكاء الاصطناعي')
