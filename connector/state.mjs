import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { writeFileSync, renameSync } from 'node:fs';
import path from 'node:path';

export function writePrivateJSON(file, value) {
  const temporary = `${file}.${randomBytes(8).toString('hex')}.tmp`;
  writeFileSync(temporary, JSON.stringify(value), { mode: 0o600 });
  renameSync(temporary, file);
}

export function saveCredentials(directory, key, credentials) {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(credentials)), cipher.final()]);
  writePrivateJSON(path.join(directory, 'session.enc.json'), {
    version: 1, iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'),
    ciphertext: encrypted.toString('base64'),
  });
}

export function decryptCredentials(record, key) {
  if (record.version !== 1) throw new Error('Unsupported session');
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(record.iv, 'base64'));
  decipher.setAuthTag(Buffer.from(record.tag, 'base64'));
  return JSON.parse(Buffer.concat([decipher.update(Buffer.from(record.ciphertext, 'base64')), decipher.final()]).toString());
}

export function publicEvent(type, data, previous = {}) {
  const base = { updated_at: Date.now() / 1000 };
  switch (type) {
    case 0: {
      const image = String(data.image || '').replace(/^data:image\/png;base64,/, '');
      if (!image || image.length > 1_000_000 || !/^[A-Za-z0-9+/=]+$/.test(image)) {
        throw new Error('Invalid QR image');
      }
      return { ...base, state: 'qr', image, expires_at: Date.now() / 1000 + 100 };
    }
    case 1: return { ...base, state: 'expired', message: 'Mã QR đã hết hạn. Tạo mã mới để thử lại.' };
    case 2: return { ...previous, ...base, state: 'scanned', display_name: String(data.display_name || '').slice(0,100) };
    case 3: return { ...base, state: 'declined', message: 'Bạn đã từ chối đăng nhập trên điện thoại.' };
    default: return previous;
  }
}
