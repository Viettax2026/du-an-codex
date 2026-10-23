import io
import sqlite3

from PIL import Image
from test_workflow import app, post, register, token


def png():
    stream=io.BytesIO();Image.new('RGB',(60,40),'#6556ed').save(stream,format='PNG')
    return stream.getvalue()


def upload(client, name='photo.png', data=None, group=''):
    return client.post('/media/upload',data={'csrf':token(client),'group':str(group),'file':(io.BytesIO(png() if data is None else data),name)},headers={'Accept':'application/json'})


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as db:
        return db.execute(sql,args).fetchall()


def test_media_library_upload_filters_preview_and_owner_access(app):
    client=app.test_client();register(client)
    assert upload(client).status_code==201
    assert upload(client,'notes.pdf',b'%PDF-1.4\n%%EOF').status_code==201
    assert upload(client,'video.mp4',b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00').status_code==201
    page=client.get('/media').text
    assert page.count('class="media-card"')==3
    assert 'Quản lý Media' in page
    assert client.get('/media?kind=image').text.count('class="media-card"')==1
    assert client.get('/media?kind=document').text.count('class="media-card"')==1
    assert client.get('/media?ext=mp4').text.count('class="media-card"')==1
    assert client.get('/media?q=missing').text.count('class="media-card"')==0
    assert client.get('/media/1/preview').data==png()
    assert client.get('/media/2/preview').mimetype=='application/pdf'
    assert client.get('/media/2/preview').headers['X-Frame-Options']=='SAMEORIGIN'
    assert "frame-ancestors 'self'" in client.get('/media/2/preview').headers['Content-Security-Policy']
    assert client.get('/media').headers['X-Frame-Options']=='DENY'
    assert client.get('/media?kind=bad').status_code==400
    other=app.test_client();register(other,'other')
    assert 'photo.png' not in other.get('/media').text
    for path in ['/media/1/preview','/media/1/delete','/media/1']:
        assert other.get(path).status_code==404
    assert post(other,'/media/1/group',{'group':''}).status_code==404


def test_media_validation_quota_and_failed_upload_cleanup(app,monkeypatch):
    import media_library
    client=app.test_client();register(client)
    root=app.extensions['campaign_manager'].media_root
    assert upload(client,'fake.png',b'not-an-image').status_code==400
    assert upload(client,'bad.html',b'<html></html>').status_code==400
    assert upload(client,'bad.pdf',b'not-a-pdf').status_code==400
    assert query(app,'SELECT count(*) FROM campaign_media')==[(0,)]
    assert not root.exists() or list(root.iterdir())==[]
    monkeypatch.setattr(media_library,'MEDIA_FILE_LIMIT',1)
    assert upload(client).status_code==201
    response=upload(client,'another.png')
    assert response.status_code==400 and 'giới hạn' in response.json['error']
    assert query(app,'SELECT count(*) FROM campaign_media')==[(1,)]
    assert client.post('/media/upload',data={'file':(io.BytesIO(png()),'missing-csrf.png')}).status_code==400


def test_media_groups_and_bulk_move_are_scoped_to_owner(app):
    client=app.test_client();register(client)
    post(client,'/media/groups',{'name':'Báo giá'})
    assert upload(client,group=1).status_code==201
    assert upload(client,'second.png').status_code==201
    assert client.get('/media?group=1').text.count('class="media-card"')==1
    post(client,'/media/bulk-group',{'group':'1','media_ids':['1','2']})
    assert client.get('/media?group=1').text.count('class="media-card"')==2
    other=app.test_client();register(other,'other')
    post(other,'/media/groups',{'name':'Private'})
    assert client.get('/media?group=2').status_code==404
    assert upload(client,'foreign.png',group=2).status_code==404
    assert post(other,'/media/bulk-group',{'group':'2','media_ids':['1']}).status_code==404
    assert query(app,'SELECT library_group_id FROM campaign_media')==[(1,),(1,)]


def test_media_deletion_preserves_campaign_attachment_and_history(app):
    client=app.test_client();register(client)
    upload(client)
    media_id=query(app,'SELECT id FROM campaign_media')[0][0]
    post(client,'/campaigns',{'name':'Keep attachment','message':'Hello'})
    post(client,'/campaigns/1/content',{'message':'Hello','library_media_id':str(media_id)})
    assert query(app,'SELECT media_id FROM campaigns WHERE id=1')==[(media_id,)]
    assert post(client,f'/media/{media_id}/delete').status_code==400
    post(client,f'/media/{media_id}/delete',{'confirm_delete':'yes'})
    assert query(app,'SELECT library_deleted_at FROM campaign_media WHERE id=?',(media_id,))[0][0]
    assert client.get('/media').text.count('class="media-card"')==0
    assert client.get(f'/media/{media_id}').data==png()  # Existing campaign URL remains valid.
    assert client.get(f'/media/{media_id}/preview').status_code==404
    upload(client,'unused.png')
    unused=query(app,"SELECT id,storage_name FROM campaign_media WHERE filename='unused.png'")[0]
    path=app.extensions['campaign_manager'].media_root/unused[1]
    assert path.exists()
    post(client,f'/media/{unused[0]}/delete',{'confirm_delete':'yes'})
    assert not path.exists()
    assert query(app,'SELECT id FROM campaign_media WHERE id=?',(unused[0],))==[]


def test_campaign_cannot_select_another_users_library_file(app):
    first=app.test_client();register(first);upload(first)
    second=app.test_client();register(second,'other')
    post(second,'/campaigns',{'name':'Own campaign','message':'Hello'})
    response=post(second,'/campaigns/1/content',{'message':'Hello','library_media_id':'1'})
    assert 'Không tìm thấy media' in response.text
    assert query(app,'SELECT media_id FROM campaigns')==[(None,)]
    assert first.get('/media/1/preview').data==png()


def test_media_pagination_and_selected_layout(app):
    client=app.test_client();register(client)
    for index in range(25):
        assert upload(client,f'picture-{index}.png').status_code==201
    assert client.get('/media').text.count('class="media-card"')==24
    assert client.get('/media?p=2').text.count('class="media-card"')==1
    assert 'media-list' in client.get('/media?view=list').text
    assert 'media-small' in client.get('/media?view=small').text
