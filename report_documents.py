"""Editable plain-text report documents, isolated by conversation."""
from datetime import datetime, timezone, timedelta
import json
from request_lifecycle import check_cancelled
from codex_bridge import ModelError


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

    def draft(self, session_id, body, model):
        session = self.store.get_session(session_id)
        instruction = body.get("instruction", "")
        current = body.get("current", {})
        if not isinstance(instruction,str) or len(instruction)>500 or not isinstance(current,dict):
            raise ValueError("정리 요청을 확인해 주세요.")
        if any(not isinstance(current.get(k,""),str) or len(current.get(k,""))>limit for k,limit in [("title",160),("body",20000)]):
            raise ValueError("작성 중인 리포트를 확인해 주세요.")
        sources = [{"id":m["id"],"kind":"patient_statement","date":datetime.fromisoformat(m["created_at"]).astimezone(timezone(timedelta(hours=9))).date().isoformat(),"text":m["content"]}
                   for m in session["messages"] if m["role"]=="user"][-30:]
        for checkin in session["care"]["checkins"][:14]:
            sources.append({"id":"checkin-"+checkin["date"],"kind":"lifestyle_record","date":checkin["date"],"text":json.dumps(checkin,ensure_ascii=False)})
        for plan in session["care"]["guidance"]["plans"][-5:]:
            sources.append({"id":"plan-"+plan["id"],"kind":"clinician_instruction","date":plan["starts_on"],"text":plan["body"]+"\n"+plan.get("assessment","")})
        if current.get("body", "").strip():
            sources.append({"id":"current-draft","kind":"user_written_draft","date":"","text":current["body"]})
        if not sources:
            raise ValueError("먼저 내용을 작성하거나 대화·생활 기록을 남겨 주세요.")
        if not hasattr(model,"draft_report") or not model.available():
            raise ModelError("에이전트 연결을 확인해 주세요.")
        parsed = model.draft_report({"request":instruction,"current_title":current.get("title",""),"sources":sources})
        check_cancelled()
        if not isinstance(parsed,dict):raise ModelError("리포트 초안 형식을 확인하지 못했어요.")
        title, sections = parsed.get("title"), parsed.get("sections")
        if not isinstance(title,str) or len(title)>160 or not isinstance(sections,list) or not 1<=len(sections)<=5:
            raise ModelError("리포트 초안 형식을 확인하지 못했어요.")
        by_id = {s["id"]:s for s in sources}; references=[]; parts=[]
        for section in sections:
            if not isinstance(section,dict) or not isinstance(section.get("heading"),str) or len(section["heading"])>100:
                raise ModelError("리포트 항목을 확인하지 못했어요.")
            lines=[]
            statements=section.get("statements")
            if not isinstance(statements,list) or not 1<=len(statements)<=6:
                raise ModelError("리포트 문장을 확인하지 못했어요.")
            for statement in statements:
                if not isinstance(statement,dict) or not isinstance(statement.get("text"),str) or not 1<=len(statement["text"])<=1000:
                    raise ModelError("리포트 문장을 확인하지 못했어요.")
                evidence=statement.get("evidence")
                if not isinstance(evidence,list) or not 1<=len(evidence)<=3:
                    raise ModelError("리포트 근거를 확인하지 못했어요.")
                numbers=[]
                for reference in evidence:
                    source = by_id.get(reference.get("source_id")) if isinstance(reference,dict) else None
                    quote=reference.get("quote") if isinstance(reference,dict) else None
                    if not source or not isinstance(quote,str) or not 2<=len(quote)<=120 or quote not in source["text"]:
                        raise ModelError("리포트 인용을 원문과 대조하지 못했어요. 다시 정리해 주세요.")
                    record={"source_id":source["id"],"kind":source["kind"],"date":source["date"],"quote":quote}
                    if record not in references:references.append(record)
                    numbers.append(str(references.index(record)+1))
                lines.append(statement["text"]+" ["+", ".join(numbers)+"]")
            parts.append(section["heading"]+"\n"+"\n".join(lines))
        evidence_text="\n".join(f'[{i+1}] {r["date"] or "작성 중인 리포트"} · “{r["quote"]}”' for i,r in enumerate(references))
        text="\n\n".join(parts)+"\n\n근거\n"+evidence_text
        if len(text)>20000:raise ModelError("리포트 초안이 너무 길어요. 범위를 줄여 주세요.")
        return {"title":title,"body":text,"references":references}
