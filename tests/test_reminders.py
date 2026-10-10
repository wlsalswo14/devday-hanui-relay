import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from care import KST
from google_bridge import GemmaChat
from codex_bridge import ModelError
from request_lifecycle import RequestCancelled
from server import App


class ReminderModel:
    def __init__(self): self.calls=[]
    def available(self): return True
    def generate_reminder(self,event):
        self.calls.append(event)
        return "다가오는 일정을 기억해 주세요."


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.model=ReminderModel();self.app=App(Path(self.temp.name),model=self.model)
        self.sid=self.app.store.create_session()['id'];self.now=datetime.now(KST)

    def event(self,minutes=10):
        care=self.app.care.event(self.sid,{'title':'산책','start':(self.now+timedelta(minutes=minutes)).isoformat(),
            'end':(self.now+timedelta(minutes=minutes+30)).isoformat(),'location':'공원','note':''})
        return care['events'][-1]

    def test_only_due_events_and_cached_reminder_are_generated(self):
        self.event();self.event(90)
        result=self.app.reminders.poll(self.sid,now=self.now)
        self.assertEqual(len(result['reminders']),1)
        self.assertEqual(result['reminders'][0]['title'],'산책')
        self.app.reminders.poll(self.sid,now=self.now)
        self.assertEqual(len(self.model.calls),1)

    def test_dismissal_survives_reload_and_session_isolation(self):
        self.event();item=self.app.reminders.poll(self.sid,now=self.now)['reminders'][0]
        other=self.app.store.create_session()['id']
        self.assertEqual(self.app.reminders.poll(other,now=self.now)['reminders'],[])
        self.app.reminders.poll(other,item['id'],now=self.now)
        self.assertEqual(len(self.app.reminders.poll(self.sid,now=self.now)['reminders']),1)
        self.app.reminders.poll(self.sid,item['id'],now=self.now)
        self.assertEqual(self.app.reminders.poll(self.sid,now=self.now)['reminders'],[])

    def test_deleted_or_rescheduled_event_invalidates_old_reminder(self):
        event=self.event();self.app.reminders.poll(self.sid,now=self.now)
        self.app.care.event(self.sid,{**event,'start':(self.now+timedelta(hours=3)).isoformat(),
            'end':(self.now+timedelta(hours=4)).isoformat()},event['id'])
        self.assertEqual(self.app.reminders.poll(self.sid,now=self.now)['reminders'],[])
        self.app.care.delete(self.sid,'events',event['id'])
        self.assertEqual(self.app.reminders.poll(self.sid,now=self.now)['reminders'],[])

    def test_event_removed_during_inference_is_never_notified(self):
        event=self.event()
        def generate(_):
            self.app.care.delete(self.sid,'events',event['id']);return '준비해 주세요.'
        with patch.object(self.model,'generate_reminder',side_effect=generate):
            self.assertEqual(self.app.reminders.poll(self.sid,now=self.now)['reminders'],[])

    def test_cancelled_generation_is_not_saved(self):
        self.event()
        with patch.object(self.model,'generate_reminder',side_effect=RequestCancelled()):
            with self.assertRaises(RequestCancelled):self.app.reminders.poll(self.sid,now=self.now)
        with self.app.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM reminders').fetchone()[0],0)

    def test_gemma_reminder_rejects_invented_numeric_details(self):
        model=GemmaChat(Path(self.temp.name),key='fixture')
        with patch.object(GemmaChat,'execute',return_value=({'note':'5분 늦어도 돼요'},[])):
            with self.assertRaises(ModelError): model.generate_reminder({'title':'산책','start':'2026-10-10T10:00:00+09:00'})
