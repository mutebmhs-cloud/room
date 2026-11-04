import asyncio
from app import groq_connectivity as net

def test_groq_connectivity_diagnostic_has_no_secrets_in_logs(monkeypatch,capsys):
    monkeypatch.setattr(net,"selection",lambda:("groq","openai/gpt-oss-20b","PRIVATE_KEY_MUST_NOT_APPEAR"))
    class Response:
        status_code=200
        def __init__(self,is_chat):self.is_chat=is_chat
        def json(self):
            return {"choices":[{"message":{"content":"العربية"}}]} if self.is_chat else {"data":[]}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def get(self,url,**kwargs):
            assert kwargs["headers"]["Authorization"].endswith("PRIVATE_KEY_MUST_NOT_APPEAR")
            return Response(False)
        async def post(self,url,**kwargs):
            assert kwargs["json"]["messages"][1]["content"].startswith("ما لغة")
            return Response(True)
    monkeypatch.setattr(net.httpx,"AsyncClient",Client)
    asyncio.run(net.check_groq_connection())
    output=capsys.readouterr().out
    assert "auth_http=200" in output
    assert "chat_http=200 has_text=true" in output
    assert "PRIVATE_KEY_MUST_NOT_APPEAR" not in output
