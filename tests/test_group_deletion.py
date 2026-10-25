import sqlite3

import pytest

from app import create_app
from campaign_exclusions import contact_is_excluded
from test_workflow import app, post, register
from test_public_api import key


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, args).fetchall()


@pytest.mark.parametrize('operation', ['create', 'rename', 'duplicate'])
def test_permanent_deletion_and_name_reuse_preserve_profiles_sources_and_audiences(app, operation):
    client = app.test_client(); register(client)
    post(client, '/data-groups', {'name': 'TEST'})
    post(client, '/data-groups/import', {'group': 'TEST', 'phones': '0901234567'})
    post(client, '/data-groups/duplicate', {'group': 'TEST', 'name': 'Keep copy'})
    post(client, '/campaigns', {'name': 'Old audience', 'message': 'Hi', 'data_mode': 'group', 'tag': 'TEST'})
    old_id = query(app, "SELECT id FROM data_groups WHERE name='TEST'")[0][0]
    sources = query(app, 'SELECT id,batch_id,label FROM contact_data_sources')
    response = post(client, '/data-groups/delete', {'group': 'TEST', 'confirm_delete': 'yes'})
    assert response.status_code == 200
    assert query(app, 'SELECT id FROM data_groups WHERE id=?', (old_id,)) == []
    assert query(app, 'SELECT group_id FROM data_group_contacts WHERE group_id=?', (old_id,)) == []
    assert query(app, 'SELECT phone,tag,consent FROM contacts') == [('0901234567','',1)]
    assert query(app, 'SELECT id,batch_id,label FROM contact_data_sources') == sources
    assert query(app, 'SELECT group_id FROM contact_data_sources') == [(None,)]
    assert query(app, 'SELECT group_id,group_name FROM data_import_batches') == [(None,'TEST')]
    assert query(app, "SELECT audience_mode,tag FROM campaigns") == [('list','')]
    assert query(app, 'SELECT contact_id FROM campaign_contacts') == [(1,)]
    assert query(app, "SELECT count(*) FROM contact_group_memberships WHERE group_name='Keep copy'") == [(1,)]
    if operation == 'create':
        response = post(client, '/data-groups', {'name': 'TEST'})
    else:
        post(client, '/data-groups', {'name': 'Incoming'})
        post(client, '/data-groups/import', {'group': 'Incoming', 'phones': '0912345678'})
        response = post(client, '/data-groups/edit' if operation == 'rename' else '/data-groups/duplicate',
                        {'name': 'TEST', 'original_group': 'Incoming', 'group': 'Incoming'})
    assert response.status_code == 200 and 'Tên nhóm đã tồn tại' not in response.text
    assert query(app, "SELECT id FROM data_groups WHERE name='TEST'")[0][0] > old_id
    expected = 0 if operation == 'create' else 1
    assert query(app, "SELECT count(*) FROM contact_group_memberships WHERE group_name='TEST'") == [(expected,)]
    post(client, '/data-groups/import', {'group': 'TEST', 'phones': '0923456789'})
    post(client, '/campaigns/1')
    assert query(app, 'SELECT p.phone FROM deliveries d JOIN contacts p ON p.id=d.contact_id WHERE d.campaign_id=1') == [('0901234567',)]
    assert 'Tên nhóm đã tồn tại' in post(client, '/data-groups', {'name': 'TEST'}).text
    assert query(app, 'PRAGMA foreign_key_check') == []


def test_deleting_last_group_does_not_reappear_or_reuse_id_via_legacy_materialization(app):
    client = app.test_client(); register(client); headers = key(client)
    post(client, '/data-groups', {'name': 'TEST'})
    post(client, '/data-groups/import', {'group': 'TEST', 'phones': '0901234567'})
    old_id = query(app, 'SELECT id FROM data_groups')[0][0]
    post(client, '/data-groups/delete', {'group': 'TEST', 'confirm_delete': 'yes'})
    assert client.get('/campaigns/group-options').json['groups'] == []
    assert client.get('/api/v1/data-groups', headers=headers).json['data']['groups'] == []
    assert query(app, 'SELECT id FROM data_groups') == []
    assert 'TEST' not in client.get('/data-groups').text
    assert '0901234567' in client.get('/contacts').text
    # The web's contact form creates legacy tags, later materialized by API GET.
    post(client, '/contacts', {'name': 'New', 'phone': '0912345678', 'tag': 'TEST'})
    groups = client.get('/api/v1/data-groups', headers=headers).json['data']['groups']
    assert len(groups) == 1 and groups[0]['id'] > old_id
    assert client.get(f'/api/v1/data-groups/{old_id}/members', headers=headers).status_code == 404
    assert client.get(f"/api/v1/data-groups/{groups[0]['id']}/members", headers=headers).json['data']['total'] == 1
    # Explicit API creation also uses the monotonically increasing sequence.
    post(client, '/data-groups/delete', {'group': 'TEST', 'confirm_delete': 'yes'})
    response = client.post('/api/v1/data-groups', json={'name': 'TEST'}, headers=headers)
    assert response.status_code == 201 and response.json['data']['id'] > groups[0]['id']


def test_old_hidden_groups_are_permanently_removed_on_upgrade_with_exclusions_intact(app):
    client = app.test_client(); register(client)
    post(client, '/data-groups', {'name': 'TEST'})
    post(client, '/data-groups/import', {'group': 'TEST', 'phones': '0901234567'})
    post(client, '/campaigns', {'name': 'Existing', 'message': 'Hi', 'data_mode': 'group', 'tag': 'TEST'})
    old_id = query(app, 'SELECT id FROM data_groups')[0][0]
    post(client, '/campaign-exclusions/rules', {'name': 'Protect old members', 'data_group_id': str(old_id)})
    post(client, '/campaigns/1/exclusions', {'exclusions_present': 'yes', 'exclusion_rule_group_id': '1'})
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute('UPDATE data_groups SET deleted_at=CURRENT_TIMESTAMP WHERE id=?', (old_id,))
    create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'test-only'})
    assert query(app, 'SELECT id FROM data_groups') == []
    assert query(app, 'SELECT data_group_id FROM exclusion_rule_groups') == [(None,)]
    assert query(app, 'SELECT rule_group_id,contact_id FROM exclusion_rule_contacts') == [(1,1)]
    assert query(app, 'SELECT audience_mode,tag FROM campaigns') == [('list','')]
    post(client, '/data-groups', {'name': 'TEST'})
    post(client, '/data-groups/import', {'group': 'TEST', 'phones': '0912345678'})
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.row_factory = sqlite3.Row
        assert contact_is_excluded(lambda: connection,1,1,1)
        assert not contact_is_excluded(lambda: connection,1,1,2)
    create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'test-only'})
    assert query(app, 'SELECT id FROM data_groups WHERE deleted_at IS NOT NULL') == []
    assert query(app, 'PRAGMA foreign_key_check') == []


def test_delete_group_is_owner_scoped_csrf_protected_and_requires_confirmation(app):
    client = app.test_client(); register(client)
    other = app.test_client(); register(other, 'other')
    for browser in (client, other):
        post(browser, '/data-groups', {'name': 'TEST'})
        post(browser, '/data-groups/import', {'group': 'TEST', 'phones': '0901234567'})
    assert client.post('/data-groups/delete', data={'group':'TEST','confirm_delete':'yes'}).status_code == 400
    assert post(client, '/data-groups/delete', {'group':'TEST'}).status_code == 400
    assert query(app, 'SELECT count(*) FROM data_groups') == [(2,)]
    post(client, '/data-groups/delete', {'group':'TEST','confirm_delete':'yes'})
    assert query(app, 'SELECT user_id,name FROM data_groups') == [(2,'TEST')]
    assert query(app, 'SELECT user_id,tag FROM contacts ORDER BY user_id') == [(1,''),(2,'TEST')]
    assert post(client, '/data-groups/delete', {'group':'TEST','confirm_delete':'yes'}).status_code == 404


def test_stale_delete_confirmation_does_not_remove_recreated_group(app):
    client = app.test_client(); register(client)
    post(client, '/data-groups', {'name': 'TEST'})
    old_id = query(app, 'SELECT id FROM data_groups')[0][0]
    assert f'name="group_id" value="{old_id}"' in client.get('/data-groups/delete?group=TEST').text
    post(client, '/data-groups/delete', {'group':'TEST','confirm_delete':'yes','group_id':str(old_id)})
    post(client, '/data-groups', {'name':'TEST'})
    response = post(client, '/data-groups/delete', {'group':'TEST','confirm_delete':'yes','group_id':str(old_id)})
    assert response.status_code == 409
    assert query(app, "SELECT name FROM data_groups") == [('TEST',)]

