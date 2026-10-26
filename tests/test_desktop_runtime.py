"""Windows-compatible desktop lifecycle tests; no real Zalo traffic or GUI."""
import json
import socket
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen

import pytest

from desktop.runtime import DesktopRuntime
from runtime_lock import RuntimeLock
from zalo_connector import QRConnector
from test_workflow import post,register,token


def runtime(tmp_path,**kwargs):
    return DesktopRuntime(tmp_path/'Dữ liệu Viettax',config={'TESTING':True,'ZALO_QR_ENABLED':False},**kwargs)


def query(r,sql):
    with sqlite3.connect(r.app.config['DATABASE']) as db:return db.execute(sql).fetchall()


def test_window_controls_scheduler_and_close_preserves_local_data_and_releases_port(tmp_path):
    called=threading.Event();r=runtime(tmp_path,tick=called.set)
    assert Path(r.app.instance_path)==r.instance
    key=(r.instance/'session.key').read_bytes()
    try:
        url=r.start();assert urlsplit(url).hostname=='127.0.0.1'
        assert not called.is_set() and r.worker is None
        with urlopen(url+'/login',timeout=5) as response:assert response.status==200
        assert r.activate();assert called.wait(3)
        with r.app.app_context():
            db=r.app.extensions['campaign_manager'].db();db.execute("INSERT INTO users(name,username,password) VALUES('Local','local','unused')");db.commit()
        assert r.stop(5)
        assert not r.worker.is_alive() and not r.server_thread.is_alive()
        assert not Path(r.app.config['DATABASE']).with_suffix('.scheduler.heartbeat').exists()
        with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',int(urlsplit(url).port)))!=0
        reopened=runtime(tmp_path,tick=lambda:None)
        try:
            assert (reopened.instance/'session.key').read_bytes()==key
            assert query(reopened,'SELECT username FROM users')==[('local',)]
            assert reopened.worker is None
        finally:assert reopened.stop(5)
    finally:r.stop(5)


def test_single_desktop_and_scheduler_lock_work_across_processes(tmp_path):
    r=runtime(tmp_path,tick=lambda:None)
    try:
        with pytest.raises(RuntimeError,match='tiến trình khác'):runtime(tmp_path)
        r.start();r.activate()
        result=r.app.test_cli_runner().invoke(args=['run-scheduler','--once'])
        assert result.exit_code==1 and 'tiến trình khác' in result.output
        script="from runtime_lock import RuntimeLock\nimport sys\ntry: RuntimeLock(sys.argv[1]).acquire()\nexcept RuntimeError: sys.exit(7)\n"
        child=subprocess.run([sys.executable,'-c',script,str(r.scheduler_lock.path)],capture_output=True,timeout=10)
        assert child.returncode==7,child.stderr.decode(errors='replace')
        assert r.stop(5)
        with RuntimeLock(r.scheduler_lock.path):pass
    finally:r.stop(5)


def test_close_waits_for_current_scheduled_work_and_never_starts_a_second_cycle(tmp_path):
    entered=threading.Event();release=threading.Event();calls=[]
    def work():calls.append(1);entered.set();assert release.wait(5)
    r=runtime(tmp_path,tick=work)
    try:
        r.start();r.activate();assert entered.wait(3)
        assert not r.stop(.01);assert r.worker.is_alive()
        assert not r.activate()
        release.set();assert r.stop(5);assert calls==[1]
    finally:release.set();r.stop(5)


def test_close_drains_committed_manual_send_but_blocks_new_http_and_direct_claims(tmp_path):
    r=runtime(tmp_path);client=r.app.test_client();register(client)
    post(client,'/accounts',{'name':'Local Zalo'})
    post(client,'/contacts',{'name':'Lan','phone':'0901234567','consent':'on'})
    post(client,'/contacts',{'name':'Next','phone':'0912345678','consent':'on'})
    post(client,'/campaigns',{'name':'Local','message':'Hello','account_id':'1'})
    connector=r.app.extensions['zalo_connector'];connector.status=Mock(return_value={'state':'connected'})
    connector.message_action=Mock(return_value={'state':'resolved','uid':'123','name':'Lan'})
    r.app.config['ZALO_QR_ENABLED']=True
    post(client,'/campaigns/1/prepare-send',{'account_id':'1','contact_id':'1'})
    post(client,'/campaigns/1/prepare-send',{'account_id':'1','contact_id':'2'})
    csrf=token(client);cookie=client.get_cookie('session').value
    entered=threading.Event();release=threading.Event();results=[]
    def sending(*args,**kwargs):entered.set();assert release.wait(10);return {'state':'sent','message_id':'mock-accepted'}
    connector.message_action=Mock(side_effect=sending)
    def send_http():
        request=Request(r.url+'/campaigns/1/send/1',data=urlencode({'csrf':csrf,'confirm_send':'yes'}).encode(),headers={'Cookie':'session='+cookie})
        try:
            with urlopen(request,timeout=15) as response:results.append(response.status)
        except Exception as error:results.append(error)
    r.start();thread=threading.Thread(target=send_http);thread.start()
    try:
        assert entered.wait(5)
        assert query(r,'SELECT state FROM message_sends WHERE id=1')==[('sending',)]
        assert not r.stop(.01)
        with pytest.raises(HTTPError) as response:urlopen(r.url+'/login',timeout=5)
        assert response.value.code==503
        blocked=post(client,'/campaigns/1/send/2',{'confirm_send':'yes'})
        assert blocked.status_code==409 and connector.message_action.call_count==1
        release.set();thread.join(10);assert not thread.is_alive()
        assert r.stop(5)
        assert query(r,'SELECT state FROM message_sends ORDER BY id')==[('sent',),('prepared',)]
        assert query(r,'SELECT count(*) FROM campaign_attempts')==[(1,)]
    finally:release.set();thread.join(10);r.stop(5)


def test_bundled_node_and_qr_shutdown_keep_saved_credentials(tmp_path):
    source=tmp_path/'source';sdk=source/'connector'/'node_modules'/'zca-js';sdk.mkdir(parents=True)
    node=source/'runtime'/'node.exe';node.parent.mkdir();node.write_bytes(b'test-only')
    connector=QRConnector(tmp_path/'instance',source)
    assert connector.node()==str(node) and connector.available()
    connector.root.mkdir(parents=True);key=connector.root/'auth.key';key.write_bytes(b'synthetic-key')
    process=Mock();process.poll.return_value=None;connector.jobs[(1,1)]=process
    connector.stop_workers();process.terminate.assert_called_once();assert key.read_bytes()==b'synthetic-key' and not connector.jobs


def test_node_worker_uses_utf8_and_windows_environment_without_leaking_other_variables(tmp_path,monkeypatch):
    source=tmp_path/'source';connector=QRConnector(tmp_path/'instance',source,node_binary=str(tmp_path/'node.exe'))
    connector.available=Mock(return_value=True);connector.status=Mock(return_value={'state':'connected'})
    import uuid
    base=connector.account_path(1,1);base.mkdir(parents=True);base.joinpath('current.json').write_text(json.dumps({'run_id':str(uuid.uuid4())}))
    monkeypatch.setenv('SystemRoot','C:\\Windows');monkeypatch.setenv('UNRELATED_SECRET','do-not-forward')
    run=Mock(return_value=SimpleNamespace(stdout=json.dumps({'state':'resolved','uid':'123','name':'Trần'})))
    monkeypatch.setattr('zalo_connector.subprocess.run',run)
    assert connector.message_action(1,1,'resolve',phone='0901234567')['name']=='Trần'
    options=run.call_args.kwargs
    assert options['encoding']=='utf-8' and options['env']['SystemRoot']=='C:\\Windows'
    assert 'UNRELATED_SECRET' not in options['env']
    assert run.call_args.args[0][0]==str(tmp_path/'node.exe')


def test_native_close_handler_waits_for_runtime_shutdown_before_destroying_window(monkeypatch):
    from desktop.main import run_window
    destroyed=threading.Event()
    class Event(list):
        def __iadd__(self,callback):self.append(callback);return self
    events=SimpleNamespace(shown=Event(),closing=Event(),loaded=Event())
    class Window:
        def __init__(self):self.events=events
        def set_title(self,title):assert 'Đang dừng' in title
        def destroy(self):
            assert all(callback() is True for callback in events.closing)
            destroyed.set()
    window=Window();r=SimpleNamespace(url='http://127.0.0.1:1234',data_root=Path('.'),activate=Mock(),begin_stop=Mock(),stop=Mock())
    def start(**kwargs):
        for callback in events.shown:callback()
        assert all(callback() is False for callback in events.closing)
        assert destroyed.wait(3)
    monkeypatch.setitem(sys.modules,'webview',SimpleNamespace(create_window=lambda *args,**kwargs:window,start=start))
    run_window(r);r.activate.assert_called_once();assert r.stop.called and r.begin_stop.called
