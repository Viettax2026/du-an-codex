import test from 'node:test';
import assert from 'node:assert/strict';
import {actionFailure} from './action-errors.mjs';
import {lookupFailure} from './lookup-errors.mjs';
import {executeMessageAction} from './message-action.mjs';

test('lookup code 210 is a blocked recipient only during profile lookup',async()=>{
 const error=Object.assign(new Error('private token cookie'),{code:210});
 const expected={state:'lookup_failed',lookup_reason:'recipient_blocked',lookup_code:'210'};
 assert.deepEqual(lookupFailure(error),expected);
 assert.deepEqual(await executeMessageAction({findUser:async()=>{throw error;}},{action:'resolve',phone:'0901234567'}),expected);
 assert.equal(lookupFailure(error,'session').lookup_reason,'session');
});

test('explicit refusal of stranger messages is a failed action with a fixed public reason',()=>{
 for(const text of ['Người nhận chặn tin nhắn từ người lạ','Người này không nhận tin nhắn từ người lạ','Recipient does not accept messages from strangers']) {
  assert.deepEqual(actionFailure(new Error(text+' cookie=PRIVATE'),'send'),{state:'failed',error_reason:'stranger_messages_blocked'});
 }
 assert.equal(actionFailure(new Error('Người nhận chặn tin nhắn từ người lạ'),'friend').state,'unknown');
 assert.equal(actionFailure(Object.assign(new Error('Người nhận chặn tin nhắn từ người lạ'),{code:401}),'send').error_reason,'session');
});

test('network/unknown exceptions stay uncertain and raw diagnostics are never exposed',()=>{
 const result=actionFailure(Object.assign(new Error('fetch failed PRIVATE'),{code:'ECONNRESET'}),'send');
 assert.deepEqual(result,{state:'unknown',error_reason:'network',error_code:'ECONNRESET'});
 assert.deepEqual(actionFailure(Object.assign(new Error('PRIVATE cookie session/path'),{code:'https://PRIVATE'}),'send'),{state:'unknown',error_reason:'unavailable'});
});

test('a refusal after image acceptance remains partial and uncertain',async()=>{
 let dispatched=false,partial=false,calls=0;
 const error=new Error('Người nhận chặn tin nhắn từ người lạ');
 const api={sendMessage:async()=>{if(++calls===1)return {attachment:[{msgId:123}]};throw error;}};
 const input={action:'send',uid:'123',message:'Hi',styles:[{start:0,len:2,st:'b'}],attachment:{data:Buffer.from('a'),filename:'a.jpg',metadata:{totalSize:1,width:1,height:1}}};
 await assert.rejects(executeMessageAction(api,input,()=>{dispatched=true;},()=>{partial=true;}));
 assert.ok(dispatched && partial);
 assert.equal(actionFailure(error,'send','dispatch',dispatched,partial).state,'unknown');
 assert.equal(calls,2);
});
