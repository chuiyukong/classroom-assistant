"""Smoke-test the packaged executable with an isolated data directory."""
from hashlib import sha1
from http.cookiejar import CookieJar
from io import BytesIO
import json
from pathlib import Path
import socket
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from flask.json.tag import TaggedJSONSerializer
from itsdangerous import URLSafeTimedSerializer
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from classroom.version import VERSION


def run():
    exe = ROOT / 'dist' / ('v' + VERSION) / 'ClassroomAssistant.exe'
    with tempfile.TemporaryDirectory(prefix='classroom-package-') as directory:
        data_dir = Path(directory)
        # Reproduce the real Windows CRLF configuration that v1.2 misidentified.
        config_dir = data_dir / 'config'
        config_dir.mkdir()
        legacy = ROOT / 'resources/templates/classroom-64-v1'
        for name in ('layout.json', 'excel-template.json'):
            (config_dir / name).write_bytes((legacy / name).read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8'))
        (config_dir / 'seat-template.xlsx').write_bytes((legacy / 'seat-template.xlsx').read_bytes())
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen([str(exe), '--headless', '--data-dir', str(data_dir), '--port', str(port)],
                                   startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(origin + '/api/v1/student/state', timeout=1) as response:
                        state = json.load(response)
                    break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None:
                        raise RuntimeError('Packaged executable stopped before HTTP server was ready')
                    time.sleep(.2)
            else:
                raise RuntimeError('Packaged server did not start')
            assert len(state['layout']['seats']) == 64
            assert state['layout']['id'] == 'classroom-64-v2'
            assert (config_dir / 'seat-template.xlsx').read_bytes() == (ROOT / 'resources/seat-template.xlsx').read_bytes()
            with urllib.request.urlopen(origin + '/', timeout=3) as response:
                assert b'modules.js' in response.read()
            with urllib.request.urlopen(origin + '/static/app.js', timeout=3) as response:
                assert response.status == 200
            try:
                urllib.request.urlopen(origin + '/api/v1/teacher/classes', timeout=3)
                raise AssertionError('Unauthenticated teacher API was accessible')
            except urllib.error.HTTPError as error:
                assert error.code == 403
            # Sign a test-only local session with this temporary installation's secret.
            # This avoids opening the user's default browser during smoke testing.
            signer = URLSafeTimedSerializer((data_dir / 'session.key').read_text(), salt='cookie-session',
                serializer=TaggedJSONSerializer(), signer_kwargs={'key_derivation': 'hmac', 'digest_method': sha1})
            cookie = signer.dumps({'teacher': True, 'csrf': 'smoke-csrf', 'client_id': 'smoke-client'})
            headers = {'Cookie': 'classroom_session=' + cookie, 'Origin': origin,
                       'X-CSRF-Token': 'smoke-csrf', 'Content-Type': 'application/json'}
            def request(path, method='GET', payload=None, raw=False):
                req = urllib.request.Request(origin + path, method=method, headers=headers,
                                             data=None if payload is None else json.dumps(payload).encode())
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.read() if raw else json.load(response)
            assert b'class-select' in request('/teacher', raw=True)
            cls = request('/api/v1/teacher/classes', 'POST', {'name': '打包测试班', 'year':2026, 'semester':'上学期'})
            assert cls['year']==2026 and cls['semester']=='上学期'
            other=request('/api/v1/teacher/classes','POST',{'name':'打包测试班','year':2026,'semester':'下学期'})
            assert other['id']!=cls['id']
            current = request('/api/v1/teacher/classes/' + cls['id'] + '/rounds', 'POST', {})
            request('/api/v1/teacher/rounds/' + current['round']['id'] + '/seats/1', 'PUT', {'name': '测试同学'})
            workbook = load_workbook(BytesIO(request('/api/v1/teacher/classes/' + cls['id'] + '/export', raw=True)))
            assert workbook['Sheet1']['D15'].value == '测试同学'
            assert workbook['Sheet1']['E18'].value == 1
            config_url = '/api/v1/teacher/layouts/classroom-64-v2/seats/2/config'
            request(config_url, 'PUT', {'disabled': True, 'note': '设备备注'})
            state = request('/api/v1/student/state')
            assert next(c for c in state['seat_configs'] if c['seat_no'] == 2)['disabled']
            assert '设备备注' not in json.dumps(state, ensure_ascii=False)
            assert request('/api/v1/teacher/info')['version'] == VERSION
            assert b'modules.js' in request('/teacher/attendance', raw=True)
            request('/api/v1/teacher/rounds/' + current['round']['id'] + '/close', 'POST', {})
            lesson = request('/api/v1/teacher/lessons', 'POST', {'round_id': current['round']['id']})
            lid = lesson['lesson']['id']
            assert request('/api/v1/teacher/rollcall/' + lid, 'POST', {})['source'] == 'seating'
            request('/api/v1/teacher/lessons/' + lid + '/open', 'POST', {})
            assert request('/api/v1/teacher/lessons/' + lid)['lesson']['attendance_deadline']
            request('/api/v1/teacher/lessons/' + lid + '/students/' + lesson['entries'][0]['student_id'], 'PUT', {'status': 'present', 'seat_no':64})
            assert request('/api/v1/teacher/lessons/' + lid)['counts']['actual'] == 1
            assert request('/api/v1/teacher/lessons/' + lid + '/export', raw=True).startswith(b'\xef\xbb\xbf')
            print('Packaged executable passed: isolated startup, bundled assets/templates, local authentication, class/round creation, seat correction, Excel export.')
        finally:
            # PyInstaller onefile creates a child; stop only this owned process tree.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], startupinfo=startup,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=10)
            time.sleep(.2)


if __name__ == '__main__':
    run()
