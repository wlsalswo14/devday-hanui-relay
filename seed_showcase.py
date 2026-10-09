"""Prepare two explicitly synthetic, complete demo stories in the real SQLite app.

The classical passages are actual stored sources; patients, clinics and bookings
are fictional fixtures. Does not call AI/search or alter existing conversations.
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from care import KST
from codex_bridge import validate_result
from store import Store

ROOT=Path(__file__).resolve().parent


def cited_classics(store):
    records=store.library(category="classical")
    prepared=json.loads((ROOT/"data"/"showcase.seed.json").read_text(encoding="utf-8")).get("classical_readings",{})
    selected=[]
    for choices in [("食飲有節，起居有常", "飮食有節，起居有常"),("不治已病治未病", "不治已病，治未病", "治未病")]:
        found=next(((r,q) for r in records for q in choices if q in r["body"] and r["id"] not in {s["id"] for s in selected}),None)
        if not found:raise ValueError("시연할 실제 고문헌 원문을 DB에서 찾지 못했어요.")
        record,quote=found
        reading=next((c for c in prepared.get("citations",[]) if c["source_id"]==record["id"] and c["quote"]==quote),None)
        candidate={"source_id":record["id"],"quote":quote}
        if reading:candidate["reading"]=reading["reading"]
        citation=validate_result({"reply":"실제 DB 원문 인용의 합성 시연", "source_ids":[record["id"]], "memories":[], "actions":[], "citations":[candidate]},"고문헌 시연",[record])["citations"]
        if reading and (prepared.get("model"),prepared.get("effort"),prepared.get("provider"))==("gpt-6-luna","high","openai"):
            citation[0]["reading_origin"]="luna"
        selected.append({**record,"citations":citation})
    return selected


def add_report(store,sid,day,clauses,values,diet_id,followup=""):
    message=f"[합성 환자 발언 · 실제 자료 아님]\n{day} 생활 기록이야.\n"+". ".join(clauses)+"."
    candidates=[{"metric":metric,"quote":quote,"value":str(value),"date":day,"instruction_id":diet_id if metric=="adherence" else ""} for quote,(metric,value) in zip(clauses,values)]
    observations=store.guidance.validate(sid,message,candidates)
    categories={"sleep_hours":"sleep","diet_note":"diet","symptom":"symptom"}
    memories=[{"category":categories[metric],"summary":f"{day} · {clause}","quote":clause} for clause,(metric,_) in zip(clauses,values) if metric in categories]
    store.save_turn(sid,message,followup or "합성 시연: 지침에 비춰 생활 발언을 기록했어요.",[],memories,"demo",observations=observations)


def build_showcase(store,end=None):
    end=end or datetime.now(KST).date()
    data=json.loads((ROOT/"data"/"showcase.seed.json").read_text(encoding="utf-8"))
    assert data["synthetic_only"] is True
    with store.connect():
        sid=store.create_session()["id"]
        store.rename_session(sid,"합성 데모 A · 한의사 진단에서 먼저 묻는 Hanui")
        store.guidance.create(sid,{"text":data["instructions"],"assessment":data["clinician_assessment"],"author":"시연 한의사 · 합성 지침","starts_on":(end-timedelta(days=13)).isoformat()})
        plan=store.guidance.dashboard(sid)["plans"][-1]
        opening_id=store.guidance.opening(sid,plan["id"],data["opening_question"],"demo")
        diet=next(i for i in store.guidance.dashboard(sid)["instructions"] if i["category"]=="diet")
        for index,item in enumerate(data["days"]):
            day=(end-timedelta(days=item["ago"])).isoformat();met=item["met"]
            walk=15 if met else 5;coffee=1 if met else 2
            clauses=["밤 10시 30분에 잤어" if met else "새벽 1시에 잤어",f"커피 {coffee}잔 마셨어",f"점심 후 {walk}분 산책했어","찬 음식 줄였어" if met else "찬 음식 줄이지 못했어",f"{item['sleep']}시간 잤어",item["meal"],item["symptom"]]
            values=[("bedtime","22:30" if met else "01:00"),("caffeine_cups",coffee),("walk_after_lunch_minutes",walk),("adherence","done" if met else "not_done"),("sleep_hours",item["sleep"]),("diet_note",""),("symptom","")]
            # The check-in scales are explicit fictional self-reports, not inferred scores.
            extra=f"스트레스는 10점 중 {item['stress']}점, 활력은 10점 중 {item['energy']}점, 불편감은 10점 중 {item['discomfort']}점이야"
            if index==0:
                add_report(store,sid,day,[clauses[0],clauses[4]],[values[0],values[4]],diet["id"],"커피는 어제 몇 잔 마셨어요?")
                indices=[1,2,3,5,6]
                add_report(store,sid,day,[clauses[i] for i in indices]+[extra],[values[i] for i in indices],diet["id"])
            else:
                add_report(store,sid,day,clauses+[extra],values,diet["id"])
            store.care.checkin(sid,{"date":day,"sleep":item["sleep"],"caffeine":coffee,"activity":walk,"stress":item["stress"],"energy":item["energy"],"discomfort":item["discomfort"],"note":"합성 시연 체크인 · 위 날짜의 합성 대화에 적힌 직접 보고 수치"})
        classics=cited_classics(store)
        store.save_turn(sid,"[합성 시연 질문] 생활 관리와 미병에 관한 고문헌 DB 문장을 찾아줘.","DB에 있는 실제 원문 두 곳을 연결했어요. 식사·일상의 규칙성과 미병에 관한 역사적 기록이며, 개인 지침은 입력한 한의사 지침을 기준으로 관리해요.",classics,[],"demo")
        hospitals=[{"id":uuid.uuid4().hex,"name":h["name"],"address":h["address"],"reason":h["reason"],"phone":"02-000-0000","website":"","booking_url":f"https://example.org/hanui-demo/{h['key']}/booking","source_url":f"https://example.org/hanui-demo/{h['key']}","reviews":[{"kind":"clinic_info","summary":"합성 공개 안내 예시 · 실제 후기·검색 결과가 아닙니다.","url":"https://example.org/hanui-demo/information"}]} for h in data["hospitals"]]
        found={"query":"합성 지역의 생활 상담 한의원 시연","summary":data["label"],"searched_at":datetime.now(KST).isoformat(),"hospitals":hospitals,"results":[]}
        search_id=store.care.save_search(sid,"hospitals",found)
        desired=datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=KST).replace(hour=18,minute=30)
        care=store.care.booking(sid,{"search_id":search_id,"hospital_id":hospitals[0]["id"],"start":desired.isoformat(),"note":"합성 방문 준비 · 2주 리포트와 지침 원문을 보여주고, 남아 있는 더부룩함과 최근 식사 기록을 설명하기. 실제 접수 없음."})
        store.care.booking(sid,{"search_id":search_id,"hospital_id":hospitals[1]["id"],"start":(desired+timedelta(days=3)).isoformat(),"note":"합성 예약 상태 시연 · 실제 병원 접수 없음."})
        confirmation=next(b for b in store.care.dashboard(sid)["bookings"] if b["hospital"]["id"]==hospitals[1]["id"])
        store.care.booking_status(sid,confirmation["id"],{"status":"confirmed","confirmed_by_user":True,"confirmation":"합성 확정 상태 예시 · 실제 예약 확정이 아님"})
        for offset in range(5):
            day=end+timedelta(days=offset)
            start=datetime.combine(day,datetime.min.time(),tzinfo=KST).replace(hour=12,minute=40)
            store.care.event(sid,{"title":"점심 후 산책 · 합성", "start":start.isoformat(),"end":(start+timedelta(minutes=15)).isoformat(),"note":"합성 생활 일정 · 점심 후 산책 지침의 다음 실천"})
        store.care.event(sid,{"title":"리포트 확인·방문 준비 · 합성","start":(desired-timedelta(hours=1)).isoformat(),"end":(desired-timedelta(minutes=45)).isoformat(),"note":"합성 준비 일정 · 지침 원문, 누락 날짜, 수면·식사 발언을 확인"})
        actions=[{"type":"hospitals","label":"합성 병원 카드","completed":True,"search_id":search_id,"result":found},{"type":"records","label":"내원 전 리포트 보기"},{"type":"calendar","label":"자체 캘린더·방문 준비 보기"}]
        store.save_turn(sid,"[합성 시연 질문] 지금까지의 생활기록과 자료를 내원 준비로 연결해줘.","8일 기록 · 지침 실천율 75%\n리포트와 방문 준비를 확인해 보세요. 병원·예약은 합성 예시예요.",classics,[],"demo",actions=actions)
        other=store.create_session()["id"]
        store.rename_session(other,"합성 데모 B · 기록 없음·상충")
        store.guidance.create(other,{"text":"취침 23시 전, 커피 1잔 이하","author":"시연 한의사 · 합성 지침","starts_on":(end-timedelta(days=13)).isoformat()})
        for ago,count in [(3,2),(0,1),(0,3)]:
            day=(end-timedelta(days=ago)).isoformat()
            add_report(store,other,day,[f"커피 {count}잔 마셨어"],[("caffeine_cups",count)],"")
        store.save_turn(other,"[합성 시연 질문] 기록이 비거나 같은 날 서로 다르면 어떻게 정리해?","합성 시연: 취침 기록은 없어 판정하지 않았어요. 커피는 같은 날짜에 1잔과 3잔 발언이 있어 상충으로 보류해요. 기록 없는 날짜를 실패로 채우지 않고, 근거를 확인해 잘못된 기록을 제외할 수 있어요.",[],[],"demo",actions=[{"type":"records","label":"기록 없음·상충 리포트 보기"}])
        report=store.guidance.report(sid,end.isoformat())
        assert (report["recorded_days"],report["missing_days"])==(8,6)
        assert all(row["rate"]==75 for row in report["instructions"])
    return {"synthetic_only":True,"version":2,"date":end.isoformat(),"primary_session_id":sid,"secondary_session_id":other,"opening_message_id":opening_id,"opening_url":f"http://127.0.0.1:8765/?session={sid}&message={opening_id}","primary_url":f"http://127.0.0.1:8765/?session={sid}","secondary_url":f"http://127.0.0.1:8765/?session={other}","counts":{"recorded_days":8,"missing_days":6,"adherence_percent":75,"hospital_cards":3,"checkins":8,"calendar_events":7,"prepared_bookings":1,"synthetic_confirmed_bookings":1,"classical_citations":2}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--new",action="store_true",help="Create new examples even if today's showcase already exists")
    args=parser.parse_args();store=Store(ROOT/".runtime"/"hanui.sqlite3",ROOT/"data"/"knowledge.seed.json")
    target=ROOT/".runtime"/"showcase-demo.json"
    existing=json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
    if existing and not args.new and existing.get("version")==2 and existing.get("date")==datetime.now(KST).date().isoformat():
        try:
            store.get_session(existing["primary_session_id"]);store.get_session(existing["secondary_session_id"])
            print(json.dumps(existing,ensure_ascii=False,indent=2));return
        except KeyError:pass
    result=build_showcase(store)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
