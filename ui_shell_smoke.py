"""Verify the sidebar shell, real conversation switching, and mobile accessibility."""
import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from server import App, Handler, ROOT
from ui_care_smoke import FixtureModel
from ui_helpers import open_menu, select_conversation
from ui_design_smoke import TEXT_CONTRAST


def main():
    errors=[]
    with tempfile.TemporaryDirectory() as temporary:
        app=App(Path(temporary), ROOT/'data/knowledge.seed.json', FixtureModel())
        server=ThreadingHTTPServer(('127.0.0.1',0),type('ShellHandler',(Handler,),{'app':app}))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
                page=browser.new_page(viewport={'width':1440,'height':1024})
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
                page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
                expect(page.locator('#send')).to_be_enabled()
                for selector in ['.app-nav','#new-chat','#session-list','#context-sidebar','#chat-menu']:
                    assert page.locator(selector).evaluate("e=>!!e.closest('#app-sidebar')"),selector
                assert page.locator('.conversation-bar').count()==0
                assert page.locator('#app-sidebar').bounding_box()['width']==260
                initial=page.locator('#messages').bounding_box()['width']
                page.locator('#nav-toggle').click()
                expect(page.locator('.app-nav')).to_be_hidden()
                assert page.locator('#app-sidebar').bounding_box()['width']==68
                assert page.locator('#messages').bounding_box()['width']>=initial
                page.reload(wait_until='networkidle')
                expect(page.locator('.app-nav')).to_be_hidden()
                page.locator('#nav-toggle').click()
                first=page.locator('#session-select').input_value()
                page.locator('#new-chat').click()
                expect(page.locator('.session-item')).to_have_count(2)
                second=page.locator('#session-select').input_value()
                assert first!=second
                select_conversation(page,first)
                expect(page.locator(f'.session-item[data-session-id="{first}"]')).to_have_attribute('aria-current','true')
                for width in [320,390]:
                    page.set_viewport_size({'width':width,'height':844})
                    expect(page.locator('#app-sidebar')).to_be_hidden()
                    assert page.locator('#app-sidebar').evaluate('e=>e.inert')
                    composer=page.locator('#chat-form').bounding_box()
                    assert composer['y']+composer['height']<=844
                    open_menu(page)
                    expect(page.locator('#nav-backdrop')).to_be_visible()
                    assert not page.locator('#app-sidebar').evaluate('e=>e.inert')
                    expect(page.locator('#nav-toggle')).to_be_focused()
                    page.keyboard.press('Shift+Tab')
                    expect(page.locator('#chat-menu > summary')).to_be_focused()
                    page.keyboard.press('Tab')
                    expect(page.locator('#nav-toggle')).to_be_focused()
                    assert not page.evaluate(TEXT_CONTRAST)['failures']
                    page.locator('#chat-menu > summary').click()
                    settings=page.locator('.chat-menu-items').bounding_box()
                    assert settings['y']>=0 and settings['x']+settings['width']<=width
                    page.keyboard.press('Escape')
                    expect(page.locator('#app-sidebar')).to_be_hidden()
                    expect(page.locator('#mobile-nav-toggle')).to_be_focused()
                    for view in ['daily','library','calendar','report','chat']:
                        open_menu(page)
                        page.locator(f'.app-nav [data-view="{view}"]').click()
                        expect(page.locator('#app-sidebar')).to_be_hidden()
                        if view!='chat':expect(page.locator(f'#{view}-view')).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    open_menu(page)
                    page.locator('#nav-backdrop').click(position={'x':width-10,'y':400})
                    expect(page.locator('#app-sidebar')).to_be_hidden()
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    print(json.dumps({'checks':['left-sidebar contains all tools','desktop collapse/reload','recent conversation switching','mobile inert closed drawer','Escape focus restoration','all mobile views','upward settings menu','backdrop close','composer in viewport'],'console_errors':errors}))


if __name__=='__main__':main()
