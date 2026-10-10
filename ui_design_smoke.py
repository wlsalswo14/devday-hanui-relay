"""Readability and responsive QA using isolated, explicitly synthetic records."""
import json
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from ui_helpers import open_menu, select_conversation
from playwright.sync_api import sync_playwright, expect
from care import KST
from server import App, Handler, ROOT
from ui_care_smoke import FixtureModel


# Check actual rendered text against its nearest opaque surface, not just tokens.
TEXT_CONTRAST = r"""() => {
  const rgb = value => (value.match(/[\d.]+/g)||[]).map(Number);
  const lum = c => c.slice(0,3).map(v => {v/=255; return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const failures=[];let checked=0;
  for(const el of document.querySelectorAll('body *')) {
    if(![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))continue;
    if(el.closest('[hidden],.sr-only')||!el.getBoundingClientRect().width||!el.getBoundingClientRect().height)continue;
    const style=getComputedStyle(el);if(style.visibility==='hidden')continue;
    let bg=[255,255,255];
    for(let p=el;p;p=p.parentElement){const c=rgb(getComputedStyle(p).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}}
    const fg=rgb(style.color),a=lum(fg),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    const size=parseFloat(style.fontSize),large=size>=24||(size>=18.66&&parseInt(style.fontWeight)>=700);
    checked++;
    if(ratio<(large?3:4.5))failures.push({selector:el.id||el.className||el.tagName,ratio:Math.round(ratio*100)/100});
  }
  return {checked,failures};
}"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    output = ROOT / ".runtime" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with tempfile.TemporaryDirectory() as temporary:
        app = App(Path(temporary), ROOT / "data" / "knowledge.seed.json", FixtureModel())
        server = ThreadingHTTPServer(("127.0.0.1", 0), type("DesignHandler", (Handler,), {"app": app}))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                page = browser.new_page(viewport={"width": 1440, "height": 1024})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                base = f"http://127.0.0.1:{server.server_port}"
                page.goto(base, wait_until="networkidle")
                expect(page.locator("#send")).to_be_enabled()
                page.locator("#message").fill("수면 관련 고문헌 원문 찾아줘")
                page.locator("#message").press("Enter")
                expect(page.locator(".quoted-passage")).to_have_count(1)
                assert not page.locator(".source-preview").first.evaluate("e=>e.open")
                expect(page.locator(".citation-reading")).to_be_hidden()
                page.locator(".source-preview > summary").first.click()
                expect(page.locator(".citation-reading")).to_be_visible()
                page.locator(".source-preview > summary").first.click()
                assert page.locator("#knowledge-count").inner_text() == "1"
                page.locator("#message").fill("합성 테스트 지역 한의원 찾아줘")
                page.locator("#message").press("Enter")
                expect(page.locator(".hospital-card")).to_have_count(1)
                sid = page.locator("#session-select").input_value()
                care = page.request.get(f"{base}/api/sessions/{sid}").json()["care"]
                search = next(s for s in care["searches"] if s["kind"] == "hospitals")
                start = (datetime.now(KST)+timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
                for hour in [9, 10, 11]:
                    event_start=start.replace(hour=hour)
                    response=page.request.post(f"{base}/api/sessions/{sid}/events",data={"title":f"합성 생활 일정 {hour}시", "start":event_start.isoformat(), "end":(event_start+timedelta(minutes=30)).isoformat(),"location":"합성 장소","note":"디자인 검증용"})
                    assert response.ok
                response=page.request.post(f"{base}/api/sessions/{sid}/bookings",data={"search_id":search["id"],"hospital_id":search["data"]["hospitals"][0]["id"],"start":start.isoformat(),"note":"합성 예약 준비"})
                assert response.ok
                page.reload(wait_until="networkidle")
                # Close the secondary panel before sweeping navigation, then verify it separately.
                if page.locator("#context-sidebar").is_visible():page.locator("#close-sidebar").click()
                for width in [320, 360, 390, 768, 1024, 1440]:
                    page.set_viewport_size({"width":width,"height":844 if width<701 else 1024})
                    for view in ["chat", "daily", "library", "calendar"]:
                        open_menu(page)
                        page.locator(f'.app-nav [data-view="{view}"]').click()
                        if view=="library":expect(page.locator(".library-record")).to_have_count(99)
                        if view=="calendar":
                            page.locator(f'[data-day="{start.date().isoformat()}"]').click()
                            expect(page.locator(".calendar-entry")).to_have_count(4)
                            expect(page.locator("#calendar-day-list")).to_contain_text("희망 시간 · 접수 전")
                            if width<701:expect(page.locator(".calendar-cell.selected .calendar-mobile-count")).to_have_text("4건")
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width,view)
                        report=page.evaluate(TEXT_CONTRAST)
                        assert not report["failures"], (width,view,report["failures"])
                        results.append({"width":width,"view":view,"text_checked":report["checked"]})
                        if width in [390,1440]:
                            page.screenshot(path=str(output/f"redesign-{width}-{view}.png"),full_page=view!="library")
                    open_menu(page)
                    page.locator('.app-nav [data-view="chat"]').click()
                    assert page.locator(".bubble").first.evaluate("e=>parseFloat(getComputedStyle(e).fontSize)")>=16
                    assert page.locator(".quoted-passage blockquote").first.evaluate("e=>parseFloat(getComputedStyle(e).fontSize)")>=16
                    open_menu(page)
                    page.locator("#toggle-sidebar").click()
                    expect(page.locator("#context-sidebar")).to_be_visible()
                    report=page.evaluate(TEXT_CONTRAST)
                    assert not report["failures"], (width,"sidebar",report["failures"])
                    page.locator("#close-sidebar").click()
                    if not page.locator(".source-preview").first.evaluate("e=>e.open"):
                        page.locator(".source-preview > summary").first.click()
                    if not page.locator(".quoted-passage .source-original").first.evaluate("e=>e.open"):
                        page.locator(".quoted-passage .source-original > summary").first.click()
                    page.locator(".quoted-passage .citation").first.click()
                    expect(page.locator("#source-reading-section")).to_be_visible()
                    page.locator("#source-dialog .source-original > summary").click()
                    assert page.locator("#source-body").inner_text()
                    report=page.evaluate(TEXT_CONTRAST)
                    assert not report["failures"], (width,"source",report["failures"])
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    if width in [390,1440]:page.screenshot(path=str(output/f"redesign-{width}-source.png"))
                    page.keyboard.press("Escape")
                    expect(page.locator("#source-dialog")).to_be_hidden()
                # Explicit filter for the core classical corpus, with no model calls.
                open_menu(page)
                page.locator('.app-nav [data-view="library"]').click()
                page.locator("#library-category").select_option("classical")
                page.locator("#library-form button").click()
                expect(page.locator(".library-record")).to_have_count(57)
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    report={"screens":results,"checks":["six viewport widths", "rendered text contrast", "16px answers and quotations", "sidebar and source dialog", "classical-only filter", "four events in one day", "mobile count and full agenda", "no horizontal overflow"],"console_errors":errors}
    (ROOT/".runtime"/"design-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
