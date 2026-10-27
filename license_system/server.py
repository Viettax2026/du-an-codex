"""Run behind HTTPS: gunicorn 'license_system.server:create_app()'."""
import os
import re
from datetime import timedelta

from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from license_system.authority import Authority
from license_system.signatures import ActivationInvalid, LicenseError


def create_app(folder=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 4096
    authority = Authority(folder or os.environ.get('ZALOFLOW_LICENSE_DATA', '/var/lib/zaloflow-licenses'))
    app.extensions['authority'] = authority
    app.config.update(SECRET_KEY=authority.folder.joinpath('session-secret.txt').read_text().strip(),
                      SESSION_COOKIE_NAME='zaloflow_license_admin', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Strict',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=1))
    if os.environ.get('ZALOFLOW_LICENSE_TRUST_PROXY') == '1':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=1)
    from license_system.web_admin import register_admin
    register_admin(app, authority)

    @app.post('/v1/<action>')
    def exchange(action):
        if action not in ('activate', 'refresh', 'deactivate'):
            return jsonify(error='Không tìm thấy thao tác.'), 404
        # Use the direct peer unless a trusted reverse proxy is configured outside
        # this app; never trust arbitrary client-supplied X-Forwarded-For headers.
        if not authority.throttle(request.remote_addr or 'unknown'):
            return jsonify(error='Quá nhiều yêu cầu. Vui lòng thử lại sau.'), 429
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Yêu cầu không hợp lệ.'), 400
        device, credential = data.get('device'), data.get('key' if action == 'activate' else 'activation_token')
        if not isinstance(device, str) or not re.fullmatch(r'ZFM1-[A-F0-9]{64}', device) or not isinstance(credential, str) or not 16 <= len(credential) <= 200:
            return jsonify(error='Mã máy hoặc key không hợp lệ.'), 400
        try:
            return jsonify(authority.exchange(action, device, credential))
        except ActivationInvalid as error:
            return jsonify(error=str(error), error_code='activation_invalid'), 403
        except LicenseError as error:
            return jsonify(error=str(error)), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    return app
