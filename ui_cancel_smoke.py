"""Browser cancellation against real isolated HTTP workers, no external AI usage."""
import json
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from ui_helpers import open_menu, select_conversation
from playwright.sync_api import sync_playwright, expect
from server import App, Handler
from tests.test_cancellation import SlowModel, SlowProvider


def main():
    errors=[];checks=[]
    with tempfile.TemporaryDirectory() as temporary:
        provider=ThreadingHTTPServer(("127.0.0.1",0), SlowProvider)
        provider.started=threading.Event();provider.release=threading.Event()
        threading.Thread(target=provider.serve_forever,daemon=True).start()
        app=App(Path(temporary),model=SlowModel(f"http://127.0.0.1:{provider.server_port}/"))
        other=app.store.create_session()["id"]
        primary=app.store.create_session()["id"]
        server=ThreadingHTTPServer(("127.0.0.1",0),type("CancelUIHandler",(Handler,),{"app":app}))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f"http://127.0.0.1:{server.server_port}"
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                context=browser.new_context()
                for action in ["stop","view","new-chat","switch","hidden","reload","close"]:
                    page=context.new_page()
                    page.on("pageerror",lambda error:errors.append(str(error)))
                    page.goto(base+"/?session="+primary,wait_until="networkidle")
                    expect(page.locator("#send")).to_be_enabled()
                    before=len(app.store.get_session(primary)["messages"])
                    provider.started.clear()
                    page.locator("#message").fill("slow")
                    page.locator("#message").press("Enter")
                    expect(page.locator("#stop-response")).to_be_visible()
                    assert provider.started.wait(3),action
                    if action=="stop":page.locator("#stop-response").click()
                    elif action=="view":page.locator('[data-view="daily"]').click()
                    elif action=="new-chat":page.locator("#new-chat").click()
                    elif action=="switch":select_conversation(page,other)
                    elif action=="hidden":page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
                    elif action=="reload":page.reload(wait_until="networkidle")
                    else:page.close()
                    deadline=time.monotonic()+1.5
                    while app.lock.locked() and time.monotonic()<deadline:time.sleep(.02)
                    assert not app.lock.locked(),action
                    assert len(app.store.get_session(primary)["messages"])==before,action
                    if action!="close":
                        expect(page.locator("#send")).to_be_enabled()
                        assert not page.locator("#error").is_visible(),action
                        page.close()
                    checks.append(action)
                page=context.new_page()
                page.goto(base+"/?session="+primary,wait_until="networkidle")
                page.locator("#message").fill("fast");page.locator("#message").press("Enter")
                expect(page.locator(".message.assistant")).to_contain_text("Fixture")
                expect(page.locator("#send")).to_be_enabled()
                assert len(app.store.get_session(primary)["messages"])==2
                assert not errors,errors
                browser.close()
        finally:
            provider.release.set()
            server.shutdown();server.server_close();provider.shutdown();provider.server_close()
    print(json.dumps({"cancel_checks":checks,"next_request":"passed","cancelled_turns_saved":0,"console_errors":errors},indent=2))


if __name__=="__main__":main()
