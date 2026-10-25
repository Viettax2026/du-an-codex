"""Versioned, owner-scoped integration API and revocable bearer keys."""
import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from data_groups import save_group_members, insert_data_group, materialize_legacy_groups
from media_library import store_library_upload, remove_library_media

SCOPES = {'data:read': 'Đọc nhóm và data', 'data:write': 'Tạo nhóm, thêm data',
          'media:read': 'Đọc và tải Media', 'media:write': 'Tải lên, chuyển nhóm, xóa Media'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def register_public_api(app, db, login_required, manager, parse_phones):
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL,
            scopes TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT);
            CREATE TABLE IF NOT EXISTS api_idempotency (
            key_id INTEGER NOT NULL REFERENCES api_keys(id), request_key TEXT NOT NULL,
            request_hash TEXT NOT NULL, response_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(key_id,request_key));''')

    @app.route('/integrations', methods=['GET', 'POST'])
    @login_required
    def integrations():
        raw_key = None
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            scopes = set(request.form.getlist('scopes'))
            days = request.form.get('days', '90')
            if not name or len(name)>80 or not scopes or not scopes.issubset(SCOPES) or not days.isdigit() or not 1<=int(days)<=365:
                flash('Nhập tên khóa, chọn quyền và thời hạn từ 1 đến 365 ngày.', 'error')
            else:
                db().execute('BEGIN IMMEDIATE')
                count = db().execute("SELECT count(*) FROM api_keys WHERE user_id=? AND revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP", (g.user['id'],)).fetchone()[0]
                if count>=10:
                    db().rollback()
                    flash('Tối đa 10 khóa đang hoạt động. Thu hồi khóa cũ trước khi tạo thêm.', 'error')
                else:
                    raw_key = 'zf_' + secrets.token_urlsafe(32)
                    expiry = (datetime.now(timezone.utc)+timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
                    db().execute('INSERT INTO api_keys(user_id,name,token_hash,prefix,scopes,expires_at) VALUES (?,?,?,?,?,?)',
                                 (g.user['id'],name,digest(raw_key),raw_key[:10],','.join(sorted(scopes)),expiry))
                    db().commit()
        keys = db().execute('''SELECT id,name,prefix,scopes,created_at,expires_at,last_used_at,revoked_at,
            expires_at<=CURRENT_TIMESTAMP AS expired FROM api_keys WHERE user_id=? ORDER BY id DESC''', (g.user['id'],)).fetchall()
        return render_template('integrations.html', page='integrations', keys=keys, raw_key=raw_key, scopes=SCOPES)

    @app.post('/integrations/keys/<int:key_id>/revoke')
    @login_required
    def revoke_api_key(key_id):
        if not db().execute('SELECT 1 FROM api_keys WHERE id=? AND user_id=?', (key_id,g.user['id'])).fetchone():
            abort(404)
        db().execute('UPDATE api_keys SET revoked_at=coalesce(revoked_at,CURRENT_TIMESTAMP) WHERE id=? AND user_id=?', (key_id,g.user['id']))
        db().commit()
        flash('Đã thu hồi khóa API.', 'success')
        return redirect(url_for('integrations'))

    api = Blueprint('public_api', __name__, url_prefix='/api/v1')

    @api.before_request
    def authenticate():
        # Session cookies never authorize API access.
        g.user = None
        authorization = request.headers.get('Authorization', '')
        if not re.fullmatch(r'(?i:Bearer) zf_[A-Za-z0-9_-]{43}', authorization):
            abort(401, 'Cần khóa API trong header Authorization: Bearer <khóa>.')
        key = db().execute('''SELECT k.id AS key_id,k.scopes,u.id,u.name,u.username FROM api_keys k
            JOIN users u ON u.id=k.user_id WHERE k.token_hash=? AND k.revoked_at IS NULL
            AND k.expires_at>CURRENT_TIMESTAMP''', (digest(authorization[7:]),)).fetchone()
        if not key:
            abort(401, 'Khóa API không hợp lệ, đã hết hạn hoặc bị thu hồi.')
        g.user, g.api_key_id, g.api_scopes = key, key['key_id'], set(key['scopes'].split(','))
        db().execute("UPDATE api_keys SET last_used_at=CURRENT_TIMESTAMP WHERE id=? AND (last_used_at IS NULL OR last_used_at<datetime('now','-5 minutes'))", (g.api_key_id,))
        db().commit()

    @api.errorhandler(HTTPException)
    def http_error(error):
        db().rollback()
        response = jsonify(status=error.code, error_code=error.code, message=error.description, data=None)
        response.status_code = error.code
        if error.code == 401:
            response.headers['WWW-Authenticate'] = 'Bearer'
        return response

    @api.errorhandler(ValueError)
    def invalid_input(error):
        db().rollback()
        return jsonify(status=400, error_code=400, message=str(error), data=None),400

    def scope(required):
        def decorate(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if required not in g.api_scopes:
                    abort(403, 'Khóa chưa có quyền ' + required + '.')
                return view(*args, **kwargs)
            return wrapped
        return decorate

    def result(data, status=200):
        return jsonify(status=status, error_code=0, message='Thành công', data=data),status

    def body(allowed, required=()):
        data = request.get_json()
        if not isinstance(data,dict) or set(data)-set(allowed) or not set(required).issubset(data):
            raise ValueError('Kiểm tra các trường JSON bắt buộc và trường không được hỗ trợ.')
        return data

    def positive(value, name):
        if type(value) is not int or not 1<=value<=9223372036854775807:
            raise ValueError(name + ' cần là số nguyên dương trong phạm vi 64 bit.')
        return value

    def paging():
        values=[]
        for key,default,maximum in [('page',1,1000000),('per_page',50,100)]:
            raw=request.args.get(key,str(default))
            if not raw.isdigit() or not 1<=int(raw)<=maximum:
                raise ValueError('Tham số phân trang không hợp lệ.')
            values.append(int(raw))
        return values

    def owned_group(group_id):
        positive(group_id,'group_id')
        group = db().execute('SELECT * FROM data_groups WHERE id=? AND user_id=? AND deleted_at IS NULL', (group_id,g.user['id'])).fetchone()
        if not group:
            abort(404, 'Không tìm thấy nhóm data.')
        return group

    def media_group(value):
        if value is None:
            return None
        positive(value,'group_id')
        if not db().execute('SELECT 1 FROM media_groups WHERE id=? AND user_id=?', (value,g.user['id'])).fetchone():
            abort(404, 'Không tìm thấy nhóm Media.')
        return value

    def owned_media(media_id):
        positive(media_id,'media_id')
        row=manager.media(media_id)
        if not row or row['library_deleted_at']:
            abort(404, 'Không tìm thấy Media.')
        return row

    def media_json(row):
        return {**{key:row[key] for key in ('id','filename','mime','size','width','height','created_at')},
                'group_id':row['library_group_id'], 'download_url':url_for('public_api.download_media',media_id=row['id'])}

    @api.get('/data-groups')
    @scope('data:read')
    def groups():
        page,limit=paging()
        search=request.args.get('search','').strip()
        if len(search)>200:
            raise ValueError('Từ khóa tối đa 200 ký tự.')
        # Materialize legacy tag groups so every group has a stable ID.
        materialize_legacy_groups(db,g.user['id'])
        db().commit()
        args=(g.user['id'],'%'+search+'%')
        total=db().execute('SELECT count(*) FROM data_groups WHERE user_id=? AND deleted_at IS NULL AND name LIKE ?',args).fetchone()[0]
        rows=db().execute('''SELECT d.id,d.name,d.data_type,d.color,d.created_at,
            (SELECT count(*) FROM contact_group_memberships m WHERE m.user_id=d.user_id AND m.group_name=d.name) AS active_membership_count
            FROM data_groups d WHERE user_id=? AND deleted_at IS NULL AND name LIKE ? ORDER BY d.id LIMIT ? OFFSET ?''', (*args,limit,(page-1)*limit)).fetchall()
        return result(dict(groups=[dict(row) for row in rows],total=total,page=page,per_page=limit))

    @api.post('/data-groups')
    @scope('data:write')
    def create_group():
        data=body(('name','data_type','color'),('name',))
        name=data['name'];kind=data.get('data_type','all');color=data.get('color','#6860f6')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or kind not in ('all','phone','uid') or not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
            raise ValueError('Kiểm tra tên nhóm (1–80 ký tự), loại data và màu #RRGGBB.')
        name=name.strip()
        db().execute('BEGIN IMMEDIATE')
        if db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?', (g.user['id'],name,g.user['id'],name)).fetchone():
            abort(409,'Tên nhóm đã tồn tại.')
        group_id=insert_data_group(db,g.user['id'],name,kind,color.lower())
        db().commit()
        return result(dict(id=group_id,name=name,data_type=kind,color=color.lower()),201)

    @api.get('/data-groups/<int:group_id>/members')
    @scope('data:read')
    def members(group_id):
        group=owned_group(group_id);page,limit=paging()
        params=(g.user['id'],g.user['id'],group['name'])
        where='user_id=? AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?)'
        total=db().execute('SELECT count(*) FROM contacts WHERE '+where,params).fetchone()[0]
        rows=db().execute('SELECT id,name,phone,zalo_id,email,info1,info2,info3,info4,info5,consent,data_source FROM contacts WHERE '+where+' ORDER BY id LIMIT ? OFFSET ?',(*params,limit,(page-1)*limit)).fetchall()
        return result(dict(group_id=group_id,members=[dict(row) for row in rows],total=total,page=page,per_page=limit))

    @api.post('/data-groups/<int:group_id>/members')
    @scope('data:write')
    def add_members(group_id):
        data=body(('data','consent','source_name','dry_run'),('data',))
        rows=data['data'];consent=data.get('consent',True);dry=data.get('dry_run',False);source=data.get('source_name','')
        if not isinstance(rows,list) or not 1<=len(rows)<=500:
            raise ValueError('Mỗi yêu cầu cần từ 1 đến 500 dòng data.')
        if type(consent) is not bool or type(dry) is not bool or not isinstance(source,str) or len(source)>150:
            raise ValueError('consent/dry_run cần là boolean; source_name tối đa 150 ký tự.')
        request_key=request.headers.get('Idempotency-Key','')
        if request_key and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',request_key):
            raise ValueError('Idempotency-Key tối đa 128 ký tự chữ, số, dấu chấm, gạch ngang, gạch dưới hoặc hai chấm.')
        fingerprint=digest(json.dumps([group_id,data],sort_keys=True,separators=(',',':'),ensure_ascii=False))
        db().execute('BEGIN IMMEDIATE')
        group=owned_group(group_id)
        if request_key:
            saved=db().execute('SELECT * FROM api_idempotency WHERE key_id=? AND request_key=?',(g.api_key_id,request_key)).fetchone()
            if saved:
                if saved['request_hash']!=fingerprint:
                    abort(409,'Idempotency-Key đã được dùng cho nội dung khác.')
                db().rollback()
                return result(json.loads(saved['response_json']))
        if group['data_type']=='uid':
            raise ValueError('API hiện thêm data theo số điện thoại; nhóm UID chưa hỗ trợ.')
        incoming={};invalid=[];duplicates=0
        limits={'name':100,'zalo_id':100,'email':254,'info1':500,'info2':500,'info3':500,'info4':500,'info5':500}
        for index,row in enumerate(rows,1):
            try:
                if not isinstance(row,dict):
                    raise ValueError('Dòng data cần là một object.')
                if set(row)-({'phone'}|set(limits)):
                    raise ValueError('Dòng chứa trường không hỗ trợ.')
                raw=row.get('phone','')
                if type(raw) not in (str,int):
                    raise ValueError('phone cần là chuỗi hoặc số nguyên.')
                raw=str(raw).strip()
                if raw.isdigit() and len(raw)==9:
                    raw='0'+raw
                phones=parse_phones(raw)
                if len(phones)!=1:
                    raise ValueError('Mỗi dòng cần đúng một số điện thoại.')
                clean={}
                for field,maximum in limits.items():
                    value=row.get(field,'')
                    if not isinstance(value,str) or len(value)>maximum:
                        raise ValueError(field+' sai kiểu hoặc quá dài.')
                    clean[field]=value.strip()
                phone=phones[0]
                if phone in incoming:
                    duplicates+=1
                else:
                    incoming[phone]=dict(clean,phone=phone)
            except ValueError as error:
                invalid.append(dict(row=index,reason=str(error)))
        existing=set()
        if incoming:
            marks=','.join('?' for _ in incoming)
            existing={row['phone'] for row in db().execute('''SELECT p.phone FROM contacts p JOIN contact_group_memberships m ON m.contact_id=p.id
                WHERE p.user_id=? AND m.user_id=p.user_id AND m.group_name=? AND p.phone IN ('''+marks+')',
                (g.user['id'],group['name'],*incoming))}
        added=len(set(incoming)-existing)
        response=dict(group_id=group_id,received_count=len(rows),added_count=added,
                      existing_count=len(incoming)-added+duplicates,invalid_count=len(invalid),
                      invalid_rows=invalid[:100],invalid_rows_truncated=len(invalid)>100,dry_run=dry)
        if dry:
            db().rollback()
        else:
            saved=save_group_members(db,g.user['id'],group['name'],incoming,int(consent),source,'api',confirm_existing=data.get('consent') is True)
            response['added_count']=saved['added']
            if request_key:
                db().execute('INSERT INTO api_idempotency(key_id,request_key,request_hash,response_json) VALUES (?,?,?,?)',
                             (g.api_key_id,request_key,fingerprint,json.dumps(response,ensure_ascii=False)))
            db().commit()
        return result(response)

    @api.get('/media-groups')
    @scope('media:read')
    def media_groups():
        rows=db().execute('SELECT id,name FROM media_groups WHERE user_id=? ORDER BY id',(g.user['id'],)).fetchall()
        return result(dict(groups=[dict(row) for row in rows],total=len(rows)))

    @api.post('/media-groups')
    @scope('media:write')
    def create_media_group():
        data=body(('name',),('name',));name=data['name']
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:
            raise ValueError('Tên nhóm cần từ 1 đến 80 ký tự.')
        try:
            cursor=db().execute('INSERT INTO media_groups(user_id,name) VALUES (?,?)',(g.user['id'],name.strip()))
            db().commit()
        except sqlite3.IntegrityError:
            abort(409,'Tên nhóm đã tồn tại.')
        return result(dict(id=cursor.lastrowid,name=name.strip()),201)

    @api.get('/media')
    @scope('media:read')
    def media():
        page,limit=paging();where='user_id=? AND library_deleted_at IS NULL';params=[g.user['id']]
        kind=request.args.get('kind','all');q=request.args.get('q','').strip()
        if kind not in ('all','image','video','document') or len(q)>120:
            raise ValueError('Kiểm tra kind và từ khóa q tối đa 120 ký tự.')
        if 'group_id' in request.args:
            raw=request.args['group_id']
            if not raw.isdigit():
                raise ValueError('group_id cần là số nguyên dương.')
            group=media_group(int(raw));where+=' AND library_group_id=?';params.append(group)
        if kind!='all':
            where+=' AND '+{'image':"mime LIKE 'image/%'",'video':"mime LIKE 'video/%'",'document':"mime='application/pdf'"}[kind]
        if q:
            where+=' AND filename LIKE ?';params.append('%'+q+'%')
        total=db().execute('SELECT count(*) FROM campaign_media WHERE '+where,params).fetchone()[0]
        rows=db().execute('SELECT * FROM campaign_media WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',(*params,limit,(page-1)*limit)).fetchall()
        return result(dict(media=[media_json(row) for row in rows],total=total,page=page,per_page=limit))

    @api.post('/media')
    @scope('media:write')
    def upload_media():
        if request.mimetype!='multipart/form-data':
            abort(415,'Dùng multipart/form-data với trường file và group_id tùy chọn.')
        raw=request.form.get('group_id','')
        if raw and not raw.isdigit():
            raise ValueError('group_id cần là số nguyên dương.')
        group=media_group(int(raw)) if raw else None
        media_id=store_library_upload(db,manager,g.user['id'],request.files.get('file'),group)
        return result(media_json(owned_media(media_id)),201)

    @api.get('/media/<int:media_id>/file')
    @scope('media:read')
    def download_media(media_id):
        row=owned_media(media_id)
        path=manager.media_root/row['storage_name']
        if not path.is_file():
            abort(404,'Tệp không còn trên máy chủ.')
        return send_file(path,mimetype=row['mime'],as_attachment=True,download_name=row['filename'],conditional=True)

    @api.patch('/media/<int:media_id>')
    @scope('media:write')
    def move_media(media_id):
        data=body(('group_id',),('group_id',));group=media_group(data['group_id'])
        owned_media(media_id)
        db().execute('UPDATE campaign_media SET library_group_id=? WHERE id=? AND user_id=?',(group,media_id,g.user['id']))
        db().commit()
        return result(media_json(owned_media(media_id)))

    @api.delete('/media/<int:media_id>')
    @scope('media:write')
    def delete_media(media_id):
        positive(media_id,'media_id')
        data=body(('confirm_delete',),('confirm_delete',))
        if data['confirm_delete'] is not True:
            raise ValueError('Gửi confirm_delete: true để xác nhận xóa.')
        retained=remove_library_media(db,manager,g.user['id'],media_id)
        return result(dict(id=media_id,retained_for_campaigns=retained))

    app.register_blueprint(api)

    # Routing errors occur before blueprint hooks; keep these JSON too.
    for code in (404,405):
        def routing_error(error):
            if request.path.startswith('/api/v1/'):
                return jsonify(status=error.code,error_code=error.code,message=error.description,data=None),error.code
            return error.get_response()
        app.register_error_handler(code,routing_error)

    @app.get('/integrations/openapi.json')
    def api_schema():
        from api_schema import build_schema
        return jsonify(build_schema())
