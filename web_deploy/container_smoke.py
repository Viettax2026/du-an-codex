"""Run only in the disposable Ubuntu container; no real accounts or Zalo sends."""
import http.client
import http.cookiejar
import json
import os
import re
import signal
import ssl
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

# This script is launched from the extracted package on Ubuntu 24.04.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from web_deploy.configure import render


def main():
    domain, name = 'web-smoke.example', 'web-smoke'
    root = Path('/opt/web-smoke')
    assert Path('/etc/os-release').read_text().find('24.04') >= 0
    assert not (root / 'desktop').exists() and not (root / 'license_system').exists()
    node = root / 'runtime/node/bin/node'
    environment = dict(os.environ, PATH=str(node.parent) + ':' + os.environ['PATH'], COOKIE_SECURE='1', ZALO_QR_ENABLED='1')
    subprocess.run([str(node), '--input-type=module', '-e', "import('zca-js').then(() => console.log('Zalo SDK import OK'))"], cwd=root / 'connector', env=environment, check=True)
    cert = Path('/etc/letsencrypt/live') / domain
    cert.mkdir(parents=True)
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=' + domain,
                    '-addext', 'subjectAltName=DNS:' + domain + ',IP:127.0.0.1', '-keyout', str(cert / 'privkey.pem'), '-out', str(cert / 'fullchain.pem')], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    files = render(domain, name, 8040, tls=True)
    for file, value in files.items():
        if file.endswith('.service'):
            Path('/etc/systemd/system', file).write_text(value)
    subprocess.run(['systemd-analyze', 'verify', '/etc/systemd/system/web-smoke.service', '/etc/systemd/system/web-smoke-scheduler.service'], check=True)
    Path('/etc/nginx/sites-enabled/default').unlink(missing_ok=True)
    Path('/etc/nginx/sites-enabled/web-smoke').write_text(files['web-smoke.nginx.conf'])
    Path('/etc/nginx/conf.d/web-smoke-limits.conf').write_text(files['web-smoke-limits.conf'])
    subprocess.run(['nginx', '-t'], check=True)
    processes = []
    try:
        processes.append(subprocess.Popen(['runuser', '-u', name, '--', str(root / '.venv/bin/gunicorn'), '--bind', '127.0.0.1:8040', '--workers', '1', '--threads', '4', 'app:create_app()'], cwd=root, env=environment, start_new_session=True))
        processes.append(subprocess.Popen(['nginx', '-g', 'daemon off;'], start_new_session=True))
        cookies = http.cookiejar.CookieJar()
        client = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(cert / 'fullchain.pem'))), HTTPCookieProcessor(cookies))
        def request(path, data=None):
            return client.open(Request('https://127.0.0.1' + path, data=urlencode(data).encode() if data is not None else None, headers={'Host': domain}), timeout=5)
        deadline = time.monotonic() + 20
        while True:
            try:
                with request('/register') as response:
                    page = response.read().decode(); assert response.status == 200
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        assert any(cookie.name == 'session' and cookie.secure for cookie in cookies)
        with request('/register', dict(csrf=csrf, name='Synthetic smoke user', username='smoke-user', password='synthetic-test-password')) as response:
            assert response.status == 200 and 'Chờ duyệt tài khoản' in response.read().decode()
        with request('/login') as response:
            page = response.read().decode()
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        with request('/login', dict(csrf=csrf, username='smoke-user', password='synthetic-test-password')) as response:
            assert 'chờ quản trị viên duyệt' in response.read().decode()
        subprocess.run(['runuser', '-u', name, '--', str(root / '.venv/bin/python'), '-m', 'flask', '--app', 'app',
                        'approve-user', '--username', 'smoke-user'], cwd=root, env=environment, check=True)
        with request('/login') as response:
            csrf = re.search(r'name="csrf" value="([^"]+)"', response.read().decode()).group(1)
        with request('/login', dict(csrf=csrf, username='smoke-user', password='synthetic-test-password')) as response:
            assert response.status == 200 and 'Synthetic smoke user' in response.read().decode()
        with request('/campaigns') as response:
            assert response.status == 200
        connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=5)
        connection.request('GET', '/login', headers={'Host': domain})
        response = connection.getresponse(); assert response.status == 308
        assert response.getheader('Location') == 'https://' + domain + '/login'; connection.close()
        subprocess.run(['runuser', '-u', name, '--', str(root / '.venv/bin/python'), '-c',
                        "from app import create_app; app=create_app(); assert app.extensions['zalo_connector'].available(); assert 'desktop_license' not in app.extensions"], cwd=root, env=environment, check=True)
        subprocess.run(['runuser', '-u', name, '--', str(root / '.venv/bin/python'), '-m', 'flask', '--app', 'app', 'run-scheduler', '--once'], cwd=root, env=environment, check=True)
        assert not root.joinpath('instance/zalo.scheduler.heartbeat').exists()
        # In this container systemd is not PID 1. Stop the actual writer first;
        # a minimal control stub reports the services inactive to the backup.
        os.killpg(processes[0].pid, signal.SIGTERM); processes[0].wait(15)
        control = Path('/tmp/web-smoke-control'); control.mkdir()
        control.joinpath('systemctl').write_text('#!/bin/sh\nexit 3\n'); control.joinpath('systemctl').chmod(0o755)
        root.joinpath('instance/media').mkdir(exist_ok=True)
        root.joinpath('instance/media/backup-test.jpg').write_bytes(b'synthetic-image-data')
        subprocess.run(['bash', str(root / 'web_deploy/backup-web.sh'), name, '/tmp/web-backups'],
                       env=dict(environment, PATH=str(control) + ':' + environment['PATH']), check=True)
        archive = next(Path('/tmp/web-backups').glob('backup-*/instance-backup.tar.gz'))
        restored = Path('/tmp/web-restored'); restored.mkdir()
        with tarfile.open(archive) as backup:
            backup.extractall(restored, filter='data')
        assert restored.joinpath('instance/session.key').read_bytes() == root.joinpath('instance/session.key').read_bytes()
        assert restored.joinpath('instance/media/backup-test.jpg').read_bytes() == b'synthetic-image-data'
        with sqlite3.connect(restored / 'instance/zalo.sqlite3') as db:
            assert db.execute('SELECT username FROM users').fetchall() == [('smoke-user',)]
            assert db.execute('SELECT count(*) FROM campaign_attempts').fetchone()[0] == 0
        print(json.dumps(dict(ok=True, ubuntu='24.04', https=True, registration=True, scheduler_once=True, backup_restore=True, windows_app=False, license_authority=False)))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()


if __name__ == '__main__':
    main()
