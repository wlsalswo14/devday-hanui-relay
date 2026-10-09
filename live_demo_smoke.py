"""Real Codex demo flow against an isolated DB; no hospital booking is submitted."""
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from care import KST
from codex_bridge import MODEL, EFFORT
from server import App, ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        app = App(Path(directory), ROOT / "data" / "knowledge.seed.json")
        assert app.codex_enabled, "Codex login unavailable"
        sid = app.store.create_session()["id"]
        first = app.chat(sid, {"message": "요즘 하루 5시간 자고 커피를 2잔 마셔. 이 생활 패턴을 기억해줘.", "mode": "codex"})
        assert any("5시간" in m["quote"] for m in first["memories"]), "Self-report not saved"
        print("PASS: self-reported lifestyle memory", flush=True)
        second = app.chat(sid, {"message": "내가 몇 시간 잔다고 했지? 황제내경의 미병과 생활관리 관련 DB 원문을 찾아 인용 위치도 보여줘.", "mode": "codex"})
        reply = second["messages"][-1]
        assert "5시간" in reply["content"] or "5 시간" in reply["content"], "Previous context not recalled"
        classical = [s for s in reply["sources"] if s["category"] == "classical" and s.get("citations")]
        assert classical, "No exact classical citation"
        for source in classical:
            assert source["location"] and source["source_revision"]
            for citation in source["citations"]:
                assert source["body"][citation["offset_start"]:citation["offset_end"]] == citation["quote"]
        print("PASS: recall, classical full-text retrieval and verified original locations", flush=True)
        app.care.checkin(sid, {"date": datetime.now(KST).date().isoformat(), "sleep": 5, "caffeine": 2,
            "note": "합성 데모 입력의 수치만 저장"})
        app.care.goal(sid, {"title": "점심 후 10분 산책"})
        third = app.chat(sid, {"message": "강남역 주변 한의원 1곳을 찾아 이름, 주소, 공개 정보에 근거한 추천 이유와 전화·예약 링크를 알려줘. 방문 준비만 할게.", "mode": "codex"})
        actions = [a for a in third["messages"][-1]["actions"] if a["type"] == "hospitals" and a.get("completed")]
        assert actions and actions[0]["result"]["hospitals"], "No real sourced hospital"
        hospital = actions[0]["result"]["hospitals"][0]
        assert hospital["name"] and hospital["address"] and hospital["reason"] and hospital["source_url"]
        assert not third["care"]["bookings"] and not third["care"]["events"], "Search unexpectedly changed visit records"
        start = (datetime.now(KST)+timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
        prepared = app.care.booking(sid, {"search_id": actions[0]["search_id"], "hospital_id": hospital["id"],
            "start": start.isoformat(), "note": "실제 접수 없이 데모 방문 준비만 저장"})
        assert prepared["bookings"][0]["status"] == "prepared" and not prepared["events"]
        care = app.care.event(sid, {"title": hospital["name"]+" 방문 계획", "start": start.isoformat(),
            "location": hospital["address"], "note": "개인 일정이며 병원 예약 확정이 아님"})
        assert care["events"][0]["kind"] == "personal"
        calendar = app.care.calendar(sid)
        if isinstance(calendar, bytes):
            calendar = calendar.decode("utf-8")
        assert "BEGIN:VEVENT" in calendar and "LOCATION:" in calendar
        restored = app.store.get_session(sid)
        assert restored["memories"] and restored["care"]["checkins"] and restored["care"]["goals"]
        assert restored["messages"][-3]["sources"] == reply["sources"]
        assert len(restored["care"]["events"]) == 1
        other = app.store.create_session()["id"]
        assert not app.store.get_session(other)["care"]["bookings"]
        report = {"model": MODEL, "effort": EFFORT, "turns": 3, "knowledge_records": app.store.knowledge_count(),
            "classical_cited_records": len(classical), "hospital_candidates": len(actions[0]["result"]["hospitals"]),
            "checks": ["persistent dialogue", "self-report recall", "classical full-text retrieval", "exact original citations and offsets",
                "daily checkin and goal", "live Codex hospital lookup", "name/address/recommendation evidence", "booking preparation only",
                "personal visit schedule", "ICS export", "reload and separate conversations"],
            "booking_submitted": False, "elapsed_seconds": round(time.monotonic()-started, 1)}
    (ROOT / ".runtime" / "demo-live-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
