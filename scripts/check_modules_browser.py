"""Temporary-data browser acceptance; virtual IPs only in this test transport."""
from pathlib import Path
from datetime import datetime
import sys,tempfile,threading,re
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server
from playwright.sync_api import sync_playwright,expect


def run():
    Path('test-results').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='classroom-modules-') as folder:
        app=create_app(folder,bootstrap_key='module-test')
        real=app.wsgi_app
        def transport(env,start):
            if env.get('HTTP_X_TEST_DEVICE_IP'):env['REMOTE_ADDR']=env['HTTP_X_TEST_DEVICE_IP']
            return real(env,start)
        app.wsgi_app=transport
        seating=app.extensions['seating'];cls=app.extensions['classes'].create('演示班',2026,'上学期')
        rid=seating.open_round(cls['id'])['round']['id']
        for i,name in enumerate(('张同学甲','春风化雨同学','李同学丙'),1):seating.correct(rid,i,name)
        seating.close_round(rid)
        server=create_server(app,host='127.0.0.1',port=0,threads=12)
        threading.Thread(target=server.run,daemon=True).start()
        url='http://127.0.0.1:'+str(server.effective_port)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch();errors=[]
                teacher=browser.new_page(viewport={'width':1920,'height':1080})
                teacher.on('pageerror',lambda e:errors.append(str(e)));teacher.on('dialog',lambda d:d.accept())
                teacher.goto(url+'/teacher?key=module-test')
                expect(teacher).to_have_title('智慧课堂综合平台')
                expect(teacher.locator('#class-year option')).to_have_count(21)
                assert teacher.locator('#class-year option').first.get_attribute('value')==str(datetime.now().year+10)
                assert teacher.locator('#student-notes').count()==0
                teacher.locator('.footnote').evaluate("e=>e.style.visibility='hidden'")
                teacher.screenshot(path='test-results/teacher-v150.png',full_page=True)
                teacher.get_by_role('link',name='随机点名',exact=True).click()
                assert teacher.locator('#new-lesson').count()==0
                expect(teacher.locator('#draw-source')).to_contain_text('当前座位名单 · 3 人')
                teacher.locator('#draw-button').click();expect(teacher.locator('#draw-button')).to_be_enabled()
                teacher.get_by_role('link',name='考勤签到',exact=True).click()
                teacher.locator('#new-lesson').click();expect(teacher.locator('#open-attendance')).to_be_enabled()
                teacher.locator('#attendance-duration').fill('1');teacher.locator('#open-attendance').click()
                expect(teacher.locator('#countdown')).to_contain_text('签到剩余')
                students=[]
                for i in range(2):
                    page=browser.new_page(viewport={'width':1920,'height':1080},extra_http_headers={'X-Test-Device-IP':'10.0.0.'+str(i+1)})
                    page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url+'/attendance');students.append(page)
                a,b=students
                a.locator('[data-seat="64"]').click();a.locator('#checkin-name').fill('张同学甲');a.locator('input[value="long_term"]').check();a.locator('#checkin-button').click()
                expect(a.locator('#countdown')).to_have_text('已签到')
                teacher.get_by_role('button',name='同意长期换座').click();expect(teacher.locator('#change-requests')).to_contain_text('已同意')
                teacher.locator('[data-seat="3"]').click();teacher.locator('#correction-status').select_option('long_leave');teacher.locator('#correction-form button').click()
                expect(b.locator('[data-seat="3"]')).to_contain_text('长期请假')
                expect(b.locator('[data-seat="2"] .name')).to_have_text('春风化雨同学')
                assert b.locator('[data-seat="2"] .name').evaluate('e=>e.scrollWidth<=e.clientWidth')
                b.screenshot(path='test-results/student-v150.png',full_page=True)
                b.locator('[data-seat="2"]').click();b.locator('#checkin-name').fill('春风化雨同学');handle=b.locator('#checkin-name').element_handle()
                expect(b.locator('#countdown')).to_contain_text('签到超时：',timeout=65000)
                expect(a.locator('#countdown')).to_have_text('已签到')
                assert handle.evaluate('e=>e===document.getElementById("checkin-name")')
                expect(b.locator('#checkin-name')).to_have_value('春风化雨同学')
                b.locator('#checkin-button').click();expect(b.locator('#countdown')).to_have_text('已签到')
                expect(teacher.locator('[data-seat="2"]')).to_have_class(re.compile('late'))
                teacher.screenshot(path='test-results/attendance-v150.png',full_page=True)
                podium=teacher.locator('.attendance-main .podium').bounding_box();assert podium['y']+podium['height']<=1080
                assert teacher.locator('.attendance-sidebar').bounding_box()['x']>teacher.locator('.attendance-main').bounding_box()['x']+teacher.locator('.attendance-main').bounding_box()['width']-1
                teacher.get_by_role('link',name='随机点名',exact=True).click();expect(teacher.locator('#draw-source')).to_contain_text('已签到名单 · 2 人')
                previous=''
                for _ in range(5):
                    teacher.locator('#draw-button').click();expect(teacher.locator('#draw-button')).to_be_enabled()
                    name=teacher.locator('#draw-name').inner_text();assert name in ('张同学甲','春风化雨同学') and name!=previous;previous=name
                teacher.set_viewport_size({'width':1366,'height':768});teacher.screenshot(path='test-results/rollcall-v150.png',full_page=True)
                podium=teacher.locator('.podium').bounding_box();assert podium['y']+podium['height']<=768
                teacher.set_viewport_size({'width':1920,'height':1080});teacher.get_by_role('link',name='考勤签到',exact=True).click()
                teacher.locator('#close-attendance').click();expect(teacher.locator('#countdown')).to_have_text('签到已结束')
                teacher.locator('[data-seat="3"]').click();teacher.locator('#correction-status').select_option('present');teacher.locator('#correction-form button').click()
                expect(teacher.locator('[data-seat="3"]')).to_contain_text('已签到')
                teacher.locator('#end-lesson').click();teacher.locator('#history-search').click();teacher.locator('#history-results button').first.click()
                expect(teacher.locator('#lesson-info')).to_contain_text('只读');expect(teacher.locator('[data-seat="3"]')).to_be_disabled()
                teacher.goto(url+'/teacher');teacher.locator('#start-round').click();expect(a).to_have_url(url+'/');expect(b).to_have_url(url+'/')
                expect(a.locator('#round-status')).to_contain_text('开放中')
                teacher.locator('#close-round').click();expect(a).to_have_url(url+'/attendance')
                teacher.get_by_role('link',name='班级数据管理',exact=True).click();teacher.locator('#filter-year').select_option('2026');teacher.locator('#filter-semester').select_option('上学期')
                teacher.locator('#class-list input').check();teacher.locator('#manage-selected').click();expect(teacher.locator('#class-list input')).to_have_count(0)
                teacher.locator('#show-deleted').click();teacher.locator('#class-list input').check();teacher.locator('#manage-selected').click();expect(teacher.locator('#class-list input')).to_have_count(0)
                assert not errors,errors
                browser.close();print('v1.5 browser passed: independent draws, one-minute deadline, signed status, modal correction, long leave, six-character fit, sidebar, automatic routing, recycle.')
        finally:
            server.close()
            for handler in list(app.logger.handlers):
                if hasattr(handler,'baseFilename'):app.logger.removeHandler(handler);handler.close()

if __name__=='__main__':run()
