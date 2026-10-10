"""Persistent Web Push subscriptions and a server-owned reminder scheduler."""
import base64
import hashlib
import json
import os
import re
import threading
from datetime import datetime
from urllib.parse import urlparse
from care import KST


class PushNotifications:
    def __init__(self, store, runtime):
        self.store, self.runtime = store, runtime
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS push_subscriptions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS push_deliveries (subscription TEXT NOT NULL, notice TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, delivered INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(subscription,notice));
            """)

    def keys(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        path = self.runtime / "push-vapid.pem"
        if not path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            # Atomic create: concurrent account requests cannot replace the key.
            try:
                with path.open("xb") as file:
                    file.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            except FileExistsError:
                pass
        key = serialization.load_pem_private_key(path.read_bytes(),password=None)
        public = key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        return str(path),base64.urlsafe_b64encode(public).decode().rstrip("=")

    def settings(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM app_settings WHERE key='notifications'").fetchone()
        return json.loads(row[0]) if row else {"enabled":False,"time":"20:00"}

    def save_settings(self, body):
        if not isinstance(body.get("enabled"),bool) or not isinstance(body.get("time"),str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",body["time"]):
            raise ValueError("알림 시간과 켜짐 상태를 확인해 주세요.")
        with self.store.connect() as db:
            db.execute("INSERT INTO app_settings VALUES('notifications',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps({"enabled":body["enabled"],"time":body["time"]}),))
        return self.settings()

    def subscribe(self, body):
        endpoint = body.get("endpoint")
        keys = body.get("keys")
        if not isinstance(endpoint,str) or len(endpoint)>2000 or not isinstance(keys,dict):
            raise ValueError("브라우저 알림 정보를 확인해 주세요.")
        url = urlparse(endpoint)
        host = url.hostname or ""
        allowed = host in {"fcm.googleapis.com","updates.push.services.mozilla.com","web.push.apple.com"} or host.endswith(".push.apple.com")
        if url.scheme!="https" or not allowed or url.username or url.password or url.port not in {None,443}:
            raise ValueError("지원되는 브라우저 푸시 주소가 아니에요.")
        for name,size in (("p256dh",65),("auth",16)):
            value = keys.get(name)
            try:
                decoded = base64.urlsafe_b64decode(value+"="*((-len(value))%4))
                if len(decoded)!=size:
                    raise ValueError()
            except (ValueError,TypeError):
                raise ValueError("브라우저 알림 키가 올바르지 않아요.") from None
        identifier = hashlib.sha256(endpoint.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("INSERT INTO push_subscriptions VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",(identifier,json.dumps({"endpoint":endpoint,"keys":keys})))
        return {"subscribed":True}

    def unsubscribe(self, endpoint):
        if not isinstance(endpoint,str):
            raise ValueError("알림 구독을 확인해 주세요.")
        with self.store.connect() as db:
            sid = hashlib.sha256(endpoint.encode()).hexdigest()
            db.execute("DELETE FROM push_subscriptions WHERE id=?",(sid,))
            db.execute("DELETE FROM push_deliveries WHERE subscription=?",(sid,))
        return {"subscribed":False}

    def deliver(self, notice, payload):
        from pywebpush import webpush, WebPushException
        with self.store.connect() as db:
            subscriptions = list(db.execute("SELECT * FROM push_subscriptions"))
        if not subscriptions:
            return
        key,_ = self.keys()
        for subscription in subscriptions:
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO push_deliveries(subscription,notice) VALUES(?,?)",(subscription["id"],notice))
                previous = db.execute("SELECT * FROM push_deliveries WHERE subscription=? AND notice=?",(subscription["id"],notice)).fetchone()
                if previous["delivered"] or previous["attempts"]>=3:
                    continue
                db.execute("UPDATE push_deliveries SET attempts=attempts+1 WHERE subscription=? AND notice=?",(subscription["id"],notice))
            try:
                webpush(subscription_info=json.loads(subscription["data"]),data=json.dumps(payload,ensure_ascii=False),vapid_private_key=key,
                        vapid_claims={"sub":os.environ.get("HANUI_PUSH_CONTACT","https://localhost")},ttl=1800,timeout=8)
            except WebPushException as exc:
                if exc.response is not None and exc.response.status_code in {404,410}:
                    self.unsubscribe(json.loads(subscription["data"])["endpoint"])
                continue
            with self.store.connect() as db:
                db.execute("UPDATE push_deliveries SET delivered=1 WHERE subscription=? AND notice=?",(subscription["id"],notice))

    def tick(self, app, now=None):
        clock = now or datetime.now(KST)
        settings = self.settings()
        if not settings["enabled"] or not app.lock.acquire(blocking=False):
            return
        notices = []
        try:
            for session in self.store.list_sessions():
                for fingerprint,event in app.reminders.upcoming(session["id"],clock):
                    with self.store.connect() as db:
                        dismissed = db.execute("SELECT dismissed FROM reminders WHERE session_id=? AND fingerprint=?",(session["id"],fingerprint)).fetchone()
                    if dismissed and dismissed[0]:
                        continue
                    notices.append(("event:"+fingerprint,{"title":"Hanui","body":"다가오는 일정이 있어요.","url":"/?session="+session["id"],"tag":fingerprint}))
            program = app.hub.program()
            target = clock.replace(hour=int(settings["time"][:2]),minute=int(settings["time"][3:]),second=0,microsecond=0)
            if program and 0<=(clock-target).total_seconds()<1800:
                sessions = {s["id"] for s in self.store.list_sessions()}
                if program["session_id"] in sessions:
                    revision = hashlib.sha256(json.dumps(program,sort_keys=True).encode()).hexdigest()[:12]
                    key = "daily:"+clock.date().isoformat()+":"+revision
                    notices.append((key,{"title":"Hanui","body":"오늘의 관리 내용을 확인해 주세요.","url":"/?session="+program["session_id"]+"&care=today","tag":key}))
        finally:
            app.lock.release()
        # Network delivery must not block conversations, calendar edits or cancellation.
        for notice,payload in notices:
            sid = urlparse(payload["url"]).query.split("session=",1)[-1].split("&",1)[0]
            try:
                self.store.get_session(sid)
            except KeyError:
                continue
            if notice.startswith("event:") and notice[6:] not in {key for key,_ in app.reminders.upcoming(sid,clock)}:
                continue
            if not self.settings()["enabled"]:
                break
            self.deliver(notice,payload)


class NotificationScheduler:
    def __init__(self, root):
        self.root = root
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run,name="hanui-reminders",daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                apps = self.root.accounts.all_apps() if self.root.accounts else [self.root]
            except Exception:
                print("Hanui notification account lookup temporarily unavailable",flush=True)
                self.stop_event.wait(30)
                continue
            for app in apps:
                try:
                    app.push.tick(app)
                except Exception:
                    # No patient text, provider bodies or credentials in scheduler logs.
                    print("Hanui notification delivery temporarily unavailable",flush=True)
            self.stop_event.wait(30)

    def stop(self):
        self.stop_event.set()
