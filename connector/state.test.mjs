import test from 'node:test';
import assert from 'node:assert/strict';
import { createDecipheriv, randomBytes } from 'node:crypto';
import { mkdtempSync, readFileSync, statSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { publicEvent, saveCredentials } from './state.mjs';

test('QR event publishes image and deadline but never upstream code or token', () => {
  const result = publicEvent(0, { image: 'data:image/png;base64,aGVsbG8=', code: 'private-code', token: 'private-token' });
  assert.equal(result.state, 'qr');
  assert.equal(result.image, 'aGVsbG8=');
  assert.ok(result.expires_at > Date.now()/1000);
  assert.ok(!JSON.stringify(result).includes('private-'));
  assert.throws(() => publicEvent(0, { image: '<script>' }));
});

test('scan waits for confirmation and expiry removes QR', () => {
  const qr = publicEvent(0, { image: 'aGVsbG8=' });
  const scanned = publicEvent(2, { display_name: 'An' }, qr);
  assert.equal(scanned.state, 'scanned');
  assert.equal(scanned.display_name, 'An');
  const expired = publicEvent(1, null, scanned);
  assert.equal(expired.state, 'expired');
  assert.equal(expired.image, undefined);
});

test('credentials are encrypted with AES-GCM and written with private permissions', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'zaloflow-crypto-'));
  try {
    const key = randomBytes(32);
    const credentials = { cookie: [{ value: 'sensitive-cookie-value' }], imei: 'device' };
    saveCredentials(directory, key, credentials);
    const file = path.join(directory, 'session.enc.json');
    const contents = readFileSync(file, 'utf8');
    assert.ok(!contents.includes('sensitive-cookie-value'));
    assert.equal(statSync(file).mode & 0o777, 0o600);
    const saved = JSON.parse(contents);
    const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(saved.iv, 'base64'));
    decipher.setAuthTag(Buffer.from(saved.tag, 'base64'));
    const decoded = Buffer.concat([decipher.update(Buffer.from(saved.ciphertext, 'base64')), decipher.final()]);
    assert.deepEqual(JSON.parse(decoded.toString()), credentials);
  } finally { rmSync(directory, { recursive: true }); }
});
