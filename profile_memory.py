"""Editable account-wide text memory; retrieval never promotes text to instructions."""
import hashlib
import re
import unicodedata
from datetime import datetime, timezone


class ProfileMemory:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS health_profile (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profile_chunks (id INTEGER PRIMARY KEY, body TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS profile_search USING fts5(body, tokenize='unicode61');
            """)

    def get(self):
        with self.store.connect() as db:
            row = db.execute("SELECT body,updated_at FROM health_profile WHERE id=1").fetchone()
        return {"text": row["body"] if row else "", "updated_at": row["updated_at"] if row else None}

    def save(self, body):
        if not isinstance(body, str) or len(body) > 30000:
            raise ValueError("건강 프로필은 30,000자 이내로 입력해 주세요.")
        if "\x00" in body:
            raise ValueError("프로필에 사용할 수 없는 문자가 있어요.")
        stamp = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as db:
            db.execute("INSERT INTO health_profile VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at", (body, stamp))
            db.execute("DELETE FROM profile_chunks")
            db.execute("DELETE FROM profile_search")
            offset = 0
            for line in body.splitlines(keepends=True):
                for start in range(0, len(line), 600):
                    piece = line[start:start+600]
                    if piece.strip():
                        row = db.execute("INSERT INTO profile_chunks(body,start,end) VALUES(?,?,?)", (piece, offset+start, offset+start+len(piece)))
                        db.execute("INSERT INTO profile_search(rowid,body) VALUES(?,?)", (row.lastrowid, piece))
                offset += len(line)
        return self.get()

    def search(self, query, limit=5):
        query = unicodedata.normalize("NFKC", str(query)).lower()[:2000]
        if len(query.strip()) < 2 or query.strip() in {"안녕", "안녕하세요", "고마워", "감사합니다"}:
            return []
        groups = [("약", "복용", "처방", "알레르기"), ("잠", "수면", "취침", "기상"),
                  ("소화", "식사", "배", "속", "복통"), ("커피", "카페인"), ("목표", "관리", "지침"),
                  ("이름", "별명", "나이", "생년"), ("운동", "산책", "활동")]
        terms = set(re.findall(r"[가-힣a-z0-9]{2,}", query))
        for group in groups:
            if any(term in query for term in group):
                terms.update(group)
        terms -= {"뭐야", "어떻게", "알려줘", "있나요", "프로필", "건강", "나에", "대한"}
        if not terms:
            return []
        with self.store.connect() as db:
            expression = " OR ".join('"'+term+'"*' for term in sorted(terms)[:30])
            hits = {r[0] for r in db.execute("SELECT rowid FROM profile_search WHERE profile_search MATCH ? ORDER BY bm25(profile_search) LIMIT 15", (expression,))}
            rows = list(db.execute("SELECT * FROM profile_chunks"))
        ranked = []
        for row in rows:
            content = row["body"].lower()
            score = sum(3 if len(term)>1 else 1 for term in terms if term in content)
            # Korean inflections often differ from stored nouns: retain meaningful bigrams.
            score += sum(.2 for term in terms if len(term)>2 for i in range(len(term)-1) if term[i:i+2] in content)
            if row["id"] in hits:
                score += 2
            if score >= 1:
                ranked.append((score, row))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["start"]))
        return [{"text": r["body"], "offset_start": r["start"], "offset_end": r["end"],
                 "source": "사용자 건강 프로필", "revision": hashlib.sha256(self.get()["text"].encode()).hexdigest()[:16]}
                for _, r in ranked[:limit]]
