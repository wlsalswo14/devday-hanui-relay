"""Check automatic reminders using isolated synthetic calendar data."""
import tempfile
import threading
from pathlib import Path
from datetime import datetime,timedelta
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
from server import App,Handler
from care import KST
from ui_care_smoke import FixtureModel


class Model(FixtureModel):
    def generate_reminder(self,event):return '다가오는 산책을 기억해 주세요.'


with tempfile.TemporaryDirectory() as d:
    app=App(Path(d),model=Model());sid=app.store.create_session()['id'];now=datetime.now(KST)
    app.care.event(sid,{'title':'저녁 산책','start':(now+timedelta(minutes=10)).isoformat(),
        'end':(now+timedelta(minutes=40)).isoformat(),'location':'공원','note':''})
    server=ThreadingHTTPServer(('127.0.0.1',0),type('ReminderHandler',(Handler,),{'app':app}))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/?session={sid}')
            expect(page.locator('.app-nav [data-view="calendar"]')).to_have_text('캘린더')
            expect(page.locator('.reminder-card')).to_be_visible(timeout=10000)
            expect(page.locator('.reminder-card')).to_contain_text('저녁 산책')
            page.get_by_role('button',name='캘린더 보기 ↗').click()
            expect(page.locator('#calendar-title')).to_have_text('캘린더')
            expect(page.locator('#calendar-view')).to_be_visible()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_role('button',name='저녁 산책 알림 닫기').click()
            expect(page.locator('#calendar-reminders')).to_be_hidden()
            page.reload();page.wait_for_timeout(2000)
            expect(page.locator('#calendar-reminders')).to_be_hidden()
            assert not errors,errors
            browser.close()
    finally:server.shutdown();server.server_close()
print('PASS: automatic reminder, calendar link, mobile layout, persistent dismissal, no console errors')
