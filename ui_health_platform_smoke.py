"""Exercise profile, care start, evidence, report import and mobile without real patient data."""
import json
import re
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
from server import App,Handler,ROOT
from google_bridge import GemmaChat
from ui_helpers import open_menu


class FixtureGemma(GemmaChat):
    def execute(self,system,payload,schema,web=False):
        if 'question' in schema.get('properties',{}):return {'question':'오늘 식사 후 불편함이 있었나요?'},{}
        if 'task' in schema.get('properties',{}):
            memory=payload.get('HEALTH_PROFILE_MEMORY',[])
            reply='프로필에는 테스트 약 A를 복용한다고 적혀 있어요.' if memory else '안녕하세요!'
            return {'reply':reply,'task':'none','instruction':''},{}
        raise AssertionError('Unexpected model task')


with tempfile.TemporaryDirectory() as directory:
    app=App(Path(directory),model=FixtureGemma(Path(directory),key='fixture'))
    server=ThreadingHTTPServer(('127.0.0.1',0),type('PlatformHandler',(Handler,),{'app':app}))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':900});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('response',lambda response:print('UI HTTP',response.status,response.url.split('/')[-1]) if response.status>=400 else None)
            page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            open_menu(page);page.locator('#system-instructions-open').click()
            page.locator('#health-profile-text').fill('복용약: 테스트 약 A\n취침: 23시')
            page.locator('#system-instructions-save').click();expect(page.locator('#system-instructions-status')).to_have_text('저장했어요.')
            page.locator('#system-instructions-dialog .close-dialog').click()
            page.locator('#new-chat').click();expect(page.locator('.session-item')).to_have_count(2);expect(page.locator('#send')).to_be_enabled();page.locator('#message').fill('내 복용약 뭐야?');page.locator('#send').click()
            try:expect(page.locator('.message.assistant .bubble').last).to_contain_text('테스트 약 A')
            except AssertionError:
                print('UI diagnostics',errors,page.locator('#error').text_content())
                raise
            page.locator('#care-home-toggle').click()
            for name,value in [('concern','식사 후 불편함'),('duration','일주일'),('goal','식사 후 상태 확인')]:page.locator(f'.care-start-form [name="{name}"]').fill(value)
            page.locator('.care-start-form button[type="submit"]').click()
            expect(page.locator('#care-home-toggle')).to_have_text('오늘의 관리')
            expect(page.locator('.message.assistant .bubble').last).to_have_text('오늘 식사 후 불편함이 있었나요?')
            page.locator('.care-question').get_by_role('button',name='아니요',exact=True).click()
            expect(page.locator('.care-today .care-metrics')).to_contain_text('목표 자기보고 0%')
            page.locator('#care-week-open').click();expect(page.locator('#care-week-body')).to_contain_text('기록 없음 6일')
            page.locator('#care-week-report').click();expect(page.locator('#report-document-body')).to_have_value(re.compile('실천하지 못했어요'))
            page.locator('#save-report').click();expect(page.locator('#report-state')).to_have_text('저장됨')
            page.locator('[data-view="chat"]').click();page.reload(wait_until='networkidle')
            page.locator('#care-week-open').click();expect(page.locator('#care-week-body')).to_contain_text('목표 자기보고 0%')
            page.locator('#care-week-dialog .close-dialog').click()
            shots=ROOT/'.runtime/screenshots';shots.mkdir(parents=True,exist_ok=True)
            for width,height in [(1440,900),(390,844),(320,700)]:
                page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                assert page.locator('#messages').bounding_box()['height']>200,width
                page.locator('#care-home-toggle').click()
                assert page.locator('#messages').bounding_box()['height']>200,width
                page.screenshot(path=str(shots/f'health-platform-{width}.png'))
            assert not errors,errors
            browser.close()
        print(json.dumps({'profile_across_chats':True,'negative_answer_persisted':True,'missing_days':6,'report_import':True,'responsive':[1440,390,320]}))
    finally:
        server.shutdown();server.server_close()
