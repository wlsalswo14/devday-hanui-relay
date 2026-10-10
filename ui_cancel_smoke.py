"""Background continuity and cancellation with isolated HTTP workers, no external AI."""
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
    errors=[];checks=[];continued=[]
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
                for action in ["view","hidden","background","new-chat","switch","stop","delete","reload","close"]:
                    primary=app.store.create_session()["id"]
                    provider.release.clear()
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
                    elif action=="new-chat":
                        expect(page.locator("#new-chat")).to_be_disabled()
                        page.evaluate("document.getElementById('new-chat').click()")
                    elif action=="switch":
                        expect(page.locator(f'.session-item[data-session-id="{other}"]')).to_be_disabled()
                        page.evaluate("selectSession("+json.dumps(other)+")")
                    elif action=="hidden":page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
                    elif action=="background":
                        background=context.new_page();background.goto("about:blank");background.bring_to_front()
                        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
                    elif action=="delete":
                        page.once("dialog",lambda dialog:dialog.accept())
                        row=page.locator(f'.session-delete[data-session-id="{primary}"]')
                        row.locator("..").hover();row.click()
                    elif action=="reload":page.reload(wait_until="networkidle")
                    else:page.close()
                    if action in ["view","hidden","background","new-chat","switch"]:
                        page.wait_for_timeout(200)
                        assert app.lock.locked(),action+" cancelled the in-flight request"
                        provider.release.set()
                        if action=="background":background.close();page.bring_to_front()
                        if action in ["hidden","background"]:page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
                        if action=="view":page.locator('[data-view="chat"]').click()
                        expect(page.locator(".message.assistant").last).to_contain_text("Fixture",timeout=10000)
                        expect(page.locator("#send")).to_be_enabled()
                        assert len(app.store.get_session(primary)["messages"])==before+2,action
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".message.assistant").last).to_contain_text("Fixture")
                        page.close();continued.append(action);continue
                    deadline=time.monotonic()+1.5
                    while app.lock.locked() and time.monotonic()<deadline:time.sleep(.02)
                    assert not app.lock.locked(),action
                    if action=="delete":
                        expect(page.locator(f'.session-item[data-session-id="{primary}"]')).to_have_count(0)
                        assert all(s["id"]!=primary for s in app.store.list_sessions())
                    else:assert len(app.store.get_session(primary)["messages"])==before,action
                    if action!="close":
                        expect(page.locator("#send")).to_be_enabled()
                        assert not page.locator("#error").is_visible(),action
                        page.close()
                    checks.append(action)
                    provider.release.set();time.sleep(.05)
                primary=app.store.create_session()["id"]
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
    print(json.dumps({"continuity_checks":continued,"cancel_checks":checks,"next_request":"passed","cancelled_turns_saved":0,"console_errors":errors},indent=2))


if __name__=="__main__":main()
