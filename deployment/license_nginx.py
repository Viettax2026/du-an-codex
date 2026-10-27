"""Preserve certbot/HTTPS configuration while adding one dedicated location."""
import re
from pathlib import Path

INCLUDE = 'include /etc/nginx/snippets/zaloflow-license-location.conf;'


def configure(text):
    names = re.findall(r'\bserver_name\s+([^;]+);', text)
    if not names or any(name.strip() != 'cskh.viettaxco.com' for name in names):
        raise ValueError('Cấu hình chứa tên miền khác; không tự sửa.')
    if 'ssl_certificate' not in text:
        raise ValueError('Tên miền phải có HTTPS trước khi bật quản lý key.')
    if INCLUDE in text:
        return text
    if re.search(r'\blocation[^{};]*\/licenses', text):
        raise ValueError('Đã có cấu hình /licenses khác; cần kiểm tra trước khi cài.')
    return re.sub(r'(\bserver_name\s+cskh\.viettaxco\.com\s*;)', lambda match: match.group(1) + '\n    ' + INCLUDE, text)


if __name__ == '__main__':
    import sys
    path = Path(sys.argv[1]); path.write_text(configure(path.read_text()))
