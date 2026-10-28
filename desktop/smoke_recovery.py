"""Disposable packaged-app HTTP check; never used with a customer's database."""
import re
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


def verify_recovery_flow(url):
    browser = build_opener(HTTPCookieProcessor(CookieJar()))
    old_browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(opener, path):
        with opener.open(url + path, timeout=10) as response:
            return response.url, response.read().decode('utf-8')

    def post(opener, path, values):
        _, page = get(opener, '/account/security' if path == '/logout' else path)
        csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', page).group(1)
        request = Request(url + path, data=urlencode(dict(csrf=csrf, **values)).encode())
        with opener.open(request, timeout=10) as response:
            return response.url, response.read().decode('utf-8')

    assert '/forgot-password' in get(browser, '/login')[1]
    assert 'password-toggle' in get(browser, '/static/account-security.js')[1]
    post(browser, '/register', dict(name='Recovery smoke', username='recovery-smoke', password='temporary-old-password'))
    _, page = post(browser, '/account/security', dict(current_password='temporary-old-password'))
    code = re.search(r'<code id="issued-recovery-code">(ZFR-[A-F0-9-]+)</code>', page).group(1)
    post(old_browser, '/login', dict(username='recovery-smoke', password='temporary-old-password'))
    post(browser, '/logout', {})
    target, _ = post(browser, '/forgot-password', dict(username='recovery-smoke', recovery_code=code,
        password='temporary-new-password', confirm_password='temporary-new-password'))
    assert target.endswith('/login')
    assert get(old_browser, '/account/security')[0].endswith('/login')
    post(browser, '/login', dict(username='recovery-smoke', password='temporary-new-password'))
    assert get(browser, '/account/security')[0].endswith('/account/security')
    _, page = post(browser, '/forgot-password', dict(username='recovery-smoke', recovery_code=code,
        password='temporary-replay-password', confirm_password='temporary-replay-password'))
    assert 'không hợp lệ' in page
    return True
