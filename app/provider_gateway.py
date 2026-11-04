"""Single-provider AI gateway with strict free-model allowlists.

No paid fallback, no cross-provider disclosure, no hidden retries. Model routing
is selected explicitly by the operator, and manuscript access requires the
existing per-request author consent in the calling API.
"""
import os
import json
import httpx
from fastapi import HTTPException

GROQ_ALLOWED=frozenset({'openai/gpt-oss-20b','openai/gpt-oss-120b'})
OPENROUTER_ALLOWED_PREFIXES=()  # Explicit :free suffix required, no auto router.
def selection():
    provider=os.getenv('WRITER_AI_PROVIDER','openai').lower().strip()
    if provider=='openai':
        key=os.getenv('OPENAI_API_KEY','')
        return ('openai',os.getenv('OPENAI_MODEL','gpt-4.1-mini'),key)
    if provider=='groq':
        model=os.getenv('GROQ_FREE_MODEL','openai/gpt-oss-20b')
        if model not in GROQ_ALLOWED: return (provider,model,'')
        return (provider,model,os.getenv('GROQ_API_KEY',''))
    if provider=='openrouter':
        model=os.getenv('OPENROUTER_FREE_MODEL','')
        if (not model.endswith(':free') or model=='openrouter/free'
            or model.count('/')!=1 or len(model)>120):
            return (provider,model,'')
        return (provider,model,os.getenv('OPENROUTER_API_KEY',''))
    return ('disabled','', '')

def configured():
    return bool(selection()[2]) and os.getenv('PILOT_EPHEMERAL')!='1'

def label():
    provider,model,key=selection()
    return {'available':bool(key) and os.getenv('PILOT_EPHEMERAL')!='1',
            'provider':provider if key else None,'paid_fallback':False,
            'mode':'free_only' if provider in ('groq','openrouter') else 'direct'}

async def json_completion(instructions,messages,schema,max_tokens=1800):
    provider,model,key=selection()
    if not key or os.getenv('PILOT_EPHEMERAL')=='1':
        raise HTTPException(503,'الاتصال الذكي غير مفعّل؛ لا يمكن ادعاء تنفيذ التحليل')
    if sum(len(str(m.get('content',''))) for m in messages)+len(instructions)>22000:
        raise HTTPException(413,'السياق أكبر من الحد المسموح للتحليل الحالي')
    if provider=='openai':
        payload={'model':model,'instructions':instructions,'input':messages,
           'text':{'format':{'type':'json_schema','name':'writer_json_result',
                            'strict':True,'schema':schema}},
           'max_output_tokens':max_tokens,'store':False}
        url='https://api.openai.com/v1/responses'
    else:
        # OpenAI-compatible JSON message API, constrained by a validated schema
        # in application code after provider processing.
        payload={'model':model,
           'messages':[{'role':'system','content':instructions+'\nأعد JSON صالحًا فقط.'},*messages],
           'response_format':{'type':'json_object'},
           'max_tokens':max_tokens,'stream':False}
        if provider=='groq':
            # GPT-OSS consumes reasoning tokens before producing user-visible
            # output. Keep reasoning bounded and require exact schema adherence.
            payload['reasoning_effort']='low'
            payload['response_format']={'type':'json_schema','json_schema':{
                'name':'writer_literary_response','strict':True,'schema':schema}}
            payload.pop('max_tokens',None)
            payload['max_completion_tokens']=max(2600,min(max_tokens+1200,4200))
        url=('https://api.groq.com/openai/v1/chat/completions' if provider=='groq'
             else 'https://openrouter.ai/api/v1/chat/completions')
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response=await client.post(url,json=payload,
                headers={'Authorization':'Bearer '+key})
        if response.status_code==429:
            raise HTTPException(429,'انتهت حصة التحليل الحالية؛ لا يتم التحويل تلقائيًا إلى مزود آخر')
        if response.status_code in (402,403):
            raise HTTPException(503,'الرصيد أو الأذونات غير متاحة؛ لم يتم تشغيل مزود مدفوع بديل')
        if response.status_code!=200:
            raise HTTPException(502,'تعذر الاتصال بالنموذج المحدد')
        data=response.json()
        if provider=='openai':
            raw=''.join(c.get('text','') for item in data.get('output',[])
                if item.get('type')=='message'
                for c in item.get('content',[]) if c.get('type')=='output_text')
        else:
            raw=data['choices'][0]['message']['content']
        result=json.loads(raw)
        if not isinstance(result,dict) or not all(k in result for k in schema['required']):
            raise ValueError('missing required keys')
        return result
    except HTTPException:
        raise
    except (httpx.HTTPError,ValueError,TypeError,KeyError,IndexError,json.JSONDecodeError):
        raise HTTPException(502,'تعذر التحقق من نتيجة التحليل؛ لم تُعدل بيانات المؤلف')
