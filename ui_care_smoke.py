"""End-to-end care UI against isolated SQLite and synthetic search fixtures.

No real booking, no user's browser profile, no model usage. Live search is checked separately.
"""
import json
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from care import KST
from server import App, Handler, ROOT


class FixtureModel:
    def available(self):
        return True

    def search_web(self, query, kind):
        return {"query": query, "summary": "자동 테스트용 합성 검색 결과입니다.",
            "provider": "synthetic test fixture — no external search", "searched_at": datetime.now(KST).isoformat(),
            "hospitals": [{"id": "f" * 32, "name": "합성 테스트한의원", "address": "합성 주소",
                "phone": "", "website": "", "booking_url": "https://example.org/booking",
                "source_url": "https://example.org/hospital", "reason": "검색 조건 합성 테스트",
                "reviews": [{"summary": "합성 후기 <img src=x onerror=alert(1)>",
                             "url": "https://example.org/review", "kind": "patient_review"}]}] if kind == "hospitals" else [],
            "results": [{"title": "합성 정보", "summary": "합성 요약", "publisher": "test fixture",
                         "url": "https://example.org/info"}] if kind == "web" else []}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    problems = []
    output = ROOT / ".runtime" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        app = App(Path(temporary), ROOT / "data" / "knowledge.seed.json", FixtureModel())
        handler = type("FixtureHandler", (Handler,), {"app": app})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                page = browser.new_page(viewport={"width": 1440, "height": 1024})
                page.on("pageerror", lambda error: problems.append(str(error)))
                page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="networkidle")
                page.get_by_text("오늘, 몸과 마음은 어때요?", exact=True).wait_for()
                page.get_by_role("button", name="생활 관리", exact=True).click()
                page.locator("#checkin-sleep").fill("6.5")
                page.locator("#checkin-stress").fill("4")
                page.locator("#checkin-energy").fill("6")
                page.locator("#checkin-note").fill("합성 기록: 점심 후 산책")
                page.get_by_role("button", name="체크인 저장", exact=True).click()
                expect(page.locator("#checkin-history .record-row")).to_have_count(1)
                expect(page.locator("#daily-summary")).to_contain_text("6.5")
                page.locator("#goal-title").fill("합성 목표: 10분 산책")
                page.get_by_role("button", name="목표 추가", exact=True).click()
                expect(page.locator("#goals-list .goal-row")).to_have_count(1)
                page.locator("#goals-list input").check()
                expect(page.locator("#goals-list")).to_contain_text("누적 1일 실천")
                page.screenshot(path=str(output / "desktop-daily.png"), full_page=True)
                page.get_by_role("button", name="한의학 DB", exact=True).click()
                expect(page.locator("#library-results .library-record")).to_have_count(42)
                page.locator("#library-query").fill("인삼")
                page.locator("#library-form").get_by_role("button", name="검색", exact=True).click()
                expect(page.locator("#library-results .library-record")).to_have_count(2)
                page.locator("#library-results .library-record").first.get_by_role("button").click()
                expect(page.locator("#source-dialog")).to_be_visible()
                page.locator("#close-source").click()
                page.get_by_role("button", name="병원 찾기", exact=True).click()
                page.locator("#hospital-query").fill("합성 지역 한의원")
                page.once("dialog", lambda d: d.accept())
                page.get_by_role("button", name="병원 검색", exact=True).click()
                expect(page.locator(".hospital-card")).to_have_count(1)
                assert page.locator(".review-item img").count() == 0
                page.get_by_role("button", name="예약 준비", exact=True).click()
                page.locator("#booking-note").fill("합성 방문 메모")
                page.get_by_role("button", name="예약 준비 저장", exact=True).click()
                expect(page.locator("#bookings-list .record-row")).to_have_count(1)
                expect(page.locator("#events-list .record-row")).to_have_count(0)
                page.get_by_role("button", name="병원에서 확정받았어요", exact=True).click()
                page.locator("#booking-confirmation").fill("합성 확인: 병원에서 시간 확정")
                page.locator("#booking-confirmed").check()
                page.get_by_role("button", name="확정 기록·일정 생성", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(1)
                expect(page.locator("#bookings-list")).to_contain_text("예약 확정")
                page.get_by_role("button", name="일정 추가", exact=True).click()
                page.locator("#event-title").fill("합성 산책 일정")
                page.locator("#event-note").fill("개인 메모는 Google 링크에서 제외")
                page.get_by_role("button", name="일정 저장", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(2)
                g = page.locator("#events-list .record-row").filter(has_text="합성 산책 일정").get_by_role("link", name="Google Calendar에 추가 ↗")
                assert "개인" not in g.get_attribute("href")
                with page.expect_download() as download:
                    page.get_by_role("button", name=".ics 내보내기", exact=True).click()
                calendar = Path(download.value.path()).read_text(encoding="utf-8")
                assert calendar.count("BEGIN:VEVENT") == 2
                assert "합성 산책 일정" in calendar
                page.screenshot(path=str(output / "desktop-calendar.png"), full_page=True)
                page.get_by_role("button", name="웹 검색", exact=True).click()
                page.locator("#web-query").fill("합성 웹 검색")
                page.locator("#web-form").get_by_role("button", name="웹 검색", exact=True).click()
                expect(page.locator("#web-results .web-card")).to_have_count(1)
                page.reload(wait_until="networkidle")
                page.get_by_role("button", name="일정·예약", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(2)
                page.once("dialog", lambda d: d.accept())
                page.get_by_role("button", name="취소 기록", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(1)
                expect(page.locator("#bookings-list")).to_contain_text("취소 기록")
                page.set_viewport_size({"width": 390, "height": 844})
                for view in ["생활 관리", "한의학 DB", "병원 찾기", "일정·예약", "웹 검색"]:
                    page.locator(".app-nav").get_by_role("button", name=view, exact=True).click()
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), view
                page.get_by_role("button", name="생활 관리", exact=True).click()
                page.screenshot(path=str(output / "mobile-daily.png"), full_page=True)
                with page.expect_download() as export:
                    page.get_by_role("button", name="내 기록 내보내기", exact=True).click()
                data = json.loads(Path(export.value.path()).read_text(encoding="utf-8"))
                assert data["care"]["checkins"][0]["sleep"] == 6.5
                page.once("dialog", lambda d: d.accept())
                page.locator("#reset").click()
                expect(page.locator("#checkin-history .record-row")).to_have_count(0)
                expect(page.locator("#events-list .record-row")).to_have_count(0)
                expect(page.locator("#bookings-list .record-row")).to_have_count(0)
                assert not problems, problems
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    report={"checks":["daily checkin and averages","goal completion","library and source","hospital search UI (synthetic fixture)","review text escaping","booking preparation","external user confirmation","calendar creation","ICS download","Google link excludes private notes","web search UI (synthetic fixture)","reload persistence","booking cancellation","all mobile views","JSON export","full data deletion"],"console_errors":problems}
    (ROOT / ".runtime" / "ui-care-check.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
