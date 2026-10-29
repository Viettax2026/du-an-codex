import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {withAttachmentListener} from './attachment-listener.mjs';
import {executeMessageAction} from './message-action.mjs';
import {actionFailure} from './action-errors.mjs';

const input={action:'send',uid:'123',message:'Hợp đồng',attachment:{filename:'contract.pdf',data:Buffer.from('pdf'),metadata:{totalSize:3}}};
class Listener extends EventEmitter {
  constructor(start) {super();this.startup=start;this.stops=0;}
  start(options) {assert.equal(options.retryOnClose,false);this.startup?.(this);}
  stop() {this.stops++;this.emit('closed',1000);}
}

test('PDF waits for the SDK cipher key before dispatch and stops its socket after both acknowledgements',async()=>{
  const events=[];
  const listener=new Listener(ws=>{ws.emit('connected');events.push('connected');queueMicrotask(()=>{events.push('ready');ws.emit('cipher_key','synthetic-key');});});
  const api={listener,sendMessage:async()=>{events.push('send');return {message:{msgId:1},attachment:[{msgId:2}]};}};
  const result=await withAttachmentListener(api,input,()=>executeMessageAction(api,input));
  assert.deepEqual(result,{state:'sent',message_id:'1,2'});
  assert.deepEqual(events,['connected','ready','send']);
  assert.equal(listener.stops,1);assert.equal(listener.eventNames().length,0);
});

test('listener error or missing cipher key prevents sending either text or file',async()=>{
  for (const start of [ws=>ws.emit('error',new Error('private token')),ws=>ws.emit('connected'),ws=>ws.emit('closed',3000)]) {
    const listener=new Listener(start);let calls=0;
    const api={listener,sendMessage:async()=>{calls++;}};
    const error=await withAttachmentListener(api,input,()=>executeMessageAction(api,input),{timeoutMs:10}).catch(error=>error);
    assert.match(error.code,/^ATTACHMENT_LISTENER_/);
    assert.deepEqual(actionFailure(error,'send','dispatch',false),{state:'failed',error_reason:'attachment_connection',error_code:error.code});
    assert.equal(calls,0);assert.equal(listener.stops,1);
  }
});

test('an immediate close following readiness cannot race a text-only dispatch',async()=>{
  const listener=new Listener(ws=>{ws.emit('cipher_key','key');ws.emit('closed',3000);});let calls=0;
  await assert.rejects(withAttachmentListener({listener},input,()=>{calls++;}),{code:'ATTACHMENT_LISTENER_CLOSED'});
  assert.equal(calls,0);
});

test('disconnect after text acceptance remains uncertain and never retries the send',async()=>{
  const listener=new Listener(ws=>ws.emit('cipher_key','key'));
  let dispatched=false,partial=false,calls=0;
  const api={listener,sendMessage:async()=>{calls++;queueMicrotask(()=>listener.emit('disconnected',1006));return new Promise(()=>{});}};
  const error=await withAttachmentListener(api,input,()=>executeMessageAction(api,input,()=>{dispatched=true;},()=>{partial=true;})).catch(error=>error);
  assert.ok(dispatched && partial);assert.equal(calls,1);
  assert.equal(actionFailure(error,'send','dispatch',dispatched,partial).state,'unknown');
  assert.equal(listener.stops,1);
});

test('plain text, images and non-send operations do not open a listener',async()=>{
  for (const request of [{action:'send'},{action:'send',attachment:{filename:'photo.jpg'}},{action:'friend'}]) {
    assert.equal(await withAttachmentListener({},request,async()=>42),42);
  }
  await assert.rejects(withAttachmentListener({},input,async()=>42),{code:'ATTACHMENT_LISTENER_MISSING'});
});

test('synchronous SDK startup failure is observed and closes its owned listener',async()=>{
  const listener=new Listener(()=>{throw new Error('startup failure');});
  await assert.rejects(withAttachmentListener({listener},input,async()=>42),/startup failure/);
  assert.equal(listener.stops,1);
});
