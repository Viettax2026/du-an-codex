"""Bounded, validated contact imports shared by campaigns and data groups."""
import csv
import io
from pathlib import Path
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError


def read_contacts(upload, parse_phones):
    if not upload or not upload.filename:
        return {}
    data = upload.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Tệp data không vượt quá 2 MB.')
    suffix = Path(upload.filename).suffix.lower()
    try:
        if suffix == '.txt':
            return {phone: {'phone': phone} for phone in parse_phones(data.decode('utf-8-sig'))}
        if suffix == '.csv':
            reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
            if not reader.fieldnames or 'phone' not in reader.fieldnames:
                raise ValueError('Tệp cần cột phone; tùy chọn name, zalo_id, email, info1…info5.')
            rows = reader
        elif suffix == '.xlsx':
            from openpyxl import load_workbook
            from zipfile import ZipFile
            with ZipFile(io.BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                    raise ValueError('Tệp Excel giải nén quá lớn.')
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
            try:
                sheet = book.active.iter_rows(values_only=True)
                headers = [str(cell or '').strip() for cell in next(sheet)]
                if 'phone' not in headers:
                    raise ValueError('Excel cần hàng đầu có cột phone.')
                rows = []
                for index, row in enumerate(sheet):
                    if index >= 500:
                        raise ValueError('Tệp tối đa 500 dòng.')
                    rows.append(dict(zip(headers, row)))
            finally:
                book.close()
        else:
            raise ValueError('Chọn tệp TXT, CSV UTF-8 hoặc Excel .xlsx.')
        result = {}
        for index, row in enumerate(rows):
            if index >= 500:
                raise ValueError('Tệp tối đa 500 dòng.')
            raw = str(row.get('phone') or '').strip()
            # Spreadsheet numeric cells drop the initial zero of Vietnamese numbers.
            if raw.isdigit() and len(raw) == 9:
                raw = '0' + raw
            phones = parse_phones(raw)
            if len(phones) != 1:
                raise ValueError(f'Dòng {index + 2}: cần đúng một số điện thoại.')
            phone = phones[0]
            clean = {key: str(row.get(key) or '').strip() for key in ('name', 'zalo_id', 'email', 'info1', 'info2', 'info3', 'info4', 'info5')}
            if len(clean['name']) > 100 or len(clean['zalo_id']) > 100 or len(clean['email']) > 254 or any(len(clean[key]) > 500 for key in ('info1','info2','info3','info4','info5')):
                raise ValueError(f'Dòng {index + 2}: thông tin vượt độ dài cho phép.')
            result[phone] = dict(clean, phone=phone)
        return result
    except (UnicodeError, csv.Error, BadZipFile, StopIteration, KeyError, TypeError, ParseError, OSError) as error:
        raise ValueError('Tệp không hợp lệ. Dùng TXT/CSV UTF-8 hoặc Excel .xlsx có cột phone.') from error


def insert_contact(connection, user_id, phone, row, tag='Khách hàng', consent=1):
    connection.execute('''INSERT INTO contacts(user_id,name,phone,tag,consent,zalo_id,email,info1,info2,info3,info4,info5)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,phone) DO NOTHING''',
        (user_id, row.get('name') or 'Khách hàng ' + phone, phone, tag, consent,
         *[row.get(key, '') for key in ('zalo_id','email','info1','info2','info3','info4','info5')]))
