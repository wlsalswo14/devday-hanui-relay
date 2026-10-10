"use strict";
self.addEventListener('push',event=>{
  let data;try{data=event.data.json();}catch{return;}
  const url=new URL(data.url||'/',self.location.origin);
  if(url.origin!==self.location.origin)return;
  event.waitUntil(self.registration.showNotification('Hanui',{body:data.body||'관리 내용을 확인해 주세요.',tag:data.tag||'hanui',data:{url:url.href},icon:'/favicon.svg'}));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil((async()=>{const url=new URL(event.notification.data?.url||'/',self.location.origin);if(url.origin!==self.location.origin)return;
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    // Do not navigate an open conversation or interrupt an in-progress reply.
    const current=windows.find(client=>client.url===url.href);if(current){await current.focus();return;}
    await self.clients.openWindow(url.href);
  })());
});
