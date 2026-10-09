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
from server import App, Handler, ROOT, demo_response
from codex_bridge import validate_result


class FixtureModel:
    def available(self):
        return True

    def respond(self, message, history, memories, sources):
        if "고문헌" in message and sources:
            s = next((s for s in sources if s["category"] == "classical"), sources[0])
            return validate_result({"reply": "합성 테스트: 원문을 확인했어요.", "source_ids": [s["id"]],
                "citations": [{"source_id": s["id"], "quote": s["body"][:80]}], "memories": [], "actions": []}, message, sources)
        result = demo_response(message, history, memories, sources)
        result["reply"] = "합성 테스트 응답: " + result["reply"]
        if "한의원" in message or "공식 자료" in message:
            result["actions"] = [{"type": "hospitals" if "한의원" in message else "web",
                "label": "정보 찾기", "query": message, "title": "", "start": "", "note": ""}]
        return result

    def retrieval_keywords(self, message, history):
        return ["수면", "起居", "미병", "未病"] if "고문헌" in message else ["미병"]

    def search_web(self, query, kind):
        return {"query": query, "summary": "자동 테스트용 합성 검색 결과입니다.",
            "provider": "synthetic test fixture — no external search", "searched_at": datetime.now(KST).isoformat(),
            "hospitals": [{"id": "f" * 32, "name": "합성 테스트한의원", "address": "합성 주소",
                "phone": "02-000-0000", "website": "", "booking_url": "https://example.org/booking",
                "source_url": "https://example.org/hospital", "reason": "검색 조건 합성 테스트",
                "reviews": [{"summary": "합성 후기 <img src=x onerror=alert(1)>",
                             "url": "https://example.org/review", "kind": "patient_review"}]}] if kind == "hospitals" else [],
            "results": [{"title": "합성 정보", "summary": "합성 요약", "publisher": "test fixture",
                         "url": "https://example.org/info"}] if kind == "web" else []}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    problems = []
    map_requests = []
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
                page.on("request", lambda r: map_requests.append(r.url) if any(host in r.url for host in
                    ("dapi.kakao.com", "map.kakao.com", "map.naver.com", "/api/maps", "/map.png", "/route")) else None)
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="networkidle")
                page.get_by_text("오늘, 몸과 마음은 어때요?", exact=True).wait_for()
                def unexpected_dialog(dialog):
                    problems.append("Unexpected prompt: " + dialog.message)
                    dialog.dismiss()
                page.on("dialog", unexpected_dialog)
                page.locator("#message").fill("미병이 뭐야?")
                page.locator("#message").press("Enter")
                expect(page.locator(".message")).to_have_count(2)
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
                expect(page.locator("#library-results .library-record")).to_have_count(app.store.knowledge_count())
                page.locator("#library-query").fill("인삼")
                page.locator("#library-form").get_by_role("button", name="검색", exact=True).click()
                expect(page.locator("#library-results .library-record")).to_have_count(len(app.store.library("인삼")))
                page.locator("#library-results .library-record").first.get_by_role("button").click()
                expect(page.locator("#source-dialog")).to_be_visible()
                page.locator("#close-source").click()
                page.get_by_role("button", name="대화", exact=True).click()
                page.locator("#message").fill("합성 지역 한의원 찾아줘")
                page.locator("#message").press("Enter")
                expect(page.locator(".message")).to_have_count(4)
                expect(page.locator(".hospital-card")).to_have_count(1)
                hospital_card = page.locator(".hospital-card")
                expect(hospital_card).to_contain_text("합성 주소")
                expect(hospital_card.locator(".hospital-reason")).to_have_text("검색 조건 합성 테스트")
                assert hospital_card.get_by_role("link", name="전화 02-000-0000").get_attribute("href") == "tel:02-000-0000"
                assert hospital_card.get_by_role("link", name="예약 페이지 ↗").get_attribute("href") == "https://example.org/booking"
                assert hospital_card.locator("details").count() == 1
                assert not hospital_card.locator("details").evaluate("el=>el.open")
                assert page.locator("#visit-map, #route-panel, script[src='/maps.js'], script[src='/routes.js']").count() == 0
                assert page.locator(".review-item img").count() == 0
                page.screenshot(path=str(output / "desktop-hospital-cards.png"), full_page=True)
                page.locator("#close-sidebar").click()
                page.set_viewport_size({"width": 390, "height": 844})
                hospital_card.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=str(output / "mobile-hospital-cards.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1024})
                page.locator("#toggle-sidebar").click()
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
                page.get_by_role("button", name="대화", exact=True).click()
                page.get_by_role("button", name="방문 일정 저장", exact=True).click()
                expect(page.locator("#event-title")).to_have_value("합성 테스트한의원 방문")
                expect(page.locator("#event-location")).to_have_value("합성 주소")
                page.locator("#event-title").fill("합성 별도 방문 일정")
                page.locator("#event-note").fill("개인 방문 메모는 앱에 저장")
                page.get_by_role("button", name="일정 저장", exact=True).click()
                page.get_by_role("button", name="일정·예약", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(2)
                assert page.locator("a[href*='calendar.google.com']").count() == 0
                page.locator("#events-list .record-row").filter(has_text="합성 별도 방문 일정").get_by_role("button", name="캘린더에서 보기").click()
                expect(page.locator("#calendar-day-list")).to_contain_text("합성 별도 방문 일정")
                expect(page.locator("#calendar-grid .calendar-cell")).to_have_count(42)
                with page.expect_download() as download:
                    page.get_by_role("button", name=".ics 내보내기", exact=True).click()
                calendar = Path(download.value.path()).read_text(encoding="utf-8")
                assert calendar.count("BEGIN:VEVENT") == 2
                assert "합성 별도 방문 일정" in calendar
                assert "LOCATION:합성 주소" in calendar
                page.screenshot(path=str(output / "desktop-calendar.png"), full_page=True)
                page.get_by_role("button", name="대화", exact=True).click()
                page.locator("#message").fill("공식 자료 찾아줘")
                page.locator("#message").press("Enter")
                expect(page.locator(".message-actions .web-card")).to_have_count(1)
                page.locator("#message").fill("수면 관련 고문헌 원문 찾아줘")
                page.locator("#message").press("Enter")
                expect(page.locator(".quoted-passage blockquote")).to_have_count(1)
                expect(page.locator(".quote-location")).to_contain_text("본문")
                page.screenshot(path=str(output / "desktop-chat-sources.png"), full_page=True)
                page.remove_listener("dialog", unexpected_dialog)
                page.reload(wait_until="networkidle")
                page.get_by_role("button", name="일정·예약", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(2)
                page.once("dialog", lambda d: d.accept())
                page.get_by_role("button", name="취소 기록", exact=True).click()
                expect(page.locator("#events-list .record-row")).to_have_count(1)
                expect(page.locator("#bookings-list")).to_contain_text("취소 기록")
                page.set_viewport_size({"width": 390, "height": 844})
                for view in ["생활 관리", "한의학 DB", "일정·예약", "대화"]:
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
                # Multiple conversations keep records and unsent drafts separate.
                page.set_viewport_size({"width": 1440, "height": 1024})
                page.get_by_role("button", name="대화", exact=True).click()
                first_id = page.locator("#session-select").input_value()
                page.locator("#message").fill("요즘 5시간 자고 있어")
                page.locator("#message").press("Enter")
                expect(page.locator(".message")).to_have_count(2)
                page.locator("#message").fill("첫 대화의 작성 중 메시지")
                page.get_by_role("button", name="생활 관리", exact=True).click()
                page.locator("#checkin-sleep").fill("6")
                page.get_by_role("button", name="체크인 저장", exact=True).click()
                expect(page.locator("#checkin-history .record-row")).to_have_count(1)
                page.locator("#new-chat").click()
                expect(page.locator(".message")).to_have_count(0)
                assert not map_requests, map_requests
                for path in ("/api/maps/config", f"/api/sessions/{first_id}/places", f"/api/sessions/{first_id}/map.png", "/maps.js", "/routes.js"):
                    assert page.request.get(f"http://127.0.0.1:{server.server_port}"+path).status == 404
                assert page.request.post(f"http://127.0.0.1:{server.server_port}/api/sessions/{first_id}/route",data={}).status == 404
                second_id = page.locator("#session-select").input_value()
                assert first_id != second_id
                expect(page.locator("#message")).to_have_value("")
                page.locator("#rename-chat").click()
                page.locator("#session-title").fill("식사 이야기")
                page.get_by_role("button", name="이름 저장", exact=True).click()
                expect(page.locator("#rename-dialog")).not_to_be_visible()
                page.locator("#message").fill("아침을 거르고 있어요")
                page.locator("#message").press("Enter")
                expect(page.locator(".message")).to_have_count(2)
                page.locator("#message").fill("두 번째 대화의 초안")
                page.locator("#session-select").select_option(first_id)
                expect(page.locator("#message")).to_have_value("첫 대화의 작성 중 메시지")
                expect(page.locator(".message.user")).to_contain_text("5시간")
                expect(page.locator(".memory-card")).to_contain_text("5시간")
                page.get_by_role("button", name="생활 관리", exact=True).click()
                expect(page.locator("#checkin-history .record-row")).to_have_count(1)
                page.locator("#session-select").select_option(second_id)
                expect(page.locator("#message")).to_have_value("두 번째 대화의 초안")
                expect(page.locator("#checkin-history .record-row")).to_have_count(0)
                page.get_by_role("button", name="대화", exact=True).click()
                expect(page.locator(".message.user")).to_contain_text("아침")
                page.reload(wait_until="networkidle")
                expect(page.locator("#session-select")).to_have_value(second_id)
                expect(page.locator("#session-select option:checked")).to_contain_text("식사 이야기")
                page.locator("#toggle-sidebar").click()
                expect(page.locator("#context-sidebar")).to_be_hidden()
                page.reload(wait_until="networkidle")
                expect(page.locator("#context-sidebar")).to_be_hidden()
                page.locator("#toggle-sidebar").click()
                expect(page.locator("#context-sidebar")).to_be_visible()
                page.screenshot(path=str(output / "desktop-conversations.png"), full_page=True)
                page.locator("#close-sidebar").click()
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#toggle-sidebar").click()
                expect(page.locator("#context-sidebar")).to_be_visible()
                page.screenshot(path=str(output / "mobile-sidebar.png"), full_page=True)
                page.keyboard.press("Escape")
                expect(page.locator("#context-sidebar")).to_be_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.once("dialog", lambda d: d.accept())
                page.locator("#reset").click()
                expect(page.locator("#session-select")).to_have_value(first_id)
                expect(page.locator(".message.user")).to_contain_text("5시간")
                page.once("dialog", lambda d: d.accept())
                page.locator("#reset").click()
                expect(page.locator(".message")).to_have_count(0)
                assert not problems, problems
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    report={"checks":["AI chat and searches start without prompts (synthetic fixture)","daily checkin and averages","goal completion","library and source","hospital name/address/reason cards (synthetic fixture)","phone and booking links","collapsed review text escaping","direct visit calendar draft","booking preparation","external user confirmation","own monthly calendar and selected day","ICS download includes visit address","no Google Calendar links","web search UI (synthetic fixture)","reload persistence","booking cancellation","all mobile views","JSON export","full data deletion","multiple conversations and names","independent histories and checkins","unsent draft switching","active conversation restoration","sidebar toggle and preference","mobile sidebar and Escape","delete one conversation preserves another","no map/route assets or network requests","removed map/route endpoints return 404"],"console_errors":problems}
    (ROOT / ".runtime" / "ui-care-check.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
