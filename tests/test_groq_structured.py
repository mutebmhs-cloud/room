import asyncio
import json
import pytest
from app import provider_gateway as gateway

@pytest.mark.parametrize('effort',['low','medium','high'])
def test_groq_generation_has_strict_schema_and_reasoning_budget(monkeypatch,effort):
    monkeypatch.setenv("WRITER_AI_PROVIDER","groq")
    monkeypatch.setenv("GROQ_API_KEY","not-an-actual-key")
    monkeypatch.setenv("GROQ_FREE_MODEL","openai/gpt-oss-20b")
    monkeypatch.setenv("PILOT_EPHEMERAL","0")
    monkeypatch.setenv("GROQ_REASONING_EFFORT",effort)
    recorded=[]
    class Response:
        status_code=200
        def json(self):
            return {"choices":[{"message":{"content":json.dumps({"summary":"تم"})}}]}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def post(self,url,**kwargs):
            assert url=="https://api.groq.com/openai/v1/chat/completions"
            recorded.append(kwargs["json"])
            return Response()
    monkeypatch.setattr(gateway.httpx,"AsyncClient",Client)
    schema={"type":"object","additionalProperties":False,
            "properties":{"summary":{"type":"string"}},"required":["summary"]}
    result=asyncio.run(gateway.json_completion("أعد JSON فقط",
        [{"role":"user","content":"نص مصطنع"}],schema,max_tokens=1700))
    assert result["summary"]=="تم"
    payload=recorded[0]
    assert payload["reasoning_effort"]==effort
    assert payload["response_format"]["type"]=="json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["max_completion_tokens"]>=2600
    assert "max_tokens" not in payload
