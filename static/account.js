"use strict";
let accountInfo=null;
async function prepareAccount(){
  const response=await fetch('/api/auth');
  if(!response.ok)throw new Error('로그인 상태를 확인하지 못했어요.');
  accountInfo=await response.json();
  if(!accountInfo.enabled)return true;
  const button=document.createElement('button');button.type='button';button.className='quiet account-control';
  button.textContent=accountInfo.user?accountInfo.user.name:'Google 로그인';
  document.getElementById('system-instructions-open').before(button);
  if(accountInfo.user){button.addEventListener('click',async()=>{
    cancelActiveRequest();
    try{const registration=await navigator.serviceWorker?.getRegistration();const subscription=await registration?.pushManager.getSubscription();if(subscription){await api('/api/notifications/unsubscribe',{method:'POST',body:JSON.stringify({endpoint:subscription.endpoint})});await subscription.unsubscribe();}
      await api('/api/auth/logout',{method:'POST',body:'{}'});location.reload();
    }catch(error){showError(error.message);}
  });return true;}
  const dialog=document.getElementById('account-dialog');dialog.showModal();
  dialog.addEventListener('cancel',event=>event.preventDefault());
  const script=document.createElement('script');script.src='https://accounts.google.com/gsi/client';script.async=true;
  script.onload=()=>{google.accounts.id.initialize({client_id:accountInfo.client_id,nonce:accountInfo.nonce,callback:async result=>{
    try{await api('/api/auth/login',{method:'POST',body:JSON.stringify({credential:result.credential})});location.reload();}
    catch(error){document.getElementById('account-status').textContent=error.message;}
  }});google.accounts.id.renderButton(document.getElementById('google-signin'),{type:'standard',theme:'outline',size:'large',text:'signin_with'});};
  script.onerror=()=>document.getElementById('account-status').textContent='Google 로그인 화면을 불러오지 못했어요. 새로고침해 주세요.';
  document.head.append(script);return false;
}
