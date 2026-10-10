"""Session-owned reminders generated only from verified upcoming calendar entries."""
import hashlib
import json
import threading
import re
from datetime import datetime, timedelta

from care import KST, local_time
from request_lifecycle import check_cancelled


class Reminders:
    def __init__(self, store, model):
        self.store, self.model = store, model
        self.lock = threading.Lock()
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS reminders (session_id TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL, dismissed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id,fingerprint), FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)")

    def upcoming(self, session_id, now):
        events = self.store.care.dashboard(session_id)["events"]
        result = []
        for event in events:
            if event.get("status") == "cancelled":
                continue
            start = local_time(event["start"])
            if now-timedelta(minutes=5) <= start <= now+timedelta(minutes=30):
                fingerprint = hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                result.append((fingerprint, event))
        return sorted(result, key=lambda item: local_time(item[1]["start"]))

    def poll(self, session_id, dismissed=None, now=None):
        self.store.get_session(session_id)
        real_clock = now is None
        now = now or datetime.now(KST)
        if dismissed is not None and (not isinstance(dismissed, str) or not re.fullmatch(r"[a-f0-9]{64}", dismissed)):
            raise ValueError("알림을 확인해 주세요.")
        if not self.lock.acquire(blocking=False):
            return {"reminders": [], "pending": True}
        try:
            if dismissed:
                with self.store.connect() as db:
                    db.execute("UPDATE reminders SET dismissed=1 WHERE session_id=? AND fingerprint=?", (session_id, dismissed))
            due = self.upcoming(session_id, now)
            results = []
            generated = False
            for fingerprint, event in due:
                with self.store.connect() as db:
                    row = db.execute("SELECT data,dismissed FROM reminders WHERE session_id=? AND fingerprint=?", (session_id, fingerprint)).fetchone()
                if row:
                    if not row["dismissed"]:
                        results.append(json.loads(row["data"]))
                    continue
                if generated or not hasattr(self.model, "generate_reminder") or not self.model.available():
                    continue
                note = self.model.generate_reminder(event)
                check_cancelled()
                # A deletion, cancellation, or time change during inference invalidates the reminder.
                if fingerprint not in {key for key, _ in self.upcoming(session_id, datetime.now(KST) if real_clock else now)}:
                    continue
                data = {"id": fingerprint, "event_id": event["id"], "title": event["title"],
                        "start": event["start"], "location": event.get("location", ""), "note": note}
                with self.store.connect() as db:
                    check_cancelled()
                    db.execute("INSERT OR IGNORE INTO reminders(session_id,fingerprint,data) VALUES(?,?,?)", (session_id, fingerprint, json.dumps(data, ensure_ascii=False)))
                results.append(data)
                generated = True
            return {"reminders": results}
        finally:
            self.lock.release()
