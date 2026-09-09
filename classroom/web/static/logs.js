/* Read-only lesson queries; never changes attendance or fixed seating. ES5. */
(function(){
  'use strict';
  var classes=[], lessons=[], detail=null, events=[], teaching=false, querySerial=0, detailSerial=0;
  var labels={pending:'未签到',present:'已签到',late:'迟到 · 已签到',leave:'请假',long_leave:'长期请假',absent:'缺勤'};
  function el(id){return document.getElementById(id);}
  function put(id,text){el(id).textContent=text;}
  function time(value){return value?new Date(value).toLocaleString():'尚未下课';}
  function option(id,value,text){var node=document.createElement('option');node.value=value;node.textContent=text;el(id).appendChild(node);}
  function get(path,cb){var x=new XMLHttpRequest();x.open('GET','/api/v1/teacher/'+path,true);x.timeout=12000;x.onload=function(){var data;try{data=JSON.parse(x.responseText);}catch(e){cb('服务器响应异常');return;}cb(x.status===200?null:(data.error?data.error.message:'查询失败'),data);};x.onerror=x.ontimeout=function(){cb('连接中断，请重新查询');};x.send();}
  var map=new window.ClassroomSeatMap(el('log-map'),function(n){
    if(!detail){return;}var matches=detail.entries.filter(function(r){return r.seat_no===n;}),fixed=detail.entries.filter(function(r){return r.original_seat===n;}),r=matches[0]||fixed[0];
    if(!r){put('log-student-detail','空位');return;}
    var text=r.name+' · '+labels[r.status]+' · 实际座位：'+(r.seat_no||'未签到');
    if(teaching){text+='。教学数据模块尚未开发；未来在此查看该学生本节课的数据。';}
    else {text+=' · 签到时间：'+(r.signed_at?time(r.signed_at):'未签到')+' · 学生机 IP：'+(r.source_ip||'未获取（教师补签或未签到）');
      var history=events.filter(function(e){return e.student_id===r.student_id;});
      if(history.length){text+='。设备与纠正记录：'+history.map(function(e){return time(e.created_at)+' '+({checkin:'学生签到',teacher_checkin:'教师补签',mark_pending:'撤销签到',mark_absent:'标记缺勤',mark_leave:'标记请假',mark_long_leave:'标记长期请假'}[e.action]||e.action)+' '+(e.seat_no?e.seat_no+'号 ':'')+(e.source_ip||'未获取IP');}).join('；');}}
    put('log-student-detail',text);
  });
  function filteredClasses(){return classes.filter(function(c){return (!el('log-graduation').value||String(c.graduation_year||'unset')===el('log-graduation').value)&&(!el('log-year').value||String(c.year)===el('log-year').value)&&(!el('log-semester').value||c.semester===el('log-semester').value);});}
  function classOptions(){var selected=el('log-class').value;el('log-class').textContent='';option('log-class','','全部班级');filteredClasses().forEach(function(c){option('log-class',c.id,c.name+' · '+(c.graduation_year?c.graduation_year+'届':'未设置届数')+' · '+(c.year?c.year+'年 '+c.semester:'未设置学期')+(c.deleted_at?' · 回收站':''));});el('log-class').value=filteredClasses().some(function(c){return c.id===selected;})?selected:'';}
  function loadClasses(){el('log-search').disabled=true;get('classes',function(err,live){if(err){put('log-message',err);return;}get('classes?deleted=1',function(error,deleted){if(error){put('log-message',error);return;}classes=live.classes.concat(deleted.classes);['graduation','year'].forEach(function(key){var id='log-'+key,previous=el(id).value,values=[];el(id).textContent='';option(id,'',key==='graduation'?'全部届数':'全部年份');classes.forEach(function(c){var v=key==='graduation'?String(c.graduation_year||'unset'):String(c.year);if(values.indexOf(v)===-1){values.push(v);option(id,v,v==='unset'||v==='0'?'未设置':v);}});el(id).value=values.indexOf(previous)===-1?'':previous;});classOptions();el('log-search').disabled=false;});});}
  function render(){if(!detail){return;}var l=detail.lesson;put('log-title',l.class_name+' · '+(teaching?'教学日志':'考勤日志'));put('log-times','上课：'+time(l.started_at)+' · 下课：'+time(l.ended_at));put('log-counts',l.attendance_started_at?'应到 '+detail.counts.expected+' · 实到 '+detail.counts.actual+' · 缺勤 '+detail.counts.absent+' · 请假 '+(detail.counts.leave+detail.counts.long_leave):'本节课未开展考勤');el('log-export').href='/api/v1/teacher/lessons/'+l.id+'/export';el('log-export').hidden=teaching;put('log-help',teaching?'教学数据模块预留：点击学生座位查看入口，尚未采集其他教学数据。':'鼠标指向座位查看签到时间；点击座位查看签到与设备记录。');map.layout(detail.layout);map.update(detail.entries,{teacher:true,log:true,disabled:[],blocked:false});put('log-student-detail','');el('log-view').hidden=false;}
  function tab(value){teaching=value;el('attendance-log-tab').className='secondary'+(!value?' current':'');el('teaching-log-tab').className='secondary'+(value?' current':'');render();}
  el('attendance-log-tab').onclick=function(){tab(false);};el('teaching-log-tab').onclick=function(){tab(true);};
  ['graduation','year','semester'].forEach(function(key){el('log-'+key).onchange=classOptions;});
  el('log-search').onclick=function(){var serial=++querySerial;++detailSerial;detail=null;el('log-view').hidden=true;var params=[],cid=el('log-class').value,day=el('log-day').value,ids=filteredClasses().map(function(c){return c.id;});if(cid){params.push('class_id='+encodeURIComponent(cid));}if(day){params.push('day='+encodeURIComponent(day));}get('lessons?'+params.join('&'),function(err,d){if(serial!==querySerial){return;}if(err){put('log-message',err);return;}lessons=d.lessons.filter(function(l){return ids.indexOf(l.class_id)!==-1;});el('log-lesson').textContent='';option('log-lesson','','请选择一节课');lessons.forEach(function(l){option('log-lesson',l.id,l.class_name+' · '+time(l.started_at)+' — '+time(l.ended_at));});put('log-message','找到 '+lessons.length+' 节课');});};
  el('log-lesson').onchange=function(){var id=this.value,serial=++detailSerial;el('log-view').hidden=true;if(!id){detail=null;return;}get('lessons/'+id,function(err,d){if(serial!==detailSerial){return;}if(err){put('log-message',err);return;}detail=d;events=[];render();get('lessons/'+id+'/events',function(error,data){if(serial!==detailSerial){return;}if(error){put('log-message',error);return;}events=data.events;});});};
  window.addEventListener('classes-updated',loadClasses);loadClasses();
}());
