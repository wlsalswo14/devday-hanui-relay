"use strict";
let currentView="chat", selectedHospital=null, confirmingBooking=null, editingEvent=null, toastTimer=null;
const careLabels={prepared:"예약 준비",confirmed:"사용자 확인 · 예약 확정",cancelled:"취소 기록"};
function sessionPath(suffix){return `/api/sessions/${state.session.id}/${suffix}`;}
function button(label,action,className="secondary"){const b=node("button",className,label);b.type="button";b.addEventListener("click",action);return b;}
function link(label,url,className="external-link"){
  const a=node("a",className,label);try{const parsed=new URL(url);if(parsed.protocol!=="https:")return node("span","search-note",label+" · 링크 없음");a.href=parsed.href;}catch{return node("span","search-note",label+" · 링크 없음");}
  a.target="_blank";a.rel="noopener noreferrer";return a;
}
function status(message,error=false,permanent=false){clearTimeout(toastTimer);$("tool-status").textContent=message;$("tool-status").className="toast"+(error?" toast-error":"");$("tool-status").hidden=!message;if(!permanent)toastTimer=setTimeout(()=>{$("tool-status").hidden=true;},6500);}
function showView(view){
  currentView=view;document.querySelector(".conversation").hidden=view!=="chat";document.querySelector(".context").hidden=view!=="chat";
  document.querySelectorAll(".tool-view").forEach(p=>p.hidden=p.id!==`${view}-view`);
  document.querySelectorAll(".app-nav button").forEach(b=>{const selected=b.dataset.view===view;b.classList.toggle("active",selected);if(selected)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current");});
  if(view==="library"&&!$("library-results").children.length)loadLibrary();
  syncSidebar();
}
document.querySelectorAll(".app-nav button").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.view)));
document.querySelectorAll(".close-dialog").forEach(b=>b.addEventListener("click",()=>b.closest("dialog").close()));
function openAction(action){
  if(state.busy)return;
  if(action.type==="hospitals"||action.type==="web"){showView("chat");$("message").focus();}
  else if(action.type==="calendar"||action.type==="booking"||action.completed){showView("calendar");if(action.start&&typeof focusCalendarDate==="function")focusCalendarDate(action.start);}
  else if(action.type==="event"){showView("calendar");openEvent({title:action.title,start:action.start,note:action.note});}
  else {showView("daily");if(action.type==="goal"){$("goal-title").value=action.title||"";$("goal-title").focus();}else if(action.type==="checkin"){$("checkin-date").value=state.session.care.today;loadCheckin();for(const key of ["sleep","stress","energy","discomfort","activity","caffeine"]){if(action[key])$(`checkin-${key}`).value=action[key];}if(action.note)$("checkin-note").value=action.note;$("checkin-state").textContent="대화에서 정리한 초안이에요. 날짜·수치를 확인한 뒤 저장해 주세요.";$("checkin-sleep").focus();}else $("checkin-note").focus();}
}
async function runTool(task,message="저장하고 있어요…"){
  if(state.busy||!state.session)return;busy(true);status(message,false,true);
  try{const result=await task();if(result?.checkins){state.session.care=result;renderCare();}status("완료했어요.");return result;}
  catch(error){status(error.message,true);return null;}finally{busy(false);}
}
function post(suffix,body){return api(sessionPath(suffix),{method:"POST",body:JSON.stringify(body)});}
function formatTime(value){return new Date(value).toLocaleString("ko-KR",{month:"short",day:"numeric",weekday:"short",hour:"2-digit",minute:"2-digit"});}
function inputTime(value){if(!value)return "";const d=new Date(value);if(Number.isNaN(d.getTime()))return "";return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}T${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;}
function tomorrowTime(){const d=new Date();d.setDate(d.getDate()+1);d.setHours(14,0,0,0);return inputTime(d.toISOString());}
function empty(container,message){container.append(node("p","empty-note",message));}
function loadCheckin(){
  if(!state.session)return;const selected=$("checkin-date").value||state.session.care.today;
  const c=state.session.care.checkins.find(x=>x.date===selected);
  ["sleep","stress","energy","discomfort","activity","caffeine","note"].forEach(key=>{$(`checkin-${key}`).value=c?.[key]??"";});
  $("checkin-state").textContent=c?"이 날짜의 기존 기록을 수정해요.":"입력한 항목만 기록해요. 비워 둔 값은 추정하지 않아요.";
}
$("checkin-date").addEventListener("change",loadCheckin);
function renderCare(){
  const care=state.session?.care;if(!care)return;
  $("checkin-date").max=care.today;if(!$("checkin-date").value)$("checkin-date").value=care.today;loadCheckin();
  const summary=$("daily-summary");summary.replaceChildren();
  [["최근 7일 기록",care.summary.days,"일"],["평균 수면",care.summary.averages.sleep,"시간"],["평균 스트레스",care.summary.averages.stress,"/ 10"],["평균 활동",care.summary.averages.activity,"분"]].forEach(([label,value,unit])=>{const card=node("div","stat-card");card.append(node("span","stat-label",label),node("strong","",value===null?"—":String(value)),node("span","stat-unit",value===null?"아직 기록이 없어요":unit));summary.append(card);});
  const goals=$("goals-list");goals.replaceChildren();if(!care.goals.length)empty(goals,"작은 목표 하나부터 시작해요.");
  care.goals.forEach(goal=>{const row=node("article","goal-row");const label=node("label","check-label");const check=document.createElement("input");check.type="checkbox";check.checked=goal.completed_dates.includes(care.today);check.setAttribute("aria-label",goal.title+" 오늘 완료");check.addEventListener("change",()=>{const done=check.checked;runTool(()=>post(`goals/${goal.id}`,{done})).then(r=>{if(!r)check.checked=!done;});});label.append(check,node("span","",goal.title));row.append(label,node("span","memory-origin",`누적 ${goal.completed_dates.length}일 실천`),button("삭제",()=>deleteRecord("goals",goal.id),"quiet"));goals.append(row);});
  const chart=$("sleep-chart");chart.replaceChildren();
  for(let ago=6;ago>=0;ago--){const d=new Date(care.today+"T12:00:00+09:00");d.setDate(d.getDate()-ago);const date=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;const found=care.checkins.find(c=>c.date===date);const hours=found?.sleep??null;const column=node("div","chart-column");column.append(node("span","chart-value",hours===null?"—":`${hours}h`));const track=node("div","chart-track");const bar=node("div","chart-bar"+(hours===null?" missing":""));bar.style.height=`${hours===null?3:Math.min(hours/12*100,100)}%`;track.append(bar);column.append(track,node("span","chart-date",date.slice(5)));chart.append(column);}
  const history=$("checkin-history");history.replaceChildren();if(!care.checkins.length)empty(history,"오늘의 기록이 쌓이면 흐름을 확인할 수 있어요.");
  care.checkins.slice(0,14).forEach(c=>{const row=node("article","record-row");row.append(node("strong","",c.date),node("p","",[`수면 ${c.sleep??"—"}시간`,`스트레스 ${c.stress??"—"}/10`,`활력 ${c.energy??"—"}/10`,`불편감 ${c.discomfort??"—"}/10`,`활동 ${c.activity??"—"}분`,`카페인 ${c.caffeine??"—"}잔`].join(" · ")));if(c.note)row.append(node("p","record-note",c.note));const actions=node("div","row-actions");actions.append(button("수정",()=>{$("checkin-date").value=c.date;loadCheckin();$("checkin-sleep").focus();}),button("삭제",()=>deleteRecord("checkins",c.date),"quiet"));row.append(actions);history.append(row);});
  const memories=$("memory-history");memories.replaceChildren();if(!state.session.memories.length)empty(memories,"대화에서 나의 생활을 알려주면 기록해요.");
  state.session.memories.slice().reverse().forEach(m=>{const row=node("article","record-row");row.append(node("span","badge",categories[m.category]||"기록"),node("p","",m.summary),node("p","memory-origin",`원문: ${m.quote}`),button("이 기억 삭제",()=>deleteRecord("memories",m.id),"quiet"));memories.append(row);});
  renderCalendar(care);
}
async function deleteRecord(collection,id){if(state.busy||!window.confirm("이 기록을 삭제할까요?"))return;await runTool(async()=>{const care=await api(sessionPath(`${collection}/${id}`),{method:"DELETE"});if(collection==="memories"){state.session=await api(`/api/sessions/${state.session.id}`);render();}return care;});}
$("checkin-form").addEventListener("submit",async e=>{e.preventDefault();const body={date:$("checkin-date").value,note:$("checkin-note").value};["sleep","stress","energy","discomfort","activity","caffeine"].forEach(k=>{const v=$(`checkin-${k}`).value;body[k]=v===""?null:Number(v);});await runTool(()=>post("checkins",body));});
$("goal-form").addEventListener("submit",async e=>{e.preventDefault();const result=await runTool(()=>post("goals",{title:$("goal-title").value,category:$("goal-category").value}));if(result)$("goal-title").value="";});
async function loadLibrary(){
  const query=new URLSearchParams({q:$("library-query").value,category:$("library-category").value});
  try{const response=await api("/api/knowledge?"+query);const container=$("library-results");container.replaceChildren();$("library-total").textContent=`검색 ${response.records.length}건 · 전체 ${state.session?.knowledge_count??""}건`;
    if(!response.records.length)empty(container,"이 검색어와 맞는 자료가 없어요. 약재 이름이나 미병·수면·스트레스 등으로 검색해 보세요.");
    response.records.forEach(r=>{const card=node("article","tool-card library-record");card.append(node("span","badge",{herb:"한약재",concept:"미병·개념",lifestyle:"생활",resource:"정보 포털",classical:"고문헌 원문"}[r.category]),node("h2","",r.title),node("p","",r.summary||r.body),node("p","search-note",r.location||r.publisher),button("출처·적용 범위 보기",()=>openSource(r)));container.append(card);});
  }catch(error){status(error.message,true);}
}
$("library-form").addEventListener("submit",e=>{e.preventDefault();loadLibrary();});
function renderLookup(container,search){
    const kind=search.kind,data=search.data;const head=node("div","lookup-heading");head.append(node("span","badge",kind==="hospitals"?"Hanui가 찾은 병원":"Hanui가 찾아본 정보"),node("p","search-note",`확인 ${formatTime(data.searched_at)}`));container.append(head);
    if(kind==="hospitals"){
      const cards=node("div","hospital-grid");data.hospitals.forEach(h=>{const card=node("article","tool-card hospital-card");card.append(node("h2","",h.name),node("p","hospital-address",h.address||"주소 확인 필요"),node("p","hospital-reason",h.reason));
        if(h.reviews.length){const reviews=node("details","review-section");reviews.append(node("summary","","확인한 공개 자료"));h.reviews.forEach(r=>{const item=node("div","review-item");item.append(node("span","badge",r.kind==="patient_review"?"환자 후기 · 검색 요약":"병원 안내 · 홍보 정보"),node("p","",r.summary),link("후기·정보 원문 ↗",r.url));reviews.append(item);});card.append(reviews);}
        const actions=node("div","row-actions");const phone=h.phone.replace(/[^+0-9-]/g,"");if(phone&&/\d{7}/.test(phone.replace(/-/g,""))){const a=node("a","secondary",`전화 ${h.phone}`);a.href="tel:"+phone;actions.append(a);}if(h.booking_url)actions.append(link("예약 페이지 ↗",h.booking_url,"secondary"));
        actions.append(button("예약 준비",()=>openBooking(search.id,h),"primary"),button("방문 일정 저장",()=>openEvent({title:h.name+" 방문",location:h.address}),"secondary"));card.append(actions,link("정보 원문 확인 ↗",h.source_url));cards.append(card);});
      if(!data.hospitals.length)empty(cards,"확인 가능한 병원을 찾지 못했어요. 지역이나 조건을 바꿔 검색해 주세요.");container.append(cards);
    }else{
      data.results.forEach(r=>{const card=node("article","tool-card web-card");card.append(node("h2","",r.title),node("p","",r.summary),node("p","search-note",r.publisher),link("원문 확인 ↗",r.url));container.append(card);});if(!data.results.length)empty(container,"확인 가능한 검색 결과가 없어요.");
    }
}
function openBooking(searchId,hospital){selectedHospital={searchId,hospital};$("booking-title").textContent=hospital.name+" 예약 준비";$("booking-start").value=tomorrowTime();$("booking-note").value="";$("booking-dialog").showModal();}
$("booking-use-memory").addEventListener("click",()=>{const recent=state.session.memories.slice(-6);$("booking-note").value=recent.map(m=>`${categories[m.category]||"생활기록"}: ${m.quote}`).join("\n").slice(0,1000);});
$("booking-form").addEventListener("submit",async e=>{e.preventDefault();if(!selectedHospital)return;const result=await runTool(()=>post("bookings",{search_id:selectedHospital.searchId,hospital_id:selectedHospital.hospital.id,start:$("booking-start").value,note:$("booking-note").value}));if(result){$("booking-dialog").close();showView("calendar");status("예약 준비를 저장했어요. 전화·예약 페이지에서 병원에 접수해 주세요.");}});
function openConfirmation(booking){confirmingBooking=booking;$("booking-confirmation").value="";$("booking-confirmed").checked=false;$("confirm-dialog").showModal();}
$("confirm-form").addEventListener("submit",async e=>{e.preventDefault();if(!confirmingBooking)return;const result=await runTool(()=>post(`bookings/${confirmingBooking.id}`,{status:"confirmed",confirmation:$("booking-confirmation").value,confirmed_by_user:$("booking-confirmed").checked}));if(result){$("confirm-dialog").close();status("사용자 확인으로 예약 확정을 기록하고 방문 일정을 만들었어요.");}});
function renderCalendar(care){
  if(typeof renderOwnCalendar==="function")renderOwnCalendar(care);
  const events=$("events-list");events.replaceChildren();if(!care.events.length)empty(events,"생활 일정이나 확정된 방문 일정이 여기에 모여요.");
  if(care.conflicts?.length)events.append(node("p","error",`시간이 겹치는 일정 ${care.conflicts.length}쌍이 있어요. 날짜·시간을 확인해 주세요.`));
  care.events.forEach(event=>{const card=node("article","record-row");card.append(node("span","badge",event.kind==="appointment"?"병원 방문 · 사용자 확인":"나의 일정"),node("h3","",event.title),node("p","",formatTime(event.start)+" ~ "+formatTime(event.end)));if(event.location)card.append(node("p","search-note",event.location));if(event.note)card.append(node("p","record-note",event.note));const actions=node("div","row-actions");actions.append(button("캘린더에서 보기",()=>focusCalendarDate(event.start),"secondary"));if(event.kind!=="appointment")actions.append(button("수정",()=>openEvent(event)),button("삭제",()=>deleteRecord("events",event.id),"quiet"));card.append(actions);events.append(card);});
  const bookings=$("bookings-list");bookings.replaceChildren();if(!care.bookings.length)empty(bookings,"대화에서 방문할 지역을 알려주면 Hanui가 병원을 찾아 예약 준비를 도와요.");
  care.bookings.forEach(b=>{const card=node("article","record-row");card.append(node("span","badge booking-status "+b.status,careLabels[b.status]),node("h3","",b.hospital.name));if(b.hospital.address)card.append(node("p","hospital-address",b.hospital.address));if(b.hospital.reason)card.append(node("p","hospital-reason",b.hospital.reason));card.append(node("p","",`${b.status==="prepared"?"희망 시간":"기록된 시간"} · ${formatTime(b.start)}`));if(b.note)card.append(node("p","record-note",b.note));if(b.confirmation)card.append(node("p","search-note",b.confirmation));
    const actions=node("div","row-actions");if(b.status==="prepared"){const phone=b.hospital.phone.replace(/[^+0-9-]/g,"");if(phone){const a=node("a","secondary","병원 전화");a.href="tel:"+phone;actions.append(a);}if(b.hospital.booking_url)actions.append(link("예약 페이지 ↗",b.hospital.booking_url,"secondary"));actions.append(button("병원에서 확정받았어요",()=>openConfirmation(b),"primary"));}
    if(b.status!=="cancelled")actions.append(button("취소 기록",async()=>{if(!window.confirm("실제 예약이 있다면 먼저 병원에서 취소해 주세요. 이 버튼은 로컬 예약 기록과 연결된 일정만 취소합니다. 기록을 취소할까요?"))return;await runTool(()=>post(`bookings/${b.id}`,{status:"cancelled",confirmed_by_user:true}));},"quiet"));card.append(actions);bookings.append(card);});
}
function openEvent(event={}){editingEvent=event.id||null;$("event-title").value=event.title||"";$("event-start").value=inputTime(event.start)||tomorrowTime();const end=new Date($("event-start").value);end.setMinutes(end.getMinutes()+30);$("event-end").value=inputTime(event.end)||inputTime(end.toISOString());$("event-location").value=event.location||"";$("event-note").value=event.note||"";$("event-dialog").showModal();}
$("new-event").addEventListener("click",()=>openEvent());
$("event-form").addEventListener("submit",async e=>{e.preventDefault();const result=await runTool(()=>post("events"+(editingEvent?"/"+editingEvent:""),{title:$("event-title").value,start:$("event-start").value,end:$("event-end").value,location:$("event-location").value,note:$("event-note").value}));if(result)$("event-dialog").close();});
async function downloadFile(path,filename){try{const response=await fetch(path);if(!response.ok)throw new Error("내보내기를 완료하지 못했어요.");const url=URL.createObjectURL(await response.blob());const a=document.createElement("a");a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){status(error.message,true);}}
$("calendar-export").addEventListener("click",()=>{if(state.session)downloadFile(sessionPath("calendar.ics"),"hanui-calendar.ics");});
$("export-records").addEventListener("click",()=>{if(state.session)downloadFile(sessionPath("export"),"hanui-my-records.json");});
