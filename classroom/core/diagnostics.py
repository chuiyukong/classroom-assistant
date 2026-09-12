"""Bounded local diagnostics: no names, bodies, query strings, cookies or SQL."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import platform
import sqlite3
from uuid import uuid4
from collections import Counter
from flask import g, request, has_request_context


class Diagnostics:
    def __init__(self, root):
        self.root = Path(root)
        self.logger = logging.getLogger('classroom.diagnostics.' + uuid4().hex)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = RotatingFileHandler(self.root / 'diagnostics.jsonl', maxBytes=2_000_000, backupCount=4, encoding='utf-8', delay=True)
        self.logger.addHandler(self.handler)
        self.lock = threading.Lock()
        self.active = {}
        self.counts = Counter()
        self.db_counts = Counter()
        self.started = time.monotonic()
        self.sample_second = 0
        self.sample_count = 0
        self.last_stacks = 0
        self.status = '正在启动'
        self.stop_event = threading.Event()

    def event(self, event, **fields):
        self.logger.info(json.dumps(dict(time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), event=event, pid=os.getpid(), **fields), ensure_ascii=False))

    def sampled(self, event, **fields):
        with self.lock:
            second = int(time.monotonic())
            if second != self.sample_second:
                self.sample_second, self.sample_count = second, 0
            self.sample_count += 1
            if self.sample_count > 5:
                self.counts['suppressed_details'] += 1
                return
        self.event(event, **fields)

    def attach(self, app):
        @app.before_request
        def diagnostic_begin():
            g.diagnostic_id = uuid4().hex[:12]
            g.diagnostic_start = time.monotonic()
            route = str(request.url_rule) if request.url_rule else 'unmatched'
            with self.lock:
                self.active[g.diagnostic_id] = (g.diagnostic_start, route, request.method)
        @app.after_request
        def diagnostic_end(response):
            rid = getattr(g, 'diagnostic_id', None)
            if rid:
                duration = round((time.monotonic()-g.diagnostic_start)*1000, 1)
                with self.lock:
                    item = self.active.pop(rid, None)
                    self.counts['requests'] += 1
                    self.counts['status_'+str(response.status_code)] += 1
                response.headers['X-Request-ID'] = rid
                if item and (duration >= 500 or response.status_code >= 500):
                    self.sampled('request_slow_or_failed', request_id=rid, route=item[1], method=item[2], elapsed_ms=duration, status=response.status_code)
            return response
        @app.teardown_request
        def diagnostic_cleanup(error):
            with self.lock:
                self.active.pop(getattr(g, 'diagnostic_id', None), None)

    def db_event(self, write, wait_ms, duration_ms, error=None):
        with self.lock:
            self.db_counts['write' if write else 'read'] += 1
            if error:self.db_counts['errors'] += 1
            if wait_ms >= 100:self.db_counts['lock_waits'] += 1
        if error or wait_ms >= 100 or duration_ms >= 500:
            self.sampled('database', request_id=getattr(g,'diagnostic_id',None) if has_request_context() else None, write=write, begin_wait_ms=round(wait_ms,1), transaction_ms=round(duration_ms,1), error_type=type(error).__name__ if error else None, sqlite_code=getattr(error,'sqlite_errorname',None))

    def stacks(self, reason):
        now=time.monotonic()
        if now-self.last_stacks < 60:return
        self.last_stacks=now
        frames=sys._current_frames()
        stacks=[]
        for thread in threading.enumerate():
            if thread.ident in frames and (thread.name.startswith('waitress') or thread.name=='classroom-server'):
                stacks.append(dict(thread=thread.name, frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_stack(frames[thread.ident])[-16:]]))
        self.event('thread_stacks', reason=reason, threads=stacks)

    def monitor(self, server, server_thread, port, addresses):
        import urllib.request
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        from classroom.version import VERSION
        self.event('server_started', version=VERSION, python=platform.python_version(), sqlite=sqlite3.sqlite_version, platform=platform.platform(), ppid=os.getppid(), frozen=bool(getattr(sys,'frozen',False)), port=port, threads=server.adj.threads, connection_limit=server.adj.connection_limit, channel_timeout=server.adj.channel_timeout, cleanup_interval=server.adj.cleanup_interval, addresses=addresses())
        failures=0;cycle=0;previous_ips=None
        while not self.stop_event.wait(5):
            alive=server_thread.is_alive() if server_thread else True
            start=time.monotonic();health='ok'
            try:
                with opener.open('http://127.0.0.1:'+str(port)+'/health',timeout=2) as r:
                    if r.status!=200:health='http_'+str(r.status)
            except Exception as e:health=type(e).__name__
            failures=0 if health=='ok' else failures+1
            self.status='服务已停止' if not alive else ('服务响应缓慢，请保存诊断日志' if failures else '服务正常')
            dispatcher=server.task_dispatcher
            with dispatcher.lock:
                queue=len(dispatcher.queue);workers=len(dispatcher.threads);active_workers=dispatcher.active_count
            with self.lock:
                oldest=max((time.monotonic()-x[0] for x in self.active.values()),default=0)
                inflight=len(self.active);counts=dict(self.counts);db_counts=dict(self.db_counts)
                self.counts.clear();self.db_counts.clear()
            self.event('heartbeat', server_alive=alive, health=health, probe_ms=round((time.monotonic()-start)*1000,1), queue=queue, workers=workers, active_workers=active_workers, channels=len(server._map), inflight=inflight, oldest_ms=round(oldest*1000,1), requests=counts, database=db_counts, cpu_seconds=round(time.process_time(),2), db_bytes=self._size('classroom.sqlite3'), wal_bytes=self._size('classroom.sqlite3-wal'))
            if failures>=2 or oldest>=10 or queue>=workers:self.stacks('health_or_queue')
            if cycle%6==0:
                ips=addresses()
                if ips!=previous_ips:self.event('network_addresses',addresses=ips);previous_ips=ips
            cycle+=1
            if not alive:break

    def _size(self,name):
        try:return (self.root/name).stat().st_size
        except OSError:return 0

    def close(self):
        self.stop_event.set()
        self.handler.close()
        self.logger.removeHandler(self.handler)


class WaitressDiagnosticHandler(logging.Handler):
    def __init__(self, diagnostics):
        super().__init__();self.diagnostics=diagnostics
    def emit(self, record):
        template=str(record.msg)
        if template.startswith('Task queue depth'):
            self.diagnostics.sampled('waitress_queue',depth=record.args[0] if record.args else None)
        elif 'connection limit' in template:
            self.diagnostics.sampled('waitress_connection_limit',level=record.levelname,accepting='dropped below' in template)
        elif record.levelno>=logging.WARNING:
            self.diagnostics.sampled('waitress_warning',level=record.levelname,error_type=record.exc_info[0].__name__ if record.exc_info else None)
