import sqlite3
from unittest.mock import Mock
from test_workflow import app, post, register, token


def test_alias_is_rendered_confirmed_and_claimed_once(app):
    app.config['ZALO_QR_ENABLED'] = True
    client = app.test_client()
    register(client)
    post(client, '/accounts', {'name':'Zalo'})
    post(client, '/contacts', {'name':'Lan','phone':'0901234567','consent':'on'})
    post(client, '/campaigns', {'name':'Alias','message':'Hello','options_present':'yes',
        'send_message':'yes','rename_enabled':'yes','rename_template':'#{FULL_NAME} - #{PHONE}'})
    connector = app.extensions['zalo_connector']
    connector.status = Mock(return_value={'state':'connected'})
    connector.message_action = Mock(return_value={'state':'resolved','uid':'123','name':'Lan Zalo'})
    response = post(client,'/campaigns/1/prepare-send',{'contact_id':'1','account_id':'1'})
    assert 'Lan Zalo - 0901234567' in response.text
    connector.message_action.reset_mock()
    assert client.post('/campaigns/1/alias/1',data={'csrf':token(client)}).status_code == 400
    other = app.test_client()
    register(other,'other')
    assert other.post('/campaigns/1/alias/1',data={'csrf':token(other),'confirm_alias':'yes'}).status_code == 404
    connector.message_action.return_value = {'state':'renamed'}
    response = post(client,'/campaigns/1/alias/1',{'confirm_alias':'yes'})
    assert 'Zalo đã tiếp nhận đổi tên' in response.text
    post(client,'/campaigns/1/alias/1',{'confirm_alias':'yes'})
    post(client,'/campaigns/1/cancel-send/1')
    connector.message_action.assert_called_once_with(1,1,'alias',uid='123',message='Lan Zalo - 0901234567')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT alias_state,state FROM message_sends').fetchone() == ('renamed','prepared')


def test_empty_alias_template_cannot_be_saved(app):
    client = app.test_client()
    register(client)
    post(client,'/campaigns',{'name':'Bad','message':'Hello','rename_enabled':'yes'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM campaigns').fetchone()[0] == 0
