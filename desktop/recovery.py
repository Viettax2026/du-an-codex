"""Explicit local Windows administrator support, never a public HTTP action."""
import os
from contextlib import contextmanager
from pathlib import Path

from account_recovery import issue_code
from account_approval import grant_admin
from app import create_app
from runtime_lock import RuntimeLock


def windows_admin():
    if os.name != 'nt':
        return False
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


@contextmanager
def local_account_database(data_root):
    if not windows_admin():
        raise RuntimeError('Chức năng hỗ trợ này yêu cầu PowerShell chạy bằng quyền quản trị viên Windows.')
    root = Path(data_root).resolve()
    instance = root / 'instance'
    database = instance / 'zalo.sqlite3'
    if not database.is_file():
        raise RuntimeError('Không tìm thấy dữ liệu ZaloFlow ở thư mục đã chọn. Không tạo tài khoản mới.')
    with RuntimeLock(root / 'desktop.lock'):
        app = create_app({'DATABASE': str(database)}, instance_path=instance)
        with app.app_context():
            connection = app.extensions['campaign_manager'].db()
            yield connection


def issue_local_support_code(data_root, username):
    with local_account_database(data_root) as connection:
        user = connection.execute('SELECT id FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        if not user:
            raise RuntimeError('Không tìm thấy tài khoản trong dữ liệu Windows đã chọn. Không tạo tài khoản mới.')
        code = issue_code(connection, user['id'], support=True)
        connection.commit()
        return code


def grant_local_admin(data_root, username):
    with local_account_database(data_root) as connection:
        connection.execute('BEGIN IMMEDIATE')
        try:
            grant_admin(connection, username)
            connection.commit()
        except ValueError as error:
            connection.rollback()
            raise RuntimeError(str(error)) from error


def account_admin_dialog(data_root, username):
    if not windows_admin():
        raise RuntimeError('Chức năng hỗ trợ này yêu cầu PowerShell chạy bằng quyền quản trị viên Windows.')
    import ctypes
    message = (f'Duyệt và cấp quyền quản trị ZaloFlow cho tài khoản {username}?\n\n'
               f'Dữ liệu: {Path(data_root).resolve()}\n\n'
               'Tài khoản này sẽ duyệt hoặc khóa các tài khoản khác trên bản Windows này. '
               'Chỉ tiếp tục khi đây là chủ ứng dụng đáng tin cậy. Đóng tool trước khi thực hiện.')
    if ctypes.windll.user32.MessageBoxW(None, message, 'ZaloFlow · Cấp quyền quản trị', 0x24) != 6:
        return
    grant_local_admin(data_root, username)
    ctypes.windll.user32.MessageBoxW(None,
        'Đã duyệt và cấp quyền quản trị. Mật khẩu, dữ liệu và key được giữ nguyên. '
        'Mở ZaloFlow bình thường, đăng nhập lại rồi vào Quản lý tài khoản.', 'ZaloFlow', 0x40)


def recovery_dialog(data_root, username):
    if not windows_admin():
        raise RuntimeError('Chức năng hỗ trợ này yêu cầu PowerShell chạy bằng quyền quản trị viên Windows.')
    import ctypes
    message = (f'Tạo mã hỗ trợ đặt lại mật khẩu cho tài khoản {username}?\n\n'
               f'Dữ liệu: {Path(data_root).resolve()}\n\n'
               'Chỉ tiếp tục khi bạn đã xác minh chủ tài khoản. Đóng tool trước. '
               'Mã có hiệu lực 15 phút và dùng một lần. Dữ liệu chiến dịch được giữ nguyên.')
    if ctypes.windll.user32.MessageBoxW(None, message, 'ZaloFlow · Hỗ trợ khôi phục', 0x24) != 6:
        return
    code = issue_local_support_code(data_root, username)
    ctypes.windll.user32.MessageBoxW(None,
        f'Tài khoản: {username}\n\nMã khôi phục:\n{code}\n\n'
        'Mã dùng một lần, hết hạn sau 15 phút. Nhấn Ctrl+C để sao chép nội dung hộp thoại.\n'
        'Mở lại ZaloFlow → Quên mật khẩu? để đặt mật khẩu mới. Chỉ gửi mã riêng cho chủ tài khoản.',
        'ZaloFlow · Mã hỗ trợ', 0x40)
