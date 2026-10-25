// Return only fixed categories and short codes; never expose upstream messages,
// cookies, tokens, URLs or credential file paths to the UI/history.
export function lookupFailure(error, stage='lookup') {
  const rawCode=String(error?.code ?? error?.cause?.code ?? '');
  const lookup_code=/^(?:-?\d{1,8}|[A-Z][A-Z0-9_]{0,31})$/.test(rawCode)?rawCode:'';
  const text=String(error?.message || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d').toLowerCase();
  if(stage==='lookup' && rawCode==='210')return {state:'lookup_failed',lookup_reason:'recipient_blocked',lookup_code:'210'};
  if(stage==='lookup' && !['401','403','429'].includes(rawCode) && (rawCode==='216' || /(?:user|profile) (?:is )?not found|could not find (?:user|profile)|khong tim thay (?:nguoi dung|tai khoan)|(?:so dien thoai|tai khoan).*chua dang ky/.test(text))) return {state:'not_found'};
  let lookup_reason='unavailable';
  if(rawCode==='429' || /too many requests|rate.?limit|gioi han.*(?:tra cuu|tim kiem)|vuot.*gioi han.*tim/.test(text)) lookup_reason='rate_limited';
  else if(/^(?:E(?:CONNRESET|CONNREFUSED|TIMEDOUT|NOTFOUND|HOSTUNREACH|PIPE)|UND_ERR_[A-Z_]+)$/.test(rawCode) || /fetch failed|network|timed? ?out|socket|connection/.test(text)) lookup_reason='network';
  else if(stage==='session' || stage==='input' || ['401','403'].includes(rawCode) || /session.*(?:expired|invalid)|invalid.*session|not logged in|login required|phien dang nhap|dang nhap lai/.test(text)) lookup_reason='session';
  else if(/invalid (?:profile|recipient)|failed to parse response|invalid json/.test(text)) lookup_reason='invalid_response';
  return {state:'lookup_failed',lookup_reason,...(lookup_code?{lookup_code}:{})};
}
