"""Google ID-token login and isolated per-account applications."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from contextlib import contextmanager


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_value(header, name):
    jar = SimpleCookie()
    try:
        jar.load(header or "")
        return jar[name].value if name in jar else ""
    except Exception:
        return ""


class GoogleAccounts:
    def __init__(self, root, client_id=None, verifier=None):
        self.root = root
        config = root.runtime / "google-login.json"
        self.client_id = client_id if client_id is not None else os.environ.get("HANUI_GOOGLE_CLIENT_ID", "")
        if not self.client_id and config.exists():
            self.client_id = json.loads(config.read_text(encoding="utf-8-sig")).get("client_id","")
        if self.client_id and not re.fullmatch(r"[a-zA-Z0-9.-]+\.apps\.googleusercontent\.com", self.client_id):
            raise ValueError("Google 웹 OAuth 클라이언트 ID를 확인해 주세요.")
        self.verifier = verifier or self.verify
        self.path = root.runtime / "accounts.sqlite3"
        self.lock = threading.RLock()
        self.apps = {}
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS logins (token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS challenges (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            """)

    @property
    def enabled(self):
        return bool(self.client_id)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def challenge(self):
        value = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM challenges WHERE expires<?",(time.time(),))
            db.execute("INSERT INTO challenges VALUES(?,?)",(digest(value),time.time()+300))
        return value

    def verify(self, token):
        try:
            from google.oauth2 import id_token
            from google.auth.transport.requests import Request
            return id_token.verify_oauth2_token(token, Request(), self.client_id)
        except ImportError:
            raise ValueError("Google 로그인 모듈을 설치해 주세요: pip install -r requirements.txt") from None
        except Exception:
            raise ValueError("Google 로그인을 확인하지 못했어요. 다시 로그인해 주세요.") from None

    def login(self, credential, nonce):
        if not self.enabled:
            raise ValueError("Google OAuth 클라이언트 ID 설정이 필요해요.")
        if not isinstance(credential,str) or not credential or len(credential)>16000 or not nonce:
            raise ValueError("로그인 요청을 확인해 주세요.")
        with self.connect() as db:
            row = db.execute("SELECT expires FROM challenges WHERE token_hash=?",(digest(nonce),)).fetchone()
            if not row or row[0]<time.time():
                raise ValueError("로그인 요청이 만료됐어요. 다시 시도해 주세요.")
        payload = self.verifier(credential)
        if payload.get("nonce") != nonce or payload.get("aud") != self.client_id or payload.get("iss") not in {"accounts.google.com","https://accounts.google.com"} or float(payload.get("exp",0))<=time.time():
            raise ValueError("Google 로그인 정보가 일치하지 않아요.")
        sub = payload.get("sub")
        if not isinstance(sub,str) or not sub or len(sub)>255:
            raise ValueError("Google 계정 식별자를 확인하지 못했어요.")
        account = digest("google:"+sub)
        user = {"id":account,"name":str(payload.get("name","사용자"))[:100],"email":str(payload.get("email",""))[:254]}
        token = secrets.token_urlsafe(48)
        with self.connect() as db:
            # Consume exactly once even when concurrent login requests race.
            if not db.execute("DELETE FROM challenges WHERE token_hash=? AND expires>?",(digest(nonce),time.time())).rowcount:
                raise ValueError("이미 사용한 로그인 요청이에요.")
            db.execute("INSERT INTO accounts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",(account,json.dumps(user,ensure_ascii=False)))
            db.execute("DELETE FROM logins WHERE expires<?",(time.time(),))
            db.execute("INSERT INTO logins VALUES(?,?,?)",(digest(token),account,time.time()+30*86400))
        return token,user

    def user(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute("SELECT a.data FROM accounts a JOIN logins l ON a.id=l.account_id WHERE l.token_hash=? AND l.expires>?",(digest(token),time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM logins WHERE token_hash=?",(digest(token),))

    def app_for(self, user):
        from server import App
        from google_bridge import GemmaChat
        with self.lock:
            if user["id"] not in self.apps:
                runtime = self.root.runtime / "users" / user["id"]
                runtime.mkdir(parents=True,exist_ok=True)
                # Shared read-only knowledge configuration, never copy patient data or API keys.
                config = self.root.runtime / "knowledge-db.json"
                if config.exists():
                    (runtime / "knowledge-db.json").write_bytes(config.read_bytes())
                model = self.root.model
                if isinstance(model,GemmaChat):
                    model = GemmaChat(runtime,key=model.key,effort=model.effort)
                    model.browser_search_enabled = self.root.model.browser_search_enabled
                self.apps[user["id"]] = App(runtime,seed=self.root.store.seed,model=model)
            return self.apps[user["id"]]

    def all_apps(self):
        if not self.enabled:
            return [self.root]
        with self.connect() as db:
            users = [json.loads(r[0]) for r in db.execute("SELECT data FROM accounts")]
        return [self.app_for(user) for user in users]
