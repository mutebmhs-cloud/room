"""Arabic literary fault-injection evaluation against the EXACT application analysis adapter.

A real evaluation REQUIRES an API key and bills that provider; without a key it
exits nonzero and explicitly marks the experiment NOT EXECUTED. All texts are
synthetic and safe to share. The heuristic score is diagnostic, not a quality certification.
"""
import asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.writer_intelligence import generate_analysis

FIXTURE=Path(__file__).resolve().parents[1]/"tests/fixtures/literary_fault_cases.json"

async def run():
    data=json.loads(FIXTURE.read_text(encoding="utf8"))
    if not os.getenv("OPENAI_API_KEY"):
        print("NOT_RUN: OPENAI_API_KEY not configured. No literary defect detection has been verified.")
        return 2
    rows=[]
    for case in data["cases"]:
        started=time.monotonic()
        try:
            result=await generate_analysis(case["kind"],"critique",case["text"])
            feedback=result.get("feedback",[])
            grounded=[x for x in feedback if x.get("evidence","").strip() and x["evidence"].strip() in case["text"]]
            corpus=" ".join(" ".join(str(x.get(k,"")) for k in ("observation","impact","action")) for x in grounded).lower()
            has_signal=bool(grounded) and (
                not case["expected"] or any(term.lower() in corpus for term in case["expected"])
            )
            detected=has_signal if not case["clean"] else None
            false_alarm=bool(grounded) if case["clean"] else None
            rows.append({"id":case["id"],"kind":case["kind"],"clean":case["clean"],
              "fault":case["fault"],"detected":detected,"false_alarm":false_alarm,
              "feedback":grounded,"latency_seconds":round(time.monotonic()-started,2),"error":None})
            print(case["id"]+": "+("POTENTIAL DETECTION" if detected else "NO DETECTION / CLEAN CASE"))
        except Exception as exc:
            rows.append({"id":case["id"],"kind":case["kind"],"clean":case["clean"],
              "fault":case["fault"],"detected":None,"false_alarm":None,
              "feedback":[],"error":type(exc).__name__+" "+str(exc)[:180]})
            print(case["id"]+": ERROR "+type(exc).__name__)
    faults=[x for x in rows if not x["clean"]]
    controls=[x for x in rows if x["clean"]]
    hits=sum(x["detected"] is True for x in faults)
    false_alarms=sum(x["false_alarm"] is True for x in controls)
    report={"evaluation":"diagnostic_heuristics_requires_human_judgment",
      "faults":len(faults),"potential_hits":hits,"clean_controls":len(controls),
      "flagged_controls":false_alarms,"model":os.getenv("OPENAI_MODEL","gpt-4.1-mini"),
      "results":rows}
    dest=Path(os.getenv("WRITER_EVAL_OUTPUT","/tmp/writer-fault-evaluation.json"))
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print("REPORT "+str(dest)+"; detection cannot be certified until human reviews the reasons.")
    return 0 if len(rows)==len(data["cases"]) and all(x["error"] is None for x in rows) else 1

if __name__=="__main__":
    raise SystemExit(asyncio.run(run()))
