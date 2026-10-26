import {readFileSync} from 'node:fs';
import {Zalo} from 'zca-js';
import {decryptCredentials} from './state.mjs';
import {executeScan} from './scan-action.mjs';
import {lookupFailure} from './lookup-errors.mjs';
let stage='input';
const finish=value=>{process.stdout.write(JSON.stringify(value));process.exit(0);};
setTimeout(()=>finish({state:'error',reason:'network'}),40000);
try {
  const input=JSON.parse(readFileSync(0,'utf8'));
  const credentials=decryptCredentials(JSON.parse(readFileSync(input.session)),readFileSync(input.key));
  stage='session';
  const api=await new Zalo({logging:false,checkUpdate:false}).login(credentials);
  stage='lookup';finish(await executeScan(api,input));
} catch(error) {finish({state:'error',reason:lookupFailure(error,stage).lookup_reason || 'unavailable'});}
