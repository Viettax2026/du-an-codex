import test from 'node:test';
import assert from 'node:assert/strict';
import {executeScan,assertJoinedGroup} from './scan-action.mjs';
import {executeMessageAction} from './message-action.mjs';

test('friend scan paginates and returns only public fields without mutations',async()=>{
  const api={getAllFriends:async(count,page)=>{assert.equal(count,100);assert.equal(page,2);return [{userId:'123',displayName:'Lan',phoneNumber:'0901234567',cookie:'SECRET'}];}};
  const result=await executeScan(api,{kind:'friends',offset:100});
  assert.equal(result.rows[0].phone,'0901234567');assert.equal(result.next_offset,200);
  assert.ok(!JSON.stringify(result).includes('SECRET'));assert.equal(result.has_more,false);
});

test('member scan preserves hidden phones and derives roles from joined group',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{name:'Team',creatorId:'1',adminIds:['2'],memVerList:['1_0','2_7','3_0'],totalMember:3}}}),
    getGroupMembersInfo:async ids=>{assert.deepEqual(ids,['1','2','3']);return {profiles:{'1':{displayName:'Owner'},'2':{displayName:'Admin'},'3':{displayName:'Member'}}};}};
  const result=await executeScan(api,{kind:'members',group_id:'900'});
  assert.deepEqual(result.rows.map(row=>row.role),['owner','admin','member']);assert.ok(result.rows.every(row=>row.phone===''));
  await assert.rejects(executeScan(api,{kind:'members',group_id:'901'}));
});

test('group scan reports restricted or incomplete member lists',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{name:'Limited',currentMems:[{id:'1',dName:'Visible'}],totalMember:20,hasMoreMember:1}}}),getGroupMembersInfo:async()=>({profiles:{}})};
  const result=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(result.limited,true);assert.equal(result.rows.length,1);assert.equal(result.total,20);
});

test('group sends use Group thread type including styled image text and never user thread',async()=>{
  const calls=[];const api={sendMessage:async(data,id,type)=>{calls.push({data,id,type});return data.attachments?{attachment:[{msgId:'image'}]}:{message:{msgId:'text'}};}};
  const result=await executeMessageAction(api,{action:'send',thread_type:1,uid:'900',message:'Hello',styles:[{start:0,len:5,st:'b'}],attachment:{data:Buffer.from('image'),filename:'a.png',metadata:{totalSize:5,width:1,height:1}}});
  assert.equal(result.state,'sent');assert.equal(calls.length,2);assert.ok(calls.every(call=>call.type===1 && call.id==='900'));
  await assert.rejects(executeMessageAction(api,{action:'friend',thread_type:1,uid:'900',message:'Hello'}));
  await assert.rejects(assertJoinedGroup({getAllGroups:async()=>({gridVerMap:{'901':1}})},'900'));
});
