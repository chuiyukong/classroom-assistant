/* Only this student's short-lived announcement is returned by the server. ES5. */
(function(){
  'use strict';
  var failures=0,nextPoll=0,busy=false,last='',hideTimer=null;
  try{last=sessionStorage.getItem('classroom-last-draw')||'';}catch(e){}
  var panel=document.createElement('div');panel.className='rollcall-popup';panel.hidden=true;panel.setAttribute('role','status');panel.setAttribute('aria-live','assertive');
  var content=document.createElement('div'),title=document.createElement('p'),name=document.createElement('strong'),hint=document.createElement('small');
  title.textContent='请你回答';hint.textContent='5 秒后自动关闭';content.appendChild(title);content.appendChild(name);content.appendChild(hint);panel.appendChild(content);document.body.appendChild(panel);
  function poll(){
    if(busy || Date.now()<nextPoll){return;}busy=true;var x=new XMLHttpRequest();x.open('GET','/api/v1/student/rollcall',true);x.timeout=4000;
    x.onload=function(){busy=false;failures=x.status===200?0:Math.min(4,failures+1);nextPoll=Date.now()+(failures?Math.pow(2,failures)*1000:1300)+Math.random()*250;if(x.status!==200){return;}var d;try{d=JSON.parse(x.responseText);}catch(e){return;}var a=d.announcement;if(!a||a.id===last){return;}last=a.id;try{sessionStorage.setItem('classroom-last-draw',last);}catch(e){}name.textContent=a.name;panel.hidden=false;clearTimeout(hideTimer);hideTimer=setTimeout(function(){panel.hidden=true;},5000);};
    x.onerror=x.ontimeout=function(){busy=false;failures=Math.min(4,failures+1);nextPoll=Date.now()+Math.pow(2,failures)*1000;};x.send();
  }
  poll();setInterval(poll,700);
}());
