import test from 'node:test';
import assert from 'node:assert/strict';
import { lookupFailure } from './lookup-errors.mjs';

test('lookup failures reveal only fixed categories/codes and preserve their phase',()=>{
  assert.deepEqual(lookupFailure(Object.assign(new Error('User not found: secret payload'),{code:221})),{state:'not_found'});
  assert.deepEqual(lookupFailure(new Error('Không tìm thấy người dùng')),{state:'not_found'});
  assert.deepEqual(lookupFailure(Object.assign(new Error('token=private'),{code:429})),{state:'lookup_failed',lookup_reason:'rate_limited',lookup_code:'429'});
  assert.deepEqual(lookupFailure(new Error('fetch failed'), 'session'),{state:'lookup_failed',lookup_reason:'network'});
  assert.deepEqual(lookupFailure(new Error('private cookie'),'session'),{state:'lookup_failed',lookup_reason:'session'});
  assert.deepEqual(lookupFailure(new Error('User not found'),'session'),{state:'lookup_failed',lookup_reason:'session'});
  const failure=lookupFailure(Object.assign(new Error('private URL and cookie'),{code:'private/path/token'}));
  assert.deepEqual(failure,{state:'lookup_failed',lookup_reason:'unavailable'});
});
