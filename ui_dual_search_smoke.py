"""Check both-engine and partial-failure source display with isolated fixture data."""
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from server import App, Handler, ROOT
from ui_care_smoke import FixtureModel


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = App(Path(directory), model=FixtureModel())
        ids = []
        for blocked in (False, True):
            sid = app.store.create_session()['id']
            ids.append(sid)
            statuses = [{'provider':'네이버','status':'ok','count':4},
                        {'provider':'구글','status':'blocked' if blocked else 'ok','count':4}]
            engines = ['네이버'] if blocked else ['네이버','구글']
            rows = [{'title':f'공식 자료 {i}', 'summary':'검색 결과의 요약', 'url':f'https://example.org/{i}',
                     'publisher':'example.org', 'search_engines':engines} for i in range(4)]
            action = {'type':'web','completed':True,'label':'웹검색','result':
                      {'results':rows,'hospitals':[],'provider_status':statuses}}
            app.store.save_turn(sid,'공식 자료 검색해줘.','검색 결과를 확인했어요.',[],[],'codex',[action])
        server = ThreadingHTTPServer(('127.0.0.1',0),type('DualSearchHandler',(Handler,),{'app':app}))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
                for index, sid in enumerate(ids):
                    page.evaluate('async id=>useSession(await api(`/api/sessions/${id}`))',sid)
                    expect(page.locator('.lookup-heading')).to_contain_text('네이버 · 4건')
                    expect(page.locator('.lookup-heading')).to_contain_text('구글 · 검색 제한' if index else '구글 · 4건')
                    expect(page.locator('.web-card').first).to_contain_text('네이버 · example.org' if index else '네이버 · 구글 · example.org')
                    expect(page.locator('.web-card').last).to_be_hidden()
                    page.get_by_text('다른 출처 1개',exact=True).click()
                    expect(page.locator('.web-card').last).to_be_visible()
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.set_viewport_size({'width':1440,'height':1000})
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('PASS: dual-engine attribution, Google blocked with Naver retained, expanded sources, mobile layout')


if __name__=='__main__':
    main()
