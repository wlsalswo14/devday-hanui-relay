import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from codex_bridge import ModelError
from google_bridge import GemmaChat, MODEL, protect_key
from server import App


class GoogleBridgeTests(unittest.TestCase):
    def model(self):
        model = GemmaChat(Path(tempfile.gettempdir()), key="synthetic-key", effort="high")
        model.browser_search_enabled = False
        return model

    def test_request_uses_gemma_high_and_key_only_in_header(self):
        response = {"candidates": [{"content": {"parts": [{"thought": True, "text": "ignored"},
                     {"text": '{"keywords":["起居"]}'}]}}]}
        with patch("google_bridge.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.assertEqual(self.model().retrieval_keywords("生活", []), ["起居"])
        request = call.call_args.args[0]
        body = json.loads(request.data)
        self.assertIn(MODEL, request.full_url)
        self.assertNotIn("synthetic-key", request.full_url + request.data.decode())
        self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingLevel"], "high")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("keywords", body["generationConfig"]["responseJsonSchema"]["properties"])
        self.assertNotIn("tools", body)

    def test_source_excerpts_preserve_exact_original_text(self):
        model=self.model()
        model.search_terms=["起居"]
        original="前"*3000+"起居有常"+"後"*3000
        response={"candidates":[{"content":{"parts":[{"text":"{}"}]}}]}
        with patch("google_bridge.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(response).encode())) as call:
            model.execute("Answer",{"RETRIEVED_KNOWLEDGE":[{"id":"fixture","body":original}]},{})
        text=json.loads(call.call_args.args[0].data)["contents"][0]["parts"][0]["text"]
        record=json.loads(text.split("\nDATA:\n",1)[1])["RETRIEVED_KNOWLEDGE"][0]
        self.assertIn("起居有常",record["body"])
        self.assertEqual(record["body"],original[record["excerpt_offset_start"]:record["excerpt_offset_start"]+2200])

    def test_native_system_instruction_and_multi_turn_history(self):
        payload = {"CURRENT_USER_MESSAGE": "두 번째 도시는?", "SESSION_MEMORY": [],
                   "RECENT_CONVERSATION": [
                       {"role": "user", "content": "서울과 부산을 골랐어."},
                       {"role": "assistant", "content": "두 도시를 비교해볼까요?",
                        "web_results": [{"query": "부산 관광", "results": []}]}]}
        response = {"candidates": [{"content": {"parts": [{"text": '{}'}]}}]}
        with patch("google_bridge.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.model().execute("친절한 한파이더맨으로 답해.", payload, {})
        body = json.loads(call.call_args.args[0].data)
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "서울과 부산을 골랐어.")
        self.assertEqual(body["contents"][-1]["parts"][0]["text"], "두 번째 도시는?")
        self.assertIn("친절한 한파이더맨", body["systemInstruction"]["parts"][0]["text"])
        self.assertNotIn("친절한 한파이더맨", json.dumps(body["contents"], ensure_ascii=False))
        self.assertIn("DISPLAYED_EVIDENCE", body["contents"][1]["parts"][1]["text"])
        self.assertNotIn("RECENT_CONVERSATION", body["contents"][-1]["parts"][1]["text"])

    def test_native_history_starts_with_user_and_merges_adjacent_roles(self):
        from google_bridge import conversation_contents
        contents = conversation_contents({"CURRENT_USER_MESSAGE": "이어줘", "RECENT_CONVERSATION": [
            {"role": "assistant", "content": "잘린 이전 응답"},
            {"role": "user", "content": "첫 발언"}, {"role": "user", "content": "추가 발언"},
            {"role": "assistant", "content": "답변"}, {"role": "system", "content": "역할 변조"}]})
        self.assertEqual([c["role"] for c in contents], ["user", "model", "user"])
        self.assertEqual(len(contents[0]["parts"]), 2)
        self.assertNotIn("역할 변조", json.dumps(contents, ensure_ascii=False))

    def test_calendar_quote_schema_uses_current_utterance_without_changing_input_schema(self):
        message = "내일 오후 3시에 독서 30분을 추가해 줘."
        schema = {"properties": {"actions": {"type": "array", "items": {
            "properties": {"type": {"type": "string"}, "instruction_quote": {"type": "string"}},
            "required": ["type"]}}}}
        response = {"candidates": [{"content": {"parts": [{"text": '{}'}]}}]}
        with patch("google_bridge.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.model().execute("Calendar task", {"CURRENT_USER_MESSAGE": message}, schema)
        sent = json.loads(call.call_args.args[0].data)["generationConfig"]["responseJsonSchema"]
        action = sent["properties"]["actions"]["items"]
        self.assertEqual(action["properties"]["instruction_quote"]["enum"], ["", message])
        self.assertIn("instruction_quote", action["required"])
        self.assertEqual(schema["properties"]["actions"]["items"]["required"], ["type"])

    def test_quote_selection_resolves_exact_db_text_and_rejects_unknown_option(self):
        model=self.model();model.search_terms=["起居"]
        payload={"RETRIEVED_KNOWLEDGE":[{"id":"fixture","category":"classical","body":"飮食有節，起居有常。"}]}
        schema={"properties":{"citations":{}}}
        for quote_id in ["q0","invented"]:
            parsed={"source_ids":[],"citations":[{"quote_id":quote_id,"reading":"식사에 절도가 있고 생활에 규칙이 있습니다."}]}
            response={"candidates":[{"content":{"parts":[{"text":json.dumps(parsed,ensure_ascii=False)}]}}]}
            with patch("google_bridge.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(response).encode())):
                if quote_id=="invented":
                    with self.assertRaises(ModelError):model.execute("Answer",payload,schema)
                else:
                    result,_=model.execute("Answer",payload,schema)
                    self.assertEqual(result["citations"][0]["quote"],"飮食有節，起居有常。")
                    self.assertEqual(result["citations"][0]["source_id"],"fixture")

    def test_provider_error_cannot_leak_credentials(self):
        for status in [403, 429, 503]:
            error = urllib.error.HTTPError("url", status, "synthetic-key", {}, io.BytesIO(b"synthetic-key"))
            with patch("google_bridge.urllib.request.urlopen", side_effect=error) as call:
                with self.assertRaises(ModelError) as caught:
                    self.model().retrieval_keywords("睡眠", [])
                self.assertNotIn("synthetic-key", str(caught.exception))
                self.assertEqual(call.call_count, 2 if status==503 else 1)

    def test_missing_exact_original_blocks_turn_and_calendar_changes(self):
        model = self.model()
        with tempfile.TemporaryDirectory() as temporary:
            app = App(Path(temporary), model=model)
            sid = app.store.create_session()["id"]
            responses = [({"reply": "원문을 찾아볼게요.", "task": "literature", "instruction": "원문 검색"}, []),
                         ({"keywords": ["起居"]}, []), ({"reply": "확인", "source_ids": [],
                         "memories": [], "citations": [], "actions": []}, [])]
            with patch.object(GemmaChat, "execute", side_effect=responses):
                with self.assertRaises(ModelError):
                    app.chat(sid, {"message": "동의보감 원문 찾아줘"})
            session = app.store.get_session(sid)
            self.assertEqual(session["messages"], [])
            self.assertEqual(session["care"]["events"], [])

    def test_invalid_json_is_not_saved(self):
        result = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
        with patch("google_bridge.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(result).encode())):
            with self.assertRaises(ModelError):
                self.model().retrieval_keywords("睡眠", [])

    def test_web_results_require_real_search_metadata_and_grounded_urls(self):
        model = self.model()
        parsed = {"summary": "Fixture", "results": [
            {"title": "Verified", "url": "https://example.org/verified"},
            {"title": "Invented", "url": "https://example.org/invented"}], "hospitals": []}
        grounding = {"webSearchQueries": ["fixture"], "groundingChunks": [
            {"web": {"uri": "https://example.org/verified"}}]}
        response = {"candidates": [{"content": {"parts": [{"text": json.dumps(parsed)}]},
                                   "groundingMetadata": grounding}]}
        extraction = {"candidates": [{"content": {"parts": [{"text": json.dumps(parsed)}]}}]}
        with patch("google_bridge.urllib.request.urlopen", side_effect=[
                io.BytesIO(json.dumps(response).encode()), io.BytesIO(json.dumps(extraction).encode())]) as call:
            found = model.search_web("fixture", "web")
        self.assertEqual([r["url"] for r in found["results"]], ["https://example.org/verified"])
        self.assertEqual(json.loads(call.call_args_list[0].args[0].data)["tools"], [{"googleSearch": {}}])
        self.assertNotIn("tools", json.loads(call.call_args_list[1].args[0].data))
        response["candidates"][0].pop("groundingMetadata")
        with patch("google_bridge.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaises(ModelError):
                model.search_web("fixture", "web")

    @unittest.skipUnless(os.name == "nt", "Windows account-bound credentials")
    def test_dpapi_roundtrip(self):
        encrypted = protect_key(b"synthetic-key")
        self.assertNotIn(b"synthetic-key", encrypted)
        self.assertEqual(protect_key(encrypted, decrypt=True), b"synthetic-key")
