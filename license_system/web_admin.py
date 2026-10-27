import secrets
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from license_system.signatures import LicenseError


def register_admin(app, authority):
    def require_admin(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get('admin_epoch') or session['admin_epoch'] != authority.setting('admin_epoch'):
                return redirect(url_for('admin_login'))
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def csrf_admin():
        if request.endpoint not in ('admin_login', 'admin_panel', 'admin_logout'):
            return
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf', '')):
            abort(400, 'Phiên làm việc hết hạn. Tải lại trang.')

    @app.template_filter('license_time')
    def license_time(timestamp):
        return datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo('Asia/Bangkok')).strftime('%H:%M %d/%m/%Y')

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            if not authority.throttle('admin:' + (request.remote_addr or 'unknown')):
                abort(429, 'Quá nhiều lần thử. Thử lại sau 15 phút.')
            password = request.form.get('password', '')
            if len(password) <= 256 and check_password_hash(authority.setting('admin_password_hash'), password):
                session.clear(); session['admin_epoch'] = authority.setting('admin_epoch'); session.permanent = True
                return redirect(url_for('admin_panel'))
            flash('Mật khẩu quản trị không đúng.')
        return render_template('license_admin_login.html')

    @app.post('/admin/logout')
    def admin_logout():
        session.clear()
        return redirect(url_for('admin_login'))

    @app.route('/admin', methods=['GET', 'POST'])
    @require_admin
    def admin_panel():
        issued = None
        if request.method == 'POST':
            try:
                action = request.form.get('action')
                if action == 'issue':
                    issued = authority.issue(request.form.get('customer', ''), int(request.form.get('days', '30')), seats=1)
                    flash('Đã tạo key. Sao chép ngay: hệ thống chỉ lưu mã kiểm tra, không lưu lại key gốc.')
                else:
                    authority.manage(int(request.form.get('license_id', '0')), action, int(request.form.get('days', '30')))
                    flash({'revoke': 'Đã thu hồi key.', 'extend': 'Đã gia hạn key.', 'reset-devices': 'Đã hủy các máy đang kích hoạt.'}[action])
                    return redirect(url_for('admin_panel'))
            except (LicenseError, ValueError) as error:
                flash(str(error) or 'Thông tin không hợp lệ.')
        return render_template('license_admin.html', licenses=authority.list_licenses(), issued=issued)
