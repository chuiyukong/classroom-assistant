"""50-student visual acceptance using isolated synthetic data and local browsers."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server
from playwright.sync_api import sync_playwright, expect


def run():
    Path('test-results').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='classroom-visual-') as folder:
        app=create_app(folder,bootstrap_key='visual-test')
        seating=app.extensions['seating'];attendance=app.extensions['attendance']
        cls=app.extensions['classes'].create('演示班',2026,'上学期','高一')
        rid=seating.open_round(cls['id'])['round']['id']
        for n in range(1,51):seating.correct(rid,n,'春风化雨生' if n==1 else '测试生%02d'%n)
        seating.seats.update('classroom-64-v2',60,True,'测试设备故障')
        server=create_server(app,host='127.0.0.1',port=0,threads=12)
        threading.Thread(target=server.run,daemon=True).start()
        url='http://127.0.0.1:'+str(server.effective_port)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch();errors=[]
                teacher=browser.new_page(viewport={'width':1920,'height':1080})
                student=browser.new_page(viewport={'width':1920,'height':1080})
                for page in (teacher,student):page.on('pageerror',lambda e:errors.append(str(e)))
                teacher.goto(url+'/teacher?key=visual-test');student.goto(url+'/')
                expect(student.locator('#active-class')).to_have_text('演示班')
                expect(teacher.locator('#active-class')).to_have_text('演示班 · 2026年 上学期')
                expect(teacher.locator('#class-title')).to_have_text('座位登记')
                def check_style(page):
                    expect(page.locator('.seat')).to_have_count(64)
                    name=page.locator('.seat .name').first
                    assert name.evaluate('e=>getComputedStyle(e).fontSize')=='15px'
                    assert name.evaluate('e=>getComputedStyle(e).fontWeight')=='400'
                    assert page.locator('.seat .number').first.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
                    number=page.locator('.seat .number').first
                    assert number.evaluate('e=>getComputedStyle(e,"::after").top')=='5px'
                    assert number.evaluate('e=>getComputedStyle(e,"::after").bottom')=='5px'
                    assert page.locator('.site-footer').count()==0
                    long=page.locator('[data-seat="1"] .name')
                    assert long.evaluate('e=>e.scrollWidth<=e.clientWidth')
                check_style(teacher);check_style(student)
                teacher.locator('.footnote').evaluate("e=>e.style.visibility='hidden'")
                teacher.screenshot(path='test-results/teacher-v160.png',full_page=True)
                seating.close_round(rid);lesson=attendance.start(rid);lid=lesson['lesson']['id'];rows=lesson['entries']
                attendance.action(lid,'open')
                for n,row in enumerate(rows[:35],1):attendance.checkin(lid,row['student_id'],n,'10.9.0.'+str(n),'visual-'+str(n))
                with app.extensions['database'].connect(write=True) as db:
                    db.execute('UPDATE lessons SET attendance_deadline=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat(),lid))
                for n,row in enumerate(rows[35:38],36):attendance.checkin(lid,row['student_id'],n,'10.9.0.'+str(n),'visual-'+str(n))
                attendance.mark(lid,rows[38]['student_id'],'leave');attendance.mark(lid,rows[39]['student_id'],'long_leave')
                attendance.checkin(lid,rows[40]['student_id'],64,'10.9.0.64','visual-64',move_reason='device_fault')
                teacher.goto(url+'/teacher/attendance');student.goto(url+'/attendance')
                expect(teacher.locator('#attendance-summary')).to_contain_text('50')
                check_style(teacher);check_style(student)
                assert student.locator('.seat-status').first.evaluate('e=>getComputedStyle(e).fontSize')=='14px'
                assert student.locator('[data-seat="42"]').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(234, 240, 245)'
                assert student.locator('[data-seat="36"]').evaluate('e=>getComputedStyle(e).backgroundColor')==student.locator('[data-seat="1"]').evaluate('e=>getComputedStyle(e).backgroundColor')
                teacher.screenshot(path='test-results/attendance-v160.png',full_page=True);student.screenshot(path='test-results/student-v160.png',full_page=True)
                podium=teacher.locator('.attendance-main .podium').bounding_box();assert podium['y']+podium['height']<=1080
                teacher.goto(url+'/teacher/rollcall');teacher.set_viewport_size({'width':1366,'height':768})
                check_style(teacher);expect(teacher.locator('#draw-source')).to_contain_text('39 人')
                podium=teacher.locator('.podium').bounding_box();assert podium['y']+podium['height']<=768
                teacher.screenshot(path='test-results/rollcall-v160.png',full_page=True)
                attendance.action(lid,'end');teacher.set_viewport_size({'width':1920,'height':1080});teacher.goto(url+'/teacher/data')
                expect(teacher.locator('#log-grade option')).to_have_count(2)
                teacher.locator('#log-grade').select_option('高一');teacher.locator('#log-search').click();expect(teacher.locator('#log-lesson option')).to_have_count(2)
                teacher.locator('#log-lesson').select_option(lid);expect(teacher.locator('#log-view')).to_be_visible();check_style(teacher)
                teacher.screenshot(path='test-results/data-v160.png',full_page=True)
                assert not errors,errors
                browser.close()
                print('50-student visual checks passed: 15px regular names / 14px status, full-card state colors, inset dividers, state colors, compact maps, grade log filters, all pages.')
        finally:
            server.close()
            for handler in list(app.logger.handlers):
                if hasattr(handler,'baseFilename'):app.logger.removeHandler(handler);handler.close()


if __name__=='__main__':run()
