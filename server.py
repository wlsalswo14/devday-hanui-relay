"""Loopback-only MVP: chat, persistent self-reports, grounded knowledge retrieval."""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from codex_bridge import CodexChat, ModelError
from google_bridge import GemmaChat, MODEL, EFFORT
from request_lifecycle import RequestManager, RequestCancelled, check_cancelled
from store import Store
from care import text, local_time
from reminders import Reminders
from report_documents import ReportDocuments

ROOT = Path(__file__).resolve().parent


def demo_memories(message: str):
    if re.search(r"친구|어머니|엄마|아버지|아빠|예를|가정|라면|자면|먹으면|마시면", message):
        return []
    checks = {
        "sleep": r"(?:잠|자고|자요|자는|수면|잤).*(?:시간|못|적)|(?:\d+\s*시간).*(?:자|잠|수면)",
        "stress": r"스트레스.*(?:많|받|있|심)|긴장.*(?:돼|되|해)",
        "caffeine": r"커피.*(?:잔|마셔|마시|먹)|카페인.*(?:먹|마시|섭취)",
        "diet": r"(?:아침|점심|저녁|식사).*(?:거르|먹|불규칙)",
        "activity": r"(?:산책|운동|걷기).*(?:해|했|분|시간)",
        "symptom": r"(?:피곤|피로|불편|아파|아프).*(?:해|해요|느껴|있)|(?:피곤해|아파요)",
        "goal": r"(?:목표|기록할게|기록해줘|관리해줘)",
    }
    return [{"category": category, "summary": message[:180], "quote": message}
            for category, pattern in checks.items() if re.search(pattern, message)]


def demo_response(message, history, memories, sources):
    """Explicitly labelled deterministic preview, never presented as model inference."""
    additions = demo_memories(message)
    if re.search(r"아까|기억|지난|몇\s*시간", message) and not additions:
        sleep = [m for m in memories if m["category"] == "sleep"]
        if sleep:
            reply = f'이전에 “{sleep[-1]["quote"]}”라고 이야기했어요. 사용자 발언으로 기록되어 있어요. 지금은 그때와 달라진 점이 있나요?'
        elif memories:
            reply = f'최근에는 “{memories[-1]["quote"]}”라고 이야기했어요. 이 기록에서 이어서 살펴볼까요?'
        else:
            reply = "아직 저장된 생활기록이 없어요. 최근 수면이나 식사 패턴부터 이야기해 줄래요?"
        return {"reply": reply, "source_ids": [], "memories": additions}
    if re.search(r"예약|병원|캘린더|일정", message):
        return {"reply": "Luna High 대화에서 방문할 지역과 조건을 알려주면 병원 정보를 찾아 전화·예약 링크로 연결해요. 병원에서 확정을 받은 뒤 알려주면 일정에 남길 수 있어요. 샘플 대화는 실제 정보를 찾지 않아요.",
                "source_ids": [], "memories": additions}
    intro = "이야기한 내용을 생활기록에 남겼어요." if additions else "관련 자료를 찾아봤어요."
    if sources:
        body = sources[0]["body"]
        reply = f'{intro}\n\n{body}\n\n'
        if sources[0]["category"] == "herb":
            reply += "이 자료는 약재의 기원 정보예요. 개인에게 맞는 약재나 복용량을 판단하는 자료는 아니에요. 다른 약재의 정보도 찾아볼까요?"
        elif any(m["category"] == "sleep" for m in additions):
            reply += "이런 수면 패턴은 언제부터 이어졌나요?"
        elif "미병" in message:
            reply += "특정 상태로 단정하기보다, 최근 불편함과 생활 변화를 먼저 기록해볼까요?"
        else:
            reply += "최근 생활에서 가장 달라진 점은 무엇인가요?"
        # Only cite the record actually included in the deterministic answer.
        return {"reply": reply, "source_ids": [sources[0]["id"]], "memories": additions}
    return {"reply": intro + " 현재 작은 자료 DB에는 이 질문에 직접 답할 자료가 없어요. 최근 수면·식사·활동에서 달라진 점을 알려주면 기록을 이어갈 수 있어요.",
            "source_ids": [], "memories": additions}


class App:
    def __init__(self, runtime=None, seed=None, model=None):
        runtime = runtime or ROOT / ".runtime"
        self.store = Store(runtime / "hanui.sqlite3", seed or ROOT / "data" / "knowledge.seed.json")
        self.model = model or GemmaChat(runtime)
        self.codex_enabled = self.model.available()
        self.lock = threading.Lock()
        self.requests = RequestManager()
        self.care = self.store.care
        self.reminders = Reminders(self.store, self.model)
        self.report_documents = ReportDocuments(self.store)

    def web_search(self, session_id, body, kind):
        self.store.get_session(session_id)
        query = text(body.get("query"), "검색어", 350)
        if not hasattr(self.model, "search_web"):
            raise ModelError("웹 검색 모델이 연결되지 않았어요.")
        if not self.lock.acquire(timeout=.5):
            raise ValueError("이전 AI 응답을 기다리고 있어요.")
        try:
            if isinstance(self.model, CodexChat):
                self.model.lookup_context = {}
            result = self.model.search_web(query, kind)
            with self.store.connect():
                check_cancelled()
                self.care.save_search(session_id, kind, result)
                dashboard = self.care.dashboard(session_id)
                check_cancelled()
                return dashboard
        finally:
            self.lock.release()

    def care_action(self, session_id, kind, body, item=None):
        if not self.lock.acquire(timeout=.5):
            raise ValueError("AI 응답이 끝난 뒤 기록을 변경할 수 있어요.")
        try:
            if kind == "checkins" and not item:
                return self.care.checkin(session_id, body)
            if kind == "goals":
                return self.care.tick(session_id, item, body) if item else self.care.goal(session_id, body)
            if kind == "guidance" and not item:
                with self.store.connect():
                    care=self.store.guidance.create(session_id, body)
                    if body.get("start_conversation"):
                        mode=body.get("mode","codex")
                        if mode not in {"codex","demo"}: raise ValueError("지원하지 않는 대화 방식이에요.")
                        plan=care["guidance"]["plans"][-1]
                        citations=[]
                        if mode=="codex":
                            if not hasattr(self.model,"start_checkin"): raise ModelError("첫 확인 질문 모델이 연결되지 않았어요.")
                            if isinstance(self.model,CodexChat):
                                keywords=self.model.retrieval_keywords(plan["body"]+" "+plan.get("assessment",""),[],[plan])
                                sources=self.store.search_fulltext(keywords,4 if isinstance(self.model,GemmaChat) else 8)
                                result=self.model.start_checkin(plan,sources)
                                question=result["reply"]
                                citations=self.citation_records(result,sources,mode)
                            else:
                                question=self.model.start_checkin(plan)
                        else:
                            question="[샘플 질문] 한의사 선생님의 생활 지침을 함께 살펴볼게요. 어젯밤에는 몇 시에 주무셨어요?"
                        check_cancelled()
                        self.store.guidance.opening(session_id,plan["id"],question,mode,citations)
                    check_cancelled()
                return self.care.dashboard(session_id)
            if kind == "events":
                return self.care.event(session_id, body, item)
            if kind == "bookings":
                return self.care.booking_status(session_id, item, body) if item else self.care.booking(session_id, body)
            raise ValueError("지원하지 않는 요청이에요.")
        finally:
            self.lock.release()

    def calendar_action(self, session_id, action, message):
        """Execute a session-owned, explicitly requested local calendar change."""
        quote = action.get("instruction_quote", "")
        if not quote or quote not in message:
            raise ValueError("변경할 내용을 대화에서 구체적으로 알려주세요.")
        if re.search(r"(?:삭제|취소|추가|수정|예약)하면|예를\s*들어|가정|만약|(?:삭제|취소|추가|수정|예약)하지\s*마|(?:빼|넣|옮기)지\s*마", quote):
            raise ValueError("가정이나 금지 요청으로는 캘린더를 변경하지 않아요.")
        kind, operation = action["type"], action.get("operation")
        care = self.care.dashboard(session_id)
        target_id = action.get("target_id", "")
        if kind == "event":
            if operation == "create":
                body = {k: action.get(k, "") for k in ("title", "start", "end", "location", "note")}
                before = {e["id"] for e in care["events"]}
                updated = self.care.event(session_id, body)
                event = next(e for e in updated["events"] if e["id"] not in before)
                outcome = "일정을 추가했어요."
            elif operation in {"update", "delete"}:
                event = next((e for e in care["events"] if e["id"] == target_id), None)
                if not event:
                    raise ValueError("현재 대화의 일정 하나를 지정해 주세요.")
                if operation == "delete":
                    self.care.delete(session_id, "events", target_id)
                    outcome = "일정을 삭제했어요."
                else:
                    body = {k: action.get(k) or event[k] for k in ("title", "start", "end", "location", "note")}
                    if action.get("start") and not action.get("end"):
                        body["end"] = (local_time(body["start"])+(local_time(event["end"])-local_time(event["start"]))).isoformat()
                    updated = self.care.event(session_id, body, target_id)
                    event = next(e for e in updated["events"] if e["id"] == target_id)
                    outcome = "일정을 수정했어요."
            else:
                raise ValueError("일정 추가·수정·삭제 중 하나를 요청해 주세요.")
            action["record_id"] = event["id"]
            detail = event["title"]+" · "+local_time(event["start"]).strftime("%m월 %d일 %H:%M")
        elif kind == "booking":
            if operation == "create":
                before = {b["id"] for b in care["bookings"]}
                updated = self.care.booking(session_id, {k: action.get(k, "") for k in ("search_id", "hospital_id", "start", "note")})
                booking = next(b for b in updated["bookings"] if b["id"] not in before)
                outcome = "예약 준비를 저장했어요. 병원 접수는 전화·예약 링크에서 완료해 주세요."
            else:
                booking = next((b for b in care["bookings"] if b["id"] == target_id), None)
                if not booking:
                    raise ValueError("현재 대화의 예약 기록 하나를 지정해 주세요.")
                if operation == "update":
                    body = {"start": action.get("start") or booking["start"]}
                    if action.get("note"):
                        body["note"] = action["note"]
                    updated = self.care.update_booking(session_id, target_id, body)
                    outcome = "방문 희망 시간을 변경했어요. 병원과 변경 시간을 확인해 주세요."
                elif operation == "cancel":
                    updated = self.care.booking_status(session_id, target_id, {"status": "cancelled", "local_only": True})
                    outcome = "앱의 예약 기록과 방문 일정을 취소했어요. 실제 예약은 병원에도 취소를 요청해 주세요."
                elif operation == "confirm":
                    if re.search(r"아직|안\s*(?:됐|받|했)|않|못|아니|아님|미확정|확정해|확정할|확정되면", quote) or not re.search(r"확정.{0,12}(?:됐|되었|받|했|이야|이에요)|예약.{0,8}(?:완료|했|됐)", quote):
                        raise ValueError("병원에서 예약 확정을 받았는지 알려주세요. 앱에서 병원 예약을 확정할 수는 없어요.")
                    updated = self.care.booking_status(session_id, target_id, {"status": "confirmed", "confirmation": quote[:300], "confirmed_by_user": True})
                    outcome = "병원에서 확정받았다는 말씀을 기록하고 방문 일정을 추가했어요."
                else:
                    raise ValueError("예약 준비·시간 변경·확정 기록·취소 중 하나를 요청해 주세요.")
                booking = next(b for b in updated["bookings"] if b["id"] == target_id)
            action["record_id"] = booking["id"]
            detail = booking["hospital"]["name"]+" · "+local_time(booking["start"]).strftime("%m월 %d일 %H:%M")
        else:
            raise ValueError("캘린더 요청을 확인해 주세요.")
        action.update(completed=True, label="캘린더에서 보기", outcome=outcome+"\n"+detail)
        return action["outcome"]

    def citation_records(self, result, sources, mode):
        citations=[dict(s) for s in sources if s["id"] in result["source_ids"]]
        for source in citations:
            source["citations"]=[dict(c) for c in result.get("citations",[]) if c["source_id"]==source["id"]]
            for citation in source["citations"]:
                if citation.get("reading"):
                    citation["reading_origin"]=("google" if isinstance(self.model,GemmaChat) else "luna") if isinstance(self.model,CodexChat) and mode=="codex" else "demo"
        return citations

    def chat(self, session_id, body):
        message, mode = body.get("message"), body.get("mode", "codex")
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError("1~2,000자 안에서 이야기를 입력해 주세요.")
        if mode not in {"codex", "demo"}:
            raise ValueError("지원하지 않는 대화 방식이에요.")
        if not self.lock.acquire(timeout=.5):
            raise ValueError("이전 답변을 기다리고 있어요. 답변이 끝나면 이어서 이야기해 주세요.")
        try:
            session = self.store.get_session(session_id)
            if len(session["messages"]) >= 200:
                raise ValueError("대화가 길어졌어요. 새 대화를 시작해 주세요.")
            if mode == "codex" and isinstance(self.model, GemmaChat) and self.model.browser.requested(message):
                result = self.model.browse(message.strip())
                check_cancelled()
                with self.store.connect():
                    saved = self.store.save_turn(session_id, message.strip(), result["reply"], [], [], mode, [], [])
                    check_cancelled()
                    return saved
            # Current query takes priority; short references may inherit recent context.
            query = message
            if len(message.strip()) < 12 and re.search(r"그거|더|응|그래|관련", message):
                past = [m["content"] for m in session["messages"] if m["role"] == "user"]
                if past:
                    query += " " + past[-1]
            if mode == "codex" and hasattr(self.model, "retrieval_keywords"):
                if isinstance(self.model,CodexChat):
                    keywords=self.model.retrieval_keywords(message.strip(),session["messages"],session["care"]["guidance"]["plans"])
                else:
                    keywords = self.model.retrieval_keywords(message.strip(), session["messages"])
                sources = self.store.search_fulltext(keywords,4 if isinstance(self.model,GemmaChat) else 8)
            else:
                sources = self.store.search(query)
            if isinstance(self.model, CodexChat):
                care = session["care"]
                self.model.care_context = {key: care[key] for key in ("today", "summary", "goals", "events", "bookings", "conflicts")}
                self.model.care_context["checkins"] = care["checkins"][:7]
                self.model.care_context["public_searches"] = care["searches"]
                self.model.care_context["clinician_instructions"] = [i for i in care["guidance"]["instructions"] if i["active"]]
                self.model.care_context["clinician_plans"] = care["guidance"]["plans"]
                self.model.care_context["patient_observations"] = care["guidance"]["observations"][-20:]
            responder = self.model.respond if mode == "codex" else demo_response
            result = responder(message.strip(), session["messages"], session["memories"], sources)
            check_cancelled()
            actions = result.get("actions", [])
            observations = self.store.guidance.validate(session_id, message.strip(), result.get("observations", []))
            # Luna selects read-only information tasks from the conversation.
            # Calendar writes run after information lookup and are saved with the chat turn.
            if mode == "codex" and hasattr(self.model, "search_web"):
                for action in actions[:2]:
                    kind = action.get("type")
                    lookup = kind in {"hospitals", "web"} and bool(action.get("query"))
                    if lookup:
                        try:
                            if isinstance(self.model, CodexChat):
                                self.model.lookup_context = {"question": message.strip(), "db_records": sources}
                            found = self.model.search_web(action["query"][:350], kind)
                            check_cancelled()
                            action["result"] = found
                            action["completed"] = True
                            action["label"] = "찾아본 정보"
                            result["reply"] += "\n\n" + found["summary"]
                        except RequestCancelled:
                            raise
                        except ModelError:
                            action["error"] = "정보를 확인하지 못했어요. 대화에서 다시 요청해 주세요."
                    # At most one web request per conversation turn.
                    if lookup:
                        break
            citations=self.citation_records(result,sources,mode)
            with self.store.connect():
                check_cancelled()
                for action in actions:
                    if action.get("completed") and action.get("type") in {"hospitals","web"}:
                        action["search_id"] = self.care.save_search(session_id, action["type"], action["result"])
                outcomes = []
                if mode == "codex":
                    for action in actions:
                        if action["type"] in {"event", "booking"} and action.get("operation"):
                            outcomes.append(self.calendar_action(session_id, action, message.strip()))
                if outcomes:
                    if citations or any(a["type"] not in {"event", "booking", "calendar"} for a in actions):
                        result["reply"] += "\n\n"+"\n\n".join(outcomes)
                    else:
                        result["reply"] = "\n\n".join(outcomes)
                saved = self.store.save_turn(session_id, message.strip(), result["reply"], citations,
                                            result["memories"], mode, actions, observations)
                check_cancelled()
                return saved
        finally:
            self.lock.release()


class Handler(BaseHTTPRequestHandler):
    app: App
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # A closed browser tab is a normal disconnect, including keep-alive sockets.
            # Completed DB writes remain available when the user returns.
            pass

    def respond(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.validate_origin():
            return self.respond(403, {"error": "이 주소에서 요청할 수 없어요."})
        path = urlparse(self.path).path
        if path == "/api/sessions":
            return self.respond(200, {"sessions": self.app.store.list_sessions()})
        if path == "/api/config":
            return self.respond(200, {"codex_enabled": self.app.codex_enabled,
                "knowledge_count": self.app.store.knowledge_count(),
                "model": getattr(self.app.model,"model_name",MODEL),
                "provider": getattr(self.app.model,"provider","test"),
                "effort": getattr(self.app.model,"effort",EFFORT)})
        if path == "/api/knowledge":
            query = parse_qs(urlparse(self.path).query)
            try:
                return self.respond(200, {"records": self.app.store.library(query.get("q", [""])[0][:300], query.get("category", [""])[0])})
            except ValueError as exc:
                return self.respond(400, {"error": str(exc)})
        document = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/report", path)
        if document:
            try:
                return self.respond(200, self.app.report_documents.get(document[1]))
            except KeyError:
                return self.respond(404, {"error": "대화를 찾지 못했어요."})
        report = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/visit-report", path)
        if report:
            try:
                query = parse_qs(urlparse(self.path).query)
                return self.respond(200, self.app.store.guidance.report(report[1], query.get("end", [None])[0]))
            except KeyError:
                return self.respond(404, {"error": "대화를 찾지 못했어요."})
            except ValueError as exc:
                return self.respond(400, {"error": str(exc)})
        match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/(care|calendar\.ics|export)", path)
        if match:
            try:
                if match[2] == "calendar.ics":
                    return self.respond(200, self.app.care.calendar(match[1]), "text/calendar; charset=utf-8")
                return self.respond(200, self.app.care.dashboard(match[1]) if match[2] == "care" else self.app.store.get_session(match[1]))
            except KeyError:
                return self.respond(404, {"error": "대화를 찾지 못했어요."})
        match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})", path)
        if match:
            try:
                return self.respond(200, self.app.store.get_session(match[1]))
            except KeyError:
                return self.respond(404, {"error": "대화를 찾지 못했어요."})
        files = {"/": "index.html", "/app.css": "app.css", "/shell.css": "shell.css", "/report-print.css": "report-print.css", "/app.js": "app.js", "/care.js": "care.js", "/calendar.js": "calendar.js", "/guidance.js": "guidance.js", "/reminders.js": "reminders.js", "/report.js": "report.js", "/favicon.svg": "favicon.svg"}
        if path in files:
            file = ROOT / "static" / files[path]
            if file.exists():
                content_type = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}[file.suffix]
                return self.respond(200, file.read_bytes(), content_type)
        return self.respond(404, {"error": "페이지를 찾지 못했어요."})

    def validate_origin(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        return host in expected and (not origin or origin == f"http://{host}")

    def do_POST(self):
        if not self.validate_origin():
            return self.respond(403, {"error": "이 주소에서 요청할 수 없어요."})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.respond(415, {"error": "JSON 요청만 받을 수 있어요."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = 100000 if re.fullmatch(r"/api/sessions/[a-f0-9]{32}/report", urlparse(self.path).path) else 20000
            if not 0 < length <= limit:
                self.close_connection = True
                return self.respond(413, {"error": "요청이 너무 크거나 비어 있어요."})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("요청 형식이 올바르지 않아요.")
            path = urlparse(self.path).path
            cancel = re.fullmatch(r"/api/requests/([a-f0-9]{32})/cancel", path)
            if cancel:
                self.app.requests.cancel(cancel[1])
                return self.respond(200, {"cancelled": True})
            if path == "/api/sessions":
                return self.respond(201, self.app.store.create_session())
            document = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/report", path)
            if document:
                return self.respond(200, self.app.report_documents.save(document[1], body))
            match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/title", path)
            if match:
                if not self.app.lock.acquire(blocking=False):
                    raise ValueError("AI 응답이 끝난 뒤 이름을 바꿀 수 있어요.")
                try:
                    return self.respond(200, self.app.store.rename_session(match[1], body.get("title")))
                finally:
                    self.app.lock.release()
            match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/chat", path)
            if match:
                with self.app.requests.scope(self.connection, body.get("request_id")):
                    return self.respond(200, self.app.chat(match[1], body))
            match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/reminders", path)
            if match:
                with self.app.requests.scope(self.connection, body.get("request_id")):
                    return self.respond(200, self.app.reminders.poll(match[1], body.get("dismiss")))
            match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/(checkins|goals|events|bookings|hospitals|web|guidance)(?:/([a-f0-9]{32}))?", path)
            if match:
                session_id, kind, item = match.groups()
                if kind in {"hospitals", "web"} and not item:
                    with self.app.requests.scope(self.connection, body.get("request_id")):
                        return self.respond(200, self.app.web_search(session_id, body, kind))
                if kind == "guidance" and body.get("start_conversation"):
                    with self.app.requests.scope(self.connection, body.get("request_id")):
                        return self.respond(200, self.app.care_action(session_id, kind, body, item))
                return self.respond(200, self.app.care_action(session_id, kind, body, item))
            return self.respond(404, {"error": "요청을 찾지 못했어요."})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.respond(400, {"error": str(exc) if not isinstance(exc, json.JSONDecodeError) else "요청 형식이 올바르지 않아요."})
        except KeyError:
            return self.respond(404, {"error": "대화를 찾지 못했어요."})
        except RequestCancelled as exc:
            return self.respond(499, {"error": str(exc)})
        except ModelError as exc:
            return self.respond(503, {"error": str(exc)})
        except Exception:
            return self.respond(500, {"error": "요청을 처리하지 못했어요. 다시 시도해 주세요."})

    def do_DELETE(self):
        if not self.validate_origin():
            return self.respond(403, {"error": "이 주소에서 요청할 수 없어요."})
        child = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/(goals|events|memories|checkins|patient-records)/([a-f0-9]{32}|\d{4}-\d{2}-\d{2})", urlparse(self.path).path)
        if child:
            try:
                if not self.app.lock.acquire(blocking=False):
                    return self.respond(409, {"error": "AI 응답이 끝난 뒤 기록을 삭제할 수 있어요."})
                try:
                    return self.respond(200, self.app.care.delete(*child.groups()))
                finally:
                    self.app.lock.release()
            except KeyError:
                return self.respond(404, {"error": "기록을 찾지 못했어요."})
            except ValueError as exc:
                return self.respond(400, {"error": str(exc)})
        match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})", urlparse(self.path).path)
        if not match:
            return self.respond(404, {"error": "요청을 찾지 못했어요."})
        if not self.app.lock.acquire(blocking=False):
            return self.respond(409, {"error": "답변이 끝난 뒤 대화를 삭제할 수 있어요."})
        try:
            self.app.store.delete_session(match[1])
            return self.respond(200, {"deleted": True})
        except KeyError:
            return self.respond(404, {"error": "대화를 찾지 못했어요."})
        finally:
            self.app.lock.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.app = App()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Hanui Relay: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
