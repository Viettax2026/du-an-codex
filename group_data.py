"""Owned collections of Zalo group destinations, separate from phone contacts."""
import json
import sqlite3

from flask import abort, g, jsonify, render_template, request


def initialize_group_data(db):
    db().executescript('''CREATE TABLE IF NOT EXISTS zalo_group_data (
        id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,name));
        CREATE TABLE IF NOT EXISTS zalo_group_data_members (
        id INTEGER PRIMARY KEY,data_group_id INTEGER NOT NULL REFERENCES zalo_group_data(id) ON DELETE CASCADE,
        account_id INTEGER NOT NULL REFERENCES zalo_accounts(id),group_id TEXT NOT NULL,name TEXT NOT NULL,
        source_row_id INTEGER NOT NULL REFERENCES data_scan_rows(id),UNIQUE(data_group_id,account_id,group_id));
        CREATE TABLE IF NOT EXISTS zalo_group_tags (
        user_id INTEGER NOT NULL REFERENCES users(id),account_id INTEGER NOT NULL REFERENCES zalo_accounts(id),
        group_id TEXT NOT NULL,tag TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,account_id,group_id,tag));''')


def owned_group_rows(db,user_id,account_id,raw,allow_empty=False):
    try:ids=json.loads(raw or '[]')
    except (ValueError,TypeError):raise ValueError('Chọn lại danh sách group.') from None
    if not isinstance(ids,list) or len(ids)>10000 or not ids and not allow_empty or any(type(i) is not int or i<1 for i in ids):
        raise ValueError('Chọn từ 1 đến 10.000 group Zalo.')
    ids=set(ids)
    if not ids:return []
    rows=db().execute('''SELECT r.* FROM data_scan_rows r JOIN data_scans s ON s.id=r.scan_id
        WHERE s.user_id=? AND s.account_id=? AND s.kind='groups' AND r.kind='group'
        AND r.id IN ('''+','.join('?' for _ in ids)+')',(user_id,account_id,*ids)).fetchall()
    if len(rows)!=len(ids):raise ValueError('Group không thuộc tài khoản gửi. Tải và chọn lại group của đúng tài khoản.')
    return list({row['uid']:row for row in rows}.values())


def collection_rows(db,user_id,group_id,account_id):
    if not db().execute('SELECT 1 FROM zalo_group_data WHERE id=? AND user_id=?',(group_id,user_id)).fetchone():abort(404)
    return db().execute('''SELECT m.id AS membership_id,m.source_row_id AS id,m.group_id AS uid,m.name,
        (SELECT group_concat(tag,', ') FROM zalo_group_tags t WHERE t.user_id=? AND t.account_id=m.account_id AND t.group_id=m.group_id) AS tags
        FROM zalo_group_data_members m WHERE m.data_group_id=? AND m.account_id=? ORDER BY m.id''',(user_id,group_id,account_id)).fetchall()


def register_group_data(app,db,login_required,manager):
    def account():
        value=request.values.get('account_id','')
        if not value:raise ValueError('Chọn tài khoản Zalo hợp lệ.')
        if not db().execute('SELECT 1 FROM zalo_accounts WHERE id=? AND user_id=? AND deleted_at IS NULL',(value,g.user['id'])).fetchone():abort(404)
        return value

    def own(group_id):
        row=db().execute('SELECT * FROM zalo_group_data WHERE id=? AND user_id=?',(group_id,g.user['id'])).fetchone()
        if not row:abort(404)
        return row

    def add_members(group_id,account_id):
        rows=owned_group_rows(db,g.user['id'],account_id,request.form.get('group_scan_row_ids'),allow_empty=True)
        added=0
        for row in rows:
            added+=db().execute('''INSERT OR IGNORE INTO zalo_group_data_members(data_group_id,account_id,group_id,name,source_row_id)
                VALUES (?,?,?,?,?)''',(group_id,account_id,row['uid'],row['name'],row['id'])).rowcount
        return added

    @app.get('/group-data')
    @login_required
    def group_data_page():return render_template('group_data.html',page='data_groups')

    @app.get('/group-data/catalog')
    @login_required
    def group_data_catalog():
        sender=request.args.get('account_id','')
        if sender:account()
        groups=db().execute('''SELECT d.id,d.name,count(m.id) AS total FROM zalo_group_data d
            LEFT JOIN zalo_group_data_members m ON m.data_group_id=d.id AND (?='' OR m.account_id=?)
            JOIN zalo_accounts a ON a.id=m.account_id AND a.deleted_at IS NULL
            WHERE d.user_id=? GROUP BY d.id ORDER BY d.name''',(sender,sender,g.user['id'])).fetchall()
        # Include empty collections as well as those containing other senders.
        counts={row['id']:row['total'] for row in groups}
        items=db().execute('SELECT id,name FROM zalo_group_data WHERE user_id=? ORDER BY name',(g.user['id'],)).fetchall()
        accounts=db().execute('SELECT id,name FROM zalo_accounts WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall()
        tags=db().execute('SELECT DISTINCT tag FROM zalo_group_tags WHERE user_id=? AND (?=\'\' OR account_id=?) ORDER BY tag',(g.user['id'],sender,sender)).fetchall()
        return jsonify(groups=[dict(row,total=counts.get(row['id'],0)) for row in items],accounts=[dict(row) for row in accounts],tags=[row['tag'] for row in tags])

    @app.post('/group-data/new')
    @login_required
    def new_group_data():
        try:
            name=request.form.get('name','').strip()
            if not name or len(name)>80:raise ValueError('Tên nhóm data cần từ 1 đến 80 ký tự.')
            sender=account()
            db().execute('BEGIN IMMEDIATE')
            group_id=db().execute('INSERT INTO zalo_group_data(user_id,name) VALUES (?,?)',(g.user['id'],name)).lastrowid
            added=add_members(group_id,sender);db().commit()
            return jsonify(id=group_id,name=name,added=added)
        except (ValueError,sqlite3.IntegrityError) as error:
            db().rollback();return jsonify(error=str(error) if isinstance(error,ValueError) else 'Tên nhóm data đã tồn tại.'),400

    @app.get('/group-data/<int:group_id>/members')
    @login_required
    def group_data_members(group_id):
        try:
            sender=account();own(group_id)
            rows=collection_rows(db,g.user['id'],group_id,sender)
            return jsonify(rows=[dict(row) for row in rows],total=len(rows))
        except ValueError as error:return jsonify(error=str(error)),400

    @app.post('/group-data/<int:group_id>/add')
    @login_required
    def add_group_data(group_id):
        try:
            own(group_id);sender=account();db().execute('BEGIN IMMEDIATE')
            added=add_members(group_id,sender);db().commit();return jsonify(added=added)
        except ValueError as error:db().rollback();return jsonify(error=str(error)),400

    @app.post('/group-data/<int:group_id>/remove/<int:member_id>')
    @login_required
    def remove_group_data_member(group_id,member_id):
        own(group_id)
        db().execute('DELETE FROM zalo_group_data_members WHERE id=? AND data_group_id=?',(member_id,group_id));db().commit()
        return jsonify(ok=True)

    @app.post('/group-data/<int:group_id>/delete')
    @login_required
    def delete_group_data(group_id):
        own(group_id);db().execute('BEGIN IMMEDIATE')
        for campaign in db().execute("SELECT id FROM campaigns WHERE user_id=? AND group_data_id=? AND group_data_mode='group'",(g.user['id'],group_id)).fetchall():
            app.extensions['group_campaign_runner'].sync_targets(manager.owned(campaign['id']))
            db().execute("UPDATE campaigns SET group_data_mode='direct',group_data_id=NULL WHERE id=?",(campaign['id'],))
            manager.event(campaign['id'],'group_source_deleted','Nhóm data đã xóa; giữ danh sách group hiện có của chiến dịch.')
        db().execute('DELETE FROM zalo_group_data_members WHERE data_group_id=?',(group_id,))
        db().execute('DELETE FROM zalo_group_data WHERE id=? AND user_id=?',(group_id,g.user['id']));db().commit()
        return jsonify(ok=True)

    @app.post('/group-data/<int:group_id>/rename')
    @login_required
    def rename_group_data(group_id):
        own(group_id);name=request.form.get('name','').strip()
        if not name or len(name)>80:return jsonify(error='Tên nhóm cần từ 1 đến 80 ký tự.'),400
        try:
            db().execute('UPDATE zalo_group_data SET name=? WHERE id=? AND user_id=?',(name,group_id,g.user['id']));db().commit();return jsonify(ok=True)
        except sqlite3.IntegrityError:db().rollback();return jsonify(error='Tên nhóm data đã tồn tại.'),400
