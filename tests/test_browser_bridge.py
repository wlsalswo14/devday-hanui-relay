import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_bridge import BrowserBridge
from codex_bridge import ModelError
from google_bridge import GemmaChat
from request_lifecycle import RequestManager, RequestCancelled
from server import App


class BrowserTests(unittest.TestCase):
    def test_only_explicit_browser_requests_route_to_browser(self):
        self.assertTrue(BrowserBridge.requested("브라우저에서 메뉴 눌러줘"))
        self.assertTrue(BrowserBridge.requested("https://example.org 열어줘"))
        self.assertFalse(BrowserBridge.requested("한의학 자료 찾아줘"))

    def test_rejects_arbitrary_code_selectors_files_and_credentials(self):
        browser = BrowserBridge()
        for action in [{"operation": "run_code"}, {"operation": "click", "target": "#password"},
                       {"operation": "navigate", "value": "file:///secret"},
                       {"operation": "navigate", "value": "https://user:pass@example.org"}]:
            with self.assertRaises(ModelError):
                browser.perform(action)

    def test_current_refs_are_replaced_and_snapshot_keys_redacted(self):
        browser = BrowserBridge()
        with patch.object(browser, "_connect"), patch.object(browser, "_rpc", return_value={
                "content": [{"type": "text", "text": "[ref=f1e4] AIza" + "x"*36}]}):
            result = browser.perform({"operation": "snapshot"})
            self.assertIn("[redacted]", result)
            self.assertEqual(browser.targets, {"f1e4"})
        with patch.object(browser, "_connect"), patch.object(browser, "_rpc", return_value={
                "content": [{"type": "text", "text": "[ref=f2e9]"}]}):
            browser.perform({"operation": "click", "target": "f1e4"})
        with self.assertRaises(ModelError):
            browser.perform({"operation": "click", "target": "f1e4"})

    def test_cannot_navigate_away_from_active_hanui_conversation(self):
        browser = BrowserBridge(); browser.current_url = "http://127.0.0.1:8765/"
        with self.assertRaises(ModelError):
            browser.perform({"operation": "navigate", "value": "https://example.org"})

    def test_tool_error_does_not_become_a_successful_observation(self):
        browser = BrowserBridge()
        with patch.object(browser, "_connect"), patch.object(browser, "_rpc", return_value={"isError": True}):
            with self.assertRaises(ModelError):
                browser.perform({"operation": "snapshot"})

    def test_model_observes_action_result_before_finishing(self):
        model = GemmaChat(Path(tempfile.gettempdir()), key="fixture")
        plans = [({"operation": "click", "target": "f1e4", "value": "", "reply": ""}, []),
                 ({"operation": "done", "target": "", "value": "", "reply": "메뉴를 열었어요."}, [])]
        with patch.object(model.browser, "perform", side_effect=["closed [ref=f1e4]", "open [ref=f2e9]"]) as tool:
            with patch.object(model, "execute", side_effect=plans) as execute:
                self.assertEqual(model.browse("브라우저 메뉴 열어줘")["reply"], "메뉴를 열었어요.")
        self.assertEqual(tool.call_count, 2)
        self.assertEqual(execute.call_args.args[1]["current_screen"], "open [ref=f2e9]")

    def test_browser_chat_failure_and_cancellation_do_not_save_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            model = GemmaChat(Path(directory), key="fixture")
            app = App(Path(directory), model=model)
            sid = app.store.create_session()["id"]
            for error in [ModelError("브라우저 연결 실패"), RequestCancelled()]:
                with patch.object(model, "browse", side_effect=error):
                    with self.assertRaises(ModelError):
                        app.chat(sid, {"message": "브라우저 메뉴 열어줘"})
                self.assertEqual(app.store.get_session(sid)["messages"], [])

    def test_cancelled_scope_never_calls_browser_transport(self):
        manager = RequestManager(); request_id = "a"*32
        manager.cancel(request_id)
        with patch("browser_bridge.urllib.request.urlopen") as transport:
            with self.assertRaises(RequestCancelled):
                with manager.scope(request_id=request_id):
                    BrowserBridge().perform({"operation": "snapshot"})
            transport.assert_not_called()

    def test_search_requires_observed_external_links_and_rejects_captcha(self):
        browser = BrowserBridge()
        screen = "- /url: https://www.google.com/settings\n- /url: https://example.org/sleep"
        def observe(*args):
            browser.current_url = "https://www.google.com/search?q=sleep"
            return screen
        with patch.object(browser, "perform", side_effect=observe):
            result = browser.search("sleep")
            self.assertEqual(result["urls"], ["https://example.org/sleep"])
        def blocked(*args):
            browser.current_url = "https://www.google.com/sorry/index"
            return "reCAPTCHA"
        with patch.object(browser, "perform", side_effect=blocked):
            with self.assertRaises(ModelError): browser.search("sleep")

    def test_search_failure_keeps_cited_db_reply_without_fake_search_success(self):
        model = GemmaChat(Path(tempfile.gettempdir()), key="fixture")
        normal = {"reply": "DB 답변", "actions": [], "citations": []}
        with patch.object(model.browser, "search", side_effect=ModelError("구글 검색 제한")):
            with patch("codex_bridge.CodexChat.respond", return_value=normal):
                result = model.respond("수면", [], [], [])
        self.assertIn("DB 자료로 답했어요", result["reply"])
        self.assertFalse(result["actions"][0]["completed"])

    def test_cancelled_search_cannot_fall_back_to_saved_db_reply(self):
        model = GemmaChat(Path(tempfile.gettempdir()), key="fixture")
        with patch.object(model.browser, "search", side_effect=RequestCancelled()):
            with patch("codex_bridge.CodexChat.respond") as normal:
                with self.assertRaises(RequestCancelled): model.respond("수면", [], [], [])
                normal.assert_not_called()

    def test_extension_token_url_is_redacted_before_model_input(self):
        clean = BrowserBridge.redact("chrome-extension://x/connect?token=private-token&client=hanui")
        self.assertNotIn("private-token", clean)
