"""Cross-platform license lifecycle tests; all sends/network calls are synthetic."""
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from desktop.licensing import DesktopLicense, load_config
from desktop.runtime import DesktopRuntime
from license_system.authority import Authority, LEASE_SECONDS, secret_hash
from license_system.server import create_app as create_license_app
from license_system.signatures import LicenseError, decode, encode, verify
from test_workflow import app, post, token
from test_send import setup_send, prepare

DEVICE_A = 'ZFM1-' + 'A' * 64
DEVICE_B = 'ZFM1-' + 'B' * 64


@pytest.fixture
def authority(tmp_path):
    authority = Authority(tmp_path / 'owner')
    authority.initialize('https://cskh.viettaxco.com/licenses')
    return authority


@pytest.fixture
def clock():
    return SimpleNamespace(wall=int(time.time()), mono=1000)


def make_client(tmp_path, authority, clock, device=DEVICE_A):
    config = json.loads(authority.folder.joinpath('client-config.json').read_text())
    def transport(config, action, data):
        return authority.exchange(action, data['device'], data.get('key', data.get('activation_token')), clock.wall)
    return DesktopLicense(tmp_path / device[-10:], config, transport, device, lambda: clock.wall, lambda: clock.mono)


def test_one_seat_is_atomic_and_only_key_hash_is_stored(authority, clock):
    issued = authority.issue('Viettax', now=clock.wall)
    def activate(device):
        try:
            return authority.exchange('activate', device, issued['key'], clock.wall)
        except LicenseError as error:
            return error
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(activate, (DEVICE_A, DEVICE_B)))
    assert sum(isinstance(result, dict) for result in results) == 1
    with authority.connection() as db:
        assert db.execute('SELECT count(*) FROM activations WHERE active=1').fetchone()[0] == 1
        stored = db.execute('SELECT key_hash FROM licenses').fetchone()[0]
        assert stored == secret_hash(issued['key']) and stored != issued['key']
    assert issued['key'] not in json.dumps(authority.list_licenses())


def test_activation_reentry_transfer_and_owner_reset(authority, clock, tmp_path):
    key = authority.issue('Viettax', now=clock.wall)['key']
    first = make_client(tmp_path, authority, clock)
    second = make_client(tmp_path, authority, clock, DEVICE_B)
    first.activate(key); old_token = first.state['activation_token']
    first.activate(key)
    assert old_token != first.state['activation_token']
    with pytest.raises(LicenseError):
        authority.exchange('refresh', DEVICE_A, old_token, clock.wall)
    with pytest.raises(LicenseError, match='đủ số máy'):
        second.activate(key)
    first.deactivate(); assert not first.allowed()
    second.activate(key); assert second.allowed()
    authority.manage(1, 'reset-devices', now=clock.wall)
    assert not second.refresh(force=True)
    first.activate(key); assert first.allowed()


def test_revocation_clears_access_and_extension_resumes_same_activation(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    key = authority.issue('Khách A', now=clock.wall)['key']; client.activate(key)
    authority.manage(1, 'revoke', now=clock.wall)
    assert not client.refresh(force=True)
    assert not client.allowed() and 'lease' not in client.state
    authority.manage(1, 'extend', days=30, now=clock.wall)
    assert client.refresh(force=True)
    assert client.claims()['customer'] == 'Khách A'


def test_periodic_checks_and_offline_grace_never_extend_signed_expiry(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    client.activate(authority.issue('A', now=clock.wall)['key'])
    original = client.state['lease']
    client.transport = Mock(side_effect=ConnectionError('Offline'))
    clock.wall += 301; clock.mono += 301
    assert client.refresh() and client.state['lease'] == original
    clock.wall += LEASE_SECONDS; clock.mono += LEASE_SECONDS
    assert not client.refresh() and not client.allowed() and client.state['lease'] == original
    assert client.transport.call_count == 2


def test_key_expiry_and_backwards_clock_do_not_prolong_access(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    key = authority.issue('A', days=1, now=clock.wall)['key']; client.activate(key)
    clock.wall += 86000; clock.mono += 86000
    assert client.refresh(force=True)
    assert client.claims()['valid_until'] == client.claims()['license_expires_at']
    clock.wall -= 86400; clock.mono += 401
    assert not client.allowed()


def test_tampered_and_copied_leases_never_unlock_another_device(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    client.activate(authority.issue('A', now=clock.wall)['key'])
    signed = client.state['lease']; prefix, payload, signature = signed.split('.')
    data = json.loads(decode(payload)); data['license_expires_at'] += 365 * 86400
    forged = '.'.join((prefix, encode(json.dumps(data).encode()), signature))
    with pytest.raises(LicenseError):
        verify(forged, client.config['public_key'], DEVICE_A, clock.wall)
    second = make_client(tmp_path, authority, clock, DEVICE_B)
    second.state = dict(client.state)
    assert not second.allowed() and not second.refresh(force=True)
    for invalid in ('', 'ZF1.bad.bad', 'ZF1.' + 'A' * 9000 + '.bad'):
        with pytest.raises(LicenseError):
            verify(invalid, client.config['public_key'], DEVICE_A, clock.wall)


def test_restarting_requires_server_validation_and_different_keys_require_deactivation(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    first = authority.issue('A', now=clock.wall)['key']; client.activate(first)
    second = authority.issue('B', now=clock.wall)['key']
    with pytest.raises(LicenseError, match='Hủy kích hoạt'):
        client.activate(second)
    reopened = make_client(tmp_path, authority, clock)
    reopened.transport = Mock(side_effect=ConnectionError('Offline'))
    assert not reopened.allowed() and not reopened.refresh(force=True)
    online = make_client(tmp_path, authority, clock)
    assert online.refresh(force=True)
    online.deactivate(); online.activate(second)
    assert online.claims()['customer'] == 'B'


def test_renewal_network_does_not_hold_dispatch_guard_lock(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    client.activate(authority.issue('A', now=clock.wall)['key'])
    original = client.transport; entered = threading.Event(); release = threading.Event()
    def waiting(*args):
        entered.set(); assert release.wait(5); return original(*args)
    client.transport = waiting
    thread = threading.Thread(target=lambda: client.refresh(force=True)); thread.start()
    try:
        assert entered.wait(2)
        began = time.monotonic(); assert client.allowed()
        assert time.monotonic() - began < .5
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive()


def test_deactivation_blocks_new_dispatch_while_network_is_pending(authority, clock, tmp_path):
    client = make_client(tmp_path, authority, clock)
    client.activate(authority.issue('A', now=clock.wall)['key'])
    original = client.transport; entered = threading.Event(); release = threading.Event()
    def waiting(*args):
        entered.set(); assert release.wait(5); return original(*args)
    client.transport = waiting
    thread = threading.Thread(target=client.deactivate); thread.start()
    try:
        assert entered.wait(2); assert not client.allowed()
    finally:
        release.set(); thread.join(5)
    assert not client.allowed()


def test_client_configuration_requires_https_and_private_files_are_not_replaced(authority, tmp_path):
    private = authority.key_path.read_bytes()
    with pytest.raises(FileExistsError):
        authority.initialize('https://cskh.viettaxco.com/licenses')
    assert authority.key_path.read_bytes() == private
    config_path = authority.folder / 'client-config.json'; valid = json.loads(config_path.read_text())
    for url in ('http://example.com', 'https://user:password@example.com', 'https://example.com?token=x'):
        config_path.write_text(json.dumps(dict(valid, server_url=url)))
        with pytest.raises(LicenseError):
            load_config(config_path)
    assert 'PRIVATE' not in json.dumps(valid)


def test_public_authority_endpoints_require_device_credentials_and_reject_malformed_json(authority):
    app = create_license_app(authority.folder); client = app.test_client()
    key = authority.issue('A')['key']
    for data in (None, [], {}, {'device': DEVICE_A, 'key': []}, {'device': 'other', 'key': key}):
        assert client.post('/v1/activate', json=data).status_code == 400
    response = client.post('/v1/activate', json=dict(device=DEVICE_A, key=key))
    assert response.status_code == 200 and response.json['lease'].startswith('ZF1.')
    secret = response.json['activation_token']
    assert key not in response.text and response.headers['Cache-Control'] == 'no-store'
    assert client.post('/v1/refresh', json=dict(device=DEVICE_B, activation_token=secret)).status_code == 403
    assert client.post('/v1/issue', json=dict(device=DEVICE_A, key=key)).status_code == 404
    assert client.get('/admin').status_code == 302
    # Client-controlled proxy headers do not bypass per-peer throttling.
    with authority.connection() as db:
        db.execute('INSERT OR REPLACE INTO rate_windows VALUES(?,?,100)', ('127.0.0.1', int(time.time())))
    assert client.post('/v1/refresh', json=dict(device=DEVICE_A, activation_token=secret), headers={'X-Forwarded-For': '1.2.3.4'}).status_code == 429


def admin_csrf(client, path='/admin/login'):
    response = client.get(path)
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def test_owner_admin_requires_login_csrf_and_reauth_after_password_change(authority):
    app = create_license_app(authority.folder); client = app.test_client()
    password = authority.folder.joinpath('admin-password.txt').read_text().strip()
    assert client.post('/admin/login', data={'password': password}).status_code == 400
    assert client.post('/admin/login', data={'csrf': admin_csrf(client), 'password': password}).status_code == 302
    csrf = admin_csrf(client, '/admin')
    assert client.post('/admin', data={'action': 'issue', 'customer': 'A'}).status_code == 400
    response = client.post('/admin', data=dict(csrf=csrf, action='issue', customer='Viettax', days='30'))
    assert response.status_code == 200 and 'Key vừa tạo' in response.text
    assert len(authority.list_licenses()) == 1
    assert 'ZF-' not in client.get('/admin').text
    authority.set_admin_password('new-owner-password-2026')
    assert client.get('/admin').status_code == 302
    assert not authority.folder.joinpath('admin-password.txt').exists()


def test_expired_license_blocks_guard_without_consuming_attempt_or_preview(app, authority, clock, tmp_path):
    license = make_client(tmp_path, authority, clock)
    license.activate(authority.issue('A', now=clock.wall)['key'])
    app.extensions['desktop_license'] = license
    client, connector = setup_send(app); prepare(client); connector.message_action.reset_mock()
    clock.wall += 3700; clock.mono += 3700
    assert post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'}).status_code == 403
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT state FROM message_sends').fetchone()[0] == 'prepared'
        assert db.execute('SELECT count(*) FROM campaign_attempts').fetchone()[0] == 0
    connector.message_action.assert_not_called()
    assert license.refresh(force=True)
    connector.message_action.return_value = dict(state='sent', message_id='mock-1')
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT state FROM message_sends').fetchone()[0] == 'sent'
        assert db.execute('SELECT count(*) FROM campaign_attempts').fetchone()[0] == 1


def test_desktop_activation_page_enforces_key_and_preserves_login_csrf(authority, clock, tmp_path):
    license = make_client(tmp_path, authority, clock)
    runtime = DesktopRuntime(tmp_path / 'desktop', config={'TESTING': True}, license=license)
    try:
        client = runtime.app.test_client()
        assert client.get('/register').location == '/desktop/license'
        assert client.get('/api/v1/data-groups').status_code == 403
        assert client.post('/desktop/license', data={'key': 'wrong'}).status_code == 400
        key = authority.issue('A', now=clock.wall)['key']
        response = post(client, '/desktop/license', dict(key=key, action='activate'))
        assert response.status_code == 200 and license.allowed()
        assert client.get('/register').status_code == 200
        assert post(client, '/desktop/license', {'action': 'deactivate'}).status_code == 403
    finally:
        runtime.stop(5)


def test_expiry_between_scheduler_check_and_claim_does_not_permanently_block_campaign(app, authority, clock, tmp_path):
    from campaign_schedule import TZ
    license = make_client(tmp_path, authority, clock)
    license.activate(authority.issue('A', now=clock.wall)['key'])
    app.extensions['desktop_license'] = license
    client, connector = setup_send(app)
    now = datetime.fromtimestamp(clock.wall, TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    fields = dict(schedule_present='yes', schedule_enabled='yes', schedule_kind='daily', schedule_date=now.date().isoformat(),
                  schedule_time='00:00', schedule_stop='23:59', schedule_stop_enabled='no', account_id='1',
                  schedule_skip_sunday_present='yes', schedule_skip_sunday='no')
    post(client, '/campaigns/1/schedule', fields)
    scheduler = app.extensions['campaign_scheduler']
    with app.app_context():
        scheduler.tick(lambda: now)
    connector.message_action.reset_mock()
    def expire_before_claim(*args):
        clock.wall += 3700; clock.mono += 3700
        return dict(state='connected')
    connector.status.side_effect = expire_before_claim
    with app.app_context():
        scheduler.tick(lambda: now)
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT schedule_error FROM campaigns').fetchone()[0] == ''
        assert db.execute('SELECT state FROM message_sends').fetchone()[0] == 'prepared'
        assert db.execute('SELECT count(*) FROM campaign_attempts').fetchone()[0] == 0
    connector.message_action.assert_not_called()
    assert license.refresh(force=True)
    connector.status.side_effect = None
    connector.message_action.return_value = dict(state='sent', message_id='mock-accepted')
    with app.app_context():
        scheduler.tick(lambda: now)
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT state FROM message_sends').fetchone()[0] == 'sent'
        assert db.execute('SELECT count(*) FROM campaign_attempts').fetchone()[0] == 1


def test_unlicensed_scheduler_waits_and_never_processes_campaigns(authority, clock, tmp_path):
    license = make_client(tmp_path, authority, clock)
    called = threading.Event()
    runtime = DesktopRuntime(tmp_path / 'desktop', config={'TESTING': True}, license=license, tick=called.set)
    try:
        runtime.start(); runtime.activate()
        assert not called.wait(.1)
        license.activate(authority.issue('A', now=clock.wall)['key'])
        assert called.wait(3)
    finally:
        assert runtime.stop(5)


def test_nginx_install_preserves_https_and_rejects_unrelated_sites():
    from deployment.license_nginx import configure
    existing = 'server { listen 443 ssl; server_name cskh.viettaxco.com; ssl_certificate /cert; location / { proxy_pass http://127.0.0.1:8000; } }'
    configured = configure(existing)
    assert 'ssl_certificate /cert;' in configured and 'proxy_pass http://127.0.0.1:8000;' in configured
    assert configure(configured) == configured
    for invalid in (existing.replace('cskh.viettaxco.com', 'other.com'), existing.replace('ssl_certificate', 'disabled_certificate'), existing.replace('location / ', 'location /licenses/ ')):
        with pytest.raises(ValueError):
            configure(invalid)
