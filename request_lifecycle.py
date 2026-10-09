"""Cancel browser-owned inference on explicit cancellation or disconnected HTTP."""
import contextvars
import re
import select
import socket
import threading
import time
import uuid
from contextlib import contextmanager

from codex_bridge import ModelError

CURRENT_REQUEST = contextvars.ContextVar("hanui_request", default=None)


class RequestCancelled(ModelError):
    def __init__(self):
        super().__init__("응답을 취소했어요.")


def check_cancelled():
    request = CURRENT_REQUEST.get()
    if request is not None and request.cancelled.is_set():
        raise RequestCancelled()


class RequestManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = {}
        self.cancelled = {}

    def cancel(self, request_id):
        if not re.fullmatch(r"[a-f0-9]{32}", request_id or ""):
            raise ValueError("취소할 요청을 확인해 주세요.")
        with self.lock:
            now = time.monotonic()
            self.cancelled = {k: v for k, v in self.cancelled.items() if now-v < 60}
            if len(self.cancelled) >= 256:
                self.cancelled.pop(next(iter(self.cancelled)))
            self.cancelled[request_id] = now
            request = self.active.get(request_id)
            if request:
                request.cancelled.set()

    @contextmanager
    def scope(self, connection=None, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id,str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise ValueError("요청 식별자가 올바르지 않아요.")
        request = type("Request", (), {})()
        request.cancelled, request.done = threading.Event(), threading.Event()
        with self.lock:
            if request_id in self.active:
                raise ValueError("이미 처리 중인 요청이에요.")
            if time.monotonic()-self.cancelled.get(request_id, -1000) < 60:
                request.cancelled.set()
            self.active[request_id] = request
        token = CURRENT_REQUEST.set(request)
        def watch():
            while not request.done.wait(.1):
                try:
                    readable, _, _ = select.select([connection], [], [], 0)
                    if readable and not connection.recv(1, socket.MSG_PEEK):
                        request.cancelled.set()
                        return
                except (OSError, ValueError):
                    request.cancelled.set()
                    return
        if connection is not None:
            threading.Thread(target=watch, daemon=True).start()
        try:
            check_cancelled()
            yield request
        finally:
            request.done.set()
            CURRENT_REQUEST.reset(token)
            with self.lock:
                self.active.pop(request_id, None)
