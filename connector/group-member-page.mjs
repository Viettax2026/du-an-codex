// Read-only paginated group information, using the existing authenticated SDK.
// Request layout: @softtynet/zca-js 2.3.7, getGroupInfoV2 (MIT).
// See THIRD_PARTY_NOTICES.md. No alternate identity, privilege or setting changes.
export function installGroupMemberPaging(api) {
  if(typeof api.getGroupInfoV2==='function')return;
  api.getGroupInfoV2=async(groupId,{mpage=1,mcount=100}={})=>{
    if(!/^\d{1,30}$/.test(String(groupId)) || !Number.isInteger(mpage) || mpage<1 || mpage>10000 || mcount!==100)throw new Error('Invalid group member page');
    const ctx=typeof api.getContext==='function'?api.getContext():null;
    if(!ctx?.secretKey || !ctx.imei)throw new Error('Group paging context unavailable');
    const base=new URL(api.zpwServiceMap?.group?.[0]);
    if(base.protocol!=='https:' || base.username || base.password || base.port || !['zalo.me','zaloapp.com'].some(host=>base.hostname===host || base.hostname.endsWith('.'+host)))throw new Error('Invalid group service');
    const sdk=await import(new URL('./utils.js',import.meta.resolve('zca-js')).href);
    const params=sdk.encodeAES(ctx.secretKey,JSON.stringify({grid:String(groupId),avatar_size:120,member_avatar_size:120,mpage,mcount,imei:ctx.imei}));
    if(!params)throw new Error('Group paging request unavailable');
    // Match this method's published protocol version without changing the
    // shared session or the version used by any other SDK operation.
    const url=sdk.makeURL(ctx,new URL('/api/group/getgi/v2',base).href,{params,zpw_ver:689});
    return sdk.resolveResponse(ctx,await sdk.request(ctx,url,{method:'GET'}));
  };
}
