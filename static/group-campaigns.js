(() => {
  document.querySelectorAll('.campaign-wizard select[name="action"]').forEach(select=>select.addEventListener('change',()=>{
    if(select.value!=='group_message')return;
    const form=select.closest('form'),params=new URLSearchParams({name:form.elements.name.value,account_id:form.elements.account_id.value});
    location.href=`/group-campaigns/new?${params}`;
  }));
  const form=document.querySelector('[data-group-campaign-form]');if(!form)return;
  const find=name=>document.querySelector(`[data-${name}]`),csrf=form.dataset.csrf;
  const picker=find('zalo-group-picker'),sender=form.elements.account_id;
  let targets=new Map(),targetPage=1,sourceRows=new Map(),choices=new Set(),scanId=null,loadedPages=0,more=false,busy=false;
  try{for(const row of JSON.parse(find('initial-group-targets').textContent))targets.set(row.uid,row);}catch{}
  const status=text=>{find('group-form-status').textContent=text;};
  async function api(url,data){
    const response=await fetch(url,data?{method:'POST',body:new URLSearchParams({csrf,...data})}:{cache:'no-store'});
    if(response.redirected)throw new Error('Phiên đăng nhập đã hết hạn. Tải lại trang.');
    const result=await response.json();if(!response.ok)throw new Error(result.error || 'Không tải được group.');return result;
  }
  function updateTargets(){
    const list=[...targets.values()],pages=Math.max(1,Math.ceil(list.length/50));targetPage=Math.max(1,Math.min(targetPage,pages));
    find('group-target-ids').value=JSON.stringify(list.map(row=>row.id));find('group-target-count').textContent=list.length;
    find('target-page').textContent=`Trang ${targetPage}/${pages}`;find('target-prev').disabled=targetPage<=1;find('target-next').disabled=targetPage>=pages;
    const body=find('group-target-rows');body.replaceChildren();
    list.slice((targetPage-1)*50,targetPage*50).forEach((row,index)=>{
      const tr=document.createElement('tr');[(targetPage-1)*50+index+1,row.name,row.uid].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});
      const td=document.createElement('td'),remove=document.createElement('button');remove.type='button';remove.className='ghost';remove.textContent='Xóa';remove.setAttribute('aria-label',`Xóa group ${row.name}`);remove.addEventListener('click',()=>{targets.delete(row.uid);updateTargets();});td.append(remove);tr.append(td);body.append(tr);
    });
    if(!list.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='Chọn group Zalo hoặc thêm từ kết quả quét group đã lưu.';tr.append(td);body.append(tr);}
  }
  function renderPicker(){
    const query=find('pick-query').value.toLocaleLowerCase('vi'),body=find('pick-rows');body.replaceChildren();
    [...sourceRows.values()].filter(row=>(row.name+' '+row.uid).toLocaleLowerCase('vi').includes(query)).forEach(row=>{
      const tr=document.createElement('tr'),td=document.createElement('td'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=choices.has(row.id);checkbox.setAttribute('aria-label',`Chọn group ${row.name}`);checkbox.addEventListener('change',()=>{if(checkbox.checked)choices.add(row.id);else choices.delete(row.id);updatePickerSelection();});td.append(checkbox);tr.append(td);
      [row.name,row.uid,row.member_count].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;tr.append(cell);});body.append(tr);
    });
    updatePickerSelection();find('pick-more').hidden=!more;
  }
  function visiblePickerRows(){const query=find('pick-query').value.toLocaleLowerCase('vi');return [...sourceRows.values()].filter(row=>(row.name+' '+row.uid).toLocaleLowerCase('vi').includes(query));}
  function updatePickerSelection(){
    const visible=visiblePickerRows(),all=find('pick-select-all');
    all.checked=visible.length>0 && visible.every(row=>choices.has(row.id));all.indeterminate=visible.some(row=>choices.has(row.id)) && !all.checked;
    find('pick-status').textContent=`Đã tải ${sourceRows.size} group · ${choices.size} đã chọn.${more?' Bấm Tải thêm để đọc tiếp.':''}`;
  }
  find('pick-select-all').addEventListener('change',()=>{for(const row of visiblePickerRows()){if(find('pick-select-all').checked)choices.add(row.id);else choices.delete(row.id);}renderPicker();});
  async function readLoaded(){
    let first=await api(`/data-scans/${scanId}/rows?p=1`);
    if(first.scan.kind!=='groups' || String(first.scan.account_id)!==sender.value)throw new Error('Kết quả quét không thuộc tài khoản gửi đã chọn.');
    for(let p=loadedPages+1;p<=first.pages;p++){
      const data=p===1?first:await api(`/data-scans/${scanId}/rows?p=${p}`);for(const row of data.rows)sourceRows.set(row.id,row);loadedPages=p;
    }
    more=first.scan.has_more;renderPicker();
  }
  function resetPicker(){sourceRows.clear();choices.clear();scanId=null;loadedPages=0;more=false;find('pick-query').value='';renderPicker();}
  async function pickGroups(saved){
    if(busy)return;if(!sender.value){status('Chọn tài khoản gửi trước khi chọn group.');sender.focus();return;}
    busy=true;resetPicker();picker.showModal();find('pick-status').textContent='Đang tải group…';
    try{
      let selector=find('group-scan-choice');
      if(selector)selector.remove();
      if(saved){
        const data=await api('/data-scans/catalog'),scans=data.scans.filter(scan=>scan.kind==='groups');
        selector=document.createElement('select');selector.dataset.groupScanChoice='';selector.setAttribute('aria-label','Kết quả quét group đã lưu');selector.append(new Option('Chọn kết quả quét group',''),...scans.map(scan=>new Option(`${scan.source_name} · ${scan.account_name} (${scan.total})`,scan.id)));find('pick-query').before(selector);
        selector.addEventListener('change',async()=>{resetPicker();if(!selector.value)return;scanId=Number(selector.value);try{await readLoaded();}catch(error){find('pick-status').textContent=error.message;}});
        find('pick-status').textContent=scans.length?'Chọn kết quả quét của đúng tài khoản gửi.':'Chưa có kết quả quét group. Bấm Chọn group Zalo để tải mới.';
      } else {const data=await api('/data-scans/start',{kind:'groups',account_id:sender.value});scanId=data.scan_id;await readLoaded();}
    }catch(error){find('pick-status').textContent=error.message;}finally{busy=false;}
  }
  find('pick-zalo-groups').addEventListener('click',()=>pickGroups(false));find('load-saved-groups').addEventListener('click',()=>pickGroups(true));
  document.querySelectorAll('[data-close-zalo-picker]').forEach(button=>button.addEventListener('click',()=>picker.close()));
  find('pick-query').addEventListener('input',renderPicker);
  find('pick-more').addEventListener('click',async()=>{
    if(busy || !scanId)return;busy=true;find('pick-status').textContent='Đang tải thêm group…';
    try{await api(`/data-scans/${scanId}/more`,{});await readLoaded();}catch(error){find('pick-status').textContent=error.message;}finally{busy=false;}
  });
  find('insert-zalo-groups').addEventListener('click',()=>{for(const id of choices){const row=sourceRows.get(id);if(row)targets.set(row.uid,row);}updateTargets();picker.close();status(`Đã chọn ${targets.size} group.`);});
  find('clear-zalo-groups').addEventListener('click',()=>{targets.clear();updateTargets();});
  find('target-prev').addEventListener('click',()=>{targetPage--;updateTargets();});find('target-next').addEventListener('click',()=>{targetPage++;updateTargets();});
  sender.addEventListener('change',()=>{targets.clear();updateTargets();status('Tài khoản đã đổi. Chọn lại group của tài khoản này.');});
  find('group-action').addEventListener('change',event=>{if(event.target.value==='phone_actions')location.href='/campaigns#new';});
  form.addEventListener('submit',event=>{updateTargets();if(!targets.size){event.preventDefault();status('Chọn ít nhất một group Zalo.');find('group-form-status').scrollIntoView({block:'center'});}});
  updateTargets();
})();
