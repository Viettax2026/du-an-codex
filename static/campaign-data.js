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
 // Import inspection is separate from validation: choosing a file never stages data.
 let category='valid',resultPage=1,exportPending=false,inspectTimer;
 const collections=()=>result?{valid:result.rows,invalid:result.excluded,duplicates:result.duplicate_rows}:{valid:[],invalid:[],duplicates:[]};
 function message(text,error=false){$('[data-import-status]').textContent=text;$('[data-import-status]').classList.toggle('is-error',error);}
 function resultTable(){
  const rows=collections()[category],head=$('[data-import-result-head]'),body=$('[data-import-preview]');head.replaceChildren();body.replaceChildren();
  ['STT',...fields.map(key=>labels[key]),...(category==='valid'?[]:['Dòng nguồn','Lý do'])].forEach(title=>{const th=document.createElement('th');th.textContent=title;head.append(th);});
  resultPage=Math.max(1,Math.min(resultPage,Math.ceil(rows.length/100) || 1));const offset=(resultPage-1)*100;
  $('[data-result-pages]').hidden=!result;$('[data-result-prev]').disabled=resultPage===1;$('[data-result-next]').disabled=resultPage*100>=rows.length;$('[data-result-page]').textContent=`Hiển thị ${rows.length?offset+1:0}–${Math.min(offset+100,rows.length)} / ${rows.length}`;
  rows.slice(offset,offset+100).forEach((row,index)=>{const tr=document.createElement('tr');cell(tr,offset+index+1);fields.forEach(key=>cell(tr,row[key] || ''));if(category!=='valid'){cell(tr,row.row);cell(tr,row.reason);}body.append(tr);});
  if(!rows.length){const tr=document.createElement('tr');cell(tr,result?'Không có dữ liệu trong nhóm này.':'Chưa có dữ liệu đã kiểm tra').colSpan=category==='valid'?8:10;body.append(tr);}
  upload.querySelectorAll('[data-result-tab]').forEach(tab=>{const active=tab.dataset.resultTab===category;tab.setAttribute('aria-selected',String(active));tab.closest('[data-result-group]').classList.toggle('is-active',active);});
 }
 function updateAccept(){
  $('[data-import-footer]').textContent=result?.rows.length?`Sẽ chèn ${result.rows.length} dữ liệu hợp lệ vào danh sách chờ.`:'Kiểm tra dữ liệu để xem kết quả trước khi chèn.';
  $('[data-accept-campaign-import]').disabled=!result?.rows.length;
  for(const [key,rows] of Object.entries(collections())){upload.querySelector(`[data-result-count="${key}"]`).textContent=rows.length;upload.querySelector(`[data-export-category="${key}"]`).disabled=exportPending || !rows.length;}
 }
 function invalidate(){
  epoch++;controller?.abort();clearTimeout(inspectTimer);result=null;category='valid';resultPage=1;$('[data-check-campaign-import]').disabled=false;$('[data-import-results]').hidden=true;updateAccept();resultTable();message('Dữ liệu đã thay đổi. Bấm Kiểm tra dữ liệu để cập nhật.');
 }
 function renderMapping(payload){
  const visible=mode==='file' || payload.columns.length>1;
  $('[data-multi-phone-options]').hidden=!visible;$('[data-import-mapping]').hidden=!visible;
  $('[data-mapping-fields]').replaceChildren();$('[data-extra-mapping-fields]').replaceChildren();
  Object.entries(labels).forEach(([key,title])=>{
   const label=document.createElement('label');label.textContent=title+(key==='phone'?' *':'');const select=document.createElement('select');select.dataset.importField=key;select.setAttribute('aria-label',title);
   select.add(new Option('— Bỏ qua —',''));payload.columns.forEach(col=>select.add(new Option(col.label,col.value)));select.value=payload.mapping[key] || '';select.addEventListener('change',invalidate);label.append(select);
   $(['email','zalo_id'].includes(key)?'[data-extra-mapping-fields]':'[data-mapping-fields]').append(label);
  });
  $('[data-skip-import-header]').checked=payload.skip_header;
  const sheet=$('[data-import-sheet]');sheet.replaceChildren();payload.sheets.forEach(name=>sheet.add(new Option(name,name)));sheet.value=payload.sheet;$('[data-import-sheet-wrap]').hidden=!payload.sheets.length;
  const sample=$('[data-import-sample]');sample.replaceChildren();const table=document.createElement('table'),head=document.createElement('thead'),header=document.createElement('tr'),body=document.createElement('tbody');
  ['Dòng',...payload.columns.map(col=>col.label)].forEach(value=>{const th=document.createElement('th');th.textContent=value;header.append(th);});head.append(header);
  payload.sample.forEach((row,index)=>{const tr=document.createElement('tr');cell(tr,index+1);payload.columns.forEach(col=>cell(tr,row[Number(col.value)] || ''));body.append(tr);});table.append(head,body);sample.append(table);
 }
 function payload(phase,reset=false,sheetOverride=null){
  const data=new FormData();data.set('csrf',form.elements.csrf.value);data.set('phase',phase);data.set('multi_phone',$('[name=campaign_multi_phone]:checked').value);
  const file=(mode==='text'?$('[data-import-txt]'):$('[data-import-file]')).files[0];
  if(file && file.size>2*1024*1024)throw new Error('Tệp data không vượt quá 2 MB.');
  data.set('mode',mode==='file' || file?'file':'text');if(file)data.set('file',file);else data.set('text',$('[data-import-text]').value);
  if(sheetOverride!==null)data.set('sheet',sheetOverride);
  else if(!reset && $('[data-import-sheet]').value)data.set('sheet',$('[data-import-sheet]').value);
  if(!reset && !$('[data-import-mapping]').hidden){data.set('mapping',JSON.stringify(Object.fromEntries([...upload.querySelectorAll('[data-import-field]')].map(select=>[select.dataset.importField,select.value]))));data.set('skip_header',$('[data-skip-import-header]').checked?'yes':'');}
  return data;
 }
 async function inspectOrCheck(phase,reset=false,sheetOverride=null){
  invalidate();const current=epoch;controller=new AbortController();const check=$('[data-check-campaign-import]');check.disabled=true;message(phase==='inspect'?'Đang đọc dữ liệu nguồn…':'Đang kiểm tra dữ liệu…');
  try{
   const response=await fetch(upload.dataset.previewUrl,{method:'POST',body:payload(phase,reset,sheetOverride),credentials:'same-origin',headers:{Accept:'application/json'},signal:controller.signal});
   if(response.redirected)throw new Error('Phiên làm việc đã hết hạn. Tải lại trang để đăng nhập.');
   const data=await response.json();if(!response.ok)throw new Error(data.error || 'Không đọc được dữ liệu.');if(current!==epoch)return;
   renderMapping(data);
   if(phase==='inspect'){message(`Đã tải dữ liệu nguồn${data.sheet?' · Sheet '+data.sheet:''}. Bấm Kiểm tra dữ liệu để xem kết quả.`);return;}
   result=data;category='valid';$('[data-import-results]').hidden=false;resultTable();updateAccept();
   message(`Đã kiểm tra ${data.source_rows} dòng nguồn · ${data.items_count} mục sau tách. Trùng chỉ tính trong lần upload này.${data.ignored_phones?' '+data.ignored_phones+' SĐT không chọn theo thiết lập.':''}${data.ignored_invalid?' '+data.ignored_invalid+' giá trị không hợp lệ đã bỏ qua.':''}`);
   $('[data-import-results]').scrollIntoView({block:'start'});
  }catch(error){if(error.name!=='AbortError' && current===epoch)message(error instanceof SyntaxError?'Không đọc được phản hồi. Tải lại trang để kiểm tra phiên làm việc.':error.message,true);}
  finally{if(current===epoch)check.disabled=false;}
 }
 function sourceChanged(){invalidate();$('[data-import-mapping]').hidden=true;$('[data-import-sheet]').replaceChildren();inspectOrCheck('inspect',true);}
 form.querySelector('[data-open-campaign-upload]').addEventListener('click',()=>{upload.showModal();if(mode==='text')$('[data-import-text]').focus();});
 upload.querySelectorAll('[data-close-campaign-upload]').forEach(button=>button.addEventListener('click',()=>upload.close()));
 upload.querySelectorAll('[data-upload-mode]').forEach(button=>button.addEventListener('click',()=>{
  mode=button.dataset.uploadMode;upload.querySelectorAll('[data-upload-mode]').forEach(tab=>tab.setAttribute('aria-selected',String(tab===button)));
  $('#campaign-import-text').hidden=mode!=='text';$('#campaign-import-file').hidden=mode!=='file';$('[data-multi-phone-options]').hidden=mode!=='file';$('[data-import-mapping]').hidden=true;invalidate();
  const file=(mode==='text'?$('[data-import-txt]'):$('[data-import-file]')).files[0];if(file)sourceChanged();
 }));
 $('[data-import-text]').addEventListener('input',()=>{$('[data-import-txt]').value='';$('[data-import-mapping]').hidden=true;invalidate();if($('[data-import-text]').value.includes('\t'))inspectTimer=setTimeout(()=>inspectOrCheck('inspect',true),250);});
 $('[data-pick-import-file]').addEventListener('click',()=>$('[data-import-file]').click());
 for(const selector of ['[data-import-txt]','[data-import-file]'])$(selector).addEventListener('change',()=>{$('[data-import-filename]').textContent=$('[data-import-file]').files[0]?.name || '';sourceChanged();});
 $('[data-import-sheet]').addEventListener('change',()=>inspectOrCheck('inspect',true,$('[data-import-sheet]').value));
 $('[data-skip-import-header]').addEventListener('change',invalidate);upload.querySelectorAll('[name=campaign_multi_phone]').forEach(radio=>radio.addEventListener('change',invalidate));
 $('[data-check-campaign-import]').addEventListener('click',()=>inspectOrCheck('check'));
 upload.querySelectorAll('[data-result-tab]').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.resultTab;resultPage=1;resultTable();}));
 $('[data-result-prev]').addEventListener('click',()=>{resultPage--;resultTable();});$('[data-result-next]').addEventListener('click',()=>{resultPage++;resultTable();});
 upload.querySelectorAll('[data-export-category]').forEach(button=>button.addEventListener('click',async()=>{
  if(!result || exportPending)return;const current=epoch;exportPending=true;updateAccept();
  try{
   const data=payload('check');data.set('category',button.dataset.exportCategory);const response=await fetch(upload.dataset.exportUrl,{method:'POST',body:data,credentials:'same-origin'});
   if(response.redirected)throw new Error('Phiên làm việc đã hết hạn.');if(!response.ok){const error=await response.json();throw new Error(error.error || 'Không tải được Excel.');}
   const blob=await response.blob();if(current!==epoch)return;const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`data-${button.dataset.exportCategory}.xlsx`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){if(current===epoch)message(error.message || 'Không tải được Excel.',true);}finally{exportPending=false;updateAccept();}
 }));
 upload.addEventListener('close',()=>{epoch++;controller?.abort();clearTimeout(inspectTimer);$('[data-check-campaign-import]').disabled=false;});
 $('[data-accept-campaign-import]').addEventListener('click',()=>{
  if(!result || $('[data-accept-campaign-import]').disabled)return;
  const combined=new Set([...merged().map(row=>row.phone),...result.rows.map(row=>row.phone)]);
  if(combined.size>10000){message('Danh sách chờ vượt 10.000 khách hàng. Bỏ bớt data trước khi thêm.',true);return;}
  const next=new Map(imported);result.rows.forEach(row=>{if(!next.has(row.phone))next.set(row.phone,row);});
  if(new TextEncoder().encode(JSON.stringify([...next.values()])).length>8*1024*1024){message('Danh sách chờ vượt 8 MB. Bỏ bớt data hoặc chia thành lần nhập khác.',true);return;}
  next.forEach((row,phone)=>imported.set(phone,row));page=1;renderQueue();upload.close();
 });
 parent.addEventListener('cancel',event=>{event.preventDefault();location.assign(parent.querySelector('.data-dialog-close').href);});
 renderQueue();parent.showModal();
})();
