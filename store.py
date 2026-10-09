"""Small SQLite knowledge library and per-session conversation storage."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from care import CareStore
from guidance import GuidanceStore


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path, seed: Path):
        self.path, self.seed = path, seed
        self._connections = threading.local()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.seed_mtime = None
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL, content TEXT NOT NULL, mode TEXT NOT NULL,
                    sources TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    category TEXT NOT NULL, summary TEXT NOT NULL, quote TEXT NOT NULL,
                    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, UNIQUE(session_id, category, quote));
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, seq);
                CREATE INDEX IF NOT EXISTS memories_session ON memories(session_id, seq);
            """)
            if "actions" not in {r[1] for r in db.execute("PRAGMA table_info(messages)")}:
                db.execute("ALTER TABLE messages ADD COLUMN actions TEXT NOT NULL DEFAULT '[]'")
            if "title" not in {r[1] for r in db.execute("PRAGMA table_info(sessions)")}:
                db.execute("ALTER TABLE sessions ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        self.care = CareStore(self)
        self.guidance = GuidanceStore(self)
        self.refresh_knowledge()

    @contextmanager
    def connect(self):
        active = getattr(self._connections, "active", None)
        if active is not None:
            yield active
            return
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            self._connections.active = db
            with db:
                yield db
        finally:
            self._connections.active = None
            db.close()

    def refresh_knowledge(self):
        if not self.seed.exists():
            return
        seeds = [self.seed]
        classics = self.seed.parent / "classics.seed.json"
        if self.seed.name == "knowledge.seed.json" and classics.exists():
            seeds.append(classics)
        mtime = tuple((str(p), p.stat().st_mtime_ns) for p in seeds)
        if mtime == self.seed_mtime:
            return
        records = []
        for seed in seeds:
            loaded = json.loads(seed.read_text(encoding="utf-8-sig"))
            if not isinstance(loaded, list):
                raise ValueError("Knowledge seed must be a list")
            records.extend(loaded)
        required = {"id", "title", "category", "tags", "body", "source_url", "publisher",
                    "evidence_level", "limitations", "retrieved_at"}
        if not isinstance(records, list) or len(records) > 1000:
            raise ValueError("Knowledge seed must be a list of up to 1000 records")
        seen = set()
        for record in records:
            if not isinstance(record, dict) or not required <= record.keys():
                raise ValueError("Knowledge record is missing fields")
            if any(not isinstance(record[k], str) or not record[k].strip() for k in required - {"tags"}):
                raise ValueError("Knowledge metadata must contain non-empty strings")
            if not isinstance(record["tags"], list) or any(not isinstance(t, str) for t in record["tags"]):
                raise ValueError("Knowledge tags must be strings")
            if record["category"] not in {"concept", "lifestyle", "herb", "resource", "classical"}:
                raise ValueError("Unsupported knowledge category")
            if urlparse(record["source_url"]).scheme not in {"http", "https"}:
                raise ValueError("Invalid source URL")
            if record["id"] in seen:
                raise ValueError("Duplicate knowledge ID")
            seen.add(record["id"])
            if record["category"] == "classical" and any(
                not isinstance(record.get(k), str) or not record[k].strip()
                for k in ("book", "section", "location", "source_revision", "license")
            ):
                raise ValueError("Classical text requires exact location and attribution")
        with self.connect() as db:
            db.execute("DELETE FROM knowledge")
            db.executemany("INSERT INTO knowledge VALUES (?,?)", [
                (r["id"], json.dumps(r, ensure_ascii=False)) for r in records
            ])
            db.execute("CREATE TABLE IF NOT EXISTS knowledge_text (id TEXT PRIMARY KEY REFERENCES knowledge(id) ON DELETE CASCADE, text TEXT NOT NULL)")
            db.execute("DELETE FROM knowledge_text")
            db.executemany("INSERT INTO knowledge_text VALUES (?,?)", [
                (r["id"], " ".join([r["title"], r["body"], r.get("summary", ""), r.get("book", ""), r.get("section", ""), " ".join(r["tags"])]).lower())
                for r in records
            ])
        self.seed_mtime = mtime

    def knowledge_count(self):
        self.refresh_knowledge()
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

    def search(self, query: str, limit: int = 3):
        self.refresh_knowledge()
        with self.connect() as db:
            records = [json.loads(r[0]) for r in db.execute("SELECT record FROM knowledge")]
        expanded = query.lower()
        synonyms = {"잠": "수면", "피곤": "수면 생활관리", "피로": "생활관리",
                    "밥": "식사", "긴장": "스트레스", "커피": "생활관리", "걷": "운동"}
        for word, expansion in synonyms.items():
            if word in expanded:
                expanded += " " + expansion
        herb_names = {r["tags"][0] for r in records if r["category"] == "herb" and r["tags"]}
        named_herbs = {name for name in herb_names if name in query}
        ranked = []
        for record in records:
            if named_herbs and (record["category"] != "herb" or not named_herbs.intersection(record["tags"])):
                continue
            score = sum(5 for tag in record["tags"] if tag.lower() in expanded)
            score += sum(1 for token in re.findall(r"[가-힣A-Za-z]{2,}", expanded)
                         if token in record["title"])
            if score:
                ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [r for _, r in ranked[:limit]]

    def library(self, query="", category=""):
        if category and category not in {"concept", "lifestyle", "herb", "resource", "classical"}:
            raise ValueError("자료 종류를 확인해 주세요.")
        self.refresh_knowledge()
        if query:
            records = self.search_fulltext([query], 1000)
        else:
            with self.connect() as db:
                records = [json.loads(r[0]) for r in db.execute("SELECT record FROM knowledge ORDER BY id")]
        return [r for r in records if not category or r["category"] == category]

    def search_fulltext(self, keywords, limit=8):
        """Search every stored passage, including original text and Korean readings.

        Parameterized substring matching preserves Korean/Chinese phrases without
        an external tokenizer; ranking and corpus diversity bound the model context.
        """
        self.refresh_knowledge()
        terms = list(dict.fromkeys(t.strip().lower() for t in keywords
                                  if isinstance(t, str) and 1 < len(t.strip()) <= 80))[:12]
        if not terms:
            return []
        clauses = " OR ".join("instr(t.text, ?) > 0" for _ in terms)
        with self.connect() as db:
            rows = db.execute("SELECT k.record,t.text FROM knowledge k JOIN knowledge_text t ON k.id=t.id WHERE " + clauses, terms).fetchall()
        ranked = []
        for row in rows:
            record = json.loads(row["record"])
            score = sum(1 for term in terms if term in row["text"])
            score += sum(3 for term in terms if term in record["title"].lower() or term in " ".join(record["tags"]).lower())
            ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        selected = [r for _, r in ranked[:limit]]
        # Include both historical and modern evidence when either corpus matches.
        if limit >= 2:
            for classical in (True, False):
                candidates = [r for _, r in ranked if (r["category"] == "classical") == classical]
                if candidates and not any((r["category"] == "classical") == classical for r in selected):
                    selected[-1] = candidates[0]
        return selected

    def create_session(self):
        session_id = uuid.uuid4().hex
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] >= 100:
                raise ValueError("대화가 너무 많아요. 사용하지 않는 대화를 삭제해 주세요.")
            db.execute("INSERT INTO sessions(id,created_at) VALUES (?,?)", (session_id, now()))
        return self.get_session(session_id)

    def list_sessions(self):
        with self.connect() as db:
            rows = db.execute("""SELECT s.id,s.created_at,s.title,
                (SELECT content FROM messages WHERE session_id=s.id AND role='user' ORDER BY seq LIMIT 1) AS first_message,
                COALESCE((SELECT MAX(created_at) FROM messages WHERE session_id=s.id),s.created_at) AS updated_at,
                (SELECT COUNT(*) FROM messages WHERE session_id=s.id AND role='user') AS turns
                FROM sessions s ORDER BY updated_at DESC,s.id""").fetchall()
        return [{"id": r["id"], "title": r["title"] or (r["first_message"] or "새 대화").replace("\n", " ")[:40],
                 "created_at": r["created_at"], "updated_at": r["updated_at"], "turns": r["turns"]} for r in rows]

    def rename_session(self, session_id, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise ValueError("대화 이름은 1~80자로 입력해 주세요.")
        with self.connect() as db:
            if not db.execute("UPDATE sessions SET title=? WHERE id=?", (title.strip(), session_id)).rowcount:
                raise KeyError(session_id)
        return self.get_session(session_id)

    def get_session(self, session_id: str):
        with self.connect() as db:
            session = db.execute("SELECT title FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not session:
                raise KeyError(session_id)
            messages = [dict(r) for r in db.execute(
                "SELECT id,role,content,mode,sources,actions,created_at FROM messages WHERE session_id=? ORDER BY seq",
                (session_id,))]
            memories = [dict(r) for r in db.execute(
                "SELECT id,category,summary,quote,message_id,created_at FROM memories WHERE session_id=? ORDER BY seq",
                (session_id,))]
        for message in messages:
            message["sources"] = json.loads(message["sources"])
            message["actions"] = json.loads(message["actions"])
        first_message = next((m["content"] for m in messages if m["role"] == "user"), "새 대화")
        care = self.care.dashboard(session_id)
        previous_user = None
        for message in messages:
            if message["role"] == "user": previous_user = message["id"]
            else: message["patient_evidence"] = [o for o in care["guidance"]["observations"] if o["message_id"] == previous_user]
        return {"id": session_id, "title": session["title"] or first_message.replace("\n", " ")[:40], "messages": messages, "memories": memories,
                "knowledge_count": self.knowledge_count(), "care": care}

    def save_turn(self, session_id, message, reply, sources, memories, mode, actions=None, observations=None):
        user_id = uuid.uuid4().hex
        timestamp = now()
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                raise KeyError(session_id)
            db.execute("INSERT INTO messages(id,session_id,role,content,mode,sources,created_at,actions) VALUES (?,?,?,?,?,?,?,?)",
                       (user_id,session_id,"user",message,mode,"[]",timestamp,"[]"))
            observation_ids = self.guidance.record(session_id,user_id,observations or [])
            if observation_ids:
                coaching = self.guidance.coach(session_id,observation_ids)
                if coaching:
                    if sources or actions:
                        reply=reply+"\n\n"+coaching
                    else:
                        questions=re.findall(r"[^.!?？\n]+[?？]",reply)
                        followup=questions[-1].strip() if questions else ""
                        reply=coaching+("\n\n"+followup if 0<len(followup)<=200 else "")
            db.execute("INSERT INTO messages(id,session_id,role,content,mode,sources,created_at,actions) VALUES (?,?,?,?,?,?,?,?)",
                       (uuid.uuid4().hex,session_id,"assistant",reply,mode,json.dumps(sources,ensure_ascii=False),timestamp,json.dumps(actions or [],ensure_ascii=False)))
            for memory in memories:
                db.execute("INSERT OR IGNORE INTO memories(id,session_id,category,summary,quote,message_id,created_at) VALUES (?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex, session_id, memory["category"], memory["summary"],
                            memory["quote"], user_id, timestamp))
        return self.get_session(session_id)

    def delete_session(self, session_id):
        with self.connect() as db:
            if not db.execute("DELETE FROM sessions WHERE id=?", (session_id,)).rowcount:
                raise KeyError(session_id)
