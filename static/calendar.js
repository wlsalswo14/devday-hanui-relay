"use strict";
const calendarState={sessionId:null,month:"",day:""};
function koreaDay(value){return new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Seoul",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(value));}
function calendarItems(care){
  const events=care.events.map(e=>({...e,calendarKind:e.kind==="appointment"?"confirmed":"event"}));
  care.bookings.filter(b=>b.status==="prepared").forEach(b=>events.push({id:"booking-"+b.id,title:b.hospital.name+" · 예약 준비",start:b.start,end:new Date(new Date(b.start).getTime()+30*60000).toISOString(),location:b.hospital.address,calendarKind:"prepared",booking:b}));
  return events.sort((a,b)=>new Date(a.start)-new Date(b.start));
}
function onCalendarDay(item,day){return new Date(item.start)<new Date(day+"T00:00:00+09:00").getTime()+86400000&&new Date(item.end)>new Date(day+"T00:00:00+09:00");}
function focusCalendarDate(value){calendarState.day=koreaDay(value);calendarState.month=calendarState.day.slice(0,7);showView("calendar");renderOwnCalendar(state.session.care);$("calendar-grid").scrollIntoView({behavior:"smooth",block:"center"});}
function renderOwnCalendar(care){
  if(!state.session)return;
  if(calendarState.sessionId!==state.session.id){calendarState.sessionId=state.session.id;calendarState.day=care.today;calendarState.month=care.today.slice(0,7);$("calendar-feedback").textContent="일정은 이 앱에 저장돼요. 병원 예약은 전화·예약 링크에서 접수해 주세요.";$("calendar-message").value="";}
  const [year,month]=calendarState.month.split("-").map(Number),start=new Date(Date.UTC(year,month-1,1,12)),items=calendarItems(care);
  $("calendar-month-title").textContent=`${year}년 ${month}월`;
  const grid=$("calendar-grid");grid.replaceChildren();const first=new Date(start);first.setUTCDate(1-start.getUTCDay());
  for(let i=0;i<42;i++){
    const date=new Date(first);date.setUTCDate(first.getUTCDate()+i);const day=date.toISOString().slice(0,10),found=items.filter(item=>onCalendarDay(item,day));
    const cell=node("button","calendar-cell"+(day.slice(0,7)!==calendarState.month?" outside":"")+(day===care.today?" today":"")+(day===calendarState.day?" selected":""));cell.type="button";cell.dataset.day=day;cell.setAttribute("aria-pressed",String(day===calendarState.day));cell.setAttribute("aria-label",`${day} · ${found.length}개 일정`);const number=node("span","calendar-number",date.getUTCDate());cell.append(number);
    found.slice(0,2).forEach(item=>cell.append(node("span","calendar-pill "+item.calendarKind,item.title)));if(found.length>2)cell.append(node("span","calendar-more",`+${found.length-2}`));if(found.length)cell.append(node("span","calendar-mobile-count",`${found.length}건`));
    cell.addEventListener("click",()=>{calendarState.day=day;calendarState.month=day.slice(0,7);renderOwnCalendar(care);});grid.append(cell);
  }
  $("calendar-day-title").textContent=new Date(calendarState.day+"T12:00:00+09:00").toLocaleDateString("ko-KR",{timeZone:"Asia/Seoul",month:"long",day:"numeric",weekday:"long"});
  const list=$("calendar-day-list");list.replaceChildren();const chosen=items.filter(item=>onCalendarDay(item,calendarState.day));if(!chosen.length)empty(list,"이 날은 비어 있어요.");
  chosen.forEach(item=>{const entry=node("article","calendar-entry "+item.calendarKind);entry.append(node("span","calendar-time",new Date(item.start).toLocaleTimeString("ko-KR",{timeZone:"Asia/Seoul",hour:"2-digit",minute:"2-digit"})),node("strong","",item.title));if(item.location)entry.append(node("p","search-note",item.location));entry.append(node("span","badge",item.calendarKind==="prepared"?"희망 시간 · 접수 전":item.calendarKind==="confirmed"?"병원 확정 · 사용자 확인":"개인 일정"));list.append(entry);});
}
function moveCalendarMonth(delta){const [year,month]=calendarState.month.split("-").map(Number),date=new Date(Date.UTC(year,month-1+delta,1,12));calendarState.month=date.toISOString().slice(0,7);calendarState.day=calendarState.month+"-01";renderOwnCalendar(state.session.care);}
$("calendar-prev").addEventListener("click",()=>moveCalendarMonth(-1));$("calendar-next").addEventListener("click",()=>moveCalendarMonth(1));
$("calendar-today").addEventListener("click",()=>focusCalendarDate(state.session.care.today+"T12:00:00+09:00"));
$("calendar-day-add").addEventListener("click",()=>openEvent({start:calendarState.day+"T14:00:00+09:00"}));
$("calendar-chat-form").addEventListener("submit",async event=>{event.preventDefault();const message=$("calendar-message").value.trim();if(!message||state.busy)return;if(state.mode!=="codex"){$("calendar-feedback").textContent="에이전트 모드에서 대화로 캘린더를 관리할 수 있어요.";return;}$("calendar-feedback").textContent="에이전트가 캘린더를 정리하고 있어요…";const success=await send(message);if(success){$("calendar-message").value="";$("calendar-feedback").textContent=state.session.messages.at(-1).content;const changed=state.session.messages.at(-1).actions?.find(a=>a.completed&&a.start&&["event","booking"].includes(a.type));if(changed){calendarState.day=koreaDay(changed.start);calendarState.month=calendarState.day.slice(0,7);renderOwnCalendar(state.session.care);}}else $("calendar-feedback").textContent=$("error").textContent||"요청을 처리하지 못했어요. 다시 이야기해 주세요.";});
