/* ES5 / local XHR only. Module pages have separate state from seat editing. */
(function () {
  'use strict';
  var teacher = document.body.getAttribute('data-teacher') === 'yes';
  var module = document.body.getAttribute('data-module'), state = null, arrangement = null;
  var historyId = '', correctionId = '', correctionLesson = '', recycled = false, drawing = false, busy = false;
  var moduleConnected = false, drawScope='all', correctionEmptySeat=null, rangeRevision=0;
  var contextBusy=false, contextNext=0, pollNext=0, failures=0, polling = false, selectedSeat = null, checkinLesson = null, serverOffset = 0, lastRequests = '';
  var seatMap = el('attendance-map') ? new window.ClassroomSeatMap(el('attendance-map'), function(n){ if(!teacher){showCheckin(n);}else if(module==='attendance'){showCorrection(n);}else if(module==='rollcall'){toggleDrawStudent(n);} }) : null;
  var labels = {pending:'未签到', present:'已到', late:'迟到', leave:'请假', absent:'缺勤', long_leave:'长期请假'};
  ['new-lesson','open-attendance','close-attendance','end-lesson','draw-button','checkin-button'].forEach(function(id){if(el(id)){el(id).disabled=true;}});
  function el(id) { return document.getElementById(id); }
  function put(id, s) { if (el(id)) { el(id).textContent = s; } }
  function make(tag, text, cls) { var n = document.createElement(tag); n.textContent = text || ''; n.className = cls || ''; return n; }
  function message(s) { put('module-message', s); }
  function api(method, path, data, cb) {
    var x = new XMLHttpRequest(); x.open(method, '/api/v1/' + path, true); x.timeout = 12000;
    if (method !== 'GET') { x.setRequestHeader('Content-Type', 'application/json'); x.setRequestHeader('X-CSRF-Token', document.querySelector('meta[name="csrf-token"]').getAttribute('content')); }
    x.onload = function () { var d; try { d = JSON.parse(x.responseText); } catch (e) { cb('服务器响应异常'); return; } cb(x.status >= 200 && x.status < 300 ? null : (d.error ? d.error.message : '操作失败'), d); };
    x.onerror = x.ontimeout = function () { cb('连接中断，请检查教师机；重新连接后核对结果。'); };
    x.send(method === 'GET' ? null : JSON.stringify(data));
  }
  function save(path, data, method, cb) {
    if (busy) { return; } busy = true;
    api(method || 'POST', path, data, function (err, d) { busy = false; message(err || '已保存'); if(el('correction-error')){put('correction-error',err||'');} if (!err && cb) { cb(d); } refresh(); });
  }
  function time(s) { return s ? new Date(s).toLocaleString() : ''; }
  var links = document.querySelectorAll('.module-nav a');
  for (var i = 0; i < links.length; i++) { if (links[i].getAttribute('href') === window.location.pathname) { links[i].className = 'current'; } }
  function map(entries) {
    if (!seatMap || !state) { return; }
    seatMap.layout(state.layout);
    seatMap.update(entries, {disabled:state.disabled_seats || [], teacher:teacher, rollcall:module==='rollcall', attendance:state.source==='attendance' || !!(state.lesson && state.lesson.attendance_started_at), manual:module==='rollcall' && drawScope==='manual' && !drawing,selected:drawScope==='manual'?state.selected_ids:[],blocked:teacher ? (module==='rollcall' ? (!moduleConnected || drawing) : !(state.is_current && state.lesson && state.lesson.attendance_started_at)) : !canCheckin()});
  }
  function toggleDrawStudent(n){
    if(drawScope!=='manual' || drawing || busy || !state){return;}
    var rows=state.entries.filter(function(r){return (state.source==='attendance'?r.seat_no:r.original_seat)===n;});
    if(!rows.length){return;}var selected=(state.selected_ids||[]).slice(),id=rows[0].student_id,index=selected.indexOf(id);
    if(index===-1){selected.push(id);}else{selected.splice(index,1);}
    rangeRevision++;save('teacher/rollcall/selection',{context_id:state.context_id,student_ids:selected},'PUT',function(d){if(state && state.context_id===d.context_id){render(d);}});
  }
  function canCheckin() {
    var l=state && state.lesson;
    return !!(moduleConnected && l && l.attendance_started_at && (!l.attendance_closed_at || state.recheckin_available) && !state.my_student_id);
  }
  function countdown() {
    if(!el('countdown')) { return; }
    var l=state && state.lesson;
    if(!l || !l.attendance_started_at){put('countdown','签到未开放');el('countdown').className='operation-status is-closed';return;}
    if(!teacher && state.my_student_id){put('countdown','已签到');el('countdown').className='operation-status is-open';return;}
    if(!teacher && l.attendance_closed_at && state.recheckin_available){put('countdown','指定学生可重新签到');el('countdown').className='operation-status is-open';return;}
    var seconds=l.attendance_deadline ? Math.ceil((new Date(l.attendance_deadline).getTime()-Date.now()-serverOffset)/1000) : null;
    var late=seconds!==null && seconds<=0, span=Math.abs(seconds||0);
    var clock=('0'+Math.floor(span/60)).slice(-2)+':'+('0'+span%60).slice(-2);
    put('countdown',l.attendance_closed_at ? '签到已结束' : (late ? '签到超时：'+clock : (seconds===null ? '签到开放中' : '签到剩余 '+clock)));
    el('countdown').className='operation-status '+(l.attendance_closed_at?'is-closed':(late?'is-late':'is-open'));

  }
  function closeCheckin() { if(busy){return;} el('checkin-dialog').hidden=true; if(selectedSeat && seatMap.buttons[selectedSeat]){seatMap.buttons[selectedSeat].focus();} selectedSeat=null; }
  function showCheckin(n) {
    if(!canCheckin() || busy){return;} selectedSeat=n;checkinLesson=state.lesson.id;
    put('checkin-title',n+' 号座位签到');el('checkin-name').value='';el('move-reasons').hidden=true;
    Array.prototype.forEach.call(document.querySelectorAll('input[name="move-reason"]'),function(r){r.checked=false;});
    put('checkin-error','');el('checkin-dialog').hidden=false;el('checkin-name').focus();
  }
  function moveReason() {
    var typed=el('checkin-name').value.replace(/\s/g,'').toLowerCase();
    var matches=(state.entries||[]).filter(function(r){return r.name.replace(/\s/g,'').toLowerCase()===typed;});
    el('move-reasons').hidden=!(matches.length===1 && matches[0].original_seat!==selectedSeat);
  }
  function showCorrection(number) {
    if(!state || !state.lesson || !state.is_current || !state.lesson.attendance_started_at){return;}
    correctionLesson=state.lesson.id;
    var actual=state.entries.filter(function(r){return r.seat_no===number;}),fixed=state.entries.filter(function(r){return r.original_seat===number;});
    var r=actual[0]||fixed[0]||state.entries[0];if(!r){return;}
    var select=el('correction-student');select.textContent='';
    state.entries.forEach(function(item){var o=make('option',item.name+' · '+item.original_seat+'号');o.value=item.student_id;select.appendChild(o);});
    correctionEmptySeat=actual.length||fixed.length?null:number;select.value=r.student_id;loadCorrection();
    put('correction-error','');put('correction-name',number+'号 · 考勤纠正');el('correction-panel').hidden=false;select.focus();
  }
  function loadCorrection(){
    var r=state.entries.filter(function(item){return item.student_id===el('correction-student').value;})[0];if(!r){return;}
    correctionId=r.student_id;el('correction-status').value=r.status==='late'?'present':r.status;el('correction-seat').value=correctionEmptySeat||r.seat_no||r.original_seat;
    put('correction-detail',labels[r.status]+(r.late_seconds?' · 迟到 '+r.late_seconds+' 秒':''));
  }
  function render(d) {
    var previous = state && state.lesson ? state.lesson.id : null;
    state = d; var l = d.lesson, live = !!(l && d.is_current);
    if(d.server_time){serverOffset=new Date(d.server_time).getTime()-Date.now();}
    if(!teacher && checkinLesson && (!l || l.id!==checkinLesson)){closeCheckin();}
    if(teacher && module==='rollcall'){
      el('draw-button').disabled=!d.candidate_count || drawing;
      put('draw-source','点名范围人数 · '+d.candidate_count+' 人'+(d.candidate_count===1?'（仅一人可选）':''));
      if(seatMap.contextId!==d.context_id){seatMap.contextId=d.context_id;seatMap.highlight(null);put('draw-name','准备点名');}
      map(d.entries||[]);return;
    }
    countdown();
    if (previous !== (l ? l.id : null) && el('correction-panel')) { el('correction-panel').hidden = true; correctionId = ''; }
    if (teacher) {
      put('lesson-info', l ? (live ? '本节课堂' : '历史课堂 · 只读') + ' · ' + l.class_name + ' · ' + time(l.started_at) + (l.attendance_started_at ? (l.attendance_closed_at ? ' · 签到已结束' : ' · 签到开放中') : ' · 未发起签到') : '当前未上课');
      el('open-attendance').disabled = !live || !!l.attendance_started_at;
      el('close-attendance').disabled = !live || !l.attendance_started_at || !!l.attendance_closed_at;
      var teaching=!!(l && !l.ended_at);el('end-lesson').disabled = !teaching;
      el('new-lesson').disabled=teaching || busy;put('new-lesson',teaching?'正在上课':'开始上课');el('new-lesson').className=teaching?'primary is-teaching':'primary';
      var summary = el('attendance-summary'); summary.textContent = '';
      if (l) {
        [['expected','应到'],['actual','实到'],['pending','未签到'],['leave','请假'],['long_leave','长期请假'],['absent','缺勤'],['late','迟到']].forEach(function (pair) { var n = make('div', '', 'summary-card'); n.appendChild(make('strong', String(d.counts[pair[0]]))); n.appendChild(make('span', pair[1])); summary.appendChild(n); });
      }
      put('missing-names', l && l.attendance_started_at ? '尚未到场：' + (d.entries.filter(function (r) { return r.status !== 'present' && r.status !== 'late'; }).map(function (r) { return r.name + '（' + labels[r.status] + '）'; }).join('、') || '全部到齐') : '尚未开展考勤');
      map(d.entries || []);
      var signature=JSON.stringify(d.change_requests||[])+live;
      if(signature!==lastRequests){lastRequests=signature;el('change-requests').textContent='';
        (d.change_requests||[]).forEach(function(q){var row=make('div','','change-request');row.appendChild(make('span',q.name+' '+(q.kind==='temporary'?'临时换座':'长期换座')+' · '+q.from_seat+' → '+q.to_seat+' · '+({pending:'待审批',approved:'已同意',rejected:'已拒绝',cancelled:'已取消'}[q.status])));
          if(q.status==='pending' && live){[true,false].forEach(function(yes){var b=make('button',yes?'同意':'拒绝','secondary');b.onclick=function(){if(yes && q.kind!=='temporary' && !confirm('同意 '+q.name+' 长期换至 '+q.to_seat+' 号？将修改当前座位，历史不变。')){return;}save('teacher/seat-changes/'+q.id,{approve:yes},'POST',function(result){if(result.fixed_updated){var link=el('move-saved-link');link.hidden=false;link.href='/teacher?class_id='+encodeURIComponent(result.class_id);link.textContent='固定座位已保存至 '+result.seat_no+' 号 · 查看当前座位';message('长期换座已保存，当前固定座位已更新');}});};row.appendChild(b);});}el('change-requests').appendChild(row);});
        if(!(d.change_requests||[]).length){put('change-requests','暂无申请');}}
    } else {
      el('checkin-button').disabled=!canCheckin() || busy;
      var own=(d.entries||[]).filter(function(r){return r.student_id===d.my_student_id;})[0];
      put('checkin-instruction','请按登记的座位就坐和签到，若设备异常请在空座位就坐签到。');
      if(own){var instruction=el('checkin-instruction');instruction.textContent='';instruction.appendChild(make('strong',own.name,'identity-chip'));instruction.appendChild(document.createTextNode('已在'+own.seat_no+'号座位签到。'));}
      put('checkin-status',d.my_student_id ? '' : (canCheckin() ? '点击座位，输入姓名签到' : '签到未开放'));
      map(d.entries||[]); countdown();
    }
  }
  function refresh() {
    if (module === 'data' || polling || Date.now()<pollNext) { return; }
    polling = true;
    var requested = historyId, requestedRange=rangeRevision, requestedScope=drawScope;
    api('GET', teacher ? (module==='rollcall' ? 'teacher/rollcall/current?scope='+encodeURIComponent(drawScope) : historyId ? 'teacher/lessons/' + historyId : 'teacher/lessons/current') : 'student/attendance', null, function (err, d) {
      polling = false; moduleConnected=!err;failures=err?Math.min(failures+1,4):0;pollNext=Date.now()+(err?Math.pow(2,failures)*1000:0)+Math.random()*200;
      if (requested !== historyId || requestedRange!==rangeRevision || requestedScope!==drawScope) { return; }
      put('module-connection', err ? '状态：连接中断' : '状态：已连接');
      el('module-connection').className='connection'+(err?' offline':'');
      if (!err) { render(d); } else {
        if(state){map(state.entries||[]);}
        ['open-attendance','close-attendance','end-lesson','draw-button','checkin-button'].forEach(function (id) { if (el(id)) { el(id).disabled = true; } });
      }
    });
  }
  function context() {
    if(contextBusy || Date.now()<contextNext){return;}contextBusy=true;
    api('GET', teacher ? 'teacher/current' : 'student/state', null, function (err, d) {
      contextBusy=false;contextNext=Date.now()+(err?6000:0)+Math.random()*300;
      if (!err) { arrangement = d; put('active-class',d['class'] ? d['class'].name : '未选择上课班级'); if(!teacher){el('seating-nav').hidden=!(d.round && d.round.is_open);if(d.round && d.round.is_open){window.location.replace('/');}} }
    });
  }
  window.addEventListener('classes-updated',function(){contextNext=0;context();});
  if (module === 'data') {
    var classData=[];
    function renderClasses(){el('class-list').textContent='';classData.filter(function(c){return (!el('filter-year').value || String(c.year)===el('filter-year').value) && (!el('filter-semester').value || (c.semester||'unset')===el('filter-semester').value);}).forEach(function(c){var label=make('label','','class-choice'),check=document.createElement('input');check.type='checkbox';check.value=c.id;label.appendChild(check);label.appendChild(make('span',c.name+' · '+c.student_count+' 人 · '+(c.graduation_year?c.graduation_year+'届':'未设置届数')+' · '+(c.year?c.year+'年 '+c.semester:'未设置学期')));var rename=make('input','','class-rename');rename.value=c.name;rename.maxLength=40;rename.setAttribute('aria-label',c.name+'班级名称');label.appendChild(rename);var grade=make('input','','grade-edit');grade.type='number';grade.min=1900;grade.max=2200;grade.value=c.graduation_year||'';grade.placeholder='毕业届数';grade.setAttribute('aria-label',c.name+'毕业届数');label.appendChild(grade);var update=make('button','保存名称和届数','secondary');update.type='button';update.onclick=function(e){e.preventDefault();save('teacher/classes/'+c.id,{name:rename.value,graduation_year:Number(grade.value)||0},'PUT',function(){classes();var event=document.createEvent('Event');event.initEvent('classes-updated',true,true);window.dispatchEvent(event);});};label.appendChild(update);el('class-list').appendChild(label);});}
    el('filter-year').onchange=renderClasses;el('filter-semester').onchange=renderClasses;
    function classes() {
      api('GET', 'teacher/classes' + (recycled ? '?deleted=1' : ''), null, function (err, d) {
        if (err) { message(err); return; } put('module-connection', recycled ? '回收站 · 可以恢复' : '在用班级'); el('class-list').textContent = '';
        classData=d.classes;var selectedYear=el('filter-year').value;el('filter-year').textContent='';var all=make('option','全部年份');all.value='';el('filter-year').appendChild(all);var years=[];d.classes.forEach(function(c){if(years.indexOf(c.year)===-1){years.push(c.year);var o=make('option',c.year?c.year+'年':'未设置');o.value=String(c.year);el('filter-year').appendChild(o);}});el('filter-year').value=years.indexOf(Number(selectedYear))!==-1?selectedYear:'';renderClasses();
        put('manage-selected', recycled ? '恢复所选班级' : '删除所选班级');
      });
    }
    el('show-live').onclick = function () { recycled = false; classes(); }; el('show-deleted').onclick = function () { recycled = true; classes(); };
    el('select-all').onclick = function () { var checks = el('class-list').querySelectorAll('input[type=checkbox]'); var all = Array.prototype.every.call(checks, function (c) { return c.checked; }); Array.prototype.forEach.call(checks, function (c) { c.checked = !all; }); };
    el('manage-selected').onclick = function () { var ids = [], names = []; Array.prototype.forEach.call(el('class-list').querySelectorAll('input[type=checkbox]:checked'), function (c) { ids.push(c.value); names.push(c.parentNode.textContent); }); if (!ids.length) { message('请先选择班级'); return; } if (!confirm((recycled ? '恢复' : '移入回收站并结束相关登记和课堂') + '：\n' + names.join('\n'))) { return; } save('teacher/classes/manage', {ids:ids, action: recycled ? 'restore' : 'delete'}, 'POST', function () { classes(); context(); }); };
    el('export-classes').onclick=function(){var ids=[];Array.prototype.forEach.call(el('class-list').querySelectorAll('input[type=checkbox]:checked'),function(c){ids.push(c.value);});if(!ids.length){message('请先选择班级');return;}window.location.href='/api/v1/teacher/classes/export-csv?ids='+encodeURIComponent(ids.join(','));};
    classes(); context(); return;
  }
  if (teacher) {
    if(el('new-lesson')){el('new-lesson').onclick = function () {
      if(busy || (state && state.lesson && !state.lesson.ended_at)){return;}
      if (!arrangement || !arrangement.round) { message('请先在在线选座中选择上课班级并完成登记'); return; }
      if (!confirm('确认开始上课？本节使用当前座位名单。')) { return; }
      save('teacher/lessons', {round_id: arrangement.round.id, late_after: 5}, 'POST', function () { historyId = ''; put('draw-name','准备点名'); put('draw-history',''); });
    };
    }
    [['open-attendance','open'],['close-attendance','close'],['end-lesson','end']].forEach(function (pair) { if(!el(pair[0])){return;} el(pair[0]).onclick = function () { if (!state || !state.lesson) { return; } if (pair[1] !== 'open' && !confirm('确认结束？未签到人员会记为缺勤；结束本节课后日志只读。')) { return; } save('teacher/lessons/' + state.lesson.id + '/' + pair[1], pair[1]==='open' ? {duration_minutes:Number(el('attendance-duration').value)} : {},'POST',function(){if(pair[1]==='end'){message('已下课，本节课堂日志已保存。');}}); }; });
    if (module === 'attendance') {
      el('correction-close').onclick=function(){el('correction-panel').hidden=true;};
      el('correction-student').onchange=loadCorrection;
      document.addEventListener('keydown',function(e){if(el('correction-panel').hidden){return;}if(e.keyCode===27){el('correction-panel').hidden=true;}if(e.keyCode===9){var nodes=Array.prototype.filter.call(el('correction-panel').querySelectorAll('select,input,button'),function(n){return !n.disabled && n.offsetParent!==null;});var index=nodes.indexOf(document.activeElement);e.preventDefault();nodes[(index+(e.shiftKey?-1:1)+nodes.length)%nodes.length].focus();}});
      el('correction-form').onsubmit = function (e) { e.preventDefault(); if (!correctionId) { return; } save('teacher/lessons/' + correctionLesson + '/students/' + correctionId, {status:el('correction-status').value, seat_no:Number(el('correction-seat').value)}, 'PUT', function () { el('correction-panel').hidden = true; }); };
      el('missing-toggle').onclick=function(){el('missing-names').hidden=!el('missing-names').hidden;put('missing-toggle',el('missing-names').hidden?'查询尚未到场':'收起尚未到场');};
    } else {
      el('draw-scope').onchange=function(){if(drawing){this.value=drawScope;return;}drawScope=this.value;refresh();};
      el('draw-button').onclick = function () {
        if(drawing || !state || !state.candidate_count){return;} drawing=true;el('draw-button').disabled=true;
        var contextId=state.context_id, scope=drawScope, entries=state.candidates.slice(), order=entries.slice(), index=0;
        for(var j=order.length-1;j>0;j--){var k=Math.floor(Math.random()*(j+1)),temp=order[j];order[j]=order[k];order[k]=temp;}
        el('draw-scope').disabled=true;put('draw-name','正在随机点名…');
        function finish(err,d){drawing=false;el('draw-scope').disabled=false;if(err){message(err);put('draw-name','未抽取');seatMap.highlight(null);}else{put('draw-name',d.name);seatMap.highlight(d.seat_no);}refresh();}
        function step(){
          if(!state || state.context_id!==contextId){finish('名单已切换，请重新点名');return;}
          if(index<order.length){seatMap.highlight(order[index++].seat_no);setTimeout(step,Math.max(16,Math.floor(1800/order.length)));return;}
          api('POST','teacher/rollcall/current',{context_id:contextId,scope:scope,candidate_ids:entries.map(function(r){return r.student_id;})},function(err,d){
            if(!state || state.context_id!==contextId){finish('名单已切换，请重新点名');return;}finish(err,d);
          });
        }
        step();
      };
    }
  } else {
    el('checkin-close').onclick=closeCheckin;el('checkin-name').oninput=moveReason;
    document.addEventListener('keydown',function(e){if(el('checkin-dialog').hidden){return;}if(e.keyCode===27){closeCheckin();}if(e.keyCode===9){var nodes=Array.prototype.filter.call(el('checkin-dialog').querySelectorAll('input,button'),function(n){return !n.disabled && n.offsetParent!==null;});var index=nodes.indexOf(document.activeElement),next=(index+(e.shiftKey?-1:1)+nodes.length)%nodes.length;e.preventDefault();nodes[next].focus();}});
    el('checkin-form').onsubmit=function(e){e.preventDefault();if(busy || !selectedSeat || !canCheckin()){return;}
      var radio=document.querySelector('input[name="move-reason"]:checked');var reason=el('move-reasons').hidden?'':(radio?radio.value:'');
      if(!el('move-reasons').hidden && !reason){put('checkin-error','请选择换座原因');return;}
      busy=true;el('checkin-button').disabled=true;
      api('POST','student/attendance',{lesson_id:checkinLesson,name:el('checkin-name').value,seat_no:selectedSeat,move_reason:reason},function(err){busy=false;if(err){put('checkin-error',err);}else{closeCheckin();message(reason?'签到成功，换座申请已提交':'签到成功');}refresh();});
    };
  }
  setTimeout(function(){context();refresh();},Math.random()*400); setInterval(refresh, 1000); setInterval(context, 3000); setInterval(countdown,250);
}());
