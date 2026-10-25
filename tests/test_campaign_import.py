import io
import json
import sqlite3

from openpyxl import Workbook
from test_workflow import app,post,register,token
from test_send import setup_send
from test_message_composer import query


def preview(client,**data):
    return client.post('/campaigns/1/data/preview',data=dict(csrf=token(client),**data))


def test_preview_normalizes_deduplicates_reports_invalid_and_never_writes(app):
    client,connector=setup_send(app)
    before=query(app,'SELECT count(*) FROM contacts'),query(app,'SELECT count(*) FROM campaign_contacts'),query(app,'SELECT count(*) FROM campaign_events')
    response=preview(client,text='0901234567; +84 912 345 678\nbad\n0912345678',mode='text')
    assert response.status_code==200
    result=response.json
    assert [row['phone'] for row in result['rows']]==['0901234567','0912345678']
    assert result['duplicates']==1 and len(result['invalid'])==1
    assert before==(query(app,'SELECT count(*) FROM contacts'),query(app,'SELECT count(*) FROM campaign_contacts'),query(app,'SELECT count(*) FROM campaign_events'))
    assert not connector.message_action.called


def test_excel_and_pasted_columns_can_be_mapped_before_staging(app):
    client,_=setup_send(app)
    book=Workbook();sheet=book.active
    sheet.append(['Mã','Họ tên','Số điện thoại','Info 1']);sheet.append(['Company code','New contact',923456789,'Gold'])
    data=io.BytesIO();book.save(data);data.seek(0)
    response=preview(client,mode='file',file=(data,'contacts.xlsx'))
    assert response.json['mapping']['phone']=='2' and response.json['skip_header']
    assert response.json['rows'][0]['phone']=='0923456789'
    assert response.json['rows'][0]['name']=='New contact' and response.json['rows'][0]['info1']=='Gold'
    pasted='Mã\tTên người nhận\tĐiện thoại\nA\tLan\t0934567890'
    mapping=json.dumps(dict(phone='2',name='1'))
    result=preview(client,mode='text',text=pasted,mapping=mapping,skip_header='yes').json
    assert result['rows'][0]['name']=='Lan' and result['rows'][0]['phone']=='0934567890'
    assert not result['invalid']


def test_staged_data_is_revalidated_on_save_and_keeps_old_profiles_and_results(app):
    client,connector=setup_send(app)
    rows=[dict(phone='0901234567',name='Do not overwrite'),dict(phone='0912345678',name='New',info1='Gold',email='new@example.com')]
    response=post(client,'/campaigns/1/data',dict(rows_json=json.dumps(rows),consent='yes'))
    assert response.status_code==200
    assert query(app,'SELECT name FROM contacts WHERE phone="0901234567"')==[('Lan',)]
    assert query(app,'SELECT name,info1,email,consent FROM contacts WHERE phone="0912345678"')==[('New','Gold','new@example.com',1)]
    assert query(app,'SELECT audience_mode FROM campaigns')==[('list',)]
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(2,)]
    for bad in [[dict(phone='bad')],[dict(phone=912345678)],'invalid']:
        post(client,'/campaigns/1/data',dict(rows_json=json.dumps(bad),consent='yes'))
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(2,)]
    assert not connector.message_action.called


def test_import_preview_requires_owner_csrf_and_bounded_valid_file(app):
    client,_=setup_send(app)
    assert client.post('/campaigns/1/data/preview',data=dict(mode='text',text='0901234567')).status_code==400
    other=app.test_client();register(other,'other')
    assert preview(other,mode='text',text='0901234567').status_code==404
    assert other.get('/campaigns?add_data=1').status_code==404
    assert preview(client,mode='file',file=(io.BytesIO(b'x'),'bad.exe')).status_code==400
    assert preview(client,mode='file',file=(io.BytesIO(b'x'*(2*1024*1024+1)),'large.txt')).status_code==400
    assert preview(client,mode='text',text='\n'.join(['0901234567']*502)).status_code==400
    assert preview(client,mode='text',text='0901234567',mapping='{"phone":0}').status_code==400


def test_snapshot_ids_cannot_reference_other_owners_or_revoked_consent(app):
    client,_=setup_send(app)
    other=app.test_client();register(other,'other')
    post(other,'/contacts',dict(name='Private',phone='0923456789',consent='on'))
    foreign=query(app,'SELECT id FROM contacts WHERE user_id=2')[0][0]
    post(client,'/campaigns/1/data',dict(source_contact_ids=json.dumps([foreign]),consent='yes'))
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(0,)]
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute('UPDATE contacts SET consent=0 WHERE id=1')
    post(client,'/campaigns/1/data',dict(source_contact_ids='[1]',consent='yes'))
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(0,)]
    assert query(app,'SELECT consent FROM contacts WHERE id=1')==[(0,)]
