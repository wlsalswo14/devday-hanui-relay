"""Prepare a synthetic clinician case with a REAL Luna first question, no patient reply."""
import json
import sys
from datetime import datetime, timedelta
from server import App, ROOT
from care import KST


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    case=json.loads((ROOT/"data"/"showcase.seed.json").read_text(encoding="utf-8"))
    app=App()
    sid=app.store.create_session()["id"]
    app.store.rename_session(sid,"합성 데모 · Hanui의 첫 질문에 답하기")
    try:
        app.care_action(sid,"guidance",{"text":case["instructions"],"assessment":case["clinician_assessment"],"author":"합성 시연 한의사","starts_on":(datetime.now(KST).date()-timedelta(days=1)).isoformat(),"start_conversation":True,"mode":"codex"})
    except Exception:
        app.store.delete_session(sid)
        raise
    session=app.store.get_session(sid)
    assert [m["role"] for m in session["messages"]]==["assistant"]
    result={"synthetic_clinician":True,"actual_luna_opening":True,"model":"gpt-6-luna","effort":"high","provider":"openai","session_id":sid,"url":f"http://127.0.0.1:8765/?session={sid}","question":session["messages"][0]["content"]}
    (ROOT/".runtime"/"coaching-entry.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
