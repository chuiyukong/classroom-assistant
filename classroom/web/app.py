import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import secrets
import sqlite3
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException

from classroom.classes.service import ClassService
from classroom.core.config import prepare_data
from classroom.core.db import Database
from classroom.core.errors import AppError
from classroom.exports.excel import ExcelExportService
from classroom.layouts.service import LayoutService
from classroom.seating.service import SeatingService, UNSET
from classroom.version import VERSION
from classroom.attendance.service import AttendanceService, STATUSES
from classroom.rollcall.service import RollCallService
import csv
from io import StringIO, BytesIO


def create_app(data_dir=None, bootstrap_key=None):
    root, secret, port = prepare_data(data_dir)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secret, MAX_CONTENT_LENGTH=16384,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_NAME="classroom_session", DATA_DIR=root, PORT=port)
    key = bootstrap_key or secrets.token_urlsafe(32)
    app.config["BOOTSTRAP_KEY"] = key
    log = RotatingFileHandler(root / "application.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    app.logger.addHandler(log)
    database = Database(root / "classroom.sqlite3")
    # Owner explicitly waived backup for the v1 -> v2 TEST-data upgrade.
    # The exception is schema-specific; later migrations retain normal backups.
    database.migrate(skip_backup_for_version=2)
    layouts = LayoutService(database, root / "config")
    classes = ClassService(database)
    settings = json.loads((root / 'settings.json').read_text(encoding='utf-8'))
    limit_ip = settings.get('limit_one_registration_per_ip', True)
    if type(limit_ip) is not bool:
        raise ValueError('limit_one_registration_per_ip 必须为 true 或 false')
    seating = SeatingService(database, layouts, limit_ip=limit_ip)
    exports = ExcelExportService(seating, root / "config")
    attendance = AttendanceService(database, seating)
    rollcall = RollCallService(database, attendance)
    app.extensions.update(attendance=attendance, rollcall=rollcall)
    app.extensions.update(database=database, layouts=layouts, classes=classes, seating=seating, exports=exports,
                          students=seating.students, seat_configs=seating.seats)

    def teacher_origin():
        # Validate Host as well as socket address: blocks DNS rebinding.
        parsed = urlsplit(request.host_url)
        return request.remote_addr in ("127.0.0.1", "::1") and parsed.hostname in ("127.0.0.1", "localhost", "::1")

    @app.before_request
    def guard():
        teacher = request.path.startswith("/teacher") or request.path.startswith("/api/v1/teacher/")
        if teacher and not teacher_origin():
            raise AppError("教师管理仅允许在教师机本地打开", 403, "teacher_local_only")
        if request.path.startswith("/api/v1/teacher/") and not session.get("teacher"):
            raise AppError("请从教师机启动窗口打开管理页面", 403, "teacher_session_required")
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if request.headers.get("Origin") != request.host_url.rstrip("/"):
                raise AppError("请求来源无效，请从登记页面操作", 403, "invalid_origin")
            expected = session.get("csrf", "")
            if not expected or not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), expected.encode()):
                raise AppError("页面会话已失效，请刷新后重试", 403, "invalid_csrf")
            if not request.is_json:
                raise AppError("请求必须使用 JSON", 415)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.errorhandler(AppError)
    def expected_error(error):
        return jsonify(error={"code": error.code, "message": error.message}), error.status

    @app.errorhandler(sqlite3.OperationalError)
    def busy(error):
        app.logger.exception("Database operation failed")
        return jsonify(error={"code": "database_unavailable", "message": "保存暂未完成，请稍后重试；若持续出现请联系教师"}), 503

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return jsonify(error={"code": "http_error", "message": "请求格式或地址无效"}), error.code
        app.logger.exception("Unhandled application error")
        return jsonify(error={"code": "internal_error", "message": "操作未完成，请联系教师查看运行日志"}), 500

    def init_session():
        session.setdefault("csrf", secrets.token_urlsafe(24))
        session.setdefault("client_id", secrets.token_urlsafe(24))

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise AppError("请求内容必须为对象")
        return data

    @app.get("/")
    def student_page():
        init_session()
        return render_template("student.html", csrf=session["csrf"])

    @app.get("/teacher")
    def teacher_page():
        supplied = request.args.get("key", "")
        if supplied and hmac.compare_digest(supplied.encode(), key.encode()):
            session["teacher"] = True
            init_session()
            return redirect("/teacher")
        if not session.get("teacher"):
            raise AppError("请从教师机启动窗口点击“打开教师管理”", 403)
        return render_template("teacher.html", csrf=session["csrf"])

    @app.get("/api/v1/student/state")
    def state():
        init_session()
        return jsonify(seating.active(session["client_id"], request.remote_addr))

    @app.post("/api/v1/student/registrations")
    def submit():
        data = body()
        return jsonify(seating.submit(data.get("round_id"), data.get("seat_no"), data.get("name"),
                                      session["client_id"], data.get("request_id"), request.remote_addr))

    @app.get("/api/v1/teacher/info")
    def info():
        return jsonify(data_dir=str(root), urls=app.config.get("STUDENT_URLS", []), version=VERSION,
                       limit_one_registration_per_ip=limit_ip)

    @app.get('/api/v1/teacher/current')
    def current():
        return jsonify(seating.get_current_arrangement())

    @app.post('/api/v1/teacher/classes/<class_id>/publish')
    def publish(class_id):
        body()
        seating.publish_class(class_id)
        return jsonify(ok=True)

    @app.get('/api/v1/teacher/classes/<class_id>/students')
    def students(class_id):
        return jsonify(students=seating.students.list(class_id))

    @app.post('/api/v1/teacher/classes/<class_id>/students')
    def add_student(class_id):
        data = body()
        return jsonify(seating.students.create(class_id, data.get('name'), data.get('note', ''))), 201

    @app.put('/api/v1/teacher/students/<student_id>/note')
    def student_note(student_id):
        seating.students.update_note(student_id, body().get('note'))
        return jsonify(ok=True)

    @app.put('/api/v1/teacher/layouts/<layout_id>/seats/<int:seat_no>/config')
    def seat_config(layout_id, seat_no):
        data = body()
        seating.seats.update(layout_id, seat_no, data.get('disabled'), data.get('note'))
        return jsonify(ok=True)

    @app.get("/api/v1/teacher/classes")
    def list_classes():
        return jsonify(classes=classes.list(request.args.get('deleted') == '1'), active_class_id=seating.get_current_arrangement()['active_class_id'])

    @app.post("/api/v1/teacher/classes")
    def new_class():
        return jsonify(classes.create(body().get("name"))), 201

    @app.get("/api/v1/teacher/classes/<class_id>/rounds")
    def list_rounds(class_id):
        return jsonify(rounds=seating.rounds(class_id))

    @app.post("/api/v1/teacher/classes/<class_id>/rounds")
    def open_round(class_id):
        data = body()
        return jsonify(seating.open_round(class_id, data.get('expected_current_id', UNSET))), 201

    @app.post("/api/v1/teacher/rounds/<round_id>/close")
    def close_round(round_id):
        body()
        seating.close_round(round_id)
        return jsonify(ok=True)

    @app.get("/api/v1/teacher/classes/<class_id>/arrangement")
    def arrangement(class_id):
        return jsonify(seating.get_arrangement(class_id, request.args.get("round_id")))

    @app.put("/api/v1/teacher/rounds/<round_id>/seats/<int:seat_no>")
    def correct(round_id, seat_no):
        data = body()
        seating.correct(round_id, seat_no, data.get('name'), data.get('student_note', UNSET),
                        data.get('student_id'), data.get('force_new', False))
        return jsonify(ok=True)

    @app.get("/api/v1/teacher/classes/<class_id>/export")
    def export(class_id):
        output, filename = exports.export(class_id, request.args.get("round_id"))
        return send_file(output, as_attachment=True, download_name=filename,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get('/teacher/<module>')
    def module_page(module):
        if module not in ('attendance', 'rollcall', 'data'):
            raise AppError('页面不存在', 404)
        if not session.get('teacher'):
            raise AppError('请从启动窗口打开教师管理', 403)
        return render_template('module.html', csrf=session['csrf'], module=module, teacher=True)

    @app.get('/attendance')
    def attendance_page():
        init_session()
        return render_template('module.html', csrf=session['csrf'], module='attendance', teacher=False)

    @app.post('/api/v1/teacher/classes/manage')
    def manage_classes():
        data = body()
        if data.get('action') not in ('delete', 'restore'):
            raise AppError('管理操作无效')
        ids = data.get('ids')
        with database.connect(write=True) as db:
            classes.set_deleted(db, ids, data['action'] == 'delete')
            if data['action'] == 'delete':
                seating.retire_classes(db, ids)
                attendance.retire_classes(db, ids)
        return jsonify(ok=True)

    @app.get('/api/v1/teacher/lessons/current')
    def lesson_current():
        return jsonify(attendance.state())

    @app.post('/api/v1/teacher/lessons')
    def lesson_start():
        data = body()
        return jsonify(attendance.start(data.get('round_id'), data.get('late_after', 5))), 201

    @app.get('/api/v1/teacher/lessons')
    def lesson_history():
        return jsonify(lessons=attendance.history(request.args.get('class_id'), request.args.get('day')))

    @app.get('/api/v1/teacher/lessons/<lid>')
    def lesson_detail(lid):
        return jsonify(attendance.detail(lid))

    @app.post('/api/v1/teacher/lessons/<lid>/<action>')
    def lesson_action(lid, action):
        body()
        return jsonify(attendance.action(lid, action))

    @app.put('/api/v1/teacher/lessons/<lid>/students/<sid>')
    def attendance_correct(lid, sid):
        data = body()
        if data.get('status') == 'present':
            return jsonify(attendance.checkin(lid, sid, data.get('seat_no'), teacher=True))
        attendance.mark(lid, sid, data.get('status'))
        return jsonify(ok=True)

    @app.get('/api/v1/student/attendance')
    def student_attendance():
        init_session()
        return jsonify(attendance.state(True, request.remote_addr, session['client_id']))

    @app.post('/api/v1/student/attendance')
    def student_checkin():
        data = body()
        return jsonify(attendance.checkin(data.get('lesson_id'), data.get('student_id'), data.get('seat_no'), request.remote_addr, session['client_id']))

    @app.post('/api/v1/teacher/rollcall/<lid>')
    def draw(lid):
        body()
        return jsonify(rollcall.draw(lid))

    @app.get('/api/v1/teacher/rollcall/<lid>')
    def draws(lid):
        return jsonify(draws=rollcall.history(lid))

    @app.get('/api/v1/teacher/lessons/<lid>/export')
    def attendance_export(lid):
        data = attendance.detail(lid)
        stream = StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['班级','上课时间','签到开始','学生编号','姓名','原座位','签到座位','考勤状态','签到时间','迟到秒数'])
        def safe(value):
            value = str(value or '')
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        for r in data['entries']:
            writer.writerow([safe(data['lesson']['class_name']), data['lesson']['started_at'], data['lesson']['attendance_started_at'], r['student_id'], safe(r['name']), r['original_seat'], r['seat_no'], STATUSES[r['status']] if data['lesson']['attendance_started_at'] else '未开展考勤', r['signed_at'], r['late_seconds']])
        return send_file(BytesIO(stream.getvalue().encode('utf-8-sig')), as_attachment=True, download_name='考勤日志_' + lid[:8] + '.csv', mimetype='text/csv; charset=utf-8')

    return app
