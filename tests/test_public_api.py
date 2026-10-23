import io
import re
import sqlite3

from test_workflow import app, post, register, token
from test_media_library import png


def key(client, scopes=('data:read','data:write','media:read','media:write')):
    response=post(client,'/integrations',{'name':'CRM test','scopes':list(scopes),'days':'30'})
    match=re.search(r'value="(zf_[A-Za-z0-9_-]{43})"',response.text)
    assert match, response.status_code
    return {'Authorization':'Bearer '+match.group(1)}


def query(app,sql,args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql,args).fetchall()


def create_group(client,headers,name='API group',kind='phone'):
    response=client.post('/api/v1/data-groups',json={'name':name,'data_type':kind},headers=headers)
    assert response.status_code==201
    return response.json['data']['id']


def test_keys_are_private_hashed_revocable_and_require_explicit_bearer(app):
    client=app.test_client();register(client)
    assert client.get('/integrations').status_code==200
    headers=key(client)
    raw=headers['Authorization'][7:]
    assert query(app,'SELECT token_hash FROM api_keys')[0][0]!=raw
    assert raw not in client.get('/integrations').text
    assert client.get('/api/v1/data-groups').status_code==401  # Session alone is insufficient.
    assert client.get('/api/v1/data-groups?token='+raw).status_code==401
    assert client.get('/api/v1/data-groups',headers=headers).status_code==200
    assert client.get('/api/v1/data-groups',headers={'Authorization':headers['Authorization'].replace('Bearer ','bearer ')}).status_code==200
    assert query(app,'SELECT last_used_at FROM api_keys')[0][0]
    assert client.post('/integrations/keys/1/revoke').status_code==400
    other=app.test_client();register(other,'other')
    assert post(other,'/integrations/keys/1/revoke').status_code==404
    post(client,'/integrations/keys/1/revoke')
    response=client.get('/api/v1/data-groups',headers=headers)
    assert response.status_code==401 and response.is_json
    assert response.headers['WWW-Authenticate']=='Bearer'
    new=key(client)
    query(app,"UPDATE api_keys SET expires_at='2000-01-01' WHERE id=2")
    assert client.get('/api/v1/data-groups',headers=new).status_code==401
    # Existing web CSRF checks are unchanged.
    assert client.post('/data-groups',data={'name':'CSRF bypass'}).status_code==400
    assert client.post('/media/upload',data={'file':(io.BytesIO(png()),'image.png')}).status_code==400


def test_scopes_and_api_errors_do_not_redirect_or_grant_cookie_permissions(app):
    client=app.test_client();register(client)
    headers=key(client,('data:read',))
    assert client.post('/api/v1/data-groups',json={'name':'Forbidden'},headers=headers).status_code==403
    assert client.get('/api/v1/media',headers=headers).status_code==403
    assert client.get('/api/v1/not-a-route',headers=headers).status_code==404
    assert client.get('/api/v1/not-a-route',headers=headers).is_json
    assert client.put('/api/v1/data-groups',json={},headers=headers).status_code==405
    write=key(client)
    for data in [[],None,{'name':'x','username':'other'},{'name':''},{'name':'x','data_type':[]}]:
        response=client.post('/api/v1/data-groups',json=data,headers=write)
        assert response.status_code in (400,415) and response.is_json
    assert client.get('/api/v1/data-groups?per_page=101',headers=headers).status_code==400
    assert client.get('/api/v1/data-groups/999999999999999999999/members',headers=headers).status_code==400
    assert client.get('/api/v1/media/999999999999999999999/file',headers=write).status_code==400
    assert client.delete('/api/v1/media/999999999999999999999',json={'confirm_delete':True},headers=write).status_code==400
    assert client.post('/api/v1/data-groups',data='{broken',content_type='application/json',headers=write).status_code==400


def test_api_group_members_dry_run_partial_import_sources_and_idempotency(app):
    client=app.test_client();register(client);headers=key(client)
    group=create_group(client,headers)
    assert client.post('/api/v1/data-groups',json={'name':'API group'},headers=headers).status_code==409
    payload={'data':[{'name':'Lan','phone':'0901234567'}, {'phone':'+84 901 234 567'},
                     {'phone':'0348.410.323'}, {'phone':'bad'}, 'not an object'],
             'consent':True,'source_name':'CRM test','dry_run':True}
    url=f'/api/v1/data-groups/{group}/members'
    preview=client.post(url,json=payload,headers=headers)
    assert preview.status_code==200
    assert {k:preview.json['data'][k] for k in ['received_count','added_count','existing_count','invalid_count']}=={
        'received_count':5,'added_count':2,'existing_count':1,'invalid_count':2}
    assert query(app,'SELECT count(*) FROM contacts')==[(0,)]
    assert query(app,'SELECT count(*) FROM data_import_batches')==[(0,)]
    payload['dry_run']=False
    once={**headers,'Idempotency-Key':'crm-001'}
    response=client.post(url,json=payload,headers=once)
    assert response.json['data']['added_count']==2
    assert client.post(url,json=payload,headers=once).json==response.json
    assert query(app,'SELECT count(*) FROM data_import_batches')==[(1,)]
    assert query(app,'SELECT count(*) FROM contact_data_sources')==[(2,)]
    assert query(app,'SELECT DISTINCT data_source FROM contacts')==[('API · CRM test',)]
    assert client.post(url,json={'data':[{'phone':'0901234567'}]},headers=once).status_code==409
    listing=client.get(url+'?per_page=1',headers=headers).json['data']
    assert listing['total']==2 and len(listing['members'])==1
    assert listing['members'][0]['name']=='Lan' and listing['members'][0]['consent']==1
    assert client.get('/api/v1/data-groups',headers=headers).json['data']['groups'][0]['active_membership_count']==2
    assert '0901234567' in client.get('/data-groups?group=API+group').text
    assert client.get('/data-groups/source-history/1?group=API+group').json['sources'][0]['label']=='API · CRM test'


def test_existing_profiles_link_to_new_group_without_overwriting_info_or_consent(app):
    client=app.test_client();register(client);headers=key(client)
    first=create_group(client,headers,'First');second=create_group(client,headers,'Second')
    client.post(f'/api/v1/data-groups/{first}/members',json={'data':[{'name':'Original','phone':'0901234567'}],'source_name':'CRM / Viettax'},headers=headers)
    assert query(app,'SELECT data_source FROM contacts')==[('API · CRM / Viettax',)]
    response=client.post(f'/api/v1/data-groups/{second}/members',json={'data':[{'name':'Changed','phone':'0901234567'}],'consent':True},headers=headers)
    assert response.json['data']['added_count']==1
    assert query(app,'SELECT name,tag,consent FROM contacts')==[('Original','First',0)]
    assert client.get(f'/api/v1/data-groups/{second}/members',headers=headers).json['data']['total']==1
    again=client.post(f'/api/v1/data-groups/{second}/members',json={'data':[{'phone':'0901234567'}]},headers=headers)
    assert again.json['data']['added_count']==0 and again.json['data']['existing_count']==1
    uid=create_group(client,headers,'UID','uid')
    assert client.post(f'/api/v1/data-groups/{uid}/members',json={'data':[{'phone':'0901234567'}]},headers=headers).status_code==400
    post(client,'/data-groups/delete',{'group':'Second','confirm_delete':'yes'})
    assert client.get(f'/api/v1/data-groups/{second}/members',headers=headers).status_code==404


def test_api_owner_is_key_owner_even_with_other_users_cookie(app):
    first=app.test_client();register(first);a=key(first);group=create_group(first,a)
    other=app.test_client();register(other,'other');b=key(other)
    assert other.get(f'/api/v1/data-groups/{group}/members',headers=b).status_code==404
    assert other.post(f'/api/v1/data-groups/{group}/members',json={'data':[{'phone':'0901234567'}]},headers=b).status_code==404
    # Cookie belongs to other, bearer belongs to first: write only into first's account.
    assert other.post(f'/api/v1/data-groups/{group}/members',json={'data':[{'phone':'0901234567'}]},headers=a).status_code==200
    assert query(app,'SELECT user_id FROM contacts')==[(1,)]
    assert other.get('/api/v1/data-groups',headers=b).json['data']['groups']==[]


def test_api_media_upload_move_download_validation_and_owner_boundaries(app):
    client=app.test_client();register(client);headers=key(client)
    group=client.post('/api/v1/media-groups',json={'name':'Assets'},headers=headers).json['data']['id']
    response=client.post('/api/v1/media',data={'group_id':str(group),'file':(io.BytesIO(png()),'photo.png')},headers=headers)
    assert response.status_code==201
    item=response.json['data'];media_id=item['id']
    assert 'storage_name' not in item and 'path' not in item
    assert client.get(item['download_url'],headers=headers).data==png()
    assert client.get('/api/v1/media?kind=image&group_id='+str(group),headers=headers).json['data']['total']==1
    assert client.patch(f'/api/v1/media/{media_id}',json={'group_id':None},headers=headers).json['data']['group_id'] is None
    other=app.test_client();register(other,'other');b=key(other)
    for path in [item['download_url'],'/api/v1/media?group_id='+str(group)]:
        assert other.get(path,headers=b).status_code==404
    assert other.patch(f'/api/v1/media/{media_id}',json={'group_id':None},headers=b).status_code==404
    assert other.delete(f'/api/v1/media/{media_id}',json={'confirm_delete':True},headers=b).status_code==404
    assert client.post('/api/v1/media',data={'file':(io.BytesIO(b'bad'),'photo.png')},headers=headers).status_code==400
    assert client.post('/api/v1/media',data={'file':(io.BytesIO(png()),'photo.png'),'group_id':'999'},headers=headers).status_code==404
    assert client.post('/api/v1/media',data={'file':(io.BytesIO(b'x'*(10*1024*1024+1)),'big.png')},headers=headers).status_code==400
    assert client.post('/api/v1/media',data={'file':(io.BytesIO(b'x'*(13*1024*1024)),'bigger.png')},headers=headers).status_code==413
    assert client.delete(f'/api/v1/media/{media_id}',json={},headers=headers).status_code==400
    path=app.extensions['campaign_manager'].media_root/query(app,'SELECT storage_name FROM campaign_media WHERE id=?',(media_id,))[0][0]
    assert client.delete(f'/api/v1/media/{media_id}',json={'confirm_delete':True},headers=headers).json['data']['retained_for_campaigns'] is False
    assert not path.exists()


def test_api_deletion_keeps_used_campaign_files(app):
    client=app.test_client();register(client);headers=key(client)
    client.post('/api/v1/media',data={'file':(io.BytesIO(png()),'photo.png')},headers=headers)
    post(client,'/campaigns',{'name':'Keep media','message':'Hello'})
    post(client,'/campaigns/1/content',{'message':'Hello','library_media_id':'1'})
    response=client.delete('/api/v1/media/1',json={'confirm_delete':True},headers=headers)
    assert response.json['data']['retained_for_campaigns'] is True
    assert client.get('/media/1').data==png()
    assert client.get('/api/v1/media/1/file',headers=headers).status_code==404
    assert client.get('/api/v1/media',headers=headers).json['data']['total']==0


def test_openapi_and_import_limits(app):
    client=app.test_client();register(client);headers=key(client)
    schema=client.get('/integrations/openapi.json').json
    assert schema['openapi']=='3.0.3'
    assert len(schema['paths'])==6
    assert schema['components']['securitySchemes']['BearerAuth']['scheme']=='bearer'
    group=create_group(client,headers)
    url=f'/api/v1/data-groups/{group}/members'
    for payload in [{'data':[]},{'data':[{}]*501},{'data':[{}],'consent':'yes'},{'data':[{}],'source_name':123}]:
        response=client.post(url,json=payload,headers=headers)
        assert response.status_code==400 and response.is_json
    assert query(app,'SELECT count(*) FROM contacts')==[(0,)]


def test_concurrent_retries_share_one_import_and_source_batch(app):
    from concurrent.futures import ThreadPoolExecutor
    client=app.test_client();register(client);headers=key(client)
    group=create_group(client,headers)
    headers={**headers,'Idempotency-Key':'simultaneous-import'}
    def send(_):
        with app.test_client() as caller:
            response=caller.post(f'/api/v1/data-groups/{group}/members',headers=headers,
                                 json={'data':[{'phone':'0901234567'}]})
            return response.status_code,response.json
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(send,range(2)))
    assert results[0]==results[1]
    assert results[0][0]==200
    assert query(app,'SELECT count(*) FROM contacts')==[(1,)]
    assert query(app,'SELECT count(*) FROM data_import_batches')==[(1,)]
    assert query(app,'SELECT count(*) FROM contact_data_sources')==[(1,)]
