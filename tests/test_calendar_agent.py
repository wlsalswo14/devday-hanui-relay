import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from care import KST
from codex_bridge import validate_result
from server import App, ROOT


class CalendarModel:
    def __init__(self): self.actions = []
    def available(self): return True
    def respond(self, message, history, memories, sources):
        return validate_result({"reply": "캘린더를 정리할게요.", "source_ids": [], "memories": [],
            "citations": [], "actions": self.actions}, message, sources)


class CalendarAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.model = CalendarModel()
        self.app = App(Path(self.temp.name), ROOT/"data"/"knowledge.seed.json", self.model)
        self.sid = self.app.store.create_session()["id"]
        self.other = self.app.store.create_session()["id"]
        self.start = (datetime.now(KST)+timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0).isoformat()
        self.hospital = {"id": "f"*32, "name": "합성 한의원", "address": "합성 주소", "phone": "",
            "website": "", "booking_url": "", "source_url": "https://example.org/clinic", "reason": "합성 자료", "reviews": []}
        self.search = self.app.care.save_search(self.sid, "hospitals", {"hospitals": [self.hospital]})

    def tearDown(self): self.temp.cleanup()

    def chat(self, instruction, *actions):
        self.model.actions = [{"instruction_quote": instruction, **action} for action in actions]
        return self.app.chat(self.sid, {"message": instruction, "mode": "codex"})

    def create(self):
        return self.chat("이틀 뒤 14시에 산책 일정 넣어줘", {"type": "event", "operation": "create",
            "title": "산책", "start": self.start, "end": (datetime.fromisoformat(self.start)+timedelta(minutes=45)).isoformat(), "location": "동네 공원"})["care"]["events"][0]

    def prepare(self):
        return self.chat("합성 한의원 이틀 뒤 14시 예약 준비해줘", {"type": "booking", "operation": "create",
            "search_id": self.search, "hospital_id": self.hospital["id"], "start": self.start})["care"]["bookings"][0]

    def confirm(self, booking):
        return self.chat("병원에 전화해서 그 시간으로 확정받았어", {"type": "booking", "operation": "confirm", "target_id": booking["id"]})

    def test_create_and_update_preserve_duration_and_unchanged_fields(self):
        event = self.create()
        new_start = (datetime.fromisoformat(self.start)+timedelta(hours=1)).isoformat()
        result = self.chat("산책을 15시로 옮겨줘", {"type": "event", "operation": "update", "target_id": event["id"], "start": new_start})
        changed = result["care"]["events"][0]
        self.assertEqual(changed["id"], event["id"])
        self.assertEqual(changed["location"], "동네 공원")
        self.assertEqual(datetime.fromisoformat(changed["end"])-datetime.fromisoformat(changed["start"]), timedelta(minutes=45))
        self.assertTrue(result["messages"][-1]["actions"][0]["completed"])
        self.assertIn("일정을 수정했어요", result["messages"][-1]["content"])

    def test_delete_is_persistent_and_other_conversation_is_unchanged(self):
        event = self.create()
        self.app.care.event(self.other, {"title": "다른 대화", "start": self.start})
        self.chat("산책 삭제해줘", {"type": "event", "operation": "delete", "target_id": event["id"]})
        self.assertEqual(self.app.store.get_session(self.sid)["care"]["events"], [])
        self.assertEqual(len(self.app.store.get_session(self.other)["care"]["events"]), 1)

    def test_foreign_target_and_unquoted_instruction_cannot_write(self):
        foreign = self.app.care.event(self.other, {"title": "다른 대화", "start": self.start})["events"][0]
        with self.assertRaises(ValueError):
            self.chat("다른 대화 삭제해줘", {"type": "event", "operation": "delete", "target_id": foreign["id"]})
        with self.assertRaises(ValueError):
            self.chat("안녕", {"type": "event", "operation": "create", "title": "위조", "start": self.start,
                "instruction_quote": "일정 추가해줘"})
        self.assertEqual(self.app.store.get_session(self.sid)["messages"], [])

    def test_hypothetical_or_prohibition_is_not_a_write_instruction(self):
        for message in ("산책을 추가하면 어떻게 돼?", "산책을 추가하지 마"):
            with self.assertRaises(ValueError):
                self.chat(message, {"type": "event", "operation": "create", "title": "산책", "start": self.start})
        self.assertEqual(self.app.care.dashboard(self.sid)["events"], [])

    def test_multi_action_failure_rolls_back_calendar_and_chat(self):
        with self.assertRaises(ValueError):
            self.chat("산책 넣고 없는 일정 삭제해줘", {"type": "event", "operation": "create", "title": "산책", "start": self.start},
                {"type": "event", "operation": "delete", "target_id": "a"*32})
        result = self.app.store.get_session(self.sid)
        self.assertEqual(result["care"]["events"], [])
        self.assertEqual(result["messages"], [])

    def test_booking_creates_only_preparation_and_cannot_use_foreign_search(self):
        booking = self.prepare()
        self.assertEqual(booking["status"], "prepared")
        self.assertEqual(self.app.care.dashboard(self.sid)["events"], [])
        with self.assertRaises(ValueError):
            self.app.calendar_action(self.other, {"type": "booking", "operation": "create", "instruction_quote": "예약 준비해줘",
                "search_id": self.search, "hospital_id": self.hospital["id"], "start": self.start}, "예약 준비해줘")

    def test_confirmation_needs_report_of_actual_hospital_confirmation(self):
        booking = self.prepare()
        for message in ("그 예약 확정해줘", "아직 확정받지 못했어", "확정받지 못했어", "확정받은 건 아니야"):
            with self.assertRaises(ValueError):
                self.chat(message, {"type": "booking", "operation": "confirm", "target_id": booking["id"]})
        confirmed = self.confirm(booking)
        self.assertEqual(confirmed["care"]["bookings"][0]["status"], "confirmed")
        self.assertEqual(len(confirmed["care"]["events"]), 1)

    def test_local_cancel_removes_linked_visit_without_external_claim(self):
        booking = self.prepare()
        self.confirm(booking)
        result = self.chat("예약 취소해줘", {"type": "booking", "operation": "cancel", "target_id": booking["id"]})
        self.assertEqual(result["care"]["events"], [])
        self.assertEqual(result["care"]["bookings"][0]["status"], "cancelled")
        self.assertIn("실제 예약은 병원에도", result["messages"][-1]["content"])

    def test_moving_confirmed_booking_returns_to_preparation(self):
        booking = self.prepare()
        self.confirm(booking)
        later = (datetime.fromisoformat(self.start)+timedelta(hours=2)).isoformat()
        result = self.chat("방문 시간을 16시로 바꿔줘", {"type": "booking", "operation": "update", "target_id": booking["id"], "start": later})
        changed = result["care"]["bookings"][0]
        self.assertEqual(changed["start"], later)
        self.assertEqual(changed["status"], "prepared")
        self.assertEqual(changed["confirmation"], "")
        self.assertEqual(result["care"]["events"], [])

    def test_prepared_visit_is_tentative_in_export_and_disappears_after_cancel(self):
        booking = self.prepare()
        calendar = self.app.care.calendar(self.sid)
        self.assertIn(b"STATUS:TENTATIVE", calendar)
        self.assertIn(("UID:booking-"+booking["id"]).encode(), calendar)
        self.assertNotIn(b"STATUS:CONFIRMED", calendar)
        self.chat("예약 준비 취소해줘", {"type": "booking", "operation": "cancel", "target_id": booking["id"]})
        self.assertNotIn(b"BEGIN:VEVENT", self.app.care.calendar(self.sid))


if __name__ == "__main__": unittest.main()
