/* ES5 / local XHR only. Module pages have separate state from seat editing. */
(function () {
  'use strict';
  var teacher = document.body.getAttribute('data-teacher') === 'yes';
  var module = document.body.getAttribute('data-module'), state = null, arrangement = null;
  var historyId = '', correctionId = '', correctionLesson = '', recycled = false, drawing = false, busy = false;
  var polling = false;
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
  function options(id, rows, valueKey, label) {
    var select = el(id), old = select.value; select.textContent = '';
    var blank = make('option', '请选择'); blank.value = ''; select.appendChild(blank);
    rows.forEach(function (r) { var o = make('option', label(r)); o.value = r[valueKey]; select.appendChild(o); });
    select.value = old;
  }
  var links = document.querySelectorAll('.module-nav a');
  for (var i = 0; i < links.length; i++) { if (links[i].getAttribute('href') === window.location.pathname) { links[i].className = 'current'; } }
  function map(entries) {
    if (!el('attendance-map')) { return; } var box = el('attendance-map'); box.textContent = '';
    for (var seat = 1; seat <= 64; seat++) {
      var names = entries.filter(function (r) { return r.seat_no === seat; });
      box.appendChild(make('div', seat + ' · ' + (names.length ? names[0].name : '无人签到'), 'attendance-tile' + (names.length ? ' present' : '')));
    }
  }
  function render(d) {
    var previous = state && state.lesson ? state.lesson.id : null;
    state = d; var l = d.lesson, live = !!(l && d.is_current);
    if (previous !== (l ? l.id : null) && el('correction-panel')) { el('correction-panel').hidden = true; correctionId = ''; }
    if (teacher) {
      put('lesson-info', l ? (live ? '本节课堂' : '历史课堂 · 只读') + ' · ' + l.class_name + ' · ' + time(l.started_at) + (l.attendance_started_at ? (l.attendance_closed_at ? ' · 签到已结束' : ' · 签到开放中') : ' · 未发起签到') : '尚未开始本节课');
      el('open-attendance').disabled = !live || !!l.attendance_started_at;
      el('close-attendance').disabled = !live || !l.attendance_started_at || !!l.attendance_closed_at;
      el('end-lesson').disabled = !live;
      if (module === 'rollcall') {
        el('draw-button').disabled = !live || drawing;
        put('draw-source', l && l.attendance_started_at ? '名单来源：本节课已到与迟到学生；未签到、请假和缺勤不参与。' : '名单来源：本节课堂的座位名单。');
        return;
      }
      var summary = el('attendance-summary'); summary.textContent = '';
      if (l) {
        [['expected','应到'],['actual','实到'],['pending','未签到'],['leave','请假'],['long_leave','长期请假'],['absent','缺勤'],['late','迟到']].forEach(function (pair) { var n = make('div', '', 'summary-card'); n.appendChild(make('strong', String(d.counts[pair[0]]))); n.appendChild(make('span', pair[1])); summary.appendChild(n); });
      }
      put('missing-names', l && l.attendance_started_at ? '尚未到场：' + (d.entries.filter(function (r) { return r.status !== 'present' && r.status !== 'late'; }).map(function (r) { return r.name + '（' + labels[r.status] + '）'; }).join('、') || '全部到齐') : '尚未开展考勤');
      el('attendance-export').hidden = !l; if (l) { el('attendance-export').href = '/api/v1/teacher/lessons/' + l.id + '/export'; }
      var rows = el('attendance-rows'); rows.textContent = '';
      (d.entries || []).forEach(function (r) {
        var tr = make('tr'); [r.name, r.original_seat + ' → ' + (r.seat_no || '—'), l.attendance_started_at ? labels[r.status] : '未开展', r.late_seconds ? Math.ceil(r.late_seconds / 60) + ' 分钟' : '—'].forEach(function (s) { tr.appendChild(make('td', s)); });
        var td = make('td'), b = make('button', '纠正 / 补签', 'secondary'); b.disabled = !live || !l.attendance_started_at;
        b.onclick = function () { correctionId = r.student_id; correctionLesson = l.id; put('correction-name', r.name + ' · 原座位 ' + r.original_seat); el('correction-status').value = r.status === 'late' ? 'present' : r.status; el('correction-seat').value = r.seat_no || r.original_seat; el('correction-panel').hidden = false; el('correction-panel').scrollIntoView(); }; td.appendChild(b); tr.appendChild(td); rows.appendChild(tr);
      }); map(d.entries || []);
    } else {
      var open = l && l.attendance_started_at && !l.attendance_closed_at;
      el('checkin-button').disabled = !open || !!d.my_student_id || busy;
      put('checkin-status', !l ? '等待教师开始本节课' : (d.my_student_id ? '本机签到已由教师机保存。修改请联系教师。' : (open ? '签到开放中，请核对姓名和实际座位。' : '签到尚未开放或已经结束。')));
      options('checkin-student', d.entries || [], 'student_id', function (r) { return r.name + ' · 原座位 ' + r.original_seat; });
      options('checkin-seat', (d.available_seats || []).map(function (n) { return {n:n}; }), 'n', function (r) { return r.n + ' 号'; });
      map(d.entries || []);
    }
  }
  function refresh() {
    if (module === 'data' || polling) { return; }
    polling = true;
    var requested = historyId;
    api('GET', teacher ? (historyId ? 'teacher/lessons/' + historyId : 'teacher/lessons/current') : 'student/attendance', null, function (err, d) {
      polling = false;
      if (requested !== historyId) { return; }
      put('module-connection', err || '● 已连接 · 每秒更新');
      if (!err) { render(d); } else {
        ['open-attendance','close-attendance','end-lesson','draw-button','checkin-button'].forEach(function (id) { if (el(id)) { el(id).disabled = true; } });
      }
    });
  }
  function context() {
    api('GET', teacher ? 'teacher/current' : 'student/state', null, function (err, d) {
      if (!err) { arrangement = d; put('active-title', {'attendance':'考勤签到','rollcall':'随机点名','data':'班级数据管理'}[module] + ' · ' + (d['class'] ? d['class'].name : '未选择上课班级')); }
    });
  }
  if (module === 'data') {
    function classes() {
      api('GET', 'teacher/classes' + (recycled ? '?deleted=1' : ''), null, function (err, d) {
        if (err) { message(err); return; } put('module-connection', recycled ? '回收站 · 可以恢复' : '在用班级'); el('class-list').textContent = '';
        d.classes.forEach(function (c) { var label = make('label', '', 'class-choice'), check = document.createElement('input'); check.type = 'checkbox'; check.value = c.id; label.appendChild(check); label.appendChild(make('span', c.name)); el('class-list').appendChild(label); });
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
      save('teacher/lessons', {round_id: arrangement.round.id, late_after: Number(el('late-after').value)}, 'POST', function () { historyId = ''; put('draw-name','准备点名'); put('draw-history',''); });
    };
    [['open-attendance','open'],['close-attendance','close'],['end-lesson','end']].forEach(function (pair) { el(pair[0]).onclick = function () { if (!state || !state.lesson) { return; } if (pair[1] !== 'open' && !confirm('确认结束？未签到人员会记为缺勤；结束本节课后日志只读。')) { return; } save('teacher/lessons/' + state.lesson.id + '/' + pair[1], {}); }; });
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
        if (drawing || !state || !state.lesson) { return; } drawing = true; el('draw-button').disabled = true;
        var lid = state.lesson.id, entries = state.entries.filter(function (r) { return !state.lesson.attendance_started_at || r.status === 'present' || r.status === 'late'; });
        var animation = setInterval(function () { put('draw-name', entries.length ? entries[Math.floor(Math.random()*entries.length)].name : '等待结果'); }, 90);
        api('POST','teacher/rollcall/'+lid,{},function(err,d){setTimeout(function(){clearInterval(animation);drawing=false;if(err){message(err);put('draw-name','未抽取');}else{put('draw-name',d.name+' · '+d.seat_no+' 号');api('GET','teacher/rollcall/'+lid,null,function(e,result){if(!e){put('draw-history',result.draws.map(function(r){return time(r.created_at)+' '+r.name+'（'+r.seat_no+'号）';}).join(' / '));}});}refresh();}, window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 1000);});
      };
    }
  } else {
    el('checkin-form').onsubmit = function (e) { e.preventDefault(); if (!state || !state.lesson) { return; } save('student/attendance', {lesson_id:state.lesson.id, student_id:el('checkin-student').value, seat_no:Number(el('checkin-seat').value)}, 'POST', function () { message('签到成功，教师机已保存。'); }); };
  }
  context(); refresh(); setInterval(refresh, 1000); setInterval(context, 3000);
}());
