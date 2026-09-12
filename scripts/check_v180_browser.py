"""v1.8 focused browser checks, 64 synthetic students and isolated storage."""
from pathlib import Path
import sys,tempfile,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server
from playwright.sync_api import sync_playwright,expect


def run():
 with tempfile.TemporaryDirectory(prefix='classroom-v180-') as folder:
  app=create_app(folder,bootstrap_key='v180');s=app.extensions['seating'];a=app.extensions['attendance'];classes=app.extensions['classes']
  cls=classes.create('测试一班');other=classes.create('测试二班');rid=s.open_round(cls['id'])['round']['id']
  for n in range(1,65):s.correct(rid,n,'春风化雨' if n==1 else '测试%02d'%n)
  server=create_server(app,host='127.0.0.1',port=0,threads=12);threading.Thread(target=server.run,daemon=True).start();url='http://127.0.0.1:'+str(server.effective_port)
  try:
   with sync_playwright() as p:
    b=p.chromium.launch();page=b.new_page(viewport={'width':1920,'height':1080});student=b.new_page();errors=[];dialogs=[];accept=[True]
    def dialog(d):
     dialogs.append(d.message)
     d.accept() if accept[0] else d.dismiss()
    page.on('dialog',dialog);page.on('pageerror',lambda e:errors.append(str(e)));student.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url+'/teacher?key=v180');page.locator('[data-seat="1"]').click();page.locator('#role-monitor').check();page.locator('#role-representative').check();page.locator('#student-note').fill('测试私密备注');page.locator('#submit-seat').click()
    expect(page.locator('[data-seat="1"] .role-badge')).to_have_text('班长·课代表')
    student.goto(url+'/');expect(student.locator('[data-seat="1"] .role-badge')).to_have_text('班长·课代表');assert '测试私密备注' not in student.content()
    s.close_round(rid)
    page.goto(url+'/teacher/rollcall');expect(page.locator('#draw-source')).to_contain_text('点名范围人数 · 64 人')
    page.evaluate("() => {window.visits=[];var h=ClassroomSeatMap.prototype.highlight;ClassroomSeatMap.prototype.highlight=function(n){if(n){window.visits.push(n);}return h.call(this,n);};}")
    t=time.monotonic();page.locator('#draw-button').click();expect(page.locator('#draw-button')).to_be_enabled(timeout=3000);elapsed=time.monotonic()-t
    assert elapsed<3,elapsed
    assert len(set(page.evaluate('window.visits.slice(0,64)')))==64
    page.locator('#draw-scope').select_option('manual');expect(page.locator('#draw-source')).to_contain_text('点名范围人数 · 0 人')
    page.locator('[data-seat="1"]').click();expect(page.locator('#draw-source')).to_contain_text('点名范围人数 · 1 人')
    t=time.monotonic();page.locator('#draw-button').click();expect(page.locator('#draw-button')).to_be_enabled(timeout=3000);assert time.monotonic()-t<3
    page.locator('#draw-scope').select_option('late');expect(page.locator('#draw-source')).to_contain_text('点名范围人数 · 0 人')
    page.goto(url+'/teacher/attendance');page.locator('#new-lesson').click();expect(page.locator('#new-lesson')).to_have_text('正在上课');expect(page.locator('#new-lesson')).to_be_disabled();expect(page.locator('#end-lesson')).to_be_enabled()
    page.reload();expect(page.locator('#new-lesson')).to_be_disabled();page.locator('#open-attendance').click()
    expect(page.locator('[data-seat="1"] .role-badge')).to_have_text('班长·课代表')
    bounds=page.locator('[data-seat="1"]').bounding_box();badge=page.locator('[data-seat="1"] .role-badge').bounding_box();name=page.locator('[data-seat="1"] .name').bounding_box()
    glyph=page.locator('[data-seat="1"] .name').evaluate('e=>{var r=document.createRange();r.selectNodeContents(e);return r.getBoundingClientRect().top;}')
    assert glyph>=badge['y']+badge['height'],(glyph,badge)
    assert badge['x']>=bounds['x'] and badge['x']+badge['width']<=bounds['x']+bounds['width']
    page.locator('[data-seat="1"]').screenshot(path='test-results/role-seat-v180.png')
    page.screenshot(path='test-results/roles-v180.png',full_page=True)
    student.goto(url+'/attendance');expect(student.locator('[data-seat="1"] .role-badge')).to_have_text('班长·课代表')
    page.goto(url+'/teacher/rollcall');page.set_viewport_size({'width':1366,'height':768});expect(page.locator('[data-seat="1"] .role-badge')).to_have_text('班长·课代表')
    badge=page.locator('[data-seat="1"] .role-badge').bounding_box()
    glyph=page.locator('[data-seat="1"] .name').evaluate('e=>{var r=document.createRange();r.selectNodeContents(e);return r.getBoundingClientRect().top;}')
    assert glyph>=badge['y']+badge['height'],(glyph,badge)
    page.set_viewport_size({'width':1920,'height':1080})
    with app.extensions['database'].connect() as db:lid=a.running(db)['id']
    page.goto(url+'/teacher');page.locator('#class-select').select_option(other['id']);expect(page.locator('#active-class')).to_contain_text('测试二班')
    accept[0]=False;page.locator('#publish-class').click();expect(page.locator('#publish-class')).to_be_enabled();assert a.detail(lid)['lesson']['ended_at'] is None
    accept[0]=True;page.locator('#publish-class').click();expect(page.locator('#teacher-tip')).to_contain_text('学生当前显示：测试二班');expect(page.locator('#publish-class')).to_be_disabled();assert a.detail(lid)['lesson']['ended_at'];assert a.detail(lid)['counts']['absent']==64
    assert any('正在上课' in x and '切换班级' in x for x in dialogs)
    page.locator('#class-select').select_option(cls['id']);expect(page.locator('#active-class')).to_contain_text('测试一班')
    page.locator('#publish-class').click();expect(page.locator('#teacher-tip')).to_contain_text('学生当前显示：测试一班')
    page.locator('#start-round').click();expect(page.locator('[data-seat="2"] .name')).to_have_text('空位')
    page.locator('[data-seat="2"]').click();page.locator('#student-name').fill('春风化雨');page.locator('#submit-seat').click()
    expect(page.locator('[data-seat="2"] .role-badge')).to_have_text('班长·课代表')
    assert not errors,errors
    b.close();print('v1.8 browser checks passed: 64 candidates in %.2fs; single/manual/late scopes; role badges; lesson lock and confirmed/cancelled switch.'%elapsed)
  finally:
   server.close()
   app.extensions['diagnostics'].close()
   for handler in list(app.logger.handlers):
    handler.close();app.logger.removeHandler(handler)
if __name__=='__main__':run()
