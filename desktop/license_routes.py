from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from license_system.signatures import LicenseError


def register_license_routes(app, license):
    @app.context_processor
    def license_context():
        return dict(desktop_license_enabled=True)

    @app.before_request
    def enforce_desktop_license():
        if request.endpoint in ('static', 'desktop_license', 'login', 'logout', 'forgot_password', 'forgot_password_email', 'account_security', 'account_email', 'registration_pending', 'admin_users', 'admin_user_status'):
            return
        if not license.allowed():
            if request.path.startswith('/api/'):
                return jsonify(error='Cần kích hoạt bản quyền trên máy Windows.'), 403
            return redirect(url_for('desktop_license'))

    @app.route('/desktop/license', methods=['GET', 'POST'])
    def desktop_license():
        # Before the first local app account exists, allow only activation, not
        # remotely deactivating another user's already activated installation.
        if request.method == 'POST':
            action = request.form.get('action', 'activate')
            if action == 'deactivate' and not g.user:
                abort(403, 'Đăng nhập trước khi hủy kích hoạt máy này.')
            try:
                if action == 'activate':
                    license.activate(request.form.get('key', ''))
                    from desktop.admin_accounts import sync_license_admin
                    try:sync_license_admin(app,license)
                    except LicenseError as error:
                        app.extensions['desktop_admin_error']=str(error)
                        raise
                    flash('Đã kích hoạt bản quyền trong tool này.', 'success')
                elif action == 'deactivate':
                    license.deactivate()
                    flash('Đã hủy kích hoạt trong tool này. Với key theo phiên, có thể cần chờ tối đa 2 phút để dùng lại ở tool khác.', 'success')
                elif action == 'refresh':
                    license.refresh(force=True)
                    flash('Đã kiểm tra lại bản quyền.' if license.allowed() else license.error or 'Nhập key còn hạn để tiếp tục.', 'success' if license.allowed() else 'error')
                else:
                    abort(400)
            except (LicenseError, ConnectionError) as error:
                flash(str(error), 'error')
            return redirect(url_for('desktop_license'))
        status = license.status()
        expiry = ''
        if status['claims']:
            expiry = datetime.fromtimestamp(status['claims']['license_expires_at'], timezone.utc).astimezone(ZoneInfo('Asia/Bangkok')).strftime('%H:%M %d/%m/%Y')
        return render_template('desktop_license.html', page='license', license_status=status, expiry=expiry,
                               admin_setup_error=app.extensions.get('desktop_admin_error',''))
