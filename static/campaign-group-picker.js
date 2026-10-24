(() => {
  const dialog = document.querySelector('#campaign-group-dialog');
  const form = document.querySelector('.campaign-wizard');
  if (!dialog || !form) return;
  const container = dialog.querySelector('[data-campaign-group-options]');
  const search = dialog.querySelector('[data-campaign-group-search]');
  const status = dialog.querySelector('[data-campaign-group-status]');
  const choose = dialog.querySelector('[data-choose-campaign-group]');
  const refresh = dialog.querySelector('[data-reload-campaign-groups]');
  const confirmConsent = dialog.querySelector('[data-confirm-group-consent]');
  const preview = form.querySelector('[data-group-snapshot-preview]');
  const ids = form.querySelector('[data-group-snapshot-ids]');
  const selected = new Map(JSON.parse(preview.dataset.initialGroupSnapshot).map(row => [row.id,row]));
  const number = value => Number(value).toLocaleString('vi-VN');
  let groups = [], limit = 10000, epoch = 0, page = 1;
  function message(text, error=false) { status.textContent=text; status.classList.toggle('is-error',error); }
  function updateSnapshot() {
    const rows = [...selected.values()];
    ids.value = JSON.stringify(rows.map(row => row.id));
    preview.hidden = rows.length===0;
    page = Math.max(1,Math.min(page,Math.ceil(rows.length/50) || 1));
    preview.querySelector('[data-group-snapshot-summary]').textContent = `${number(rows.length)} data đã thêm từ nhóm`;
    const body = preview.querySelector('[data-group-snapshot-rows]'); body.replaceChildren();
    rows.slice((page-1)*50,page*50).forEach((row,index) => {
      const tr = document.createElement('tr');
      [String((page-1)*50+index+1),row.name,row.phone].forEach(value => { const td=document.createElement('td');td.textContent=value;tr.append(td); });
      const td=document.createElement('td'), remove=document.createElement('button');
      remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Bỏ ${row.phone} khỏi danh sách đang nhập`);
      remove.addEventListener('click',()=>{ selected.delete(row.id); updateSnapshot(); });
      td.append(remove);tr.append(td);body.append(tr);
    });
    preview.querySelector('[data-group-snapshot-page]').textContent = `Trang ${page}/${Math.max(1,Math.ceil(rows.length/50))}`;
    preview.querySelector('[data-group-snapshot-prev]').disabled = page<=1;
    preview.querySelector('[data-group-snapshot-prev]').dataset.snapshotDisabled = String(page<=1);
    preview.querySelector('[data-group-snapshot-next]').disabled = page*50>=rows.length;
    preview.querySelector('[data-group-snapshot-next]').dataset.snapshotDisabled = String(page*50>=rows.length);
    ids.dispatchEvent(new Event('change',{bubbles:true}));
  }
  preview.querySelector('[data-group-snapshot-prev]').addEventListener('click',()=>{page-=1;updateSnapshot();});
  preview.querySelector('[data-group-snapshot-next]').addEventListener('click',()=>{page+=1;updateSnapshot();});
  form.addEventListener('campaign-clear-snapshot',()=>{selected.clear();page=1;updateSnapshot();});
  function filterGroups() {
    const query = search.value.trim().toLocaleLowerCase('vi'); let visible=0;
    container.querySelectorAll('[data-group-name]').forEach(row => {
      row.hidden = !row.dataset.groupName.includes(query);
      if (!row.hidden) visible+=1;
      else if (row.querySelector('input').checked) {row.querySelector('input').checked=false;choose.disabled=true;confirmConsent.hidden=true;}
    });
    if (groups.length) message(visible ? 'Chỉ thêm khách hàng đã đồng ý nhận tin; số trùng sẽ được gộp.' : 'Không có nhóm khớp từ khóa.');
  }
  function renderGroups(selectedId=null) {
    container.replaceChildren();choose.disabled=true;confirmConsent.hidden=true;
    if (!groups.length) {
      const empty=document.createElement('p');empty.className='group-picker-empty';empty.textContent='Chưa có nhóm data. Tạo nhóm và thêm data trong mục Nhóm data.';container.append(empty);return;
    }
    groups.forEach(group => {
      const label=document.createElement('label');label.className='campaign-group-choice';label.dataset.groupName=group.name.toLocaleLowerCase('vi');
      const input=document.createElement('input');input.type='radio';input.name='campaign-group-choice';input.value=String(group.id);
      input.addEventListener('change',()=>{
        choose.disabled=group.eligible===0 || group.eligible>limit;
        confirmConsent.hidden=group.eligible>=group.total;
        confirmConsent.textContent=`Xác nhận đồng ý nhận tin cho ${number(group.total-group.eligible)} khách trong nhóm`;
        message(group.eligible===0 ? 'Trạng thái đồng ý của nhóm chưa được cập nhật. Bạn có thể xác nhận ngay bên dưới.' : group.eligible>limit ? `Nhóm vượt ${number(limit)} khách hàng đồng ý nhận tin. Chia nhóm nhỏ hơn để thêm.` : `Sẽ thêm ${number(group.eligible)} khách hàng đã đồng ý nhận tin.`,choose.disabled);
      });
      const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','1.7');icon.setAttribute('aria-hidden','true');
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v1M3 8h18l-3 12H3a1 1 0 0 1-1-1Z');icon.append(path);
      const text=document.createElement('span'), title=document.createElement('b'), details=document.createElement('small');title.textContent=group.name;
      details.textContent=`${({all:'Mọi loại dữ liệu',phone:'Số điện thoại',uid:'UID'})[group.data_type] || 'Mọi loại dữ liệu'} · ${number(group.total)} thành viên · ${number(group.eligible)} đồng ý nhận tin`;
      text.append(title,details);label.append(input,icon,text);container.append(label);
    });
    filterGroups();
    const restored=[...container.querySelectorAll('input')].find(input=>input.value===String(selectedId));
    if(restored){restored.checked=true;restored.dispatchEvent(new Event('change'));}
  }
  async function load(selectedId=null) {
    const request = ++epoch;choose.disabled=true;refresh.disabled=true;container.replaceChildren();confirmConsent.hidden=true;message('Đang tải nhóm data…');
    try {
      const response=await fetch(dialog.dataset.groupOptionsUrl,{headers:{Accept:'application/json'}});
      const result=await response.json();
      if (!response.ok) throw new Error(result.error || 'Không tải được nhóm data.');
      if (request!==epoch || !dialog.open) return;
      groups=result.groups;limit=result.limit;renderGroups(selectedId);
      if (!groups.length) message('Chưa có nhóm data để chọn.');
    } catch(error) {
      if (request===epoch && dialog.open) message(error instanceof SyntaxError ? 'Phiên làm việc hết hạn. Lưu nội dung đang nhập rồi đăng nhập lại.' : error.message,true);
    } finally {if(request===epoch)refresh.disabled=false;}
  }
  form.querySelector('[data-show-groups]').addEventListener('click',()=>{dialog.showModal();load();});
  dialog.querySelectorAll('[data-close-campaign-group]').forEach(button=>button.addEventListener('click',()=>dialog.close()));
  dialog.addEventListener('close',()=>{epoch+=1;refresh.disabled=false;choose.disabled=true;});
  refresh.addEventListener('click',()=>load());search.addEventListener('input',filterGroups);
  confirmConsent.addEventListener('click',async()=>{
    const group=container.querySelector('input:checked');if(!group)return;
    const groupId=group.value, request=++epoch;confirmConsent.disabled=true;choose.disabled=true;refresh.disabled=true;
    const data=new FormData();data.set('csrf',form.elements.csrf.value);data.set('group_id',groupId);data.set('confirm_consent','yes');
    try{
      const response=await fetch(dialog.dataset.groupConsentUrl,{method:'POST',body:data,headers:{Accept:'application/json'}});
      const result=await response.json();if(!response.ok)throw new Error(result.error || 'Chưa cập nhật được trạng thái đồng ý.');
      if(request===epoch && dialog.open)await load(groupId);
    }catch(error){if(request===epoch && dialog.open)message(error instanceof SyntaxError ? 'Phiên làm việc hết hạn. Tải lại trang và đăng nhập lại.' : error.message,true);}
    finally{confirmConsent.disabled=false;if(request===epoch)refresh.disabled=false;}
  });
  choose.addEventListener('click',async()=>{
    const group=container.querySelector('input:checked');if(!group)return;
    const request=++epoch;choose.disabled=true;refresh.disabled=true;message('Đang thêm data từ nhóm…');
    const data=new FormData();data.set('csrf',form.elements.csrf.value);data.set('group_id',group.value);
    try {
      const response=await fetch(dialog.dataset.groupSnapshotUrl,{method:'POST',body:data,headers:{Accept:'application/json'}});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error || 'Chưa thêm được data từ nhóm.');
      if(request!==epoch || !dialog.open)return;
      const merged=new Set([...selected.keys(),...result.rows.map(row=>row.id)]);
      if(merged.size>limit)throw new Error(`Danh sách từ nhóm vượt ${number(limit)} khách hàng. Bỏ bớt data trước khi thêm.`);
      result.rows.forEach(row=>selected.set(row.id,row));page=1;updateSnapshot();dialog.close();
      preview.scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch(error) {if(request===epoch && dialog.open)message(error instanceof SyntaxError ? 'Phiên làm việc hết hạn. Lưu nội dung đang nhập rồi đăng nhập lại.' : error.message,true);}
    finally{if(request===epoch){refresh.disabled=false;choose.disabled=false;}}
  });
  updateSnapshot();
})();
