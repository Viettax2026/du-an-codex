"""Bounded import previews and revalidated, unsaved campaign queue rows."""
import csv
import io
import json
import re
from pathlib import Path

from werkzeug.datastructures import FileStorage
from data_import import canonical_header,read_sheet_rows,read_contacts

FIELDS=('name','phone','info1','info2','info3','info4','info5','email','zalo_id')


def clean_row(row,parse_phones):
    if not isinstance(row,dict):raise ValueError('Dòng data không hợp lệ.')
    if any(key in row and not isinstance(row[key],str) for key in FIELDS):raise ValueError('Thông tin khách hàng phải là văn bản.')
    stream=io.StringIO();writer=csv.writer(stream);writer.writerow(FIELDS);writer.writerow([row.get(key,'') for key in FIELDS])
    result=read_contacts(FileStorage(stream=io.BytesIO(stream.getvalue().encode()),filename='data.csv'),parse_phones)
    return next(iter(result.values()))


def staged_rows(raw,parse_phones):
    if not raw:return {}
    if len(raw.encode())>8*1024*1024:raise ValueError('Danh sách chờ tối đa 8 MB.')
    try:rows=json.loads(raw)
    except (TypeError,ValueError) as error:raise ValueError('Danh sách chờ không hợp lệ. Kiểm tra và nhập lại.') from error
    if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Danh sách chiến dịch tối đa 10.000 khách hàng.')
    result={}
    for row in rows:
        clean=clean_row(row,parse_phones);result[clean['phone']]=clean
    return result


def preview(form,upload,parse_phones):
    mode=form.get('mode','text')
    if mode not in ('text','file'):raise ValueError('Chọn nhập TXT hoặc Excel/CSV.')
    if mode=='file':
        if not upload or not upload.filename:raise ValueError('Chọn tệp dữ liệu.')
        if Path(upload.filename).suffix.lower()=='.txt':
            data=upload.read(2*1024*1024+1)
            if len(data)>2*1024*1024:raise ValueError('Tệp data không vượt quá 2 MB.')
            text=data.decode('utf-8-sig');table=None
        else:table=read_sheet_rows(upload)
    else:
        text=form.get('text','');table=None
    if table is None:
        if len(text.encode())>2*1024*1024:raise ValueError('Dữ liệu không vượt quá 2 MB.')
        if '\t' in text:
            table=[]
            for row in csv.reader(io.StringIO(text),delimiter='\t'):
                if not any(cell.strip() for cell in row):continue
                if len(row)>100 or len(table)>=501:raise ValueError('Tối đa 500 dòng data và 100 cột.')
                table.append(row)
        else:
            table=[]
            for match in re.finditer(r'[^\r\n,;]+',text):
                part=match.group().strip()
                if part:table.append([part])
                if len(table)>501:raise ValueError('Tối đa 500 dòng data và một dòng tiêu đề.')
    if not table:raise ValueError('Nhập số điện thoại hoặc chọn tệp dữ liệu.')
    if len(table)>501 or max(map(len,table))>100:raise ValueError('Tối đa 500 dòng data và 100 cột.')
    width=max(map(len,table));headers=[canonical_header(cell) for cell in table[0]]
    mapping={key:str(headers.index(key)) if key in headers else '' for key in FIELDS}
    if not mapping['phone']:mapping['phone']='0'
    skip_header='phone' in headers
    if 'mapping' in form:
        try:chosen=json.loads(form['mapping'])
        except ValueError as error:raise ValueError('Cột dữ liệu không hợp lệ.') from error
        if not isinstance(chosen,dict):raise ValueError('Cột dữ liệu không hợp lệ.')
        mapping={key:chosen.get(key,'') for key in FIELDS}
        skip_header=form.get('skip_header')=='yes'
    used=[]
    for value in mapping.values():
        if not isinstance(value,str) or value and (not value.isdigit() or int(value)>=width):raise ValueError('Cột được chọn không có trong dữ liệu.')
        if value:used.append(value)
    if not mapping['phone']:raise ValueError('Cần chọn cột Số điện thoại.')
    if len(set(used))!=len(used):raise ValueError('Mỗi trường cần chọn một cột khác nhau.')
    rows=table[1:] if skip_header else table
    if not rows or len(rows)>500:raise ValueError('Cần từ 1 đến 500 dòng data sau khi bỏ tiêu đề.')
    valid={};invalid=[];duplicates=0
    for index,row in enumerate(rows):
        values={key:row[int(col)].strip() if col and int(col)<len(row) else '' for key,col in mapping.items()}
        try:
            clean=clean_row(values,parse_phones)
            duplicates+=int(clean['phone'] in valid);valid.setdefault(clean['phone'],clean)
        except ValueError as error:
            invalid.append(dict(row=index+(2 if skip_header else 1),phone=values['phone'][:100],reason=str(error).removeprefix('Dòng 2: ')))
    return dict(rows=list(valid.values()),invalid=invalid,duplicates=duplicates,mapping=mapping,skip_header=skip_header,
                columns=[dict(value=str(i),label=f'Cột {i+1}: '+str(table[0][i] if i<len(table[0]) else '')[:80]) for i in range(width)],sample=table[:5])
