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
        if request.endpoint in ('static', 'desktop_license', 'login', 'logout', 'forgot_password', 'account_security'):
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
                    flash('Đã kích hoạt bản quyền cho máy này.', 'success')
                elif action == 'deactivate':
                    license.deactivate()
                    flash('Đã hủy kích hoạt. Bạn có thể nhập key trên máy khác.', 'success')
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
        return render_template('desktop_license.html', page='license', license_status=status, expiry=expiry)
