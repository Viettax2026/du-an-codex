import test from 'node:test';
import assert from 'node:assert/strict';
import { sendMessageFactory } from './node_modules/zca-js/dist/apis/sendMessage.js';
import { createContext } from './node_modules/zca-js/dist/context.js';
import { encodeAES, decodeAES } from './node_modules/zca-js/dist/utils.js';
import { executeMessageAction } from './message-action.mjs';

function sdkHarness() {
  const requests=[];
  const ctx=createContext();
  // Synthetic credentials and encrypted mock responses; no Zalo login/network.
  ctx.secretKey=Buffer.alloc(32,1).toString('base64');
  ctx.imei='offline-test';ctx.userAgent='offline-test';
  ctx.cookie={getCookieString:async()=>''};
  ctx.settings={features:{sharefile:{max_file:10,max_size_share_file_v3:10}}};
  ctx.options.logging=false;
  ctx.options.polyfill=async(url,options)=>{
    assert.equal(new URL(url).hostname,'sdk.invalid');
    const params=JSON.parse(decodeAES(ctx.secretKey,options.body.get('params')));
    requests.push({path:new URL(url).pathname,params});
    const data=encodeAES(ctx.secretKey,JSON.stringify({error_code:0,data:{msgId:100+requests.length}}));
    return new Response(JSON.stringify({error_code:0,data}),{headers:{'Content-Type':'application/json'}});
  };
  const api={
    zpwServiceMap:{chat:['https://sdk.invalid'],group:['https://sdk.invalid'],file:['https://sdk.invalid']},
    uploadAttachment:async()=>[{fileType:'image',photoId:'offline-photo',width:2,height:2,totalSize:5,
      normalUrl:'https://sdk.invalid/image',hdUrl:'https://sdk.invalid/image',thumbUrl:'https://sdk.invalid/image'}],
  };
  api.sendMessage=sendMessageFactory(ctx,api);
  return {api,requests};
}

test('real pinned SDK serializes UTF-16 bold/italic into textProperties after sending image without a caption', async()=>{
  const {api,requests}=sdkHarness();
  const styles=[{start:3,len:8,st:'b'},{start:8,len:3,st:'i'}];
  const result=await executeMessageAction(api,{action:'send',uid:'123',message:'😊 Chào Lan',styles,
    attachment:{data:Buffer.from('image'),filename:'quote.jpg',metadata:{totalSize:5,width:2,height:2}}});
  assert.equal(requests.length,2);
  assert.equal(requests[0].path,'/api/message/photo_original/send');
  assert.equal(requests[0].params.desc,'');
  assert.equal(requests[1].path,'/api/message/sms');
  assert.equal(requests[1].params.message,'😊 Chào Lan');
  assert.deepEqual(JSON.parse(requests[1].params.textProperties),{styles,ver:0});
  assert.deepEqual(result,{state:'sent',message_id:'101,102'});
});

test('real pinned SDK sends plain image caption once without duplicating its text', async()=>{
  const {api,requests}=sdkHarness();
  const result=await executeMessageAction(api,{action:'send',uid:'123',message:'Chào Lan',
    attachment:{data:Buffer.from('image'),filename:'quote.jpg',metadata:{totalSize:5,width:2,height:2}}});
  assert.equal(requests.length,1);
  assert.equal(requests[0].params.desc,'Chào Lan');
  assert.deepEqual(result,{state:'sent',message_id:'101'});
});
