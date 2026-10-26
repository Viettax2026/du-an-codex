(() => {
  document.querySelectorAll('.campaign-wizard:not([data-group-campaign-form]) select[name="action"]').forEach(select=>select.addEventListener('change',()=>{
    if(select.value!=='group_message')return;
    const form=select.closest('form'),params=new URLSearchParams({name:form.elements.name.value,account_id:form.elements.account_id.value});
    location.href=`/group-campaigns/new?${params}`;
  }));
  const form=document.querySelector('[data-group-campaign-form]');if(!form)return;
  const find=name=>document.querySelector(`[data-${name}]`),csrf=form.dataset.csrf;
  const picker=find('zalo-group-picker'),sender=form.elements.account_id;
  let targets=new Map(),targetPage=1,sourceRows=new Map(),choices=new Set(),scanId=null,loadedPages=0,more=false,busy=false;
  let collections=[],pickerRevision=0,sourceRevision=0;
  try{for(const row of JSON.parse(find('initial-group-targets').textContent))targets.set(row.uid,row);}catch{}
  const status=(text,error=false)=>{find('group-form-status').textContent=text;find('group-form-status').classList.toggle('is-error',error);};
  const isDynamic=()=>form.elements.group_data_mode.value==='group';
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
      const td=document.createElement('td');if(!isDynamic()){const remove=document.createElement('button');remove.type='button';remove.className='group-remove';remove.setAttribute('aria-label',`Xóa group ${row.name}`);const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');for(const [key,value] of Object.entries({width:'17',height:'17',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','aria-hidden':'true'}))svg.setAttribute(key,value);const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7');svg.append(path);remove.append(svg);remove.addEventListener('click',()=>{targets.delete(row.uid);updateTargets();});td.append(remove);}tr.append(td);body.append(tr);
    });
    if(!list.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='Chọn group Zalo hoặc thêm từ kết quả quét group đã lưu.';tr.append(td);body.append(tr);}
    updateWizard();
  }
  function renderPicker(){
    const query=find('pick-query').value.toLocaleLowerCase('vi'),body=find('pick-rows');body.replaceChildren();
    [...sourceRows.values()].filter(row=>(row.name+' '+row.uid).toLocaleLowerCase('vi').includes(query)).forEach(row=>{
      const tr=document.createElement('tr'),td=document.createElement('td'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=choices.has(row.id);checkbox.setAttribute('aria-label',`Chọn group ${row.name}`);checkbox.addEventListener('change',()=>{if(checkbox.checked)choices.add(row.id);else choices.delete(row.id);updatePickerSelection();});td.append(checkbox);tr.append(td);
      [row.name,row.uid,row.member_count ?? '—'].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;tr.append(cell);});body.append(tr);
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
  async function readLoaded(version=pickerRevision){
    const id=scanId;
    let first=await api(`/data-scans/${id}/rows?p=1`);
    if(version!==pickerRevision)return;
    if(first.scan.kind!=='groups' || String(first.scan.account_id)!==sender.value)throw new Error('Kết quả quét không thuộc tài khoản gửi đã chọn.');
    for(let p=loadedPages+1;p<=first.pages;p++){
      const data=p===1?first:await api(`/data-scans/${id}/rows?p=${p}`);if(version!==pickerRevision)return;for(const row of data.rows)sourceRows.set(row.id,row);loadedPages=p;
    }
    more=first.scan.has_more;renderPicker();
  }
  function resetPicker(){sourceRows.clear();choices.clear();scanId=null;loadedPages=0;more=false;find('pick-query').value='';renderPicker();}
  async function pickGroups(saved){
    if(busy)return;if(!sender.value){status('Chọn tài khoản gửi trước khi chọn group.');sender.focus();return;}
    busy=true;const version=++pickerRevision;resetPicker();picker.showModal();find('pick-status').textContent='Đang tải group…';find('insert-zalo-groups').disabled=true;
    try{
      let selector=find('group-scan-choice');
      if(selector)selector.remove();
      if(saved==='collection'){
        const data=await api(`/group-data/catalog?account_id=${encodeURIComponent(sender.value)}`);if(version!==pickerRevision)return;
        selector=document.createElement('select');selector.dataset.groupScanChoice='';selector.setAttribute('aria-label','Nhóm data group Zalo');selector.append(new Option('Chọn nhóm data',''),...data.groups.map(group=>new Option(`${group.name} (${group.total})`,group.id)));find('pick-query').before(selector);
        selector.addEventListener('change',async()=>{const choiceVersion=++pickerRevision;resetPicker();if(!selector.value)return;const choice=selector.value;try{const result=await api(`/group-data/${choice}/members?account_id=${encodeURIComponent(sender.value)}`);if(choiceVersion!==pickerRevision || selector.value!==choice)return;for(const row of result.rows)sourceRows.set(row.id,row);renderPicker();}catch(error){find('pick-status').textContent=error.message;}});
        find('pick-status').textContent='Chọn nhóm data để thêm vào danh sách riêng của chiến dịch.';
      } else if(saved){
        const data=await api('/data-scans/catalog'),scans=data.scans.filter(scan=>scan.kind==='groups' && String(scan.account_id)===sender.value);if(version!==pickerRevision)return;
        selector=document.createElement('select');selector.dataset.groupScanChoice='';selector.setAttribute('aria-label','Kết quả quét group đã lưu');selector.append(new Option('Chọn kết quả quét group',''),...scans.map(scan=>new Option(`${scan.source_name} · ${scan.account_name} (${scan.total})`,scan.id)));find('pick-query').before(selector);
        selector.addEventListener('change',async()=>{const choiceVersion=++pickerRevision;resetPicker();if(!selector.value)return;scanId=Number(selector.value);try{await readLoaded(choiceVersion);}catch(error){find('pick-status').textContent=error.message;}});
        find('pick-status').textContent=scans.length?'Chọn kết quả quét của đúng tài khoản gửi.':'Chưa có kết quả quét group. Bấm Chọn group Zalo để tải mới.';
      } else {const data=await api('/data-scans/start',{kind:'groups',account_id:sender.value});if(version!==pickerRevision)return;scanId=data.scan_id;await readLoaded(version);}
    }catch(error){find('pick-status').textContent=error.message;}finally{busy=false;find('insert-zalo-groups').disabled=false;}
  }
  find('pick-zalo-groups').addEventListener('click',()=>pickGroups(false));find('load-saved-groups').addEventListener('click',()=>pickGroups(true));
  find('add-group-collection').addEventListener('click',()=>pickGroups('collection'));
  document.querySelectorAll('[data-close-zalo-picker]').forEach(button=>button.addEventListener('click',()=>picker.close()));
  find('pick-query').addEventListener('input',renderPicker);
  find('pick-more').addEventListener('click',async()=>{
    if(busy || !scanId)return;busy=true;find('pick-status').textContent='Đang tải thêm group…';
    try{await api(`/data-scans/${scanId}/more`,{});await readLoaded();}catch(error){find('pick-status').textContent=error.message;}finally{busy=false;}
  });
  find('insert-zalo-groups').addEventListener('click',()=>{if(busy || isDynamic())return;for(const id of choices){const row=sourceRows.get(id);if(row)targets.set(row.uid,row);}updateTargets();picker.close();status(`Đã chọn ${targets.size} group.`);});
  find('clear-zalo-groups').addEventListener('click',()=>{targets.clear();updateTargets();});
  find('target-prev').addEventListener('click',()=>{targetPage--;updateTargets();});find('target-next').addEventListener('click',()=>{targetPage++;updateTargets();});
  sender.addEventListener('change',async()=>{pickerRevision++;sourceRevision++;picker.close();targets.clear();updateTargets();status('Tài khoản đã đổi. Chọn lại group của tài khoản này.');try{await refreshCollections();if(isDynamic())await loadCollection();}catch(error){status(error.message,true);}});
  find('group-action').addEventListener('change',event=>{if(event.target.value==='phone_actions')location.href='/campaigns#new';});
  async function refreshCollections(){
    const selected=form.elements.group_data_id.value || form.dataset.initialCollection || '',account=sender.value;
    const data=await api(`/group-data/catalog?${new URLSearchParams(account?{account_id:account}:{})}`);if(account!==sender.value)return;
    collections=data.groups;form.elements.group_data_id.replaceChildren(new Option('Chọn nhóm data',''),...collections.map(group=>new Option(`${group.name} (${group.total})`,group.id)));
    form.elements.group_data_id.value=selected;form.dataset.initialCollection='';
    find('group-tag-suggestions').replaceChildren(...data.tags.map(tag=>new Option(tag,tag)));updateWizard();
  }
  async function loadCollection(){
    const version=++sourceRevision,id=form.elements.group_data_id.value,account=sender.value;
    targets.clear();updateTargets();if(!id || !account){status('Chọn tài khoản và nhóm data group Zalo.');return;}
    const data=await api(`/group-data/${id}/members?account_id=${encodeURIComponent(account)}`);
    if(version!==sourceRevision || !isDynamic() || account!==sender.value)return;
    for(const row of data.rows)targets.set(row.uid,row);updateTargets();status(`Nhóm data hiện có ${targets.size} group của tài khoản đã chọn. Group mới sẽ được nhận khi chiến dịch chạy.`);
  }
  async function changeSource(){
    find('group-source-select').hidden=!isDynamic();find('group-direct-tools').hidden=isDynamic();
    form.elements.group_data_id.required=isDynamic();
    find('group-source-note').textContent=isDynamic()?'Danh sách theo nhóm data. Group đã xử lý giữ lịch sử; group mới được nhận khi lịch chạy.':'Chọn group tài khoản gửi đã tham gia. Mỗi group được xử lý một lần trong chiến dịch.';
    if(isDynamic())try{await loadCollection();}catch(error){status(error.message,true);}
    else{sourceRevision++;updateTargets();}
    updateWizard();
  }
  form.querySelectorAll('[name=group_data_mode]').forEach(input=>input.addEventListener('change',changeSource));
  form.elements.group_data_id.addEventListener('change',()=>loadCollection().catch(error=>status(error.message,true)));
  find('reload-group-data').addEventListener('click',async()=>{try{await refreshCollections();if(isDynamic())await loadCollection();}catch(error){status(error.message,true);}});
  find('save-group-collection').addEventListener('click',async()=>{
    if(!targets.size || !sender.value){status('Chọn tài khoản và group trước khi lưu vào nhóm data.',true);return;}
    try{await refreshCollections();find('save-collection-choice').replaceChildren(new Option('Tạo nhóm mới',''),...collections.map(group=>new Option(group.name,group.id)));find('save-name-label').hidden=false;find('save-collection-status').textContent='';find('group-save-dialog').showModal();}catch(error){status(error.message,true);}
  });
  document.querySelectorAll('[data-close-group-save]').forEach(button=>button.addEventListener('click',()=>find('group-save-dialog').close()));
  find('save-collection-choice').addEventListener('change',()=>{find('save-name-label').hidden=Boolean(find('save-collection-choice').value);});
  find('group-save-form').addEventListener('submit',async event=>{
    event.preventDefault();const group=find('save-collection-choice').value;
    try{const data=await api(group?`/group-data/${group}/add`:'/group-data/new',{name:find('save-collection-name').value,account_id:sender.value,group_scan_row_ids:find('group-target-ids').value});await refreshCollections();find('group-save-dialog').close();status(`Đã thêm ${data.added} group vào nhóm data.`);}catch(error){find('save-collection-status').textContent=error.message;}
  });
  function updateOptions(){
    const enabled=form.elements.group_tags_enabled.checked;find('group-tag-fields').hidden=!enabled;form.elements.group_tags.required=enabled;
    const share=form.elements.group_share.checked;
    find('group-personalization-note').textContent=share?'Gửi chia sẻ dùng cùng nội dung cho các group trong lô. Xóa các biến cá nhân hóa trước khi lưu.':'Dùng {{name}} để chèn tên group khi gửi riêng từng group.';updateWizard();
  }
  for(const name of ['group_tags_enabled','group_share'])form.elements[name].addEventListener('change',updateOptions);
  const sections=form.querySelector('.wizard-sections'),steps=[...form.querySelectorAll('[data-group-wizard-step]')];
  function goStep(card){
    card.querySelector('.wizard-card-body').hidden=false;card.querySelector('[data-group-step-toggle]').setAttribute('aria-expanded','true');
    const top=card.getBoundingClientRect().top-sections.getBoundingClientRect().top+sections.scrollTop-8;
    sections.scrollTo({top:Math.max(0,top),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    activate(card.id.replace('group-step-',''));
  }
  function activate(key){for(const step of steps){const active=step.dataset.groupWizardStep===key;step.classList.toggle('is-active',active);if(active)step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');}}
  steps.forEach(step=>step.addEventListener('click',event=>{event.preventDefault();goStep(document.querySelector(step.getAttribute('href')));}));
  form.querySelectorAll('[data-group-step-toggle]').forEach(button=>button.addEventListener('click',()=>{const expanded=button.getAttribute('aria-expanded')==='true';button.setAttribute('aria-expanded',String(!expanded));document.getElementById(button.getAttribute('aria-controls')).hidden=expanded;}));
  sections.addEventListener('scroll',()=>{const cards=[...sections.querySelectorAll('.wizard-card')],top=sections.getBoundingClientRect().top+40;let active=cards[0];for(const card of cards)if(card.getBoundingClientRect().top<=top)active=card;activate(active.id.replace('group-step-',''));},{passive:true});
  function updateWizard(){
    if(!form.querySelector('.wizard-sections'))return;
    const f=form.elements,composer=form.querySelector('[data-message-composer]');
    const values={action:true,account:Boolean(f.account_id.value),name:Boolean(f.name.value.trim()),options:!f.group_tags_enabled.checked || Boolean(f.group_tags.value.trim()),source:['direct','group'].includes(f.group_data_mode.value),groups:targets.size>0,
      message:Boolean(f.message.value.trim()) && composer.dataset.messageValid!=='false',media:f.media_mode.value==='none' || Boolean(f.media.files.length || f.library_media_id.value || composer.dataset.initialMedia!=='null'),schedule:!f.schedule_enabled.checked || form.querySelector('[data-schedule-fields]').dataset.scheduleValid!=='false',interval:f.interval_seconds.validity.valid,limits:[f.message_limit,f.message_hour_limit,f.message_window_minutes].every(input=>input.validity.valid)};
    for(const step of form.querySelectorAll('[data-group-wizard-step]')){const checks=[...step.querySelectorAll('[data-group-wizard-check]')];let count=0;for(const item of checks){const done=Boolean(values[item.dataset.groupWizardCheck]);item.classList.toggle('is-done',done);if(done)count++;}const complete=count===checks.length;step.classList.toggle('is-complete',complete);step.querySelector('[data-step-number]').textContent=complete?'✓':step.querySelector('[data-step-number]').dataset.stepNumber;step.querySelector('[data-step-count]').textContent=`${count} / ${checks.length}`;}
  }
  form.addEventListener('input',updateWizard);form.addEventListener('change',updateWizard);
  form.addEventListener('invalid',event=>{const card=event.target.closest('.wizard-card');if(card)goStep(card);},true);
  form.addEventListener('submit',event=>{
    updateTargets();if(event.submitter?.name==='save_draft')return;
    if(!targets.size){event.preventDefault();status('Chọn ít nhất một group Zalo.',true);goStep(document.getElementById('group-step-groups'));}
    if(form.elements.group_share.checked && /\{\{name\}\}|#\{(?!TODAY\()[A-Z]/.test(form.elements.message.value)){event.preventDefault();status('Gửi chia sẻ không hỗ trợ cá nhân hóa. Xóa biến cá nhân hóa hoặc bỏ chọn gửi chia sẻ.',true);goStep(document.getElementById('group-step-message'));}
  });
  updateTargets();updateOptions();
  refreshCollections().then(()=>changeSource()).catch(error=>status(error.message,true));
})();
