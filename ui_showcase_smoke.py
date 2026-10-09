"""Verify populated demo stories through the actual UI using an isolated DB."""
import json
import re
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from seed_showcase import build_showcase
from server import App,Handler,ROOT
from ui_design_smoke import TEXT_CONTRAST


class OfflineModel:
    def available(self):return False


def main():
    sys.stdout.reconfigure(encoding="utf-8");errors=[]
    output=ROOT/".runtime"/"screenshots";output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        app=App(Path(directory),ROOT/"data"/"knowledge.seed.json",OfflineModel())
        showcase=build_showcase(app.store);sid=showcase["primary_session_id"]
        session=app.store.get_session(sid);report=app.store.guidance.report(sid)
        assert [m["role"] for m in session["messages"][:3]]==["assistant","user","assistant"]
        assert "어젯밤" in session["messages"][0]["content"]
        assert "새벽 1시" in session["messages"][1]["content"]
        assert "커피는 어제 몇 잔" in session["messages"][2]["content"]
        assert "합성 한의사 진단" in session["care"]["guidance"]["plans"][0]["assessment"]
        assert len(session["care"]["checkins"])==8
        assert len(session["care"]["events"])==7
        assert (report["recorded_days"],report["missing_days"])==(8,6)
        assert all(row["rate"]==75 for row in report["instructions"])
        for source in session["messages"][-1]["sources"]:
            for citation in source["citations"]:assert source["body"][citation["offset_start"]:citation["offset_end"]]==citation["quote"]
        evidence={o["id"]:o for o in report["evidence"]}
        assert all(set(c["evidence_ids"])<=evidence.keys() for c in report["claims"])
        assert all(o["content"][o["offset_start"]:o["offset_end"]]==o["quote"] for o in evidence.values())
        server=ThreadingHTTPServer(("127.0.0.1",0),type("ShowcaseHandler",(Handler,),{"app":app}))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                page=browser.new_page(viewport={"width":1440,"height":1100})
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.on("console",lambda m:errors.append(m.text) if m.type=="error" else None)
                page.goto(f"http://127.0.0.1:{server.server_port}/?session={sid}",wait_until="networkidle")
                expect(page.locator("#session-select")).to_have_value(sid)
                expect(page.locator("#context-sidebar")).to_be_hidden()
                chat_rect=page.locator("#messages").bounding_box()
                assert chat_rect["width"]>=1440*0.8 and chat_rect["height"]>=600,chat_rect
                page.locator("#messages").evaluate("e=>e.scrollTop=0")
                page.screenshot(path=str(output/"showcase-opening.png"))
                page.locator("#messages").evaluate("e=>e.scrollTop=e.scrollHeight")
                expect(page.locator(".hospital-card")).to_have_count(3)
                expect(page.locator("#guidance-count")).to_have_text("4")
                expect(page.locator("#sources .source-card")).to_have_count(2)
                latest=page.locator(".message.assistant").last
                expect(latest).to_contain_text("합성 예시")
                expect(latest.locator(".citation-reading")).to_have_count(2)
                expect(latest.locator(".reading-label").first).to_have_text("에이전트 해석")
                assert not latest.locator(".source-original").first.evaluate("e=>e.open")
                expect(latest.locator(".quoted-passage")).to_have_count(2)
                latest.locator(".bubble").scroll_into_view_if_needed()
                page.screenshot(path=str(output/"showcase-chat.png"),full_page=True)
                page.locator("#toggle-sidebar").click()
                page.locator("#sources .source-card").first.click()
                expect(page.locator("#source-dialog")).to_be_visible()
                expect(page.locator("#source-location")).not_to_be_empty()
                expect(page.locator("#source-reading")).not_to_be_empty()
                assert not page.locator("#source-dialog .source-original").evaluate("e=>e.open")
                page.keyboard.press("Escape")
                page.locator('.app-nav [data-view="daily"]').click()
                expect(page.locator(".clinician-goal")).to_have_count(4)
                page.screenshot(path=str(output/"showcase-daily.png"),full_page=True)
                page.locator('.app-nav [data-view="report"]').click()
                expect(page.locator("#print-report")).to_be_enabled()
                expect(page.locator("#report-sheet")).to_contain_text("75%")
                expect(page.locator("#report-sheet")).to_contain_text("기록 없음 6일")
                page.screenshot(path=str(output/"showcase-report.png"),full_page=True)
                pdf=page.pdf(path=str(ROOT/".runtime"/"showcase-report.pdf"),prefer_css_page_size=True,print_background=True)
                assert len(re.findall(rb"/Type\s*/Page\b",pdf))==1
                assert b"/URI" in pdf
                page.emulate_media(media="screen")
                page.locator('.report-instruction .patient-reference').first.click()
                expect(page.locator(".patient-evidence-card")).to_have_count(8)
                page.keyboard.press("Escape")
                page.locator('.app-nav [data-view="calendar"]').click()
                expect(page.locator("#calendar-grid .calendar-pill")).not_to_have_count(0)
                expect(page.locator("#bookings-list")).to_contain_text("예약 준비")
                expect(page.locator("#bookings-list")).to_contain_text("예약 확정")
                page.screenshot(path=str(output/"showcase-calendar.png"),full_page=True)
                ics=page.request.get(f"http://127.0.0.1:{server.server_port}/api/sessions/{sid}/calendar.ics").body()
                assert b"STATUS:TENTATIVE" in ics
                for width in [320,390]:
                    page.set_viewport_size({"width":width,"height":844})
                    for view in ["chat","daily","calendar","report"]:
                        page.locator(f'.app-nav [data-view="{view}"]').click()
                        if view=="chat" and page.locator("#context-sidebar").is_visible():page.locator("#close-sidebar").click()
                        if view=="report":expect(page.locator("#print-report")).to_be_enabled()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"),(width,view)
                        assert not page.evaluate(TEXT_CONTRAST)["failures"],(width,view)
                    if width==390:page.screenshot(path=str(output/"showcase-mobile-report.png"),full_page=True)
                page.set_viewport_size({"width":1440,"height":1100})
                page.locator("#session-select").select_option(showcase["secondary_session_id"])
                expect(page.locator(".report-instruction")).to_have_count(2)
                expect(page.locator("#report-sheet")).to_contain_text("상충 1일")
                expect(page.locator("#report-sheet")).to_contain_text("기록 없음 14일")
                page.screenshot(path=str(output/"showcase-conflict.png"),full_page=True)
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    result={"synthetic_only":True,"checks":["two populated and separate conversations","four instructions and eight checkins","75% and six missing days","real classical DB quotations and offsets","three fictional hospital cards","prepared and explicitly synthetic confirmed booking","seven calendar events and ICS","patient claim references","one A4 page with original links","320/390px text contrast and overflow","conflicting record withheld"],"console_errors":errors}
    (ROOT/".runtime"/"showcase-ui-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
