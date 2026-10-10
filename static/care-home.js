"use strict";
let careHomeData=null,careHomeLoad=0,careVisit=null;
const profileLabel=node('label','profile-field','개인 건강 프로필');
const profileText=document.createElement('textarea');profileText.id='health-profile-text';profileText.rows=6;profileText.maxLength=30000;profileText.placeholder='불편한 점, 복용약, 알레르기, 생활 습관, 관리 목표…';profileLabel.append(profileText);
$('system-instructions-text').rows=3;$('system-instructions-status').before(profileLabel,node('p','section-caption','필요한 내용만 찾아 대화에 참고해요.'));
function selectedCareGoal(){
  return careHomeData?.goals.find(g=>g.guidance?.active)||careHomeData?.goals.find(g=>g.session_id===careHomeData.program?.session_id)||careHomeData?.goals[0];
}
async function refreshCareHome(){
  if(!state.session)return;const generation=++careHomeLoad;
  try{const data=await api('/api/care-home');if(generation!==careHomeLoad)return;careHomeData=data;renderCareHome();if(new URLSearchParams(location.search).get('care')==='today'){$('care-home-body').hidden=false;$('care-home-toggle').setAttribute('aria-expanded','true');}}
  catch(error){if(error.status===401)showError(error.message);}
}
function careEvidence(item){
  const row=node('div','care-evidence');
  row.append(node('span','',item.quote||('수동 기록 · '+JSON.stringify(item.value))));
  if(item.message_id){const a=node('a','','발언 보기');a.href=`/?session=${item.session_id}&message=${item.message_id}`;a.target='_blank';a.rel='noopener';row.append(a);}
  return row;
}
function renderCareHome(){
  const body=$('care-home-body');body.replaceChildren();if(!careHomeData)return;
  $('care-home-toggle').textContent=careHomeData.program?'오늘의 관리':'관리 시작';
  if(!careHomeData.program){
    const form=node('form','care-start-form');
    for(const [name,label,max] of [['concern','어떤 점이 불편한가요?',300],['duration','언제부터인가요?',100],['goal','어떤 도움을 받고 싶나요?',200]]){const field=node('label','',label),input=document.createElement('input');input.name=name;input.required=true;input.maxLength=max;field.append(input);form.append(field);}
    const submit=node('button','primary','관리 시작');submit.type='submit';form.append(submit);
    form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{
      const fields=Object.fromEntries(new FormData(form));careHomeData=await api('/api/care-home/start',{method:'POST',body:JSON.stringify({...fields,session_id:state.session.id})});
      useSession(await api(`/api/sessions/${state.session.id}`));await refreshSessions();renderCareHome();
    }catch(error){if(error.name!=='AbortError')showError(error.message);}finally{busy(false);submit.disabled=false;}});body.append(form);return;
  }
  const today=node('div','care-today'),goal=selectedCareGoal();
  if(goal){const question=node('div','care-question');question.append(node('p','',`오늘 ‘${goal.title}’ 실천했나요?`));const buttons=node('div','row-actions');
    for(const [label,done] of [['예',true],['아니요',false]])buttons.append(button(label,async()=>{if(state.busy)return;busy(true);try{
      careHomeData=await api('/api/care-home/answer',{method:'POST',body:JSON.stringify({session_id:goal.session_id,goal_id:goal.id,done})});
      if(state.session.id===goal.session_id){state.session=await api(`/api/sessions/${state.session.id}`);render();}renderCareHome();status('기록했어요.');
    }catch(error){showError(error.message);}finally{busy(false);}}));question.append(buttons);today.append(question);
  }else today.append(button('오늘 기록',()=>{showView('daily');revealEditor('checkin-editor');}));
  const summary=careHomeData.goal_adherence;
  today.append(node('p','care-metrics',`이번 주 기록 ${careHomeData.recorded_days}/7일`+(summary.percent!==null?` · 목표 자기보고 ${summary.percent}%`:'')));
  const completed=new Set(careHomeData.followups.map(v=>v.booking_id));
  const visit=careHomeData.visits.find(v=>v.start.slice(0,10)<=careHomeData.today&&!completed.has(v.id));
  if(visit)today.append(button('방문 후 지침 입력',()=>{careVisit=visit;$('care-visited-date').value=visit.start.slice(0,10);$('care-visited-date').min=visit.start.slice(0,10);$('care-visited-date').max=careHomeData.today;$('care-visit-status').textContent='';$('care-visit-dialog').showModal();}));
  today.append(button('진료 준비',()=>{$('care-week-dialog').showModal();paintCareWeek();} ,'quiet'));
  body.append(today);
}
$('care-home-toggle').addEventListener('click',()=>{const open=$('care-home-body').hidden;$('care-home-body').hidden=!open;$('care-home-toggle').setAttribute('aria-expanded',String(open));});
function paintCareWeek(){
  const body=$('care-week-body');body.replaceChildren();if(!careHomeData)return;
  const a=careHomeData.adherence,g=careHomeData.goal_adherence;
  body.append(node('p','care-metrics',`기록 ${careHomeData.recorded_days}/7일 · 기록 없음 ${7-careHomeData.recorded_days}일`));
  if(a.percent!==null)body.append(node('p','',`지침 ${a.percent}% · 판정 가능 ${a.assessed}건 중 ${a.met}건 준수 · 기록 없음 ${a.unknown}건`));
  if(g.percent!==null)body.append(node('p','',`목표 자기보고 ${g.percent}% · 확인 ${g.assessed}건 중 ${g.met}건 실천`));
  for(const trend of careHomeData.trends){
    const details=node('details','care-day'),value=week=>week.average===null?'기록 없음':`${week.average}${trend.unit} (${week.recorded_days}일)`;
    details.append(node('summary','',`${trend.label} · 지난주 ${value(trend.previous)} / 이번 주 ${value(trend.current)}`));
    for(const item of [...trend.previous.evidence,...trend.current.evidence]){details.append(node('p','care-metrics',item.day),careEvidence(item));}
    if(trend.previous.conflicting_days+trend.current.conflicting_days)details.append(node('p','care-metrics','상충 기록은 평균에서 제외'));
    body.append(details);
  }
  careHomeData.days.forEach(day=>{const details=node('details','care-day');details.append(node('summary','',day.date+' · '+day.status));day.evidence.forEach(item=>details.append(careEvidence(item)));body.append(details);});
  if(careHomeData.program)body.append(node('p','care-metrics','진료 때 물어볼 점: '+careHomeData.program.concern+'에 대해 어떤 내용을 더 관찰하면 좋을까요?'));
  body.append(button('지침 추가',()=>{$('care-week-dialog').close();$('guidance-start').value=careHomeData.today;$('guidance-dialog').showModal();},'quiet'));
}
$('care-week-open').addEventListener('click',async()=>{await refreshCareHome();paintCareWeek();$('care-week-dialog').showModal();});
$('care-week-report').addEventListener('click',async()=>{
  if(!careHomeData||state.busy)return;
  try{await loadReport();showView('report');const document=reportDocuments.get(state.session.id);
    const lines=[`기간: ${careHomeData.days[0].date} ~ ${careHomeData.today}`,`기록 ${careHomeData.recorded_days}/7일 · 기록 없음 ${7-careHomeData.recorded_days}일`];
    const adherence=careHomeData.adherence,reported=careHomeData.goal_adherence;
    if(adherence.percent!==null)lines.push(`지침 ${adherence.percent}% · 판정 가능 ${adherence.assessed}건 중 ${adherence.met}건 준수 · 기록 없음 ${adherence.unknown}건 [아래 날짜별 발언 근거]`);
    if(reported.percent!==null)lines.push(`목표 자기보고 ${reported.percent}% · 확인 ${reported.assessed}건 중 ${reported.met}건 실천 [아래 목표 응답 근거]`);
    careHomeData.days.forEach(day=>{lines.push('\n'+day.date+' · '+day.status);day.evidence.forEach(item=>lines.push('- '+(item.quote||JSON.stringify(item.value))+(item.message_id?` [발언: ${location.origin}/?session=${item.session_id}&message=${item.message_id}]`:' [사용자 체크인]')));});
    document.title=document.title||'내원 전 주간 기록';document.body=(document.body?document.body+'\n\n':'')+lines.join('\n');document.dirty=true;paintReport(document);$('care-week-dialog').close();
  }catch(error){showError(error.message);}
});
$('care-visit-form').addEventListener('submit',async event=>{event.preventDefault();if(!careVisit)return;try{
  careHomeData=await api('/api/care-home/followup',{method:'POST',body:JSON.stringify({booking_id:careVisit.id,session_id:careVisit.session_id,visited_on:$('care-visited-date').value,instructions:$('care-visit-instructions').value})});
  if(state.session.id===careVisit.session_id){state.session=await api(`/api/sessions/${state.session.id}`);render();}
  $('care-visit-dialog').close();$('care-visit-instructions').value='';renderCareHome();status('받은 지침을 관리에 연결했어요.');
}catch(error){$('care-visit-status').textContent=error.message;}});
$('care-settings-open').addEventListener('click',async()=>{try{const settings=await api('/api/notifications');$('care-notification-enabled').checked=settings.enabled;$('care-notification-time').value=settings.time;$('care-notification-status').textContent='';$('care-settings-dialog').showModal();}catch(error){showError(error.message);}});
function pushKey(value){const padded=value+'='.repeat((4-value.length%4)%4);return Uint8Array.from(atob(padded.replaceAll('-','+').replaceAll('_','/')),c=>c.charCodeAt(0));}
$('care-settings-form').addEventListener('submit',async event=>{event.preventDefault();try{
  const enabled=$('care-notification-enabled').checked,time=$('care-notification-time').value;
  if(enabled){if(!('serviceWorker' in navigator)||!('PushManager' in window))throw new Error('이 브라우저는 푸시 알림을 지원하지 않아요.');
    if(await Notification.requestPermission()!=='granted')throw new Error('브라우저 설정에서 Hanui 알림을 허용해 주세요.');
    await navigator.serviceWorker.register('/sw.js');const registration=await navigator.serviceWorker.ready,settings=await api('/api/notifications');
    const subscription=await registration.pushManager.getSubscription()||await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:pushKey(settings.public_key)});
    await api('/api/notifications/subscribe',{method:'POST',body:JSON.stringify(subscription.toJSON())});
  }
  await api('/api/notifications',{method:'POST',body:JSON.stringify({enabled,time})});$('care-notification-status').textContent='저장했어요.';
}catch(error){$('care-notification-status').textContent=error.message;}});
