"""Own the local web server and scheduler for precisely one open desktop window."""
import logging
import os
import threading
import time
from pathlib import Path

from app import create_app
from runtime_lock import RuntimeLock


class RequestGate:
    def __init__(self,application,stop):
        self.application,self.stop=application,stop
        self.condition=threading.Condition();self.active=0

    def __call__(self,environ,start_response):
        tracked=environ.get('REQUEST_METHOD','GET') not in ('GET','HEAD','OPTIONS')
        with self.condition:
            if self.stop.is_set():
                start_response('503 Service Unavailable',[('Content-Type','text/plain; charset=utf-8')])
                return ['Tool đang đóng; không nhận thêm lượt mới.'.encode()]
            if tracked:self.active+=1
        def response():
            iterable=None
            try:
                iterable=self.application(environ,start_response)
                yield from iterable
            finally:
                if iterable is not None and hasattr(iterable,'close'):iterable.close()
                if tracked:
                    with self.condition:self.active-=1;self.condition.notify_all()
        return response()


def default_data_root():
    base=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local'/'share')
    return base/'ZaloFlow'


class DesktopRuntime:
    def __init__(self,data_root=None,config=None,tick=None,license=None):
        self.data_root=Path(data_root or default_data_root()).resolve()
        self.instance=self.data_root/'instance';self.instance.mkdir(parents=True,exist_ok=True)
        self.instance_lock=RuntimeLock(self.data_root/'desktop.lock').acquire()
        self.stop_event=threading.Event();self.closed=threading.Event();self.lifecycle=threading.Lock()
        settings=dict(DATABASE=str(self.instance/'zalo.sqlite3'),SESSION_COOKIE_SECURE=False,
            ZALO_QR_ENABLED=True,TRUSTED_HOSTS=['127.0.0.1','localhost'],DESKTOP_STOP_EVENT=self.stop_event)
        settings.update(config or {})
        try:self.app=create_app(settings,instance_path=self.instance)
        except BaseException:self.instance_lock.release();raise
        self.license=license
        try:
            if self.license is None and not self.app.config.get('TESTING'):
                from desktop.licensing import DesktopLicense
                self.license=DesktopLicense(self.data_root/'license')
        except BaseException:
            self.instance_lock.release();raise
        if self.license is not None:
            from desktop.license_routes import register_license_routes
            self.app.extensions['desktop_license']=self.license
            register_license_routes(self.app,self.license)
        self.gate=RequestGate(self.app,self.stop_event)
        self.tick=tick or self.app.extensions['campaign_scheduler'].tick
        self.server=None;self.server_thread=None;self.worker=None;self.url=None
        self.scheduler_lock=RuntimeLock(Path(self.app.config['DATABASE']).with_suffix('.scheduler.lock'))
        self.started=False

    def start(self):
        from waitress import create_server
        with self.lifecycle:
            if self.started or self.stop_event.is_set():raise RuntimeError('Tool không thể khởi động lại trong phiên đã đóng.')
            try:
                self.server=create_server(self.gate,host='127.0.0.1',port=0,threads=4,asyncore_loop_timeout=0.1,
                    clear_untrusted_proxy_headers=True,expose_tracebacks=False)
                self.url=f'http://127.0.0.1:{self.server.effective_port}'
                self.server_thread=threading.Thread(target=self.server.run,name='ZaloFlow-web',daemon=True)
                self.server_thread.start();self.started=True
                return self.url
            except BaseException:self.instance_lock.release();raise

    def activate(self):
        """Only called after the native application window is visible."""
        with self.lifecycle:
            if not self.started or self.stop_event.is_set():return False
            if self.worker:return False
            self.scheduler_lock.acquire()
            self.worker=threading.Thread(target=self._work,name='ZaloFlow-scheduler',daemon=True)
            self.worker.start();return True

    def _work(self):
        while not self.stop_event.is_set():
            with self.app.app_context():
                try:
                    licensed=self.license is None or self.license.refresh()
                    if not self.stop_event.is_set() and licensed:self.tick()
                except Exception:
                    self.app.extensions['campaign_manager'].db().rollback()
                    logging.getLogger('desktop').exception('Local schedule cycle failed')
            self.stop_event.wait(1)

    def begin_stop(self):
        self.stop_event.set()
        self.app.extensions['campaign_scheduler'].stopping=True

    def stop(self,timeout=None):
        """Reject new claims immediately; drain the current claims before closing."""
        self.begin_stop()
        with self.lifecycle:
            if self.closed.is_set():return True
            deadline=time.monotonic()+timeout if timeout is not None else None
            remaining=lambda:max(0,deadline-time.monotonic()) if deadline is not None else None
            if self.worker:
                self.worker.join(remaining())
                if self.worker.is_alive():return False
            with self.gate.condition:
                while self.gate.active:
                    left=remaining()
                    if left is not None and left<=0:return False
                    self.gate.condition.wait(left)
            self.app.extensions['zalo_connector'].stop_workers()
            if self.server:
                def close_channels():
                    for channel in list(self.server._map.values()):channel.close()
                # Close sockets on the asyncore thread, rather than racing its
                # select() call from the native window's shutdown thread.
                if self.server_thread and self.server_thread.is_alive():
                    self.server.trigger.pull_trigger(close_channels)
                else:close_channels()
                self.server.task_dispatcher.shutdown(timeout=5)
            if self.server_thread:self.server_thread.join(5)
            if self.server_thread and self.server_thread.is_alive():return False
            Path(self.app.config['DATABASE']).with_suffix('.scheduler.heartbeat').unlink(missing_ok=True)
            self.scheduler_lock.release();self.instance_lock.release();self.closed.set()
            return True
