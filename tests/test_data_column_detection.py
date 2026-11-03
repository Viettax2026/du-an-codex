"""Phone-column suggestions never replace explicit customer mappings."""
import io
import json
import sqlite3

import pytest
from openpyxl import Workbook

from campaign_actions import parse_phones
from data_import import suggest_contact_columns
from test_workflow import app,post,register,token
from test_send import setup_send

FIELDS=('name','phone','info1','info2','info3','info4','info5')


@pytest.mark.parametrize(('rows','column','source','skip'),[
    ([['MST','Tên','Khác','SỐ_ĐIỆN_THOẠI *','E','F','G'],
      ['0312345670','Lan','','0901234567','','','0923456789']], '3','header',True),
    ([['0312345670','Lan','','','','','0901234567'],
      ['0312345671','Bình','','','','','0912345678']], '6','values',False),
    ([['123456789','Lan','0934567890','','','','not a phone'],
      ['123456788','Bình','+84 912 345 678','','','','not a phone']], '2','values',False),
    ([['A','B','C','D','E','F','G']], '6','default',False),
    ([['A','B'],['C','D']], '0','default',False),
    ([['MST','Liên hệ khác','Tên','D','E','F','Kho'],
      ['0312345670','0901234567','Lan','','','','12'],
      ['0312345671','0912345678','Bình','','','','13']], '1','values',True),
    ([['Name','0901234567'],['Bình','0912345678']], '1','values',False),
    ([['A','B','C','D','E','F',901234567],
      ['A','B','C','D','E','F','+84 912.345.678']], '6','values',False),
    ([['Điện thoại','B','C','D','E','F','Mobile'],
      ['0901234567','','','','','','0912345678']], '6','header',True),
])
def test_suggestions_use_headers_then_phone_formats_then_g(rows,column,source,skip):
    result=suggest_contact_columns(rows,parse_phones,FIELDS)
    assert result['mapping']['phone']==column
    assert result['phone_mapping_source']==source and result['skip_header'] is skip
    assert all(value!=column for key,value in result['mapping'].items() if key!='phone')


def workbook():
    book=Workbook();sheet=book.active;sheet.title='CSKH'
    sheet.append(['0312345670','2026-11-03','Lan','','','',901234567])
    sheet.append(['0312345671','2026-11-03','Bình','','','','+84912345678'])
    other=book.create_sheet('Other')
    other.append(['Tên','Điện thoại']);other.append(['Loan','0934567890'])
    data=io.BytesIO();book.save(data);return data.getvalue()


def test_group_upload_defaults_g_preserves_first_record_and_honors_manual_change(app):
    client=app.test_client();register(client)
    post(client,'/data-groups',dict(name='Detected'))
    raw=workbook()
    response=post(client,'/data-groups/import/columns',dict(group='Detected',file=(io.BytesIO(raw),'customers.xlsx')))
    assert response.json['sheet']=='CSKH'
    assert response.json['mapping']['phone']=='6' and response.json['skip_header'] is False
    selected=dict(group='Detected',sheet='CSKH',import_mode='mapped',column_phone='6',column_name='2')
    preview=post(client,'/data-groups/import/preview',dict(selected,file=(io.BytesIO(raw),'customers.xlsx'))).json
    assert [row['phone'] for row in preview['rows']]==['0901234567','0912345678']
    assert [row['name'] for row in preview['rows']]==['Lan','Bình']
    # Re-selecting A explicitly must use A, not re-run the automatic G choice.
    selected['column_phone']='0'
    manual=post(client,'/data-groups/import/preview',dict(selected,file=(io.BytesIO(raw),'customers.xlsx'))).json
    assert [row['phone'] for row in manual['rows']]==['0312345670','0312345671']
    post(client,'/data-groups/import',dict(selected,file=(io.BytesIO(raw),'customers.xlsx')))
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT phone FROM contacts ORDER BY id').fetchall()==[('0312345670',),('0312345671',)]
    other=post(client,'/data-groups/import/columns',dict(group='Detected',sheet='Other',file=(io.BytesIO(raw),'customers.xlsx'))).json
    assert other['mapping']['phone']=='1' and other['skip_header'] is True


def test_campaign_upload_uses_same_g_suggestion_and_explicit_mapping(app):
    client,connector=setup_send(app);raw=workbook()
    def inspect(**values):
        return client.post('/campaigns/1/data/preview',data=dict(csrf=token(client),mode='file',
            file=(io.BytesIO(raw),'customers.xlsx'),**values)).json
    suggested=inspect(phase='inspect')
    assert suggested['mapping']['phone']=='6' and suggested['skip_header'] is False
    checked=inspect()
    assert [row['phone'] for row in checked['rows']]==['0901234567','0912345678']
    manual=inspect(mapping=json.dumps(dict(phone='0',name='2')))
    assert [row['phone'] for row in manual['rows']]==['0312345670','0312345671']
    assert not connector.message_action.called
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM contacts').fetchone()==(1,)
