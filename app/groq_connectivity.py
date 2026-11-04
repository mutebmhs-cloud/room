"""One-time opt-in connectivity check for the actual Groq key stored on Render.

The key never leaves HTTPS request headers and is never printed. Only synthetic
fixed strings are sent. No writer content, database or files are accessed.
"""
import asyncio
import httpx
from .provider_gateway import selection

async def check_groq_connection():
    provider,model,key=selection()
    if provider!="groq" or not key:
        print("WRITER_GROQ_NET skipped_not_configured",flush=True)
        return
    timeout=httpx.Timeout(timeout=10.0,connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout,trust_env=True) as client:
            response=await asyncio.wait_for(client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization":"Bearer "+key}),timeout=12.0)
        print("WRITER_GROQ_NET auth_http="+str(response.status_code),flush=True)
    except asyncio.TimeoutError:
        print("WRITER_GROQ_NET auth_timeout",flush=True)
        return
    except httpx.HTTPError as exc:
        print("WRITER_GROQ_NET auth_network_error="+type(exc).__name__,flush=True)
        return
    if response.status_code!=200:return
    try:
        async with httpx.AsyncClient(timeout=timeout,trust_env=True) as client:
            response=await asyncio.wait_for(client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":"Bearer "+key},
                json={"model":model,
                      "messages":[
                        {"role":"system","content":"أجب بكلمة عربية واحدة فقط."},
                        {"role":"user","content":"ما لغة هذه الجملة: هذا اختبار مصطنع."}],
                      "max_completion_tokens":300,"reasoning_effort":"low","stream":False}),timeout=16.0)
        ok=False
        if response.status_code==200:
            data=response.json()
            ok=bool(data.get("choices",[{}])[0].get("message",{}).get("content"))
        print("WRITER_GROQ_NET chat_http="+str(response.status_code)+
              " has_text="+str(ok).lower(),flush=True)
    except asyncio.TimeoutError:
        print("WRITER_GROQ_NET chat_timeout",flush=True)
    except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:
        print("WRITER_GROQ_NET chat_error="+type(exc).__name__,flush=True)
