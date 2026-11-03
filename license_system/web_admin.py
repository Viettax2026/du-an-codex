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
        key_view = None
        if request.method == 'POST':
            try:
                action = request.form.get('action')
                if action == 'issue':
                    issued = authority.issue(request.form.get('customer', ''), int(request.form.get('days', '30')), seats=1, mode='floating',
                                             admin_username='' if request.form.get('admin_username_auto') == '1' else request.form.get('admin_username', ''))
                    flash('Đã tạo key kèm tài khoản và mật khẩu quản trị tool. Bấm Xem key để xem lại bộ thông tin đã cấp.')
                elif action == 'show-key':
                    key_view = authority.key_for_owner(int(request.form.get('license_id','0')))
                elif action == 'save-key-copy':
                    license_id = int(request.form.get('license_id','0'))
                    key_view = authority.key_for_owner(license_id)
                    authority.save_original_key(license_id,request.form.get('original_key',''))
                    key_view = authority.key_for_owner(license_id)
                    flash('Đã lưu bản key gốc để xem lại. Giữ nguyên hạn dùng, quyền và các kích hoạt.')
                elif action == 'create-tool-admin':
                    license_id = int(request.form.get('license_id','0'))
                    key_view = authority.key_for_owner(license_id)
                    authority.create_tool_admin(license_id,'' if request.form.get('admin_username_auto') == '1' else request.form.get('admin_username',''))
                    key_view = authority.key_for_owner(license_id)
                    flash('Đã tạo quản trị cho key hiện tại. Đóng/mở tool hoặc bấm Kiểm tra lại bản quyền để nhận tài khoản; key và hạn dùng giữ nguyên.')
                else:
                    if action == 'delete' and request.form.get('confirm_delete') != '1':
                        raise LicenseError('Vui lòng xác nhận xóa vĩnh viễn key đã thu hồi.')
                    authority.manage(int(request.form.get('license_id', '0')), action, int(request.form.get('days', '30')))
                    flash({'revoke': 'Đã thu hồi key.', 'extend': 'Đã gia hạn key.', 'reset-devices': 'Đã hủy các kích hoạt. Key theo phiên có thể cần chờ tối đa 2 phút để kết thúc lượt đang xử lý.',
                           'delete': 'Đã xóa vĩnh viễn key đã thu hồi và các kích hoạt của key này.'}[action])
                    return redirect(url_for('admin_panel'))
            except (LicenseError, ValueError) as error:
                flash(str(error) or 'Thông tin không hợp lệ.')
        return render_template('license_admin.html', licenses=authority.list_licenses(), issued=issued, key_view=key_view)
