import { readFileSync } from 'node:fs';
import { Zalo } from 'zca-js';
import { decryptCredentials } from './state.mjs';
import { executeMessageAction } from './message-action.mjs';

let sending = false;
const finish = value => { process.stdout.write(JSON.stringify(value)); process.exit(0); };
setTimeout(() => finish({state: sending ? 'unknown' : 'failed'}), 40_000);
try {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  if (input.attachment) {
    const file = input.attachment;
    input.attachment = {data: readFileSync(file.path), filename: file.filename,
      metadata: {totalSize: file.size, width: file.width, height: file.height}};
  }
  const credentials = decryptCredentials(JSON.parse(readFileSync(input.session)), readFileSync(input.key));
  const api = await new Zalo({logging: false, checkUpdate: false}).login(credentials);
  finish(await executeMessageAction(api, input, () => { sending = true; }));
} catch {
  // An error after dispatch may follow acceptance by Zalo. Never retry automatically.
  finish({state: sending ? 'unknown' : 'failed'});
}
