"""Private reusable message templates and the campaign composer's media picker."""
import json
from flask import abort, g, jsonify, request, url_for
from rich_message import read_message, render_message, display_message, variant_spans


def register_message_composer(app, db, login_required, manager):
    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS message_templates (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT 'Chung',
            message TEXT NOT NULL, message_html TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db().execute('CREATE INDEX IF NOT EXISTS message_templates_owner ON message_templates(user_id,id)')
        db().commit()

    def media_item(media):
        if not media:
            return None
        return dict(id=media['id'], filename=media['filename'], mime=media['mime'], size=media['size'],
                    preview_url=url_for('media_file' if media['library_deleted_at'] else 'preview_library_media', media_id=media['id']))

    app.jinja_env.globals['composer_media'] = lambda media_id: media_item(manager.media(media_id))

    @app.get('/composer/media')
    @login_required
    def composer_library():
        rows=db().execute('SELECT * FROM campaign_media WHERE user_id=? AND library_deleted_at IS NULL ORDER BY id DESC', (g.user['id'],)).fetchall()
        return jsonify(items=[media_item(row) for row in rows])

    @app.post('/composer/preview')
    @login_required
    def composer_preview():
        try:
            message, html=read_message(request.form)
            sample=dict(name='Lan', phone='0901234567', email='lan@example.com', **{f'info{i}':f'Thông tin mẫu {i}' for i in range(1,6)})
            variants=[]
            for index in range(len(variant_spans(message))):
                text,styles=render_message(message,html,sample,dict(name='Lan',original_name='Lan'),strict=False,variant_index=index)
                variants.append(dict(html=str(display_message(text,json.dumps(styles))),length=len(text.encode('utf-16-le'))//2))
            return jsonify(**variants[0],variants=variants)
        except ValueError as error:
            return jsonify(error=str(error)),400

    @app.route('/message-templates', methods=['GET','POST'])
    @login_required
    def message_templates():
        if request.method=='GET':
            rows=db().execute('SELECT id,name,group_name,message,message_html FROM message_templates WHERE user_id=? ORDER BY updated_at DESC,id DESC', (g.user['id'],)).fetchall()
            return jsonify(items=[dict(row) for row in rows])
        try:
            name=request.form.get('name','').strip()
            group=request.form.get('group_name','').strip() or 'Chung'
            if not name or len(name)>80 or len(group)>60:
                raise ValueError('Tên mẫu cần 1–80 ký tự; tên nhóm tối đa 60 ký tự.')
            message,html=read_message(request.form)
            if not message:
                raise ValueError('Nhập nội dung trước khi lưu mẫu.')
            template_id=request.form.get('template_id','')
            if template_id:
                row=db().execute('SELECT id FROM message_templates WHERE id=? AND user_id=?',(template_id,g.user['id'])).fetchone()
                if not row:
                    abort(404)
                db().execute('UPDATE message_templates SET name=?,group_name=?,message=?,message_html=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(name,group,message,html,row['id'],g.user['id']))
                template_id=row['id']
            else:
                count=db().execute('SELECT count(*) FROM message_templates WHERE user_id=?',(g.user['id'],)).fetchone()[0]
                if count>=1000:
                    raise ValueError('Thư viện tối đa 1.000 mẫu nội dung.')
                template_id=db().execute('INSERT INTO message_templates(user_id,name,group_name,message,message_html) VALUES (?,?,?,?,?)',(g.user['id'],name,group,message,html)).lastrowid
            db().commit()
            return jsonify(id=template_id)
        except ValueError as error:
            db().rollback()
            return jsonify(error=str(error)),400

    @app.post('/message-templates/<int:template_id>/delete')
    @login_required
    def delete_message_template(template_id):
        row=db().execute('DELETE FROM message_templates WHERE id=? AND user_id=?',(template_id,g.user['id']))
        if not row.rowcount:
            abort(404)
        db().commit()
        return jsonify(deleted=True)
