"use strict";
const guidanceState={sessionId:null};
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
  if(i.assessment)body.append(node("h3","","한의사 진단·평가"),node("p","source-body",i.assessment));
  const p=node("p","source-body"),chars=Array.from(i.plan_text);p.append(document.createTextNode(chars.slice(0,i.offset_start).join("")),node("mark","",chars.slice(i.offset_start,i.offset_end).join("")),document.createTextNode(chars.slice(i.offset_end).join("")));body.append(p);$("patient-evidence-dialog").showModal();
}
function renderClinicianGoal(container,goal){
  const i=goal.guidance,row=node("article","clinician-goal");row.append(node("h3","",i.body));
  const actions=node("div","row-actions");actions.append(button("대화로 기록",()=>{showView("chat");$("message").focus();}));
  row.append(actions,fold("원문·관리",[node("p","search-note",`${i.author} · ${i.starts_on}부터 · ${i.rule.operator==="self_report"?"직접 실천 보고":"시간·수치 비교"}`),button("지침 원문",()=>showInstructionOriginal(i)),button("지침 종료",()=>deleteRecord("goals",goal.id),"quiet")],"record-details"));container.append(row);
}
function renderGuidance(care){
  if(guidanceState.sessionId!==state.session.id){guidanceState.sessionId=state.session.id;$("patient-evidence-dialog").close();}
  $("guidance-start").max=care.today;
  const data=care.guidance||{instructions:[],observations:[]},active=data.instructions.filter(i=>i.active);
  $("guidance-sidebar").hidden=!active.length;$("guidance-count").textContent=String(active.length);
  const sidebar=$("guidance-sidebar-items");sidebar.replaceChildren();active.slice(0,4).forEach(i=>{const p=node("button","source-card guidance-side-item");p.type="button";p.append(node("strong","",i.body));p.addEventListener("click",()=>showInstructionOriginal(i));sidebar.append(p);});
  const plans=$("guidance-plans");plans.replaceChildren();
  if(!active.length)plans.append(node("p","empty-note","지침을 입력해 주세요."));
  else {plans.append(node("p","search-note",`진행 중 ${active.length}개`));}
  const assessments=(data.plans||[]).filter(p=>p.assessment);if(assessments.length)plans.append(fold("한의사 진단·평가",assessments.map(p=>node("p","search-note",`${p.author} · ${p.assessment}`)),"record-details"));
  const records=$("patient-records");records.replaceChildren();
  if(data.observations.length){records.append(node("h3","","최근 대화 기록"));const list=node("div","patient-recent-records");data.observations.slice(-3).reverse().forEach(o=>{const row=node("div","patient-recent-row");row.append(node("strong","",`${o.day.slice(5)} · ${observationLabels[o.metric]} · ${observationValue(o)}`),patientReference([o],"원문"),button("제외",()=>deleteRecord("patient-records",o.id),"quiet"));list.append(row);});records.append(list);}
  if(currentView==="report")loadReport();
}
$("new-guidance").addEventListener("click",()=>{$("guidance-start").value=state.session.care.today;$("guidance-dialog").showModal();$("guidance-text").focus();});
$("guidance-form").addEventListener("submit",async e=>{e.preventDefault();const result=await runTool(async()=>{const care=await post("guidance",{text:$("guidance-text").value,assessment:$("guidance-assessment").value,author:$("guidance-author").value,starts_on:$("guidance-start").value,start_conversation:true,mode:state.mode});state.session=await api(`/api/sessions/${state.session.id}`);render();return care;},"첫 확인 질문을 준비하고 있어요…");if(result){$("guidance-dialog").close();$("guidance-text").value="";$("guidance-assessment").value="";showView("chat");$("message").focus();status("Hanui의 질문에 답해 주세요.");}});
$("sidebar-report").addEventListener("click",()=>showView("report"));
