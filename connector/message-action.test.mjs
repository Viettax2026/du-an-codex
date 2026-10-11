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
