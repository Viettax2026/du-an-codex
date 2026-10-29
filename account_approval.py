"""Explicit account approval, separate from Windows license administration."""
from functools import wraps
import re

import click
from flask import abort, flash, g, redirect, render_template, request, url_for

STATES = {'pending': 'Chờ duyệt', 'approved': 'Đã duyệt', 'rejected': 'Từ chối', 'blocked': 'Đã khóa'}


def initialize_approval(db):
    columns = {row['name'] for row in db().execute('PRAGMA table_info(users)')}
    if 'approval_status' not in columns:
        db().execute("ALTER TABLE users ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'pending' CHECK(approval_status IN ('pending','approved','rejected','blocked'))")
        # Preserve existing operators and data. This runs only once, never
        # approves registrations submitted after this migration.
        db().execute("UPDATE users SET approval_status='approved'")
    for name, declaration in {
        'role': "TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin'))",
        'registered_at': "TEXT NOT NULL DEFAULT ''",
        'approved_at': 'TEXT',
        'approved_by': 'INTEGER REFERENCES users(id)',
    }.items():
        if name not in columns:
            db().execute(f'ALTER TABLE users ADD COLUMN {name} {declaration}')
    db().execute('''CREATE TABLE IF NOT EXISTS account_approval_events (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db().executescript('''CREATE TABLE IF NOT EXISTS retired_user_ids (id INTEGER PRIMARY KEY);
        CREATE TRIGGER IF NOT EXISTS users_prevent_retired_id AFTER INSERT ON users
        WHEN EXISTS (SELECT 1 FROM retired_user_ids WHERE id=NEW.id)
        BEGIN SELECT RAISE(ABORT,'Retired account IDs cannot be reused'); END;''')
    db().commit()


def create_pending_account(connection, name, username, password_hash):
    # Allocate in the same write statement. An old browser session or a local
    # credential directory must never become the identity of a different user.
    return connection.execute('''INSERT INTO users(id,name,username,password,approval_status,role,registered_at)
        SELECT coalesce(max(id),0)+1,?,?,?,'pending','user',CURRENT_TIMESTAMP
        FROM (SELECT id FROM users UNION ALL SELECT id FROM retired_user_ids)''', (name, username, password_hash))


def set_approval(connection, user_id, status, actor_id=None):
    if status not in STATES:
        raise ValueError('Trạng thái không hợp lệ.')
    target = connection.execute('SELECT id,role,approval_status FROM users WHERE id=?', (user_id,)).fetchone()
    if not target:
        raise ValueError('Không tìm thấy tài khoản.')
    if target['role'] == 'admin' and status != 'approved':
        raise ValueError('Không khóa hoặc từ chối tài khoản quản trị tại đây.')
    if target['approval_status'] == status:
        return False
    connection.execute('''UPDATE users SET approval_status=?,auth_version=auth_version+1,
        approved_at=CASE WHEN ?='approved' THEN CURRENT_TIMESTAMP ELSE approved_at END,
        approved_by=CASE WHEN ?='approved' THEN ? ELSE approved_by END WHERE id=?''',
        (status, status, status, actor_id, user_id))
    connection.execute('INSERT INTO account_approval_events(user_id,actor_id,action) VALUES (?,?,?)',
                       (user_id, actor_id, status))
    return True


def grant_admin(connection, username):
    user = connection.execute('SELECT id,role FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
    if not user:
        raise ValueError('Không tìm thấy tài khoản. Đăng ký tài khoản trước hoặc dùng reset-admin để tạo admin.')
    set_approval(connection, user['id'], 'approved')
    if user['role'] != 'admin':
        connection.execute("UPDATE users SET role='admin',auth_version=auth_version+1 WHERE id=?", (user['id'],))
        connection.execute("INSERT INTO account_approval_events(user_id,action) VALUES (?,'grant_admin')", (user['id'],))


def delete_empty_test_user(connection, username):
    """Caller owns the local database; delete only a named, empty test account.

    Keep SQLite foreign keys enabled. Operational data and other users' audit
    history are never cascaded away to make a deletion succeed.
    """
    username = username.strip().lower()
    if not re.fullmatch(r'test[a-z0-9_.-]{0,60}', username):
        raise ValueError('Lệnh này chỉ xóa tài khoản thử có tên bắt đầu bằng test.')
    if not connection.execute('PRAGMA foreign_keys').fetchone()[0]:
        raise ValueError('Cần bật bảo vệ khóa ngoại trước khi xóa tài khoản.')
    connection.execute('BEGIN IMMEDIATE')
    try:
        user = connection.execute('SELECT id,role FROM users WHERE username=?', (username,)).fetchone()
        if not user:
            connection.rollback()
            return False
        if user['role'] == 'admin':
            raise ValueError('Không xóa tài khoản quản trị bằng lệnh xóa tài khoản thử.')
        def quote(value):
            return '"' + value.replace('"', '""') + '"'
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(' + quote(table) + ')')}
            references = {row['from'] for row in connection.execute('PRAGMA foreign_key_list(' + quote(table) + ')') if row['table'].lower() == 'users'}
            if 'user_id' in columns:
                references.add('user_id')
            for column in references:
                if (table, column) in {('account_recovery_codes','user_id'), ('account_email_codes','user_id'), ('account_approval_events','user_id')}:
                    continue
                # Own approval events will be removed below; a reference from
                # another account's history must still prevent deletion.
                extra = ' AND user_id<>?' if table == 'account_approval_events' and column == 'actor_id' else ''
                args = (user['id'], user['id']) if extra else (user['id'],)
                if connection.execute('SELECT 1 FROM ' + quote(table) + ' WHERE ' + quote(column) + '=?' + extra + ' LIMIT 1', args).fetchone():
                    raise ValueError('Tài khoản còn dữ liệu hoặc liên kết trong ' + table + '. Chưa xóa tài khoản hay dữ liệu nào.')
        connection.execute('DELETE FROM account_recovery_codes WHERE user_id=?', (user['id'],))
        connection.execute('DELETE FROM account_email_codes WHERE user_id=?', (user['id'],))
        connection.execute('DELETE FROM account_approval_events WHERE user_id=?', (user['id'],))
        connection.execute('INSERT INTO retired_user_ids(id) VALUES (?)', (user['id'],))
        connection.execute('DELETE FROM users WHERE id=?', (user['id'],))
        connection.commit()
        return True
    except BaseException:
        connection.rollback()
        raise


def register_approval(app, db, login_required):
    @app.cli.command('delete-test-user')
    @click.option('--username', required=True)
    def delete_test_account(username):
        """Local VPS owner: delete one empty test account by exact username."""
        try:
            deleted = delete_empty_test_user(db(), username)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo('Đã xóa tài khoản thử ' + username.strip().lower() + '.' if deleted else 'Không tìm thấy tài khoản thử này; không thay đổi dữ liệu.')

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user['role'] != 'admin':
                abort(403, 'Chỉ quản trị viên được quản lý tài khoản.')
            return view(*args, **kwargs)
        return wrapped

    @app.get('/registration-pending')
    def registration_pending():
        return render_template('registration_pending.html')

    @app.get('/admin/users')
    @admin_required
    def admin_users():
        state = request.args.get('status', 'pending')
        if state not in (*STATES, 'all'):
            state = 'pending'
        search = request.args.get('q', '').strip()[:100]
        raw_page = request.args.get('page', '1')
        page = int(raw_page) if raw_page.isdecimal() and len(raw_page) <= 6 else 1
        where, args = [], []
        if state != 'all':
            where.append('approval_status=?'); args.append(state)
        if search:
            where.append('(username LIKE ? OR name LIKE ?)'); args.extend(['%' + search + '%'] * 2)
        predicate = ' WHERE ' + ' AND '.join(where) if where else ''
        total = db().execute('SELECT count(*) FROM users' + predicate, args).fetchone()[0]
        pages = max(1, (total + 49) // 50); page = max(1, min(page, pages))
        users = db().execute('''SELECT id,name,username,role,approval_status,registered_at,approved_at
            FROM users''' + predicate + ' ORDER BY id DESC LIMIT 50 OFFSET ?', (*args, (page-1)*50)).fetchall()
        counts = {row['approval_status']: row['n'] for row in db().execute('SELECT approval_status,count(*) AS n FROM users GROUP BY approval_status')}
        return render_template('admin_users.html', page='users', users=users, states=STATES,
                               selected_status=state, search=search, counts=counts, total=total, current_page=page, pages=pages)

    @app.post('/admin/users/<int:user_id>/status')
    @admin_required
    def admin_user_status(user_id):
        state = request.form.get('status', '')
        if state not in STATES or state == 'pending':
            abort(400, 'Chọn Duyệt, Từ chối hoặc Khóa.')
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        try:
            actor = connection.execute('SELECT role,approval_status,auth_version FROM users WHERE id=?', (g.user['id'],)).fetchone()
            if not actor or actor['role'] != 'admin' or actor['approval_status'] != 'approved' or actor['auth_version'] != g.user['auth_version']:
                abort(403)
            target = connection.execute('SELECT id,role FROM users WHERE id=?', (user_id,)).fetchone()
            if not target:
                abort(404)
            if user_id == g.user['id'] or target['role'] == 'admin':
                abort(400, 'Không thay đổi quyền truy cập của tài khoản quản trị tại đây.')
            changed = set_approval(connection, user_id, state, actor_id=g.user['id'])
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        flash(('Đã cập nhật: ' + STATES[state] + '.') if changed else 'Tài khoản đã ở trạng thái này.', 'success')
        selected = request.form.get('filter_status', 'pending')
        return redirect(url_for('admin_users', status=selected if selected in (*STATES, 'all') else 'pending', q=request.form.get('q', '')[:100]))

    @app.cli.command('grant-admin')
    @click.option('--username', required=True)
    def grant_account_admin(username):
        """Local VPS owner: grant administration without changing the password."""
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        try:
            grant_admin(connection, username)
            connection.commit()
        except ValueError as error:
            connection.rollback()
            raise click.ClickException(str(error)) from error
        click.echo('Đã cấp quyền quản trị và duyệt tài khoản. Mật khẩu và dữ liệu được giữ nguyên; đăng nhập lại để quản lý tài khoản.')

    @app.cli.command('approve-user')
    @click.option('--username', required=True)
    def approve_account(username):
        """Local VPS owner: approve an existing account; does not grant admin."""
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        user = connection.execute('SELECT id FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        if not user:
            connection.rollback()
            raise click.ClickException('Không tìm thấy tài khoản.')
        set_approval(connection, user['id'], 'approved')
        connection.commit()
        click.echo('Đã duyệt tài khoản. Người dùng có thể đăng nhập bằng mật khẩu đã đăng ký.')
