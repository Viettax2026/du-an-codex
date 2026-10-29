"""Fixed, public descriptions: upstream exception messages never enter history."""
import re

ERROR_LABELS={
    'stranger_messages_blocked':'Người nhận chặn tin nhắn từ người lạ',
    'recipient_blocked':'Người nhận bị Zalo chặn',
    'network':'Kết nối Zalo bị gián đoạn hoặc hết thời gian chờ',
    'rate_limited':'Zalo đang giới hạn thao tác',
    'session':'Phiên Zalo chưa đăng nhập hoặc đã hết hạn',
    'invalid_response':'Chưa nhận được phản hồi xác nhận hợp lệ từ Zalo',
    'attachment_connection':'Kênh xác nhận tải tệp Zalo chưa kết nối hoặc đã bị gián đoạn',
    'unavailable':'Không thực hiện được thao tác Zalo',
}


def diagnostics(data):
    if not isinstance(data,dict):return {}
    result={}
    if data.get('error_reason') in ERROR_LABELS:result['error_reason']=data['error_reason']
    code=str(data.get('error_code',''))
    if re.fullmatch(r'-?\d{1,8}|[A-Z][A-Z0-9_]{0,31}',code):result['error_code']=code
    return result


def error_description(data):
    public=diagnostics(data)
    label=ERROR_LABELS.get(public.get('error_reason'),'')
    return label+(' (mã '+public['error_code']+')' if label and public.get('error_code') else '')
