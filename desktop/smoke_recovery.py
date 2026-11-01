"""Disposable packaged-app HTTP check; never used with a customer's database."""
import re
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


def verify_admin_flow(url, username, password):
    """A signed synthetic key provisions the owner before this HTTP check."""
    owner = build_opener(HTTPCookieProcessor(CookieJar()))
    child = build_opener(HTTPCookieProcessor(CookieJar()))

    def post(opener, path, values, source):
        with opener.open(url+source,timeout=10) as response:
            page=response.read().decode('utf-8')
        csrf=re.search(r'name="csrf" value="([a-f0-9]+)"',page).group(1)
        request=Request(url+path,data=urlencode(dict(csrf=csrf,**values)).encode())
        with opener.open(request,timeout=10) as response:
            return response.url,response.read().decode('utf-8')

    post(owner,'/login',dict(username=username,password=password),'/login')
    _,page=post(owner,'/admin/users/create',dict(name='Native staff',username='native-staff',password='staff888',
                    confirm_password='staff888'),'/admin/users')
    assert 'Đã tạo tài khoản thường' in page
    target,_=post(child,'/login',dict(username='native-staff',password='staff888'),'/login')
    assert target.rstrip('/')==url
    try:
        child.open(url+'/admin/users',timeout=10)
    except HTTPError as error:
        assert error.code==403
    else:
        raise AssertionError('A regular account acquired admin rights')
    return True


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
    post(browser, '/register', dict(name='Recovery smoke', username='recovery-smoke', email='smoke@example.com', password='temporary-old-password'))
    target, _ = post(browser, '/login', dict(username='recovery-smoke', password='temporary-old-password'))
    assert target.rstrip('/') == url, 'A licensed desktop registration must log in without approval'
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
