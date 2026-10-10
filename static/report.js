"use strict";
const reportDocuments=new Map();
let reportSession=null,reportLoad=0;
function paintReport(document){
  $("report-document-title").value=document.title;$("report-document-body").value=document.body;
  $("report-document-title").disabled=false;$("report-document-body").disabled=false;$("save-report").disabled=false;$("print-report").disabled=false;
  $("report-state").textContent=document.dirty?"미저장":document.revision?"저장됨":"";
}
async function loadReport(){
  if(!state.session)return;
  const sid=state.session.id;
  if(reportSession===sid)return;
  reportSession=sid;const generation=++reportLoad;
  if(reportDocuments.has(sid)){paintReport(reportDocuments.get(sid));return;}
  $("report-document-title").value="";$("report-document-body").value="";
  $("report-document-title").disabled=true;$("report-document-body").disabled=true;$("save-report").disabled=true;$("print-report").disabled=true;$("report-state").textContent="불러오는 중…";
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
