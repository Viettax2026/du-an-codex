"""Private media catalog backed by the existing campaign attachment storage."""
import math
from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

MEDIA_FILE_LIMIT = 1000


def register_media_library(app, db, login_required, manager):
    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS media_groups (
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,
            UNIQUE(user_id,name))''')
        columns = {row['name'] for row in db().execute('PRAGMA table_info(campaign_media)')}
        for column, kind in {'library_group_id':'INTEGER REFERENCES media_groups(id)','library_deleted_at':'TEXT'}.items():
            if column not in columns:
                db().execute(f'ALTER TABLE campaign_media ADD COLUMN {column} {kind}')
        db().commit()

    def group_id(raw):
        if not raw:
            return None
        if not raw.isdigit() or not db().execute('SELECT 1 FROM media_groups WHERE id=? AND user_id=?',(raw,g.user['id'])).fetchone():
            abort(404)
        return int(raw)

    def owned(media_id):
        media = manager.media(media_id)
        if not media or media['library_deleted_at']:
            abort(404)
        return media

    @app.get('/media')
    @login_required
    def media_library():
        group = group_id(request.args.get('group',''))
        kind = request.args.get('kind','all')
        query = request.args.get('q','').strip()[:120]
        extension = request.args.get('ext','')
        days = request.args.get('days','')
        sorting = request.args.get('sort','newest')
        view = request.args.get('view','grid')
        order = {'newest':'id DESC','oldest':'id ASC','name':'filename COLLATE NOCASE,id DESC','size':'size DESC,id DESC'}
        if kind not in ('all','image','video','document') or extension not in ('','jpg','jpeg','png','webp','pdf','mp4') or days not in ('','7','30') or sorting not in order or view not in ('grid','small','list'):
            abort(400)
        where = 'user_id=? AND library_deleted_at IS NULL AND filename LIKE ?'
        params = [g.user['id'],'%'+query+'%']
        if group:
            where += ' AND library_group_id=?'; params.append(group)
        if extension:
            where += ' AND lower(filename) LIKE ?'; params.append('%.'+extension)
        if days:
            where += " AND created_at>=datetime('now',?)"; params.append('-'+days+' days')
        counts = db().execute("SELECT count(*) AS total,coalesce(sum(mime LIKE 'image/%'),0) AS image,coalesce(sum(mime LIKE 'video/%'),0) AS video,coalesce(sum(mime='application/pdf'),0) AS document FROM campaign_media WHERE "+where,params).fetchone()
        if kind!='all':
            where += ' AND '+{'image':"mime LIKE 'image/%'",'video':"mime LIKE 'video/%'",'document':"mime='application/pdf'"}[kind]
        total = db().execute('SELECT count(*) FROM campaign_media WHERE '+where,params).fetchone()[0]
        pages = max(1,math.ceil(total/24)); number = max(1,min(request.args.get('p',1,type=int),pages))
        rows = db().execute('SELECT * FROM campaign_media WHERE '+where+' ORDER BY '+order[sorting]+' LIMIT 24 OFFSET ?',(*params,(number-1)*24)).fetchall()
        groups = db().execute('''SELECT d.*,count(m.id) AS total FROM media_groups d LEFT JOIN campaign_media m
            ON m.library_group_id=d.id AND m.user_id=d.user_id AND m.library_deleted_at IS NULL
            WHERE d.user_id=? GROUP BY d.id ORDER BY d.name''',(g.user['id'],)).fetchall()
        used = db().execute('SELECT count(*) AS files,coalesce(sum(size),0) AS bytes FROM campaign_media WHERE user_id=?',(g.user['id'],)).fetchone()
        active = db().execute('SELECT count(*) FROM campaign_media WHERE user_id=? AND library_deleted_at IS NULL',(g.user['id'],)).fetchone()[0]
        def link(**changes):
            values = dict(group=group or '',kind=kind,q=query,ext=extension,days=days,sort=sorting,view=view)
            values.update(changes)
            return url_for('media_library',**values)
        return render_template('media_library.html',page='media',rows=rows,groups=groups,group=group,kind=kind,query=query,
                               extension=extension,days=days,sorting=sorting,view=view,counts=counts,total=total,used=used,
                               active=active,number=number,pages=pages,media_link=link,limit=MEDIA_FILE_LIMIT)

    @app.post('/media/groups')
    @login_required
    def create_media_group():
        name = request.form.get('name','').strip()
        if not name or len(name)>80:
            flash('Tên nhóm cần từ 1 đến 80 ký tự.','error')
            return redirect(url_for('media_library'))
        db().execute('INSERT OR IGNORE INTO media_groups(user_id,name) VALUES (?,?)',(g.user['id'],name))
        db().commit()
        group = db().execute('SELECT id FROM media_groups WHERE user_id=? AND name=?',(g.user['id'],name)).fetchone()
        return redirect(url_for('media_library',group=group['id']))

    @app.post('/media/upload')
    @login_required
    def upload_library_media():
        group = group_id(request.form.get('group',''))
        new_id = None
        try:
            db().execute('BEGIN IMMEDIATE')
            if db().execute('SELECT count(*) FROM campaign_media WHERE user_id=?',(g.user['id'],)).fetchone()[0]>=MEDIA_FILE_LIMIT:
                raise ValueError(f'Thư viện đã đạt giới hạn {MEDIA_FILE_LIMIT:,} tệp.')
            new_id = manager.upload(request.files.get('file'))
            if not new_id:
                raise ValueError('Chọn tệp để tải lên.')
            db().execute('UPDATE campaign_media SET library_group_id=? WHERE id=? AND user_id=?',(group,new_id,g.user['id']))
            db().commit()
            if request.accept_mimetypes.best=='application/json':
                return jsonify(id=new_id,message='Đã tải tệp lên.'),201
            flash('Đã tải tệp lên.','success')
            return redirect(url_for('media_library',group=group or ''))
        except ValueError as error:
            media = manager.media(new_id) if new_id else None
            if media:
                (manager.media_root/media['storage_name']).unlink(missing_ok=True)
            db().rollback()
            if request.accept_mimetypes.best=='application/json':
                return jsonify(error=str(error)),400
            flash(str(error),'error')
            return redirect(url_for('media_library',group=group or ''))

    @app.get('/media/<int:media_id>/preview')
    @login_required
    def preview_library_media(media_id):
        media = owned(media_id)
        path = manager.media_root/media['storage_name']
        if not path.is_file():
            abort(404)
        return send_file(path,mimetype=media['mime'],download_name=media['filename'],conditional=True)

    @app.post('/media/<int:media_id>/group')
    @login_required
    def move_library_media(media_id):
        owned(media_id); group = group_id(request.form.get('group',''))
        db().execute('UPDATE campaign_media SET library_group_id=? WHERE id=? AND user_id=?',(group,media_id,g.user['id']))
        db().commit()
        return redirect(url_for('media_library',group=group or ''))

    @app.post('/media/bulk-group')
    @login_required
    def bulk_move_library_media():
        group = group_id(request.form.get('group',''))
        ids = request.form.getlist('media_ids')
        if not ids or len(ids)>24 or any(not value.isdigit() for value in ids):
            abort(400)
        marks = ','.join('?' for _ in ids)
        db().execute('BEGIN IMMEDIATE')
        count = db().execute('SELECT count(*) FROM campaign_media WHERE user_id=? AND library_deleted_at IS NULL AND id IN ('+marks+')',(g.user['id'],*ids)).fetchone()[0]
        if count!=len(set(ids)):
            abort(404)
        db().execute('UPDATE campaign_media SET library_group_id=? WHERE user_id=? AND id IN ('+marks+')',(group,g.user['id'],*ids))
        db().commit()
        return redirect(url_for('media_library',group=group or ''))

    @app.route('/media/<int:media_id>/delete',methods=['GET','POST'])
    @login_required
    def delete_library_media(media_id):
        if request.method=='POST':
            db().execute('BEGIN IMMEDIATE')
        media = owned(media_id)
        used = db().execute('SELECT 1 FROM campaigns WHERE media_id=? UNION SELECT 1 FROM message_sends WHERE media_id=?',(media_id,media_id)).fetchone()
        if request.method=='POST':
            if request.form.get('confirm_delete')!='yes':
                abort(400)
            if used:
                db().execute('UPDATE campaign_media SET library_deleted_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(media_id,g.user['id']))
            else:
                (manager.media_root/media['storage_name']).unlink(missing_ok=True)
                db().execute('DELETE FROM campaign_media WHERE id=? AND user_id=?',(media_id,g.user['id']))
            db().commit()
            flash('Đã ẩn khỏi thư viện; tệp đang dùng trong chiến dịch được giữ lại.' if used else 'Đã xóa tệp.','success')
            return redirect(url_for('media_library'))
        return render_template('media_delete.html',page='media',media=media,used=bool(used))
