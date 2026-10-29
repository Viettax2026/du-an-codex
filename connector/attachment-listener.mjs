function connectionError(code) {
  return Object.assign(new Error('Attachment confirmation connection unavailable'), {code});
}

/** zca-js 2.2.0 completes PDF/video uploads through a WebSocket file_done event.
 * Keep one short-lived listener for this worker, ready before any text/file
 * dispatch. Never fetch conversation history or reconnect/retry a send here.
 */
export async function withAttachmentListener(api, input, operation, {timeoutMs=8000}={}) {
  if (input.action !== 'send' || !/\.(pdf|mp4)$/i.test(input.attachment?.filename || '')) return operation();
  const listener=api.listener;
  if (!listener || !['on','off','start','stop'].every(key=>typeof listener[key]==='function')) {
    throw connectionError('ATTACHMENT_LISTENER_MISSING');
  }
  let active=true, lost=false, timer, readyResolve, readyReject, interrupt;
  const ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;});
  ready.catch(()=>{});
  const disconnected=new Promise((resolve,reject)=>{interrupt=reject;});
  // A disconnect can follow the cipher-key event in the same event-loop turn.
  // Install a rejection observer before awaiting readiness.
  disconnected.catch(()=>{});
  const fail=()=>{
    if (!active) return;
    lost=true;
    const error=connectionError('ATTACHMENT_LISTENER_CLOSED');
    readyReject(error);interrupt(error);
  };
  const onReady=()=>{clearTimeout(timer);readyResolve();};
  const cleanup=()=>{
    listener.off('cipher_key',onReady);
    listener.off('error',fail);
    listener.off('disconnected',fail);
    listener.off('closed',onClosed);
  };
  const onClosed=()=>{fail();if (!active) cleanup();};
  listener.on('cipher_key',onReady);
  listener.on('error',fail);
  listener.on('disconnected',fail);
  listener.on('closed',onClosed);
  try {
    timer=setTimeout(()=>readyReject(connectionError('ATTACHMENT_LISTENER_TIMEOUT')),timeoutMs);
    listener.start({retryOnClose:false});
    await ready;
    return await Promise.race([Promise.resolve().then(()=>{
      if (lost) throw connectionError('ATTACHMENT_LISTENER_CLOSED');
      return operation();
    }),disconnected]);
  } finally {
    active=false;
    clearTimeout(timer);
    listener.off('cipher_key',onReady);
    // Keep the no-op error handler until the socket actually closes. The SDK
    // emits EventEmitter 'error' while an asynchronous socket close is pending.
    try {listener.stop();} catch {cleanup();}
  }
}
