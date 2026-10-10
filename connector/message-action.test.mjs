import test from 'node:test';
import assert from 'node:assert/strict';
import { executeMessageAction } from './message-action.mjs';
import { decryptCredentials } from './state.mjs';

test('phone lookup returns only recipient identity and normalizes Vietnamese numbers', async () => {
  const result = await executeMessageAction({findUser: async phone => {
    assert.equal(phone, '84901234567');
    return {uid: '123456', display_name: 'Lan', token: 'private'};
  }}, {action: 'resolve', phone: '090 123 4567'});
  assert.deepEqual(result, {state: 'resolved', uid: '123456', name: 'Lan'});
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
