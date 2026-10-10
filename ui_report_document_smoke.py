"""Verify the replacement free-form report editor on isolated synthetic data."""
import tempfile
import threading
import re
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
from server import App,Handler,ROOT
from ui_care_smoke import FixtureModel
from ui_helpers import open_menu,select_conversation

with tempfile.TemporaryDirectory() as d:
    app=App(Path(d),model=FixtureModel())
    server=ThreadingHTTPServer(('127.0.0.1',0),type('DocumentHandler',(Handler,),{'app':app}))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            page.locator('[data-view="report"]').click()
            title=page.locator('#report-document-title');body=page.locator('#report-document-body')
            expect(body).to_be_enabled();expect(body).to_have_value('')
            assert page.locator('.adherence-table,.report-rate,#report-end').count()==0
            first=page.locator('#session-select').input_value()
            title.fill('내원 전에 전달할 내용');body.fill('어제는 푹 잤습니다.\n\n의사 선생님께 물어볼 것\n<script>literal</script>')
            expect(page.locator('#report-state')).to_have_text('미저장')
            page.locator('#save-report').click();expect(page.locator('#report-state')).to_have_text('저장됨')
            page.reload(wait_until='networkidle');page.locator('[data-view="report"]').click()
            expect(body).to_have_value('어제는 푹 잤습니다.\n\n의사 선생님께 물어볼 것\n<script>literal</script>')
            pdf=page.pdf(prefer_css_page_size=True)
            assert len(re.findall(rb'/Type\s*/Page\b',pdf))==1
            assert page.locator('#report-print-body script').count()==0
            page.locator('#new-chat').click();expect(page.locator('.session-item')).to_have_count(2)
            page.locator('[data-view="report"]').click()
            expect(body).to_have_value('');expect(body).to_be_enabled()
            body.fill('두 번째 대화 초안')
            select_conversation(page,first);page.locator('[data-view="report"]').click();expect(body).to_have_value('어제는 푹 잤습니다.\n\n의사 선생님께 물어볼 것\n<script>literal</script>')
            for width in [320,390]:
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                expect(body).to_be_visible()
            output=ROOT/'.runtime/screenshots';output.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(output/'free-report-mobile.png'))
            assert not errors,errors
            browser.close()
    finally:server.shutdown();server.server_close()
print('PASS: blank editor, save/reload, conversation isolation, HTML literal text, PDF, mobile layout')
