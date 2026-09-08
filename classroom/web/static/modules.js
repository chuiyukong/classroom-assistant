/* ES5 / local XHR only. Module pages have separate state from seat editing. */
(function () {
  'use strict';
  var teacher = document.body.getAttribute('data-teacher') === 'yes';
  var module = document.body.getAttribute('data-module'), state = null, arrangement = null;
  var historyId = '', correctionId = '', correctionLesson = '', recycled = false, drawing = false, busy = false;
  var moduleConnected = false;
  var polling = false, selectedSeat = null, checkinLesson = null, serverOffset = 0, lastRequests = '';
  var seatMap = el('attendance-map') ? new window.ClassroomSeatMap(el('attendance-map'), function(n){ if(!teacher){showCheckin(n);} }) : null;
  var labels = {pending:'未签到', present:'已到', late:'迟到', leave:'请假', absent:'缺勤', long_leave:'长期请假'};
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
    api(method || 'POST', path, data, function (err, d) { busy = false; message(err || '已保存'); if (!err && cb) { cb(d); } refresh(); });
  }
  function time(s) { return s ? new Date(s).toLocaleString() : ''; }
  var links = document.querySelectorAll('.module-nav a');
  for (var i = 0; i < links.length; i++) { if (links[i].getAttribute('href') === window.location.pathname) { links[i].className = 'current'; } }
  function map(entries) {
    if (!seatMap || !state) { return; }
    seatMap.layout(state.layout);
    seatMap.update(entries, {disabled:state.disabled_seats || [], teacher:teacher, rollcall:module==='rollcall', attendance:!!(state.lesson && state.lesson.attendance_started_at), blocked:teacher || !canCheckin()});
  }
  function canCheckin() {
    var l=state && state.lesson;
    return !!(moduleConnected && l && l.attendance_started_at && !l.attendance_closed_at && !state.my_student_id);
  }
  function countdown() {
    if(!el('countdown')) { return; }
    var l=state && state.lesson;
    if(!l || !l.attendance_started_at){put('countdown','签到未开放');el('countdown').className='operation-status is-closed';return;}
    var seconds=l.attendance_deadline ? Math.ceil((new Date(l.attendance_deadline).getTime()-Date.now()-serverOffset)/1000) : null;
    var late=seconds!==null && seconds<=0, span=Math.abs(seconds||0);
    var clock=('0'+Math.floor(span/60)).slice(-2)+':'+('0'+span%60).slice(-2);
    put('countdown',l.attendance_closed_at ? '签到已结束' : (late ? '迟到签到开放 · 已超时 '+clock : (seconds===null ? '签到开放中' : '签到开放中 · 签到剩余 '+clock)));
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
  function render(d) {
    var previous = state && state.lesson ? state.lesson.id : null;
    state = d; var l = d.lesson, live = !!(l && d.is_current);
    if(d.server_time){serverOffset=new Date(d.server_time).getTime()-Date.now();}
    if(!teacher && checkinLesson && (!l || l.id!==checkinLesson)){closeCheckin();}
    if(teacher && module==='rollcall'){
      put('lesson-info', l ? l.class_name + ' · 本节课堂' : '请先开始本节课');
      el('draw-button').disabled=!live || drawing;
      put('draw-source',l && l.attendance_started_at ? '仅点名已签到学生' : '使用座位名单');
      if(previous!==(l?l.id:null)){seatMap.highlight(null);put('draw-name','准备点名');put('draw-history','');}
      map(d.entries||[]);return;
    }
    countdown();
    if (previous !== (l ? l.id : null) && el('correction-panel')) { el('correction-panel').hidden = true; correctionId = ''; }
    if (teacher) {
      put('lesson-info', l ? (live ? '本节课堂' : '历史课堂 · 只读') + ' · ' + l.class_name + ' · ' + time(l.started_at) + (l.attendance_started_at ? (l.attendance_closed_at ? ' · 签到已结束' : ' · 签到开放中') : ' · 未发起签到') : '尚未开始本节课');
      el('open-attendance').disabled = !live || !!l.attendance_started_at;
      el('close-attendance').disabled = !live || !l.attendance_started_at || !!l.attendance_closed_at;
      el('end-lesson').disabled = !live;
      var summary = el('attendance-summary'); summary.textContent = '';
      if (l) {
        [['expected','应到'],['actual','实到'],['pending','未签到'],['leave','请假'],['long_leave','长期请假'],['absent','缺勤'],['late','迟到']].forEach(function (pair) { var n = make('div', '', 'summary-card'); n.appendChild(make('strong', String(d.counts[pair[0]]))); n.appendChild(make('span', pair[1])); summary.appendChild(n); });
      }
      put('missing-names', l && l.attendance_started_at ? '尚未到场：' + (d.entries.filter(function (r) { return r.status !== 'present' && r.status !== 'late'; }).map(function (r) { return r.name + '（' + labels[r.status] + '）'; }).join('、') || '全部到齐') : '尚未开展考勤');
      el('attendance-export').hidden = !l; if (l) { el('attendance-export').href = '/api/v1/teacher/lessons/' + l.id + '/export'; }
      var rows = el('attendance-rows'); rows.textContent = '';
      (d.entries || []).forEach(function (r) {
        var tr = make('tr'); [r.name, r.original_seat + ' → ' + (r.seat_no || '—'), l && l.attendance_started_at ? labels[r.status] : '未开展', r.late_seconds ? Math.ceil(r.late_seconds / 60) + ' 分钟' : '—'].forEach(function (s) { tr.appendChild(make('td', s)); });
        var td = make('td'), b = make('button', '纠正 / 补签', 'secondary'); b.disabled = !live || !l.attendance_started_at;
        b.onclick = function () { correctionId = r.student_id; correctionLesson = l.id; put('correction-name', r.name + ' · 原座位 ' + r.original_seat); el('correction-status').value = r.status === 'late' ? 'present' : r.status; el('correction-seat').value = r.seat_no || r.original_seat; el('correction-panel').hidden = false; el('correction-panel').scrollIntoView(); }; td.appendChild(b); tr.appendChild(td); rows.appendChild(tr);
      }); map(d.entries || []);
      var signature=JSON.stringify(d.change_requests||[])+live;
      if(signature!==lastRequests){lastRequests=signature;el('change-requests').textContent='';
        (d.change_requests||[]).forEach(function(q){var row=make('div','','change-request');row.appendChild(make('span',q.name+' · '+q.from_seat+' → '+q.to_seat+' · '+({pending:'待审批',approved:'已同意',rejected:'已拒绝',cancelled:'已取消'}[q.status])));
          if(q.status==='pending' && live){[true,false].forEach(function(yes){var b=make('button',yes?'同意长期换座':'拒绝','secondary');b.onclick=function(){if(yes && !confirm('同意 '+q.name+' 长期换至 '+q.to_seat+' 号？将修改当前座位，历史不变。')){return;}save('teacher/seat-changes/'+q.id,{approve:yes});};row.appendChild(b);});}el('change-requests').appendChild(row);});
        if(!(d.change_requests||[]).length){put('change-requests','暂无申请');}}
    } else {
      el('checkin-button').disabled=!canCheckin() || busy;
      put('checkin-status',d.my_student_id ? '签到成功' : (canCheckin() ? '点击座位，输入姓名签到' : '签到未开放'));
      map(d.entries||[]); countdown();
    }
  }
  function refresh() {
    if (module === 'data' || polling) { return; }
    polling = true;
    var requested = historyId;
    api('GET', teacher ? (historyId ? 'teacher/lessons/' + historyId : 'teacher/lessons/current') : 'student/attendance', null, function (err, d) {
      polling = false; moduleConnected=!err;
      if (requested !== historyId) { return; }
      put('module-connection', err ? '状态：连接中断' : '状态：已连接');
      el('module-connection').className='connection'+(err?' offline':'');
      if (!err) { render(d); } else {
        if(state){map(state.entries||[]);}
        ['open-attendance','close-attendance','end-lesson','draw-button','checkin-button'].forEach(function (id) { if (el(id)) { el(id).disabled = true; } });
      }
    });
  }
  function context() {
    api('GET', teacher ? 'teacher/current' : 'student/state', null, function (err, d) {
      if (!err) { arrangement = d; put('active-class',d['class'] ? d['class'].name : '未选择上课班级'); if(!teacher){el('seating-nav').hidden=!(d.round && d.round.is_open);} }
    });
  }
  if (module === 'data') {
    var classData=[];
    function renderClasses(){el('class-list').textContent='';classData.filter(function(c){return (!el('filter-year').value || String(c.year)===el('filter-year').value) && (!el('filter-semester').value || (c.semester||'unset')===el('filter-semester').value);}).forEach(function(c){var label=make('label','','class-choice'),check=document.createElement('input');check.type='checkbox';check.value=c.id;label.appendChild(check);label.appendChild(make('span',c.name+' · '+(c.year?c.year+'年 '+c.semester:'未设置学期')));el('class-list').appendChild(label);});}
    el('filter-year').onchange=renderClasses;el('filter-semester').onchange=renderClasses;
    function classes() {
      api('GET', 'teacher/classes' + (recycled ? '?deleted=1' : ''), null, function (err, d) {
        if (err) { message(err); return; } put('module-connection', recycled ? '回收站 · 可以恢复' : '在用班级'); el('class-list').textContent = '';
        classData=d.classes;var selectedYear=el('filter-year').value;el('filter-year').textContent='';var all=make('option','全部年份');all.value='';el('filter-year').appendChild(all);var years=[];d.classes.forEach(function(c){if(years.indexOf(c.year)===-1){years.push(c.year);var o=make('option',c.year?c.year+'年':'未设置');o.value=String(c.year);el('filter-year').appendChild(o);}});el('filter-year').value=years.indexOf(Number(selectedYear))!==-1?selectedYear:'';renderClasses();
        put('manage-selected', recycled ? '恢复所选班级' : '删除所选班级');
      });
    }
    el('show-live').onclick = function () { recycled = false; classes(); }; el('show-deleted').onclick = function () { recycled = true; classes(); };
    el('select-all').onclick = function () { var checks = el('class-list').querySelectorAll('input'); var all = Array.prototype.every.call(checks, function (c) { return c.checked; }); Array.prototype.forEach.call(checks, function (c) { c.checked = !all; }); };
    el('manage-selected').onclick = function () { var ids = [], names = []; Array.prototype.forEach.call(el('class-list').querySelectorAll('input:checked'), function (c) { ids.push(c.value); names.push(c.parentNode.textContent); }); if (!ids.length) { message('请先选择班级'); return; } if (!confirm((recycled ? '恢复' : '移入回收站并结束相关登记和课堂') + '：\n' + names.join('\n'))) { return; } save('teacher/classes/manage', {ids:ids, action: recycled ? 'restore' : 'delete'}, 'POST', function () { classes(); context(); }); };
    classes(); context(); return;
  }
  if (teacher) {
    el('new-lesson').onclick = function () {
      if (!arrangement || !arrangement.round) { message('请先在在线选座中选择上课班级并完成登记'); return; }
      if (!confirm('开始新的一节课？上一节日志将转为只读，本节使用当前座位名单，不沿用上一节签到。')) { return; }
      save('teacher/lessons', {round_id: arrangement.round.id, late_after: 5}, 'POST', function () { historyId = ''; put('draw-name','准备点名'); put('draw-history',''); });
    };
    [['open-attendance','open'],['close-attendance','close'],['end-lesson','end']].forEach(function (pair) { if(!el(pair[0])){return;} el(pair[0]).onclick = function () { if (!state || !state.lesson) { return; } if (pair[1] !== 'open' && !confirm('确认结束？未签到人员会记为缺勤；结束本节课后日志只读。')) { return; } save('teacher/lessons/' + state.lesson.id + '/' + pair[1], pair[1]==='open' ? {duration_minutes:Number(el('attendance-duration').value)} : {}); }; });
    if (module === 'attendance') {
      el('correction-form').onsubmit = function (e) { e.preventDefault(); if (!correctionId) { return; } save('teacher/lessons/' + correctionLesson + '/students/' + correctionId, {status:el('correction-status').value, seat_no:Number(el('correction-seat').value)}, 'PUT', function () { el('correction-panel').hidden = true; }); };
      api('GET','teacher/classes',null,function(err,d){ if (!err) { d.classes.forEach(function(c){var o=make('option',c.name);o.value=c.id;el('history-class').appendChild(o);}); } });
      el('history-search').onclick = function () {
        var query = [], cid = el('history-class').value, day = el('history-day').value;
        if (cid) { query.push('class_id=' + encodeURIComponent(cid)); } if (day) { query.push('day=' + encodeURIComponent(day)); }
        api('GET','teacher/lessons?' + query.join('&'),null,function(err,d){ if(err){message(err);return;} el('history-results').textContent=''; d.lessons.forEach(function(l){var b=make('button',l.class_name+' · '+time(l.started_at)+(l.ended_at?' · 已结束':' · 课堂记录'),'secondary history-item');b.onclick=function(){historyId=l.id;refresh();};el('history-results').appendChild(b);}); if(!d.lessons.length){put('history-results','没有符合条件的日志');} });
      };
      el('history-current').onclick = function () { historyId = ''; refresh(); };
    } else {
      el('draw-button').onclick = function () {
        if(drawing || !state || !state.lesson){return;} drawing=true;el('draw-button').disabled=true;
        var lid=state.lesson.id, entries=state.entries.filter(function(r){return !state.lesson.attendance_started_at || r.status==='present' || r.status==='late';});
        var reduced=window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        function flash(){if(!entries.length){return;}var r=entries[Math.floor(Math.random()*entries.length)];seatMap.highlight(state.lesson.attendance_started_at?r.seat_no:r.original_seat);put('draw-name',r.name);}
        var animation=reduced?null:setInterval(flash,110);
        api('POST','teacher/rollcall/'+lid,{},function(err,d){setTimeout(function(){clearInterval(animation);drawing=false;
          if(!state.lesson || state.lesson.id!==lid){seatMap.highlight(null);put('draw-name','课堂已切换');refresh();return;}
          if(err){message(err);put('draw-name','未抽取');seatMap.highlight(null);}else{put('draw-name',d.name);seatMap.highlight(d.seat_no);api('GET','teacher/rollcall/'+lid,null,function(e,result){if(!e){put('draw-history','本节已点名：'+result.draws.map(function(r){return r.name;}).join('、'));}});}refresh();},reduced?0:1200);});
      };
    }
  } else {
    el('checkin-close').onclick=closeCheckin;el('checkin-name').oninput=moveReason;
    document.addEventListener('keydown',function(e){if(el('checkin-dialog').hidden){return;}if(e.keyCode===27){closeCheckin();}if(e.keyCode===9){var nodes=Array.prototype.filter.call(el('checkin-dialog').querySelectorAll('input,button'),function(n){return !n.disabled && n.offsetParent!==null;});var index=nodes.indexOf(document.activeElement),next=(index+(e.shiftKey?-1:1)+nodes.length)%nodes.length;e.preventDefault();nodes[next].focus();}});
    el('checkin-form').onsubmit=function(e){e.preventDefault();if(busy || !selectedSeat || !canCheckin()){return;}
      var radio=document.querySelector('input[name="move-reason"]:checked');var reason=el('move-reasons').hidden?'':(radio?radio.value:'');
      if(!el('move-reasons').hidden && !reason){put('checkin-error','请选择换座原因');return;}
      busy=true;el('checkin-button').disabled=true;
      api('POST','student/attendance',{lesson_id:checkinLesson,name:el('checkin-name').value,seat_no:selectedSeat,move_reason:reason},function(err){busy=false;if(err){put('checkin-error',err);}else{closeCheckin();message(reason==='long_term'?'签到成功，长期换座申请已提交':'签到成功');}refresh();});
    };
  }
  context(); refresh(); setInterval(refresh, 1000); setInterval(context, 3000); setInterval(countdown,250);
}());
