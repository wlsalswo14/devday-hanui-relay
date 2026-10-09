"""Live Luna query planning, classical exact quotations and conversational web lookup."""
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
        execute = app.model.execute
        def capture(system, payload, schema, web=False):
            parsed, events = execute(system, payload, schema, web)
            if "keywords" in schema["properties"]:
                (ROOT / ".runtime" / "retrieval-keywords-debug.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
            if "RETRIEVED_KNOWLEDGE" in payload:
                (ROOT / ".runtime" / "retrieval-debug.json").write_text(json.dumps({
                    "source_ids": [s["id"] for s in payload["RETRIEVED_KNOWLEDGE"]],
                    "parsed": parsed}, ensure_ascii=False, indent=2), encoding="utf-8")
            return parsed, events
        app.model.execute = capture
        sid = app.store.create_session()["id"]
        report = {"model": "gpt-6-luna", "effort": "high", "checks": []}
        for message in [
            "황제내경에서 미병과 일상생활 관리에 관해 어떤 말을 했는지 DB 원문을 찾아 인용 위치와 함께 설명해줘.",
            "이번엔 인삼 관련 고문헌 DB 원문과 현재 NIH NCCIH의 공식 인삼 자료를 웹에서 직접 찾아 비교해줘.",
        ]:
            session = app.chat(sid, {"message": message, "mode": "codex"})
            reply = session["messages"][-1]
            classical = [s for s in reply["sources"] if s["category"] == "classical"]
            assert classical, "No classical DB record used"
            assert any(s.get("citations") for s in classical), "No verified classical quote"
            for source in classical:
                assert source["location"] and source["source_revision"]
                for citation in source.get("citations", []):
                    assert source["body"][citation["offset_start"]:citation["offset_end"]] == citation["quote"]
            if "웹에서" in message:
                web = [a for a in reply["actions"] if a["type"] == "web" and a.get("completed")]
                assert web and web[0]["result"]["results"], "No conversational live web results"
            report["checks"].append({"question": message, "reply": reply["content"],
                "sources": reply["sources"], "actions": reply["actions"]})
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        (ROOT / ".runtime" / "retrieval-live-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"model": report["model"], "effort": report["effort"],
            "turns": len(report["checks"]), "verified_classical_sources": [len([s for s in c["sources"] if s["category"] == "classical"]) for c in report["checks"]],
            "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
