"use strict";
const $ = id => document.getElementById(id);
const state = {session: null, sessions: [], drafts: {}, config: null, busy: false, mode: "codex", sidebarOpen: false};
try{const preference=localStorage.getItem("hanui_sidebar_v2");if(preference!==null)state.sidebarOpen=preference==="open";}catch{}
const categories = {sleep:"수면",stress:"마음 · 스트레스",diet:"식사",activity:"활동",caffeine:"커피 · 카페인",symptom:"느낀 불편함",goal:"생활 목표"};
function node(tag, className, text) { const n = document.createElement(tag); if(className)n.className=className; if(text !== undefined)n.textContent=text; return n; }
function fold(label,items,className="secondary-details"){const d=node("details",className);d.append(node("summary","",label),...items);return d;}
function shortText(text,max=42){return text.length>max?text.slice(0,max-1)+"…":text;}
function sourceName(record){return record.category==="classical"?`${record.book} · ${record.section}`:record.title;}
function revealEditor(id){const editor=$(id);if(editor)editor.open=true;}
function savedId(){try{return localStorage.getItem("hanui_session");}catch{return null;}}
function saveId(id){try{localStorage.setItem("hanui_session",id);}catch{/* In-memory session remains usable. */}}
let activeAI=null, uiGeneration=0, loadingClock=null;
function cancelActiveRequest(){
  if(!activeAI)return;
  const request=activeAI;activeAI=null;uiGeneration++;request.controller.abort();
  const url=`/api/requests/${request.id}/cancel`,body="{}";
  if(!navigator.sendBeacon(url,new Blob([body],{type:"application/json"})))fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body,keepalive:true}).catch(()=>{});
  busy(false);showError("");if(typeof status==="function")status("");
  document.querySelectorAll(".pending-message").forEach(e=>e.remove());
}
window.addEventListener("pagehide",cancelActiveRequest);
document.addEventListener("visibilitychange",()=>{if(document.hidden)cancelActiveRequest();});
async function api(path, options={}) {
  let request=null;
  const ai=options.method==="POST"&&/\/(chat|hospitals|web|guidance)$/.test(path)&&(!path.endsWith("/guidance")||JSON.parse(options.body||"{}").start_conversation);
  if(ai){request={id:crypto.randomUUID().replaceAll("-",""),controller:new AbortController()};activeAI=request;options={...options,signal:request.controller.signal,body:JSON.stringify({...JSON.parse(options.body||"{}"),request_id:request.id})};busy(true);}
  try{
  const response=await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  let body;try{body=await response.json();}catch{throw new Error("서버 응답을 읽지 못했어요.");}
  if(request?.controller.signal.aborted)throw new DOMException("Cancelled","AbortError");
  if(!response.ok){const error=new Error(body.error||"요청을 처리하지 못했어요.");error.status=response.status;throw error;}
  return body;
  }finally{if(request&&activeAI===request)activeAI=null;}
}
function showError(message){$("error").textContent=message||"";$("error").hidden=!message;}
function busy(value){state.busy=value;$("send").disabled=value;$("reset").disabled=value;$("mode").disabled=value;$("session-select").disabled=value&&!activeAI;$("new-chat").disabled=value&&!activeAI;$("rename-chat").disabled=value;$("loading").hidden=!value;$("chat-form").setAttribute("aria-busy",String(value));document.querySelectorAll(".suggestion, .tool-view button, dialog form button, .action-button").forEach(b=>b.disabled=value);if(!value){clearInterval(loadingClock);loadingClock=null;$("loading-message").textContent="답변을 준비하고 있어요…";}else if(!loadingClock){const started=Date.now();loadingClock=setInterval(()=>{$("loading-message").textContent=`원문을 확인하고 답변을 준비 중이에요 · ${Math.floor((Date.now()-started)/1000)}초`;},1000);}}
function syncSidebar(){const chat=!document.querySelector(".conversation").hidden;$("context-sidebar").hidden=!chat||!state.sidebarOpen;$("toggle-sidebar").hidden=!chat;$("toggle-sidebar").textContent="기록·자료";$("toggle-sidebar").setAttribute("aria-expanded",String(chat&&state.sidebarOpen));document.querySelector(".workspace").classList.toggle("sidebar-collapsed",!state.sidebarOpen);$("sidebar-backdrop").hidden=!chat||!state.sidebarOpen;}
function toggleSidebar(open){if(!open&&$("context-sidebar").contains(document.activeElement))$("toggle-sidebar").focus();state.sidebarOpen=open;try{localStorage.setItem("hanui_sidebar_v2",open?"open":"closed");}catch{}syncSidebar();}
$("toggle-sidebar").addEventListener("click",()=>toggleSidebar(!state.sidebarOpen));
$("close-sidebar").addEventListener("click",()=>toggleSidebar(false));
$("sidebar-backdrop").addEventListener("click",()=>toggleSidebar(false));
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!document.querySelector("dialog[open]"))toggleSidebar(false);});
async function refreshSessions(){state.sessions=(await api("/api/sessions")).sessions;const select=$("session-select");select.replaceChildren();state.sessions.forEach(s=>{const option=node("option","",s.title);option.value=s.id;select.append(option);});select.value=state.session?.id||"";}
function useSession(session){if(state.session)state.drafts[state.session.id]=$("message").value;state.session=session;saveId(session.id);$("message").value=state.drafts[session.id]||"";updateCount();$("checkin-date").value="";$("goal-title").value="";selectedHospital=null;confirmingBooking=null;editingEvent=null;document.querySelectorAll("dialog[open]").forEach(d=>d.close());showError("");render();$("session-select").value=session.id;}
$("session-select").addEventListener("change",async()=>{cancelActiveRequest();if(state.busy)return;const id=$("session-select").value;busy(true);try{useSession(await api(`/api/sessions/${id}`));}catch(e){showError(e.message);$("session-select").value=state.session.id;}finally{busy(false);}});
$("new-chat").addEventListener("click",async()=>{cancelActiveRequest();if(state.busy)return;busy(true);try{useSession(await api("/api/sessions",{method:"POST",body:"{}"}));await refreshSessions();showView("chat");}catch(e){showError(e.message);}finally{busy(false);$("message").focus();}});
$("rename-chat").addEventListener("click",()=>{if(state.busy||!state.session)return;$("session-title").value=state.session.title;$("rename-dialog").showModal();$("session-title").focus();});
$("rename-form").addEventListener("submit",async e=>{e.preventDefault();if(state.busy)return;busy(true);try{state.session=await api(`/api/sessions/${state.session.id}/title`,{method:"POST",body:JSON.stringify({title:$("session-title").value})});await refreshSessions();$("rename-dialog").close();}catch(e){showError(e.message);}finally{busy(false);}});
function setModeDescription(){
  $("mode-description").textContent=state.mode==="codex"?"에이전트":"샘플 · AI 호출 없음";
}
function openSource(record){
  $("source-title").textContent=sourceName(record);$("source-meta").textContent=`${record.publisher} · ${record.retrieved_at}`;
  $("source-body").textContent=record.body;$("source-limit").textContent=record.limitations;
  $("source-location").textContent=record.location?`${record.book} · ${record.section} · ${record.location} · 판본 ${record.source_revision}`:"";
  $("source-location").hidden=!record.location;
  const readings=(record.citations||[]).filter(c=>c.reading);
  $("source-reading").textContent=readings.length?readings.map(c=>c.reading).join("\n\n"):record.summary||"";$("source-reading-section").hidden=!readings.length&&!record.summary;
  $("source-reading-section").querySelector("h3").textContent=readings.length?(readings.every(c=>["luna","openai","google"].includes(c.reading_origin))?"한국어 해석 · 에이전트":"한국어 해석 · 예시"):"자료 요약";
  const original=$("source-dialog").querySelector(".source-original");if(original){original.open=false;original.querySelector("summary").textContent=record.category==="classical"?"한자 원문·출처":"자료 원문·출처";}
  const link=$("source-link");let valid=false;try{const url=new URL(record.source_url);valid=["https:","http:"].includes(url.protocol);if(valid)link.href=url.href;}catch{}
  link.hidden=!valid;$("source-dialog").showModal();
}
function welcome(){
  const section=node("div","welcome");const art=node("div","welcome-art");art.append(node("span","","h."));section.append(art,node("h2","","오늘, 몸과 마음은 어때요?"));
  section.append(node("p","","편하게 이야기해 주세요."));
  const suggestions=node("div","suggestions");
  ["요즘 5시간 정도 자고 낮에 피곤해","미병이 뭔지 알려줘","강남역 근처 한의원 찾아줘"].forEach(text=>{const b=node("button","suggestion",text);b.type="button";b.addEventListener("click",()=>{$("message").value=text;updateCount();$("chat-form").requestSubmit();});suggestions.append(b);});section.append(suggestions);return section;
}
function render(){
  const messages=$("messages");messages.replaceChildren();
  if(!state.session.messages.length)messages.append(welcome());
  state.session.messages.forEach(message=>{
    const article=node("article",`message ${message.role}`);article.id="message-"+message.id;const label=node("div","message-label");
    if(message.role==="assistant")label.append(node("span","mini-mark","h."));
    label.append(node("span","",message.role==="user"?"나":message.mode==="codex"?"Hanui":"샘플"));article.append(label,node("div","bubble",message.content));
    if(message.sources?.length){message.sources.forEach(record=>{
      if(record.citations?.length){const passage=node("section","quoted-passage");passage.append(node("span","source-kind",shortText(sourceName(record),55)));
        record.citations.forEach(c=>{if(c.reading){passage.append(node("p","reading-label",["luna","openai","google"].includes(c.reading_origin)?"에이전트 해석":"예시 해석"),node("p","citation-reading",c.reading));}
          const original=fold(record.category==="classical"?"한자 원문·출처":"인용·출처",[node("blockquote","",c.quote),node("p","quote-location",`${record.location||record.title} · 본문 ${c.offset_start+1}–${c.offset_end}자`)],"source-original");
          const detail=node("button","citation","출처 보기 ↗");detail.type="button";detail.addEventListener("click",()=>openSource(record));original.append(detail);passage.append(original);
        });article.append(passage);
      }else{const detail=node("button","citation",shortText(sourceName(record)));detail.type="button";detail.title=record.title;detail.addEventListener("click",()=>openSource(record));article.append(detail);}
    });}
    if(message.actions?.length){const actions=node("div","message-actions");message.actions.forEach(action=>{if(action.type==="hospitals"||action.type==="web"){if(action.completed){const found=action.result?{id:action.search_id,kind:action.type,data:action.result}:state.session.care.searches.find(s=>s.id===action.search_id||(!action.search_id&&s.kind===action.type));if(found)renderLookup(actions,found);}if(action.error)actions.append(node("p","search-note",action.error));return;}const button=node("button","secondary action-button",action.label||"다음 단계 보기");button.type="button";button.addEventListener("click",()=>openAction(action));actions.append(button);});article.append(actions);}
    if(message.patient_evidence?.length&&typeof patientReference==="function")article.append(patientReference(message.patient_evidence,"기록 근거"));
    messages.append(article);
  });
  const memories=$("memories");memories.replaceChildren();$("memory-count").textContent=String(state.session.memories.length);
  if(!state.session.memories.length)memories.append(node("div","empty-note","수면, 식사, 활동처럼\n나의 일상을 이야기해 보세요."));
  const memoryCards=state.session.memories.slice().reverse().map(memory=>{const card=node("article","memory-card");card.append(node("div","memory-category",categories[memory.category]||"생활기록"),node("p","",shortText(memory.summary,75)));return card;});
  memories.append(...memoryCards.slice(0,3));if(memoryCards.length>3)memories.append(fold(`이전 기록 ${memoryCards.length-3}개`,memoryCards.slice(3)));
  const sources=$("sources");sources.replaceChildren();
  const latest=[...state.session.messages].reverse().find(m=>m.role==="assistant");const records=latest?.sources||[];
  $("knowledge-count").textContent=String(records.length);
  if(!records.length)sources.append(node("div","empty-note","질문에 맞는 자료를 찾으면\n출처를 여기에 모아둘게요."));
  records.forEach(record=>{const button=node("button","source-card");button.type="button";button.title=record.title;button.append(node("strong","",shortText(sourceName(record),45)));button.addEventListener("click",()=>openSource(record));sources.append(button);});
  messages.scrollTop=messages.scrollHeight;
  if(typeof renderCare==="function")renderCare();
  syncSidebar();
}
function updateCount(){$("counter").textContent=`${$("message").value.length} / 2000`;}
async function send(override=null){
  if(state.busy||!state.session)return false;const message=(typeof override==="string"?override:$("message").value).trim();if(!message)return false;
  showError("");busy(true);
  const generation=uiGeneration;
  const pending=node("article","message user pending-message");pending.append(node("div","message-label","나 · 전송 중"),node("div","bubble",message));$("messages").append(pending);$("messages").scrollTop=$("messages").scrollHeight;
  try{state.session=await api(`/api/sessions/${state.session.id}/chat`,{method:"POST",body:JSON.stringify({message,mode:state.mode})});if(override===null){$("message").value="";updateCount();}render();await refreshSessions();return true;}
  catch(error){if(generation===uiGeneration&&error.name!=="AbortError")showError(error.message);return false;}finally{pending.remove();if(generation===uiGeneration){busy(false);if(override===null)$("message").focus();}}
}
$("stop-response").addEventListener("click",cancelActiveRequest);
$("chat-form").addEventListener("submit",event=>{event.preventDefault();send();});
$("message").addEventListener("input",updateCount);
$("message").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){event.preventDefault();$("chat-form").requestSubmit();}});
$("mode").addEventListener("change",()=>{state.mode=$("mode").value;setModeDescription();});
$("reset").addEventListener("click",async()=>{
  if(state.busy||!state.session||!window.confirm("이 대화와 연결된 생활기록을 모두 삭제할까요?"))return;
  busy(true);showError("");try{const deleted=state.session.id;await api(`/api/sessions/${deleted}`,{method:"DELETE"});delete state.drafts[deleted];await refreshSessions();state.session=null;useSession(state.sessions.length?await api(`/api/sessions/${state.sessions[0].id}`):await api("/api/sessions",{method:"POST",body:"{}"}));await refreshSessions();}catch(error){showError(error.message);}finally{busy(false);}
});
$("close-source").addEventListener("click",()=>$("source-dialog").close());
$("source-dialog").addEventListener("click",event=>{if(event.target===$("source-dialog")){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
async function init(){
  busy(true);try{
    state.config=await api("/api/config");const option=$("mode").querySelector('option[value="codex"]');option.disabled=!state.config.codex_enabled;
    if(!state.config.codex_enabled){state.mode="demo";$("mode").value="demo";}setModeDescription();
    const shared=new URLSearchParams(location.search).get("session");const id=/^[a-f0-9]{32}$/.test(shared||"")?shared:savedId();if(id){try{state.session=await api(`/api/sessions/${id}`);}catch(error){if(error.status!==404)throw error;}}
    await refreshSessions();
    if(!state.session)state.session=state.sessions.length?await api(`/api/sessions/${state.sessions[0].id}`):await api("/api/sessions",{method:"POST",body:"{}"});saveId(state.session.id);render();await refreshSessions();
    const target=new URLSearchParams(location.search).get("message");if(/^[a-f0-9]{32}$/.test(target||"")){const el=document.getElementById("message-"+target);if(el){el.scrollIntoView({block:"center"});el.classList.add("evidence-highlight");}}
  }catch(error){showError(error.message);}finally{busy(false);}
}
init();
