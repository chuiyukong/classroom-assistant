"""Isolated browser workflow for attendance, roll call and class recycling."""
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server
from playwright.sync_api import sync_playwright, expect


def run():
    with tempfile.TemporaryDirectory(prefix='classroom-modules-') as folder:
        app = create_app(folder, bootstrap_key='module-test')
        s = app.extensions['seating']; c = app.extensions['classes'].create('演示班级')
        r = s.open_round(c['id'])['round']
        for i in range(1, 5): s.correct(r['id'], i, '演示同学' + str(i))
        s.close_round(r['id'])
        server = create_server(app, host='127.0.0.1',port=0,threads=12)
        threading.Thread(target=server.run,daemon=True).start()
        url='http://127.0.0.1:'+str(server.effective_port)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                teacher=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];teacher.on('pageerror',lambda e:errors.append(str(e)))
                teacher.on('dialog',lambda d:d.accept())
                teacher.goto(url+'/teacher?key=module-test')
                expect(teacher.locator('#active-title')).to_contain_text('在线选座系统 · 演示班级')
                teacher.locator('.footnote').evaluate("e => e.style.visibility='hidden'")
                teacher.screenshot(path='test-results/teacher-v120.png',full_page=True)
                teacher.get_by_role('link',name='考勤签到',exact=True).click()
                expect(teacher.locator('#active-title')).to_contain_text('演示班级')
                teacher.locator('#new-lesson').click()
                expect(teacher.locator('#open-attendance')).to_be_enabled()
                teacher.locator('#open-attendance').click()
                expect(teacher.locator('#lesson-info')).to_contain_text('签到开放中')
                student=browser.new_page(viewport={'width':1024,'height':768})
                student.on('pageerror',lambda e:errors.append(str(e)))
                student.goto(url+'/')
                expect(student.locator('#class-title')).to_contain_text('演示班级')
                student.screenshot(path='test-results/student-v120.png',full_page=True)
                student.goto(url+'/attendance')
                expect(student.locator('#checkin-button')).to_be_enabled()
                student.locator('#checkin-student').select_option(label='演示同学1 · 原座位 1')
                student.locator('#checkin-seat').select_option('64')
                student.locator('#checkin-button').click()
                expect(student.locator('#module-message')).to_contain_text('签到成功')
                expect(teacher.locator('#attendance-rows tr').first).to_contain_text('1 → 64')
                teacher.locator('#attendance-rows tr').nth(1).get_by_role('button').click()
                teacher.locator('#correction-status').select_option('long_leave')
                teacher.locator('#correction-form button').click()
                expect(teacher.locator('#missing-names')).to_contain_text('长期请假')
                assert '长期请假' not in student.locator('body').inner_text()
                teacher.get_by_role('link',name='随机点名',exact=True).click()
                expect(teacher.locator('#draw-button')).to_be_enabled()
                teacher.locator('#draw-button').click()
                expect(teacher.locator('#draw-name')).to_have_text('演示同学1 · 64 号')
                teacher.get_by_role('link',name='考勤签到',exact=True).click()
                expect(teacher.locator('#end-lesson')).to_be_enabled()
                teacher.locator('#end-lesson').click()
                expect(teacher.locator('#end-lesson')).to_be_disabled()
                teacher.locator('#history-search').click()
                teacher.locator('#history-results button').first.click()
                expect(teacher.locator('#lesson-info')).to_contain_text('只读')
                assert teacher.locator('#attendance-rows button:enabled').count()==0
                teacher.screenshot(path='test-results/attendance-v120.png',full_page=True)
                teacher.get_by_role('link',name='班级数据管理',exact=True).click()
                teacher.locator('#class-list input').check()
                teacher.locator('#manage-selected').click()
                expect(teacher.locator('#class-list input')).to_have_count(0)
                teacher.locator('#show-deleted').click()
                teacher.locator('#class-list input').check()
                teacher.locator('#manage-selected').click()
                expect(teacher.locator('#class-list input')).to_have_count(0)
                teacher.goto(url+'/teacher')
                expect(teacher.locator('[data-seat="1"]')).to_be_visible()
                teacher.screenshot(path='test-results/seating-v120.png',full_page=True)
                assert teacher.locator('body').evaluate("e => Array.from(e.querySelectorAll('*')).filter(n => n.textContent.trim() && getComputedStyle(n).display !== 'none' && parseFloat(getComputedStyle(n).fontSize) < 16).map(n=>n.id)") == []
                assert not errors,errors
                browser.close()
                print('Browser passed: module navigation, temporary seat, live summary, private status, roll call, history, recycle/restore, minimum 16px typography.')
        finally:
            server.close()
            for handler in list(app.logger.handlers):
                if hasattr(handler, 'baseFilename'):
                    app.logger.removeHandler(handler)
                    handler.close()


if __name__=='__main__':run()
