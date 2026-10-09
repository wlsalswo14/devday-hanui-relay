"use strict";
const guidanceState={sessionId:null,report:null,request:0};
const observationLabels={bedtime:"취침 시각",sleep_hours:"수면 시간",caffeine_cups:"커피",walk_after_lunch_minutes:"점심 후 산책",activity_minutes:"활동",diet_note:"식사",symptom:"불편감",adherence:"지침 실천 보고"};
const adherenceLabels={met:"준수",unmet:"미준수",unknown:"기록 없음",unassessed:"미판정",conflict:"상충 기록",inactive:"지침 기간 밖"};
function evidenceHref(record){return `/?session=${encodeURIComponent(state.session.id)}&message=${encodeURIComponent(record.message_id)}`;}
function observationValue(o){if(o.metric==="bedtime")return `${String(Math.floor(o.value/60)).padStart(2,"0")}:${String(o.value%60).padStart(2,"0")}`;if(o.metric==="sleep_hours")return `${o.value}시간`;if(o.metric==="caffeine_cups")return `${o.value}잔`;if(o.metric.endsWith("minutes"))return `${o.value}분`;if(o.metric==="adherence")return o.value==="done"?"실천했다고 보고":"실천하지 못했다고 보고";return "환자 발언";}
function openPatientEvidence(records,absence=null){
  const body=$("patient-evidence-body");body.replaceChildren();
  if(!records.length){body.append(node("p","empty-note",absence||"이 기간에 원문 근거가 있는 기록이 없어요."));}
  for(const o of records){
    const card=node("section","patient-evidence-card");
    card.append(node("h3","",`${o.day} · ${observationLabels[o.metric]||"환자 발언"}`),node("p","search-note",`말한 날짜 ${new Date(o.created_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"})} · 본문 ${o.offset_start+1}–${o.offset_end}자 · 원문 대조 확인`));
    const quote=node("blockquote","patient-quote",o.quote);card.append(quote);
    const full=node("details","patient-full-message");full.append(node("summary","","발언 전체 보기"));
    const content=node("p","source-body"),chars=Array.from(o.content);
    content.append(document.createTextNode(chars.slice(0,o.offset_start).join("")),node("mark","",chars.slice(o.offset_start,o.offset_end).join("")),document.createTextNode(chars.slice(o.offset_end).join("")));full.append(content);card.append(full);
    const jump=node("a","external-link","원래 대화로 이동 ↗");jump.href=evidenceHref(o);jump.addEventListener("click",e=>{e.preventDefault();$("patient-evidence-dialog").close();showView("chat");const target=document.getElementById("message-"+o.message_id);if(target){target.scrollIntoView({block:"center",behavior:"smooth"});target.classList.add("evidence-highlight");setTimeout(()=>target.classList.remove("evidence-highlight"),2200);}});card.append(jump);body.append(card);
  }
  $("patient-evidence-dialog").showModal();
}
function patientReference(records,label="발언 근거 보기",absence=null){
  const a=node("a","patient-reference",label);a.href=records.length?evidenceHref(records[0]):"#report-sheet";
  a.addEventListener("click",e=>{e.preventDefault();openPatientEvidence(records,absence);});return a;
}
function showInstructionOriginal(i){
  const body=$("patient-evidence-body");body.replaceChildren();body.append(node("h3","","한의사 지침 입력 원문"),node("p","source-meta",`${i.author} · 시작 ${i.starts_on} · 입력 ${new Date(i.created_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"})}`));
  const p=node("p","source-body"),chars=Array.from(i.plan_text);p.append(document.createTextNode(chars.slice(0,i.offset_start).join("")),node("mark","",chars.slice(i.offset_start,i.offset_end).join("")),document.createTextNode(chars.slice(i.offset_end).join("")));body.append(p);$("patient-evidence-dialog").showModal();
}
function renderClinicianGoal(container,goal){
  const i=goal.guidance,row=node("article","clinician-goal");row.append(node("h3","",i.body));
  const actions=node("div","row-actions");actions.append(button("대화로 기록",()=>{showView("chat");$("message").focus();}));
  row.append(actions,fold("원문·관리",[node("p","search-note",`${i.author} · ${i.starts_on}부터 · ${i.rule.operator==="self_report"?"직접 실천 보고":"시간·수치 비교"}`),button("지침 원문",()=>showInstructionOriginal(i)),button("지침 종료",()=>deleteRecord("goals",goal.id),"quiet")],"record-details"));container.append(row);
}
function renderGuidance(care){
  if(guidanceState.sessionId!==state.session.id){guidanceState.sessionId=state.session.id;guidanceState.report=null;$("report-sheet").replaceChildren();$("report-end").value=care.today;$("patient-evidence-dialog").close();}
  $("report-end").max=care.today;$("guidance-start").max=care.today;
  const data=care.guidance||{instructions:[],observations:[]},active=data.instructions.filter(i=>i.active);
  $("guidance-sidebar").hidden=!active.length;$("guidance-count").textContent=String(active.length);
  const sidebar=$("guidance-sidebar-items");sidebar.replaceChildren();active.slice(0,4).forEach(i=>{const p=node("button","source-card guidance-side-item");p.type="button";p.append(node("strong","",i.body));p.addEventListener("click",()=>showInstructionOriginal(i));sidebar.append(p);});
  const plans=$("guidance-plans");plans.replaceChildren();
  if(!active.length)plans.append(node("p","empty-note","지침을 입력해 주세요."));
  else {plans.append(node("p","search-note",`진행 중 ${active.length}개`));}
  const records=$("patient-records");records.replaceChildren();
  if(data.observations.length){records.append(node("h3","","최근 대화 기록"));const list=node("div","patient-recent-records");data.observations.slice(-3).reverse().forEach(o=>{const row=node("div","patient-recent-row");row.append(node("strong","",`${o.day.slice(5)} · ${observationLabels[o.metric]} · ${observationValue(o)}`),patientReference([o],"원문"),button("제외",()=>deleteRecord("patient-records",o.id),"quiet"));list.append(row);});records.append(list);}
  if(currentView==="report")loadReport();
}
$("new-guidance").addEventListener("click",()=>{$("guidance-start").value=state.session.care.today;$("guidance-dialog").showModal();$("guidance-text").focus();});
$("guidance-form").addEventListener("submit",async e=>{e.preventDefault();const result=await runTool(()=>post("guidance",{text:$("guidance-text").value,author:$("guidance-author").value,starts_on:$("guidance-start").value}));if(result){$("guidance-dialog").close();$("guidance-text").value="";status("한의사 지침을 개인 목표로 저장했어요. 대화에서 실천 내용을 알려주세요.");}});
$("sidebar-report").addEventListener("click",()=>showView("report"));
$("report-form").addEventListener("submit",e=>{e.preventDefault();loadReport();});
$("print-report").addEventListener("click",()=>{if(guidanceState.report)window.print();});
async function loadReport(){
  if(!state.session)return;const sid=state.session.id,request=++guidanceState.request;
  $("report-state").textContent="기록 확인 중…";$("print-report").disabled=true;
  try{const report=await api(`/api/sessions/${sid}/visit-report?end=${encodeURIComponent($("report-end").value||state.session.care.today)}`);if(sid!==state.session?.id||request!==guidanceState.request)return;guidanceState.report=report;renderVisitReport(report);$("report-state").textContent="근거에서 원문 확인";$("print-report").disabled=false;}
  catch(error){if(request!==guidanceState.request)return;$("report-state").textContent=error.message;guidanceState.report=null;$("report-sheet").replaceChildren();}
}
function renderVisitReport(report){
  const sheet=$("report-sheet");sheet.replaceChildren();const evidence=new Map(report.evidence.map(o=>[o.id,o]));
  const refs=claim=>claim.evidence_ids.map(id=>evidence.get(id)).filter(Boolean);
  const header=node("header","report-header");header.append(node("h2","","2주 생활 리포트"),node("p","search-note",`${report.start} — ${report.end}`));sheet.append(header);
  const coverage=node("div","report-coverage");coverage.append(node("strong","",`발언 기록 ${report.recorded_days}일 / 14일`),node("span","",`기록 없음 ${report.missing_days}일`),patientReference(report.evidence,"기간의 근거",`${report.start} — ${report.end}의 대화에서 검증된 실천·생활 발언을 찾지 못했어요. 빈 날짜는 추정하지 않았어요.`));sheet.append(coverage);
  const summary=node("section","report-section");summary.append(node("h3","","01 · 지침 실천 현황"));
  if(!report.instructions.length)summary.append(node("p","empty-note","이 기간에 등록된 한의사 지침이 없어요."));
  const matrix=node("div","report-matrix"),table=node("table","adherence-table"),head=node("thead",""),tr=node("tr","");tr.append(node("th","","지침 · 근거"));report.days.forEach(d=>tr.append(node("th","",d.slice(8))));head.append(tr);table.append(head);const tbody=node("tbody","");
  report.instructions.forEach(row=>{
    const item=node("div","report-instruction");const name=node("button","instruction-name",row.instruction.body);name.type="button";name.addEventListener("click",()=>showInstructionOriginal(row.instruction));item.append(name,node("strong","report-rate",row.rate===null?"판정 보류":`${row.rate}%`));
    const line=node("p","report-claim",`${row.counts.met}/${row.assessed}일 준수 · 기록 없음 ${row.counts.unknown}일`+(row.counts.conflict?` · 상충 ${row.counts.conflict}일`:"")+(row.counts.unassessed?` · 미판정 ${row.counts.unassessed}일`:""));line.append(document.createTextNode(" "),patientReference(refs(row.claim),`근거 ${refs(row.claim).length}`,`${row.instruction.starts_on}부터 ${report.end}까지 해당 지침을 판정할 발언 기록이 없어요. 지침 시작 전 날짜는 분모에서 제외해요.`));item.append(line,fold("집계 기준",[node("p","search-note",`${row.instruction.author} · ${row.instruction.starts_on}부터`),node("p","search-note",row.claim.text)],"report-calculation"));summary.append(item);
    const r=node("tr",""),label=node("th","",row.instruction.body);label.scope="row";r.append(label);
    row.days.forEach(day=>{const td=node("td",""),b=node("button","day-status "+day.status,{met:"●",unmet:"×",unknown:"—",unassessed:"?",conflict:"!",inactive:"·"}[day.status]);b.type="button";b.setAttribute("aria-label",`${day.date} · ${row.instruction.body} · ${adherenceLabels[day.status]}`);b.title=`${day.date} · ${adherenceLabels[day.status]}`;b.addEventListener("click",()=>openPatientEvidence(refs(day),`${day.date} · ${adherenceLabels[day.status]}. 조회 시점 ${report.generated_at}.`));td.append(b);r.append(td);});tbody.append(r);
  });table.append(tbody);matrix.append(table);summary.append(matrix,node("p","report-legend","● 준수　× 미준수　— 기록 없음　? 미판정　! 상충　· 기간 밖"),node("p","report-method","실천율 = 준수 ÷ 판정일. 기록 없음·미판정·상충은 제외."));sheet.append(summary);
  const detail=node("div","report-detail-grid"),trends=node("section","report-section");trends.append(node("h3","","02 · 수면·식사 추이"));
  report.trends.forEach(c=>{const p=node("p","report-trend",c.text);p.append(document.createTextNode(" "),patientReference(refs(c),"근거",`${report.start} — ${report.end}의 해당 주차에 판정 가능한 기록이 없어요.`));trends.append(p);});
  report.meals.forEach(c=>{const p=node("p","report-patient-note",`${c.date} · “${c.text}”`);p.append(document.createTextNode(" "),patientReference(refs(c),"발언"));trends.append(p);});detail.append(trends);
  const symptoms=node("section","report-section");symptoms.append(node("h3","","03 · 환자가 말한 불편감"));
  if(!report.symptoms.length)symptoms.append(node("p","report-trend","기록 없음"),patientReference([],"조회 근거",`${report.start} — ${report.end}에서 검증된 불편감 발언이 없어요.`));
  report.symptoms.forEach(c=>{const p=node("p","report-patient-note",`${c.date} · “${c.text}”`);p.append(document.createTextNode(" "),patientReference(refs(c),"발언"));symptoms.append(p);});detail.append(symptoms);sheet.append(detail);
  sheet.append(node("footer","report-footer","대화 원문·날짜에 근거한 자기보고 요약. 지침 제목과 근거에서 원문 확인."));
}
