/* Stable seat nodes: polling only changes text/classes, never focused inputs. */
(function () {
  'use strict';
  function make(tag, cls, text) { var n=document.createElement(tag); n.className=cls||''; n.textContent=text||''; return n; }
  function SeatMap(root, click) { this.root=root; this.click=click; this.id=''; this.buttons={}; this.highlighted=null; }
  SeatMap.prototype.layout=function (layout) {
    if (!layout || this.id===layout.id) { return; }
    this.id=layout.id; this.root.textContent=''; this.root.className='seat-map attendance-seat-map'; this.buttons={};
    var self=this;
    for(var b=1;b<=4;b++) {
      var block=make('div','big-group'),last='';
      for(var row=0;row<8;row++) {
        var seats=layout.seats.filter(function(s){return s.big_group===b && s.row===row;});
        seats.sort(function(a,c){return a.column-c.column;});
        if(!seats.length){continue;}
        if(seats[0].group!==last){last=seats[0].group;block.appendChild(make('div','group-label',last));}
        var line=make('div','seat-row');
        seats.forEach(function(s){var btn=make('button','seat attendance-seat');btn.type='button';btn.setAttribute('data-seat',s.number);btn.appendChild(make('span','number',String(s.number)));var content=make('span','seat-content');content.appendChild(make('strong','name','空位'));content.appendChild(make('span','seat-status',''));btn.appendChild(content);btn.appendChild(make('span','role-badge',''));btn.onclick=function(){if(self.click){self.click(s.number);}};self.buttons[s.number]=btn;line.appendChild(btn);});
        block.appendChild(line);
      }
      block.appendChild(make('div','big-group-title',['第一大组','第二大组','第三大组','第四大组'][b-1]));this.root.appendChild(block);
    }
  };
  SeatMap.prototype.update=function(entries,options){
    options=options||{};var labels={pending:'未签到',present:'已签到',late:'已签到·迟到',leave:'请假',absent:'缺勤',long_leave:'长期请假'};
    var fixed={},actual={},disabled=options.disabled||[];
    entries.forEach(function(r){fixed[r.original_seat]=r;if(r.seat_no){actual[r.seat_no]=r;}});
    for(var number in this.buttons){if(Object.prototype.hasOwnProperty.call(this.buttons,number)){
      var n=Number(number),btn=this.buttons[n],r=actual[n]||fixed[n],signed=!!actual[n],moved=r&&r.seat_no&&r.seat_no!==n;
      if(options.rollcall && moved){r=null;moved=false;}
      var state=signed?'present':(moved?'moved':(r?'pending':'empty')),off=disabled.indexOf(n)!==-1;
      var status=off?'设备停用':(signed?'已签到':(moved?'已换座':(r?'未签到':'')));
      if(r && r.status && !moved){status=labels[r.status];state=r.status;}
      if(options.rollcall && !options.attendance){status=off?'设备停用':'';state=r?'taken':'empty';}
      btn.className='seat attendance-seat '+state+(r && r.role?' has-role':'')+(off?' unavailable':'')+(this.highlighted===n?' draw-highlight':'')+(r && (options.selected||[]).indexOf(r.student_id)!==-1?' manual-selected':'');
      btn.querySelector('.name').textContent=r?r.name:'空位';btn.querySelector('.seat-status').textContent=status;
      btn.querySelector('.role-badge').textContent=r?['','班长','课代表','班长·课代表'][r.role||0]:'';
      btn.disabled=!!options.blocked||(!!options.rollcall && !options.manual)||(!options.teacher && (off||signed));
      btn.setAttribute('aria-label',n+'号 '+(r?r.name:'空位')+' '+status);
      btn.title=n+'号 '+(r?r.name:'空位')+' '+status+(options.log && r ? '\n签到时间：'+(r.signed_at?new Date(r.signed_at).toLocaleString():'未签到')+'\n学生机 IP：'+(r.source_ip||'未获取（教师补签或未签到）') : '');
    }}
  };
  SeatMap.prototype.highlight=function(number){var old=this.buttons[this.highlighted];if(old){old.className=old.className.replace(' draw-highlight','');}this.highlighted=number;var next=this.buttons[number];if(next){next.className+=' draw-highlight';}};
  window.ClassroomSeatMap=SeatMap;
}());
