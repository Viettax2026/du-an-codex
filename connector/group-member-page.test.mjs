import test from 'node:test';
import assert from 'node:assert/strict';
import {installGroupMemberPaging} from './group-member-page.mjs';
import {createContext} from './node_modules/zca-js/dist/context.js';
import {encodeAES,decodeAES} from './node_modules/zca-js/dist/utils.js';
import {executeScan} from './scan-action.mjs';

function harness({error=0}={}) {
  const ctx=createContext(),requests=[];
  ctx.secretKey=Buffer.alloc(32,7).toString('base64');ctx.imei='synthetic-device';ctx.userAgent='offline-test';
  ctx.cookie={getCookieString:async()=>''};ctx.options.logging=false;
  ctx.options.polyfill=async(url,options)=>{
    assert.equal(new URL(url).hostname,'group.chat.zalo.me');assert.equal(options.method,'GET');
    assert.equal(new URL(url).searchParams.get('zpw_ver'),'689');
    assert.equal(new URL(url).searchParams.get('zpw_type'),'30');
    requests.push({path:new URL(url).pathname,params:JSON.parse(decodeAES(ctx.secretKey,new URL(url).searchParams.get('params')))});
    if(error)return new Response(JSON.stringify({error_code:error,error_message:'PRIVATE_UPSTREAM'}));
    const data={groupId:'900',totalMember:645,currentMems:[{id:'123',dName:'Member'}],hasMoreMember:1};
    return new Response(JSON.stringify({error_code:0,data:encodeAES(ctx.secretKey,JSON.stringify({error_code:0,data}))}));
  };
  const api={getContext:()=>ctx,zpwServiceMap:{group:['https://group.chat.zalo.me']}};
  installGroupMemberPaging(api);return {api,requests};
}

test('group page adapter uses pinned SDK encryption, session and response handling',async()=>{
  const {api,requests}=harness();
  const data=await api.getGroupInfoV2('900',{mpage:3,mcount:100});
  assert.equal(data.currentMems[0].id,'123');assert.equal(requests.length,1);
  assert.deepEqual(requests[0],{path:'/api/group/getgi/v2',params:{grid:'900',avatar_size:120,member_avatar_size:120,mpage:3,mcount:100,imei:'synthetic-device'}});
  for(const options of [{mpage:0},{mpage:1.5},{mpage:10001},{mpage:1,mcount:1000}])await assert.rejects(api.getGroupInfoV2('900',options));
  await assert.rejects(api.getGroupInfoV2('900/other'));assert.equal(requests.length,1);
});

test('group page adapter propagates authorization errors without retries and rejects unexpected services',async()=>{
  const {api,requests}=harness({error:403});
  await assert.rejects(api.getGroupInfoV2('900'),error=>error.code===403);assert.equal(requests.length,1);
  api.zpwServiceMap.group[0]='https://unexpected.invalid';
  await assert.rejects(api.getGroupInfoV2('900'),/Invalid group service/);assert.equal(requests.length,1);
});

test('candidate page source cannot be called for an unjoined group',async()=>{
  const {api,requests}=harness();api.getAllGroups=async()=>({gridVerMap:{'901':1}});
  await assert.rejects(executeScan(api,{kind:'members',group_id:'900'}),/not joined/);assert.equal(requests.length,0);
});
