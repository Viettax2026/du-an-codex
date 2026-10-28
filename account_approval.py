"""Explicit account approval, separate from Windows license administration."""
from functools import wraps

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
    db().commit()


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


def register_approval(app, db, login_required):
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
