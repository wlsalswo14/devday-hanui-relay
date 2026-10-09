"""Explicit live check: two synthetic turns using the signed-in OpenAI account."""
import json
import sys
import tempfile
import time
from pathlib import Path

from server import App, ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        app = App(Path(directory), ROOT / "data" / "knowledge.seed.json")
        if not app.codex_enabled:
            raise RuntimeError("ChatGPT login is unavailable")
        session_id = app.store.create_session()["id"]
        first = app.chat(session_id, {"message": "요즘 5시간 정도 자고 낮에 피곤해. 이 내용을 기억해줘.",
                        "mode": "codex"})
        assert first["memories"], "No self-reported memory extracted"
        assert any("5시간" in m["quote"] for m in first["memories"])
        second = app.chat(session_id, {"message": "아까 내가 몇 시간 잔다고 했지? 미병이 뭔지도 자료를 찾아 알려줘.",
                         "mode": "codex"})
        reply = second["messages"][-1]
        assert "5시간" in reply["content"] or "5 시간" in reply["content"], "Prior context not recalled"
        assert reply["sources"], "No actual DB citation returned"
        report = {"model": "gpt-6-luna", "effort": "high", "auth": "existing ChatGPT login",
                  "turns": 2, "memories": len(second["memories"]),
                  "source_ids": [s["id"] for s in reply["sources"]],
                  "elapsed_seconds": round(time.monotonic() - started, 1),
                  "reply": reply["content"]}
        folder = ROOT / ".runtime"
        folder.mkdir(exist_ok=True)
        (folder / "live-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
