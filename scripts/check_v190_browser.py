"""50 fictional students: perspectives, disabled devices, class editing."""
from pathlib import Path
import sys,tempfile,threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server
from playwright.sync_api import sync_playwright,expect

def orientation(page,student):
 expect(page.locator('[data-seat]').first).to_have_attribute('data-seat','57' if student else '8')
 box=page.locator('.podium').bounding_box();seat=page.locator('[data-seat]').first.bounding_box()
 assert (box['y']<seat['y'])==student
 assert page.locator('[data-seat]').count()==64

def run():
 with tempfile.TemporaryDirectory(prefix='classroom-v190-') as folder:
  app=create_app(folder,bootstrap_key='preview');s=app.extensions['seating'];c=app.extensions['classes'].create('虚构班');rid=s.open_round(c['id'])['round']['id']
  for i in range(1,51):s.correct(rid,i,'测试学生%02d'%i)
  s.seats.update(s.layouts.current['id'],64,True,'虚构故障备注')
  server=create_server(app,host='127.0.0.1',port=0,threads=12,connection_limit=400)
  threading.Thread(target=server.run,daemon=True).start();url='http://127.0.0.1:'+str(server.effective_port)
  try:
   with sync_playwright() as p:
    b=p.chromium.launch();teacher=b.new_page(viewport={'width':1920,'height':1080});student=b.new_page(viewport={'width':1920,'height':1080})
    errors=[]
    for page in (teacher,student):page.on('pageerror',lambda e:errors.append(str(e)))
    teacher.goto(url+'/teacher?key=preview');teacher.locator('#class-select').select_option(c['id']);orientation(teacher,False)
    student.goto(url+'/');orientation(student,True);expect(student.locator('[data-seat="64"] .name')).to_have_text('设备停用');student.screenshot(path='test-results/student-seating190.png',full_page=True)
    s.close_round(rid);student.wait_for_url(url+'/attendance');orientation(student,True)
    teacher.goto(url+'/teacher/attendance');orientation(teacher,False)
    for page in (teacher,student):expect(page.locator('[data-seat="64"] .name')).to_have_text('设备停用')
    student.screenshot(path='test-results/student-attendance190.png',full_page=True)
    teacher.goto(url+'/teacher/data');expect(teacher.locator('#class-list')).to_contain_text('50 人')
    assert teacher.locator('.class-rename').bounding_box()['width']>=150
    teacher.locator('.class-rename').fill('改名测试班');teacher.locator('.grade-edit').fill('2029');teacher.get_by_role('button',name='保存名称和届数').click()
    expect(teacher.locator('#class-list')).to_contain_text('改名测试班 · 50 人 · 2029届')
    teacher.screenshot(path='test-results/class-data190.png',full_page=True)
    assert not errors,errors
    b.close();print('v1.9 browser: 50 students, both student perspectives, teacher perspective preserved, class count/rename/cohort passed')
  finally:
   server.close();server.task_dispatcher.shutdown();app.extensions['diagnostics'].close()
   for h in list(app.logger.handlers):
    if hasattr(h,'baseFilename'):h.close();app.logger.removeHandler(h)
if __name__=='__main__':run()
