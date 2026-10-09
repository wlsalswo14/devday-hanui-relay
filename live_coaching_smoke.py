"""Actual Luna High: clinician context -> assistant question -> patient answer."""
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from care import KST
from server import App, ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    started=time.monotonic()
    fixture=json.loads((ROOT/"data"/"showcase.seed.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        app=App(Path(directory),ROOT/"data"/"knowledge.seed.json")
        sid=app.store.create_session()["id"]
        app.care_action(sid,"guidance",{"text":fixture["instructions"],"assessment":fixture["clinician_assessment"],"author":"합성 시연 한의사","starts_on":(datetime.now(KST).date()-timedelta(days=1)).isoformat(),"start_conversation":True,"mode":"codex"})
        before=app.store.get_session(sid)
        assert [m["role"] for m in before["messages"]]==["assistant"]
        assert "?" in before["messages"][0]["content"]
        assert not before["care"]["guidance"]["observations"] and not before["memories"]
        assert app.store.guidance.report(sid)["recorded_days"]==0
        def assert_classical(message):
            classical=[s for s in message["sources"] if s["category"]=="classical"]
            assert classical
            for source in classical:
                assert source["citations"]
                for citation in source["citations"]:
                    assert citation["reading"] and citation["reading_origin"]=="luna"
                    assert source["body"][citation["offset_start"]:citation["offset_end"]]==citation["quote"]
        assert_classical(before["messages"][0])
        session=app.chat(sid,{"message":"어제 새벽 1시에 잤어. 어제 5시간 잤어.","mode":"codex"})
        assert [m["role"] for m in session["messages"]]==["assistant","user","assistant"]
        observations=session["care"]["guidance"]["observations"]
        bedtime=next(o for o in observations if o["metric"]=="bedtime")
        assert bedtime["value"]==60
        patient=session["messages"][1]
        assert all(patient["content"][o["offset_start"]:o["offset_end"]]==o["quote"] for o in observations)
        assert "지침과 차이" in session["messages"][-1]["content"]
        assert app.store.get_session(sid)["messages"]==session["messages"]
        assert_classical(session["messages"][-1])
        result={"model":"gpt-6-luna","effort":"high","provider":"openai","elapsed_seconds":round(time.monotonic()-started,1),"opening":before["messages"][0]["content"],"patient":patient["content"],"reply":session["messages"][-1]["content"],"observations":observations}
    (ROOT/".runtime"/"coaching-live-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="observations"},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
