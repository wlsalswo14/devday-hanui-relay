"use strict";
const reportDocuments=new Map();
let reportSession=null,reportLoad=0;
function paintReport(document){
  $("report-document-title").value=document.title;$("report-document-body").value=document.body;
  $("report-document-title").disabled=false;$("report-document-body").disabled=false;$("save-report").disabled=false;$("print-report").disabled=false;$("draft-report").disabled=!state.config?.codex_enabled;
  $("report-state").textContent=document.dirty?"미저장":document.revision?"저장됨":"";
}
async function loadReport(){
  if(!state.session)return;
  const sid=state.session.id;
  if(reportSession===sid)return;
  reportSession=sid;const generation=++reportLoad;
  if(reportDocuments.has(sid)){paintReport(reportDocuments.get(sid));return;}
  $("report-document-title").value="";$("report-document-body").value="";
  $("report-document-title").disabled=true;$("report-document-body").disabled=true;$("save-report").disabled=true;$("print-report").disabled=true;$("draft-report").disabled=true;$("report-state").textContent="불러오는 중…";
  try{
    const document=await api(`/api/sessions/${sid}/report`);
    if(generation!==reportLoad||sid!==state.session?.id)return;
    reportDocuments.set(sid,{...document,dirty:false});paintReport(reportDocuments.get(sid));
  }catch(error){if(generation===reportLoad){reportSession=null;$("report-state").textContent=error.message;}}
}
function editReport(){
  const document=reportDocuments.get(state.session?.id);if(!document)return;
  document.title=$("report-document-title").value;document.body=$("report-document-body").value;document.dirty=true;$("report-state").textContent="미저장";
}
$("report-document-title").addEventListener("input",editReport);
$("report-document-body").addEventListener("input",editReport);
async function saveReport(){
  const sid=state.session?.id,document=reportDocuments.get(sid);if(!document||document.saving)return;
  const snapshot={title:document.title,body:document.body,revision:document.revision};document.saving=true;$("save-report").disabled=true;$("report-state").textContent="저장 중…";
  try{
    const saved=await api(`/api/sessions/${sid}/report`,{method:"POST",body:JSON.stringify(snapshot)});
    document.revision=saved.revision;document.updated_at=saved.updated_at;document.dirty=document.title!==snapshot.title||document.body!==snapshot.body;
    if(state.session?.id===sid)$("report-state").textContent=document.dirty?"미저장":"저장됨";
  }catch(error){if(state.session?.id===sid)$("report-state").textContent=error.message;}
  finally{document.saving=false;if(state.session?.id===sid)$("save-report").disabled=false;}
}
$("save-report").addEventListener("click",saveReport);
$("print-report").addEventListener("click",()=>window.print());
window.addEventListener("beforeprint",()=>{$("report-print-title").textContent=$("report-document-title").value||"리포트";$("report-print-body").textContent=$("report-document-body").value;});
document.addEventListener("keydown",event=>{if(currentView==="report"&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();saveReport();}});
let reportDraft=null,reportDraftSession=null,reportDraftRunning=false;
$("draft-report").addEventListener("click",()=>{reportDraft=null;reportDraftSession=state.session.id;$("report-draft-preview").hidden=true;$("report-draft-status").textContent="";$("report-draft-instruction").value="";$("report-draft-dialog").showModal();$("report-draft-instruction").focus();});
$("report-draft-form").addEventListener("submit",async event=>{
  event.preventDefault();if(state.busy||reportDraftRunning)return;
  const sid=state.session?.id,document=reportDocuments.get(sid);if(!document)return;
  const generation=uiGeneration;reportDraftRunning=true;$("report-draft-preview").hidden=true;$("report-draft-status").textContent="정리 중…";$("report-draft-stop").hidden=false;
  try{
    const draft=await api(`/api/sessions/${sid}/report-draft`,{method:"POST",body:JSON.stringify({instruction:$("report-draft-instruction").value,current:{title:document.title,body:document.body}})});
    if(generation!==uiGeneration||sid!==state.session?.id||!$("report-draft-dialog").open)return;
    reportDraft=draft;reportDraftSession=sid;$("report-draft-title").textContent=draft.title;$("report-draft-body").textContent=draft.body;$("report-draft-preview").hidden=false;$("report-draft-status").textContent="초안 · 적용 후 자유롭게 수정하세요.";
  }catch(error){if(sid===state.session?.id)$("report-draft-status").textContent=error.name==="AbortError"?"중단했어요.":error.message;}
  finally{reportDraftRunning=false;$("report-draft-stop").hidden=true;if(generation===uiGeneration)busy(false);}
});
$("report-draft-stop").addEventListener("click",cancelActiveRequest);
$("report-draft-dialog").addEventListener("close",()=>{if(reportDraftRunning)cancelActiveRequest();reportDraft=null;});
$("apply-report-draft").addEventListener("click",()=>{if(!reportDraft||reportDraftSession!==state.session?.id)return;const document=reportDocuments.get(reportDraftSession);document.title=reportDraft.title;document.body=reportDraft.body;document.dirty=true;paintReport(document);$("report-draft-dialog").close();$("report-document-body").focus();});
