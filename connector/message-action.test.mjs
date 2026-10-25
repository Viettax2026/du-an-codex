import test from 'node:test';
import assert from 'node:assert/strict';
import { executeMessageAction } from './message-action.mjs';
import { decryptCredentials } from './state.mjs';

test('friend invitation succeeds only after upstream response; does not send a message', async () => {
  let count = 0;
  const api = {sendFriendRequest: async (message, uid) => {
    count++; assert.equal(uid, '123'); assert.equal(message, 'Xin chào'); return '';
  }, sendMessage: async () => {throw new Error('Must not send');}};
  assert.deepEqual(await executeMessageAction(api, {action:'friend',uid:'123',message:'Xin chào'}), {state:'friend_requested'});
  assert.equal(count, 1);
  await assert.rejects(executeMessageAction(api, {action:'friend',uid:'123',message:'x'.repeat(151)}));
  assert.equal(count, 1);
  assert.deepEqual(await executeMessageAction({sendFriendRequest: async () => undefined}, {action:'friend',uid:'123',message:'Hello'}), {state:'unknown'});
});

test('phone lookup returns only recipient identity and normalizes Vietnamese numbers', async () => {
  const result = await executeMessageAction({findUser: async phone => {
    assert.equal(phone, '84901234567');
    return {uid: '123456', display_name: 'Lan', token: 'private'};
  }}, {action: 'resolve', phone: '090 123 4567'});
  assert.deepEqual(result, {state: 'resolved', uid: '123456', name: 'Lan', original_name: '', gender: null});
  await assert.rejects(executeMessageAction({}, {action: 'resolve', phone: 'bad'}));
});
test('empty profiles and explicit missing-user responses are skippable; connection/session failures are not', async()=>{
  const input={action:'resolve',phone:'0901234567'};
  let dispatches=0;
  for (const user of [null,undefined,{}, {uid:null},{uid:''},{uid:0}]) {
    assert.deepEqual(await executeMessageAction({findUser:async()=>user},input,()=>dispatches++),{state:'not_found'});
  }
  for (const code of [216,'216']) {
    assert.deepEqual(await executeMessageAction({findUser:async()=>{throw Object.assign(new Error('not found'),{code});}},input),{state:'not_found'});
  }
  for (const code of [401,429,500,undefined]) {
    await assert.rejects(executeMessageAction({findUser:async()=>{throw Object.assign(new Error('lookup unavailable'),{code});}},input));
  }
  for (const user of ['unexpected',[],{uid:'invalid-id'}]) {
    await assert.rejects(executeMessageAction({findUser:async()=>user},input));
  }
  assert.equal(dispatches,0);
});
test('send is successful only with upstream message ID and never retries an uncertain dispatch', async () => {
  let count = 0, dispatched = false;
  const input = {action: 'send', uid: '123456', message: 'Xin chào Lan'};
  const result = await executeMessageAction({sendMessage: async (message, uid, type) => {
    count++; assert.equal(message, input.message); assert.equal(uid, input.uid); assert.equal(type, 0);
    return {message: {msgId: 999}};
  }}, input, () => {dispatched = true;});
  assert.deepEqual(result, {state: 'sent', message_id: '999'});
  assert.equal(count, 1); assert.ok(dispatched);
  assert.deepEqual(await executeMessageAction({sendMessage: async () => ({message: null})}, input), {state: 'unknown'});
  count = 0;
  await assert.rejects(executeMessageAction({sendMessage: async () => {count++; throw new Error('network');}}, input));
  assert.equal(count, 1);
});
test('tampered encrypted credentials cannot be restored', () => {
  assert.throws(() => decryptCredentials({version: 2}, Buffer.alloc(32)));
  assert.throws(() => decryptCredentials({version: 1, iv: Buffer.alloc(12).toString('base64'), tag: Buffer.alloc(16).toString('base64'), ciphertext: 'AA=='}, Buffer.alloc(32)));
});

test('alias uses the nickname API and requires upstream acknowledgement', async () => {
  const calls = [];
  const api = {changeFriendAlias: async (...args) => {calls.push(args); return '';}};
  assert.deepEqual(await executeMessageAction(api,{action:'alias',uid:'123',message:'Lan - 0901234567'}),{state:'renamed'});
  assert.deepEqual(calls,[['Lan - 0901234567','123']]);
  api.changeFriendAlias = async () => ({unexpected:true});
  assert.deepEqual(await executeMessageAction(api,{action:'alias',uid:'123',message:'Lan'}),{state:'unknown'});
  await assert.rejects(executeMessageAction(api,{action:'alias',uid:'123',message:'x'.repeat(101)}));
});

test('media uses attachment buffer and requires attachment acknowledgement', async () => {
  const attachment = {data: Buffer.from('pdf'), filename: 'test.pdf', metadata: {totalSize: 3}};
  const input = {action: 'send', uid: '123', message: 'Nội dung', attachment};
  let calls = 0;
  const api = {sendMessage: async (content, uid, type) => {
    calls++; assert.equal(content.msg, 'Nội dung'); assert.equal(content.attachments[0], attachment);
    assert.equal(uid, '123'); assert.equal(type, 0);
    return {message: {msgId: 1}, attachment: [{msgId: 2}]};
  }};
  assert.deepEqual(await executeMessageAction(api, input), {state: 'sent', message_id: '1,2'});
  assert.equal(calls, 1);
  api.sendMessage = async () => ({message: {msgId: 1}, attachment: []});
  assert.deepEqual(await executeMessageAction(api, input), {state: 'unknown'});
  let dispatched = false;
  await assert.rejects(executeMessageAction(api, {...input, attachment: {...attachment, filename: 'bad.exe'}}, () => {dispatched = true;}));
  await assert.rejects(executeMessageAction(api, {...input, attachment: {...attachment, filename: 'bad.png'}}, () => {dispatched = true;}));
  assert.equal(dispatched, false);
});

test('rich message and attachment preserve UTF-16 styles; malformed styles never dispatch', async () => {
  const styles = [{start:3,len:8,st:'b'}, {start:3,len:4,st:'i'}];
  const attachment = {data:Buffer.from('pdf'),filename:'quote.pdf',metadata:{totalSize:3}};
  const input = {action:'send',uid:'123',message:'😊 Chào Lan',styles};
  let calls=0, dispatches=0;
  const api={sendMessage:async(content,uid,type)=>{
    calls++;assert.deepEqual(content.styles,styles);assert.equal(content.msg,input.message);assert.equal(uid,'123');assert.equal(type,0);
    if (content.attachments) assert.equal(content.attachments[0],attachment);
    return {message:{msgId:5},attachment:[{msgId:6}]};
  }};
  assert.deepEqual(await executeMessageAction(api,input,()=>dispatches++),{state:'sent',message_id:'5'});
  assert.deepEqual(await executeMessageAction(api,{...input,attachment},()=>dispatches++),{state:'sent',message_id:'5,6'});
  for(const invalid of [[{start:1,len:1,st:'b'}],[{start:3,len:100,st:'b'}],[{start:3,len:2,st:'css'}],[{start:3,len:2,st:'b',onclick:'bad'}],{},[{start:3,len:2,st:'ind_$',indentSize:100}]]) {
    await assert.rejects(executeMessageAction(api,{...input,styles:invalid},()=>dispatches++));
  }
  await assert.rejects(executeMessageAction(api,{...input,action:'friend'},()=>dispatches++));
  assert.equal(calls,2);assert.equal(dispatches,2);
});

for (const filename of ['quote.jpg','quote.PNG','quote.webp']) {
  test(`styled ${filename} sends image first and rich text second, with both acknowledgements`, async () => {
    const attachment={data:Buffer.from('image'),filename,metadata:{totalSize:5,width:2,height:2}};
    const styles=[{start:3,len:8,st:'b'}];
    const calls=[];let claims=0;
    const api={sendMessage:async(...args)=>{
      calls.push(args);
      return calls.length===1 ? {message:null,attachment:[{msgId:10}]} : {message:{msgId:11},attachment:[]};
    }};
    const result=await executeMessageAction(api,{action:'send',uid:'123',message:'😊 Chào Lan',styles,attachment},()=>claims++);
    assert.deepEqual(calls,[[{msg:'',attachments:[attachment]},'123',0],[{msg:'😊 Chào Lan',styles},'123',0]]);
    assert.deepEqual(result,{state:'sent',message_id:'10,11'});
    assert.equal(claims,1);
  });
}

test('styled image partial acceptance never retries or claims success for a missing part', async () => {
  const attachment={data:Buffer.from('image'),filename:'quote.jpg',metadata:{totalSize:5,width:2,height:2}};
  const input={action:'send',uid:'123',message:'Chào Lan',styles:[{start:0,len:8,st:'b'}],attachment};
  for (const response of [undefined,{}, {attachment:[]}, {attachment:[{}]}, {message:{msgId:1},attachment:[]}]) {
    let calls=0;
    assert.deepEqual(await executeMessageAction({sendMessage:async()=>{calls++;return response;}},input),{state:'unknown'});
    assert.equal(calls,1); // No text dispatch without an image acknowledgement.
  }
  let calls=0;
  assert.deepEqual(await executeMessageAction({sendMessage:async()=>++calls===1?{attachment:[{msgId:1}]}:{attachment:[]}},input),{state:'unknown'});
  assert.equal(calls,2);
  calls=0;
  await assert.rejects(executeMessageAction({sendMessage:async()=>{
    if (++calls===1) return {attachment:[{msgId:1}]};
    throw new Error('uncertain text acceptance');
  }},input));
  assert.equal(calls,2);
});

test('plain image keeps its single caption and non-image attachments require text acknowledgement', async () => {
  const attachment={data:Buffer.from('image'),filename:'quote.jpg',metadata:{totalSize:5,width:2,height:2}};
  let calls=0;
  const api={sendMessage:async content=>{
    calls++;assert.equal(content.msg,'Chào Lan');assert.deepEqual(content.attachments,[attachment]);
    return {message:null,attachment:[{msgId:10}]};
  }};
  assert.deepEqual(await executeMessageAction(api,{action:'send',uid:'123',message:'Chào Lan',attachment}),{state:'sent',message_id:'10'});
  assert.equal(calls,1);
  assert.deepEqual(await executeMessageAction({sendMessage:async()=>({attachment:[{msgId:10}]})},
    {action:'send',uid:'123',message:'Chào Lan',attachment:{...attachment,filename:'quote.pdf'}}),{state:'unknown'});
});
