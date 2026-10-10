"use strict";
let reminderRequest=null;
function cancelReminders(){
  if(reminderRequest){const request=reminderRequest;reminderRequest=null;request.controller.abort();navigator.sendBeacon(`/api/requests/${request.id}/cancel`,new Blob(["{}"],{type:"application/json"}));}
}
function clearReminders(){cancelReminders();$("calendar-reminders").replaceChildren();$("calendar-reminders").hidden=true;}
async function pollReminders(dismiss){
  if(reminderRequest||state.busy||document.hidden||!state.session||state.mode!=="codex")return;
  const sessionId=state.session.id,request={id:crypto.randomUUID().replaceAll("-",""),controller:new AbortController()};reminderRequest=request;
  try{
    const response=await fetch(`/api/sessions/${sessionId}/reminders`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_id:request.id,...(dismiss?{dismiss}: {})}),signal:request.controller.signal});
    if(!response.ok)return;
    const result=await response.json();
    if(request.controller.signal.aborted||sessionId!==state.session?.id||result.pending)return;
    const tray=$("calendar-reminders");tray.replaceChildren();tray.hidden=!result.reminders.length;
    result.reminders.forEach(item=>{
      const card=node("article","reminder-card"),heading=node("div","reminder-heading");heading.append(node("span","","에이전트 리마인드"));
      const close=node("button","quiet","×");close.type="button";close.setAttribute("aria-label",`${item.title} 알림 닫기`);close.addEventListener("click",()=>{card.remove();tray.hidden=!tray.children.length;pollReminders(item.id);});heading.append(close);
      const time=new Date(item.start).toLocaleTimeString("ko-KR",{timeZone:"Asia/Seoul",hour:"2-digit",minute:"2-digit"});
      card.append(heading,node("strong","",`${time} · ${item.title}`),node("p","",item.note));
      const open=node("button","quiet","캘린더 보기 ↗");open.type="button";open.addEventListener("click",()=>focusCalendarDate(item.start));card.append(open);tray.append(card);
    });
  }catch(error){if(error.name!=="AbortError")console.debug("Reminder temporarily unavailable");}
  finally{if(reminderRequest===request)reminderRequest=null;}
}
window.addEventListener("pagehide",cancelReminders);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)pollReminders();});
setInterval(()=>pollReminders(),60000);
setTimeout(()=>pollReminders(),1500);
