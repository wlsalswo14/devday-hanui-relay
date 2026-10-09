import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_bridge import ModelError, validate_result
from server import App, Handler, demo_memories
from store import Store

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "knowledge.seed.json"


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail = False

    def available(self):
        return True

    def respond(self, message, history, memories, sources):
        self.calls.append((message, history, memories, sources))
        if self.fail:
            raise ModelError("테스트 연결 실패")
        return {"reply": "자료를 확인했어요.", "source_ids": [s["id"] for s in sources[:1]],
                "memories": demo_memories(message)}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name)
        self.model = FakeModel()
        self.app = App(self.runtime, SEED, self.model)
        self.session_id = self.app.store.create_session()["id"]

    def tearDown(self):
        self.temp.cleanup()

    def chat(self, message, mode="demo"):
        return self.app.chat(self.session_id, {"message": message, "mode": mode})

    def test_self_report_is_persisted_with_original_message(self):
        result = self.chat("요즘 5시간 정도 자고 낮에 피곤해")
        self.assertTrue(any(m["category"] == "sleep" for m in result["memories"]))
        for memory in result["memories"]:
            self.assertEqual(memory["quote"], result["messages"][0]["content"])
            self.assertEqual(memory["message_id"], result["messages"][0]["id"])
        reopened = Store(self.runtime / "hanui.sqlite3", SEED)
        self.assertEqual(reopened.get_session(self.session_id)["memories"], result["memories"])

    def test_recall_across_turns(self):
        self.chat("요즘 5시간 정도 자고 낮에 피곤해")
        result = self.chat("아까 내가 몇 시간 잔다고 했지?")
        self.assertIn("5시간", result["messages"][-1]["content"])
        self.assertEqual(len(result["messages"]), 4)

    def test_topic_switch_retrieves_herb_not_sleep(self):
        self.chat("요즘 5시간 자고 있어")
        result = self.chat("감초 자료를 찾아줘")
        sources = result["messages"][-1]["sources"]
        self.assertTrue(sources)
        self.assertTrue(all(s["category"] == "herb" and "감초" in s["tags"] for s in sources))

    def test_others_and_hypotheticals_are_not_self_reports(self):
        for message in ["친구가 잠을 5시간 자요", "5시간 자면 어떻게 돼?", "어머니가 잠을 못 자요"]:
            self.assertEqual(demo_memories(message), [])

    def test_sessions_are_isolated(self):
        self.chat("요즘 5시간 자고 있어")
        other = self.app.store.create_session()
        self.assertEqual(other["messages"], [])
        self.assertEqual(other["memories"], [])

    def test_delete_cascades_to_messages_and_memories(self):
        self.chat("요즘 5시간 자고 있어")
        self.app.store.delete_session(self.session_id)
        with self.assertRaises(KeyError):
            self.app.store.get_session(self.session_id)
        with self.app.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)

    def test_codex_receives_prior_context_and_real_records(self):
        self.chat("요즘 5시간 자고 있어", mode="codex")
        self.chat("수면에 관한 자료가 더 있어?", mode="codex")
        _, history, memories, sources = self.model.calls[-1]
        self.assertEqual(len(history), 2)
        self.assertTrue(memories)
        self.assertTrue(sources)
        self.assertTrue(all(s["source_url"].startswith("https://") for s in sources))

    def test_model_failure_does_not_persist_partial_turn(self):
        self.model.fail = True
        with self.assertRaises(ModelError):
            self.chat("미병이 뭐야?", mode="codex")
        result = self.app.store.get_session(self.session_id)
        self.assertEqual(result["messages"], [])

    def test_ai_chat_runs_directly(self):
        result = self.chat("미병이 뭐야?", mode="codex")
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(len(self.model.calls), 1)

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ModelError):
            validate_result({"reply": "답변", "source_ids": ["invented"], "memories": []}, "질문", [])

    def test_invented_memory_quote_is_dropped(self):
        result = validate_result({"reply": "답변", "source_ids": [], "memories": [
            {"category": "sleep", "summary": "사용자는 3시간 수면", "quote": "3시간"}
        ]}, "요즘 5시간 자요", [])
        self.assertEqual(result["memories"], [])

    def test_empty_database_returns_no_fabricated_record(self):
        empty = self.runtime / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        store = Store(self.runtime / "empty.sqlite3", empty)
        self.assertEqual(store.search("감초"), [])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        app = App(Path(cls.temp.name), SEED, FakeModel())
        handler = type("TestHandler", (Handler,), {"app": app})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    def test_http_chat_and_reload(self):
        session = self.request("/api/sessions", {})
        result = self.request(f'/api/sessions/{session["id"]}/chat',
                              {"message": "요즘 5시간 자고 있어", "mode": "demo"})
        self.assertEqual(len(result["messages"]), 2)
        restored = self.request(f'/api/sessions/{session["id"]}')
        self.assertEqual(result, restored)

    def test_foreign_origin_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/sessions", {}, {"Origin": "https://unrelated.example"})
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_invalid_json_returns_400(self):
        req = urllib.request.Request(self.base + "/api/sessions", data=b"{bad",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_foreign_host_cannot_read_configuration(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/config", headers={"Host": "unrelated.example"})
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
