/* ES5 + XMLHttpRequest: compatible with older Chrome / Firefox on Windows 7. */
(function () {
  'use strict';
  var teacher = document.body.getAttribute('data-mode') === 'teacher';
  if(document.getElementById('seating-nav')){document.getElementById('seating-nav').className='current';}
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
  var state = null, classId = '', historyId = '', seatButtons = {}, layoutId = '', selected = null;
  var pending = null, busy = false, connected = false, version = 0, timer = null;
  var profiles = [], classNames = {}, noteDirty = false;
  function el(id) { return document.getElementById(id); }
  function text(id, value) { el(id).textContent = value; }
  function notice(message, error) { text('notice', message); el('notice').className = 'notice' + (error ? ' error' : ''); }
  function api(method, url, data, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true); xhr.timeout = 12000;
    if (method !== 'GET') { xhr.setRequestHeader('Content-Type', 'application/json'); xhr.setRequestHeader('X-CSRF-Token', csrf); }
    xhr.onload = function () {
      var result; try { result = JSON.parse(xhr.responseText); } catch (e) { done('服务器响应异常，请重试'); return; }
      if (xhr.status >= 200 && xhr.status < 300) { done(null, result); }
      else { done(result.error ? result.error.message : '操作未完成，请重试', null, xhr.status); }
    };
    xhr.onerror = xhr.ontimeout = function () { done('连接中断或超时，请确认教师机正在运行。', null, 0); };
    xhr.send(method === 'GET' ? null : JSON.stringify(data));
  }
  function classLabel(c) { return c.name + (c.graduation_year?' · '+c.graduation_year+'届':'') + (c.year ? ' · '+c.year+'年 '+c.semester : ' · 未设置学期'); }
  function option(select, value, label) { var o = document.createElement('option'); o.value = value; o.textContent = label; select.appendChild(o); }
  function make(tag, cls, value) { var n = document.createElement(tag); n.className = cls || ''; if (value !== undefined) { n.textContent = value; } return n; }
  function connect(ok) {
    connected = ok; text('connection', ok ? '状态：已连接' : '状态：连接中断');
    el('connection').className = 'connection' + (ok ? '' : ' offline');
    if (!ok) { for (var k in seatButtons) { if (Object.prototype.hasOwnProperty.call(seatButtons, k)) { seatButtons[k].disabled = true; } } }
    buttons();
  }
  function buildMap(layout) {
    if (layoutId === layout.id) { return; }
    layoutId = layout.id; el('seat-map').textContent = ''; seatButtons = {};
    for (var b = 1; b <= 4; b++) {
      var block = make('div', 'big-group'), lastGroup = '';
      for (var row = 0; row < 8; row++) {
        var rowSeats = layout.seats.filter(function (s) { return s.big_group === b && s.row === row; });
        rowSeats.sort(function (a, c) { return a.column - c.column; });
        if (rowSeats[0].group !== lastGroup) { lastGroup = rowSeats[0].group; block.appendChild(make('div', 'group-label', lastGroup)); }
        var line = make('div', 'seat-row');
        rowSeats.forEach(function (s) {
          var btn = make('button', 'seat'); btn.type = 'button';
          btn.appendChild(make('span', 'number', s.number)); btn.appendChild(make('span', 'name', '空位'));
          btn.onclick = function () { showDialog(s.number); }; btn.setAttribute('data-seat', s.number);
          seatButtons[s.number] = btn; line.appendChild(btn);
        });
        block.appendChild(line);
      }
      block.appendChild(make('div', 'big-group-title', ['第一大组', '第二大组', '第三大组', '第四大组'][b - 1]));
      el('seat-map').appendChild(block);
    }
  }
  function record(number) {
    if (!state) { return null; }
    for (var i = 0; i < state.registrations.length; i++) { if (state.registrations[i].seat_no === number) { return state.registrations[i]; } }
    return null;
  }
  function device(number) {
    var configs = state ? state.seat_configs || [] : [];
    for (var i = 0; i < configs.length; i++) { if (configs[i].seat_no === number) { return configs[i]; } }
    return {disabled: false, note: ''};
  }
  function render(data) {
    if (state && state.round && (!data.round || state.round.id !== data.round.id)) {
      closeDialog(); pending = null;
      if (!teacher) { notice(data.round && data.round.is_open ? '新登记已开始，请重新核对座位并登记。' : '当前座位已更新，请以座位图为准。'); }
    }
    if(!teacher && (!data.round || !data.round.is_open)){window.location.replace('/attendance');return;}
    text('active-class', data['class'] ? (teacher ? classLabel(data['class']) : data['class'].name) : '等待上课');
    state = data; buildMap(data.layout); text('capacity', data.layout.seats.length); text('count', data.count);
    text('class-title', data.is_current === false ? '历史存档' : '座位登记');
    var round = data.round;
    text('round-status', teacher && data.is_current === false && round ? '历史存档 · ' + new Date(round.opened_at).toLocaleString() : (round && round.is_open ? '座位登记开放中' : '座位登记未开放'));
    el('round-status').className='operation-status '+(round && round.is_open ? 'is-open':'is-closed');
    text('hint', teacher ? (data.is_current === false ? '存档只读，设备状态显示当前状态。可导出此份存档。' : '点击座位可编辑学生登记、学生备注及跨班级共用的设备配置。') : (data.my_seat ? '这台电脑已登记 ' + data.my_seat + ' 号座位。填写有误请联系教师。' : (round && round.is_open ? '请按电脑或桌面座位号核对实际位置，填写姓名。' : '座位登记未开放')));
    if(!teacher && data.my_seat){var mine=data.registrations.filter(function(r){return r.seat_no===data.my_seat;})[0];el('hint').textContent='';var who=document.createElement('strong');who.className='identity-chip';who.textContent=mine?mine.name:'你';el('hint').appendChild(who);el('hint').appendChild(document.createTextNode('已登记 '+data.my_seat+' 号座位，填写有误请联系教师。'));}
    var available = 0, disabled = 0;
    data.layout.seats.forEach(function (s) {
      var btn = seatButtons[s.number], item = record(s.number), config = device(s.number);
      if (config.disabled) { disabled++; } else if (!item) { available++; }
      btn.className = 'seat' + (item ? ' taken' : '') + (config.disabled ? ' unavailable' : '') + (s.number === selected ? ' chosen' : '');
      btn.children[1].textContent = item ? item.name + (config.disabled ? '（停用）' : '') : (config.disabled ? '设备停用' : '空位');
      btn.title = s.number + ' 号 · ' + (item ? item.name : '未登记') + (config.disabled ? ' · 设备停用' : '');
      if (teacher) { btn.title += (config.note ? '\n设备：' + config.note : '') + (item && item.student_note ? '\n学生：' + item.student_note : ''); }
      btn.setAttribute('aria-label', btn.title);
      btn.disabled = !connected || (teacher ? !data.is_current : (!round || !round.is_open || !!item || !!data.my_seat || !!config.disabled));
    });
    text('empty-summary', '可用空位 ' + available + ' 个 · 停用设备 ' + disabled + ' 台');
    if (teacher) { text('teacher-tip', '学生当前显示：' + (classNames[data.active_class_id] || '尚未选择班级') + '。查看其他班级或存档不会自动切换学生页面。'); }
    buttons();
  }
  function buttons() {
    if (!teacher) { return; }
    el('start-round').disabled = !connected || !classId || busy || !state || !state.is_current;
    el('publish-class').disabled = !connected || !classId || busy || !state || state.active_class_id === classId;
    el('class-select').disabled = busy; el('round-select').disabled = busy;
    el('close-round').disabled = !connected || busy || !state || !state.round || !state.round.is_open || !state.is_current;
    el('export').disabled = !connected || busy || !state || !state.round;
  }
  function poll() {
    clearTimeout(timer);
    var currentVersion = version;
    var url = teacher ? (classId ? '/api/v1/teacher/classes/' + classId + '/arrangement' + (historyId ? '?round_id=' + historyId : '') : '/api/v1/teacher/current') : '/api/v1/student/state';
    api('GET', url, null, function (err, data) {
      if (currentVersion !== version) { return; }
      connect(!err);
      if (!err) {
        if (teacher && !classId) { data['class'] = null; data.round = null; data.registrations = []; data.count = 0; }
        render(data);
      }
      timer = setTimeout(poll, err ? 2500 : 1000);
    });
  }
  function refresh() { version++; poll(); }
  function showDialog(number) {
    if (!connected || busy) { return; }
    selected = number; var item = record(number);
    text('dialog-title', number + ' 号座位'); text('dialog-context', teacher ? '教师修改' : '确认实际座位');
    text('dialog-help', teacher ? '学生备注跟随学生保存；设备配置对所有班级生效。' : '请确认这就是您当前使用的电脑座位。');
    el('student-name').value = item ? item.name : '';
    el('clear-seat').hidden = !teacher || !item; text('submit-seat', teacher ? '保存修改' : '确认登记');
    text('dialog-error', ''); el('dialog').hidden = false; el('student-name').focus();
    if (teacher) {
      var cfg = device(number);
      el('seat-form').hidden = !state.round;
      el('student-note').value = item ? item.student_note || '' : ''; noteDirty = false;
      el('new-identity').checked = false;
      el('seat-disabled').checked = !!cfg.disabled; el('device-note').value = cfg.note || ''; text('device-message', '');
      var select = el('student-record'); select.textContent = ''; option(select, '', '按姓名匹配已有记录');
      loadProfiles(function () {
        if (selected !== number || el('dialog').hidden) { return; }
        profiles.forEach(function (p) { option(select, p.id, p.name + ' · 编号 ' + p.id.slice(0, 8)); });
        select.value = item && item.student_id ? item.student_id : '';
      });
    }
    if (state) { render(state); }
  }
  function closeDialog() {
    if (busy) { return; }
    var previous = selected; selected = null; el('dialog').hidden = true;
    if (state) { render(state); }
    if (previous && seatButtons[previous]) { seatButtons[previous].focus(); }
  }
  el('dialog-close').onclick = closeDialog;
  document.addEventListener('keydown', function (event) {
    if (el('dialog').hidden) { return; }
    if (event.key === 'Escape' || event.keyCode === 27) { closeDialog(); }
    if (event.key === 'Tab' || event.keyCode === 9) {
      var focusables = Array.prototype.filter.call(el('dialog').querySelectorAll('button, input, select, textarea'), function (n) { return !n.disabled && n.offsetParent !== null; });
      var index = focusables.indexOf(document.activeElement), next = index + (event.shiftKey ? -1 : 1);
      if (next < 0) { next = focusables.length - 1; } if (next >= focusables.length) { next = 0; }
      event.preventDefault(); focusables[next].focus();
    }
  });
  function saveSeat(name) {
    if (busy || !state || !state.round) { return; }
    var roundId = state.round.id, number = selected;
    busy = true; el('submit-seat').disabled = true; el('clear-seat').disabled = true; buttons();
    var data = {name: name}, url = '/api/v1/teacher/rounds/' + roundId + '/seats/' + number, method = 'PUT';
    if (teacher && name) {
      data.force_new = el('new-identity').checked;
      data.student_id = data.force_new ? null : (el('student-record').value || null);
      if (noteDirty) { data.student_note = el('student-note').value; }
    }
    if (!teacher) {
      var signature = roundId + ':' + number + ':' + name;
      if (!pending || pending.signature !== signature) { pending = {signature: signature, id: String(Date.now()) + '-' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2)}; }
      data = {round_id: roundId, seat_no: number, name: name, request_id: pending.id};
      url = '/api/v1/student/registrations'; method = 'POST';
    }
    api(method, url, data, function (err, result) {
      busy = false; el('submit-seat').disabled = false; el('clear-seat').disabled = false; buttons();
      if (err) { text('dialog-error', err); }
      else { closeDialog(); notice(teacher ? '修改已保存。' : (result.duplicate ? '此前的提交已保存；请以当前座位图为准。' : '登记成功！您的座位是 ' + number + ' 号。')); pending = null; }
      refresh();
    });
  }
  el('seat-form').onsubmit = function (event) { event.preventDefault(); var name = el('student-name').value.trim(); if (!name) { text('dialog-error', '请输入姓名'); return; } saveSeat(name); };
  el('clear-seat').onclick = function () { if (confirm('确认清除 ' + selected + ' 号座位的登记？')) { saveSeat(''); } };
  function loadRounds(done) {
    if (!classId) { done(); return; }
    api('GET', '/api/v1/teacher/classes/' + classId + '/rounds', null, function (err, data) {
      if (err) { notice(err, true); done(); return; }
      var select = el('round-select'); select.textContent = ''; option(select, '', '当前座位');
      data.rounds.forEach(function (r, i) { if (i > 0) { option(select, r.id, '存档 ' + r.number + ' · ' + new Date(r.opened_at).toLocaleString()); } });
      select.value = historyId; done();
    });
  }
  function loadClasses(chosen) {
    api('GET', '/api/v1/teacher/classes', null, function (err, data) {
      if (err) { notice(err, true); return; }
      var select = el('class-select'); select.textContent = ''; option(select, '', '请选择班级');
      data.classes.forEach(function (c) { option(select, c.id, classLabel(c)); classNames[c.id] = classLabel(c); });
      classId = chosen || data.active_class_id || (data.classes.length ? data.classes[0].id : ''); select.value = classId;
      historyId = ''; loadRounds(refresh);
    });
  }
  function loadProfiles(done) {
    if (!classId) { profiles = []; done(); return; }
    var requested = classId;
    api('GET', '/api/v1/teacher/classes/' + classId + '/students', null, function (err, data) {
      if (requested !== classId) { return; }
      if (err) { notice(err, true); profiles = []; } else { profiles = data.students; }
      done();
    });
  }
  function profile(id) { for (var i = 0; i < profiles.length; i++) { if (profiles[i].id === id) { return profiles[i]; } } return null; }
  if (teacher) {
    el('student-note').oninput = function () { noteDirty = true; };
    el('student-record').onchange = function () {
      var p = profile(this.value);
      if (p) { el('student-name').value = p.name; el('student-note').value = p.note; el('new-identity').checked = false; noteDirty = false; }
    };
    el('new-identity').onchange = function () {
      if (this.checked) { el('student-record').value = ''; el('student-note').value = ''; noteDirty = true; }
    };
    el('device-form').onsubmit = function (event) {
      event.preventDefault(); if (busy || !state) { return; }
      busy = true; buttons(); el('device-save').disabled = true;
      api('PUT', '/api/v1/teacher/layouts/' + state.layout.id + '/seats/' + selected + '/config',
        {disabled: el('seat-disabled').checked, note: el('device-note').value}, function (err) {
          busy = false; el('device-save').disabled = false; buttons(); text('device-message', err || '设备配置已保存，对所有班级生效。'); refresh();
        });
    };
    el('publish-class').onclick = function () {
      busy = true; buttons();
      api('POST', '/api/v1/teacher/classes/' + classId + '/publish', {}, function (err) {
        busy = false; notice(err || '已设为当前上课班级，学生页面会自动更新。', !!err); refresh();
      });
    };
    api('GET', '/api/v1/teacher/info', null, function (err, data) {
      if (err) { notice(err, true); return; }
      text('student-urls', data.urls.length ? data.urls.join('   /   ') : '请查看教师机启动窗口');
      text('data-location', 'v' + data.version + ' · ' + (data.limit_one_registration_per_ip ? '按本次登记限制 IP' : 'IP 限制已关闭') + ' · 数据目录：' + data.data_dir);
    });
    for(var y=new Date().getFullYear()+10;y>=new Date().getFullYear()-10;y--){option(el('class-year'),String(y),y+'年');} el('class-year').value=String(new Date().getFullYear());
    el('class-form').onsubmit = function (event) {
      event.preventDefault(); var name = el('class-name').value.trim();
      api('POST', '/api/v1/teacher/classes', {name: name, year:Number(el('class-year').value), semester:el('class-semester').value,graduation_year:Number(el('class-graduation').value)||0}, function (err, data) {
        if (err) { notice(err, true); return; } el('class-name').value = ''; loadClasses(data.id); notice('班级已添加，请开始登记。');
      });
    };
    el('class-select').onchange = function () { closeDialog(); classId = this.value; historyId = ''; state = null; profiles = []; version++; loadRounds(refresh); notice(''); };
    el('round-select').onchange = function () { closeDialog(); historyId = this.value; state = null; refresh(); notice(''); };
    el('start-round').onclick = function () {
      if (state && state.round && !confirm('发起空白的新登记？该班当前座位将自动转为只读存档，学生备注和设备配置继续保留。')) { return; }
      busy = true; buttons();
      api('POST', '/api/v1/teacher/classes/' + classId + '/rounds', {expected_current_id: state && state.round ? state.round.id : null}, function (err) {
        busy = false; if (err) { notice(err, true); refresh(); return; } historyId = ''; loadRounds(refresh); notice('登记已开放，请通过极域打开学生网址。');
      });
    };
    el('close-round').onclick = function () {
      if (!confirm('结束登记后，学生不能继续提交。确认结束？')) { return; }
      busy = true; buttons();
      api('POST', '/api/v1/teacher/rounds/' + state.round.id + '/close', {}, function (err) {
        busy = false; notice(err || '登记已结束，可以导出 Excel。', !!err); refresh();
      });
    };
    el('export').onclick = function () { window.location.href = '/api/v1/teacher/classes/' + classId + '/export' + (historyId ? '?round_id=' + historyId : ''); };
    var chosenClass=/[?&]class_id=([^&]+)/.exec(window.location.search);loadClasses(chosenClass?decodeURIComponent(chosenClass[1]):null);
    window.addEventListener('focus',refresh);
    document.addEventListener('visibilitychange',function(){if(!document.hidden){refresh();}});
  } else { poll(); }
}());
