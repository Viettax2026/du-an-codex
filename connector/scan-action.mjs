// Read-only Zalo data sources. Only public profile fields leave this module.
const ID=/^\d{1,30}$/;
const text=(value,max=100)=>String(value ?? '').slice(0,max);
const uid=value=>String(value ?? '').replace(/_\d+$/,'');
const flag=value=>value===true || value===1 || value==='1';
function avatar(value) {
  try {const url=new URL(String(value));return url.protocol==='https:' && !url.username && !url.password ? url.href.slice(0,1500) : '';}
  catch {return '';}
}
function profile(value,id,role='member') {
  return {uid:id,name:text(value?.displayName || value?.dName || value?.zaloName || value?.username || id),
    phone:text(value?.phoneNumber || '',30),avatar:avatar(value?.avatar),role,kind:'user',member_count:0};
}
export async function joinedGroupIds(api) {
  const data=await api.getAllGroups();
  if(!data?.gridVerMap || typeof data.gridVerMap!=='object' || Array.isArray(data.gridVerMap))throw new Error('Invalid groups');
  return Object.keys(data.gridVerMap).filter(id=>ID.test(id)).sort();
}
export async function assertJoinedGroup(api,id) {
  if(!ID.test(String(id)) || !(await joinedGroupIds(api)).includes(String(id)))throw new Error('Group not joined');
}
function errorCode(error) {
  const code=String(error?.code ?? error?.cause?.code ?? '');
  return /^-?\d{1,8}$/.test(code)?code:'';
}
function memberProfiles(data,includeIds=false) {
  const profiles=new Map();
  if(includeIds){
    for(const field of ['memVerList','memberIds']){
      if(data[field]!==undefined && !Array.isArray(data[field]))throw new Error('Invalid paged member IDs');
      for(const entry of data[field] || []){const id=uid(entry);if(ID.test(id))profiles.set(id,{});}
    }
  }
  for(const member of data.currentMems){const id=uid(member?.id);if(ID.test(id))profiles.set(id,member);}
  return profiles;
}
async function pagedMembers(api,input,group,total,viewerRole,hidden,diagnostics,knownMembers) {
  const cursor=input.cursor || {},continuing=cursor.source==='group_info_v2';
  if(typeof api.getGroupInfoV2!=='function'){diagnostics.paged_status='sdk_unavailable';if(continuing)throw new Error('Group paging unavailable');return null;}
  const memberPage=continuing?cursor.member_page:1,start=continuing?cursor.member_offset:0;
  diagnostics.paged_page=memberPage;
  let data;
  try {data=await api.getGroupInfoV2(String(input.group_id),{mpage:memberPage,mcount:100});}
  catch(error){diagnostics.paged_status='page_error';diagnostics.paged_error_code=errorCode(error);if(continuing)throw error;return null;}
  if(String(data?.groupId)!==String(input.group_id) || !Array.isArray(data.currentMems))throw new Error('Invalid paged group response');
  const profiles=memberProfiles(data,true);
  Object.assign(diagnostics,{paged_status:profiles.size?'ok':'empty',paged_raw_count:data.currentMems.length,paged_valid_count:profiles.size,paged_more:flag(data.hasMoreMember)});
  const reported=Number(data.totalMember),expected=Math.max(total,Number.isFinite(reported)?reported:0);
  if(!continuing && !flag(data.hasMoreMember) && profiles.size<expected){
    // Keep additional authorized IDs even when this source is also partial.
    for(const [id,member] of profiles)knownMembers.set(id,member);
    return null;
  }
  return memberPageResult(api,input,group,total,viewerRole,hidden,diagnostics,knownMembers,data,profiles,'group_info_v2',memberPage,start);
}
async function linkedMembers(api,input,group,total,viewerRole,hidden,diagnostics,knownMembers) {
  const cursor=input.cursor || {},continuing=cursor.source==='group_link';
  if(typeof api.getGroupLinkDetail!=='function' || typeof api.getGroupLinkInfo!=='function'){
    diagnostics.link_status='sdk_unavailable';
    if(continuing)throw new Error('Group link reading unavailable');
    return null;
  }
  let detail;
  try {detail=await api.getGroupLinkDetail(String(input.group_id));}
  catch(error){diagnostics.link_status='detail_error';diagnostics.error_code=errorCode(error);if(continuing)throw error;return null;}
  let link;
  if(!flag(detail?.enabled)){
    diagnostics.link_status=[0,'0',false].includes(detail?.enabled)?'disabled':'missing_link';
    if(continuing)throw new Error('Group link unavailable');
    return null;
  }
  try {link=new URL(detail?.link);}catch {diagnostics.link_status='missing_link';if(continuing)throw new Error('Group link unavailable');return null;}
  if(link.protocol!=='https:' || link.hostname!=='zalo.me' || link.port || link.username || link.password || !/^\/g\/[a-z0-9]+\/?$/i.test(link.pathname)){
    diagnostics.link_status='invalid_link';
    if(continuing)throw new Error('Group link unavailable');
    return null;
  }
  const memberPage=continuing?cursor.member_page:1,start=continuing?cursor.member_offset:0;
  diagnostics.link_page=memberPage;
  let data;
  try {data=await api.getGroupLinkInfo({link:link.href,memberPage});}
  catch(error){diagnostics.link_status='page_error';diagnostics.error_code=errorCode(error);if(continuing)throw error;return null;}
  if(String(data?.groupId)!==String(input.group_id) || !Array.isArray(data.currentMems))throw new Error('Invalid linked group response');
  const profiles=memberProfiles(data);
  Object.assign(diagnostics,{link_status:profiles.size?'ok':'empty',link_raw_count:data.currentMems.length,link_valid_count:profiles.size,link_more:flag(data.hasMoreMember)});
  // An empty link preview must not discard profiles available in group info.
  if(!continuing && !profiles.size && diagnostics.group_info_ids>0)return null;
  return memberPageResult(api,input,group,total,viewerRole,hidden,diagnostics,knownMembers,data,profiles,'group_link',memberPage,start);
}
async function memberPageResult(api,input,group,total,viewerRole,hidden,diagnostics,knownMembers,data,profiles,source,memberPage,start) {
  const profileIds=new Set(profiles.keys());
  // Merge known IDs into the first native page, including its continuation chunks.
  // A smaller link preview must never replace the group-info member list.
  if(memberPage===1){
    for(const id of [...knownMembers.keys()].sort())if(!profiles.has(id))profiles.set(id,knownMembers.get(id));
    diagnostics.merged_first_page_count=profiles.size;
  }
  const list=[...profiles.entries()];
  if(start>list.length)throw new Error('Invalid linked group cursor');
  const page=list.slice(start,start+100),withinPage=start+100<list.length;
  const missing=page.map(([id])=>id).filter(id=>!profileIds.has(id) || !profiles.get(id)?.dName && !profiles.get(id)?.displayName && !profiles.get(id)?.zaloName);
  let details={};
  if(missing.length){
    diagnostics.profile_status='unavailable';
    if(typeof api.getGroupMembersInfo==='function'){
      try {
        const response=await api.getGroupMembersInfo(missing);
        if(!response?.profiles || typeof response.profiles!=='object' || Array.isArray(response.profiles))throw new Error('Invalid member profiles');
        details=response.profiles;diagnostics.profile_status='ok';
      } catch(error){diagnostics.profile_status='error';diagnostics.profile_error_code=errorCode(error);}
    }
  }
  const hasMore=withinPage || flag(data.hasMoreMember);
  const offset=Number(input.offset || 0)+Math.max(1,page.length),atLimit=hasMore && offset>=10000;
  const admins=new Set((data.adminIds || group.adminIds || []).map(String));
  const sourceTotal=Number(data.totalMember);
  return {state:'ok',rows:page.map(([id,member])=>profile(details[id] || details[`${id}_0`] || member,id,String(data.creatorId || group.creatorId)===id?'owner':admins.has(id)?'admin':'member')),
    next_offset:offset,has_more:hasMore && !atLimit,total:Math.max(total,list.length,Number.isFinite(sourceTotal)?Math.max(0,Math.floor(sourceTotal)):0),
    source_name:text(group.name || input.group_id),accessible_total:null,limited:atLimit,
    limit_reason:atLimit?'scan_limit':'',viewer_role:viewerRole,member_source:source,members_hidden:hidden,
    cursor:hasMore && !atLimit?{source,member_page:withinPage?memberPage:memberPage+1,member_offset:withinPage?start+100:0}:{},diagnostics};
}
export async function executeScan(api,input) {
  const offset=Number(input.offset || 0),size=100;
  const cursor=input.cursor || {},fromLink=cursor.source==='group_link',fromPaged=cursor.source==='group_info_v2',memberCursor=fromLink || fromPaged;
  if(cursor.source && !memberCursor || memberCursor && (input.kind!=='members' || !Number.isInteger(cursor.member_page) || cursor.member_page<1 || cursor.member_page>10000 || !Number.isInteger(cursor.member_offset) || cursor.member_offset<0 || cursor.member_offset>10000))throw new Error('Invalid member cursor');
  if(!Number.isInteger(offset) || offset<0 || offset>10000 || !memberCursor && offset%size)throw new Error('Invalid offset');
  if(input.kind==='friends') {
    const source=await api.getAllFriends(size,offset/size+1);
    if(!Array.isArray(source))throw new Error('Invalid friends');
    const rows=source.slice(0,size).filter(row=>ID.test(String(row.userId))).map(row=>profile(row,String(row.userId),'friend'));
    return {state:'ok',rows,has_more:source.length>=size && offset+size<10000,next_offset:offset+size,total:null,
      limited:offset+size>=10000 && source.length>=size,source_name:'Danh sách bạn bè'};
  }
  if(!['groups','members'].includes(input.kind))throw new Error('Invalid source');
  const ids=await joinedGroupIds(api);
  if(input.kind==='groups') {
    const page=ids.slice(offset,offset+size);
    const info=page.length?await api.getGroupInfo(page):{gridInfoMap:{}};
    if(!info?.gridInfoMap)throw new Error('Invalid group information');
    return {state:'ok',rows:page.map(id=>{
      const group=info.gridInfoMap[id];if(!group)throw new Error('Incomplete group information');
      return {uid:id,name:text(group.name || id),phone:'',avatar:avatar(group.avt || group.fullAvt),role:'group',kind:'group',
        member_count:Math.max(0,Math.min(1000000,Number(group.totalMember)||0))};
    }),has_more:offset+size<Math.min(ids.length,10000),next_offset:offset+size,total:ids.length,
      limited:ids.length>10000,source_name:'Danh sách group đã tham gia'};
  }
  const groupId=String(input.group_id || '');
  if(!ID.test(groupId) || !ids.includes(groupId))throw new Error('Group not joined');
  const response=await api.getGroupInfo(groupId),group=response?.gridInfoMap?.[groupId];
  if(!group)throw new Error('Invalid group information');
  const members=new Map();
  for(const entry of group.memVerList || []) {const id=uid(entry);if(ID.test(id))members.set(id,{});}
  for(const entry of group.memberIds || []) {const id=uid(entry);if(ID.test(id))members.set(id,members.get(id)||{});}
  for(const entry of group.currentMems || []) {const id=uid(entry.id);if(ID.test(id))members.set(id,entry);}
  let all=[...members.keys()].sort();
  const admins=new Set((group.adminIds || []).map(String));
  const selfId=typeof api.getOwnId==='function'?String(api.getOwnId()):'';
  const viewerRole=!ID.test(selfId)?'unknown':String(group.creatorId)===selfId?'owner':admins.has(selfId)?'admin':'member';
  const reported=Number(group.totalMember);
  const total=Math.max(all.length,Number.isFinite(reported)?Math.max(0,Math.floor(reported)):0);
  const incomplete=total>all.length || (!Number.isFinite(reported) || reported<=0) && flag(group.hasMoreMember);
  const hidden=flag(group.setting?.lockViewMember);
  const diagnostics={version:1,group_type:group.type===1 || group.type===2?group.type:0,
    group_info_ids:all.length,mem_ver_count:Array.isArray(group.memVerList)?group.memVerList.length:0,
    member_id_count:Array.isArray(group.memberIds)?group.memberIds.length:0,preview_count:Array.isArray(group.currentMems)?group.currentMems.length:0,
    link_status:'not_needed',paged_status:'not_needed'};
  if(incomplete && !fromLink || fromPaged){
    const paged=await pagedMembers(api,input,group,total,viewerRole,hidden,diagnostics,members);
    if(paged)return paged;
  }
  if(incomplete || fromLink){
    const linked=await linkedMembers(api,input,group,total,viewerRole,hidden,diagnostics,members);
    if(linked)return linked;
  }
  all=[...members.keys()].sort();
  const page=all.slice(offset,offset+size);
  const details=page.length?await api.getGroupMembersInfo(page):{profiles:{}};
  if(!details?.profiles || typeof details.profiles!=='object')throw new Error('Invalid member profiles');
  const limitReason=incomplete?(hidden?'hidden_members':'incomplete_members'):all.length>10000?'scan_limit':'';
  return {state:'ok',rows:page.map(id=>profile(details.profiles[id] || details.profiles[`${id}_0`] || members.get(id),id,
    String(group.creatorId)===id?'owner':admins.has(id)?'admin':'member')),
    has_more:offset+size<Math.min(all.length,10000),next_offset:offset+size,
    total,source_name:text(group.name || groupId),accessible_total:all.length,
    limited:Boolean(limitReason),limit_reason:limitReason,viewer_role:viewerRole,member_source:'group_info',members_hidden:hidden,cursor:{},diagnostics};
}
