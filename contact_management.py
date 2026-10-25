"""Review selected customer records before bulk edits or archival deletion."""
import json

from flask import abort, flash, g, redirect, render_template, request, url_for


def register_contact_management(app, db, login_required):
    def handle(mode, ids=None):
        try:
            if ids is None:
                raw=request.form.get('contact_ids','')
                if len(raw)>250000:
                    raise ValueError('Chọn tối đa 10.000 khách hàng mỗi lần.')
                try:
                    ids=json.loads(raw)
                except (ValueError,TypeError) as error:
                    raise ValueError('Chọn khách hàng trước khi thao tác.') from error
            if not isinstance(ids,list) or not ids or len(ids)>10000 or any(type(value) is not int or not 1<=value<=9223372036854775807 for value in ids):
                raise ValueError('Chọn từ 1 đến 10.000 khách hàng hợp lệ.')
            ids=list(dict.fromkeys(ids));marks=','.join('?' for _ in ids)
            applying=request.method=='POST' and request.form.get('action')=='apply'
            if applying:
                db().execute('BEGIN IMMEDIATE')
            rows=db().execute('SELECT id,name,phone,tag,consent,deleted_at FROM contacts WHERE user_id=? AND id IN ('+marks+') ORDER BY id',
                              (g.user['id'],*ids)).fetchall()
            if len(rows)!=len(ids):
                abort(404)
            if mode=='edit' and any(row['deleted_at'] for row in rows):
                raise ValueError('Một số khách hàng đã bị xóa. Tải lại danh sách rồi chọn lại.')
            if applying:
                if mode=='delete':
                    if request.form.get('confirm_delete')!='yes':
                        raise ValueError('Đánh dấu xác nhận xóa các khách hàng đã chọn.')
                    count=db().execute('UPDATE contacts SET deleted_at=CURRENT_TIMESTAMP,consent=0 WHERE user_id=? AND deleted_at IS NULL AND id IN ('+marks+')',
                                       (g.user['id'],*ids)).rowcount
                    db().commit();flash(f'Đã xóa {count} khách hàng khỏi danh sách và nhóm data. Lịch sử đã có được giữ nguyên.','success')
                else:
                    tag=request.form.get('tag','').strip();consent=request.form.get('consent','')
                    if (not tag and not consent) or len(tag)>80 or consent not in ('','yes','no'):
                        raise ValueError('Nhập nhóm mới hoặc chọn trạng thái nhận tin cần áp dụng.')
                    updates=[];values=[]
                    if tag:
                        group=db().execute('SELECT deleted_at FROM data_groups WHERE user_id=? AND name=?',(g.user['id'],tag)).fetchone()
                        if group and group['deleted_at']:
                            raise ValueError('Nhóm này đã được lưu trữ. Chọn tên nhóm khác.')
                        from data_groups import insert_data_group
                        insert_data_group(db,g.user['id'],tag)
                        updates.append('tag=?');values.append(tag)
                    if consent:
                        updates.append('consent=?');values.append(int(consent=='yes'))
                    count=db().execute('UPDATE contacts SET '+','.join(updates)+' WHERE user_id=? AND deleted_at IS NULL AND id IN ('+marks+')',
                                       (*values,g.user['id'],*ids)).rowcount
                    db().commit();flash(f'Đã cập nhật {count} khách hàng đã chọn.','success')
                return redirect(url_for('contacts'))
            groups=db().execute('SELECT name FROM data_groups WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall()
            return render_template('contact_selection.html',mode=mode,rows=rows[:50],total=len(ids),contact_ids=ids,groups=groups,page='contacts')
        except ValueError as error:
            db().rollback();flash(str(error),'error')
            return redirect(url_for('contacts'))

    @app.post('/contacts/bulk-edit')
    @login_required
    def bulk_edit_contacts():
        return handle('edit')

    @app.post('/contacts/bulk-delete')
    @login_required
    def bulk_delete_contacts():
        return handle('delete')

    @app.route('/contacts/<int:contact_id>/delete',methods=['GET','POST'])
    @login_required
    def delete_contact(contact_id):
        return handle('delete',[contact_id])
