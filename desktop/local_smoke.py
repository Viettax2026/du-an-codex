"""Disposable checks for the separate local desktop edition."""
import json
import re
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from desktop.local_runtime import LocalDesktopRuntime
from desktop.window import run_window


def smoke_check(report, gui=False):
    with tempfile.TemporaryDirectory(prefix='zaloflow-local-smoke-',ignore_cleanup_errors=True) as folder:
        runtime=LocalDesktopRuntime(folder)
        try:
            runtime.start()
            assert runtime.license is None and runtime.license_worker is None
            browser=build_opener(HTTPCookieProcessor(CookieJar()))
            with browser.open(runtime.url+'/register',timeout=10) as response:
                page=response.read().decode('utf-8')
            assert 'Bản quyền / Nhập key' not in page
            csrf=re.search(r'name="csrf" value="([a-f0-9]+)"',page).group(1)
            values=dict(csrf=csrf,name='Local owner',username='local-owner',password='synthetic-owner-password')
            with browser.open(Request(runtime.url+'/register',data=urlencode(values).encode()),timeout=10) as response:
                assert 'Đã tạo tài khoản quản trị đầu tiên' in response.read().decode('utf-8')
            try:urlopen(runtime.url+'/desktop/license',timeout=10)
            except HTTPError as error:assert error.code==404
            else:raise AssertionError('Local edition exposed an activation page')
            assert runtime.app.extensions['zalo_connector'].available(),'Missing bundled connector'
            from desktop.smoke_recovery import verify_admin_flow,verify_recovery_flow
            assert verify_admin_flow(runtime.url,'local-owner','synthetic-owner-password')
            assert verify_recovery_flow(runtime.url)
            if gui:run_window(runtime,smoke=True,title='ZaloFlow Local')
            else:
                runtime.activate();deadline=time.monotonic()+10
                heartbeat=Path(runtime.app.config['DATABASE']).with_suffix('.scheduler.heartbeat')
                while not heartbeat.exists() and time.monotonic()<deadline:time.sleep(.05)
                assert heartbeat.exists()
                assert runtime.stop(timeout=10)
            Path(report).write_text(json.dumps(dict(ok=True,gui=gui,stopped=runtime.closed.is_set(),
                no_key=True,node_available=True,local_accounts=True,password_recovery=True,
                activation_route_absent=True,license_worker_absent=True)),encoding='utf-8')
        finally:runtime.stop()
