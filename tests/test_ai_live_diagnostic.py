"""Synthetic inference probe must never read production data or write prompts to logs."""
import asyncio
from app import ai_live_diagnostic as diag
from app import writer_intelligence as wi
from app import provider_gateway as gw

def test_synthetic_probe_runs_only_fake_corpus(monkeypatch,capsys):
    calls=[]
    async def mocked(kind,scope,text):
        calls.append((kind,scope,text))
        return {'feedback':[{'evidence':'قال سامر صراحة إنه يبلغ اثنين وثلاثين عامًا'}]
                if 'سامر' in text else []}
    monkeypatch.setattr(wi,'generate_analysis',mocked)
    monkeypatch.setattr(gw,'configured',lambda: True)
    monkeypatch.setattr(gw,'selection',lambda:('groq','openai/gpt-oss-20b','not_logged'))
    async def no_sleep(_):return None
    monkeypatch.setattr(diag.asyncio,'sleep',no_sleep)
    asyncio.run(diag.evaluate_live_synthetic())
    printed=capsys.readouterr().out
    assert len(calls)==3
    assert all(kind in ('novel','short') and scope=='critique' for kind,scope,_ in calls)
    assert all('مخطوط كاتب' not in text for _,_,text in calls)
    assert 'not_logged' not in printed
    assert 'في صباح الإثنين' not in printed
    assert 'completed_no_author_content_access' in printed

def test_no_probe_if_disabled(monkeypatch,capsys):
    monkeypatch.setattr(gw,'configured',lambda:False)
    asyncio.run(diag.evaluate_live_synthetic())
    assert 'disabled_or_unconfigured' in capsys.readouterr().out
