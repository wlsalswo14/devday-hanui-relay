import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from care import KST, clean_checkin, today, safe_url
from codex_bridge import ModelError, validate_result
from server import App

SEED = Path(__file__).resolve().parents[1] / "data" / "knowledge.seed.json"


class SearchModel:
    def available(self):
        return True

    def search_web(self, query, kind):
        if query == "fail":
            raise ModelError("test failure")
        return {"query": query, "summary": "合成 fixture", "results": [], "hospitals": [
            {"id": "f" * 32, "name": "테스트한의원 (합성)", "address": "합성 주소",
             "phone": "", "website": "", "booking_url": "https://example.org/booking",
             "reason": "합성 테스트 데이터", "source_url": "https://example.org/hospital", "reviews": []}
        ], "provider": "synthetic test fixture — no external search", "searched_at": datetime.now(KST).isoformat()}


class CareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.temp.name), SEED, SearchModel())
        self.session = self.app.store.create_session()["id"]
        self.other = self.app.store.create_session()["id"]
        self.care = self.app.care

    def tearDown(self):
        self.temp.cleanup()

    def when(self, delta=1):
        return (datetime.now(KST) + timedelta(days=delta)).replace(microsecond=0).isoformat()

    def prepare(self):
        self.app.web_search(self.session, {"query": "fixture"}, "hospitals")
        search = self.care.dashboard(self.session)["searches"][0]
        result = self.care.booking(self.session, {"search_id": search["id"], "hospital_id": "f" * 32,
                                  "start": self.when(), "note": "합성 방문 메모"})
        return result["bookings"][0]

    def test_daily_record_is_upserted_and_missing_values_stay_unknown(self):
        first = self.care.checkin(self.session, {"sleep": 5.5, "stress": 7})
        self.assertEqual(first["checkins"][0]["energy"], None)
        second = self.care.checkin(self.session, {"sleep": 6.5, "stress": 4})
        self.assertEqual(len(second["checkins"]), 1)
        self.assertEqual(second["summary"]["averages"]["sleep"], 6.5)

    def test_invalid_metrics_are_rejected_without_saving(self):
        for body in [{"sleep": -1}, {"stress": 11}, {"energy": True}, {"sleep": float("nan")},
                     {"activity": float("inf")}, {"caffeine": 0.5}, {"date": self.when()[:10]}]:
            with self.assertRaises(ValueError):
                self.care.checkin(self.session, body)
        self.assertEqual(self.care.dashboard(self.session)["checkins"], [])

    def test_seven_day_averages_exclude_older_records(self):
        old = (datetime.now(KST).date() - timedelta(days=10)).isoformat()
        self.care.checkin(self.session, {"date": old, "sleep": 1})
        data = self.care.checkin(self.session, {"sleep": 8})
        self.assertEqual(data["summary"]["days"], 1)
        self.assertEqual(data["summary"]["averages"]["sleep"], 8)

    def test_daily_goal_tick_is_idempotent_and_session_owned(self):
        data = self.care.goal(self.session, {"title": "10분 산책"})
        goal = data["goals"][0]["id"]
        self.care.tick(self.session, goal, {"done": True})
        data = self.care.tick(self.session, goal, {"done": True})
        self.assertEqual(data["goals"][0]["completed_dates"], [today()])
        with self.assertRaises(KeyError):
            self.care.tick(self.other, goal, {"done": False})
        data = self.care.tick(self.session, goal, {"done": False})
        self.assertEqual(data["goals"][0]["completed_dates"], [])

    def test_event_update_delete_and_calendar_escaping(self):
        data = self.care.event(self.session, {"title": "한글 산책" * 20, "start": self.when(),
                              "note": "메모\nBEGIN:VEVENT,;\\"})
        item = data["events"][0]["id"]
        calendar = self.care.calendar(self.session)
        self.assertEqual(calendar.count(b"BEGIN:VEVENT\r\n"), 1)
        self.assertIn(b"\\nBEGIN:VEVENT\\,\\;\\\\", calendar)
        self.assertTrue(all(len(line) <= 75 for line in calendar.split(b"\r\n")))
        calendar.decode("utf-8")
        updated = self.care.event(self.session, {"title": "수정", "start": self.when(2)}, item)
        self.assertEqual(updated["events"][0]["title"], "수정")
        with self.assertRaises(KeyError):
            self.care.delete(self.other, "events", item)
        self.assertEqual(self.care.delete(self.session, "events", item)["events"], [])

    def test_event_end_must_follow_start(self):
        with self.assertRaises(ValueError):
            self.care.event(self.session, {"title": "일정", "start": self.when(2), "end": self.when(1)})

    def test_calendar_detects_overlap_and_allows_adjacent_events(self):
        start = datetime.now(KST) + timedelta(days=1)
        first = self.care.event(self.session, {"title": "첫 일정", "start": start.isoformat()})
        second = self.care.event(self.session, {"title": "다음 일정", "start": (start + timedelta(minutes=30)).isoformat()})
        self.assertEqual(second["conflicts"], [])
        overlap = self.care.event(self.session, {"title": "겹침", "start": (start + timedelta(minutes=10)).isoformat()})
        self.assertEqual(len(overlap["conflicts"]), 2)

    def test_numeric_chat_checkin_is_a_proposal_and_drops_unreported_values(self):
        result = validate_result({"reply": "초안", "source_ids": [], "memories": [], "actions": [
            {"type": "checkin", "label": "확인", "sleep": "6", "stress": "9"}]}, "오늘 6시간 잤어", [])
        self.assertEqual(result["actions"][0]["sleep"], "6")
        self.assertNotIn("stress", result["actions"][0])
        self.assertEqual(self.care.dashboard(self.session)["checkins"], [])

    def test_booking_is_prepared_without_claiming_external_completion(self):
        booking = self.prepare()
        self.assertEqual(booking["status"], "prepared")
        self.assertEqual(self.care.dashboard(self.session)["events"], [])

    def test_booking_cannot_use_another_session_search_or_fabricated_hospital(self):
        self.app.web_search(self.session, {"query": "fixture"}, "hospitals")
        search_id = self.care.dashboard(self.session)["searches"][0]["id"]
        for session, hospital in [(self.other, "f" * 32), (self.session, "a" * 32)]:
            with self.assertRaises(ValueError):
                self.care.booking(session, {"search_id": search_id, "hospital_id": hospital, "start": self.when()})

    def test_confirmation_requires_external_user_attestation_and_creates_one_event(self):
        booking = self.prepare()
        for body in [{"status": "confirmed"}, {"status": "confirmed", "confirmed_by_user": True, "confirmation": ""}]:
            with self.assertRaises(ValueError):
                self.care.booking_status(self.session, booking["id"], body)
        body = {"status": "confirmed", "confirmed_by_user": True, "confirmation": "합성 병원 확인"}
        data = self.care.booking_status(self.session, booking["id"], body)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["status"], "user_confirmed")
        with self.assertRaises(ValueError):
            self.care.booking_status(self.session, booking["id"], body)
        self.assertEqual(len(self.care.dashboard(self.session)["events"]), 1)

    def test_cancel_removes_calendar_event_without_external_call(self):
        b = self.prepare()
        self.care.booking_status(self.session, b["id"], {"status": "confirmed", "confirmed_by_user": True, "confirmation": "합성 확인"})
        event = self.care.dashboard(self.session)["events"][0]
        with self.assertRaises(ValueError):
            self.care.delete(self.session, "events", event["id"])
        data = self.care.booking_status(self.session, b["id"], {"status": "cancelled", "confirmed_by_user": True})
        self.assertEqual(data["events"], [])
        self.assertEqual(data["bookings"][0]["status"], "cancelled")

    def test_whole_session_deletion_cascades_all_care_records(self):
        self.care.checkin(self.session, {"sleep": 6})
        self.care.goal(self.session, {"title": "산책"})
        b = self.prepare()
        self.care.booking_status(self.session, b["id"], {"status": "confirmed", "confirmed_by_user": True, "confirmation": "합성 확인"})
        self.app.store.delete_session(self.session)
        with self.app.store.connect() as db:
            for table in ("checkins", "goals", "goal_ticks", "events", "bookings", "searches"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_search_failure_does_not_save_results_and_retry_runs_directly(self):
        with self.assertRaises(ModelError):
            self.app.web_search(self.session, {"query": "fail"}, "hospitals")
        self.assertEqual(self.care.dashboard(self.session)["searches"], [])
        result = self.app.web_search(self.session, {"query": "fixture"}, "hospitals")
        self.assertEqual(len(result["searches"]), 1)

    def test_library_filters_and_named_herbs_do_not_leak_unrelated_records(self):
        self.assertGreaterEqual(self.app.store.knowledge_count(), 40)
        records = self.app.store.library("인삼", "herb")
        self.assertTrue(records)
        self.assertTrue(all("인삼" in r["tags"] for r in records))
        self.assertEqual(self.app.store.library("없는자료가나다", "herb"), [])

    def test_unknown_owner_and_sql_table_are_rejected(self):
        with self.assertRaises(KeyError):
            self.care.checkin("a" * 32, {"sleep": 5})
        with self.assertRaises(ValueError):
            self.care.delete(self.session, "events; DROP TABLE sessions", "a" * 32)

    def test_dangerous_urls_are_removed(self):
        for url in ["javascript:alert(1)", "http://example.org", "https://127.0.0.1/test", "https://10.0.0.1", "https://user:pass@example.org"]:
            self.assertEqual(safe_url(url), "")
        self.assertEqual(safe_url("https://example.org/source"), "https://example.org/source")


if __name__ == "__main__":
    unittest.main()
