(() => {
  const dialog=document.getElementById('data-scan-dialog');if(!dialog)return;
  const $=name=>dialog.querySelector(`[data-scan-${name}]`),csrf=dialog.dataset.csrf;
  let scanId=null,page=1,pages=1,rows=[],selection=new Set(),busy=false,revision=0,queryTimer;
  const roleLabels={friend:'Bạn bè',member:'Thành viên',admin:'Phó nhóm',owner:'Trưởng nhóm',group:'Group',customer:'Khách đã gửi tin'};
  const checkLabels={unchecked:'Chưa kiểm tra',matched:'Khớp UID',mismatch:'Khác UID',not_found:'Không tìm thấy',unavailable:'Chưa kiểm tra được'};
  function message(text,error=false){$('status').textContent=text;$('status').classList.toggle('is-error',error);}
  function updateSelection(){
    $('selection').textContent=`${selection.size} đã tích chọn`;
    $('import').disabled=busy || !selection.size || $('kind').value==='groups' || !$('destination').value;
    $('check').disabled=busy || !scanId || !rows.some(row=>row.phone);
    $('export').disabled=busy || !scanId;
    $('select-page').checked=rows.length>0 && rows.every(row=>selection.has(row.id));
    $('select-page').indeterminate=rows.some(row=>selection.has(row.id)) && !$('select-page').checked;
  }
  function setBusy(value){busy=value;for(const name of ['load','more','load-groups','select-all'])$(name).disabled=value;updateSelection();}
  async function request(url,data){
    const options=data?{method:'POST',body:new URLSearchParams({csrf,...data})}:{cache:'no-store'};
    const response=await fetch(url,options);
    if(response.redirected)throw new Error('Phiên đăng nhập đã hết hạn. Tải lại trang.');
    const result=await response.json();if(!response.ok)throw new Error(result.error || 'Không thực hiện được. Tải lại trang và thử lại.');return result;
  }
  function filters(){return {q:$('query').value,phone:$('phone').value,role:$('role').value};}
  function actionData(){return {...filters(),ids:selection.size?JSON.stringify([...selection]):'',deduplicate:$('dedupe').checked?'yes':'no'};}
  function renderRows(){
    const body=$('rows');body.replaceChildren();
    rows.forEach((row,index)=>{
      const tr=document.createElement('tr'),choice=document.createElement('td'),checkbox=document.createElement('input');
      checkbox.type='checkbox';checkbox.checked=selection.has(row.id);checkbox.setAttribute('aria-label',`Chọn ${row.name}`);
      checkbox.addEventListener('change',()=>{if(checkbox.checked)selection.add(row.id);else selection.delete(row.id);updateSelection();});choice.append(checkbox);tr.append(choice);
      const ordinal=document.createElement('td');ordinal.textContent=(page-1)*100+index+1;tr.append(ordinal);
      const picture=document.createElement('td');
      if(row.avatar){const image=document.createElement('img');image.src=row.avatar;image.alt='';image.loading='lazy';image.referrerPolicy='no-referrer';picture.append(image);}
      else {const initial=document.createElement('span');initial.className='scan-avatar';initial.textContent=row.name.slice(0,1);picture.append(initial);}tr.append(picture);
      [row.name,row.phone || '—',row.uid,roleLabels[row.role] || row.role,row.kind==='group'?row.member_count:'—',row.phone?checkLabels[row.phone_state]:'Chưa có SĐT'].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});
      body.append(tr);
    });
    if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=9;td.textContent='Chưa có dữ liệu hoặc không khớp bộ lọc.';tr.append(td);body.append(tr);}updateSelection();
  }
  async function refresh(){
    if(!scanId)return;
    const current=++revision,id=scanId;
    const data=await request(`/data-scans/${id}/rows?${new URLSearchParams({...filters(),p:page})}`);
    if(current!==revision || id!==scanId)return;
    rows=data.rows;page=data.page;pages=data.pages;
    $('total').textContent=`Tổng ${data.loaded} data${data.scan.total!==null?' / '+data.scan.total+' từ nguồn':''}`;
    $('range').textContent=`Hiển thị ${data.total?(page-1)*100+1:0}–${Math.min(page*100,data.total)}/${data.total} data`;
    $('page').textContent=`Trang ${page}/${pages}`;$('prev').disabled=page<=1;$('next').disabled=page>=pages;
    $('more').hidden=!data.scan.has_more;
    if(data.scan.error)message(data.scan.error,true);
    else if(data.scan.limited)message('Đã lưu phần dữ liệu Zalo cho phép xem. Danh sách có thể chưa đầy đủ hoặc đã chạm giới hạn 10.000 dòng.');
    else message(`Đã lưu kết quả: ${data.scan.source_name}.${data.scan.has_more?' Bấm Tải tiếp để đọc thêm.':' Đã tải hết dữ liệu nguồn trả về.'}`);
    renderRows();
  }
  async function catalog(){
    const data=await request('/data-scans/catalog'),previous=$('account').value;
    $('account').replaceChildren(new Option('Chọn tài khoản',''),...data.accounts.map(account=>new Option(`${account.name} · ${account.connected?'Đã đăng nhập':'Chưa đăng nhập'}`,account.id)));
    if(previous)$('account').value=previous;
    else if(data.accounts.length)$('account').value=String(data.accounts.find(account=>account.connected)?.id || data.accounts[0].id);
    $('saved').replaceChildren(new Option('Chọn kết quả quét trước đó',''),...data.scans.map(scan=>new Option(`#${scan.id} · ${scan.source_name} · ${scan.account_name} (${scan.total})`,scan.id)));
    if(scanId)$('saved').value=String(scanId);
    const destination=$('destination').value || dialog.dataset.destination;
    $('destination').replaceChildren(new Option('Chọn nhóm data',''),...data.groups.map(group=>new Option(group.name,group.id)));
    if(destination)$('destination').value=destination;updateSelection();
  }
  document.querySelectorAll('[data-open-scan]').forEach(button=>button.addEventListener('click',async()=>{
    const menu=button.closest('details');if(menu)menu.open=false;dialog.showModal();
    try{await catalog();if(scanId)await refresh();}catch(error){message(error.message,true);}
  }));
  dialog.querySelectorAll('[data-scan-close]').forEach(button=>button.addEventListener('click',()=>dialog.close()));
  $('kind').addEventListener('change',()=>{$('group-controls').hidden=$('kind').value!=='members';updateSelection();});
  $('account').addEventListener('change',()=>{$('remote-group').replaceChildren(new Option('Tải và chọn group Zalo',''));});
  $('load-groups').addEventListener('click',async()=>{
    if(busy)return;if(!$('account').value){message('Chọn tài khoản Zalo trước khi tải group.',true);return;}setBusy(true);const account=$('account').value;message('Đang tải group đã tham gia…');
    try{
      let offset=0,all=[];
      do {const data=await request('/data-scans/groups',{account_id:account,offset});all.push(...data.rows);offset=data.next_offset;if(!data.has_more)break;}while(offset<10000);
      if(account!==$('account').value)return;
      $('remote-group').replaceChildren(new Option('Chọn group Zalo',''),...all.map(group=>new Option(`${group.name} (${group.member_count})`,group.uid)));
      message(`Đã tải ${all.length} group. Chọn group rồi bấm Tải data.`);
    }catch(error){message(error.message,true);}finally{setBusy(false);}
  });
  $('load').addEventListener('click',async()=>{
    if(busy)return;if(!$('account').value){message('Chọn tài khoản Zalo trước khi tải dữ liệu.',true);return;}setBusy(true);message('Đang tải dữ liệu từ nguồn đã chọn…');
    try{
      const data=await request('/data-scans/start',{kind:$('kind').value,account_id:$('account').value,remote_group:$('remote-group').value});
      scanId=data.scan_id;selection.clear();page=1;$('query').value='';$('phone').value='';$('role').value='';await catalog();await refresh();
    }catch(error){message(error.message,true);try{await catalog();}catch{}}finally{setBusy(false);}
  });
  $('saved').addEventListener('change',async()=>{
    if(!$('saved').value)return;scanId=Number($('saved').value);selection.clear();page=1;
    try{const data=await request(`/data-scans/${scanId}/rows`);$('kind').value=data.scan.kind;$('account').value=String(data.scan.account_id);$('group-controls').hidden=data.scan.kind!=='members';await refresh();}catch(error){message(error.message,true);}
  });
  $('more').addEventListener('click',async()=>{if(busy || !scanId)return;setBusy(true);try{await request(`/data-scans/${scanId}/more`,{});await refresh();}catch(error){message(error.message,true);}finally{setBusy(false);}});
  for(const name of ['phone','role'])$(name).addEventListener('change',()=>{selection.clear();page=1;refresh().catch(error=>message(error.message,true));});
  $('query').addEventListener('input',()=>{clearTimeout(queryTimer);queryTimer=setTimeout(()=>{selection.clear();page=1;refresh().catch(error=>message(error.message,true));},250);});
  $('prev').addEventListener('click',()=>{page=Math.max(1,page-1);refresh().catch(error=>message(error.message,true));});
  $('next').addEventListener('click',()=>{page=Math.min(pages,page+1);refresh().catch(error=>message(error.message,true));});
  $('select-page').addEventListener('change',()=>{for(const row of rows){if($('select-page').checked)selection.add(row.id);else selection.delete(row.id);}renderRows();});
  $('clear').addEventListener('click',()=>{selection.clear();renderRows();});
  $('select-all').addEventListener('click',async()=>{
    if(!scanId || busy)return;setBusy(true);
    try{const data=await request(`/data-scans/${scanId}/ids?${new URLSearchParams(filters())}`);selection=new Set(data.ids);renderRows();}catch(error){message(error.message,true);}finally{setBusy(false);}
  });
  $('destination').addEventListener('change',updateSelection);
  $('export').addEventListener('click',async()=>{
    if(busy || !scanId)return;setBusy(true);
    try{const response=await fetch(`/data-scans/${scanId}/export`,{method:'POST',body:new URLSearchParams({csrf,...actionData()})});
      if(!response.ok || response.redirected){let text='Không xuất được Excel.';try{text=(await response.json()).error || text;}catch{}throw new Error(text);}
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`data-quet-${scanId}.xlsx`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){message(error.message,true);}finally{setBusy(false);}
  });
  $('import').addEventListener('click',async()=>{
    if(busy || !scanId || !selection.size)return;setBusy(true);
    try{const data=await request(`/data-scans/${scanId}/import`,{...actionData(),group_id:$('destination').value,consent:$('consent').checked?'yes':''});message(`Đã thêm ${data.added} SĐT vào nhóm “${data.group}”. ${data.skipped} dòng không đủ điều kiện. Mở lại nhóm để xem dữ liệu mới.`);}
    catch(error){message(error.message,true);}finally{setBusy(false);}
  });
  $('check').addEventListener('click',async()=>{
    if(busy || !scanId)return;setBusy(true);
    try{const data=await request(`/data-scans/${scanId}/phone-ids?${new URLSearchParams(filters())}`);const ids=data.ids.filter(id=>!selection.size || selection.has(id));
      if(!ids.length)throw new Error('Không có SĐT công khai trong phần đã chọn.');
      let done=0;
      for(const id of ids){if(!dialog.open)break;message(`Đang kiểm tra SĐT ${done+1}/${ids.length}…`);const result=await request(`/data-scans/${scanId}/check-phone`,{row_id:id});done++;if(result.rate_limited){message('Zalo đang giới hạn tra cứu. Đã dừng kiểm tra SĐT.',true);return;}}
      await refresh();message(`Đã kiểm tra ${done} SĐT. Không gửi tin nhắn hoặc lời mời kết bạn.`);
    }catch(error){message(error.message,true);}finally{setBusy(false);}
  });
  updateSelection();
})();
