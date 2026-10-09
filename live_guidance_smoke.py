"""Real OpenAI Luna High, isolated synthetic guidance, no real patient data."""
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from care import KST
from server import App, ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8");started=time.monotonic();checks=[]
    with tempfile.TemporaryDirectory() as temporary:
        app=App(Path(temporary),ROOT/"data"/"knowledge.seed.json")
        assert app.codex_enabled
        sid=app.store.create_session()["id"]
        app.store.guidance.create(sid,{"text":"취침 23시 전, 찬 음식 줄이기, 커피 1잔 이하, 점심 후 산책 10분","author":"합성 테스트 한의사","starts_on":(datetime.now(KST).date()-timedelta(days=13)).isoformat()})
        for message,metrics in [
            ("어제 새벽 1시에 잤어. 어제 커피 두 잔 마셨어.",{"bedtime","caffeine_cups"}),
            ("오늘 점심 후 15분 산책했어. 오늘 찬 음식 줄였어.",{"walk_after_lunch_minutes","adherence"}),
            ("오늘 6.5시간 잤어. 오늘 속이 더부룩했어.",{"sleep_hours","symptom"}),
        ]:
            result=app.chat(sid,{"message":message,"mode":"codex"})
            fresh=result["messages"][-1]["patient_evidence"]
            assert metrics<={o["metric"] for o in fresh}, [(o["metric"],o["quote"]) for o in fresh]
            assert all(o["quote"]==o["content"][o["offset_start"]:o["offset_end"]] for o in fresh)
            checks.append({"message":message,"metrics":[o["metric"] for o in fresh]})
            print("PASS: "+message,flush=True)
        before=len(app.store.guidance.observations(sid))
        app.chat(sid,{"message":"만약 내일 새벽 1시에 자면 지침을 못 지키는 건가?","mode":"codex"})
        assert len(app.store.guidance.observations(sid))==before
        report=app.store.guidance.report(sid)
        assert report["recorded_days"]==2 and report["missing_days"]==12
        assert report["symptoms"]
        other=app.store.create_session()["id"]
        assert not app.store.guidance.report(other)["evidence"]
    report={"provider":"OpenAI Codex · gpt-6-luna · high","synthetic_only":True,"elapsed_seconds":round(time.monotonic()-started,1),"checks":checks,"hypothetical_no_record":True,"session_isolation":True,"recorded_days":2,"missing_days":12}
    (ROOT/".runtime"/"guidance-live-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
