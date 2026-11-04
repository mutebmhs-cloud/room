"""Optional live literary model evaluation using SYNTHETIC Arabic passages only.

Records bounded, non-sensitive diagnostics. Does not read author manuscripts.
A model response is NOT editorially certified by these heuristics.
"""
import asyncio
import json
import os
from pathlib import Path
from fastapi import HTTPException

CASES=("novel-age","novel-knowledge","novel-clean")

def chosen_cases(dataset):
    """Use three baseline cases unless a one-off comprehensive evaluation is requested."""
    if os.getenv("WRITER_AI_EVAL_ALL")=="1":
        return dataset["cases"]
    wanted=set(CASES)
    return [case for case in dataset["cases"] if case["id"] in wanted]

async def evaluate_live_synthetic():
    from .writer_intelligence import generate_analysis
    from .provider_gateway import configured, selection
    if not configured():
        print("WRITER_AI_LIVE_DIAG disabled_or_unconfigured",flush=True)
        return
    provider,model,_=selection()
    fixture=Path(__file__).parents[1]/"tests"/"fixtures"/"literary_fault_cases.json"
    try:
        dataset=json.loads(fixture.read_text(encoding="utf-8"))
        cases=chosen_cases(dataset)
    except (OSError,ValueError,KeyError,TypeError) as error:
        print("WRITER_AI_LIVE_DIAG setup_failed="+type(error).__name__,flush=True)
        return
    print("WRITER_AI_LIVE_DIAG started provider="+provider+
          " model="+model+" cases="+str(len(cases)),flush=True)
    success=faults_detected=flagged_clean=failed=0
    objective_clean_flags=0
    rate_limited=False
    # Throttle *synthetic* evaluations to avoid exhausting free-provider TPM.
    delay=max(0,min(30,int(os.getenv('WRITER_AI_EVAL_INTERVAL_SECONDS',
                                    '12' if len(cases)>3 else '2'))))
    for case in cases:
        try:
            result=await asyncio.wait_for(
                generate_analysis(case["kind"],"critique",case["text"]),timeout=45)
            feedback=result.get("feedback",[])
            grounded=[row for row in feedback if isinstance(row,dict)
                      and isinstance(row.get("evidence"),str)
                      and bool(row["evidence"].strip())
                      and row["evidence"].strip() in case["text"]]
            observations=" ".join(str(x.get("observation",""))+" "+
                                  str(x.get("impact","")) for x in grounded).lower()
            signal=bool(grounded) and any(
                token.lower() in observations for token in case.get("expected",[]))
            if case["clean"] and grounded:flagged_clean+=1
            if case["clean"] and any(x.get('classification')=='objective_candidate' for x in grounded):
                objective_clean_flags+=1
            if not case["clean"] and signal:faults_detected+=1
            success+=1
            counts=result.get("diagnostic_counts",{})
            print("WRITER_AI_LIVE_DIAG case="+case["id"]+
                  " response_valid=true grounded="+str(len(grounded))+
                  " model_feedback="+str(counts.get("model_feedback_count","unknown"))+
                  " objective="+str(sum(x.get('classification')=='objective_candidate' for x in grounded))+
                  " total="+str(len(feedback))+
                  " heuristic_signal="+str(signal).lower()+
                  " clean_control="+str(bool(case["clean"])).lower(),flush=True)
        except asyncio.TimeoutError:
            failed+=1
            print("WRITER_AI_LIVE_DIAG case="+case["id"]+
                  " response_valid=false error_kind=Timeout45s",flush=True)
        except HTTPException as error:
            failed+=1
            print("WRITER_AI_LIVE_DIAG case="+case["id"]+
                  " response_valid=false http_status="+str(error.status_code),flush=True)
            if error.status_code==429:
                rate_limited=True
                break
        except Exception as error:
            failed+=1
            print("WRITER_AI_LIVE_DIAG case="+case["id"]+
                  " response_valid=false error_kind="+type(error).__name__,flush=True)
        await asyncio.sleep(delay)
    print("WRITER_AI_LIVE_DIAG completed_no_author_content_access"
          " total="+str(len(cases))+" successful="+str(success)+
          " failed="+str(failed)+" rate_limited="+str(rate_limited).lower()+" potential_hits="+str(faults_detected)+
          " flagged_clean="+str(flagged_clean)+
          " objective_clean_flags="+str(objective_clean_flags)+
          " note=heuristics_not_human_certification",flush=True)
