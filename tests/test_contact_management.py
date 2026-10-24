import io
import json
import sqlite3

from test_workflow import app, post, register, token
from test_send import setup_send, prepare


def query(app,sql,args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql,args).fetchall()


def test_explicit_group_import_confirmation_updates_existing_rows_but_default_does_not(app):
    client=app.test_client();register(client)
    post(client,'/data-groups',{'name':'TEST'})
    post(client,'/data-groups/import',{'group':'TEST','phones':'0901234567','consent':''})
    post(client,'/data-groups/import',{'group':'TEST','phones':'0901234567'})
    assert query(app,'SELECT consent FROM contacts')==[(0,)]
    response=post(client,'/data-groups/import',{'group':'TEST','phones':'0901234567','consent':'yes'})
    assert 'Đã ghi nhận đồng ý cho 1 hồ sơ đã có' in response.text
    assert query(app,'SELECT consent FROM contacts')==[(1,)]
    assert client.get('/campaigns/group-options').json['groups'][0]['eligible']==1


def test_confirm_131_existing_group_contacts_without_reuploading(app):
    client=app.test_client();register(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.executemany('INSERT INTO contacts(user_id,name,phone,tag,consent) VALUES(1,?,?,?,0)',
                       ((f'Customer {i}',f'090{i:07d}','TEST') for i in range(131)))
    group=client.get('/campaigns/group-options').json['groups'][0]
    assert group['total']==131 and group['eligible']==0
    assert client.post('/campaigns/group-consent',data={'csrf':token(client),'group_id':str(group['id'])}).status_code==400
    response=client.post('/campaigns/group-consent',data={'csrf':token(client),'group_id':str(group['id']),'confirm_consent':'yes'})
    assert response.json['confirmed']==131
    assert client.get('/campaigns/group-options').json['groups'][0]['eligible']==131
    assert client.post('/campaigns/group-snapshot',data={'csrf':token(client),'group_id':str(group['id'])}).json['total']==131
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    other=app.test_client();register(other,'other')
    assert other.post('/campaigns/group-consent',data={'csrf':token(other),'group_id':str(group['id']),'confirm_consent':'yes'}).status_code==404
    assert client.post('/campaigns/group-consent',data={'group_id':str(group['id']),'confirm_consent':'yes'}).status_code==400


def test_selected_customers_are_reviewed_then_bulk_edited_without_touching_others(app):
    client=app.test_client();register(client)
    for index in range(3):
        post(client,'/contacts',{'name':f'Person {index}','phone':f'090{index:07d}','tag':'Old','consent':''})
    ids=json.dumps([1,2])
    response=post(client,'/contacts/bulk-edit',{'contact_ids':ids})
    assert 'Sửa 2 khách hàng đã chọn' in response.text
    assert query(app,'SELECT DISTINCT tag,consent FROM contacts')==[('Old',0)]
    post(client,'/contacts/bulk-edit',{'contact_ids':ids,'action':'apply','tag':'New','consent':'yes'})
    assert query(app,'SELECT name,tag,consent FROM contacts ORDER BY id')==[('Person 0','New',1),('Person 1','New',1),('Person 2','Old',0)]
    groups=client.get('/campaigns/group-options').json['groups']
    assert next(group for group in groups if group['name']=='New')['total']==2
    assert next(group for group in groups if group['name']=='Old')['total']==1
    # An empty edit does not silently clear data.
    post(client,'/contacts/bulk-edit',{'contact_ids':ids,'action':'apply'})
    assert query(app,'SELECT name FROM contacts WHERE id=1')==[('Person 0',)]


def test_delete_requires_confirmation_hides_every_membership_and_preserves_history(app):
    client,connector=setup_send(app);prepare(client)
    client.get('/data-groups')
    post(client,'/data-groups/duplicate',{'group':'VIP','name':'Shared copy'})
    review=client.get('/contacts/1/delete')
    assert 'Xóa 1 khách hàng đã chọn' in review.text
    assert query(app,'SELECT deleted_at FROM contacts')==[(None,)]
    post(client,'/contacts/1/delete',{'action':'apply'})
    assert query(app,'SELECT deleted_at FROM contacts')==[(None,)]
    post(client,'/contacts/1/delete',{'action':'apply','confirm_delete':'yes'})
    assert query(app,'SELECT deleted_at IS NOT NULL,consent FROM contacts')==[(1,0)]
    assert query(app,'SELECT count(*) FROM contact_group_memberships')==[(0,)]
    assert query(app,'SELECT count(*) FROM message_sends')==[(1,)]
    assert 'Lan Zalo' in client.get('/campaigns/1/report').text
    assert client.get('/contacts/1/edit').status_code==404
    assert 'Lan' not in client.get('/contacts').text
    assert all(group['total']==0 for group in client.get('/campaigns/group-options').json['groups'])
    connector.message_action.reset_mock()
    assert client.post('/campaigns/1/send/1',data={'csrf':token(client),'confirm_send':'yes'}).status_code==400
    assert connector.message_action.call_count==0
    # Repeating delete cannot damage historical records.
    assert post(client,'/contacts/1/delete',{'action':'apply','confirm_delete':'yes'}).status_code==200
    assert query(app,'SELECT count(*) FROM message_sends')==[(1,)]


def test_bulk_actions_are_owner_scoped_atomic_and_csrf_protected(app):
    owner=app.test_client();register(owner)
    post(owner,'/contacts',{'name':'Private','phone':'0901234567'})
    other=app.test_client();register(other,'other')
    post(other,'/contacts',{'name':'Other','phone':'0912345678'})
    for path,values in [('/contacts/bulk-edit',{'consent':'yes'}),('/contacts/bulk-delete',{'confirm_delete':'yes'})]:
        assert other.post(path,data={'csrf':token(other),'contact_ids':'[1,2]','action':'apply',**values}).status_code==404
    assert query(app,'SELECT count(*) FROM contacts WHERE deleted_at IS NOT NULL')==[(0,)]
    assert other.get('/contacts/1/delete').status_code==404
    assert owner.post('/contacts/bulk-delete',data={'contact_ids':'[1]','action':'apply','confirm_delete':'yes'}).status_code==400
    for malformed in ['[]','[true]','not-json','[9223372036854775808]']:
        post(owner,'/contacts/bulk-delete',{'contact_ids':malformed,'action':'apply','confirm_delete':'yes'})
    assert query(app,'SELECT count(*) FROM contacts WHERE deleted_at IS NULL')==[(2,)]


def test_reimporting_an_explicitly_deleted_customer_restores_one_profile_and_sources(app):
    client=app.test_client();register(client)
    post(client,'/data-groups',{'name':'Original'})
    post(client,'/data-groups/import',{'group':'Original','phones':'0901234567'})
    post(client,'/contacts/1/delete',{'action':'apply','confirm_delete':'yes'})
    post(client,'/data-groups',{'name':'Restored'})
    post(client,'/data-groups/import',{'group':'Restored','phones':'0901234567','consent':'yes'})
    assert query(app,'SELECT count(*) FROM contacts')==[(1,)]
    assert query(app,'SELECT deleted_at,consent FROM contacts')==[(None,1)]
    assert query(app,"SELECT count(*) FROM contact_group_memberships WHERE group_name='Restored'")==[(1,)]
    assert query(app,'SELECT count(*) FROM contact_data_sources')==[(2,)]
    # The single-customer form also restores an explicitly re-added archived profile.
    post(client,'/contacts/1/delete',{'action':'apply','confirm_delete':'yes'})
    post(client,'/contacts',{'name':'Re-added','phone':'0901234567'})
    assert query(app,'SELECT count(*),deleted_at,consent FROM contacts')==[(1,None,1)]
