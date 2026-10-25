(() => {
 const form=document.querySelector('[data-campaign-data-form]');if(!form)return;
 const parent=document.querySelector('#campaign-data-dialog'),upload=document.querySelector('#campaign-upload-dialog');
 const imported=new Map(),grouped=new Map();let page=1,mode='text',result=null,epoch=0,controller;
 const $=selector=>upload.querySelector(selector),queueStatus=form.querySelector('[data-queue-status]');
 const labels={name:'Tên',phone:'Số điện thoại',info1:'Info 1',info2:'Info 2',info3:'Info 3',info4:'Info 4',info5:'Info 5',email:'Email',zalo_id:'Zalo ID'};
 const fields=['name','phone','info1','info2','info3','info4','info5'];
 function cell(row,value){const td=document.createElement('td');td.textContent=String(value??'');row.append(td);return td;}
 function merged(){return [...new Map([...imported,...[...grouped.values()].map(row=>[row.phone,row])]).values()];}
 function renderQueue(){
  const rows=merged(),pages=Math.max(1,Math.ceil(rows.length/50));page=Math.max(1,Math.min(page,pages));
  const body=form.querySelector('[data-queue-rows]');body.replaceChildren();
  rows.slice((page-1)*50,page*50).forEach((row,index)=>{
   const tr=document.createElement('tr');cell(tr,(page-1)*50+index+1);fields.forEach(key=>cell(tr,row[key] || (key==='name'?'Khách hàng '+row.phone:'')));
   const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Bỏ '+row.phone+' khỏi danh sách chờ');
   remove.addEventListener('click',()=>{imported.delete(row.phone);[...grouped.values()].filter(item=>item.phone===row.phone).forEach(item=>form.dispatchEvent(new CustomEvent('campaign-remove-snapshot',{detail:{id:item.id}})));renderQueue();});cell(tr,'').append(remove);body.append(tr);
  });
  if(!rows.length){const tr=document.createElement('tr');cell(tr,'Chưa có data nào. Hãy nhập/import hoặc thêm bằng nhóm.').colSpan=9;body.append(tr);}
  form.querySelector('[data-queue-count]').textContent=rows.length?`(${rows.length.toLocaleString('vi-VN')})`:'';
  form.querySelector('[data-queue-page]').textContent=`Trang ${page}/${pages}`;
  form.querySelector('[data-queue-prev]').disabled=page===1;form.querySelector('[data-queue-next]').disabled=page===pages;
  form.querySelector('[data-clear-queue]').disabled=!rows.length;
  form.querySelector('[data-save-queue]').disabled=!rows.length || rows.length>10000 || !form.elements.consent.checked;
  form.elements.rows_json.value=JSON.stringify([...imported.values()]);
  queueStatus.textContent=rows.length>10000?'Danh sách vượt 10.000 khách hàng. Bỏ bớt data trước khi thêm.':'';
  queueStatus.classList.toggle('is-error',rows.length>10000);
 }
 try{const saved=JSON.parse(form.dataset.initialRows);if(Array.isArray(saved))saved.filter(row=>row && typeof row.phone==='string').forEach(row=>imported.set(row.phone,row));}catch{}
 form.addEventListener('campaign-group-snapshot-change',event=>{grouped.clear();event.detail.rows.forEach(row=>grouped.set(row.id,row));page=1;renderQueue();});
 form.querySelector('[data-clear-queue]').addEventListener('click',()=>{imported.clear();form.dispatchEvent(new Event('campaign-clear-snapshot'));page=1;renderQueue();});
 form.querySelector('[data-queue-prev]').addEventListener('click',()=>{page--;renderQueue();});form.querySelector('[data-queue-next]').addEventListener('click',()=>{page++;renderQueue();});
 form.elements.consent.addEventListener('change',renderQueue);
 form.addEventListener('submit',event=>{renderQueue();if(form.querySelector('[data-save-queue]').disabled){event.preventDefault();return;}form.querySelector('[data-save-queue]').disabled=true;});
 function invalidate(){epoch++;controller?.abort();result=null;$('[data-check-campaign-import]').disabled=false;$('[data-accept-campaign-import]').disabled=true;$('[data-confirm-import-skip]').checked=false;$('[data-import-status]').textContent='Dữ liệu đã thay đổi. Bấm Kiểm tra dữ liệu để cập nhật.';$('[data-import-status]').classList.remove('is-error');}
 form.querySelector('[data-open-campaign-upload]').addEventListener('click',()=>{upload.showModal();$('[data-import-text]').focus();});
 upload.querySelectorAll('[data-close-campaign-upload]').forEach(button=>button.addEventListener('click',()=>upload.close()));
 upload.querySelectorAll('[data-upload-mode]').forEach(button=>button.addEventListener('click',()=>{
  mode=button.dataset.uploadMode;upload.querySelectorAll('[data-upload-mode]').forEach(tab=>tab.setAttribute('aria-selected',String(tab===button)));
  $('#campaign-import-text').hidden=mode!=='text';$('#campaign-import-file').hidden=mode!=='file';$('[data-import-mapping]').hidden=true;$('[data-mapping-fields]').replaceChildren();$('[data-extra-mapping-fields]').replaceChildren();invalidate();
 }));
 $('[data-import-text]').addEventListener('input',()=>{$('[data-import-txt]').value='';$('[data-import-mapping]').hidden=true;invalidate();});
 for(const selector of ['[data-import-txt]','[data-import-file]'])$(selector).addEventListener('change',()=>{$('[data-import-mapping]').hidden=true;$('[data-mapping-fields]').replaceChildren();$('[data-extra-mapping-fields]').replaceChildren();invalidate();});
 $('[data-skip-import-header]').addEventListener('change',invalidate);
 function mapping(result){
  $('[data-import-mapping]').hidden=false;$('[data-mapping-fields]').replaceChildren();$('[data-extra-mapping-fields]').replaceChildren();
  Object.entries(labels).forEach(([key,title])=>{
   const label=document.createElement('label');label.textContent=title;const select=document.createElement('select');select.dataset.importField=key;
   select.add(new Option('Không chọn',''));result.columns.forEach(col=>select.add(new Option(col.label,col.value)));select.value=result.mapping[key] || '';select.addEventListener('change',invalidate);label.append(select);
   $(['email','zalo_id'].includes(key)?'[data-extra-mapping-fields]':'[data-mapping-fields]').append(label);
  });
  $('[data-skip-import-header]').checked=result.skip_header;
  const sample=$('[data-import-sample]');sample.replaceChildren();const table=document.createElement('table'),body=document.createElement('tbody');
  result.sample.forEach(row=>{const tr=document.createElement('tr');row.forEach(value=>cell(tr,value));body.append(tr);});table.append(body);sample.append(table);
 }
 function updateAccept(){ $('[data-accept-campaign-import]').disabled=!result?.rows.length || result.invalid.length>0 && !$('[data-confirm-import-skip]').checked; }
 $('[data-confirm-import-skip]').addEventListener('change',updateAccept);
 $('[data-check-campaign-import]').addEventListener('click',async()=>{
  const current=++epoch;controller?.abort();controller=new AbortController();const data=new FormData();data.set('csrf',form.elements.csrf.value);
  const file=(mode==='text'?$('[data-import-txt]'):$('[data-import-file]')).files[0];
  if(file && file.size>2*1024*1024){$('[data-import-status]').textContent='Tệp data không vượt quá 2 MB.';$('[data-import-status]').classList.add('is-error');return;}
  data.set('mode',mode==='file' || file?'file':'text');if(file)data.set('file',file);else data.set('text',$('[data-import-text]').value);
  if(!$('[data-import-mapping]').hidden){data.set('mapping',JSON.stringify(Object.fromEntries([...upload.querySelectorAll('[data-import-field]')].map(select=>[select.dataset.importField,select.value]))));data.set('skip_header',$('[data-skip-import-header]').checked?'yes':'');}
  const check=$('[data-check-campaign-import]');check.disabled=true;result=null;updateAccept();$('[data-import-status]').textContent='Đang kiểm tra dữ liệu…';$('[data-import-status]').classList.remove('is-error');
  try{
   const response=await fetch(upload.dataset.previewUrl,{method:'POST',body:data,credentials:'same-origin',headers:{Accept:'application/json'},signal:controller.signal});
   if(response.redirected)throw new Error('Phiên làm việc đã hết hạn. Tải lại trang để đăng nhập.');
   const payload=await response.json();if(!response.ok)throw new Error(payload.error || 'Không kiểm tra được dữ liệu.');if(current!==epoch)return;
   result=payload;mapping(payload);$('[data-confirm-import-skip]').checked=false;
   const body=$('[data-import-preview]');body.replaceChildren();payload.rows.slice(0,100).forEach((row,index)=>{const tr=document.createElement('tr');cell(tr,index+1);fields.forEach(key=>cell(tr,row[key] || (key==='name'?'Khách hàng '+row.phone:'')));body.append(tr);});
   if(!payload.rows.length){const tr=document.createElement('tr');cell(tr,'Chưa có số điện thoại hợp lệ. Chọn lại cột hoặc kiểm tra dữ liệu gốc.').colSpan=8;body.append(tr);}
   $('[data-import-status]').textContent=`${payload.rows.length} số hợp lệ · ${payload.duplicates} số trùng · ${payload.invalid.length} dòng lỗi.${payload.rows.length>100?' Xem trước 100 dòng đầu.':''}`;
   $('[data-import-invalid]').hidden=!payload.invalid.length;const errors=$('[data-import-errors]');errors.replaceChildren();payload.invalid.slice(0,50).forEach(row=>{const p=document.createElement('p');p.textContent=`Dòng ${row.row} · ${row.phone}: ${row.reason}`;errors.append(p);});updateAccept();
  }catch(error){if(error.name!=='AbortError' && current===epoch){$('[data-import-status]').textContent=error instanceof SyntaxError?'Không đọc được phản hồi. Tải lại trang để kiểm tra phiên làm việc.':error.message;$('[data-import-status]').classList.add('is-error');}}
  finally{if(current===epoch)check.disabled=false;}
 });
 upload.addEventListener('close',()=>{epoch++;controller?.abort();$('[data-check-campaign-import]').disabled=false;});
 $('[data-accept-campaign-import]').addEventListener('click',()=>{
  if(!result || $('[data-accept-campaign-import]').disabled)return;
  const combined=new Set([...merged().map(row=>row.phone),...result.rows.map(row=>row.phone)]);
  if(combined.size>10000){$('[data-import-status]').textContent='Danh sách chờ vượt 10.000 khách hàng. Bỏ bớt data trước khi thêm.';return;}
  result.rows.forEach(row=>{if(!imported.has(row.phone))imported.set(row.phone,row);});page=1;renderQueue();upload.close();
 });
 parent.addEventListener('cancel',event=>{event.preventDefault();location.assign(parent.querySelector('.data-dialog-close').href);});
 renderQueue();parent.showModal();
})();
