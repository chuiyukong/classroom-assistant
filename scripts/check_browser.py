"""Real Chromium + HTTP integration checks. Writes only test-results and temp data."""
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from waitress import create_server
from classroom.web.app import create_app


def run():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='classroom-browser-') as folder:
        app = create_app(folder, bootstrap_key='browser-test-key')
        # TEST-ONLY transport simulation: production never trusts this header.
        # All browser contexts run on one host; assign distinct virtual LAN IPs.
        real_wsgi = app.wsgi_app
        def test_transport(environ, start_response):
            if environ.get('HTTP_X_TEST_DEVICE_IP'):
                environ['REMOTE_ADDR'] = environ['HTTP_X_TEST_DEVICE_IP']
            return real_wsgi(environ, start_response)
        app.wsgi_app = test_transport
        server = create_server(app, host='127.0.0.1', port=0, threads=12, connection_limit=150)
        origin = 'http://127.0.0.1:' + str(server.effective_port)
        app.config['STUDENT_URLS'] = [origin + '/']
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                admin_context = browser.new_context(viewport={'width': 1440, 'height': 1100})
                admin = admin_context.new_page()
                errors = []
                admin.on('pageerror', lambda error: errors.append(str(error)))
                admin.on('dialog', lambda dialog: dialog.accept())
                admin.goto(origin + '/teacher?key=browser-test-key')
                admin.locator('#class-name').fill('高一（3）班')
                admin.get_by_role('button', name='添加班级').click()
                admin.get_by_role('button', name='发起新登记').click()
                admin.locator('#round-status').filter(has_text='登记开放中').wait_for()
                ctx_a = browser.new_context(viewport={'width': 1366, 'height': 900}, extra_http_headers={'X-Test-Device-IP': '10.0.0.1'})
                ctx_b = browser.new_context(viewport={'width': 1024, 'height': 768}, extra_http_headers={'X-Test-Device-IP': '10.0.0.2'})
                a, b = ctx_a.new_page(), ctx_b.new_page()
                for page in (a, b):
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/')
                    page.locator('[data-seat="1"]').click()
                a.locator('#student-name').fill('林晓')
                b.locator('#student-name').fill('陈晨')
                a.locator('#submit-seat').click()
                a.locator('#notice').filter(has_text='登记成功').wait_for()
                duplicate_context = browser.new_context(extra_http_headers={'X-Test-Device-IP': '10.0.0.1'})
                duplicate_page = duplicate_context.new_page(); duplicate_page.goto(origin + '/')
                duplicate_page.locator('#hint').filter(has_text='这台电脑已登记 1').wait_for()
                assert duplicate_page.locator('[data-seat="4"]').is_disabled()
                b.locator('#submit-seat').click()
                b.locator('#dialog-error').filter(has_text='该座位已登记').wait_for()
                b.locator('#dialog-close').click()
                b.locator('[data-seat="2"]').click()
                b.locator('#student-name').fill('陈晨')
                b.locator('#submit-seat').click()
                b.locator('#notice').filter(has_text='登记成功').wait_for()
                ctx_c = browser.new_context(extra_http_headers={'X-Test-Device-IP': '10.0.0.3'})
                c = ctx_c.new_page(); c.goto(origin + '/')
                c.locator('[data-seat="3"]').click(); c.locator('#student-name').fill('林晓'); c.locator('#submit-seat').click()
                c.locator('#dialog-error').filter(has_text='同名').wait_for()
                c.locator('#dialog-close').click()
                admin.locator('[data-seat="3"]').click()
                admin.locator('#student-name').fill('林晓'); admin.locator('#new-identity').check()
                admin.locator('#student-note').fill('同名的另一位同学')
                admin.locator('#submit-seat').click()
                admin.locator('#dialog').wait_for(state='hidden')
                c.locator('[data-seat="3"]').filter(has_text='林晓').wait_for()
                admin.locator('[data-seat="2"]').filter(has_text='陈晨').wait_for()
                admin.locator('[data-seat="2"]').click()
                admin.locator('#student-name').fill('陈晨同学')
                admin.locator('#student-note').fill('长期请假测试备注')
                admin.locator('#submit-seat').click()
                b.locator('[data-seat="2"]').filter(has_text='陈晨同学').wait_for()
                assert '长期请假测试备注' not in b.content()
                admin.locator('[data-seat="4"]').click()
                admin.locator('#seat-disabled').check()
                admin.locator('#device-note').fill('键盘损坏测试备注')
                admin.locator('#device-save').click()
                admin.locator('#device-message').filter(has_text='已保存').wait_for()
                admin.locator('#dialog-close').click()
                b.locator('[data-seat="4"]').filter(has_text='设备停用').wait_for()
                assert b.locator('[data-seat="4"]').is_disabled()
                assert '键盘损坏测试备注' not in b.content()
                admin.locator('[data-seat="4"]').click()
                admin.locator('#seat-disabled').uncheck()
                admin.locator('#device-save').click()
                admin.locator('#device-message').filter(has_text='已保存').wait_for()
                admin.locator('#dialog-close').click()
                assert admin.locator('#student-notes').count()==0
                ctx_b.set_offline(True)
                b.locator('#connection.offline').wait_for(timeout=20000)
                assert b.locator('[data-seat="3"]').is_disabled()
                ctx_b.set_offline(False)
                b.locator('#connection:not(.offline)').wait_for(timeout=20000)
                admin.locator('#close-round').click()
                a.wait_for_url('**/attendance')
                assert a.locator('[data-seat="3"]').is_disabled()
                with admin.expect_download() as download:
                    admin.locator('#export').click()
                download.value.save_as(output / 'browser-export.xlsx')
                admin.locator('#start-round').click()
                admin.locator('#round-status').filter(has_text='座位登记开放中').wait_for()
                a.locator('#seating-nav').wait_for(); a.locator('#seating-nav').click()
                b.goto(origin + '/')
                assert a.locator('[data-seat="1"]').is_enabled()
                admin.locator('#round-select').select_option(index=1)
                admin.locator('#round-status').filter(has_text='历史存档').wait_for()
                assert admin.locator('[data-seat="1"]').is_disabled()
                admin.locator('#round-select').select_option(index=0)
                admin.locator('#round-status').filter(has_text='座位登记开放中').wait_for()

                # Real HTTP: 64 cookie-isolated clients all submit to the running server.
                cls = app.extensions['classes'].list()[0]
                current = app.extensions['seating'].get_arrangement(cls['id'])
                rid = current['round']['id']
                def prepare_client(n):
                    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
                    with client.open(origin + '/', timeout=20) as response:
                        html = response.read().decode()
                    csrf = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
                    return n, client, csrf
                with ThreadPoolExecutor(max_workers=16) as executor:
                    clients = list(executor.map(prepare_client, range(1, 65)))
                def submit(info):
                    n, client, csrf = info
                    body = json.dumps({'round_id': rid, 'seat_no': n, 'name': '同学' + str(n), 'request_id': 'http-' + str(n)}).encode()
                    request = urllib.request.Request(origin + '/api/v1/student/registrations', data=body,
                        headers={'Content-Type': 'application/json', 'Origin': origin, 'X-CSRF-Token': csrf, 'X-Test-Device-IP': '10.0.1.' + str(n)})
                    with client.open(request, timeout=30) as response:
                        return json.load(response)
                with ThreadPoolExecutor(max_workers=64) as executor:
                    results = list(executor.map(submit, clients))
                assert len(results) == 64 and all(r['accepted'] for r in results)
                assert app.extensions['seating'].get_arrangement(cls['id'])['count'] == 64
                admin.locator('#count').filter(has_text='64').wait_for()
                admin.screenshot(path=str(output / 'teacher-full.png'), full_page=True)
                with admin.expect_download() as full_download:
                    admin.locator('#export').click()
                full_download.value.save_as(output / 'all-64-export.xlsx')
                # A partly filled arrangement makes the student page easy to inspect.
                for n in range(49, 65):
                    app.extensions['seating'].correct(rid, n, '')
                a.locator('#count').filter(has_text='48').wait_for()
                b.locator('#count').filter(has_text='48').wait_for()
                a.screenshot(path=str(output / 'student.png'), full_page=True)
                b.screenshot(path=str(output / 'student-1024.png'), full_page=True)
                admin.screenshot(path=str(output / 'teacher.png'), full_page=True)
                assert not errors, errors
                browser.close()
                print('Browser checks passed: IP across browser contexts, device state, private student notes, registration conflicts, archives, reconnect, Excel; 64 HTTP clients with simulated distinct IPs; no JS errors.')
        finally:
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(timeout=3)
            for handler in list(app.logger.handlers):
                if hasattr(handler, 'baseFilename'):
                    app.logger.removeHandler(handler)
                    handler.close()


if __name__ == '__main__':
    run()
