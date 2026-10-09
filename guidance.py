"""Clinician-entered lifestyle instructions and quote-grounded patient reports.

Luna extracts candidate observations; the server verifies quotes, dates and measured
values, and computes comparisons/report sentences. Missing data is never imputed.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta

from care import KST, text, today

METRICS = {"bedtime": "sleep", "sleep_hours": "sleep", "caffeine_cups": "caffeine",
           "walk_after_lunch_minutes": "activity", "activity_minutes": "activity",
           "diet_note": "diet", "symptom": "symptom", "adherence": "other"}
STATUS = {"met": "준수", "unmet": "미준수", "unknown": "기록 없음",
          "unassessed": "미판정", "conflict": "상충 기록", "inactive": "지침 기간 밖"}


def rule_for(clause):
    compact = re.sub(r"\s", "", clause)
    if re.search(r"취침|잠들|자기|자도록", compact):
        match = re.search(r"(\d{1,2})(?:시(?:(\d{1,2})분)?|:(\d{2}))(전|이전|까지)", compact)
        if match and 12 <= int(match[1]) <= 23:
            minute = int(match[2] or match[3] or 0)
            limit = int(match[1])*60+minute
            if minute < 60:
                return "sleep", {"metric": "bedtime", "operator": "lt" if match[4] in {"전", "이전"} else "lte", "limit": limit}
    match = re.search(r"(?:커피|카페인).{0,12}?(\d+)잔(이하|미만)", compact)
    if match and int(match[1]) <= 30:
        return "caffeine", {"metric": "caffeine_cups", "operator": "lte" if match[2]=="이하" else "lt", "limit": int(match[1])}
    match = re.search(r"점심(?:식사)?후.*?(\d+)분", compact)
    if match and re.search(r"산책|걷", compact) and int(match[1]) <= 1440:
        return "activity", {"metric": "walk_after_lunch_minutes", "operator": "gte", "limit": int(match[1])}
    category = "diet" if re.search(r"음식|식사|먹|식단", compact) else "other"
    return category, {"metric": "adherence", "operator": "self_report", "limit": None}


def observation_day(quote, message, timestamp):
    base = datetime.fromisoformat(timestamp).astimezone(KST).date()
    context = quote
    if not re.search(r"\d{4}-\d{2}-\d{2}|그제|그저께|어제|어젯|오늘|지난밤", quote):
        # Inherit only one unambiguous day from the current utterance.
        tokens = re.findall(r"\d{4}-\d{2}-\d{2}|그제|그저께|어제|어젯밤|오늘|지난밤", message)
        if len(set(tokens)) > 1:
            raise ValueError("발언마다 날짜를 함께 알려주세요.")
        context = message
    explicit = re.findall(r"\d{4}-\d{2}-\d{2}", context)
    if explicit:
        if len(set(explicit)) != 1:
            raise ValueError("기록 날짜가 분명하지 않아요.")
        day = date.fromisoformat(explicit[0])
    elif re.search(r"그제|그저께", context):
        day = base-timedelta(days=2)
    elif re.search(r"어제|어젯|지난밤", context):
        day = base-timedelta(days=1)
    else:
        if re.search(r"요즘|평소|지난주|지난달|며칠|최근", context) and "오늘" not in context:
            raise ValueError("기간 표현만으로 하루의 실천 기록을 만들지 않아요.")
        day = base
    if not base-timedelta(days=365) <= day <= base:
        raise ValueError("기록 날짜는 최근 1년의 오늘 또는 이전 날짜여야 해요.")
    return day.isoformat()


def measured_value(metric, quote):
    compact = re.sub(r"\s", "", re.sub(r"\d{4}-\d{2}-\d{2}", "", quote))
    if metric == "bedtime":
        if not re.search(r"잤|잠들었|취침했|자고|잠들어", compact):
            raise ValueError("취침 발언을 확인하지 못했어요.")
        match = re.search(r"(새벽|밤|오전|오후|저녁|아침)?(\d{1,2})(?:시(?:(\d{1,2})분)?|:(\d{2}))", compact)
        if not match:
            raise ValueError("취침 시간이 분명하지 않아요.")
        period, hour, minute = match[1], int(match[2]), int(match[3] or match[4] or 0)
        if hour > 23 or minute > 59 or (not period and hour < 12):
            raise ValueError("오전·오후를 포함한 취침 시간을 알려주세요.")
        if period in {"밤", "오후", "저녁"} and hour < 12: hour += 12
        if period in {"새벽", "오전", "아침"} and hour == 12: hour = 0
        if period == "밤" and hour == 12: hour = 0
        return hour*60+minute
    if metric == "sleep_hours":
        match = re.search(r"(\d+(?:\.\d+)?)시간", compact)
        if not match or not re.search(r"잤|수면|자고", compact): raise ValueError("수면 시간 근거가 없어요.")
        value = float(match[1])
        if not 0 <= value <= 24: raise ValueError("수면 시간 범위를 확인해 주세요.")
        return value
    if metric == "caffeine_cups":
        if not re.search(r"커피|카페인", compact): raise ValueError("커피 발언이 없어요.")
        if re.search(r"(?:커피|카페인).*(?:안마셨|안먹었|마시지않았|먹지않았)", compact): return 0
        match = re.search(r"(?:커피|카페인).{0,12}?(\d+|한|두|세|네)잔", compact)
        if not match: raise ValueError("커피 잔 수가 분명하지 않아요.")
        value = int(match[1]) if match[1].isdigit() else {"한":1,"두":2,"세":3,"네":4}[match[1]]
        if value > 30: raise ValueError("커피 잔 수 범위를 확인해 주세요.")
        return value
    if metric in {"activity_minutes", "walk_after_lunch_minutes"}:
        if not re.search(r"산책|걷|운동", compact): raise ValueError("활동 발언이 없어요.")
        if metric == "walk_after_lunch_minutes" and not re.search(r"점심(?:먹고|식사후|후|먹은뒤|먹은후)", compact):
            raise ValueError("점심 후 활동인지 확인할 수 없어요.")
        if re.search(r"(?:못했|안했|하지않았|못걸었)", compact): return 0
        match = re.search(r"(\d+)분", compact)
        if not match or not re.search(r"했|걸었|걸음|걷고|산책했", compact): raise ValueError("활동 시간 근거가 없어요.")
        value = int(match[1])
        if value > 1440: raise ValueError("활동 시간 범위를 확인해 주세요.")
        return value
    if metric == "diet_note":
        if not re.search(r"식사|음식|아침|점심|저녁|먹|식단|찬", compact): raise ValueError("식사 발언을 확인해 주세요.")
        return None
    if metric == "symptom":
        if not re.search(r"불편|피곤|피로|아프|아파|통증|답답|더부룩|속쓰|졸|어지|두통|힘들", compact):
            raise ValueError("불편감 발언을 확인해 주세요.")
        return None
    return None


class GuidanceStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS guidance_plans (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    author TEXT NOT NULL, body TEXT NOT NULL, starts_on TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS guidance_instructions (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    plan_id TEXT NOT NULL REFERENCES guidance_plans(id) ON DELETE CASCADE,
                    goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,
                    body TEXT NOT NULL, offset_start INTEGER NOT NULL, offset_end INTEGER NOT NULL,
                    category TEXT NOT NULL, rule TEXT NOT NULL, starts_on TEXT NOT NULL,
                    ended_on TEXT, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS patient_observations (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    day TEXT NOT NULL, metric TEXT NOT NULL, value TEXT NOT NULL,
                    instruction_id TEXT REFERENCES guidance_instructions(id) ON DELETE CASCADE,
                    quote TEXT NOT NULL, offset_start INTEGER NOT NULL, offset_end INTEGER NOT NULL,
                    UNIQUE(message_id,day,metric,quote,instruction_id));
                CREATE INDEX IF NOT EXISTS patient_observations_session ON patient_observations(session_id,day);
            """)
            if "excluded_at" not in {r[1] for r in db.execute("PRAGMA table_info(patient_observations)")}:
                db.execute("ALTER TABLE patient_observations ADD COLUMN excluded_at TEXT")

    def owner(self, db, session):
        if not db.execute("SELECT 1 FROM sessions WHERE id=?", (session,)).fetchone(): raise KeyError(session)

    def create(self, session, body):
        original = text(body.get("text"), "한의사 지침", 4000)
        author = text(body.get("author", "담당 한의사"), "입력자", 80)
        starts = date.fromisoformat(body.get("starts_on", today())).isoformat()
        if not "2000-01-01" <= starts <= today(): raise ValueError("지침 시작일은 오늘 또는 이전 날짜로 입력해 주세요.")
        clauses = []
        for match in re.finditer(r"[^\n,，;；]+", original):
            cleaned = re.sub(r"^\s*(?:[-•*]\s*|\d+[.)]\s*)?", "", match[0]).strip()
            if cleaned:
                begin = match.start()+match[0].index(cleaned)
                clauses.append((cleaned, begin, begin+len(cleaned)))
        if not 1 <= len(clauses) <= 20: raise ValueError("지침은 쉼표·줄바꿈으로 나누어 20개 이내로 입력해 주세요.")
        plan_id, stamp = uuid.uuid4().hex, datetime.now(KST).isoformat()
        with self.store.connect() as db:
            self.owner(db, session)
            count = db.execute("SELECT COUNT(*) FROM goals WHERE session_id=?", (session,)).fetchone()[0]
            if count+len(clauses) > 30: raise ValueError("개인 목표와 지침은 합쳐서 30개까지 만들 수 있어요.")
            db.execute("INSERT INTO guidance_plans VALUES (?,?,?,?,?,?)", (plan_id, session, author, original, starts, stamp))
            for clause, start, end in clauses:
                category, rule = rule_for(clause)
                goal, instruction = uuid.uuid4().hex, uuid.uuid4().hex
                db.execute("INSERT INTO goals VALUES (?,?,?,?,?)", (goal,session,clause[:120],category,stamp))
                db.execute("INSERT INTO guidance_instructions(id,session_id,plan_id,goal_id,body,offset_start,offset_end,category,rule,starts_on) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (instruction,session,plan_id,goal,clause,start,end,category,json.dumps(rule),starts))
        return self.store.care.dashboard(session)

    def dashboard(self, session):
        with self.store.connect() as db:
            self.owner(db, session)
            plans=[dict(r) for r in db.execute("SELECT * FROM guidance_plans WHERE session_id=? ORDER BY created_at", (session,))]
            instructions=[dict(r) for r in db.execute("SELECT * FROM guidance_instructions WHERE session_id=? ORDER BY rowid", (session,))]
        by_id={p["id"]:p for p in plans}
        for i in instructions:
            i["rule"]=json.loads(i["rule"]);i["author"]=by_id[i["plan_id"]]["author"]
            i["plan_text"]=by_id[i["plan_id"]]["body"];i["created_at"]=by_id[i["plan_id"]]["created_at"]
            if i["plan_text"][i["offset_start"]:i["offset_end"]]!=i["body"] or rule_for(i["body"])[1]!=i["rule"]:
                raise ValueError("지침 원문과 저장된 비교 기준이 일치하지 않아요.")
        observations=self.observations(session)
        return {"plans":plans,"instructions":instructions,"observations":observations[-90:]}

    def validate(self, session, message, candidates, timestamp=None):
        if not isinstance(candidates, list) or len(candidates)>8: raise ValueError("생활 발언 형식을 확인해 주세요.")
        stamp=timestamp or datetime.now(KST).isoformat()
        with self.store.connect() as db:
            instructions={r["id"]:dict(r) for r in db.execute("SELECT * FROM guidance_instructions WHERE session_id=? AND active=1",(session,))}
        clean=[]
        for item in candidates:
            quote=item.get("quote") if isinstance(item,dict) else None
            metric=item.get("metric") if isinstance(item,dict) else None
            if not isinstance(quote,str) or not 2<=len(quote)<=1000 or quote not in message or metric not in METRICS:
                raise ValueError("환자 발언 원문과 인용이 일치하지 않아요.")
            if re.search(r"만약|예를\s*들어|라면|내일|할\s*거|할게|예정|계획|먹을|마실|잘\s*거|\?|？|친구가|엄마가|아빠가", quote):
                raise ValueError("가정·계획·다른 사람의 발언을 실천 기록으로 저장하지 않아요.")
            day=observation_day(quote,message,stamp)
            if item.get("date") != day: raise ValueError("발언의 날짜와 기록 날짜가 일치하지 않아요.")
            instruction_id=item.get("instruction_id") or None
            if metric=="adherence":
                instruction=instructions.get(instruction_id)
                if not instruction or json.loads(instruction["rule"])["operator"]!="self_report":
                    raise ValueError("직접 실천 보고를 연결할 지침을 확인해 주세요.")
                compact=re.sub(r"\s","",quote)
                rule_text=re.sub(r"\s","",instruction["body"])
                cold="찬음식" in rule_text and "찬음식" in compact
                exact=rule_text in compact
                general=len(instructions)==1 and "지침" in compact
                if not (cold or exact or general): raise ValueError("어떤 지침을 실천했는지 알려주세요.")
                if re.search(r"못지켰|안지켰|못했|지키지못|줄이지못", compact): value="not_done"
                elif re.search(r"지켰|실천했|줄였|안마셨|안먹었|먹지않았", compact): value="done"
                else: raise ValueError("실천 여부가 분명하지 않아요.")
                if item.get("value")!=value: raise ValueError("실천 보고와 판정이 일치하지 않아요.")
            else:
                if instruction_id and instruction_id not in instructions: raise ValueError("다른 대화의 지침을 연결할 수 없어요.")
                value=measured_value(metric,quote)
                instruction_id=None
            if value is not None and metric!="adherence":
                expected=f"{int(value)//60:02d}:{int(value)%60:02d}" if metric=="bedtime" else str(value)
                try: valid=item.get("value")==expected if metric=="bedtime" else float(item.get("value"))==value
                except (ValueError,TypeError): valid=False
                if not valid: raise ValueError("추출한 수치가 실제 발언과 일치하지 않아요.")
            offset=message.index(quote)
            record={"day":day,"metric":metric,"value":value,"instruction_id":instruction_id,"quote":quote,"offset_start":offset,"offset_end":offset+len(quote)}
            if record not in clean:clean.append(record)
        return clean

    def record(self, session, message_id, observations):
        ids=[]
        with self.store.connect() as db:
            source=db.execute("SELECT content,created_at FROM messages WHERE id=? AND session_id=? AND role='user'",(message_id,session)).fetchone()
            if not source:raise KeyError(message_id)
            candidates=[{"metric":o["metric"],"quote":o["quote"],"date":o["day"],"instruction_id":o["instruction_id"] or "","value":f'{int(o["value"])//60:02d}:{int(o["value"])%60:02d}' if o["metric"]=="bedtime" else str(o["value"]) if o["value"] is not None else ""} for o in observations]
            observations=self.validate(session,source["content"],candidates,source["created_at"])
            for o in observations:
                item_id=uuid.uuid4().hex
                db.execute("INSERT INTO patient_observations(id,session_id,message_id,day,metric,value,instruction_id,quote,offset_start,offset_end) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (item_id,session,message_id,o["day"],o["metric"],json.dumps(o["value"]),o["instruction_id"],o["quote"],o["offset_start"],o["offset_end"]))
                ids.append(item_id)
        return ids

    def observations(self, session):
        with self.store.connect() as db:
            rows=[dict(r) for r in db.execute("SELECT o.*,m.content,m.created_at FROM patient_observations o JOIN messages m ON m.id=o.message_id WHERE o.session_id=? AND m.session_id=? AND m.role='user' AND o.excluded_at IS NULL ORDER BY o.seq",(session,session))]
        verified=[]
        for r in rows:
            if r["content"][r["offset_start"]:r["offset_end"]]!=r["quote"]: continue
            r["value"]=json.loads(r["value"])
            try:
                if observation_day(r["quote"],r["content"],r["created_at"])!=r["day"]:continue
                if r["metric"]!="adherence" and measured_value(r["metric"],r["quote"])!=r["value"]:continue
                if r["metric"]=="adherence":
                    compact=re.sub(r"\s","",r["quote"])
                    expected="not_done" if re.search(r"못지켰|안지켰|못했|지키지못|줄이지못",compact) else "done" if re.search(r"지켰|실천했|줄였|안마셨|안먹었|먹지않았",compact) else None
                    if r["value"]!=expected:continue
            except (ValueError,TypeError):continue
            verified.append(r)
        return verified

    def exclude(self,session,item):
        with self.store.connect() as db:
            self.owner(db,session)
            if not db.execute("UPDATE patient_observations SET excluded_at=? WHERE id=? AND session_id=? AND excluded_at IS NULL",(datetime.now(KST).isoformat(),item,session)).rowcount:raise KeyError(item)
        return self.store.care.dashboard(session)

    @staticmethod
    def compare(instruction, day, observations):
        if day<instruction["starts_on"] or (instruction["ended_on"] and day>instruction["ended_on"]):
            return {"date":day,"status":"inactive","evidence_ids":[]}
        rule=instruction["rule"]
        found=[o for o in observations if o["day"]==day and o["metric"]==rule["metric"] and (rule["metric"]!="adherence" or o["instruction_id"]==instruction["id"])]
        if not found and rule["operator"]=="self_report" and "찬음식" in re.sub(r"\s","",instruction["body"]):
            found=[o for o in observations if o["day"]==day and o["metric"]=="diet_note" and "찬음식" in re.sub(r"\s","",o["quote"])]
        refs=[o["id"] for o in found]
        if not found: state="unknown"
        elif len({json.dumps(o["value"]) for o in found})>1: state="conflict"
        elif rule["operator"]=="self_report": state="unassessed" if found[-1]["metric"]!="adherence" else "met" if found[-1]["value"]=="done" else "unmet"
        else:
            value=found[-1]["value"]
            if rule["metric"]=="bedtime" and value<12*60:value+=24*60
            limit=rule["limit"]
            passed=value<limit if rule["operator"]=="lt" else value<=limit if rule["operator"]=="lte" else value>=limit
            state="met" if passed else "unmet"
        return {"date":day,"status":state,"evidence_ids":refs}

    def coach(self, session, observation_ids):
        guidance=self.dashboard(session)
        fresh=[o for o in guidance["observations"] if o["id"] in observation_ids]
        lines=[]
        for i in guidance["instructions"]:
            if not i["active"]:continue
            for day in sorted({o["day"] for o in fresh}):
                cell=self.compare(i,day,guidance["observations"])
                if not set(cell["evidence_ids"]).intersection(observation_ids):continue
                if cell["status"]=="conflict":tail="서로 다른 발언이 있어 실천 여부를 보류했어요. 정확한 기록을 알려주세요."
                elif cell["status"]=="met":tail="지침에 맞게 실천했다고 기록했어요. 작은 실천을 이어가요."
                elif cell["status"]=="unmet":tail="지침과 차이가 있었다고 기록했어요. 다음 실천은 이 목표를 기준으로 준비해봐요."
                else:continue
                lines.append(day+" · “"+i["body"]+"” — "+tail)
        if fresh and not lines:lines.append("말씀한 생활·불편감과 날짜를 원문 근거로 기록했어요.")
        return "\n".join(lines[:4])

    def report(self, session, end=None):
        end=date.fromisoformat(end or today())
        if end>date.fromisoformat(today()):raise ValueError("리포트 종료일은 오늘 또는 이전 날짜여야 해요.")
        start=end-timedelta(days=13)
        days=[(start+timedelta(days=i)).isoformat() for i in range(14)]
        guidance=self.dashboard(session)
        records=[o for o in self.observations(session) if start.isoformat()<=o["day"]<=end.isoformat()]
        records.sort(key=lambda o:(o["day"],o["seq"]))
        diet_instructions={i["id"] for i in guidance["instructions"] if i["category"]=="diet"}
        meal_records=[o for o in records if o["metric"]=="diet_note" or (o["metric"]=="adherence" and o["instruction_id"] in diet_instructions)]
        claims=[];rows=[]
        for instruction in guidance["instructions"]:
            if instruction["starts_on"]>end.isoformat() or (instruction["ended_on"] and instruction["ended_on"]<start.isoformat()):continue
            cells=[self.compare(instruction,d,records) for d in days]
            counts={s:sum(c["status"]==s for c in cells) for s in STATUS}
            assessed=counts["met"]+counts["unmet"]
            eligible=14-counts["inactive"]
            recorded=eligible-counts["unknown"]
            refs=list(dict.fromkeys(r for c in cells for r in c["evidence_ids"]))
            rate=round(counts["met"]/assessed*100,1) if assessed else None
            claim={"text":f'지침 기간 {eligible}일 중 {recorded}일 기록 · 판정 가능한 {assessed}일 중 {counts["met"]}일 준수'+(f' ({rate:g}%)' if rate is not None else " · 실천율 판정 불가")+f' · 기록 없음 {counts["unknown"]}일'+(f' · 상충 {counts["conflict"]}일' if counts["conflict"] else "")+(f' · 미판정 {counts["unassessed"]}일' if counts["unassessed"] else ""),"evidence_ids":refs,"basis":"verified_observations_or_absence"}
            claims.append(claim)
            rows.append({"instruction":instruction,"days":cells,"counts":counts,"rate":rate,"assessed":assessed,"eligible":eligible,"recorded":recorded,"claim":claim})
        trends=[]
        for metric,label,unit in [("sleep_hours","수면 시간","시간"),("bedtime","취침 시각",""),("diet_note","식사 발언","일")]:
            for week in range(2):
                candidates=meal_records if metric=="diet_note" else [o for o in records if o["metric"]==metric]
                subset=[o for o in candidates if o["day"] in days[week*7:week*7+7]]
                # Conflicting daily quantities are excluded from a numeric average.
                by_day={d:[o for o in subset if o["day"]==d] for d in days[week*7:week*7+7]}
                usable=[v[-1] for v in by_day.values() if v and len({json.dumps(o["value"]) for o in v})==1]
                if metric=="diet_note":value=f'{len([v for v in by_day.values() if v])}일 기록'
                elif usable:
                    values=[o["value"]+(1440 if metric=="bedtime" and o["value"]<720 else 0) for o in usable]
                    average=sum(values)/len(values)
                    value=f'평균 {average:.1f}{unit}' if metric=="sleep_hours" else f'평균 {int(round(average))%1440//60:02d}:{int(round(average))%60:02d}'
                    value+=f' · 판정 가능한 {len(usable)}일'
                else:value="기록 없음" if not subset else "상충 기록 · 평균 판정 불가"
                claim={"text":f'{week+1}주차 {label}: {value}',"evidence_ids":[o["id"] for o in subset],"basis":"verified_observations_or_absence"}
                claims.append(claim);trends.append(claim)
        symptoms=[{"text":o["quote"],"date":o["day"],"evidence_ids":[o["id"]],"basis":"patient_quote"} for o in records if o["metric"]=="symptom"][-3:]
        meals=[{"text":o["quote"],"date":o["day"],"evidence_ids":[o["id"]],"basis":"patient_quote"} for o in meal_records][-2:]
        claims.extend(symptoms+meals)
        coverage=[{"date":d,"status":"기록 있음" if any(o["day"]==d for o in records) else "기록 없음","evidence_ids":[o["id"] for o in records if o["day"]==d]} for d in days]
        return {"session_id":session,"start":start.isoformat(),"end":end.isoformat(),"generated_at":datetime.now(KST).isoformat(),"days":days,"coverage":coverage,"instructions":rows,"trends":trends,"symptoms":symptoms,"meals":meals,"claims":claims,"evidence":records,"recorded_days":sum(c["status"]=="기록 있음" for c in coverage),"missing_days":sum(c["status"]=="기록 없음" for c in coverage)}
