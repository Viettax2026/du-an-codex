(() => {
  const root=document.querySelector('[data-group-data-manager]');if(!root)return;
  const $=key=>root.querySelector(`[data-collection-${key}]`),csrf=root.dataset.csrf;
  let groups=[],selected=null,rows=[],choices=new Set(),generation=0,busy=false;
  async function api(url,data){const response=await fetch(url,data?{method:'POST',body:new URLSearchParams({csrf,...data})}:{cache:'no-store'});if(response.redirected)throw new Error('Phiên đăng nhập đã hết hạn. Tải lại trang.');const body=await response.json();if(!response.ok)throw new Error(body.error || 'Không thực hiện được.');return body;}
  const message=text=>$('status').textContent=text;
  async function refresh(){
    const account=$('account').value;
    const data=await api(`/group-data/catalog?${new URLSearchParams(account?{account_id:account}:{})}`);
    $('account').replaceChildren(new Option('Chọn tài khoản',''),...data.accounts.map(row=>new Option(row.name,row.id)));$('account').value=account || String(data.accounts[0]?.id || '');
    if(!account && $('account').value)return refresh();
    groups=data.groups;const body=$('list');body.replaceChildren();
    for(const group of groups){const button=document.createElement('button');button.type='button';button.className='collection-button';button.classList.toggle('is-active',group.id===selected);const title=document.createElement('b'),count=document.createElement('span');title.textContent=group.name;count.textContent=group.total;button.append(title,count);button.addEventListener('click',()=>{selected=group.id;refresh().catch(error=>message(error.message));});body.append(button);}
    if(!groups.some(group=>group.id===selected))selected=groups[0]?.id || null;
    await showMembers();
  }
  async function showMembers(){
    const current=++generation,id=selected,account=$('account').value,body=$('rows');body.replaceChildren();
    $('title').textContent=groups.find(group=>group.id===id)?.name || 'Chọn nhóm data';
    for(const name of ['add','rename','delete'])$(name).disabled=!id || !account;
    if(!id || !account)return;
    const data=await api(`/group-data/${id}/members?account_id=${encodeURIComponent(account)}`);if(current!==generation)return;
    for(const row of data.rows){const tr=document.createElement('tr');for(const value of [row.name,row.uid,row.tags || '—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}const td=document.createElement('td'),remove=document.createElement('button');remove.type='button';remove.className='ghost';remove.textContent='Xóa';remove.setAttribute('aria-label',`Xóa group ${row.name}`);remove.addEventListener('click',async()=>{try{await api(`/group-data/${id}/remove/${row.membership_id}`,{});await refresh();}catch(error){message(error.message);}});td.append(remove);tr.append(td);body.append(tr);}
    if(!data.rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='Nhóm chưa có group của tài khoản này.';tr.append(td);body.append(tr);}
    root.querySelectorAll('.collection-button').forEach((button,index)=>button.classList.toggle('is-active',groups[index]?.id===selected));
  }
  root.querySelector('[data-create-collection]').addEventListener('submit',async event=>{event.preventDefault();const input=event.target.querySelector('input');try{const data=await api('/group-data/new',{name:input.value,account_id:$('account').value});selected=data.id;input.value='';await refresh();}catch(error){message(error.message);}});
  $('account').addEventListener('change',()=>{generation++;$('picker').close();refresh().catch(error=>message(error.message));});
  $('rename').addEventListener('click',async()=>{const name=window.prompt('Tên nhóm data mới',groups.find(group=>group.id===selected)?.name || '');if(name===null)return;try{await api(`/group-data/${selected}/rename`,{name});await refresh();}catch(error){message(error.message);}});
  $('delete').addEventListener('click',async()=>{if(!window.confirm('Xóa nhóm data này? Các chiến dịch đang dùng nhóm sẽ giữ danh sách group hiện có.'))return;try{await api(`/group-data/${selected}/delete`,{});selected=null;await refresh();}catch(error){message(error.message);}});
  function renderPicker(){const body=$('picker-rows');body.replaceChildren();for(const row of rows){const tr=document.createElement('tr'),td=document.createElement('td'),input=document.createElement('input');input.type='checkbox';input.checked=choices.has(row.id);input.setAttribute('aria-label',`Chọn group ${row.name}`);input.addEventListener('change',()=>{if(input.checked)choices.add(row.id);else choices.delete(row.id);updateSelection();});td.append(input);tr.append(td);for(const value of [row.name,row.uid]){const cell=document.createElement('td');cell.textContent=value;tr.append(cell);}body.append(tr);}updateSelection();}
  function updateSelection(){$('picker-status').textContent=`${rows.length} group · ${choices.size} đã chọn`;$('select-all').checked=rows.length>0 && rows.every(row=>choices.has(row.id));$('insert').disabled=busy || !choices.size;}
  $('select-all').addEventListener('change',()=>{choices=$('select-all').checked?new Set(rows.map(row=>row.id)):new Set();renderPicker();});
  $('add').addEventListener('click',async()=>{rows=[];choices.clear();renderPicker();$('picker').showModal();try{const data=await api('/data-scans/catalog');$('scan').replaceChildren(new Option('Chọn kết quả quét group',''),...data.scans.filter(scan=>scan.kind==='groups' && String(scan.account_id)===$('account').value).map(scan=>new Option(`${scan.source_name} (${scan.total})`,scan.id)));}catch(error){$('picker-status').textContent=error.message;}});
  root.querySelectorAll('[data-collection-close]').forEach(button=>button.addEventListener('click',()=>{$('picker').close();generation++;}));
  async function loadRows(scanId){
    const current=++generation,account=$('account').value;busy=true;updateSelection();rows=[];choices.clear();
    try{let data=await api(`/data-scans/${scanId}/rows`);if(data.scan.kind!=='groups' || String(data.scan.account_id)!==account)throw new Error('Chọn kết quả quét group của đúng tài khoản.');for(let page=1;page<=data.pages;page++){const part=page===1?data:await api(`/data-scans/${scanId}/rows?p=${page}`);if(current!==generation)return;rows.push(...part.rows);}renderPicker();}finally{busy=false;updateSelection();}
  }
  $('scan').addEventListener('change',()=>{if($('scan').value)loadRows($('scan').value).catch(error=>$('picker-status').textContent=error.message);});
  $('load-live').addEventListener('click',async()=>{if(busy)return;busy=true;$('picker-status').textContent='Đang tải group…';const account=$('account').value;try{const result=await api('/data-scans/start',{kind:'groups',account_id:account});let data=await api(`/data-scans/${result.scan_id}/rows`);while(data.scan.has_more && $('picker').open && $('account').value===account){await api(`/data-scans/${result.scan_id}/more`,{});data=await api(`/data-scans/${result.scan_id}/rows`);}if($('account').value===account && $('picker').open)await loadRows(result.scan_id);}catch(error){$('picker-status').textContent=error.message;}finally{busy=false;updateSelection();}});
  $('insert').addEventListener('click',async()=>{if(busy || !choices.size)return;try{const data=await api(`/group-data/${selected}/add`,{account_id:$('account').value,group_scan_row_ids:JSON.stringify([...choices])});$('picker').close();await refresh();message(`Đã thêm ${data.added} group vào nhóm data.`);}catch(error){$('picker-status').textContent=error.message;}});
  refresh().catch(error=>message(error.message));
})();
