"""Clinician input, grounded coaching, evidence drilldown and one-page PDF QA.

All messages and instructions here are explicitly synthetic and use an isolated DB.
Real model extraction is checked separately by live_guidance_smoke.py.
"""
import json
import re
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from care import KST
from codex_bridge import validate_result
from server import App, Handler, ROOT
from ui_design_smoke import TEXT_CONTRAST


class GuidanceFixture:
    def __init__(self):self.items=[]
    def available(self):return True
    def respond(self,message,history,memories,sources):
        return validate_result({"reply":"합성 지침 코칭", "source_ids":[], "memories":[], "actions":[], "citations":[], "observations":self.items},message,sources)


def main():
    sys.stdout.reconfigure(encoding="utf-8");errors=[];output=ROOT/".runtime"/"screenshots";output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        model=GuidanceFixture();app=App(Path(temporary),ROOT/"data"/"knowledge.seed.json",model)
        server=ThreadingHTTPServer(("127.0.0.1",0),type("GuidanceUIHandler",(Handler,),{"app":app}))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                page=browser.new_page(viewport={"width":1440,"height":1024})
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.on("console",lambda m:errors.append(m.text) if m.type=="error" else None)
                base=f"http://127.0.0.1:{server.server_port}";page.goto(base,wait_until="networkidle")
                expect(page.locator("#send")).to_be_enabled()
                sid=page.locator("#session-select").input_value()
                page.locator('.app-nav [data-view="daily"]').click()
                page.locator("#new-guidance").click()
                original="취침 23시 전, 찬 음식 줄이기, 커피 1잔 이하, 점심 후 산책 10분"
                page.locator("#guidance-author").fill("합성 담당 한의사")
                page.locator("#guidance-start").fill((datetime.now(KST).date()-timedelta(days=13)).isoformat())
                page.locator("#guidance-text").fill(original)
                page.get_by_role("button",name="지침·개인 목표 저장",exact=True).click()
                expect(page.locator("#guidance-dialog")).to_be_hidden()
                expect(page.locator(".clinician-goal")).to_have_count(4)
                page.locator(".clinician-goal .record-details > summary").first.click()
                page.locator(".clinician-goal").first.get_by_role("button",name="지침 원문",exact=True).click()
                expect(page.locator("#patient-evidence-body")).to_contain_text(original)
                expect(page.locator("#patient-evidence-body mark")).to_have_text("취침 23시 전")
                page.keyboard.press("Escape")
                instructions=app.store.guidance.dashboard(sid)["instructions"]
                diet=next(i for i in instructions if i["category"]=="diet")
                def observation(metric,quote,value,day,instruction=""):
                    return {"metric":metric,"quote":quote,"value":value,"date":day,"instruction_id":instruction}
                for index,ago in enumerate([13,12,11,10,6,5,1,0]):
                    day=(datetime.now(KST).date()-timedelta(days=ago)).isoformat();good=index<6
                    clauses=[f"{day} {'밤 10시' if good else '새벽 1시'}에 잤어",f"{day} 커피 {1 if good else 2}잔 마셨어",f"{day} 점심 후 {15 if good else 5}분 산책했어",f"{day} 찬 음식 {'줄였어' if good else '줄이지 못했어'}",f"{day} {6.5 if good else 5}시간 잤어",f"{day} 아침 먹었어",f"{day} 속이 더부룩했어"]
                    if index==7:clauses[-1]+=' <img src=x onerror="window.hanuiXss=true">'
                    model.items=[observation("bedtime",clauses[0],"22:00" if good else "01:00",day),observation("caffeine_cups",clauses[1],"1" if good else "2",day),observation("walk_after_lunch_minutes",clauses[2],"15" if good else "5",day),observation("adherence",clauses[3],"done" if good else "not_done",day,diet["id"]),observation("sleep_hours",clauses[4],"6.5" if good else "5",day),observation("diet_note",clauses[5],"",day),observation("symptom",clauses[6],"",day)]
                    response=page.request.post(f"{base}/api/sessions/{sid}/chat",data={"message":". ".join(clauses),"mode":"codex"})
                    assert response.ok,json.dumps(response.json(),ensure_ascii=True)+" "+json.dumps(model.items,ensure_ascii=True)
                page.reload(wait_until="networkidle")
                expect(page.locator("#guidance-count")).to_have_text("4")
                expect(page.locator(".message.assistant").last).to_contain_text("지침과 차이")
                if page.locator("#context-sidebar").is_visible():page.locator("#close-sidebar").click()
                page.locator('.app-nav [data-view="report"]').click()
                expect(page.locator(".report-instruction")).to_have_count(4)
                expect(page.locator("#report-sheet")).to_contain_text("75%")
                expect(page.locator("#report-sheet")).to_contain_text("기록 없음 6일")
                expect(page.locator(".report-coverage")).to_contain_text("발언 기록 8일 / 14일")
                report=page.request.get(f"{base}/api/sessions/{sid}/visit-report").json()
                evidence={o["id"]:o for o in report["evidence"]}
                assert all(set(c["evidence_ids"])<=evidence.keys() for c in report["claims"])
                assert all(o["content"][o["offset_start"]:o["offset_end"]]==o["quote"] for o in evidence.values())
                assert not page.evaluate("Boolean(window.hanuiXss)")
                assert page.locator("#report-sheet img").count()==0
                expect(page.locator(".report-instruction").first.locator(".patient-reference")).to_have_text("근거 8")
                page.locator(".report-instruction").first.locator(".patient-reference").click()
                expect(page.locator(".patient-evidence-card")).to_have_count(8)
                page.locator(".patient-evidence-card").first.locator("summary").click()
                expect(page.locator(".patient-evidence-card").first.locator("mark")).to_contain_text("밤 10시")
                page.screenshot(path=str(output/"desktop-patient-evidence.png"))
                href=page.locator(".patient-evidence-card").first.locator("a").get_attribute("href")
                page.locator(".patient-evidence-card").first.locator("a").click()
                expect(page.locator("#patient-evidence-dialog")).to_be_hidden()
                expect(page.locator(".evidence-highlight")).to_have_count(1)
                # PDF evidence links can restore the correct conversation and utterance.
                other=browser.new_page();other.goto(base+href,wait_until="networkidle")
                expect(other.locator("#session-select")).to_have_value(sid)
                expect(other.locator(".evidence-highlight")).to_have_count(1)
                other.close()
                page.locator('.app-nav [data-view="report"]').click()
                expect(page.locator("#print-report")).to_be_enabled()
                page.screenshot(path=str(output/"desktop-visit-report.png"),full_page=True)
                pdf=page.pdf(path=str(ROOT/".runtime"/"visit-report-synthetic.pdf"),prefer_css_page_size=True,print_background=True)
                pages=len(re.findall(rb"/Type\s*/Page\b",pdf))
                assert pages==1, f"Expected one A4 page, got {pages}"
                assert b"/URI" in pdf,"Printed evidence must preserve links"
                page.emulate_media(media="screen")
                for width in [320,390,768,1440]:
                    page.set_viewport_size({"width":width,"height":844 if width<701 else 1024})
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"),width
                    contrast=page.evaluate(TEXT_CONTRAST)
                    assert not contrast["failures"],(width,contrast["failures"])
                    if width==390:page.screenshot(path=str(output/"mobile-visit-report.png"),full_page=True)
                    page.locator('.report-instruction .patient-reference').first.click()
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                    page.keyboard.press("Escape")
                page.reload(wait_until="networkidle")
                page.locator('.app-nav [data-view="report"]').click()
                expect(page.locator("#report-sheet")).to_contain_text("75%")
                # Ending a goal preserves its historical instruction and citations.
                page.locator('.app-nav [data-view="daily"]').click()
                page.once("dialog",lambda d:d.accept())
                page.locator(".clinician-goal .record-details > summary").first.click()
                page.locator(".clinician-goal").first.get_by_role("button",name="지침 종료",exact=True).click()
                expect(page.locator(".clinician-goal")).to_have_count(3)
                page.locator('.app-nav [data-view="report"]').click()
                expect(page.locator(".report-instruction")).to_have_count(4)
                # New conversation has no clinician instructions or patient evidence.
                page.locator("#new-chat").click()
                page.locator('.app-nav [data-view="report"]').click()
                expect(page.locator(".report-instruction")).to_have_count(0)
                expect(page.locator(".report-coverage")).to_contain_text("기록 없음 14일")
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    result={"synthetic_only":True,"pdf_pages":1,"checks":["clinician text creates four personal goals", "original instruction offsets", "eight recorded days/six missing days", "75% from six of eight assessed days", "per-sentence patient references", "exact quote and date drilldown", "original conversation jump", "PDF evidence deep links", "one A4 page", "mobile overflow and text contrast", "HTML text escaping", "reload", "ended instruction retained", "conversation separation"],"console_errors":errors}
    (ROOT/".runtime"/"guidance-ui-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
