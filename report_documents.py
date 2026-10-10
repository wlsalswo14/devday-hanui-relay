"""Editable plain-text report documents, isolated by conversation."""
from datetime import datetime, timezone


class ReportDocuments:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS report_documents (session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE, title TEXT NOT NULL, body TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)")

    def get(self, session_id):
        with self.store.connect() as db:
            self.store.care.owner(db, session_id)
            row = db.execute("SELECT title,body,revision,updated_at FROM report_documents WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else {"title": "", "body": "", "revision": 0, "updated_at": ""}

    def save(self, session_id, body):
        title, content, revision = body.get("title"), body.get("body"), body.get("revision")
        if not isinstance(title, str) or len(title)>160 or not isinstance(content, str) or len(content)>20000:
            raise ValueError("제목은 160자, 본문은 20,000자까지 작성할 수 있어요.")
        if type(revision) is not int or revision<0:
            raise ValueError("저장할 리포트를 다시 확인해 주세요.")
        updated = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as db:
            self.store.care.owner(db, session_id)
            if revision == 0:
                changed = db.execute("INSERT OR IGNORE INTO report_documents VALUES(?,?,?,?,?)", (session_id,title,content,1,updated)).rowcount
            else:
                changed = db.execute("UPDATE report_documents SET title=?,body=?,revision=revision+1,updated_at=? WHERE session_id=? AND revision=?", (title,content,updated,session_id,revision)).rowcount
            if not changed:
                raise ValueError("다른 창에서 리포트가 변경됐어요. 현재 내용을 복사해 두고 새로고침해 주세요.")
        return {"title": title, "body": content, "revision": revision+1, "updated_at": updated}
