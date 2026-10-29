// Public diagnostics contain fixed categories and short codes only.
export function actionFailure(error,action,stage='dispatch',dispatched=true,partial=false) {
  const rawCode=String(error?.code ?? error?.cause?.code ?? '');
  const error_code=/^(?:-?\d{1,8}|[A-Z][A-Z0-9_]{0,31})$/.test(rawCode)?rawCode:'';
  const text=String(error?.message || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d').toLowerCase();
  let error_reason='unavailable';
  const strangerBlocked=stage==='dispatch' && action==='send' && !['401','403','429'].includes(rawCode) &&
    /nguoi nhan chan tin nhan tu nguoi la|(?:khong nhan|tu choi nhan|chan) tin nhan tu nguoi la|(?:does not|doesn't|cannot) (?:accept|receive) messages? from strangers|(?:recipient|user) blocks? messages? from strangers/.test(text);
  if(rawCode.startsWith('ATTACHMENT_LISTENER_'))error_reason='attachment_connection';
  else if(strangerBlocked)error_reason='stranger_messages_blocked';
  else if(rawCode==='429' || /too many requests|rate.?limit/.test(text))error_reason='rate_limited';
  else if(/^(?:E(?:CONNRESET|CONNREFUSED|TIMEDOUT|NOTFOUND|HOSTUNREACH|PIPE)|UND_ERR_[A-Z_]+)$/.test(rawCode) || /fetch failed|network|timed? ?out|socket|connection/.test(text))error_reason='network';
  else if(stage==='session' || ['401','403'].includes(rawCode) || /session.*(?:expired|invalid)|not logged in|login required/.test(text))error_reason='session';
  return {state:!dispatched || strangerBlocked && !partial?'failed':'unknown',error_reason,...(error_code?{error_code}:{})};
}
