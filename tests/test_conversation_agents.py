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
        self.systems = []
        def execute(model, system, payload, schema, web=False):
            self.calls.append((model, payload, schema))
            self.systems.append(system)
            return responses.pop(0), []
        return patch.object(GemmaChat, "execute", execute)

    def test_custom_system_instructions_persist_and_reach_main_and_worker(self):
        prompt = "짧고 다정하게 반말로 대화해."
        self.app.store.save_system_instructions(prompt)
        reopened = App(Path(self.temp.name), model=self.main)
        self.assertEqual(reopened.store.get_system_instructions()["prompt"], prompt)
        with self.execute_sequence([
            {"reply": "확인할게.", "task": "records_read", "instruction": "기록 조회"},
            findings(reply="아직 기록이 없어.")]):
            self.app.chat(self.sid, {"message": "내 기록 보여줘."})
        self.assertTrue(all(system.startswith(prompt) for system in self.systems))
        self.assertIn("TASK_EXECUTION_RULES", self.systems[0])
        self.assertIn("CURRENT_USER_MESSAGE authorizes", self.systems[1])

    def test_default_system_instructions_and_invalid_changes(self):
        default = self.app.store.get_system_instructions()
        self.assertIn("한파이더맨", default["prompt"])
        self.assertEqual(default["prompt"], default["default_prompt"])
        for invalid in (None, "", "   ", "x" * 4001):
            with self.assertRaises(ValueError):
                self.app.store.save_system_instructions(invalid)
        self.assertEqual(self.app.store.get_system_instructions(), default)

    def test_greeting_one_main_call_no_search_or_worker(self):
        with self.execute_sequence([{"reply": "안녕!", "task": "none", "instruction": ""}]), \
             patch.object(self.app.store, "search_fulltext", side_effect=AssertionError("Unexpected DB search")):
            saved = self.app.chat(self.sid, {"message": "안녕"})
        self.assertEqual(len(self.calls), 1)
        self.assertIs(self.calls[0][0], self.main)
        self.assertEqual(self.calls[0][1], {"CURRENT_USER_MESSAGE": "안녕", "RECENT_CONVERSATION": [], "SESSION_MEMORY": []})
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

    def test_main_receives_same_session_history_but_not_another_session(self):
        self.app.store.save_turn(self.sid, "내 별명은 도토리야.", "도토리님, 반가워요!", [], [], "codex")
        other = self.app.store.create_session()["id"]
        self.app.store.save_turn(other, "내 별명은 밤톨이야.", "반가워요.", [], [], "codex")
        with self.execute_sequence([{"reply": "도토리라고 하셨어요.", "task": "none", "instruction": ""}]):
            self.app.chat(self.sid, {"message": "내 별명 뭐였지?"})
        context = self.calls[0][1]["RECENT_CONVERSATION"]
        self.assertEqual([m["content"] for m in context], ["내 별명은 도토리야.", "도토리님, 반가워요!"])
        self.assertNotIn("밤톨", str(self.calls[0][1]))
        with self.execute_sequence([{"reply": "아직 이야기하지 않으셨어요.", "task": "none", "instruction": ""}]):
            fresh = self.app.store.create_session()["id"]
            self.app.chat(fresh, {"message": "내 별명 뭐였지?"})
        self.assertEqual(self.calls[0][1]["RECENT_CONVERSATION"], [])

    def test_followup_context_includes_previously_displayed_classical_evidence(self):
        source = {"title": "동의보감", "citations": [{"quote": "起居有常", "reading": "생활에 규칙이 있다"}]}
        self.app.store.save_turn(self.sid, "생활 원문 찾아줘.", "원문을 찾았어요.", [source], [], "codex")
        with self.execute_sequence([{"reply": "일정한 생활 리듬을 뜻해요.", "task": "none", "instruction": ""}]):
            self.app.chat(self.sid, {"message": "그 문장이 무슨 뜻이야?"})
        self.assertEqual(self.calls[0][1]["RECENT_CONVERSATION"][-1]["citations"][0]["quote"], "起居有常")

    def test_conversation_context_keeps_older_turns_and_complete_message_text(self):
        from conversation_agents import conversation_context
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(40)]
        messages[0]["content"] = "처음에 정한 약속"
        messages[-1]["content"] = "긴 답변" * 1000
        context = conversation_context({"messages": messages})
        self.assertEqual(len(context), 40)
        self.assertEqual(context[0]["content"], "처음에 정한 약속")
        self.assertEqual(context[-1]["content"], messages[-1]["content"])

    def test_conversation_context_bounds_large_histories_without_mixing_sessions(self):
        from conversation_agents import conversation_context
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i) + "가" * 6000} for i in range(80)]
        context = conversation_context({"messages": messages})
        self.assertLess(len(context), len(messages))
        self.assertEqual(context[-1]["content"], messages[-1]["content"])

    def test_web_task_runs_search_even_when_query_agent_returns_false(self):
        self.main.browser_search_enabled = True
        self.app.store.save_turn(self.sid, "질병관리청 수면 안내가 궁금해.", "관련 자료를 확인해볼 수 있어요.", [], [], "codex")
        result = {"query": "질병관리청 수면 안내", "provider": "네이버", "urls": ["https://health.kdca.go.kr/"]}
        responses = [{"reply": "검색할게요.", "task": "web", "instruction": "이전 주제인 질병관리청 수면 안내 검색"},
                     {"keywords": [], "search_needed": False, "search_query": "질병관리청 수면 안내"},
                     {"reply": "검색 결과를 확인했어요."}]
        with self.execute_sequence(responses), patch("browser_bridge.BrowserBridge.search", return_value=result) as search:
            saved = self.app.chat(self.sid, {"message": "그거 웹에서 찾아봐."})
        search.assert_called_once_with("질병관리청 수면 안내")
        self.assertTrue(self.calls[1][1]["SEARCH_REQUIRED"])
        self.assertIn("질병관리청", self.calls[1][1]["ASSIGNED_TASK_BRIEF"])
        self.assertTrue(saved["messages"][-1]["actions"][0]["completed"])

    def test_record_recall_keeps_existing_observations_without_new_writes(self):
        quote = "오늘 커피를 2잔 마셨어."
        day = datetime.now(KST).date().isoformat()
        observations = self.app.store.guidance.validate(self.sid, quote, [
            {"metric": "caffeine_cups", "date": day, "quote": quote, "value": "2"}])
        self.app.store.save_turn(self.sid, quote, "기록했어요.", [], [], "codex", [], observations)
        before = self.app.store.get_session(self.sid)["care"]["guidance"]["observations"]
        responses = [{"reply": "기록을 확인할게.", "task": "records_read", "instruction": "커피 기록 조회"},
                     findings(reply="오늘 커피를 2잔 마셨다고 기록되어 있어요.")]
        with self.execute_sequence(responses):
            saved = self.app.chat(self.sid, {"message": "오늘 커피 몇 잔 마셨지? 기록에서 찾아줘."})
        self.assertEqual(saved["care"]["guidance"]["observations"], before)
        self.assertEqual(self.calls[1][0].care_context["patient_observations"], before)
        self.assertEqual(set(self.calls[1][2]["properties"]), {"reply"})
        self.assertIn("2잔", saved["messages"][-1]["content"])

    def test_record_recall_cannot_rewrite_a_previous_quote_as_a_new_observation(self):
        quote = "오늘 커피를 2잔 마셨어."
        day = datetime.now(KST).date().isoformat()
        observation = {"metric": "caffeine_cups", "date": day, "quote": quote, "value": "2"}
        validated = self.app.store.guidance.validate(self.sid, quote, [observation])
        self.app.store.save_turn(self.sid, quote, "기록했어요.", [], [], "codex", [], validated)
        before = self.app.store.get_session(self.sid)
        responses = [{"reply": "기록을 확인할게.", "task": "records", "instruction": "커피 기록 조회"},
                     findings(reply="2잔이에요.", observations=[observation])]
        with self.execute_sequence(responses), self.assertRaises(ValueError):
            self.app.chat(self.sid, {"message": "오늘 커피 몇 잔 마셨지? 기록에서 찾아줘."})
        after = self.app.store.get_session(self.sid)
        self.assertEqual(after["messages"], before["messages"])
        self.assertEqual(after["care"]["guidance"]["observations"], before["care"]["guidance"]["observations"])

    def test_read_only_records_worker_cannot_emit_mutations(self):
        responses = [{"reply": "확인할게.", "task": "records_read", "instruction": "기록 조회"},
                     findings(actions=[{"type": "goal", "label": "목표", "title": "산책"}])]
        with self.execute_sequence(responses), self.assertRaises(ModelError):
            self.app.chat(self.sid, {"message": "내 기록을 보여줘."})
        self.assertEqual(self.app.store.get_session(self.sid)["messages"], [])

    def test_literature_worker_search_and_exact_citation(self):
        source = {"id": "fixture", "category": "classical", "body": "起居有常。", "book": "東醫寶鑑"}
        responses = [{"reply": "원문을 찾아볼게.", "task": "literature", "instruction": "규칙적인 생활 원문 탐색"},
            {"keywords": ["起居"]}, {"reply": "원문을 찾았어.", "citations": [{"source_id": "fixture", "quote": "起居有常", "reading": "생활에 규칙이 있다"}]}]
        with self.execute_sequence(responses), patch.object(self.app.store, "search_fulltext", return_value=[source]) as search:
            saved = self.app.chat(self.sid, {"message": "동의보감 원문 찾아줘"})
        search.assert_called_once_with(["起居"], 4)
        self.assertIs(self.calls[1][0], self.calls[2][0])
        self.assertIsNot(self.calls[1][0], self.main)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(set(self.calls[2][2]["properties"]), {"reply", "citations"})
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
        self.assertEqual(set(self.calls[1][2]["properties"]), {"reply", "actions"})
        self.assertNotIn("caffeine", self.calls[1][2]["properties"]["actions"]["items"]["properties"])
        self.assertEqual(set(self.calls[1][2]["properties"]["actions"]["items"]["required"]),
                         {"type", "operation", "instruction_quote", "title", "start", "end", "target_id"})

    def test_calendar_mutation_without_operation_cannot_promise_a_saved_event(self):
        message = "내일 오후 3시에 산책 추가해줘"
        start = (datetime.now(KST) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
        responses = [{"reply": "정리할게.", "task": "calendar", "instruction": "산책 추가"},
                     findings(reply="등록할게요.", actions=[{"type": "event", "title": "산책",
                              "start": start, "instruction_quote": message}]),
                     findings(reply="등록할게요.", actions=[{"type": "event", "title": "산책",
                              "start": start, "instruction_quote": message}])]
        with self.execute_sequence(responses), self.assertRaises(ValueError):
            self.app.chat(self.sid, {"message": message})
        saved = self.app.store.get_session(self.sid)
        self.assertEqual(saved["care"]["events"], [])
        self.assertEqual(saved["messages"], [])

    def test_incomplete_calendar_draft_is_retried_before_any_write(self):
        message = "내일 오후 3시에 산책 추가해줘"
        start = (datetime.now(KST) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
        responses = [{"reply": "정리할게.", "task": "calendar", "instruction": "산책 추가"},
                     findings(actions=[{"type": "event", "operation": "create", "title": "산책",
                                       "instruction_quote": message}]),
                     findings(actions=[{"type": "event", "operation": "create", "title": "산책",
                                       "start": start, "instruction_quote": message}])]
        with self.execute_sequence(responses):
            saved = self.app.chat(self.sid, {"message": message})
        self.assertEqual(len(self.calls), 3)
        self.assertIn("DRAFT_CORRECTION", self.systems[-1])
        self.assertEqual(len(saved["care"]["events"]), 1)
        self.assertEqual(len(saved["messages"]), 2)

    def test_compact_calendar_fields_still_require_user_evidence_before_writes(self):
        start = (datetime.now(KST) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
        responses = [{"reply": "확인할게.", "task": "calendar", "instruction": "산책 추가"},
                     {"reply": "산책을 준비했어.", "actions": [{"type": "event", "operation": "create", "title": "산책", "start": start}]}]
        with self.execute_sequence(responses):
            with self.assertRaises(ValueError):
                self.app.chat(self.sid, {"message": "내일 산책 추가해줘"})
        self.assertEqual(self.app.store.get_session(self.sid)["care"]["events"], [])

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
