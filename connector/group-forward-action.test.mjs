import test from 'node:test';
import assert from 'node:assert/strict';
import {executeGroupForward} from './group-forward-action.mjs';
import {forwardMessageFactory} from './node_modules/zca-js/dist/apis/forwardMessage.js';
import {createContext} from './node_modules/zca-js/dist/context.js';
import {encodeAES,decodeAES} from './node_modules/zca-js/dist/utils.js';

test('sharing uses Group threads, at most 50 destinations and only joined groups',async()=>{
  const calls=[];const api={getAllGroups:async()=>({gridVerMap:{'900':1,'901':1}}),forwardMessage:async(...args)=>{calls.push(args);return {success:[{msgId:'100'},{msgId:'101'}],fail:[]};}};
  const result=await executeGroupForward(api,{group_ids:['900','901','999'],message:'Thông báo'});
  assert.deepEqual(calls,[[{message:'Thông báo'},['900','901'],1]]);
  assert.deepEqual(result.rows.map(row=>row.state),['sent','sent','failed']);assert.equal(result.rows[2].reason,'group_not_joined');
  await assert.rejects(executeGroupForward(api,{group_ids:Array.from({length:51},(_,i)=>String(i+1)),message:'Hi'}));
  await assert.rejects(executeGroupForward(api,{group_ids:['900','900'],message:'Hi'}));assert.equal(calls.length,1);
});

test('partial acknowledgements, duplicate IDs and network failures never attribute or retry a batch',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1,'901':1}})};
  let calls=0;
  for(const response of [{success:[{msgId:'100'}],fail:[{error_code:'1'}]},{success:[{msgId:'100'},{msgId:'100'}],fail:[]},{success:[],fail:[]},null]){
    api.forwardMessage=async()=>{calls++;if(response===null)throw new Error('PRIVATE');return response;};
    const data=await executeGroupForward(api,{group_ids:['900','901'],message:'Hi'});assert.ok(data.rows.every(row=>row.state==='unknown'));assert.ok(!JSON.stringify(data).includes('PRIVATE'));
  }
  assert.equal(calls,4);
  api.forwardMessage=async()=>({success:[],fail:[{error_code:'1'},{error_code:'1'}]});
  assert.ok((await executeGroupForward(api,{group_ids:['900','901'],message:'Hi'})).rows.every(row=>row.state==='failed'));
});

test('pinned SDK actually encodes a group forward to multiple group IDs',async()=>{
  const ctx=createContext(),requests=[];ctx.secretKey=Buffer.alloc(32,1).toString('base64');ctx.imei='synthetic';ctx.userAgent='offline';ctx.cookie={getCookieString:async()=>''};ctx.options.logging=false;
  ctx.options.polyfill=async(url,options)=>{assert.equal(new URL(url).hostname,'sdk.invalid');requests.push({path:new URL(url).pathname,params:JSON.parse(decodeAES(ctx.secretKey,options.body.get('params')))});return new Response(JSON.stringify({error_code:0,data:encodeAES(ctx.secretKey,JSON.stringify({error_code:0,data:{success:[{msgId:'100'},{msgId:'101'}],fail:[]}}))}));};
  const api={zpwServiceMap:{file:['https://sdk.invalid']},getAllGroups:async()=>({gridVerMap:{'900':1,'901':1}})};api.forwardMessage=forwardMessageFactory(ctx,api);
  const data=await executeGroupForward(api,{group_ids:['900','901'],message:'Thông báo'});
  assert.ok(data.rows.every(row=>row.state==='sent'));assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/group/mforward');
  assert.deepEqual(requests[0].params.grids.map(row=>row.grid),['900','901']);assert.equal(requests[0].params.totalIds,2);
});
