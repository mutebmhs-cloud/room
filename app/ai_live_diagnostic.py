"""Opt-in one-time synthetic inference diagnostic in the deployed runtime.

This deliberately does NOT read author projects or secrets, log prompts, log
model responses, or create new accounts. Controlled by a temporary env flag.
"""
import asyncio
import json
from pathlib import Path
from fastapi import HTTPException

CASES=("novel-age","novel-knowledge","novel-clean")

async def evaluate_live_synthetic():
    from .writer_intelligence import generate_analysis
    from .provider_gateway import configured, selection
    if not configured():
        print("WRITER_AI_LIVE_DIAG disabled_or_unconfigured",flush=True)
        return
    provider,model,_=selection()
    print("WRITER_AI_LIVE_DIAG started provider="+provider+
          " model="+model+" cases="+str(len(CASES)),flush=True)
    fixture=Path(__file__).parents[1]/"tests"/"fixtures"/"literary_fault_cases.json"
    dataset=json.loads(fixture.read_text(encoding="utf-8"))
    indexed={row["id"]:row for row in dataset["cases"]}
    for case_id in CASES:
        case=indexed[case_id]
        try:
            result=await generate_analysis(case["kind"],"critique",case["text"])
            feedback=result.get("feedback",[])
            grounded=[x for x in feedback if isinstance(x,dict)
                and isinstance(x.get("evidence"),str)
                and bool(x["evidence"].strip())
                and x["evidence"].strip() in case["text"]]
            print("WRITER_AI_LIVE_DIAG case="+case_id+
                  " response_valid=true cited="+str(len(grounded))+
                  " total="+str(len(feedback))+
                  " expected_clean="+str(bool(case["clean"])).lower(),
                  flush=True)
        except HTTPException as exc:
            print("WRITER_AI_LIVE_DIAG case="+case_id+
                  " response_valid=false http_status="+str(exc.status_code),
                  flush=True)
        except Exception as exc:
            print("WRITER_AI_LIVE_DIAG case="+case_id+
                  " response_valid=false error_kind="+type(exc).__name__,
                  flush=True)
        await asyncio.sleep(1)
    print("WRITER_AI_LIVE_DIAG completed_no_author_content_access",flush=True)
