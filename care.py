"""Session-owned lifestyle, goals, booking drafts and calendar storage."""
from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

KST = timezone(timedelta(hours=9))


def today():
    return datetime.now(KST).date().isoformat()


def text(value, name, maximum=300, required=True):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        raise ValueError(f"{name}을 올바르게 입력해 주세요.")
    return value.strip()


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return ""
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return ""
        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "::1"} or "." not in host:
            return ""
        import ipaddress
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        return value
    except ValueError:
        return ""


def local_time(value):
    try:
        value = text(value, "일시", 40)
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        if not 2000 <= parsed.year <= 2100:
            raise ValueError()
        return parsed.astimezone(KST)
    except (ValueError, TypeError):
        raise ValueError("날짜와 시간을 올바르게 입력해 주세요.") from None


def clean_checkin(body):
    try:
        day = date.fromisoformat(body.get("date", today())).isoformat()
        if day > today():
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("체크인 날짜는 오늘 또는 이전 날짜로 입력해 주세요.") from None
    result = {"date": day, "note": text(body.get("note", ""), "메모", 1000, False)}
    for key, label, high, integer in [
        ("sleep", "수면 시간", 24, False), ("stress", "스트레스", 10, True),
        ("energy", "활력", 10, True), ("caffeine", "카페인 잔 수", 30, True),
        ("activity", "활동 시간", 1440, True), ("discomfort", "불편감", 10, True),
    ]:
        value = body.get(key)
        if value is None or value == "":
            result[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{label}을 숫자로 입력해 주세요.")
        if not 0 <= value <= high or (integer and int(value) != value):
            raise ValueError(f"{label}은 0~{high} 범위로 입력해 주세요.")
        result[key] = value
    return result


class CareStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS checkins (
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    date TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(session_id,date));
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    title TEXT NOT NULL, category TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS goal_ticks (
                    goal_id TEXT REFERENCES goals(id) ON DELETE CASCADE,
                    date TEXT NOT NULL, PRIMARY KEY(goal_id,date));
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bookings (
                    id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS searches (
                    id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS care_events_session ON events(session_id);
                CREATE INDEX IF NOT EXISTS care_bookings_session ON bookings(session_id);
                CREATE INDEX IF NOT EXISTS care_searches_session ON searches(session_id);
            """)

    def owner(self, db, session):
        if not db.execute("SELECT 1 FROM sessions WHERE id=?", (session,)).fetchone():
            raise KeyError(session)

    def dashboard(self, session):
        with self.store.connect() as db:
            self.owner(db, session)
            checks = [json.loads(r[0]) for r in db.execute(
                "SELECT data FROM checkins WHERE session_id=? ORDER BY date DESC LIMIT 90", (session,))]
            goals = [dict(r) for r in db.execute("SELECT id,title,category,created_at FROM goals WHERE session_id=? ORDER BY created_at", (session,))]
            for g in goals:
                g["completed_dates"] = [r[0] for r in db.execute("SELECT date FROM goal_ticks WHERE goal_id=? ORDER BY date", (g["id"],))]
            events = [json.loads(r[0]) for r in db.execute("SELECT data FROM events WHERE session_id=?", (session,))]
            bookings = [json.loads(r[0]) for r in db.execute("SELECT data FROM bookings WHERE session_id=?", (session,))]
            searches = [dict(r) for r in db.execute("SELECT id,kind,data,created_at FROM searches WHERE session_id=? ORDER BY created_at DESC LIMIT 10", (session,))]
        for row in searches:
            row["data"] = json.loads(row["data"])
        events = sorted(events, key=lambda e: e["start"])
        conflicts = [{"first": a["id"], "second": b["id"]} for i, a in enumerate(events)
                     for b in events[i+1:] if a["start"] < b["end"] and b["start"] < a["end"]]
        return {"today": today(), "checkins": checks, "goals": goals,
                "events": events, "conflicts": conflicts,
                "bookings": bookings[::-1], "searches": searches,
                "summary": self.summary(checks)}

    @staticmethod
    def summary(checks):
        cutoff = (datetime.now(KST).date() - timedelta(days=6)).isoformat()
        recent = [c for c in checks if c["date"] >= cutoff]
        averages = {}
        for key in ("sleep", "stress", "energy", "activity", "discomfort"):
            values = [c[key] for c in recent if c.get(key) is not None]
            averages[key] = round(sum(values) / len(values), 1) if values else None
        return {"days": len(recent), "averages": averages}

    def checkin(self, session, body):
        record = clean_checkin(body)
        with self.store.connect() as db:
            self.owner(db, session)
            db.execute("INSERT INTO checkins VALUES (?,?,?) ON CONFLICT(session_id,date) DO UPDATE SET data=excluded.data",
                       (session, record["date"], json.dumps(record, ensure_ascii=False)))
        return self.dashboard(session)

    def goal(self, session, body):
        title = text(body.get("title"), "목표", 120)
        category = body.get("category", "activity")
        if category not in {"sleep", "diet", "activity", "stress", "caffeine", "other"}:
            raise ValueError("목표 종류를 확인해 주세요.")
        with self.store.connect() as db:
            self.owner(db, session)
            if db.execute("SELECT COUNT(*) FROM goals WHERE session_id=?", (session,)).fetchone()[0] >= 30:
                raise ValueError("목표는 30개까지 만들 수 있어요.")
            db.execute("INSERT INTO goals VALUES (?,?,?,?,?)", (uuid.uuid4().hex, session, title, category, datetime.now(KST).isoformat()))
        return self.dashboard(session)

    def tick(self, session, item, body):
        if not isinstance(body.get("done"), bool):
            raise ValueError("완료 여부를 확인해 주세요.")
        with self.store.connect() as db:
            self.owner(db, session)
            if not db.execute("SELECT 1 FROM goals WHERE id=? AND session_id=?", (item, session)).fetchone():
                raise KeyError(item)
            if body["done"]:
                db.execute("INSERT OR IGNORE INTO goal_ticks VALUES (?,?)", (item, today()))
            else:
                db.execute("DELETE FROM goal_ticks WHERE goal_id=? AND date=?", (item, today()))
        return self.dashboard(session)

    def event(self, session, body, item=None):
        start = local_time(body.get("start"))
        end = local_time(body.get("end")) if body.get("end") else start + timedelta(minutes=30)
        if not start < end <= start + timedelta(days=7):
            raise ValueError("일정 종료는 시작 이후 7일 이내로 입력해 주세요.")
        data = {"id": item or uuid.uuid4().hex, "title": text(body.get("title"), "일정 제목", 160),
                "start": start.isoformat(), "end": end.isoformat(),
                "location": text(body.get("location", ""), "장소", 300, False),
                "note": text(body.get("note", ""), "일정 메모", 1000, False),
                "kind": "personal", "status": "planned"}
        with self.store.connect() as db:
            self.owner(db, session)
            if item:
                row = db.execute("SELECT data FROM events WHERE id=? AND session_id=?", (item, session)).fetchone()
                if not row:
                    raise KeyError(item)
                existing = json.loads(row[0])
                if existing["kind"] == "appointment":
                    raise ValueError("병원 예약 일정은 예약 상태에서 관리해 주세요.")
                db.execute("UPDATE events SET data=? WHERE id=? AND session_id=?", (json.dumps(data, ensure_ascii=False), item, session))
            else:
                if db.execute("SELECT COUNT(*) FROM events WHERE session_id=?", (session,)).fetchone()[0] >= 200:
                    raise ValueError("일정은 200개까지 저장할 수 있어요.")
                db.execute("INSERT INTO events VALUES (?,?,?)", (data["id"], session, json.dumps(data, ensure_ascii=False)))
        return self.dashboard(session)

    def save_search(self, session, kind, data):
        search_id = uuid.uuid4().hex
        with self.store.connect() as db:
            self.owner(db, session)
            db.execute("INSERT INTO searches VALUES (?,?,?,?,?)", (search_id, session, kind, json.dumps(data, ensure_ascii=False), datetime.now(KST).isoformat()))
            db.execute("DELETE FROM searches WHERE session_id=? AND id NOT IN (SELECT id FROM searches WHERE session_id=? ORDER BY created_at DESC LIMIT 20)", (session, session))
        return search_id

    def booking(self, session, body):
        search_id, hospital_id = body.get("search_id"), body.get("hospital_id")
        with self.store.connect() as db:
            self.owner(db, session)
            row = db.execute("SELECT data FROM searches WHERE id=? AND session_id=? AND kind='hospitals'", (search_id, session)).fetchone()
            if not row:
                raise ValueError("병원을 먼저 검색한 뒤 선택해 주세요.")
            hospital = next((h for h in json.loads(row[0])["hospitals"] if h["id"] == hospital_id), None)
            if not hospital:
                raise ValueError("검색 결과에서 병원을 선택해 주세요.")
            start = local_time(body.get("start"))
            if start <= datetime.now(KST):
                raise ValueError("예약 희망 시간은 현재 이후로 입력해 주세요.")
            if db.execute("SELECT COUNT(*) FROM bookings WHERE session_id=?", (session,)).fetchone()[0] >= 100:
                raise ValueError("예약 기록은 100개까지 저장할 수 있어요.")
            data = {"id": uuid.uuid4().hex, "hospital": hospital, "start": start.isoformat(),
                    "note": text(body.get("note", ""), "방문 메모", 1000, False),
                    "status": "prepared", "confirmation": "", "event_id": ""}
            db.execute("INSERT INTO bookings VALUES (?,?,?)", (data["id"], session, json.dumps(data, ensure_ascii=False)))
        return self.dashboard(session)

    def booking_status(self, session, item, body):
        status = body.get("status")
        if status not in {"confirmed", "cancelled"}:
            raise ValueError("예약 상태를 확인해 주세요.")
        with self.store.connect() as db:
            self.owner(db, session)
            row = db.execute("SELECT data FROM bookings WHERE id=? AND session_id=?", (item, session)).fetchone()
            if not row:
                raise KeyError(item)
            data = json.loads(row[0])
            if status == "confirmed":
                if body.get("confirmed_by_user") is not True:
                    raise ValueError("병원에서 예약 확정을 받은 뒤 확인해 주세요.")
                if data["status"] != "prepared":
                    raise ValueError("예약 준비 상태에서만 확정을 기록할 수 있어요.")
                confirmation = text(body.get("confirmation"), "병원 예약 확인 내용", 300)
                start = local_time(data["start"])
                event_id = uuid.uuid4().hex
                event = {"id": event_id, "title": data["hospital"]["name"] + " 방문",
                         "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(),
                         "location": data["hospital"].get("address", ""),
                         "note": "사용자가 병원 예약 확정을 확인함. " + confirmation,
                         "kind": "appointment", "status": "user_confirmed"}
                db.execute("INSERT INTO events VALUES (?,?,?)", (event_id, session, json.dumps(event, ensure_ascii=False)))
                data.update(event_id=event_id, confirmation=confirmation)
            else:
                if body.get("confirmed_by_user") is not True and body.get("local_only") is not True:
                    raise ValueError("병원과 취소를 확인한 뒤 로컬 기록을 취소해 주세요.")
                if data["event_id"]:
                    db.execute("DELETE FROM events WHERE id=? AND session_id=?", (data["event_id"], session))
                data["event_id"] = ""
            data["status"] = status
            db.execute("UPDATE bookings SET data=? WHERE id=? AND session_id=?", (json.dumps(data, ensure_ascii=False), item, session))
        return self.dashboard(session)

    def update_booking(self, session, item, body):
        """Change a local visit plan; a new desired time needs hospital confirmation."""
        with self.store.connect() as db:
            self.owner(db, session)
            row = db.execute("SELECT data FROM bookings WHERE id=? AND session_id=?", (item, session)).fetchone()
            if not row:
                raise KeyError(item)
            data = json.loads(row[0])
            if data["status"] == "cancelled":
                raise ValueError("취소한 예약은 새로 준비해 주세요.")
            start = local_time(body.get("start") or data["start"])
            if start <= datetime.now(KST):
                raise ValueError("방문 희망 시간은 현재 이후로 입력해 주세요.")
            if data["status"] == "confirmed" and start.isoformat() != data["start"]:
                db.execute("DELETE FROM events WHERE id=? AND session_id=?", (data["event_id"], session))
                data.update(status="prepared", event_id="", confirmation="")
            data["start"] = start.isoformat()
            if "note" in body:
                data["note"] = text(body["note"], "방문 메모", 1000, False)
            db.execute("UPDATE bookings SET data=? WHERE id=? AND session_id=?", (json.dumps(data, ensure_ascii=False), item, session))
        return self.dashboard(session)

    def delete(self, session, collection, item):
        # Table names are selected from a fixed allowlist, never supplied as SQL.
        if collection not in {"goals", "events", "memories", "checkins"}:
            raise ValueError("삭제할 기록을 확인해 주세요.")
        column = "date" if collection == "checkins" else "id"
        with self.store.connect() as db:
            self.owner(db, session)
            if collection == "events":
                row = db.execute("SELECT data FROM events WHERE id=? AND session_id=?", (item, session)).fetchone()
                if row and json.loads(row[0])["kind"] == "appointment":
                    raise ValueError("병원 예약은 예약 상태에서 취소해 주세요.")
            if not db.execute(f"DELETE FROM {collection} WHERE {column}=? AND session_id=?", (item, session)).rowcount:
                raise KeyError(item)
        return self.dashboard(session)

    def calendar(self, session):
        care = self.dashboard(session)
        events = [dict(e) for e in care["events"]]
        for booking in care["bookings"]:
            if booking["status"] == "prepared":
                start = local_time(booking["start"])
                events.append({"id": "booking-"+booking["id"], "title": booking["hospital"]["name"]+" · 예약 준비",
                    "start": start.isoformat(), "end": (start+timedelta(minutes=30)).isoformat(),
                    "location": booking["hospital"].get("address", ""),
                    "note": "희망 시간만 저장됨. 병원 접수·확정 전. "+booking["note"], "tentative": True})
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Hanui//Lifestyle Calendar//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
        for event in events:
            utc = lambda v: local_time(v).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            lines.extend(["BEGIN:VEVENT", f'UID:{event["id"]}@hanui.local',
                          "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                          "DTSTART:" + utc(event["start"]), "DTEND:" + utc(event["end"]),
                          "SUMMARY:" + ics_escape(event["title"]), "LOCATION:" + ics_escape(event["location"]),
                          "DESCRIPTION:" + ics_escape(event["note"]),
                          "STATUS:"+("TENTATIVE" if event.get("tentative") else "CONFIRMED"), "END:VEVENT"])
        lines.append("END:VCALENDAR")
        return b"\r\n".join(fold_line(line) for line in lines) + b"\r\n"


def ics_escape(value):
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_line(line):
    parts, current = [], bytearray()
    for character in line:
        encoded = character.encode("utf-8")
        if len(current) + len(encoded) > 75:
            parts.append(bytes(current))
            current = bytearray(b" ")
        current.extend(encoded)
    parts.append(bytes(current))
    return b"\r\n".join(parts)
