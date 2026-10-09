import json
import tempfile
import unittest
from pathlib import Path

from codex_bridge import ModelError, validate_result
from server import App
from store import Store


def record(item_id, body, classical=False):
    row = {"id": item_id, "title": "테스트 항목", "category": "classical" if classical else "concept",
        "tags": [], "body": body, "source_url": "https://example.org/source", "publisher": "합성 fixture",
        "evidence_level": "검증용", "limitations": "실제 자료 아님", "retrieved_at": "2026-10-09"}
    if classical:
        row.update(book="합성 고문헌", section="테스트 절", location="테스트 절 · 단락 1",
                   source_revision="test-revision", license="test fixture", summary="한국어 독해")
    return row


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.seed = self.root / "knowledge.seed.json"
        self.modern = record("modern", "본문에만 있는 특수키워드와 현대 자료")
        self.classical = record("classic", "原文專門詞。", True)
        self.seed.write_text(json.dumps([self.modern]), encoding="utf-8")
        (self.root / "classics.seed.json").write_text(json.dumps([self.classical]), encoding="utf-8")
        self.store = Store(self.root / "test.sqlite3", self.seed)

    def tearDown(self):
        self.temp.cleanup()

    def test_fulltext_finds_body_without_tags_and_both_corpora(self):
        rows = self.store.search_fulltext(["특수키워드", "專門詞"])
        self.assertEqual({r["id"] for r in rows}, {"modern", "classic"})
        self.assertEqual(self.store.library("專門詞", "classical")[0]["location"], "테스트 절 · 단락 1")
        self.assertEqual(self.store.search_fulltext(["' OR 1=1 --"]), [])

    def test_quote_is_exact_and_position_is_computed_from_original(self):
        result = validate_result({"reply": "답변", "source_ids": ["classic"], "memories": [],
            "citations": [{"source_id": "classic", "quote": "專門詞"}]}, "질문", [self.classical])
        citation = result["citations"][0]
        self.assertEqual(self.classical["body"][citation["offset_start"]:citation["offset_end"]], "專門詞")
        for quote in ("원문에 없는 문장", "原文…詞"):
            with self.assertRaises(ModelError):
                validate_result({"reply": "답변", "source_ids": ["classic"], "memories": [],
                    "citations": [{"source_id": "classic", "quote": quote}]}, "질문", [self.classical])

    def test_luna_keywords_drive_retrieval_and_quote_survives_reload(self):
        class Planner:
            def available(self): return True
            def retrieval_keywords(self, message, history):
                return ["專門詞"]  # Not present in the user's question.
            def respond(self, message, history, memories, sources):
                return validate_result({"reply": "찾았어요", "source_ids": [sources[0]["id"]],
                    "memories": [], "citations": [{"source_id": sources[0]["id"], "quote": "專門詞"}]}, message, sources)
        app = App(self.root / "app", self.seed, Planner())
        sid = app.store.create_session()["id"]
        result = app.chat(sid, {"message": "관련 고문헌을 알려줘", "mode": "codex"})
        citation = result["messages"][-1]["sources"][0]
        self.assertEqual(citation["id"], "classic")
        self.assertEqual(citation["citations"][0]["quote"], "專門詞")
        self.assertEqual(app.store.get_session(sid)["messages"], result["messages"])


if __name__ == "__main__":
    unittest.main()
