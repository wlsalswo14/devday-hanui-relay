"""Create an explicitly synthetic, separate 14-day report demo conversation.

No model call, patient data, hospital booking, or existing conversation changes.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from care import KST
from store import Store


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    root=Path(__file__).resolve().parent
    store=Store(root/".runtime"/"hanui.sqlite3",root/"data"/"knowledge.seed.json")
    sid=store.create_session()["id"]
    store.rename_session(sid,"합성 데모 · 2주 지침 관리")
    end=datetime.now(KST).date()
    store.guidance.create(sid,{"text":"취침 23시 전, 찬 음식 줄이기, 커피 1잔 이하, 점심 후 산책 10분","author":"합성 데모 지침 · 실제 의사 지시 아님","starts_on":(end-timedelta(days=13)).isoformat()})
    diet=next(i for i in store.guidance.dashboard(sid)["instructions"] if i["category"]=="diet")
    for index,ago in enumerate([13,12,11,10,6,5,1,0]):
        day=(end-timedelta(days=ago)).isoformat();met=index<6
        clauses=[f"{day} {'밤 10시' if met else '새벽 1시'}에 잤어",f"{day} 커피 {1 if met else 2}잔 마셨어",f"{day} 점심 후 {15 if met else 5}분 산책했어",f"{day} 찬 음식 {'줄였어' if met else '줄이지 못했어'}",f"{day} {6.5 if met else 5}시간 잤어",f"{day} 아침 먹었어",f"{day} 속이 더부룩했어"]
        values=[("bedtime","22:00" if met else "01:00"),("caffeine_cups","1" if met else "2"),("walk_after_lunch_minutes","15" if met else "5"),("adherence","done" if met else "not_done"),("sleep_hours","6.5" if met else "5"),("diet_note",""),("symptom","")]
        message="[합성 데모 발언 · 실제 환자 자료 아님] "+". ".join(clauses)
        candidates=[{"metric":metric,"value":value,"quote":quote,"date":day,"instruction_id":diet["id"] if metric=="adherence" else ""} for quote,(metric,value) in zip(clauses,values)]
        observations=store.guidance.validate(sid,message,candidates)
        store.save_turn(sid,message,"합성 데모 기록",[],[],"demo",observations=observations)
    report=store.guidance.report(sid)
    assert (report["recorded_days"],report["missing_days"])==(8,6)
    assert all(r["rate"]==75 for r in report["instructions"])
    result={"synthetic_only":True,"session_id":sid,"url":f"http://127.0.0.1:8765/?session={sid}","recorded_days":8,"missing_days":6,"adherence_percent":75}
    (root/".runtime"/"guidance-demo.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
