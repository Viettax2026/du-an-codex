"""Single concurrent tool licenses, including legacy migration and safe shutdown."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from desktop.licensing import DesktopLicense, SESSION_REFRESH_SECONDS
from desktop.runtime import DesktopRuntime
from license_system.authority import Authority, SESSION_DRAIN_SECONDS, SESSION_LEASE_SECONDS
from license_system.server import create_app
from license_system.signatures import ActivationInvalid, LicenseError, verify
from test_license_system import DEVICE_A, DEVICE_B, admin_csrf, authority, clock

SESSION_A = 'ZFS1-' + 'A' * 64
SESSION_B = 'ZFS1-' + 'B' * 64


def client_for(tmp_path, authority, clock, name, device=DEVICE_A):
    config = json.loads((authority.folder/'client-config.json').read_text())
    def transport(config, action, data):
        return authority.exchange(action, data['device'], data.get('key', data.get('activation_token')),
                                  clock.wall, session_id=data.get('session_id'))
    return DesktopLicense(tmp_path/name, config, transport, device, lambda:clock.wall, lambda:clock.mono)


@pytest.mark.parametrize('same_machine', [False, True])
def test_only_one_tool_can_claim_a_key_atomically_even_on_same_machine(authority, clock, same_machine):
    issued = authority.issue('Floating', mode='floating')
    def activate(pair):
        device, session = pair
        try:
            return authority.exchange('activate', device, issued['key'], clock.wall, session_id=session)
        except LicenseError as error:
            return error
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(activate, [(DEVICE_A,SESSION_A),(DEVICE_A if same_machine else DEVICE_B,SESSION_B)]))
    assert sum(isinstance(item,dict) for item in results) == 1
    assert any('tool khác' in str(item) for item in results if isinstance(item,LicenseError))
    assert authority.list_licenses()[0]['machines'] == 1
    with authority.connection() as db:
        assert db.execute('SELECT count(*) FROM license_sessions').fetchone()[0] == 1


def test_release_allows_another_machine_and_saved_profile_can_move_without_hardware_binding(authority, clock, tmp_path):
    issued = authority.issue('Floating', mode='floating')
    first = client_for(tmp_path, authority, clock, 'first')
    first.activate(issued['key'])
    saved = dict(first.state)
    assert first.claims()['session_id'] == first.session_id
    first.release_session()
    assert not first.allowed() and first.state['activation_token'] == saved['activation_token']
    # Copying a tool profile to a different computer is allowed after release.
    second = client_for(tmp_path, authority, clock, 'second', DEVICE_B)
    second.state = dict(first.state)
    assert second.refresh(force=True) and second.claims()['device'] == DEVICE_B
    assert second.claims()['session_id'] != first.session_id
    # A delayed release by the old process must not evict the new process.
    first.release_session()
    assert second.refresh(force=True)
    assert not first.refresh(force=True)
    assert 'tool khác' in first.error
    second.release_session()
    assert first.refresh(force=True)


def test_copied_credentials_and_leases_do_not_unlock_a_second_process(authority, clock, tmp_path):
    issued = authority.issue('Floating', mode='floating')
    first = client_for(tmp_path, authority, clock, 'first')
    second = client_for(tmp_path, authority, clock, 'second')
    first.activate(issued['key'])
    second.state = dict(first.state)
    second.startup_verified = True  # Even a copied, already-verified flag is insufficient.
    assert not second.allowed() and not second.refresh(force=True)
    with pytest.raises(LicenseError, match='phiên tool'):
        verify(first.state['lease'], first.config['public_key'], DEVICE_A, clock.wall, second.session_id)
    with pytest.raises(LicenseError, match='tool khác'):
        second.activate(issued['key'])
    assert first.refresh(force=True)


def test_network_loss_never_extends_session_and_new_tool_waits_for_inflight_drain(authority, clock, tmp_path):
    issued = authority.issue('Floating', mode='floating')
    first = client_for(tmp_path, authority, clock, 'first')
    second = client_for(tmp_path, authority, clock, 'second', DEVICE_B)
    first.activate(issued['key'])
    lease = first.state['lease']
    first.transport = Mock(side_effect=ConnectionError('Synthetic offline'))
    clock.wall += SESSION_REFRESH_SECONDS + 1; clock.mono += SESSION_REFRESH_SECONDS + 1
    assert first.refresh() and first.state['lease'] == lease
    clock.wall += SESSION_LEASE_SECONDS; clock.mono += SESSION_LEASE_SECONDS
    assert not first.refresh() and not first.allowed()
    with pytest.raises(LicenseError, match='tool khác'):
        second.activate(issued['key'])
    clock.wall += SESSION_DRAIN_SECONDS; clock.mono += SESSION_DRAIN_SECONDS
    second.activate(issued['key'])
    assert second.allowed() and not first.allowed()


def test_lost_close_release_recovers_after_timeout_without_deleting_account_data(authority, clock, tmp_path):
    issued = authority.issue('Floating', mode='floating')
    first = client_for(tmp_path, authority, clock, 'first')
    second = client_for(tmp_path, authority, clock, 'second', DEVICE_B)
    first.activate(issued['key'])
    first.transport = Mock(side_effect=ConnectionError('Synthetic offline'))
    first.release_session()
    assert not first.allowed() and first.state['activation_token']
    with pytest.raises(LicenseError, match='tool khác'):
        second.activate(issued['key'])
    clock.wall += SESSION_LEASE_SECONDS + SESSION_DRAIN_SECONDS + 1
    clock.mono += SESSION_LEASE_SECONDS + SESSION_DRAIN_SECONDS + 1
    second.activate(issued['key'])
    assert second.allowed()


def test_legacy_database_migration_is_repeatable_and_preserves_identity_and_old_keys(authority):
    old = authority.issue('Legacy')
    saved = authority.exchange('activate',DEVICE_A,old['key'])
    signer = authority.key_path.read_bytes()
    epoch = authority.setting('admin_epoch')
    with authority.connection() as db:
        db.execute('DROP TABLE license_sessions')
        db.execute('ALTER TABLE licenses DROP COLUMN mode')
    upgraded = Authority(authority.folder)
    upgraded.migrate()
    assert upgraded.list_licenses()[0]['mode'] == 'device'
    assert upgraded.exchange('refresh', DEVICE_A, saved['activation_token'])['lease']
    with pytest.raises(LicenseError,match='đủ số máy'):
        upgraded.exchange('activate',DEVICE_B,old['key'])
    assert upgraded.key_path.read_bytes() == signer and upgraded.setting('admin_epoch') == epoch
    assert upgraded.issue('New',mode='floating')['mode'] == 'floating'


def test_floating_keys_require_new_client_and_http_rejects_malformed_sessions(authority):
    issued = authority.issue('Floating',mode='floating')
    client = create_app(authority.folder).test_client()
    base = dict(device=DEVICE_A,key=issued['key'])
    assert client.post('/v1/activate',json=base).status_code == 403
    for session in ('', [], 'ZFS1-bad', 'ZFS1-'+'a'*64):
        assert client.post('/v1/activate',json=dict(base,session_id=session)).status_code == 400
    response = client.post('/v1/activate',json=dict(base,session_id=SESSION_A))
    assert response.status_code == 200
    secret = response.json['activation_token']
    assert client.post('/v1/release',json=dict(device=DEVICE_A,activation_token='wrong-secret-token',session_id=SESSION_A)).status_code == 403
    assert client.post('/v1/activate',json=dict(base,device=DEVICE_B,session_id=SESSION_B)).status_code == 403
    assert client.post('/v1/release',json=dict(device=DEVICE_A,activation_token=secret,session_id=SESSION_A)).json == dict(released=True)
    assert client.post('/v1/activate',json=dict(base,device=DEVICE_B,session_id=SESSION_B)).status_code == 200


def test_revocation_expiry_and_deletion_still_deny_floating_keys(authority, clock, tmp_path):
    issued = authority.issue('Floating',mode='floating')
    client = client_for(tmp_path,authority,clock,'first')
    client.activate(issued['key'])
    authority.manage(issued['id'],'revoke')
    assert not client.refresh(force=True)
    authority.manage(issued['id'],'extend')
    assert client.refresh(force=True)
    authority.manage(issued['id'],'revoke')
    authority.manage(issued['id'],'delete')
    assert not client.refresh(force=True) and not client.state
    with authority.connection() as db:
        assert not db.execute('SELECT * FROM license_sessions').fetchall()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_owner_ui_issues_floating_keys_without_overriding_existing_device_keys(authority):
    authority.issue('Legacy')
    client = create_app(authority.folder).test_client()
    password = (authority.folder/'admin-password.txt').read_text().strip()
    client.post('/admin/login',data=dict(csrf=admin_csrf(client),password=password))
    response = client.post('/admin',data=dict(csrf=admin_csrf(client,'/admin'),action='issue',customer='New',days=30))
    assert response.status_code == 200
    assert [row['mode'] for row in authority.list_licenses()] == ['floating','device']


def test_short_heartbeats_from_shared_ip_do_not_exhaust_legacy_limit(authority):
    issued = authority.issue('Floating',mode='floating')
    client = create_app(authority.folder).test_client()
    response = client.post('/v1/activate',json=dict(device=DEVICE_A,key=issued['key'],session_id=SESSION_A))
    token = response.json['activation_token']
    for _ in range(105):
        assert client.post('/v1/refresh',json=dict(device=DEVICE_A,activation_token=token,session_id=SESSION_A)).status_code == 200
    # Legacy clients sharing that IP retain their own allowance.
    old = authority.issue('Legacy')
    assert client.post('/v1/activate',json=dict(device=DEVICE_B,key=old['key'])).status_code == 200
    with authority.connection() as db:
        db.execute('UPDATE rate_windows SET attempts=3000 WHERE address=?',('sessions:127.0.0.1',))
    assert client.post('/v1/refresh',json=dict(device=DEVICE_A,activation_token=token,session_id=SESSION_A)).status_code == 429


def test_session_lease_never_outlives_key_expiry(authority,clock,tmp_path):
    issued = authority.issue('Floating',mode='floating')
    with authority.connection() as db:
        db.execute('UPDATE licenses SET expires_at=? WHERE id=?',(clock.wall+10,issued['id']))
    client = client_for(tmp_path,authority,clock,'first')
    client.activate(issued['key'])
    assert client.claims()['valid_until'] == clock.wall+10
    clock.wall += 10; clock.mono += 10
    assert not client.allowed() and not client.refresh(force=True)


def test_slow_network_and_windows_clock_behind_do_not_prolong_floating_lease(authority,clock,tmp_path):
    issued = authority.issue('Floating',mode='floating',now=clock.wall)
    config = json.loads((authority.folder/'client-config.json').read_text())
    def delayed(config,action,data):
        response = authority.exchange(action,data['device'],data['key'],clock.wall,session_id=data['session_id'])
        clock.wall += 8; clock.mono += 8
        return response
    client = DesktopLicense(tmp_path/'slow',config,delayed,DEVICE_A,lambda:clock.wall-120,lambda:clock.mono)
    started = clock.wall
    client.activate(issued['key'])
    assert client.allowed() and client.claims()['valid_until'] == started+60
    clock.wall += 52; clock.mono += 52
    assert not client.allowed()


def test_runtime_does_not_release_reservation_until_inflight_work_has_finished(authority, clock, tmp_path):
    issued = authority.issue('Floating',mode='floating')
    first = client_for(tmp_path,authority,clock,'first')
    second = client_for(tmp_path,authority,clock,'second',DEVICE_B)
    first.activate(issued['key'])
    entered = threading.Event(); finish = threading.Event()
    def tick():
        entered.set(); assert finish.wait(5)
    runtime = DesktopRuntime(tmp_path/'desktop',config={'TESTING':True},license=first,tick=tick)
    try:
        runtime.start(); runtime.activate(); assert entered.wait(3)
        assert not runtime.stop(.01)
        with pytest.raises(LicenseError,match='tool khác'):
            second.activate(issued['key'])
        finish.set(); assert runtime.stop(5)
        second.activate(issued['key'])
        assert second.allowed() and not first.allowed()
        assert first.state['activation_token']
    finally:
        finish.set(); runtime.stop(5)


def test_heartbeat_renews_while_scheduler_waits_for_zalo(authority, clock, tmp_path):
    issued = authority.issue('Floating',mode='floating')
    client = client_for(tmp_path,authority,clock,'first')
    client.activate(issued['key'])
    entered = threading.Event(); finish = threading.Event(); renewed = threading.Event()
    original = client.transport
    def transport(config,action,data):
        result = original(config,action,data)
        if action == 'refresh':renewed.set()
        return result
    client.transport = transport
    def tick():
        entered.set(); assert finish.wait(6)
    runtime = DesktopRuntime(tmp_path/'desktop',config={'TESTING':True},license=client,tick=tick)
    try:
        runtime.start(); runtime.activate(); assert entered.wait(3)
        renewed.clear()
        clock.wall += SESSION_REFRESH_SECONDS + 1; clock.mono += SESSION_REFRESH_SECONDS + 1
        assert renewed.wait(4)
        assert client.claims()['valid_until'] == clock.wall + SESSION_LEASE_SECONDS
        assert runtime.worker.is_alive() and not finish.is_set()
    finally:
        finish.set(); assert runtime.stop(5)
