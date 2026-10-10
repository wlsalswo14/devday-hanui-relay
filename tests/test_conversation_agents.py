import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta
from care import KST
from request_lifecycle import RequestCancelled

from codex_bridge import ModelError
from google_bridge import GemmaChat
from server import App


def findings(**changes):
    value = {"reply": "작업 결과", "source_ids": [], "citations": [], "memories": [], "actions": [], "observations": []}
    value.update(changes)
    return value


class ConversationAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.main = GemmaChat(Path(self.temp.name), key="synthetic-key")
        self.main.browser_search_enabled = False
        self.app = App(Path(self.temp.name), model=self.main)
        self.sid = self.app.store.create_session()["id"]

    def tearDown(self):
        self.temp.cleanup()

    def execute_sequence(self, responses):
        self.calls = []
        def execute(model, system, payload, schema, web=False):
            self.calls.append((model, payload, schema))
            return responses.pop(0), []
        return patch.object(GemmaChat, "execute", execute)

    def test_greeting_one_main_call_no_search_or_worker(self):
        with self.execute_sequence([{"reply": "안녕!", "task": "none", "instruction": ""}]), \
             patch.object(self.app.store, "search_fulltext", side_effect=AssertionError("Unexpected DB search")):
            saved = self.app.chat(self.sid, {"message": "안녕"})
        self.assertEqual(len(self.calls), 1)
        self.assertIs(self.calls[0][0], self.main)
        self.assertEqual(self.calls[0][1], {"CURRENT_USER_MESSAGE": "안녕"})
        self.assertEqual(saved["messages"][-1]["sources"], [])

    def test_records_use_separate_worker_no_db_and_exact_user_quote(self):
        message = "점심 후 10분 걸었어"
        responses = [{"reply": "", "task": "records", "instruction": "산책 기록 정리"},
            findings(reply="점심 후 산책 10분을 이야기해 줬네.", memories=[{"category": "activity", "summary": "점심 후 산책 10분", "quote": message}])]
        responses[0]["reply"] = "기록을 정리할게."
        with self.execute_sequence(responses), patch.object(self.app.store, "search_fulltext", side_effect=AssertionError("Unexpected DB search")):
            saved = self.app.chat(self.sid, {"message": message})
        self.assertEqual(len(self.calls), 2)
        self.assertIsNot(self.calls[1][0], self.main)
        self.assertEqual(saved["messages"][-1]["content"], "점심 후 산책 10분을 이야기해 줬네.")
        self.assertEqual(saved["memories"][0]["quote"], message)
        self.assertEqual(saved["messages"][-1]["sources"], [])

    def test_literature_worker_search_and_exact_citation(self):
        source = {"id": "fixture", "category": "classical", "body": "起居有常。", "book": "東醫寶鑑"}
        responses = [{"reply": "원문을 찾아볼게.", "task": "literature", "instruction": "규칙적인 생활 원문 탐색"},
            {"keywords": ["起居"]}, findings(source_ids=["fixture"], citations=[{"source_id": "fixture", "quote": "起居有常", "reading": "생활에 규칙이 있다"}])]
        with self.execute_sequence(responses), patch.object(self.app.store, "search_fulltext", return_value=[source]) as search:
            saved = self.app.chat(self.sid, {"message": "동의보감 원문 찾아줘"})
        search.assert_called_once_with(["起居"], 4)
        self.assertIs(self.calls[1][0], self.calls[2][0])
        self.assertIsNot(self.calls[1][0], self.main)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(saved["messages"][-1]["sources"][0]["citations"][0]["offset_end"], 4)

    def test_invented_worker_quote_blocks_save(self):
        source = {"id": "fixture", "category": "classical", "body": "起居有常。"}
        responses = [{"reply": "찾아볼게.", "task": "literature", "instruction": "문헌 탐색"}, {"keywords": ["起居"]},
            findings(source_ids=["fixture"], citations=[{"source_id": "fixture", "quote": "허구 문장", "reading": "해석"}])]
        with self.execute_sequence(responses), patch.object(self.app.store, "search_fulltext", return_value=[source]):
            with self.assertRaises(ModelError):
                self.app.chat(self.sid, {"message": "원문 찾아줘"})
        self.assertEqual(self.app.store.get_session(self.sid)["messages"], [])

    def test_records_worker_cannot_change_calendar(self):
        responses = [{"reply": "정리할게.", "task": "records", "instruction": "생활 기록"}, findings(actions=[{
            "type": "event", "label": "일정", "query": "", "title": "산책", "start": "2026-10-11T15:00:00+09:00", "note": "", "operation": "create"}])]
        with self.execute_sequence(responses):
            with self.assertRaises(ModelError):
                self.app.chat(self.sid, {"message": "산책했어"})
        self.assertEqual(self.app.store.get_session(self.sid)["care"]["events"], [])

    def test_invalid_worker_reply_saves_no_records(self):
        message = "점심 후 10분 걸었어"
        responses = [{"reply": "정리할게.", "task": "records", "instruction": "기록"},
            findings(reply="", memories=[{"category": "activity", "summary": message, "quote": message}])]
        with self.execute_sequence(responses):
            with self.assertRaises(ModelError):
                self.app.chat(self.sid, {"message": message})
        saved = self.app.store.get_session(self.sid)
        self.assertEqual(saved["messages"], [])
        self.assertEqual(saved["memories"], [])

    def test_calendar_worker_changes_only_explicit_current_session_request(self):
        message = "내일 오후 3시에 산책 추가해줘"
        start = (datetime.now(KST) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
        responses = [{"reply": "일정을 정리할게.", "task": "calendar", "instruction": "산책 일정 추가"}, findings(actions=[{
            "type": "event", "label": "산책", "query": "", "title": "산책", "start": start, "note": "",
            "operation": "create", "instruction_quote": message}])]
        with self.execute_sequence(responses), patch.object(self.app.store, "search_fulltext", side_effect=AssertionError("Unexpected DB search")):
            saved = self.app.chat(self.sid, {"message": message})
        self.assertEqual(saved["care"]["events"][0]["title"], "산책")
        self.assertIn("일정을 추가했어요", saved["messages"][-1]["content"])

    def test_cancelled_agent_work_is_discarded_before_summary_or_save(self):
        message = "점심 후 10분 걸었어"
        request_id = "a" * 32
        def execute(model, system, payload, schema, web=False):
            if model is self.main:
                return {"reply": "정리할게.", "task": "records", "instruction": "산책 기록"}, []
            self.app.requests.cancel(request_id)
            return findings(memories=[{"category": "activity", "summary": message, "quote": message}]), []
        with patch.object(GemmaChat, "execute", execute), self.app.requests.scope(request_id=request_id):
            with self.assertRaises(RequestCancelled):
                self.app.chat(self.sid, {"message": message})
        self.assertEqual(self.app.store.get_session(self.sid)["messages"], [])
        self.assertEqual(self.app.store.get_session(self.sid)["memories"], [])
