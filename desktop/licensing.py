"""Client verification only: no signing key, issuance or authority administration."""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from license_system.signatures import ActivationInvalid, LicenseError, decode, verify

REFRESH_SECONDS = 300
CONFIG_PATH = Path(__file__).resolve().parent / 'license-config.json'


def device_code():
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography', 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                identity = winreg.QueryValueEx(key, 'MachineGuid')[0]
        except OSError as error:
            raise LicenseError('Không đọc được mã máy Windows. Kiểm tra quyền đọc MachineGuid.') from error
    else:
        identity = Path('/etc/machine-id').read_text().strip()
    if not isinstance(identity, str) or len(identity.strip()) < 8:
        raise LicenseError('Không xác định được mã máy.')
    return 'ZFM1-' + hashlib.sha256(('ZaloFlow/Windows/v1:' + identity.strip().lower()).encode()).hexdigest().upper()


def load_config(path=CONFIG_PATH):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'))
        parts = urlsplit(config['server_url'])
        if config['version'] != 1 or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        if len(decode(config['public_key'])) != 32:
            raise ValueError()
        return config
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LicenseError('Bản cài chưa có cấu hình máy chủ bản quyền. Liên hệ người cung cấp phần mềm.') from error


class NoRedirect(HTTPRedirectHandler):
    # Activation credentials must never follow redirects to another host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange_http(config, action, data):
    url = config['server_url'].rstrip('/') + '/v1/' + action
    request = Request(url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            result = json.loads(response.read(16385))
            if not isinstance(result, dict):
                raise ValueError()
            return result
    except HTTPError as error:
        if error.code in (400, 403):
            try:
                result = json.loads(error.read(4096))
            except (ValueError, AttributeError):
                result = {}
            if not isinstance(result, dict):
                result = {}
            detail = result.get('error', '')
            detail = detail if isinstance(detail, str) else ''
            if result.get('error_code') == 'activation_invalid' or detail.startswith('Phiên kích hoạt không còn hiệu lực.'):
                raise ActivationInvalid(detail[:300] or 'Phiên kích hoạt đã bị hủy.') from error
            raise LicenseError(detail[:300] or 'Key không còn hiệu lực. Liên hệ người cấp key.') from error
        raise ConnectionError('Chưa kết nối được máy chủ bản quyền. Thử lại khi có mạng.') from error
    except (URLError, OSError, ValueError) as error:
        raise ConnectionError('Chưa kết nối được máy chủ bản quyền. Thử lại khi có mạng.') from error


class DesktopLicense:
    def __init__(self, folder, config=None, transport=exchange_http, device=None, clock=time.time, monotonic=time.monotonic):
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'activation.json'
        self.config = config
        self.transport = transport; self.device = device or device_code()
        self.clock, self.monotonic = clock, monotonic
        self.lock = threading.RLock()
        self.exchange_lock = threading.Lock()
        self.deactivating = False
        self.startup_verified = False
        self.state = {}; self.error = ''; self.next_refresh = 0
        if self.config is None:
            try:
                self.config = load_config()
            except LicenseError as error:
                self.error = str(error)
        self.anchor_time, self.anchor_monotonic = clock(), monotonic()
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(state, dict):
                self.state = state
        except (OSError, ValueError):
            pass

    def now(self):
        # A backwards clock change while running cannot prolong a signed lease.
        return max(self.clock(), self.anchor_time + self.monotonic() - self.anchor_monotonic)

    def claims(self):
        with self.lock:
            if self.config is None or self.deactivating or not self.startup_verified:
                return None
            try:
                return verify(self.state.get('lease', ''), self.config['public_key'], self.device, self.now())
            except LicenseError:
                return None

    def allowed(self):
        return self.claims() is not None

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(self.state, file)
        os.replace(temporary, self.path)

    def accept(self, response, secret=None):
        claims = verify(response.get('lease', ''), self.config['public_key'], self.device, self.clock())
        token = secret or self.state.get('activation_token')
        if not isinstance(token, str) or not 16 <= len(token) <= 200:
            raise LicenseError('Máy chủ trả về phiên kích hoạt không hợp lệ.')
        self.state = dict(lease=response['lease'], activation_token=token, key_hash=self.state.get('key_hash', ''))
        self.startup_verified = True
        self.anchor_time, self.anchor_monotonic = self.clock(), self.monotonic()
        self.next_refresh = self.monotonic() + REFRESH_SECONDS
        self.error = ''; self.save()
        return claims

    def activate(self, key):
        key = key.strip()
        if not re.fullmatch(r'ZF-[A-Za-z0-9_-]{32}', key):
            raise LicenseError('Key không đúng định dạng. Sao chép đầy đủ key được cấp.')
        with self.exchange_lock:
            if self.config is None:
                raise LicenseError(self.error or 'Chưa cấu hình máy chủ bản quyền.')
            fingerprint = hashlib.sha256(key.encode()).hexdigest()
            if self.state.get('activation_token') and self.state.get('key_hash') and self.state['key_hash'] != fingerprint:
                raise LicenseError('Hủy kích hoạt key hiện tại trước khi nhập key khác. Nếu đã gia hạn cùng key, bấm Kiểm tra lại.')
            response = self.transport(self.config, 'activate', dict(device=self.device, key=key))
            with self.lock:
                claims = self.accept(response, response.get('activation_token'))
                self.state['key_hash'] = fingerprint; self.save()
                return claims

    def refresh(self, force=False):
        with self.exchange_lock:
            if self.config is None:
                return False
            if not force and self.monotonic() < self.next_refresh:
                return self.allowed()
            self.next_refresh = self.monotonic() + REFRESH_SECONDS
            if not self.state.get('activation_token'):
                return False
            try:
                response = self.transport(self.config, 'refresh', dict(device=self.device, activation_token=self.state['activation_token']))
                with self.lock:
                    self.accept(response)
            except ActivationInvalid as error:
                with self.lock:
                    self.error = str(error); self.state = {}; self.save()
            except LicenseError as error:
                # An explicit denial invalidates cached access immediately.
                with self.lock:
                    self.error = str(error); self.state.pop('lease', None); self.save()
            except ConnectionError as error:
                # Connectivity failures never create or extend a signed lease.
                self.error = str(error)
            return self.allowed()

    def deactivate(self):
        with self.exchange_lock:
            with self.lock:
                self.deactivating = True
            try:
                if self.state.get('activation_token'):
                    try:
                        self.transport(self.config, 'deactivate', dict(device=self.device, activation_token=self.state['activation_token']))
                    except ActivationInvalid:
                        pass  # The server has already released this session.
                with self.lock:
                    self.state = {}; self.error = ''; self.save()
            finally:
                with self.lock:
                    self.deactivating = False

    def status(self):
        claims = self.claims()
        return dict(allowed=bool(claims), device=self.device, claims=claims, error=self.error,
                    can_deactivate=bool(self.state.get('activation_token')))
