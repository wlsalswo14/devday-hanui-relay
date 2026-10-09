"""Loopback-only MVP: chat, persistent self-reports, grounded knowledge retrieval."""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from codex_bridge import CodexChat, ModelError, MODEL, EFFORT
from store import Store
from care import text

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
        self.model = model or CodexChat(runtime)
        self.codex_enabled = self.model.available()
        self.lock = threading.Lock()
        self.care = self.store.care

    def web_search(self, session_id, body, kind):
        self.store.get_session(session_id)
        query = text(body.get("query"), "검색어", 350)
        if not hasattr(self.model, "search_web"):
            raise ModelError("웹 검색 모델이 연결되지 않았어요.")
        if not self.lock.acquire(blocking=False):
            raise ValueError("이전 AI 응답을 기다리고 있어요.")
        try:
            if isinstance(self.model, CodexChat):
                self.model.lookup_context = {}
            result = self.model.search_web(query, kind)
            self.care.save_search(session_id, kind, result)
            return self.care.dashboard(session_id)
        finally:
            self.lock.release()

    def care_action(self, session_id, kind, body, item=None):
        if not self.lock.acquire(blocking=False):
            raise ValueError("AI 응답이 끝난 뒤 기록을 변경할 수 있어요.")
        try:
            if kind == "checkins" and not item:
                return self.care.checkin(session_id, body)
            if kind == "goals":
                return self.care.tick(session_id, item, body) if item else self.care.goal(session_id, body)
            if kind == "events":
                return self.care.event(session_id, body, item)
            if kind == "bookings":
                return self.care.booking_status(session_id, item, body) if item else self.care.booking(session_id, body)
            raise ValueError("지원하지 않는 요청이에요.")
        finally:
            self.lock.release()

    def chat(self, session_id, body):
        message, mode = body.get("message"), body.get("mode", "codex")
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError("1~2,000자 안에서 이야기를 입력해 주세요.")
        if mode not in {"codex", "demo"}:
            raise ValueError("지원하지 않는 대화 방식이에요.")
        if not self.lock.acquire(blocking=False):
            raise ValueError("이전 답변을 기다리고 있어요. 답변이 끝나면 이어서 이야기해 주세요.")
        try:
            session = self.store.get_session(session_id)
            if len(session["messages"]) >= 200:
                raise ValueError("대화가 길어졌어요. 새 대화를 시작해 주세요.")
            # Current query takes priority; short references may inherit recent context.
            query = message
            if len(message.strip()) < 12 and re.search(r"그거|더|응|그래|관련", message):
                past = [m["content"] for m in session["messages"] if m["role"] == "user"]
                if past:
                    query += " " + past[-1]
            if mode == "codex" and hasattr(self.model, "retrieval_keywords"):
                keywords = self.model.retrieval_keywords(message.strip(), session["messages"])
                sources = self.store.search_fulltext(keywords)
            else:
                sources = self.store.search(query)
            if isinstance(self.model, CodexChat):
                care = session["care"]
                self.model.care_context = {key: care[key] for key in ("today", "summary", "goals", "events", "bookings", "conflicts")}
                self.model.care_context["checkins"] = care["checkins"][:7]
                self.model.care_context["public_searches"] = care["searches"][:2]
            responder = self.model.respond if mode == "codex" else demo_response
            result = responder(message.strip(), session["messages"], session["memories"], sources)
            actions = result.get("actions", [])
            # Luna selects read-only information tasks from the conversation.
            # Changes to checkins/goals/events always require review in the UI.
            if mode == "codex" and hasattr(self.model, "search_web"):
                for action in actions[:2]:
                    kind = action.get("type")
                    lookup = kind in {"hospitals", "web"} and bool(action.get("query"))
                    if lookup:
                        try:
                            if isinstance(self.model, CodexChat):
                                self.model.lookup_context = {"question": message.strip(), "db_records": sources}
                            found = self.model.search_web(action["query"][:350], kind)
                            action["search_id"] = self.care.save_search(session_id, kind, found)
                            action["result"] = found
                            action["completed"] = True
                            action["label"] = "찾아본 정보"
                            result["reply"] += "\n\n" + found["summary"]
                        except ModelError:
                            action["error"] = "정보를 확인하지 못했어요. 대화에서 다시 요청해 주세요."
                    # At most one web request per conversation turn.
                    if lookup:
                        break
            citations = [s for s in sources if s["id"] in result["source_ids"]]
            for source in citations:
                source["citations"] = [c for c in result.get("citations", []) if c["source_id"] == source["id"]]
            return self.store.save_turn(session_id, message.strip(), result["reply"], citations,
                                        result["memories"], mode, actions)
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
                "knowledge_count": self.app.store.knowledge_count(), "model": MODEL, "effort": EFFORT})
        if path == "/api/knowledge":
            query = parse_qs(urlparse(self.path).query)
            try:
                return self.respond(200, {"records": self.app.store.library(query.get("q", [""])[0][:300], query.get("category", [""])[0])})
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
        files = {"/": "index.html", "/app.css": "app.css", "/app.js": "app.js", "/care.js": "care.js", "/favicon.svg": "favicon.svg"}
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
            if not 0 < length <= 20000:
                self.close_connection = True
                return self.respond(413, {"error": "요청이 너무 크거나 비어 있어요."})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("요청 형식이 올바르지 않아요.")
            path = urlparse(self.path).path
            if path == "/api/sessions":
                return self.respond(201, self.app.store.create_session())
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
                return self.respond(200, self.app.chat(match[1], body))
            match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/(checkins|goals|events|bookings|hospitals|web)(?:/([a-f0-9]{32}))?", path)
            if match:
                session_id, kind, item = match.groups()
                if kind in {"hospitals", "web"} and not item:
                    return self.respond(200, self.app.web_search(session_id, body, kind))
                return self.respond(200, self.app.care_action(session_id, kind, body, item))
            return self.respond(404, {"error": "요청을 찾지 못했어요."})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.respond(400, {"error": str(exc) if not isinstance(exc, json.JSONDecodeError) else "요청 형식이 올바르지 않아요."})
        except KeyError:
            return self.respond(404, {"error": "대화를 찾지 못했어요."})
        except ModelError as exc:
            return self.respond(503, {"error": str(exc)})
        except Exception:
            return self.respond(500, {"error": "요청을 처리하지 못했어요. 다시 시도해 주세요."})

    def do_DELETE(self):
        if not self.validate_origin():
            return self.respond(403, {"error": "이 주소에서 요청할 수 없어요."})
        child = re.fullmatch(r"/api/sessions/([a-f0-9]{32})/(goals|events|memories|checkins)/([a-f0-9]{32}|\d{4}-\d{2}-\d{2})", urlparse(self.path).path)
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
