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

test('hidden group reports visible subset and actual viewer role without inventing more pages',async()=>{
  let requested=[];
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '2',
    getGroupInfo:async()=>({gridInfoMap:{'900':{name:'Hidden',creatorId:'1',adminIds:[],setting:{lockViewMember:1},
      currentMems:[{id:'1',dName:'Owner'},{id:'2',dName:'Self'}],totalMember:441,hasMoreMember:1}}}),
    getGroupMembersInfo:async ids=>{requested=ids;return {profiles:{}};}};
  const result=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(result.accessible_total,2);assert.equal(result.total,441);assert.equal(result.limit_reason,'hidden_members');
  assert.equal(result.viewer_role,'member');assert.equal(result.has_more,false);assert.deepEqual(requested,['1','2']);
});

test('authorized admin scans all returned IDs in a hidden group, ignoring preview-only hasMoreMember',async()=>{
  const ids=Array.from({length:441},(_,i)=>String(i+1));
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '2',
    getGroupInfo:async()=>({gridInfoMap:{'900':{name:'Admin group',creatorId:'1',adminIds:['2'],setting:{lockViewMember:1},
      memVerList:ids.map(id=>id+'_0'),currentMems:[{id:'1',dName:'Owner'},{id:'2',dName:'Admin'}],totalMember:441,hasMoreMember:1}}}),
    getGroupMembersInfo:async()=>({profiles:{}})};
  const found=[];
  for(let offset=0;offset<500;offset+=100){
    const result=await executeScan(api,{kind:'members',group_id:'900',offset});
    assert.equal(result.limited,false);assert.equal(result.limit_reason,'');assert.equal(result.viewer_role,'admin');
    assert.equal(result.accessible_total,441);assert.equal(result.has_more,offset<400);found.push(...result.rows.map(row=>row.uid));
  }
  assert.equal(new Set(found).size,441);
});

test('incomplete response does not claim hidden-member policy without explicit group setting',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '1',
    getGroupInfo:async()=>({gridInfoMap:{'900':{name:'Unknown',creatorId:'1',currentMems:[{id:'1'}],totalMember:441,hasMoreMember:1}}}),
    getGroupMembersInfo:async()=>({profiles:{}})};
  const result=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(result.limit_reason,'incomplete_members');assert.equal(result.viewer_role,'owner');assert.equal(result.accessible_total,1);
});

test('hidden member list uses enabled group-link memberPage pagination for the same joined group',async()=>{
  const ids=Array.from({length:441},(_,i)=>String(i+1)),requests=[];
  const link='https://zalo.me/g/PRIVATEINVITE';
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '2',
    getGroupInfo:async()=>({gridInfoMap:{'900':{name:'Hidden 441',creatorId:'1',setting:{lockViewMember:1},currentMems:[{id:'1'},{id:'2'}],totalMember:441,hasMoreMember:1}}}),
    getGroupLinkDetail:async id=>{assert.equal(id,'900');return {enabled:1,link};},
    getGroupLinkInfo:async payload=>{
      requests.push(payload.memberPage);assert.equal(payload.link,link);
      return {groupId:'900',creatorId:'1',currentMems:ids.slice((payload.memberPage-1)*50,payload.memberPage*50).map(id=>({id,dName:'Member '+id})),hasMoreMember:payload.memberPage<9?1:0,totalMember:441};
    }};
  let offset=0,cursor={},found=[];
  for(let index=0;index<9;index++){
    const result=await executeScan(api,{kind:'members',group_id:'900',offset,cursor});
    assert.equal(result.member_source,'group_link');assert.equal(result.limited,false);
    assert.ok(!JSON.stringify(result).includes('PRIVATEINVITE'));
    found.push(...result.rows.map(row=>row.uid));offset=result.next_offset;cursor=result.cursor;
    assert.equal(result.has_more,index<8);
  }
  assert.equal(new Set(found).size,441);assert.equal(offset,441);
  assert.deepEqual(requests,[1,2,3,4,5,6,7,8,9]);
});

test('group link fallback never enables a disabled invitation link or accepts another group',async()=>{
  let calls=0;
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{currentMems:[{id:'1'}],totalMember:441,setting:{lockViewMember:1}}}}),getGroupMembersInfo:async()=>({profiles:{}}),
    getGroupLinkDetail:async()=>({enabled:0,link:'https://zalo.me/g/test'}),getGroupLinkInfo:async()=>{calls++;return {groupId:'901',currentMems:[{id:'999'}]};}};
  const result=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(result.rows.length,1);assert.equal(result.limit_reason,'hidden_members');assert.equal(calls,0);
  api.getGroupLinkDetail=async()=>({enabled:1,link:'https://zalo.me/g/test'});
  await assert.rejects(executeScan(api,{kind:'members',group_id:'900'}),/Invalid linked group/);
});

test('large group-link pages are chunked without dropping members',async()=>{
  const members=Array.from({length:250},(_,i)=>({id:String(i+1),dName:'Member'}));
  const requested=[];
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{currentMems:[{id:'1'}],totalMember:250}}}),
    getGroupLinkDetail:async()=>({enabled:1,link:'https://zalo.me/g/test'}),getGroupLinkInfo:async payload=>{requested.push(payload.memberPage);return {groupId:'900',currentMems:members,hasMoreMember:0,totalMember:250};}};
  let offset=0,cursor={},found=[];
  for(let index=0;index<3;index++){
    const result=await executeScan(api,{kind:'members',group_id:'900',offset,cursor});
    found.push(...result.rows.map(row=>row.uid));offset=result.next_offset;cursor=result.cursor;
    assert.equal(result.has_more,index<2);
  }
  assert.equal(new Set(found).size,250);assert.deepEqual(requested,[1,1,1]);
});
