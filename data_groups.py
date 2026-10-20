"""Data groups use the existing customer tag, shared with campaign audiences."""
import re
import csv
import io
import math

from flask import Response, abort, flash, g, jsonify, redirect, render_template, request, url_for
from data_import import read_contacts, insert_contact, read_sheet_rows, read_mapped_contacts


def register_data_groups(app, db, login_required, parse_phones):
    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS data_groups (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, UNIQUE(user_id,name))''')
        columns = {row['name'] for row in db().execute('PRAGMA table_info(data_groups)')}
        for column, definition in {'data_type': "TEXT NOT NULL DEFAULT 'all'", 'color': "TEXT NOT NULL DEFAULT '#6860f6'", 'created_at': 'TEXT', 'last_import_at': 'TEXT', 'imported_count': 'INTEGER NOT NULL DEFAULT 0', 'deleted_at': 'TEXT'}.items():
            if column not in columns:
                db().execute(f'ALTER TABLE data_groups ADD COLUMN {column} {definition}')
        contact_columns = {row['name'] for row in db().execute('PRAGMA table_info(contacts)')}
        if 'data_source' not in contact_columns:
            db().execute("ALTER TABLE contacts ADD COLUMN data_source TEXT NOT NULL DEFAULT ''")
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
        db().execute('INSERT OR IGNORE INTO data_groups(user_id,name) SELECT user_id,tag FROM contacts WHERE user_id=? GROUP BY tag', (g.user['id'],))
        db().commit()
        groups = db().execute('''SELECT names.name, d.id, count(p.id) AS total,
            COALESCE(d.data_type,'all') AS data_type, COALESCE(d.color,'#6860f6') AS color FROM
            (SELECT name FROM data_groups WHERE user_id=? UNION SELECT tag FROM contacts WHERE user_id=?) names
            LEFT JOIN contacts p ON p.tag=names.name AND p.user_id=?
            LEFT JOIN data_groups d ON d.name=names.name AND d.user_id=?
            WHERE d.deleted_at IS NULL GROUP BY names.name ORDER BY names.name''',
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
        rows = db().execute('''SELECT contacts.*,
            (SELECT s.recipient_name FROM message_sends s JOIN zalo_accounts a ON a.id=s.account_id
             WHERE s.contact_id=contacts.id AND a.user_id=contacts.user_id AND s.recipient_name!='' ORDER BY s.id DESC LIMIT 1) AS display_name,
            (SELECT group_concat(DISTINCT a.name) FROM message_sends s JOIN zalo_accounts a ON a.id=s.account_id
             WHERE s.contact_id=contacts.id AND a.user_id=contacts.user_id) AS account_names,
            EXISTS (SELECT 1 FROM message_sends s WHERE s.contact_id=contacts.id AND
                (s.state!='prepared' OR s.friend_state NOT IN ('prepared','not_requested') OR s.alias_state NOT IN ('prepared','not_requested'))) AS has_processed
            FROM contacts WHERE ''' + where + ' ORDER BY id DESC LIMIT 50 OFFSET ?',
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
        require_group(selected)
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

    def require_group(name):
        metadata = db().execute('SELECT * FROM data_groups WHERE user_id=? AND name=?', (g.user['id'], name)).fetchone()
        if metadata and metadata['deleted_at']:
            abort(404)
        if not metadata and not db().execute('SELECT 1 FROM contacts WHERE user_id=? AND tag=?', (g.user['id'], name)).fetchone():
            abort(404)
        return metadata

    @app.post('/data-groups/edit')
    @login_required
    def edit_data_group():
        original = request.form.get('original_group', '')
        require_group(original)
        name = request.form.get('name', '').strip()
        data_type = request.form.get('data_type', 'all')
        color = request.form.get('color', '#6860f6')
        try:
            if not name or len(name) > 80 or data_type not in ('all','phone','uid') or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                raise ValueError('Kiểm tra tên nhóm, loại data và màu nhóm.')
            db().execute('BEGIN IMMEDIATE')
            if name != original and db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?',
                                                  (g.user['id'], name, g.user['id'], name)).fetchone():
                raise ValueError('Tên nhóm đã tồn tại. Vui lòng chọn tên khác.')
            db().execute('INSERT OR IGNORE INTO data_groups(user_id,name) VALUES (?,?)', (g.user['id'], original))
            db().execute('UPDATE data_groups SET name=?,data_type=?,color=? WHERE user_id=? AND name=?', (name, data_type, color.lower(), g.user['id'], original))
            db().execute('UPDATE contacts SET tag=? WHERE user_id=? AND tag=?', (name, g.user['id'], original))
            db().execute('UPDATE campaigns SET tag=? WHERE user_id=? AND tag=?', (name, g.user['id'], original))
            db().commit()
            flash('Đã sửa nhóm data.', 'success')
            return redirect(url_for('data_groups', group=name))
        except ValueError as error:
            db().rollback()
            flash(str(error), 'error')
            return redirect(url_for('data_groups', group=original))

    @app.route('/data-groups/delete', methods=['GET','POST'])
    @login_required
    def delete_data_group():
        name = request.form.get('group', '') if request.method == 'POST' else request.args.get('group', '')
        metadata = require_group(name)
        if request.method == 'POST':
            if request.form.get('confirm_delete') != 'yes':
                abort(400)
            db().execute('INSERT OR IGNORE INTO data_groups(user_id,name) VALUES (?,?)', (g.user['id'], name))
            db().execute('UPDATE data_groups SET deleted_at=CURRENT_TIMESTAMP WHERE user_id=? AND name=?', (g.user['id'], name))
            db().commit()
            flash('Đã ẩn nhóm khỏi danh sách. Khách hàng và dữ liệu chiến dịch được giữ nguyên.', 'success')
            return redirect(url_for('data_groups'))
        return render_template('group_delete.html', name=name, page='data_groups')

    def group_import_input(preview=False):
        group = request.form.get('group', '')
        require_group(group)
        if request.form.get('data_type', 'phone') != 'phone':
            raise ValueError('Hiện hỗ trợ Zalo – User theo SĐT.')
        incoming = {phone: {'phone': phone} for phone in parse_phones(request.form.get('phones', ''))}
        invalid = []
        if request.form.get('import_mode') == 'mapped':
            if incoming:
                raise ValueError('Chỉ nhập một nguồn dữ liệu mỗi lần.')
            mapping = {key: request.form.get('column_' + key, '') for key in ('name','phone','info1','info2','info3','info4','info5')}
            mapped, invalid = read_mapped_contacts(request.files.get('file'), parse_phones, mapping,
                                                   request.form.get('skip_header') == 'yes', report=True)
            incoming.update(mapped)
            if invalid and not preview and request.form.get('skip_invalid') != 'yes':
                first = invalid[0]
                raise ValueError(f"Có {len(invalid)} dòng lỗi; dòng {first['row']}, SĐT {first['phone']!r}: {first['reason']} Kiểm tra bảng lỗi hoặc xác nhận bỏ qua dòng lỗi.")
        else:
            incoming.update(read_contacts(request.files.get('file'), parse_phones))
        if (not incoming and not (preview and invalid)) or len(incoming) > 500:
            raise ValueError('Mỗi lần nhập từ 1 đến 500 số điện thoại.')
        return group, incoming, invalid

    @app.post('/data-groups/import/columns')
    @login_required
    def inspect_group_import():
        group = request.form.get('group', '')
        require_group(group)
        try:
            rows = read_sheet_rows(request.files.get('file'))
            width = max(len(row) for row in rows)
            return jsonify(columns=[{'index': index, 'sample': rows[0][index][:100] if index < len(rows[0]) else ''}
                                    for index in range(width)], row_count=len(rows),
                           preview_rows=[[cell[:1000] for cell in row] for row in rows[:6]])
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/data-groups/import/preview')
    @login_required
    def preview_group_import():
        try:
            _, incoming, invalid = group_import_input(preview=True)
            rows = []
            existing_count = 0
            for phone, row in incoming.items():
                existing = db().execute('SELECT * FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
                if existing:
                    existing_count += 1
                source = dict(existing) if existing else row
                rows.append({key: source.get(key, '') for key in ('name','phone','email','zalo_id','info1','info2','info3','info4','info5')})
            return jsonify(rows=rows, total=len(rows), existing=existing_count, added=len(rows)-existing_count, invalid=len(invalid), invalid_rows=invalid)
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/data-groups/import')
    @login_required
    def import_group_data():
        group = request.form.get('group', '')
        try:
            group, incoming, invalid = group_import_input()
            consent = int(request.form.get('consent') == 'yes')
            added = 0
            upload = request.files.get('file')
            filename = re.sub(r'[\x00-\x1f\x7f]', '', (upload.filename or '').replace('\\', '/').split('/')[-1])[:150] if upload else ''
            source = 'Tải file lên · ' + filename if filename else 'Nhập trực tiếp'
            for phone, row in incoming.items():
                exists = db().execute('SELECT 1 FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
                if not exists:
                    insert_contact(db(), g.user['id'], phone, row, tag=group, consent=consent)
                    db().execute('UPDATE contacts SET data_source=? WHERE user_id=? AND phone=?', (source, g.user['id'], phone))
                    added += 1
            if added:
                db().execute('''INSERT INTO data_groups(user_id,name,last_import_at,imported_count)
                    VALUES (?,?,CURRENT_TIMESTAMP,?) ON CONFLICT(user_id,name) DO UPDATE SET
                    last_import_at=CURRENT_TIMESTAMP, imported_count=imported_count+excluded.imported_count''',
                    (g.user['id'], group, added))
            db().commit()
            flash(f'Đã thêm {added} khách hàng; bỏ qua {len(incoming)-added} số đã có và {len(invalid)} dòng lỗi đã xác nhận. Giữ nguyên nhóm và thông tin khách hàng cũ.', 'success')
        except ValueError as error:
            db().rollback()
            flash(str(error), 'error')
        return redirect(url_for('data_groups', group=group))
