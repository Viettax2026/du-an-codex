import {joinedGroupIds} from './scan-action.mjs';

export async function executeGroupForward(api,input) {
  const ids=input.group_ids,message=input.message;
  if(!Array.isArray(ids) || !ids.length || ids.length>50 || new Set(ids).size!==ids.length || ids.some(id=>typeof id!=='string' || !/^\d{1,30}$/.test(id)) || typeof message!=='string' || !message.trim() || message.length>2000)throw new Error('Invalid group sharing input');
  const joined=new Set(await joinedGroupIds(api));
  const valid=ids.filter(id=>joined.has(id));
  const outcomes=new Map(ids.filter(id=>!joined.has(id)).map(uid=>[uid,{uid,state:'failed',reason:'group_not_joined'}]));
  if(valid.length){
    let result;
    try {result=await api.forwardMessage({message},valid,1);}
    catch {result=null;}
    const success=Array.isArray(result?.success)?result.success:[],fail=Array.isArray(result?.fail)?result.fail:[];
    const messageIds=success.map(row=>String(row?.msgId ?? '')).filter(id=>/^\d{1,30}$/.test(id));
    const allSent=success.length===valid.length && messageIds.length===valid.length && new Set(messageIds).size===valid.length && !fail.length;
    const allFailed=!success.length && fail.length===valid.length && fail.every(row=>row && typeof row==='object' && row.error_code!==undefined);
    // The SDK's success/fail arrays do not identify destinations. A partial
    // batch cannot safely be attributed to individual groups or retried.
    for(const uid of valid)outcomes.set(uid,{uid,state:allSent?'sent':allFailed?'failed':'unknown',reason:allSent?'batch_accepted':allFailed?'batch_refused':'batch_uncertain',...(allSent?{message_id:messageIds.join(',')}: {})});
  }
  return {state:'ok',rows:ids.map(uid=>outcomes.get(uid))};
}
