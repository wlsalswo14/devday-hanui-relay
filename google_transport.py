"""Isolated HTTP worker so cancelling a browser request closes Google's socket."""
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from request_lifecycle import CURRENT_REQUEST, check_cancelled


def send(request):
    check_cancelled()
    scope = CURRENT_REQUEST.get()
    if scope is None:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    # Credentials travel via an anonymous pipe, never arguments/files/log output.
    payload = {"url": request.full_url, "headers": dict(request.header_items()),
               "body": request.data.decode("utf-8")}
    process = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    first = True
    try:
        while True:
            check_cancelled()
            try:
                output, _ = process.communicate(json.dumps(payload) if first else None, timeout=.1)
                break
            except subprocess.TimeoutExpired:
                first = False
        check_cancelled()
        result = json.loads(output)
        if "http_status" in result:
            raise urllib.error.HTTPError(request.full_url, result["http_status"], "Provider error", {}, None)
        if process.returncode or "transport_error" in result:
            raise OSError("Provider connection failed")
        return result["response"]
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def worker():
    payload = json.load(sys.stdin)
    request = urllib.request.Request(payload["url"], data=payload["body"].encode("utf-8"),
                                     headers=payload["headers"], method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = {"response": json.load(response)}
    except urllib.error.HTTPError as exc:
        result = {"http_status": exc.code}
        exc.close()
    except Exception:
        result = {"transport_error": True}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    worker()
