import json
import tempfile
import unittest
from pathlib import Path

from codex_bridge import CodexChat, ModelError, validate_result
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

    def test_korean_reading_is_separate_from_exact_original_and_persisted(self):
        reading="원문의 전문 용어에 관한 구절이에요."
        result=validate_result({"reply":"답변","source_ids":["classic"],"memories":[],"citations":[{"source_id":"classic","quote":"專門詞","reading":reading}]},"질문",[self.classical])
        citation=result["citations"][0]
        self.assertEqual(citation["reading"],reading)
        self.assertEqual(self.classical["body"][citation["offset_start"]:citation["offset_end"]],citation["quote"])
        source={**self.classical,"citations":[citation]}
        sid=self.store.create_session()["id"]
        self.store.save_turn(sid,"질문","답변",[source],[],"demo")
        self.assertEqual(self.store.get_session(sid)["messages"][-1]["sources"][0]["citations"][0]["reading"],reading)

    def test_fresh_classical_reading_must_be_bounded_korean_text(self):
        for reading in ["", "Original Chinese only", "해석"*201, 123]:
            with self.assertRaises(ModelError):
                validate_result({"reply":"답변","source_ids":["classic"],"memories":[],"citations":[{"source_id":"classic","quote":"專門詞","reading":reading}]},"질문",[self.classical])

    def test_required_classical_reference_rejects_empty_modern_and_untranslated(self):
        candidates=[[],[{"source_id":"modern","quote":"현대 자료","reading":""}],
                    [{"source_id":"classic","quote":"專門詞"}]]
        for citations in candidates:
            with self.subTest(citations=citations), self.assertRaises(ModelError):
                validate_result({"reply":"답변","source_ids":[],"memories":[],"citations":citations},
                    "질문",[self.modern,self.classical],require_classical=True)
        valid=validate_result({"reply":"답변","source_ids":[],"memories":[],
            "citations":[{"source_id":"classic","quote":"專門詞","reading":"전문 용어"}]},
            "질문",[self.classical],require_classical=True)
        self.assertEqual(valid["source_ids"],["classic"])

    def test_real_model_path_persists_cited_opening_without_patient_facts(self):
        class Grounded(CodexChat):
            def available(self): return True
            def execute(self, system, payload, schema, **kwargs):
                if "keywords" in schema["properties"]:
                    self.context=payload["CLINICIAN_CONTEXT"]
                    return {"keywords":["專門詞"]},[]
                return {"question":"어젯밤에는 몇 시에 주무셨어요?","citations":[
                    {"source_id":"classic","quote":"專門詞","reading":"전문 용어"}]},[]
        model=Grounded(self.root)
        app=App(self.root/"opening",self.seed,model)
        sid=app.store.create_session()["id"]
        app.care_action(sid,"guidance",{"text":"취침 23시 전","assessment":"합성 한의사 소견",
            "start_conversation":True,"mode":"codex"})
        session=app.store.get_session(sid)
        self.assertEqual([m["role"] for m in session["messages"]],["assistant"])
        self.assertEqual(session["care"]["guidance"]["observations"],[])
        self.assertEqual(session["memories"],[])
        citation=session["messages"][0]["sources"][0]["citations"][0]
        self.assertEqual(citation["reading_origin"],"luna")
        self.assertEqual(model.context[0]["assessment"],"합성 한의사 소견")

    def test_missing_classical_blocks_first_question_and_rolls_back_plan(self):
        class Missing(CodexChat):
            def available(self): return True
            def retrieval_keywords(self,*args): return ["찾을수없는원문"]
            def execute(self,*args,**kwargs): raise AssertionError("Must not generate ungrounded answer")
        app=App(self.root/"missing",self.seed,Missing(self.root))
        sid=app.store.create_session()["id"]
        with self.assertRaises(ModelError):
            app.care_action(sid,"guidance",{"text":"취침 23시 전","start_conversation":True,"mode":"codex"})
        session=app.store.get_session(sid)
        self.assertEqual(session["messages"],[])
        self.assertEqual(session["care"]["guidance"]["plans"],[])
        self.assertEqual(session["care"]["goals"],[])

    def test_uncited_real_reply_cannot_mutate_calendar_or_store_turn(self):
        class Uncited(CodexChat):
            def available(self): return True
            def retrieval_keywords(self,*args): return ["專門詞"]
            def execute(self,*args,**kwargs):
                return {"reply":"일정을 추가할게요","source_ids":[],"memories":[],"citations":[],
                    "actions":[{"type":"event","operation":"create","title":"산책",
                        "start":"2026-10-10T12:00:00+09:00","instruction_quote":"내일 산책 넣어줘"}]},[]
        app=App(self.root/"uncited",self.seed,Uncited(self.root))
        sid=app.store.create_session()["id"]
        with self.assertRaises(ModelError):
            app.chat(sid,{"message":"내일 산책 넣어줘","mode":"codex"})
        session=app.store.get_session(sid)
        self.assertEqual(session["messages"],[])
        self.assertEqual(session["care"]["events"],[])


if __name__ == "__main__":
    unittest.main()
