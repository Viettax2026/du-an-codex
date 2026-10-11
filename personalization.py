import re
from datetime import datetime
from zoneinfo import ZoneInfo

TOKEN = re.compile(r'\{\{name\}\}|#\{(SEX\{([^{}]*)\}|TODAY\(([^()]*)\)|[A-Z][A-Z0-9_]*)\}')
DATE_FORMATS = {'DD/MM/YYYY': '%d/%m/%Y', 'DD-MM-YYYY': '%d-%m-%Y', 'YYYY-MM-DD': '%Y-%m-%d'}


def personalize(template, contact, zalo=None, strict=True, now=None):
    contact, zalo = dict(contact), dict(zalo or {})
    now = (now or datetime.now(ZoneInfo('Asia/Bangkok'))).astimezone(ZoneInfo('Asia/Bangkok'))
    values = {'INPUT_FULLNAME': contact.get('name'), 'PHONE': contact.get('phone'),
              'FULL_NAME': zalo.get('name'), 'ORIGINAL_NAME': zalo.get('original_name'),
              'EMAIL': contact.get('email'), **{f'INFO{i}': contact.get(f'info{i}') for i in range(1, 6)}}
    if '#{' in TOKEN.sub('', template):
        if strict:
            raise ValueError('Cú pháp cá nhân hóa không hợp lệ.')
    def missing(label):
        if strict:
            raise ValueError(f'Thiếu thông tin {label}. Bổ sung dữ liệu hoặc bỏ biến này trước khi gửi.')
        return f'[Thiếu {label}]'
    def replace(match):
        if match.group(0) == '{{name}}':
            return str(contact.get('name') or missing('INPUT_FULLNAME'))
        if match.group(2) is not None:
            choices = match.group(2).split('-')
            if len(choices) != 3:
                raise ValueError('Giới tính cần ba cách xưng hô: nam-nữ-không rõ.')
            gender = zalo.get('gender')
            return choices[gender if type(gender) is int and gender in (0, 1) else 2]
        if match.group(3) is not None:
            fmt = DATE_FORMATS.get(match.group(3))
            if not fmt:
                raise ValueError('Định dạng ngày cá nhân hóa không được hỗ trợ.')
            return now.strftime(fmt)
        value = values.get(match.group(1))
        return str(value) if value not in (None, '') else missing(match.group(1))
    return TOKEN.sub(replace, template)
