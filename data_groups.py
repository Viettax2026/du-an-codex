"""Data groups use the existing customer tag, shared with campaign audiences."""
import re
import csv
import io
import math

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from data_import import read_contacts, insert_contact


def register_data_groups(app, db, login_required, parse_phones):
    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS data_groups (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, UNIQUE(user_id,name))''')
        columns = {row['name'] for row in db().execute('PRAGMA table_info(data_groups)')}
        for column, definition in {'data_type': "TEXT NOT NULL DEFAULT 'all'", 'color': "TEXT NOT NULL DEFAULT '#6860f6'", 'created_at': 'TEXT', 'last_import_at': 'TEXT', 'imported_count': 'INTEGER NOT NULL DEFAULT 0'}.items():
            if column not in columns:
                db().execute(f'ALTER TABLE data_groups ADD COLUMN {column} {definition}')
        db().commit()

    @app.route('/data-groups', methods=['GET', 'POST'])
    @login_required
    def data_groups():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            data_type = request.form.get('data_type', 'all')
            color = request.form.get('color', '#6860f6')
            error = None
            if not name or len(name) > 80:
                error = 'Tên nhóm cần từ 1 đến 80 ký tự.'
            elif data_type not in ('all', 'phone', 'uid'):
                error = 'Loại data không hợp lệ.'
            elif not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                error = 'Màu nhóm không hợp lệ.'
            elif db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?',
                              (g.user['id'], name, g.user['id'], name)).fetchone():
                error = 'Tên nhóm đã tồn tại. Vui lòng chọn tên khác.'
            if error:
                flash(error, 'error')
            else:
                db().execute('INSERT INTO data_groups(user_id,name,data_type,color,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)',
                             (g.user['id'], name, data_type, color.lower()))
                db().commit()
                return redirect(url_for('data_groups', group=name))
        groups = db().execute('''SELECT names.name, count(p.id) AS total,
            COALESCE(d.data_type,'all') AS data_type, COALESCE(d.color,'#6860f6') AS color FROM
            (SELECT name FROM data_groups WHERE user_id=? UNION SELECT tag FROM contacts WHERE user_id=?) names
            LEFT JOIN contacts p ON p.tag=names.name AND p.user_id=?
            LEFT JOIN data_groups d ON d.name=names.name AND d.user_id=?
            GROUP BY names.name ORDER BY names.name''',
            (g.user['id'], g.user['id'], g.user['id'], g.user['id'])).fetchall()
        selected = request.args.get('group', groups[0]['name'] if groups else '')
        if selected and selected not in [row['name'] for row in groups]:
            abort(404)
        query = request.args.get('q', '').strip()[:120]
        kind = request.args.get('kind', '')
        consent = request.args.get('consent', '')
        if kind not in ('', 'phone', 'uid') or consent not in ('', 'yes', 'no'):
            abort(400)
        accounts = db().execute('SELECT id,name FROM zalo_accounts WHERE user_id=? ORDER BY name,id', (g.user['id'],)).fetchall()
        account_id = request.args.get('account_id', '')
        if account_id and (not account_id.isdigit() or int(account_id) not in {account['id'] for account in accounts}):
            abort(404)
        where = "user_id=? AND tag=? AND (name LIKE ? OR phone LIKE ? OR zalo_id LIKE ?)"
        params = [g.user['id'], selected, *(['%' + query + '%'] * 3)]
        if kind == 'uid':
            where += " AND zalo_id!=''"
        elif kind == 'phone':
            where += " AND phone!=''"
        if consent:
            where += ' AND consent=?'
            params.append(int(consent == 'yes'))
        if account_id:
            where += ''' AND (EXISTS (SELECT 1 FROM message_sends s WHERE s.contact_id=contacts.id AND s.account_id=?)
                OR EXISTS (SELECT 1 FROM campaigns c WHERE c.user_id=contacts.user_id AND c.account_id=? AND c.deleted_at IS NULL
                    AND ((c.audience_mode='group' AND (c.tag='' OR c.tag=contacts.tag)) OR
                         (c.audience_mode='list' AND EXISTS (SELECT 1 FROM campaign_contacts cc WHERE cc.campaign_id=c.id AND cc.contact_id=contacts.id)))))'''
            params.extend([int(account_id), int(account_id)])
        filtered = db().execute('SELECT count(*) FROM contacts WHERE ' + where, params).fetchone()[0]
        pages = max(1, math.ceil(filtered / 50))
        number = max(1, min(request.args.get('p', 1, type=int), pages))
        rows = db().execute('SELECT * FROM contacts WHERE ' + where + ' ORDER BY id DESC LIMIT 50 OFFSET ?',
                            (*params, (number - 1) * 50)).fetchall()
        total = next((row['total'] for row in groups if row['name'] == selected), 0)
        metadata = db().execute('SELECT * FROM data_groups WHERE user_id=? AND name=?', (g.user['id'], selected)).fetchone()
        usage = db().execute('''SELECT count(*) FROM campaigns c WHERE c.user_id=? AND c.deleted_at IS NULL AND
            ((c.audience_mode='group' AND (c.tag=? OR c.tag='')) OR
             (c.audience_mode='list' AND EXISTS (SELECT 1 FROM campaign_contacts cc JOIN contacts p ON p.id=cc.contact_id
                WHERE cc.campaign_id=c.id AND p.user_id=? AND p.tag=?)))''',
            (g.user['id'], selected, g.user['id'], selected)).fetchone()[0] if selected else 0
        runs = db().execute('''SELECT count(*) FROM message_sends s JOIN contacts p ON p.id=s.contact_id
            WHERE p.user_id=? AND p.tag=? AND (s.state!='prepared' OR s.friend_state NOT IN ('prepared','not_requested')
            OR s.alias_state NOT IN ('prepared','not_requested'))''', (g.user['id'], selected)).fetchone()[0]
        distribution = db().execute("SELECT count(*) AS phones, sum(zalo_id!='') AS uids, sum(consent=1) AS consented FROM contacts WHERE user_id=? AND tag=?",
                                     (g.user['id'], selected)).fetchone()
        return render_template('data_groups.html', groups=groups, selected=selected, rows=rows,
                               total=total, query=query, page='data_groups', metadata=metadata, usage=usage,
                               runs=runs, distribution=distribution, filtered=filtered, number=number, pages=pages,
                               kind=kind, consent=consent, accounts=accounts, account_id=account_id,
                               data_type_labels={'all': 'Mọi loại dữ liệu', 'phone': 'Số điện thoại', 'uid': 'UID'})

    @app.post('/data-groups/export')
    @login_required
    def export_group_data():
        selected = request.form.get('group', '')
        ids = request.form.getlist('contact_ids')
        if len(ids) > 50 or not ids or not all(value.isdigit() for value in ids):
            abort(400)
        rows = db().execute('SELECT name,phone,zalo_id,email,info1,info2,info3,info4,info5 FROM contacts WHERE user_id=? AND tag=? AND id IN (' +
                            ','.join('?' for _ in ids) + ') ORDER BY id', (g.user['id'], selected, *ids)).fetchall()
        if len(rows) != len(set(ids)):
            abort(404)
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['name','phone','zalo_id','email','info1','info2','info3','info4','info5'])
        for row in rows:
            writer.writerow(["'" + value if str(value).lstrip().startswith(('=', '+', '-', '@')) else value for value in row])
        return Response('\ufeff' + stream.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="group-data.csv"'})

    @app.post('/data-groups/import')
    @login_required
    def import_group_data():
        group = request.form.get('group', '')
        if not db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?',
                            (g.user['id'], group, g.user['id'], group)).fetchone():
            abort(404)
        try:
            incoming = {phone: {'phone': phone} for phone in parse_phones(request.form.get('phones', ''))}
            incoming.update(read_contacts(request.files.get('file'), parse_phones))
            if not incoming or len(incoming) > 500:
                raise ValueError('Mỗi lần nhập từ 1 đến 500 số điện thoại.')
            consent = int(request.form.get('consent') == 'yes')
            added = 0
            for phone, row in incoming.items():
                exists = db().execute('SELECT 1 FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
                if not exists:
                    insert_contact(db(), g.user['id'], phone, row, tag=group, consent=consent)
                    added += 1
            if added:
                db().execute('''INSERT INTO data_groups(user_id,name,last_import_at,imported_count)
                    VALUES (?,?,CURRENT_TIMESTAMP,?) ON CONFLICT(user_id,name) DO UPDATE SET
                    last_import_at=CURRENT_TIMESTAMP, imported_count=imported_count+excluded.imported_count''',
                    (g.user['id'], group, added))
            db().commit()
            flash(f'Đã thêm {added} khách hàng; bỏ qua {len(incoming)-added} số đã có. Giữ nguyên nhóm và thông tin khách hàng cũ.', 'success')
        except ValueError as error:
            db().rollback()
            flash(str(error), 'error')
        return redirect(url_for('data_groups', group=group))
