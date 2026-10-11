"""Exercise Prism with isolated conversations, evidence, calendar and long text."""
import json
import tempfile
import threading
from datetime import datetime,timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from care import KST
from server import App,Handler,ROOT
from ui_care_smoke import FixtureModel
from ui_design_smoke import TEXT_CONTRAST
from ui_helpers import open_menu


def main():
    errors=[];checks=[]
    shots=ROOT/'.runtime/screenshots/prism';shots.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        app=App(Path(directory),ROOT/'data/knowledge.seed.json',FixtureModel())
        server=ThreadingHTTPServer(('127.0.0.1',0),type('PrismHandler',(Handler,),{'app':app}))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
                base=f'http://127.0.0.1:{server.server_port}'
                page.goto(base,wait_until='networkidle')
                expect(page.locator('#send')).to_be_enabled()
                expect(page.locator('.welcome-title')).to_have_text('오늘은 어때요?')
                page.screenshot(path=str(shots/'welcome-desktop.png'))
                page.locator('#message').fill('수면 관련 고문헌 원문 찾아줘')
                page.locator('#send').click()
                expect(page.locator('.quoted-passage')).to_have_count(1)
                page.locator('.source-preview > summary').click()
                expect(page.locator('.citation-reading')).to_be_visible()
                page.locator('.source-original > summary').first.click()
                expect(page.locator('.quoted-passage blockquote')).to_be_visible()
                page.locator('.quoted-passage .citation').click()
                expect(page.locator('#source-dialog')).to_be_visible()
                assert not page.evaluate(TEXT_CONTRAST)['failures']
                page.screenshot(path=str(shots/'source-dialog-desktop.png'))
                page.locator('#close-source').click()
                sid=page.locator('#session-select').input_value()
                start=datetime.now(KST).replace(hour=15,minute=0,second=0,microsecond=0)
                response=page.request.post(f'{base}/api/sessions/{sid}/events',data={
                    'title':'검증용 방문 일정','start':start.isoformat(),
                    'end':(start+timedelta(minutes=30)).isoformat(),'note':'합성 UI 검증','location':''})
                assert response.ok
                long='긴 답변의 가독성과 스크롤을 확인하는 합성 문장입니다. '*80
                app.store.save_turn(sid,'합성 장문 검증',long,[],[],'codex')
                page.reload(wait_until='networkidle')
                for width in (320,360,390,768,1024,1440):
                    height=844 if width<=700 else 1000
                    page.set_viewport_size({'width':width,'height':height})
                    for view in ('chat','calendar','report'):
                        open_menu(page)
                        page.locator(f'.app-nav [data-view="{view}"]').click()
                        if view=='calendar':
                            page.locator(f'[data-day="{start.date().isoformat()}"]').click()
                            expect(page.locator('#calendar-day-list')).to_contain_text('검증용 방문 일정')
                        if view=='report':
                            page.locator('#report-document-title').fill('검증용 리포트')
                            page.locator('#report-document-body').fill('생활 기록과 질문을 자유롭게 적는 합성 문서입니다.')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,view)
                        contrast=page.evaluate(TEXT_CONTRAST)
                        assert not contrast['failures'],(width,view,contrast['failures'])
                        if view=='chat':
                            composer=page.locator('#chat-form').bounding_box()
                            assert composer['y']+composer['height']<=height,(width,composer)
                            assert page.locator('#messages').bounding_box()['height']>200
                            assert page.locator('#messages').evaluate('e=>e.scrollHeight>e.clientHeight')
                            assert page.locator('.message.assistant .bubble').last.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')>=16
                            if width>700:
                                page.locator('#nav-toggle').click()
                                expect(page.locator('.app-nav')).to_be_visible()
                        if width in (390,1440):page.screenshot(path=str(shots/f'{view}-{width}.png'))
                        checks.append({'width':width,'view':view,'text_checked':contrast['checked']})
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown();server.server_close()
    report={'screens':checks,'source_original_and_reading':True,'scrollable_long_reply':True,'console_errors':errors}
    (ROOT/'.runtime/prism-ui-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
