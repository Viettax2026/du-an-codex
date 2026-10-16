import json
import time
import uuid
from unittest.mock import Mock

from zalo_connector import QRConnector
from test_workflow import app, post, register, token


def prepare(app, tmp_path):
    connector = QRConnector(tmp_path, app.root_path)
    app.extensions['zalo_connector'].root = connector.root
    return app.extensions['zalo_connector']


def test_qr_requires_owner_csrf_and_explicit_consent(app, tmp_path):
    app.config['ZALO_QR_ENABLED'] = True
    owner, other = app.test_client(), app.test_client()
    register(owner)
    result = post(owner, '/accounts', {'name': 'My Zalo'})
    assert 'data-auto-connect="1"' in result.text
    connector = prepare(app, tmp_path)
    connector.start = Mock(return_value={'state': 'loading'})
    assert owner.post('/accounts/1/qr', data={'csrf': token(owner)}).status_code == 400
    assert owner.post('/accounts/1/qr', data={'accept_unofficial': 'yes'}).status_code == 400
    response = owner.post('/accounts/1/qr', data={'csrf': token(owner), 'accept_unofficial': 'yes'})
    assert response.status_code == 202
    assert connector.start.call_count == 1
    register(other, 'other')
    assert other.get('/accounts/1/qr').status_code == 404
    assert other.post('/accounts/1/qr', data={'csrf': token(other), 'accept_unofficial': 'yes'}).status_code == 404
    assert other.post('/accounts/1/disconnect', data={'csrf': token(other)}).status_code == 404
    assert connector.start.call_count == 1


def test_missing_connector_never_returns_fake_qr(app):
    client = app.test_client()
    register(client)
    post(client, '/accounts', {'name': 'My Zalo'})
    assert client.post('/accounts/1/qr', data={'csrf': token(client), 'accept_unofficial': 'yes'}).status_code == 503
    app.config['ZALO_QR_ENABLED'] = True
    connector = app.extensions['zalo_connector']
    connector.start = Mock(side_effect=RuntimeError('internal secret diagnostic'))
    response = client.post('/accounts/1/qr', data={'csrf': token(client), 'accept_unofficial': 'yes'})
    assert response.status_code == 503
    assert 'internal secret' not in response.text
    assert 'image' not in response.json


def test_status_scrubs_secrets_and_expired_image(app, tmp_path):
    client = app.test_client()
    register(client)
    post(client, '/accounts', {'name': 'My Zalo'})
    connector = prepare(app, tmp_path)
    base = connector.account_path(1, 1)
    run_id = str(uuid.uuid4())
    directory = base / run_id
    directory.mkdir(parents=True)
    (base / 'current.json').write_text(json.dumps({'run_id': run_id}))
    state = {'state': 'qr', 'image': 'aGVsbG8=', 'expires_at': time.time()+100,
             'updated_at': time.time(), 'cookie': 'SECRET', 'token': 'SECRET'}
    status_path = directory / 'status.json'
    status_path.write_text(json.dumps(state))
    response = client.get('/accounts/1/qr')
    assert response.json['image'] == 'aGVsbG8='
    assert 'SECRET' not in response.text
    state['expires_at'] = time.time()-1
    status_path.write_text(json.dumps(state))
    assert client.get('/accounts/1/qr').json['state'] == 'expired'
    assert 'image' not in client.get('/accounts/1/qr').json
    (directory / 'session.enc.json').write_text('encrypted-session-placeholder')
    response = client.post('/accounts/1/disconnect', data={'csrf': token(client)})
    assert response.status_code == 200
    assert not base.exists()
