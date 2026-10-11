"""Private QR login workers; no credentials are exposed through HTTP."""
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path


class QRConnector:
    def __init__(self, instance_path, source_path):
        self.root = Path(instance_path) / 'zalo'
        self.worker = Path(source_path) / 'connector' / 'qr-login.mjs'
        self.lock = threading.Lock()
        self.jobs = {}

    def available(self):
        return bool(shutil.which('node') and (self.worker.parent / 'node_modules' / 'zca-js').is_dir())

    @staticmethod
    def write_json(path, data):
        temporary = path.with_name(path.name + '.tmp')
        with open(temporary, 'w', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            json.dump(data, stream)
        temporary.replace(path)

    def account_path(self, user_id, account_id):
        return self.root / str(int(user_id)) / str(int(account_id))

    def status(self, user_id, account_id):
        base = self.account_path(user_id, account_id)
        try:
            pointer = json.loads((base / 'current.json').read_text())
            run_id = str(uuid.UUID(pointer['run_id']))
            result = json.loads((base / run_id / 'status.json').read_text())
            if result.get('state') in ('loading', 'qr', 'scanned'):
                if time.time() - result.get('updated_at', 0) > 180:
                    return {'state': 'error', 'message': 'Phiên đăng nhập đã dừng. Vui lòng tạo mã mới.'}
                if result.get('state') == 'qr' and time.time() >= result.get('expires_at', 0):
                    return {'state': 'expired', 'message': 'Mã QR đã hết hạn.'}
            # Explicit allowlist; a session file or upstream token cannot enter a response.
            return {key: result[key] for key in ('state', 'image', 'expires_at', 'display_name',
                    'message', 'verified_at') if key in result}
        except (OSError, ValueError, KeyError, TypeError):
            return {'state': 'disconnected'}

    def start(self, user_id, account_id):
        with self.lock:
            if not self.available():
                raise RuntimeError('VPS chưa cài bộ kết nối QR. Cần cài Node.js và npm ci trong thư mục connector.')
            # Reap completed children and bound the amount of simultaneous network work.
            self.jobs = {key: process for key, process in self.jobs.items() if process.poll() is None}
            account = (user_id, account_id)
            if account in self.jobs:
                return self.status(*account)
            if len(self.jobs) >= 10:
                raise RuntimeError('Máy chủ đang có nhiều phiên đăng nhập. Vui lòng thử lại sau.')
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            key_path = self.root / 'auth.key'
            if not key_path.exists():
                try:
                    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(os.urandom(32))
                except FileExistsError:
                    pass
            base = self.account_path(*account)
            run_id = str(uuid.uuid4())
            directory = base / run_id
            directory.mkdir(parents=True, mode=0o700)
            initial = {'state': 'loading', 'updated_at': time.time()}
            self.write_json(directory / 'status.json', initial)
            # The child only writes its own run directory, preventing old status races.
            process = subprocess.Popen([shutil.which('node'), str(self.worker), str(directory), str(key_path)],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True,
                                       env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                                            'NODE_ENV': 'production'})
            self.jobs[account] = process
            self.write_json(base / 'current.json', {'run_id': run_id})
            return {'state': 'loading'}

    def disconnect(self, user_id, account_id):
        with self.lock:
            process = self.jobs.pop((user_id, account_id), None)
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            base = self.account_path(user_id, account_id)
            if base.exists():
                shutil.rmtree(base)

    def message_action(self, user_id, account_id, action, **data):
        if not self.available() or self.status(user_id, account_id).get('state') != 'connected':
            return {'state': 'failed'}
        try:
            base = self.account_path(user_id, account_id)
            run_id = str(uuid.UUID(json.loads((base / 'current.json').read_text())['run_id']))
            payload = {'action': action, 'session': str(base / run_id / 'session.enc.json'),
                       'key': str(self.root / 'auth.key'), **data}
            result = subprocess.run([shutil.which('node'), str(self.worker.parent / 'message.mjs')],
                input=json.dumps(payload), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=45, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'NODE_ENV': 'production'})
            output = json.loads(result.stdout)
            return {key: output[key] for key in ('state', 'uid', 'name', 'original_name', 'gender', 'message_id') if key in output}
        except subprocess.TimeoutExpired:
            return {'state': 'unknown' if action in ('send', 'friend', 'alias') else 'failed'}
        except (OSError, ValueError, KeyError, TypeError):
            return {'state': 'unknown' if action in ('send', 'friend', 'alias') else 'failed'}
