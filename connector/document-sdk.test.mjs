import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {setTimeout as sleep} from 'node:timers/promises';
import {createHash} from 'node:crypto';
import {WebSocketServer} from 'ws';
import {Listener} from './node_modules/zca-js/dist/apis/listen.js';
import {sendMessageFactory} from './node_modules/zca-js/dist/apis/sendMessage.js';
import {uploadAttachmentFactory} from './node_modules/zca-js/dist/apis/uploadAttachment.js';
import {createContext} from './node_modules/zca-js/dist/context.js';
import {encodeAES,decodeAES} from './node_modules/zca-js/dist/utils.js';
import {executeMessageAction} from './message-action.mjs';
import {withAttachmentListener} from './attachment-listener.mjs';

function frame(command,subCommand,data) {
  const header=Buffer.alloc(4);header[0]=1;header.writeUInt16LE(command,1);header[3]=subCommand;
  return Buffer.concat([header,Buffer.from(JSON.stringify(data))]);
}

async function harness(t,{fileAck=true}={}) {
  // Actual pinned SDK uploader + message serializer + listener, with a local
  // WebSocket and synthetic encrypted HTTP responses. Never contact Zalo.
  const server=new WebSocketServer({host:'127.0.0.1',port:0});
  await once(server,'listening');
  let socket;
  server.on('connection',ws=>{
    socket=ws;
    ws.send(frame(1,1,{key:Buffer.alloc(32,2).toString('base64')}));
  });
  const ctx=createContext();ctx.secretKey=Buffer.alloc(32,1).toString('base64');
  ctx.imei='offline-file-test';ctx.userAgent='offline-file-test';ctx.uid='777';
  ctx.cookie={getCookieString:async()=>'',getCookieStringSync:()=>''};
  ctx.options.logging=false;
  // Omit only the SDK map's five-minute garbage-collection timers in tests.
  ctx.uploadCallbacks=new Map();
  ctx.settings={features:{
    sharefile:{max_file:10,max_size_share_file_v3:10,restricted_ext_file:[],chunk_size_file:1024*1024},
    socket:{retries:{},close_and_retry_codes:[],rotate_error_codes:[],ping_interval:60000},
  }};
  const requests=[];
  ctx.options.polyfill=async(url,options)=>{
    const endpoint=new URL(url);assert.equal(endpoint.hostname,'sdk.invalid');
    const encrypted=endpoint.searchParams.get('params') || options.body.get('params');
    const params=JSON.parse(decodeAES(ctx.secretKey,encrypted));
    requests.push({path:endpoint.pathname,params});
    let result={msgId:1000+requests.length};
    if (endpoint.pathname.endsWith('/asyncfile/upload')) {
      assert.ok(Buffer.isBuffer(options.body));
      result={fileId:'500',clientFileId:'501'};
      // SDK registers the completion callback after processing this response.
      setImmediate(()=>{
        if (socket?.readyState===1) socket.send(frame(601,0,{encrypt:0,data:JSON.stringify({data:{controls:[{
          content:{act_type:'file_done',fileId:'500',data:{url:'https://sdk.invalid/uploaded-file'}},
        }]}})}));
      });
    } else if (endpoint.pathname.endsWith('/asyncfile/msg') && !fileAck) result={};
    const data=encodeAES(ctx.secretKey,JSON.stringify({error_code:0,data:result}));
    return new Response(JSON.stringify({error_code:0,data}),{headers:{'Content-Type':'application/json'}});
  };
  const api={zpwServiceMap:{chat:['https://sdk.invalid'],group:['https://sdk.invalid'],file:['https://sdk.invalid']}};
  api.uploadAttachment=uploadAttachmentFactory(ctx,api);
  api.sendMessage=sendMessageFactory(ctx,api);
  api.listener=new Listener(ctx,[`ws://127.0.0.1:${server.address().port}`]);
  t.after(async()=>{
    api.listener.stop();
    for (const connection of server.clients) connection.terminate();
    await new Promise(resolve=>server.close(resolve));
  });
  return {api,requests};
}

const pdf={action:'send',uid:'123',message:'Em gửi hợp đồng',attachment:{filename:'Hop-dong.pdf',data:Buffer.from('%PDF-1.4\n%%EOF'),metadata:{totalSize:14}}};

test('reproduces the original real-SDK bug: text arrives but PDF waits forever without the file-completion listener',{timeout:3000},async t=>{
  const {api,requests}=await harness(t);
  const result=executeMessageAction(api,pdf);
  assert.equal(await Promise.race([result.then(()=> 'completed'),sleep(60).then(()=> 'waiting')]),'waiting');
  assert.deepEqual(requests.map(request=>request.path),['/api/message/sms','/api/message/asyncfile/upload']);
  assert.equal(requests.some(request=>request.path.endsWith('/asyncfile/msg')),false);
});

for (const threadType of [0,1]) for (const filename of ['Hop-dong.pdf','video.mp4']) {
  test(`real SDK completes ${filename} for thread ${threadType} and sends the uploaded file URL`,{timeout:3000},async t=>{
    const {api,requests}=await harness(t);
    const input={...pdf,thread_type:threadType,attachment:{...pdf.attachment,filename}};
    const result=await withAttachmentListener(api,input,()=>executeMessageAction(api,input));
    assert.deepEqual(result,{state:'sent',message_id:'1001,1003'});
    const base=threadType===1?'/api/group':'/api/message';
    assert.deepEqual(requests.map(request=>request.path),[base+(threadType===1?'/sendmsg':'/sms'),base+'/asyncfile/upload',base+'/asyncfile/msg']);
    const file=requests[2].params;
    assert.equal(file.fileName,filename);assert.equal(file.fileUrl,'https://sdk.invalid/uploaded-file');
    assert.equal(file.fileId,'500');assert.equal(file.totalSize,14);
    assert.equal(file.checksum,createHash('md5').update(pdf.attachment.data).digest('hex'));
    assert.equal(file[threadType===1?'grid':'toid'],'123');
    assert.equal(requests.filter(request=>request.params.message===input.message).length,1);
  });
}

test('real SDK text acceptance without a file acknowledgement stays uncertain',{timeout:3000},async t=>{
  const {api,requests}=await harness(t,{fileAck:false});
  assert.deepEqual(await withAttachmentListener(api,pdf,()=>executeMessageAction(api,pdf)),{state:'unknown'});
  assert.equal(requests.length,3);
});
