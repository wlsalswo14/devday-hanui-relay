"""Verify editable agent drafts without changing real user records."""
import tempfile
import threading
import re
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
from server import App,Handler
from ui_care_smoke import FixtureModel


class Model(FixtureModel):
    def draft_report(self,data):
        source=next(s for s in data['sources'] if s['id']=='current-draft')
        return {'title':'정리한 생활 리포트','sections':[{'heading':'생활 기록','statements':[{
            'text':'산책을 기록했습니다.','evidence':[{'source_id':source['id'],'quote':source['text'][:120]}]}]}]}


with tempfile.TemporaryDirectory() as d:
    app=App(Path(d),model=Model());server=ThreadingHTTPServer(('127.0.0.1',0),type('DraftHandler',(Handler,),{'app':app}))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle');page.locator('[data-view="report"]').click()
            editor=page.locator('#report-document-body');expect(editor).to_be_enabled();editor.fill('오늘 점심 후에 가볍게 산책했습니다.')
            page.locator('#save-report').click();expect(page.locator('#report-state')).to_have_text('저장됨')
            page.locator('#draft-report').click();page.locator('#report-draft-instruction').fill('의사 선생님께 전달할 리포트로 정리')
            page.locator('#generate-report-draft').click();expect(page.locator('#report-draft-preview')).to_be_visible()
            expect(editor).to_have_value('오늘 점심 후에 가볍게 산책했습니다.')
            expect(page.locator('#report-draft-body')).to_contain_text('근거')
            page.locator('#report-draft-dialog .close-dialog').click();expect(editor).to_have_value('오늘 점심 후에 가볍게 산책했습니다.')
            page.locator('#draft-report').click();page.locator('#generate-report-draft').click();expect(page.locator('#report-draft-preview')).to_be_visible()
            page.locator('#apply-report-draft').click()
            assert '근거' in editor.input_value();expect(page.locator('#report-state')).to_have_text('미저장')
            editor.fill(editor.input_value()+'\n\n내가 추가로 작성한 질문')
            page.locator('#save-report').click();expect(page.locator('#report-state')).to_have_text('저장됨')
            page.reload(wait_until='networkidle');page.locator('[data-view="report"]').click()
            expect(editor).to_have_value(re.compile('.*내가 추가로 작성한 질문',re.S))
            page.set_viewport_size({'width':320,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors,errors;browser.close()
    finally:server.shutdown();server.server_close()
print('PASS: agent preview, original preserved, apply, manual edit, save/reload, mobile layout')
