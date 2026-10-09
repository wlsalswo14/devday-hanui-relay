import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from google_transport import send
from request_lifecycle import RequestCancelled
from server import App, Handler


class SlowProvider(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.started.set()
        self.server.release.wait(10)
        try:
            self.send_response(200)
            body=b'{}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError: pass


class SlowModel:
    def __init__(self, url): self.url=url
    def available(self): return True
    def respond(self, message, history, memories, sources):
        if message=="slow":
            send(urllib.request.Request(self.url, data=b'{}', headers={"Content-Type":"application/json"}))
        return {"reply":"Fixture", "source_ids":[], "memories":[], "actions":[]}


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.provider=ThreadingHTTPServer(("127.0.0.1",0), SlowProvider)
        self.provider.started=threading.Event()
        self.provider.release=threading.Event()
        threading.Thread(target=self.provider.serve_forever,daemon=True).start()
        self.app=App(Path(self.temp.name),model=SlowModel(f"http://127.0.0.1:{self.provider.server_port}/"))
        self.sid=self.app.store.create_session()["id"]
        self.server=ThreadingHTTPServer(("127.0.0.1",0),type("CancelHandler",(Handler,),{"app":self.app}))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()

    def tearDown(self):
        self.provider.release.set()
        self.server.shutdown();self.server.server_close()
        self.provider.shutdown();self.provider.server_close()
        self.temp.cleanup()

    def post(self, path, body):
        connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        connection.request("POST",path,json.dumps(body),{"Content-Type":"application/json"})
        return connection

    def start(self):
        rid=uuid.uuid4().hex
        connection=self.post(f"/api/sessions/{self.sid}/chat",{"message":"slow","request_id":rid})
        self.assertTrue(self.provider.started.wait(3),"isolated HTTP worker never reached fake provider")
        return rid,connection

    def assert_ready(self):
        deadline=time.monotonic()+1.5
        while self.app.lock.locked() and time.monotonic()<deadline:time.sleep(.02)
        self.assertFalse(self.app.lock.locked())
        self.assertEqual(self.app.store.get_session(self.sid)["messages"],[])
        connection=self.post(f"/api/sessions/{self.sid}/chat",{"message":"fast"})
        response=connection.getresponse()
        self.assertEqual(response.status,200,response.read())
        response.read();connection.close()

    def test_cancel_kills_worker_discards_turn_and_accepts_next_request(self):
        rid,connection=self.start()
        cancel=self.post(f"/api/requests/{rid}/cancel",{})
        self.assertEqual(cancel.getresponse().status,200)
        cancel.close()
        response=connection.getresponse()
        self.assertEqual(response.status,499,response.read())
        response.read();connection.close()
        self.assert_ready()

    def test_browser_disconnect_without_beacon_also_releases_request(self):
        _,connection=self.start()
        connection.sock.shutdown(socket.SHUT_RDWR)
        connection.close()
        self.assert_ready()

    def test_cancel_before_post_cannot_start_model(self):
        rid=uuid.uuid4().hex
        self.app.requests.cancel(rid)
        with self.assertRaises(RequestCancelled), self.app.requests.scope(request_id=rid):
            self.app.chat(self.sid,{"message":"fast"})
        self.assertEqual(self.app.store.get_session(self.sid)["messages"],[])

    def test_cancel_during_saving_rolls_back_turn(self):
        rid=uuid.uuid4().hex
        original=self.app.store.save_turn
        def cancel_after_save(*args,**kwargs):
            result=original(*args,**kwargs)
            self.app.requests.cancel(rid)
            return result
        with patch.object(self.app.store,"save_turn",side_effect=cancel_after_save):
            with self.assertRaises(RequestCancelled), self.app.requests.scope(request_id=rid):
                self.app.chat(self.sid,{"message":"fast"})
        self.assertEqual(self.app.store.get_session(self.sid)["messages"],[])
        self.assertFalse(self.app.lock.locked())

    def test_cancel_during_saving_also_rolls_back_calendar_change(self):
        rid=uuid.uuid4().hex
        message="산책 일정 넣어줘"
        self.app.model.respond=lambda *args: {"reply":"Fixture", "source_ids":[], "memories":[],
            "actions":[{"type":"event","operation":"create","title":"산책",
                        "start":"2026-10-10T15:00:00+09:00","instruction_quote":message}]}
        original=self.app.store.save_turn
        def cancel_after_save(*args,**kwargs):
            result=original(*args,**kwargs)
            self.app.requests.cancel(rid)
            return result
        with patch.object(self.app.store,"save_turn",side_effect=cancel_after_save):
            with self.assertRaises(RequestCancelled), self.app.requests.scope(request_id=rid):
                self.app.chat(self.sid,{"message":message})
        session=self.app.store.get_session(self.sid)
        self.assertEqual(session["messages"],[])
        self.assertEqual(session["care"]["events"],[])
