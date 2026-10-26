// Read-only Zalo data sources. Only public profile fields leave this module.
const ID=/^\d{1,30}$/;
const text=(value,max=100)=>String(value ?? '').slice(0,max);
const uid=value=>String(value ?? '').replace(/_\d+$/,'');
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
export async function executeScan(api,input) {
  const offset=Number(input.offset || 0),size=100;
  if(!Number.isInteger(offset) || offset<0 || offset>10000 || offset%size)throw new Error('Invalid offset');
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
  const all=[...members.keys()].sort(),page=all.slice(offset,offset+size);
  const details=page.length?await api.getGroupMembersInfo(page):{profiles:{}};
  if(!details?.profiles || typeof details.profiles!=='object')throw new Error('Invalid member profiles');
  const admins=new Set((group.adminIds || []).map(String));
  return {state:'ok',rows:page.map(id=>profile(details.profiles[id] || details.profiles[`${id}_0`] || members.get(id),id,
    String(group.creatorId)===id?'owner':admins.has(id)?'admin':'member')),
    has_more:offset+size<Math.min(all.length,10000),next_offset:offset+size,
    total:Math.max(all.length,Number(group.totalMember)||0),source_name:text(group.name || groupId),
    limited:all.length>10000 || Number(group.totalMember)>all.length || Boolean(group.hasMoreMember)};
}
