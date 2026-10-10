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
            responses = [({"keywords": ["起居"]}, []), ({"reply": "확인", "source_ids": [],
                         "memories": [], "citations": [], "actions": []}, [])]
            with patch.object(model, "execute", side_effect=responses):
                with self.assertRaises(ModelError):
                    app.chat(sid, {"message": "산책 일정 넣어줘"})
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
