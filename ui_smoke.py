"""Browser interaction checks against the local preview, using deterministic sample mode."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    output = ROOT / ".runtime" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    problems = []
    with sync_playwright() as playwright:
        launch = {"headless": True}
        if chrome.exists():
            launch["executable_path"] = str(chrome)
        browser = playwright.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1440, "height": 1024})
        session = context.request.post("http://127.0.0.1:8765/api/sessions", data={}).json()
        context.add_init_script("localStorage.setItem('hanui_session', " + json.dumps(session["id"]) + ");")
        page = context.new_page()
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
        page.goto("http://127.0.0.1:8765", wait_until="networkidle")
        page.get_by_text("오늘, 몸과 마음은 어때요?", exact=True).wait_for()
        page.screenshot(path=str(output / "desktop-welcome.png"), full_page=True)
        page.locator("#mode").select_option("demo")
        page.get_by_role("button", name="요즘 5시간 정도 자고 낮에 피곤해", exact=True).click()
        expect(page.locator(".message")).to_have_count(2)
        assert page.locator(".memory-card").count() >= 1
        assert page.locator(".source-card").count() >= 1
        if not page.locator("#context-sidebar").is_visible():page.locator("#toggle-sidebar").click()
        page.locator(".source-card").first.click()
        assert page.locator("#source-dialog").is_visible()
        assert page.locator("#source-link").get_attribute("href").startswith("https://")
        page.locator("#close-source").click()
        page.locator("#message").fill("아까 내가 몇 시간 잔다고 했지?")
        page.locator("#message").press("Enter")
        expect(page.locator(".message")).to_have_count(4)
        assert "5시간" in page.locator(".message.assistant").last.inner_text()
        page.reload(wait_until="networkidle")
        expect(page.locator(".message")).to_have_count(4)
        assert page.locator(".memory-card").count() >= 1
        page.locator("#mode").select_option("demo")
        page.locator("#message").fill("감초 자료를 찾아줘")
        page.locator("#message").press("Enter")
        expect(page.locator(".message")).to_have_count(6)
        assert "감초" in page.locator(".source-card").first.inner_text()
        page.screenshot(path=str(output / "desktop-chat.png"), full_page=True)
        # User content must be rendered as text, not inserted as HTML.
        page.locator("#message").fill('<img src=x onerror="window.hanuiXss=true">')
        page.locator("#message").press("Enter")
        expect(page.locator(".message")).to_have_count(8)
        assert page.locator(".message.user img").count() == 0
        assert not page.evaluate("Boolean(window.hanuiXss)")
        page.set_viewport_size({"width": 390, "height": 844})
        if page.locator("#context-sidebar").is_visible():
            page.locator("#close-sidebar").click()
        page.screenshot(path=str(output / "mobile-chat.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        # Entire session deletion removes both transcript and lifestyle records.
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#reset").click()
        expect(page.locator("#session-select")).not_to_have_value(session["id"])
        assert context.request.get(f'http://127.0.0.1:8765/api/sessions/{session["id"]}').status == 404
        assert not problems, problems
        context.close()
        browser.close()
    report = {"browser": "Chrome headless", "desktop": "1440x1024", "mobile": "390x844",
              "checks": ["chat", "memory", "source dialog", "recall", "reload persistence",
                         "herb retrieval", "text escaping", "mobile overflow", "session deletion"],
              "console_errors": problems}
    (ROOT / ".runtime" / "ui-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
