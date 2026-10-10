import json
import unittest
from unittest.mock import patch

from public_search import ResultParser, search
from request_lifecycle import RequestCancelled, RequestManager
from codex_bridge import ModelError


class PublicSearchTests(unittest.TestCase):
    def test_parse_merges_observed_title_and_snippet_without_ads_or_navigation(self):
        parser = ResultParser()
        parser.feed('''<a class="fds-anchor-layout" href="https://health.kdca.go.kr/sleep">수면 건강 안내</a>
        <a class="fds-anchor-layout" href="https://health.kdca.go.kr/sleep">규칙적인 수면 습관에 관한 공식 건강 안내를 확인하세요.</a>
        <a class="fds-anchor-layout" href="https://ader.naver.com/ad">수면 광고</a>
        <a class="fds-anchor-layout" href="https://search.naver.com/search.naver">검색 더보기</a>
        <a class="fds-anchor-layout" href="http://127.0.0.1/private">수면 내부</a>
        <a href="https://example.org/menu">메뉴</a>''')
        rows = parser.results("수면 건강")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "수면 건강 안내")
        self.assertIn("규칙적인", rows[0]["summary"])
        self.assertEqual(rows[0]["publisher"], "health.kdca.go.kr")

    def test_empty_search_is_not_reported_as_success(self):
        with patch("public_search.fetch", side_effect=ValueError("No results")):
            with self.assertRaises(ModelError):
                search("공식 자료")

    def test_cancelled_request_never_starts_transport(self):
        manager = RequestManager()
        identifier = "a" * 32
        manager.cancel(identifier)
        with patch("public_search.subprocess.Popen") as process:
            with self.assertRaises(RequestCancelled), manager.scope(request_id=identifier):
                search("공식 자료")
            process.assert_not_called()

    def test_cancellation_kills_inflight_public_search(self):
        import subprocess
        manager = RequestManager()
        identifier = "b" * 32
        with patch("public_search.subprocess.Popen") as popen:
            process = popen.return_value
            process.poll.return_value = None
            def cancel(*args, **kwargs):
                if "timeout" in kwargs:
                    manager.cancel(identifier)
                    raise subprocess.TimeoutExpired("search", .1)
                return "", ""
            process.communicate.side_effect = cancel
            with self.assertRaises(RequestCancelled), manager.scope(request_id=identifier):
                search("공식 자료")
            process.kill.assert_called_once()

    def test_scope_search_returns_only_worker_results(self):
        manager = RequestManager()
        expected = {"query": "수면", "provider": "네이버", "results": [{"url": "https://example.org/sleep"}]}
        with manager.scope(), patch("public_search.subprocess.Popen") as popen:
            process = popen.return_value
            process.communicate.return_value = (json.dumps(expected), "")
            process.returncode = 0
            process.poll.return_value = 0
            self.assertEqual(search("수면"), expected)
