"""Google-hosted Gemma agent; reuse Hanui's exact citation/action validators."""
from __future__ import annotations

import ctypes
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from codex_bridge import CodexChat, ModelError

MODEL = "gemma-4-26b-a4b-it"
EFFORT = "high"
KEY_FILE = Path(__file__).resolve().parent / ".runtime/google-key.dpapi"


def protect_key(value: bytes, *, decrypt=False) -> bytes:
    """Windows DPAPI: bound to the current OS account, never a plaintext file."""
    if os.name != "nt":
        raise RuntimeError("Use HANUI_GOOGLE_API_KEY outside Windows.")
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(value)
    incoming = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    function = getattr(ctypes.windll.crypt32, "CryptUnprotectData" if decrypt else "CryptProtectData")
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise RuntimeError("Windows credential protection failed.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.data)


def load_key():
    value = os.environ.get("HANUI_GOOGLE_API_KEY", "").strip()
    if value:
        return value
    if KEY_FILE.exists():
        return protect_key(KEY_FILE.read_bytes(), decrypt=True).decode("utf-8")
    return ""


class GemmaChat(CodexChat):
    model_name = MODEL
    effort = EFFORT
    provider = "google"

    def __init__(self, runtime, key=None):
        self.runtime = runtime
        self.key = key if key is not None else load_key()
        self.care_context = {}
        self.lookup_context = {}

    def available(self):
        return bool(self.key)

    def execute(self, system, payload, schema, web=False):
        if not self.key:
            raise ModelError("Gemma 연결 키가 설정되지 않았어요.")
        # Do not describe Codex-only tools in the Google prompt. All DB and calendar
        # operations continue to run through the existing server-side validators.
        system = system.replace("OpenAI web search", "Google Search").replace("Luna High", "the agent")
        prompt = system + "\nReturn ONLY JSON matching this schema:\n" + json.dumps(schema)
        prompt += "\nDATA:\n" + json.dumps(payload, ensure_ascii=False)
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"thinkingConfig": {"thinkingLevel": "high"},
                                     "maxOutputTokens": 16000}}
        if web:
            body["tools"] = [{"googleSearch": {}}]
        request = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            # Never expose provider bodies, which can echo the credential or patient text.
            exc.close()
            if exc.code == 429:
                raise ModelError("Gemma 요청 한도에 도달했어요. 잠시 후 다시 시도해 주세요.") from None
            raise ModelError(f"Gemma 연결을 완료하지 못했어요. (HTTP {exc.code})") from None
        except (OSError, ValueError):
            raise ModelError("Gemma 응답을 받지 못했어요. 다시 시도해 주세요.") from None
        candidate = next(iter(result.get("candidates", [])), {})
        text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []) if not p.get("thought"))
        if text.strip().startswith("```"):
            text = text.strip().split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise ModelError("Gemma 응답 형식을 확인하지 못했어요. 기록은 변경하지 않았어요.") from None
        grounding = candidate.get("groundingMetadata", {})
        self.grounding = grounding
        events = ([{"type": "item.completed", "item": {"type": "web_search"}}]
                  if grounding.get("webSearchQueries") and grounding.get("groundingChunks") else [])
        return parsed, events

    def search_web(self, query, kind):
        result = super().search_web(query, kind)
        # Only retain URLs actually returned by the provider's grounding sources.
        grounded = {c.get("web", {}).get("uri") for c in self.grounding.get("groundingChunks", [])}
        result["results"] = [r for r in result["results"] if r["url"] in grounded]
        result["hospitals"] = [h for h in result["hospitals"] if h["source_url"] in grounded]
        if not result["results"] and not result["hospitals"]:
            raise ModelError("검색 출처를 검증하지 못했어요. 확인되지 않은 병원은 표시하지 않아요.")
        result["provider"] = "Google · Gemma 4 · Google Search"
        return result
