"""Data groups use the existing customer tag, shared with campaign audiences."""
import re

from flask import abort, flash, g, redirect, render_template, request, url_for
from data_import import read_contacts, insert_contact


def register_data_groups(app, db, login_required, parse_phones):
    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS data_groups (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, UNIQUE(user_id,name))''')
        columns = {row['name'] for row in db().execute('PRAGMA table_info(data_groups)')}
        for column, definition in {'data_type': "TEXT NOT NULL DEFAULT 'all'", 'color': "TEXT NOT NULL DEFAULT '#6860f6'"}.items():
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
                db().execute('INSERT INTO data_groups(user_id,name,data_type,color) VALUES (?,?,?,?)',
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
        rows = db().execute('''SELECT * FROM contacts WHERE user_id=? AND tag=?
            AND (name LIKE ? OR phone LIKE ? OR zalo_id LIKE ?) ORDER BY id DESC LIMIT 500''',
            (g.user['id'], selected, *(['%' + query + '%'] * 3))).fetchall()
        total = next((row['total'] for row in groups if row['name'] == selected), 0)
        return render_template('data_groups.html', groups=groups, selected=selected, rows=rows,
                               total=total, query=query, page='data_groups',
                               data_type_labels={'all': 'Mọi loại dữ liệu', 'phone': 'Số điện thoại', 'uid': 'UID'})

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
            db().commit()
            flash(f'Đã thêm {added} khách hàng; bỏ qua {len(incoming)-added} số đã có. Giữ nguyên nhóm và thông tin khách hàng cũ.', 'success')
        except ValueError as error:
            db().rollback()
            flash(str(error), 'error')
        return redirect(url_for('data_groups', group=group))
