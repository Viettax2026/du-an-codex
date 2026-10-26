import {readFileSync} from 'node:fs';
import {Zalo} from 'zca-js';
import {decryptCredentials} from './state.mjs';
import {executeGroupForward} from './group-forward-action.mjs';
const finish=value=>{process.stdout.write(JSON.stringify(value));process.exit(0);};
setTimeout(()=>finish({state:'error'}),40000);
try {
  const input=JSON.parse(readFileSync(0,'utf8'));
  const credentials=decryptCredentials(JSON.parse(readFileSync(input.session)),readFileSync(input.key));
  const api=await new Zalo({logging:false,checkUpdate:false}).login(credentials);
  finish(await executeGroupForward(api,input));
} catch {finish({state:'error'});}
