"""Bounded import previews and revalidated, unsaved campaign queue rows."""
import csv
import io
import json
import re
from pathlib import Path

from werkzeug.datastructures import FileStorage
from data_import import canonical_header,read_sheet_rows,read_contacts

FIELDS=('name','phone','info1','info2','info3','info4','info5','email','zalo_id')


def column_letter(index):
    result='';index+=1
    while index:index,remainder=divmod(index-1,26);result=chr(65+remainder)+result
    return result


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
    policy=form.get('multi_phone','first')
    if policy not in ('first','skip','all'):raise ValueError('Chọn cách xử lý ô có nhiều số điện thoại.')
    sheets=[];sheet=''
    if mode not in ('text','file'):raise ValueError('Chọn nhập TXT hoặc Excel/CSV.')
    if mode=='file':
        if not upload or not upload.filename:raise ValueError('Chọn tệp dữ liệu.')
        if Path(upload.filename).suffix.lower()=='.txt':
            data=upload.read(2*1024*1024+1)
            if len(data)>2*1024*1024:raise ValueError('Tệp data không vượt quá 2 MB.')
            text=data.decode('utf-8-sig');table=None
        else:
            source=read_sheet_rows(upload,sheet_name=form.get('sheet') or None,details=True)
            table,sheets,sheet=source['rows'],source['sheets'],source['sheet']
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
    inspection=dict(mapping=mapping,skip_header=skip_header,sheets=sheets,sheet=sheet,source_rows=len(table),
        columns=[dict(value=str(i),label=column_letter(i)) for i in range(width)],sample=table[:5])
    if form.get('phase')=='inspect':return inspection
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
    valid={};invalid=[];excluded=[];duplicate_rows=[];duplicates=0;skipped_rows=0;ignored_phones=0;ignored_invalid=0;candidates=0;output_size=0
    for index,row in enumerate(rows):
        values={key:row[int(col)].strip() if col and int(col)<len(row) else '' for key,col in mapping.items()}
        try:
            metadata=clean_row(dict(values,phone='0900000000'),parse_phones)
        except ValueError as error:
            failed=dict(values,row=index+(2 if skip_header else 1),phone=values['phone'][:100],reason=str(error).removeprefix('Dòng 2: '))
            invalid.append(failed);excluded.append(failed)
            continue
        phones=[];bad=0;reason='Cần ít nhất một số điện thoại hợp lệ.'
        for match in re.finditer(r'[^,;\r\n]+',values['phone']):
            raw=match.group().strip()
            if not raw:continue
            candidates+=1
            if candidates>10000:raise ValueError('Mỗi lần kiểm tra tối đa 10.000 giá trị SĐT. Chia dữ liệu thành các tệp nhỏ hơn.')
            if raw.isdigit() and len(raw)==9:raw='0'+raw
            try:
                normalized=parse_phones(raw)
                if len(normalized)!=1:raise ValueError('Cần đúng một số điện thoại trong mỗi giá trị.')
                phones.append(normalized[0])
            except ValueError as error:
                bad+=1;reason=str(error)
        if not phones:
            failed=dict(values,row=index+(2 if skip_header else 1),phone=values['phone'][:100],reason=reason)
            invalid.append(failed);excluded.append(failed);continue
        ignored_invalid+=bad
        if policy=='skip' and len(phones)>1:
            skipped_rows+=1;ignored_phones+=len(phones)
            excluded.append(dict(values,row=index+(2 if skip_header else 1),reason='Bỏ dòng có nhiều SĐT theo lựa chọn.'));continue
        if policy=='first':ignored_phones+=len(phones)-1;phones=phones[:1]
        for phone in phones:
            if phone in valid:
                duplicates+=1;duplicate_rows.append(dict(metadata,phone=phone,row=index+(2 if skip_header else 1),reason='SĐT trùng trong lần upload này.'));continue
            clean=dict(metadata,phone=phone)
            output_size+=len(json.dumps(clean,ensure_ascii=False).encode())
            if output_size>8*1024*1024:raise ValueError('Dữ liệu sau khi tách vượt 8 MB. Chia tệp nhỏ hơn hoặc lấy SĐT đầu tiên.')
            valid[phone]=clean
    return dict(rows=list(valid.values()),invalid=invalid,duplicates=duplicates,mapping=mapping,skip_header=skip_header,
                skipped_rows=skipped_rows,ignored_phones=ignored_phones,ignored_invalid=ignored_invalid,multi_phone=policy,
                columns=inspection['columns'],sample=table[:5],sheets=sheets,sheet=sheet,source_rows=len(rows),
                excluded=excluded,duplicate_rows=duplicate_rows,items_count=len(valid)+len(excluded)+duplicates)


def export_preview(data,category):
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    collections={'valid':data['rows'],'invalid':data['excluded'],'duplicates':data['duplicate_rows']}
    if category not in collections:raise ValueError('Chọn nhóm kết quả cần tải Excel.')
    book=Workbook();sheet=book.active;sheet.title={'valid':'Hợp lệ','invalid':'Lỗi bị loại','duplicates':'Trùng'}[category]
    sheet.append(['STT','Tên','Số điện thoại','Info 1','Info 2','Info 3','Info 4','Info 5','Dòng nguồn','Lý do'])
    for index,row in enumerate(collections[category],1):
        values=[str(index),*[str(row.get(key,'') or '') for key in FIELDS[:7]],str(row.get('row','')),row.get('reason','')]
        sheet.append([ILLEGAL_CHARACTERS_RE.sub('',str(value)) for value in values])
        for cell in sheet[sheet.max_row]:cell.data_type='s'
    sheet.freeze_panes='A2'
    output=io.BytesIO();book.save(output);output.seek(0)
    return output
