import { readFileSync } from 'node:fs';
import path from 'node:path';
import { Zalo, LoginQRCallbackEventType } from 'zca-js';
import { publicEvent, saveCredentials, writePrivateJSON } from './state.mjs';

const [directory, keyPath] = process.argv.slice(2);
if (!directory || !keyPath) process.exit(2);
process.umask(0o077);
const statusPath = path.join(directory, 'status.json');
const key = readFileSync(keyPath);
if (key.length !== 32) process.exit(2);
let state = { state: 'loading', updated_at: Date.now() / 1000 };
let credentials = null;
const publish = value => { state = value; writePrivateJSON(statusPath, value); };
publish(state);
const timeout = setTimeout(() => {
  publish({ state: 'error', updated_at: Date.now() / 1000,
    message: 'Kết nối Zalo quá thời gian chờ. Vui lòng thử lại.' });
  process.exit(1);
}, 180_000);

try {
  const zalo = new Zalo({ logging: false, checkUpdate: false });
  await zalo.loginQR({}, event => {
    if (event.type === LoginQRCallbackEventType.GotLoginInfo) {
      // Keep credentials in memory until the library verifies login successfully.
      credentials = event.data;
      return;
    }
    publish(publicEvent(event.type, event.data, state));
    if (event.type === LoginQRCallbackEventType.QRCodeExpired) {
      event.actions.abort();
    }
    if (event.type === LoginQRCallbackEventType.QRCodeDeclined) {
      // zca-js leaves this Promise unsettled; stop the worker explicitly.
      clearTimeout(timeout);
      process.exit(0);
    }
  });
  if (!credentials) throw new Error('No login credentials');
  saveCredentials(directory, key, credentials);
  publish({ state: 'connected', display_name: state.display_name || '',
    verified_at: Date.now() / 1000, updated_at: Date.now() / 1000,
    message: 'Đăng nhập đã được Zalo xác nhận. Chưa bật gửi tin tự động.' });
  credentials = null;
  clearTimeout(timeout);
  process.exit(0);
} catch {
  clearTimeout(timeout);
  if (state.state !== 'expired') {
    publish({ state: 'error', updated_at: Date.now() / 1000,
      message: 'Không thể đăng nhập Zalo. Kiểm tra kết nối mạng VPS hoặc thử lại sau.' });
  }
  // Never print upstream errors, cookies, tokens, or QR payloads in logs.
  process.exit(1);
}
