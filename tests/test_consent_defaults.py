import io
import re
import sqlite3

from openpyxl import Workbook
from test_workflow import app, post, register
from test_public_api import key, create_group


def query(app,sql):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql).fetchall()


def test_contact_and_csv_defaults_allow_explicit_opt_out_and_preserve_old_records(app):
    client=app.test_client();register(client)
    assert re.search(r'<input[^>]*name="consent"[^>]*checked',client.get('/contacts').text)
    post(client,'/contacts',{'name':'Default enabled','phone':'0901234567'})
    post(client,'/contacts',{'name':'Explicit opt out','phone':'0912345678','consent_present':'yes'})
    csv=b'name,phone,consent\nBlank default,0923456789,\nExplicit false,0934567890,0\nDo not change old,0912345678,1\n'
    post(client,'/contacts/import',{'file':(io.BytesIO(csv),'contacts.csv')})
    post(client,'/contacts/import',{'file':(io.BytesIO(b'name,phone\nMissing column,0945678901\n'),'no-consent.csv')})
    assert query(app,'SELECT phone,consent FROM contacts ORDER BY id')==[
        ('0901234567',1),('0912345678',0),('0923456789',1),('0934567890',0),('0945678901',1)]


def test_group_text_csv_excel_defaults_feed_picker_and_unchecked_import_stays_disabled(app):
    client=app.test_client();register(client)
    page=post(client,'/data-groups',{'name':'Defaults'})
    assert re.search(r'<input[^>]*name="consent"[^>]*checked',page.text)
    post(client,'/data-groups/import',{'group':'Defaults','phones':'0901234567'})
    post(client,'/data-groups/import',{'group':'Defaults','file':(io.BytesIO(b'0912345678'),'phones.txt')})
    post(client,'/data-groups/import',{'group':'Defaults','file':(io.BytesIO(b'phone,name\n0923456789,CSV'),'phones.csv')})
    workbook=Workbook();workbook.active.append(['phone','name']);workbook.active.append(['0934567890','Excel'])
    stream=io.BytesIO();workbook.save(stream);stream.seek(0)
    post(client,'/data-groups/import',{'group':'Defaults','file':(stream,'phones.xlsx')})
    post(client,'/data-groups/import',{'group':'Defaults','phones':'0945678901','consent_present':'yes'})
    # Reimporting a number never overwrites the previously disabled state.
    post(client,'/data-groups/import',{'group':'Defaults','phones':'0945678901'})
    assert query(app,'SELECT consent FROM contacts ORDER BY id')==[(1,),(1,),(1,),(1,),(0,)]
    group=client.get('/campaigns/group-options').json['groups'][0]
    assert group['total']==5 and group['eligible']==4
    assert re.search(r'<input[^>]*name="phones_consent"[^>]*checked',client.get('/campaigns').text)


def test_api_consent_defaults_true_but_explicit_false_and_existing_opt_out_are_preserved(app):
    client=app.test_client();register(client);headers=key(client);group=create_group(client,headers)
    url=f'/api/v1/data-groups/{group}/members'
    assert client.post(url,json={'data':[{'phone':'0901234567'}]},headers=headers).status_code==200
    assert client.post(url,json={'data':[{'phone':'0912345678'}],'consent':False},headers=headers).status_code==200
    assert client.post(url,json={'data':[{'phone':'0912345678'}]},headers=headers).status_code==200
    assert query(app,'SELECT phone,consent FROM contacts ORDER BY id')==[('0901234567',1),('0912345678',0)]
    schema=client.get('/integrations/openapi.json').json
    operation=schema['paths']['/api/v1/data-groups/{group_id}/members']['post']
    assert operation['requestBody']['content']['application/json']['schema']['properties']['consent']['default'] is True
