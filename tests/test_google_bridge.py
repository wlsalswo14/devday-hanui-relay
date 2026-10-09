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
        return GemmaChat(Path(tempfile.gettempdir()), key="synthetic-key")

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

    def test_provider_error_cannot_leak_credentials(self):
        for status in [403, 429, 503]:
            error = urllib.error.HTTPError("url", status, "synthetic-key", {}, io.BytesIO(b"synthetic-key"))
            with patch("google_bridge.urllib.request.urlopen", side_effect=error) as call:
                with self.assertRaises(ModelError) as caught:
                    self.model().retrieval_keywords("睡眠", [])
                self.assertNotIn("synthetic-key", str(caught.exception))
                self.assertEqual(call.call_count, 1)

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

    @unittest.skipUnless(os.name == "nt", "Windows account-bound credentials")
    def test_dpapi_roundtrip(self):
        encrypted = protect_key(b"synthetic-key")
        self.assertNotIn(b"synthetic-key", encrypted)
        self.assertEqual(protect_key(encrypted, decrypt=True), b"synthetic-key")
