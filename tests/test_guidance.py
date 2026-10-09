import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from care import KST, today
from codex_bridge import validate_result
from guidance import rule_for
from server import App, ROOT


class PatientModel:
    def __init__(self): self.observations=[]
    def available(self): return True
    def start_checkin(self,plan):
        self.plan=plan
        return "한의사 선생님의 생활 지침을 함께 살펴볼게요. 어젯밤에는 몇 시에 주무셨어요?"
    def respond(self,message,history,memories,sources):
        return validate_result({"reply":"합성 기록 처리", "source_ids":[], "memories":[], "actions":[], "citations":[], "observations":self.observations},message,sources)


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.model=PatientModel()
        self.app=App(Path(self.temp.name),ROOT/"data"/"knowledge.seed.json",self.model)
        self.sid=self.app.store.create_session()["id"];self.other=self.app.store.create_session()["id"]
        self.start=(datetime.now(KST).date()-timedelta(days=13)).isoformat()
        self.original="취침 23시 전, 찬 음식 줄이기, 커피 1잔 이하, 점심 후 산책 10분"
        self.app.care_action(self.sid,"guidance",{"text":self.original,"author":"합성 담당 한의사","starts_on":self.start})

    def tearDown(self): self.temp.cleanup()
    def day(self,ago=0): return (datetime.now(KST).date()-timedelta(days=ago)).isoformat()
    def item(self,metric,quote,value="",ago=0,instruction=""):
        return {"metric":metric,"quote":quote,"date":self.day(ago),"value":value,"instruction_id":instruction}
    def chat(self,message,*observations):
        self.model.observations=list(observations)
        return self.app.chat(self.sid,{"message":message,"mode":"codex"})
    def report(self):return self.app.store.guidance.report(self.sid)

    def test_original_and_four_personal_goals_survive_reload(self):
        session=self.app.store.get_session(self.sid)
        self.assertEqual(len(session["care"]["goals"]),4)
        for i in session["care"]["guidance"]["instructions"]:
            self.assertEqual(i["plan_text"][i["offset_start"]:i["offset_end"]],i["body"])
        self.assertEqual(self.app.store.get_session(self.other)["care"]["guidance"]["instructions"],[])

    def test_clinician_assessment_starts_assistant_without_patient_facts(self):
        self.app.care_action(self.other,"guidance",{"text":"취침 23시 전","assessment":"합성 한의사 진단: 수면 불규칙","start_conversation":True,"mode":"codex"})
        session=self.app.store.get_session(self.other)
        self.assertEqual([m["role"] for m in session["messages"]],["assistant"])
        self.assertIn("수면 불규칙",self.model.plan["assessment"])
        self.assertEqual(session["care"]["guidance"]["observations"],[])
        self.assertEqual(session["memories"],[])
        self.assertEqual(self.app.store.guidance.report(self.other)["recorded_days"],0)

    def test_opening_ownership_duplicate_and_persistence(self):
        self.app.care_action(self.other,"guidance",{"text":"취침 23시 전","assessment":"합성 평가","start_conversation":True,"mode":"codex"})
        plan=self.app.store.guidance.dashboard(self.other)["plans"][-1]
        self.assertEqual(self.app.store.guidance.opening(self.other,plan["id"],"중복 질문인가요?","codex"),plan["opening_message_id"])
        self.assertEqual(len(self.app.store.get_session(self.other)["messages"]),1)
        with self.assertRaises(ValueError):self.app.store.guidance.opening(self.sid,plan["id"],"다른 대화인가요?","codex")
        from store import Store
        restored=Store(self.app.store.path,ROOT/"data"/"knowledge.seed.json").get_session(self.other)
        self.assertEqual(restored["care"]["guidance"]["plans"][-1]["assessment"],"합성 평가")
        self.assertEqual(restored["messages"][0]["id"],plan["opening_message_id"])

    def test_opening_failure_rolls_back_plan_goals_and_message(self):
        self.model.start_checkin=lambda plan:"유효한 질문이 없는 결과"
        with self.assertRaises(ValueError):self.app.care_action(self.other,"guidance",{"text":"취침 23시 전","assessment":"합성 평가","start_conversation":True,"mode":"codex"})
        session=self.app.store.get_session(self.other)
        self.assertEqual(session["care"]["guidance"]["plans"],[])
        self.assertEqual(session["care"]["goals"],[])
        self.assertEqual(session["messages"],[])

    def test_demo_opening_is_explicitly_labelled_and_invalid_mode_is_atomic(self):
        self.app.care_action(self.other,"guidance",{"text":"취침 23시 전","start_conversation":True,"mode":"demo"})
        message=self.app.store.get_session(self.other)["messages"][0]
        self.assertEqual(message["mode"],"demo")
        self.assertIn("샘플 질문",message["content"])
        before=self.app.store.get_session(self.sid)
        with self.assertRaises(ValueError):self.app.care_action(self.sid,"guidance",{"text":"취침 23시 전","start_conversation":True,"mode":"other"})
        self.assertEqual(self.app.store.get_session(self.sid),before)

    def test_verified_coaching_keeps_one_followup_without_unverified_prose(self):
        self.model.respond=lambda message,history,memories,sources:validate_result({"reply":"추측한 평가 문장. 커피는 어제 몇 잔 마셨어요?","source_ids":[],"memories":[],"actions":[],"citations":[],"observations":[self.item("bedtime","어제 새벽 1시에 잤어","01:00",1)]},message,sources)
        result=self.app.chat(self.sid,{"message":"어제 새벽 1시에 잤어","mode":"codex"})
        reply=result["messages"][-1]["content"]
        self.assertIn("지침과 차이",reply)
        self.assertIn("커피는 어제 몇 잔 마셨어요?",reply)
        self.assertNotIn("추측한 평가",reply)

    def test_late_bedtime_and_coffee_compare_with_quote_and_previous_day(self):
        q="어제 새벽 1시에 잤어. 어제 커피 두 잔 마셨어"
        session=self.chat(q,self.item("bedtime","어제 새벽 1시에 잤어","01:00",1),self.item("caffeine_cups","어제 커피 두 잔 마셨어","2",1))
        self.assertIn("지침과 차이",session["messages"][-1]["content"])
        report=self.report()
        rows={r["instruction"]["rule"]["metric"]:r for r in report["instructions"]}
        self.assertEqual(rows["bedtime"]["counts"]["unmet"],1)
        self.assertEqual(rows["caffeine_cups"]["counts"]["unknown"],13)
        self.assertEqual(report["recorded_days"],1)
        for o in report["evidence"]:
            self.assertEqual(o["content"][o["offset_start"]:o["offset_end"]],o["quote"])
            self.assertEqual(o["day"],self.day(1))

    def test_six_of_eight_days_is_75_percent_and_six_unknown_not_failed(self):
        for ago in range(8):
            time="밤 10시" if ago<6 else "새벽 1시"
            q=f"{self.day(ago)} {time}에 잤어"
            self.chat(q,self.item("bedtime",q,"22:00" if ago<6 else "01:00",ago))
        row=next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="sleep")
        self.assertEqual((row["rate"],row["recorded"],row["assessed"],row["counts"]["unknown"]),(75.0,8,8,6))
        self.assertEqual(len(row["claim"]["evidence_ids"]),8)

    def test_mismatched_quote_quantity_and_date_fail_without_partial_turn(self):
        q="어제 커피 2잔 마셨어"
        for observation in [self.item("caffeine_cups","어제 커피 3잔 마셨어","3",1),self.item("caffeine_cups",q,"1",1),self.item("caffeine_cups",q,"2",0)]:
            with self.assertRaises(ValueError):self.chat(q,observation)
        self.assertEqual(self.app.store.get_session(self.sid)["messages"],[])
        self.assertEqual(self.report()["evidence"],[])

    def test_hypothetical_others_and_future_do_not_become_patient_facts(self):
        for q in ["만약 새벽 1시에 잤다면?", "내일 새벽 1시에 잘 거야", "친구가 어제 새벽 1시에 잤어"]:
            with self.assertRaises(ValueError):self.chat(q,self.item("bedtime",q,"01:00"))
        self.assertEqual(self.report()["recorded_days"],0)

    def test_ambiguous_hour_and_habitual_date_are_not_assessed(self):
        for q in ["어제 1시에 잤어", "요즘 새벽 1시에 잤어"]:
            with self.assertRaises(ValueError):self.chat(q,self.item("bedtime",q,"01:00",1 if "어제" in q else 0))

    def test_only_after_lunch_walk_matches_specific_instruction(self):
        q="오늘 20분 산책했어"
        self.chat(q,self.item("activity_minutes",q,"20"))
        row=next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="activity")
        self.assertEqual(row["counts"]["unknown"],14)
        q="오늘 점심 후 15분 산책했어"
        self.chat(q,self.item("walk_after_lunch_minutes",q,"15"))
        row=next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="activity")
        self.assertEqual(row["rate"],100)

    def test_qualitative_diet_is_explicit_self_report_not_inferred_food_failure(self):
        i=next(i for i in self.app.store.guidance.dashboard(self.sid)["instructions"] if i["category"]=="diet")
        q="오늘 찬 음식 줄였어"
        self.chat(q,self.item("adherence",q,"done",instruction=i["id"]),self.item("diet_note",q))
        self.assertEqual(next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="diet")["rate"],100)
        q="오늘 아이스크림 먹었어"
        with self.assertRaises(ValueError):self.chat(q,self.item("adherence",q,"not_done",instruction=i["id"]))

    def test_cross_session_instruction_and_unknown_reference_are_rejected(self):
        i=self.app.store.guidance.dashboard(self.sid)["instructions"][1]
        self.model.observations=[self.item("adherence","오늘 찬 음식 줄였어","done",instruction=i["id"])]
        with self.assertRaises(ValueError):self.app.chat(self.other,{"message":"오늘 찬 음식 줄였어","mode":"codex"})
        with self.assertRaises(KeyError):self.app.store.guidance.report("f"*32)

    def test_conflicting_same_day_reports_are_excluded_from_rate(self):
        for value in [1,2]:
            q=f"오늘 커피 {value}잔 마셨어"
            self.chat(q,self.item("caffeine_cups",q,str(value)))
        row=next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="caffeine")
        self.assertEqual((row["counts"]["conflict"],row["recorded"],row["assessed"],row["rate"]),(1,1,0,None))

    def test_pre_instruction_days_not_in_rate_denominator(self):
        other=self.app.store.create_session()["id"]
        self.app.store.guidance.create(other,{"text":"취침 23시 전"})
        row=self.app.store.guidance.report(other)["instructions"][0]
        self.assertEqual((row["eligible"],row["counts"]["inactive"],row["counts"]["unknown"]),(1,13,1))

    def test_goal_end_preserves_instruction_and_historical_evidence(self):
        q="어제 밤 10시에 잤어"
        self.chat(q,self.item("bedtime",q,"22:00",1))
        goal=self.app.store.get_session(self.sid)["care"]["goals"][0]
        self.app.care.delete(self.sid,"goals",goal["id"])
        row=self.report()["instructions"][0]
        self.assertEqual(row["rate"],100)
        self.assertFalse(row["instruction"]["active"])

    def test_corrupted_patient_quote_or_quantity_is_excluded(self):
        q="오늘 커피 2잔 마셨어"
        self.chat(q,self.item("caffeine_cups",q,"2"))
        with self.app.store.connect() as db:db.execute("UPDATE patient_observations SET value='1' WHERE session_id=?",(self.sid,))
        self.assertEqual(self.report()["evidence"],[])
        self.assertEqual(self.report()["missing_days"],14)

    def test_all_claims_reference_verified_patient_evidence_or_explicit_absence(self):
        q="오늘 6.5시간 잤어. 오늘 속이 더부룩했어. 오늘 아침 먹었어"
        self.chat(q,self.item("sleep_hours","오늘 6.5시간 잤어","6.5"),self.item("symptom","오늘 속이 더부룩했어"),self.item("diet_note","오늘 아침 먹었어"))
        report=self.report();ids={o["id"] for o in report["evidence"]}
        for claim in report["claims"]:
            self.assertTrue(set(claim["evidence_ids"])<=ids)
            if not claim["evidence_ids"]:self.assertEqual(claim["basis"],"verified_observations_or_absence")
        self.assertEqual(report["symptoms"][0]["text"],"오늘 속이 더부룩했어")

    def test_capacity_failure_rolls_back_all_instructions(self):
        for i in range(26):self.app.care.goal(self.sid,{"title":f"기존 목표 {i}"})
        with self.assertRaises(ValueError):self.app.store.guidance.create(self.sid,{"text":"새 지침 A, 새 지침 B"})
        self.assertEqual(len(self.app.store.guidance.dashboard(self.sid)["plans"]),1)

    def test_rule_validation_and_session_deletion_cascade(self):
        self.assertEqual(rule_for("취침 23시 99분 전")[1]["operator"],"self_report")
        q="오늘 커피 1잔 마셨어";self.chat(q,self.item("caffeine_cups",q,"1"))
        self.app.store.delete_session(self.sid)
        with self.app.store.connect() as db:
            for table in ["guidance_plans","guidance_instructions","patient_observations"]:
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?",(self.sid,)).fetchone()[0],0)

    def test_exclusion_resolves_conflict_without_erasing_original_utterance(self):
        for count in [1,2]:
            q=f"오늘 커피 {count}잔 마셨어";self.chat(q,self.item("caffeine_cups",q,str(count)))
        observations=self.report()["evidence"]
        with self.assertRaises(KeyError):self.app.care.delete(self.other,"patient-records",observations[0]["id"])
        self.app.care.delete(self.sid,"patient-records",observations[-1]["id"])
        row=next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="caffeine")
        self.assertEqual((row["rate"],row["counts"]["conflict"]),(100,0))
        self.assertIn("커피 2잔",self.app.store.get_session(self.sid)["messages"][-2]["content"])

    def test_qualitative_related_food_note_is_unassessed_not_missing_or_failed(self):
        q="오늘 찬 음식 먹었어"
        self.chat(q,self.item("diet_note",q))
        row=next(r for r in self.report()["instructions"] if r["instruction"]["category"]=="diet")
        self.assertEqual((row["counts"]["unassessed"],row["counts"]["unknown"],row["rate"]),(1,13,None))

    def test_explicit_date_does_not_merge_with_numeric_sleep_quantity(self):
        q=f"{self.day(13)} 6.5시간 잤어"
        result=self.chat(q,self.item("sleep_hours",q,"6.5",13))
        self.assertEqual(result["care"]["guidance"]["observations"][0]["value"],6.5)

    def test_diet_guidance_self_report_counts_as_sourced_meal_record(self):
        diet=next(i for i in self.app.store.guidance.dashboard(self.sid)["instructions"] if i["category"]=="diet")
        q="오늘 찬 음식 줄였어"
        self.chat(q,self.item("adherence",q,"done",instruction=diet["id"]))
        report=self.report()
        self.assertEqual(report["meals"][0]["text"],q)
        self.assertIn("1일 기록",next(c["text"] for c in report["trends"] if "2주차 식사" in c["text"]))


if __name__=="__main__":unittest.main()
