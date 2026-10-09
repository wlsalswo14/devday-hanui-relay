"use strict";
const $ = id => document.getElementById(id);
const state = {session: null, config: null, busy: false, consent: false, mode: "codex"};
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
function busy(value){state.busy=value;$("send").disabled=value;$("reset").disabled=value;$("mode").disabled=value;$("loading").hidden=!value;$("chat-form").setAttribute("aria-busy",String(value));document.querySelectorAll(".suggestion, .tool-view button, dialog form button, .action-button").forEach(b=>b.disabled=value);}
function setModeDescription(){
  $("mode-description").textContent=state.mode==="codex"?"GPT-6 Luna · High — 현재 로그인된 ChatGPT 계정으로 대화합니다.":"샘플 대화 · 실제 DB 검색 — 모델 호출 없이 화면과 생활기록을 체험합니다.";
}
function openSource(record){
  $("source-title").textContent=record.title;$("source-meta").textContent=`${record.publisher} · ${record.evidence_level} · 확인 ${record.retrieved_at}`;
  $("source-body").textContent=record.body;$("source-limit").textContent=record.limitations;
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
    const article=node("article",`message ${message.role}`);const label=node("div","message-label");
    if(message.role==="assistant")label.append(node("span","mini-mark","h."));
    label.append(node("span","",message.role==="user"?"나":message.mode==="codex"?"Hanui · Luna High":"Hanui · 샘플 대화"));article.append(label,node("div","bubble",message.content));
    if(message.sources?.length){const citations=node("div","citations");message.sources.forEach((record,i)=>{const button=node("button","citation",`${i+1} · ${record.title}`);button.type="button";button.addEventListener("click",()=>openSource(record));citations.append(button);});article.append(citations);}
    if(message.actions?.length){const actions=node("div","citations");message.actions.forEach(action=>{const button=node("button","secondary action-button",action.label||"다음 단계 보기");button.type="button";button.addEventListener("click",()=>openAction(action));actions.append(button);if(action.error)actions.append(node("p","search-note",action.error));});article.append(actions);}
    messages.append(article);
  });
  const memories=$("memories");memories.replaceChildren();$("memory-count").textContent=String(state.session.memories.length);
  if(!state.session.memories.length)memories.append(node("div","empty-note","수면, 식사, 활동처럼\n나의 일상을 이야기해 보세요."));
  state.session.memories.slice(-8).reverse().forEach(memory=>{const card=node("article","memory-card");card.append(node("div","memory-category",categories[memory.category]||"생활기록"),node("p","",memory.summary),node("span","memory-origin","사용자 발언 · "+new Date(memory.created_at).toLocaleDateString("ko-KR")));memories.append(card);});
  const sources=$("sources");sources.replaceChildren();$("knowledge-count").textContent=String(state.session.knowledge_count);
  const latest=[...state.session.messages].reverse().find(m=>m.role==="assistant");const records=latest?.sources||[];
  if(!records.length)sources.append(node("div","empty-note","질문에 맞는 자료를 찾으면\n출처를 여기에 모아둘게요."));
  records.forEach(record=>{const button=node("button","source-card");button.type="button";button.append(node("span","source-kind",record.evidence_level),node("strong","",record.title),node("span","source-publisher",record.publisher+" ↗"));button.addEventListener("click",()=>openSource(record));sources.append(button);});
  messages.scrollTop=messages.scrollHeight;
  if(typeof renderCare==="function")renderCare();
}
function updateCount(){$("counter").textContent=`${$("message").value.length} / 2000`;}
function ensureConsent(){
  if(state.mode!=="codex"||state.consent)return true;
  state.consent=window.confirm("AI 대화를 위해 입력한 이야기, 최근 대화·생활기록·체크인·일정과 찾아온 자료를 현재 로그인된 OpenAI 계정의 모델로 전달합니다. 병원·웹 검색을 요청하면 공개 검색어로 OpenAI 웹 검색을 실행합니다. 계속할까요?");return state.consent;
}
$("chat-form").addEventListener("submit",async event=>{
  event.preventDefault();if(state.busy||!state.session)return;const message=$("message").value.trim();if(!message)return;if(!ensureConsent())return;
  showError("");busy(true);
  try{state.session=await api(`/api/sessions/${state.session.id}/chat`,{method:"POST",body:JSON.stringify({message,mode:state.mode,consent:state.consent})});$("message").value="";updateCount();render();}
  catch(error){showError(error.message);}finally{busy(false);$("message").focus();}
});
$("message").addEventListener("input",updateCount);
$("message").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){event.preventDefault();$("chat-form").requestSubmit();}});
$("mode").addEventListener("change",()=>{state.mode=$("mode").value;setModeDescription();});
$("reset").addEventListener("click",async()=>{
  if(state.busy||!state.session||!window.confirm("이 대화와 연결된 생활기록을 모두 삭제할까요?"))return;
  busy(true);showError("");try{await api(`/api/sessions/${state.session.id}`,{method:"DELETE"});state.session=await api("/api/sessions",{method:"POST",body:"{}"});saveId(state.session.id);render();}catch(error){showError(error.message);}finally{busy(false);}
});
$("close-source").addEventListener("click",()=>$("source-dialog").close());
$("source-dialog").addEventListener("click",event=>{if(event.target===$("source-dialog")){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
async function init(){
  busy(true);try{
    state.config=await api("/api/config");const option=$("mode").querySelector('option[value="codex"]');option.disabled=!state.config.codex_enabled;
    if(!state.config.codex_enabled){state.mode="demo";$("mode").value="demo";}setModeDescription();
    const id=savedId();if(id){try{state.session=await api(`/api/sessions/${id}`);}catch(error){if(error.status!==404)throw error;}}
    if(!state.session)state.session=await api("/api/sessions",{method:"POST",body:"{}"});saveId(state.session.id);render();
  }catch(error){showError(error.message);}finally{busy(false);}
}
init();
