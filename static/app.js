"use strict";
const $ = id => document.getElementById(id);
const state = {session: null, sessions: [], drafts: {}, config: null, busy: false, mode: "codex", sidebarOpen: window.innerWidth>700};
try{const preference=localStorage.getItem("hanui_sidebar");if(preference!==null)state.sidebarOpen=preference==="open";}catch{}
const categories = {sleep:"수면",stress:"마음 · 스트레스",diet:"식사",activity:"활동",caffeine:"커피 · 카페인",symptom:"느낀 불편함",goal:"생활 목표"};
function node(tag, className, text) { const n = document.createElement(tag); if(className)n.className=className; if(text !== undefined)n.textContent=text; return n; }
function savedId(){try{return localStorage.getItem("hanui_session");}catch{return null;}}
function saveId(id){try{localStorage.setItem("hanui_session",id);}catch{/* In-memory session remains usable. */}}
async function api(path, options={}) {
  const response=await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  let body;try{body=await response.json();}catch{throw new Error("서버 응답을 읽지 못했어요.");}
  if(!response.ok){const error=new Error(body.error||"요청을 처리하지 못했어요.");error.status=response.status;throw error;}
  return body;
}
function showError(message){$("error").textContent=message||"";$("error").hidden=!message;}
function busy(value){state.busy=value;$("send").disabled=value;$("reset").disabled=value;$("mode").disabled=value;$("session-select").disabled=value;$("new-chat").disabled=value;$("rename-chat").disabled=value;$("loading").hidden=!value;$("chat-form").setAttribute("aria-busy",String(value));document.querySelectorAll(".suggestion, .tool-view button, dialog form button, .action-button").forEach(b=>b.disabled=value);}
function syncSidebar(){const chat=!document.querySelector(".conversation").hidden;$("context-sidebar").hidden=!chat||!state.sidebarOpen;$("toggle-sidebar").hidden=!chat;$("toggle-sidebar").textContent=state.sidebarOpen?"기록·자료 닫기":"기록·자료 열기";$("toggle-sidebar").setAttribute("aria-expanded",String(chat&&state.sidebarOpen));document.querySelector(".workspace").classList.toggle("sidebar-collapsed",!state.sidebarOpen);$("sidebar-backdrop").hidden=!chat||!state.sidebarOpen;}
function toggleSidebar(open){if(!open&&$("context-sidebar").contains(document.activeElement))$("toggle-sidebar").focus();state.sidebarOpen=open;try{localStorage.setItem("hanui_sidebar",open?"open":"closed");}catch{}syncSidebar();}
$("toggle-sidebar").addEventListener("click",()=>toggleSidebar(!state.sidebarOpen));
$("close-sidebar").addEventListener("click",()=>toggleSidebar(false));
$("sidebar-backdrop").addEventListener("click",()=>toggleSidebar(false));
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!document.querySelector("dialog[open]"))toggleSidebar(false);});
async function refreshSessions(){state.sessions=(await api("/api/sessions")).sessions;const select=$("session-select");select.replaceChildren();state.sessions.forEach(s=>{const option=node("option","",`${s.title} · ${s.turns}턴`);option.value=s.id;select.append(option);});select.value=state.session?.id||"";}
function useSession(session){if(state.session)state.drafts[state.session.id]=$("message").value;state.session=session;saveId(session.id);$("message").value=state.drafts[session.id]||"";updateCount();$("checkin-date").value="";$("goal-title").value="";selectedHospital=null;confirmingBooking=null;editingEvent=null;document.querySelectorAll("dialog[open]").forEach(d=>d.close());showError("");render();$("session-select").value=session.id;}
$("session-select").addEventListener("change",async()=>{if(state.busy)return;const id=$("session-select").value;busy(true);try{useSession(await api(`/api/sessions/${id}`));}catch(e){showError(e.message);$("session-select").value=state.session.id;}finally{busy(false);}});
$("new-chat").addEventListener("click",async()=>{if(state.busy)return;busy(true);try{useSession(await api("/api/sessions",{method:"POST",body:"{}"}));await refreshSessions();showView("chat");}catch(e){showError(e.message);}finally{busy(false);$("message").focus();}});
$("rename-chat").addEventListener("click",()=>{if(state.busy||!state.session)return;$("session-title").value=state.session.title;$("rename-dialog").showModal();$("session-title").focus();});
$("rename-form").addEventListener("submit",async e=>{e.preventDefault();if(state.busy)return;busy(true);try{state.session=await api(`/api/sessions/${state.session.id}/title`,{method:"POST",body:JSON.stringify({title:$("session-title").value})});await refreshSessions();$("rename-dialog").close();}catch(e){showError(e.message);}finally{busy(false);}});
function setModeDescription(){
  $("mode-description").textContent=state.mode==="codex"?"GPT-6 Luna · High — 현재 로그인된 ChatGPT 계정으로 대화합니다.":"샘플 대화 · 실제 DB 검색 — 모델 호출 없이 화면과 생활기록을 체험합니다.";
}
function openSource(record){
  $("source-title").textContent=record.title;$("source-meta").textContent=`${record.publisher} · ${record.evidence_level} · 확인 ${record.retrieved_at}${record.license?" · "+record.license:""}`;
  $("source-body").textContent=record.body;$("source-limit").textContent=record.limitations;
  $("source-location").textContent=record.location?`${record.book} · ${record.section} · ${record.location} · 판본 ${record.source_revision}`:"";
  $("source-location").hidden=!record.location;
  $("source-reading").textContent=record.summary||"";$("source-reading-section").hidden=!record.summary;
  const link=$("source-link");let valid=false;try{const url=new URL(record.source_url);valid=["https:","http:"].includes(url.protocol);if(valid)link.href=url.href;}catch{}
  link.hidden=!valid;$("source-dialog").showModal();
}
function welcome(){
  const section=node("div","welcome");const art=node("div","welcome-art");art.append(node("span","","h."));section.append(art,node("h2","","오늘, 몸과 마음은 어때요?"));
  const description=node("p","","일상을 이야기하면, 지난 맥락을 기억하고\n관련 한의학 자료를 함께 찾아봐요.");description.style.whiteSpace="pre-line";section.append(description);
  const suggestions=node("div","suggestions");
  ["요즘 5시간 정도 자고 낮에 피곤해","미병이 뭔지 알려줘","강남역 근처 한의원 찾아줘"].forEach(text=>{const b=node("button","suggestion",text);b.type="button";b.addEventListener("click",()=>{$("message").value=text;updateCount();$("chat-form").requestSubmit();});suggestions.append(b);});section.append(suggestions);return section;
}
function render(){
  const messages=$("messages");messages.replaceChildren();
  if(!state.session.messages.length)messages.append(welcome());
  state.session.messages.forEach(message=>{
    const article=node("article",`message ${message.role}`);article.id="message-"+message.id;const label=node("div","message-label");
    if(message.role==="assistant")label.append(node("span","mini-mark","h."));
    label.append(node("span","",message.role==="user"?"나":message.mode==="codex"?"Hanui · Luna High":"Hanui · 샘플 대화"));article.append(label,node("div","bubble",message.content));
    if(message.sources?.length){const citations=node("div","citations");message.sources.forEach((record,i)=>{if(record.citations?.length){const passage=node("div","quoted-passage");passage.append(node("span","source-kind",record.category==="classical"?"고문헌 원문":"현대 DB 자료"));record.citations.forEach(c=>{passage.append(node("blockquote","",c.quote),node("p","quote-location",`${record.location||record.title} · 본문 ${c.offset_start+1}–${c.offset_end}자`));});const detail=node("button","citation",`${record.book||record.publisher} · ${record.section||record.title} ↗`);detail.type="button";detail.addEventListener("click",()=>openSource(record));passage.append(detail);article.append(passage);}const button=node("button","citation",`${i+1} · ${record.title}`);button.type="button";button.addEventListener("click",()=>openSource(record));citations.append(button);});article.append(citations);}
    if(message.actions?.length){const actions=node("div","message-actions");message.actions.forEach(action=>{if(action.type==="hospitals"||action.type==="web"){if(action.completed){const found=action.result?{id:action.search_id,kind:action.type,data:action.result}:state.session.care.searches.find(s=>s.id===action.search_id||(!action.search_id&&s.kind===action.type));if(found)renderLookup(actions,found);}if(action.error)actions.append(node("p","search-note",action.error));return;}const button=node("button","secondary action-button",action.label||"다음 단계 보기");button.type="button";button.addEventListener("click",()=>openAction(action));actions.append(button);});article.append(actions);}
    if(message.patient_evidence?.length&&typeof patientReference==="function")article.append(patientReference(message.patient_evidence,"기록 근거 · 발언 원문"));
    messages.append(article);
  });
  const memories=$("memories");memories.replaceChildren();$("memory-count").textContent=String(state.session.memories.length);
  if(!state.session.memories.length)memories.append(node("div","empty-note","수면, 식사, 활동처럼\n나의 일상을 이야기해 보세요."));
  state.session.memories.slice(-8).reverse().forEach(memory=>{const card=node("article","memory-card");card.append(node("div","memory-category",categories[memory.category]||"생활기록"),node("p","",memory.summary),node("span","memory-origin","사용자 발언 · "+new Date(memory.created_at).toLocaleDateString("ko-KR")));memories.append(card);});
  const sources=$("sources");sources.replaceChildren();
  const latest=[...state.session.messages].reverse().find(m=>m.role==="assistant");const records=latest?.sources||[];
  $("knowledge-count").textContent=String(records.length);
  if(!records.length)sources.append(node("div","empty-note","질문에 맞는 자료를 찾으면\n출처를 여기에 모아둘게요."));
  records.forEach(record=>{const button=node("button","source-card");button.type="button";button.append(node("span","source-kind",record.evidence_level),node("strong","",record.title),node("span","source-publisher",record.publisher+" ↗"));button.addEventListener("click",()=>openSource(record));sources.append(button);});
  messages.scrollTop=messages.scrollHeight;
  if(typeof renderCare==="function")renderCare();
  syncSidebar();
}
function updateCount(){$("counter").textContent=`${$("message").value.length} / 2000`;}
async function send(override=null){
  if(state.busy||!state.session)return false;const message=(typeof override==="string"?override:$("message").value).trim();if(!message)return false;
  showError("");busy(true);
  try{state.session=await api(`/api/sessions/${state.session.id}/chat`,{method:"POST",body:JSON.stringify({message,mode:state.mode})});if(override===null){$("message").value="";updateCount();}render();await refreshSessions();return true;}
  catch(error){showError(error.message);return false;}finally{busy(false);if(override===null)$("message").focus();}
}
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
