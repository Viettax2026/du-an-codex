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

test('failed or empty link lookup preserves group-info profiles and reports only safe diagnostics',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '2',
    getGroupInfo:async()=>({gridInfoMap:{'900':{type:2,currentMems:[{id:'1',dName:'Owner'},{id:'2',dName:'Self'}],totalMember:648,setting:{lockViewMember:1}}}}),
    getGroupMembersInfo:async()=>({profiles:{}}),
    getGroupLinkDetail:async()=>{throw Object.assign(new Error('SECRET_SESSION https://zalo.me/g/PRIVATE'),{code:403});},
    getGroupLinkInfo:async()=>({groupId:'900',currentMems:[],hasMoreMember:0,totalMember:648})};
  const first=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(first.rows.length,2);assert.equal(first.limited,true);
  assert.equal(first.diagnostics.link_status,'detail_error');assert.equal(first.diagnostics.error_code,'403');
  assert.equal(first.diagnostics.group_type,2);assert.equal(first.diagnostics.group_info_ids,2);
  assert.ok(!JSON.stringify(first.diagnostics).includes('SECRET'));assert.ok(!JSON.stringify(first.diagnostics).includes('900'));
  api.getGroupLinkDetail=async()=>({enabled:1,link:'https://zalo.me/g/PRIVATE'});
  const empty=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(empty.rows.length,2);assert.equal(empty.diagnostics.link_status,'empty');assert.equal(empty.member_source,'group_info');
  api.getGroupLinkInfo=async()=>{throw Object.assign(new Error('SECRET_SESSION'),{code:'SECRET_CODE'});};
  const failed=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(failed.rows.length,2);assert.equal(failed.diagnostics.link_status,'page_error');assert.equal(failed.diagnostics.error_code,'');
  // An interrupted later page must remain retryable, rather than silently changing sources.
  await assert.rejects(executeScan(api,{kind:'members',group_id:'900',offset:50,cursor:{source:'group_link',member_page:2,member_offset:0}}));
});

test('community with four info IDs and a one-person link retains the union, not just the link preview',async()=>{
  const requested=[];
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '2',
    getGroupInfo:async()=>({gridInfoMap:{'900':{type:2,name:'Community',creatorId:'1',adminIds:['3'],
      memVerList:['1_0','2_0','3_0','4_0'],currentMems:[],totalMember:645,setting:{lockViewMember:1}}}}),
    getGroupLinkDetail:async()=>({enabled:1,link:'https://zalo.me/g/test'}),
    getGroupLinkInfo:async({memberPage})=>{assert.equal(memberPage,1);return {groupId:'900',currentMems:[{id:'2',dName:'Self'}],hasMoreMember:0,totalMember:645};},
    getGroupMembersInfo:async ids=>{requested.push(...ids);return {profiles:{'1_0':{displayName:'Owner'},'3':{displayName:'Admin'},'4':{displayName:'Other',cookie:'PRIVATE'}}};}};
  const result=await executeScan(api,{kind:'members',group_id:'900'});
  assert.deepEqual(new Set(result.rows.map(row=>row.uid)),new Set(['1','2','3','4']));
  assert.deepEqual(requested,['1','3','4']);assert.equal(result.rows.find(row=>row.uid==='3').role,'admin');
  assert.equal(result.rows.find(row=>row.uid==='1').name,'Owner');assert.equal(result.total,645);
  assert.equal(result.diagnostics.link_valid_count,1);assert.equal(result.diagnostics.merged_first_page_count,4);
  assert.equal(result.has_more,false);assert.ok(!JSON.stringify(result).includes('PRIVATE'));
  api.getGroupMembersInfo=async()=>{throw Object.assign(new Error('PRIVATE'),{code:403});};
  const partial=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(partial.rows.length,4);assert.equal(partial.diagnostics.profile_error_code,'403');
});

test('merged first native page keeps its overflow and later link pages without losing unique IDs',async()=>{
  const ids=Array.from({length:150},(_,i)=>String(i+1));
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{memVerList:ids.map(id=>id+'_0'),totalMember:645}}}),
    getGroupLinkDetail:async()=>({enabled:1,link:'https://zalo.me/g/test'}),
    getGroupLinkInfo:async({memberPage})=>({groupId:'900',currentMems:[{id:memberPage===1?'2':'151',dName:'Link member'}],hasMoreMember:memberPage===1?1:0,totalMember:645}),
    getGroupMembersInfo:async()=>({profiles:{}})};
  let offset=0,cursor={},found=[];
  for(let index=0;index<3;index++){
    const result=await executeScan(api,{kind:'members',group_id:'900',offset,cursor});
    found.push(...result.rows.map(row=>row.uid));offset=result.next_offset;cursor=result.cursor;
    assert.equal(result.has_more,index<2);assert.ok(result.rows.length<=100);
  }
  assert.equal(found.length,151);assert.equal(new Set(found).size,151);
});

test('ID-based group pages read all returned members without relying on a truncated invite preview',async()=>{
  const requests=[],ids=Array.from({length:645},(_,i)=>String(i+1));
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getOwnId:()=> '2',
    getGroupInfo:async()=>({gridInfoMap:{'900':{type:2,creatorId:'1',memVerList:['1_0','2_0','3_0','4_0'],totalMember:645,setting:{lockViewMember:1}}}}),
    getGroupInfoV2:async(id,{mpage,mcount})=>{assert.equal(id,'900');assert.equal(mcount,100);requests.push(mpage);return {groupId:'900',creatorId:'1',currentMems:ids.slice((mpage-1)*100,mpage*100).map(id=>({id,dName:'Member '+id,cookie:'PRIVATE'})),hasMoreMember:mpage<7?1:0,totalMember:645};},
    getGroupLinkDetail:async()=>{throw new Error('Must not use link when group pages are available');}};
  let offset=0,cursor={},found=[];
  for(let index=0;index<7;index++){
    const data=await executeScan(api,{kind:'members',group_id:'900',offset,cursor});
    assert.equal(data.member_source,'group_info_v2');assert.equal(data.viewer_role,'member');assert.equal(data.has_more,index<6);
    assert.equal(data.diagnostics.paged_status,'ok');assert.ok(!JSON.stringify(data).includes('PRIVATE'));
    found.push(...data.rows.map(row=>row.uid));offset=data.next_offset;cursor=data.cursor;
  }
  assert.equal(new Set(found).size,645);assert.deepEqual(requests,[1,2,3,4,5,6,7]);
});

test('partial group pages preserve newly returned IDs when link reading is unavailable',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{memVerList:['1_0'],totalMember:645}}}),
    getGroupInfoV2:async()=>({groupId:'900',currentMems:[{id:'2',dName:'New'}],totalMember:645,hasMoreMember:0}),getGroupMembersInfo:async()=>({profiles:{}})};
  const data=await executeScan(api,{kind:'members',group_id:'900'});
  assert.deepEqual(data.rows.map(row=>row.uid),['1','2']);assert.equal(data.accessible_total,2);assert.equal(data.limited,true);
  assert.equal(data.diagnostics.paged_valid_count,1);assert.equal(data.diagnostics.paged_more,false);
  api.getGroupInfoV2=async()=>{throw Object.assign(new Error('PRIVATE'),{code:403});};
  const denied=await executeScan(api,{kind:'members',group_id:'900'});
  assert.equal(denied.rows.length,1);assert.equal(denied.diagnostics.paged_error_code,'403');assert.ok(!JSON.stringify(denied).includes('PRIVATE'));
  await assert.rejects(executeScan(api,{kind:'members',group_id:'900',offset:100,cursor:{source:'group_info_v2',member_page:2,member_offset:0}}));
});

test('paged response must belong to selected group and oversized native pages retain their cursor',async()=>{
  const api={getAllGroups:async()=>({gridVerMap:{'900':1}}),getGroupInfo:async()=>({gridInfoMap:{'900':{memVerList:['1_0'],totalMember:250}}}),
    getGroupInfoV2:async()=>({groupId:'901',currentMems:[{id:'999'}],hasMoreMember:0})};
  await assert.rejects(executeScan(api,{kind:'members',group_id:'900'}),/Invalid paged group/);
  const pages=[];
  api.getGroupInfoV2=async(id,{mpage})=>{pages.push(mpage);return {groupId:'900',totalMember:250,currentMems:[],memberIds:Array.from({length:250},(_,i)=>String(i+1)),hasMoreMember:0};};
  let offset=0,cursor={},found=[];
  for(let i=0;i<3;i++){
    const data=await executeScan(api,{kind:'members',group_id:'900',offset,cursor});found.push(...data.rows.map(row=>row.uid));offset=data.next_offset;cursor=data.cursor;
  }
  assert.equal(new Set(found).size,250);assert.deepEqual(pages,[1,1,1]);
  await assert.rejects(executeScan(api,{kind:'members',group_id:'900',cursor:{source:'unexpected',member_page:1,member_offset:0}}));
});
