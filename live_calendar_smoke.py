"""Real Luna High manages an isolated own calendar; the clinic is explicitly synthetic."""
import json
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from care import KST
from server import App, Handler, ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.monotonic()
    problems = []
    with tempfile.TemporaryDirectory() as directory:
        app = App(Path(directory), ROOT/"data"/"knowledge.seed.json")
        assert app.codex_enabled
        sid = app.store.create_session()["id"]
        hospital = {"id": "f"*32, "name": "합성 캘린더테스트한의원", "address": "합성 주소", "phone": "",
            "booking_url": "https://example.org/booking", "website": "", "source_url": "https://example.org/clinic",
            "reason": "자동 검증용 합성 병원이며 실제 예약은 없음", "reviews": []}
        app.care.save_search(sid, "hospitals", {"query": "합성 테스트", "summary": "합성 검색 결과",
            "hospitals": [hospital], "results": [], "searched_at": datetime.now(KST).isoformat(), "provider": "synthetic fixture"})
        handler = type("CalendarLiveHandler", (Handler,), {"app": app})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        output = ROOT/".runtime"/"screenshots"
        output.mkdir(parents=True,exist_ok=True)
        checks = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                page = browser.new_page(viewport={"width":1440,"height":1024})
                page.on("pageerror", lambda e: problems.append(str(e)))
                page.add_init_script("localStorage.setItem('hanui_session',"+json.dumps(sid)+");")
                page.goto(f"http://127.0.0.1:{server.server_port}",wait_until="networkidle")
                page.locator("#message").fill("대화에 남겨 둔 초안")
                page.get_by_role("button",name="일정·예약",exact=True).click()
                expect(page.locator("#calendar-grid .calendar-cell")).to_have_count(42)
                def request(message):
                    page.locator("#calendar-message").fill(message)
                    with page.expect_response(lambda r:r.url.endswith("/chat") and r.request.method=="POST", timeout=240000) as response:
                        page.locator("#calendar-send").click()
                    assert response.value.status==200, response.value.json()
                    expect(page.locator("#calendar-send")).to_be_enabled(timeout=15000)
                    session = app.store.get_session(sid)
                    print("PASS: "+message, flush=True)
                    checks.append(message)
                    return session
                result = request("내일 오후 3시에 '산책' 일정을 30분 넣어줘.")
                assert len(result["care"]["events"])==1
                event = result["care"]["events"][0]
                tomorrow = (datetime.now(KST)+timedelta(days=1)).date().isoformat()
                assert event["start"].startswith(tomorrow+"T15:00")
                expect(page.locator("#calendar-day-list")).to_contain_text("산책")
                page.screenshot(path=str(output/"desktop-own-calendar.png"),full_page=True)
                result = request("방금 넣은 산책을 내일 오후 4시로 옮겨줘.")
                assert len(result["care"]["events"])==1
                assert result["care"]["events"][0]["id"]==event["id"]
                assert result["care"]["events"][0]["start"].startswith(tomorrow+"T16:00")
                with page.expect_download() as download:
                    page.locator("#calendar-export").click()
                assert "산책" in Path(download.value.path()).read_text(encoding="utf-8")
                result = request("그 산책 일정 삭제해줘.")
                assert not result["care"]["events"]
                expect(page.locator("#calendar-day-list .calendar-entry")).to_have_count(0)
                result = request("운동 일정을 하나 넣어줘. 날짜와 시간은 아직 못 정했어.")
                assert not result["care"]["events"]
                result = request("기록에 있는 합성 캘린더테스트한의원으로 내일 오후 2시 예약 준비를 저장해줘.")
                assert len(result["care"]["bookings"])==1 and not result["care"]["events"]
                expect(page.locator(".calendar-pill.prepared")).to_have_count(1)
                result = request("그 예약은 병원에 전화해서 내일 오후 2시로 확정받았어. 확정 기록을 남겨줘.")
                assert result["care"]["bookings"][0]["status"]=="confirmed"
                assert len(result["care"]["events"])==1
                expect(page.locator(".calendar-pill.confirmed")).to_have_count(1)
                page.get_by_role("button",name="대화",exact=True).click()
                expect(page.locator("#message")).to_have_value("대화에 남겨 둔 초안")
                page.get_by_role("button",name="일정·예약",exact=True).click()
                result = request("그 병원 방문 희망 시간을 내일 오후 5시로 바꿔줘.")
                assert result["care"]["bookings"][0]["status"]=="prepared"
                assert result["care"]["bookings"][0]["start"].startswith(tomorrow+"T17:00")
                assert not result["care"]["events"]
                page.set_viewport_size({"width":390,"height":844})
                assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
                page.locator("#calendar-grid").scroll_into_view_if_needed()
                page.screenshot(path=str(output/"mobile-own-calendar.png"),full_page=True)
                page.reload(wait_until="networkidle")
                page.get_by_role("button",name="일정·예약",exact=True).click()
                expect(page.locator(".calendar-pill.prepared")).to_have_count(1)
                result = request("그 예약 준비 취소해줘.")
                assert result["care"]["bookings"][0]["status"]=="cancelled"
                expect(page.locator(".calendar-pill.prepared")).to_have_count(0)
                page.locator("#calendar-next").click()
                page.locator("#calendar-prev").click()
                page.get_by_role("button",name="대화",exact=True).click()
                # Reload discarded the unsaved draft; calendar sends before reload preserved it.
                assert page.locator("a[href*='calendar.google.com']").count()==0
                page.locator("#new-chat").click()
                page.get_by_role("button",name="일정·예약",exact=True).click()
                expect(page.locator("#bookings-list .record-row")).to_have_count(0)
                assert not problems, problems
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
    report = {"model":"gpt-6-luna","effort":"high","turns":len(checks),"clinic":"synthetic fixture; no external booking",
        "checks":["natural-language create/move/delete", "missing date/time asks without writing", "local booking preparation",
            "reported external confirmation", "reschedule needs re-confirmation", "local cancellation", "month and day UI",
            "ICS export", "reload", "mobile layout", "conversation isolation", "no Google Calendar"],
        "console_errors":problems,"booking_submitted":False,"elapsed_seconds":round(time.monotonic()-started,1)}
    (ROOT/".runtime"/"calendar-live-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
