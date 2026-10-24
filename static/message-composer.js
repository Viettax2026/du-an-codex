(() => {
  const root = document.querySelector('[data-message-composer]');
  if (!root) return;
  const form = root.closest('form'), textarea = root.querySelector('[name=message]');
  const editor = root.querySelector('[data-composer-editor]'), rich = root.querySelector('[data-composer-rich]');
  const htmlField = root.querySelector('[name=message_html]'), richField = root.querySelector('[name=rich_message]');
  const status = root.querySelector('[data-composer-status]'), counter = root.querySelector('[data-composer-count]');
  const fileInput = root.querySelector('[name=media]'), libraryId = root.querySelector('[name=library_media_id]');
  const csrf = form.elements.csrf.value;
  const dialogs = [...document.querySelectorAll('.composer-dialog')];
  const templateDialog = document.querySelector('#composer-templates-dialog');
  const saveDialog = document.querySelector('#composer-save-dialog');
  const libraryDialog = document.querySelector('#composer-library-dialog');
  const previewDialog = document.querySelector('#composer-preview-dialog');
  const linkDialog = document.querySelector('#composer-link-dialog');
  let savedRange = null, previewTimer, previewEpoch = 0, templates = [], media = [];
  let currentTemplate = '', management = false, attachment = JSON.parse(root.dataset.initialMedia || 'null'), localUrl = null;
  const blocks = new Set(['P','DIV','H1','H2','H3','BLOCKQUOTE','UL','OL','LI']);
  const dropped = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','SVG','MATH','TEMPLATE']);
  const allowed = new Set(['STRONG','B','EM','I','U','S','STRIKE','BR',...blocks]);
  const styles = new Set(['b','i','u','s','f_18','lst_1','lst_2','ind_$']);
  function cleanHTML(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    function clean(node, parent) {
      if (node.nodeType === Node.TEXT_NODE) { parent.append(document.createTextNode(node.textContent)); return; }
      if (node.nodeType !== Node.ELEMENT_NODE || dropped.has(node.tagName)) return;
      let target = parent;
      if (allowed.has(node.tagName)) { target = document.createElement(node.tagName.toLowerCase()); parent.append(target); }
      else if (node.tagName === 'SPAN' && styles.has(node.dataset.style)) {
        target = document.createElement('span'); target.dataset.style = node.dataset.style; parent.append(target);
      }
      // Preserve only the text emphasis from pasted office/web content; never copy CSS or event handlers.
      const emphasis = [];
      if (node.style.fontWeight === 'bold' || Number(node.style.fontWeight) >= 600) emphasis.push('strong');
      if (node.style.fontStyle === 'italic') emphasis.push('em');
      if (node.style.textDecoration.includes('underline')) emphasis.push('u');
      if (node.style.textDecoration.includes('line-through')) emphasis.push('s');
      emphasis.forEach(tag => { const wrap = document.createElement(tag); target.append(wrap); target = wrap; });
      node.childNodes.forEach(child => clean(child,target));
      // Pasted links keep the full URL in the actual message.
      if (node.tagName === 'A') {
        try { const url = new URL(node.getAttribute('href')); if (['https:','http:'].includes(url.protocol) && node.textContent !== url.href) target.append(document.createTextNode(' ('+url.href+')')); } catch { /* Only retain label for invalid links. */ }
      }
    }
    const output = document.createElement('div');
    template.content.childNodes.forEach(node => clean(node,output));
    return output.innerHTML;
  }
  function plainText(node) {
    let text = '';
    const newline = () => { if (text && !text.endsWith('\n')) text += '\n'; };
    function visit(item) {
      if (item.nodeType === Node.TEXT_NODE) { text += item.textContent; return; }
      if (item.nodeType !== Node.ELEMENT_NODE || dropped.has(item.tagName)) return;
      if (item.tagName === 'BR') { text += '\n'; return; }
      if (blocks.has(item.tagName)) newline();
      item.childNodes.forEach(visit);
      if (blocks.has(item.tagName)) newline();
    }
    node.childNodes.forEach(visit);
    return text.trim();
  }
  function setPlainEditor(text) {
    editor.replaceChildren();
    text.split('\n').forEach((line,index) => { if (index) editor.append(document.createElement('br')); editor.append(document.createTextNode(line)); });
  }
  async function api(path, data) {
    const response = await fetch(path, data ? {method:'POST',body:data,credentials:'same-origin'} : {credentials:'same-origin'});
    let result;
    try { result = await response.json(); } catch { throw new Error('Phiên làm việc đã thay đổi. Tải lại trang rồi thử lại.'); }
    if (!response.ok) throw new Error(result.error || 'Không thực hiện được. Vui lòng thử lại.');
    return result;
  }
  function messageData() {
    const data = new FormData();
    data.set('csrf',csrf); data.set('message',textarea.value); data.set('rich_message',richField.value); data.set('message_html',htmlField.value);
    return data;
  }
  function sync() {
    if (rich.checked) { textarea.value = plainText(editor); htmlField.value = editor.innerHTML; richField.value = 'yes'; }
    else { htmlField.value = ''; richField.value = 'no'; }
    textarea.required = false;
    counter.textContent = `${textarea.value.length.toLocaleString('vi-VN')} / 2.000`;
    counter.classList.toggle('is-invalid', textarea.value.length>2000);
    status.textContent = textarea.value.length>2000 ? 'Nội dung vượt 2.000 ký tự. Vui lòng rút ngắn trước khi lưu.' : '';
    textarea.dispatchEvent(new Event('composer-sync', {bubbles:true}));
    form.dispatchEvent(new Event('input', {bubbles:true}));
    queuePreview();
  }
  function remember() {
    const selection = window.getSelection();
    if (selection.rangeCount && editor.contains(selection.anchorNode) && editor.contains(selection.focusNode)) savedRange = selection.getRangeAt(0).cloneRange();
  }
  function restore() {
    editor.focus();
    const selection = window.getSelection();
    if (savedRange && editor.contains(savedRange.commonAncestorContainer)) { selection.removeAllRanges(); selection.addRange(savedRange); }
    else { const range = document.createRange(); range.selectNodeContents(editor); range.collapse(false); selection.removeAllRanges(); selection.addRange(range); }
  }
  function insertText(text) {
    if (rich.checked) { restore(); document.execCommand('insertText',false,text); remember(); }
    else { textarea.setRangeText(text,textarea.selectionStart,textarea.selectionEnd,'end'); textarea.focus(); }
    sync();
  }
  function refreshFormat() {
    root.querySelectorAll('[aria-pressed][data-format]').forEach(button => button.setAttribute('aria-pressed', String(rich.checked && document.queryCommandState(button.dataset.format))));
  }
  function toggleRich() {
    root.querySelector('[data-rich-shell]').hidden = !rich.checked;
    root.querySelector('.composer-format').hidden = !rich.checked;
    textarea.hidden = rich.checked;
    if (rich.checked) setPlainEditor(textarea.value);
    sync();
  }
  if (root.dataset.initialHtml) editor.innerHTML = cleanHTML(root.dataset.initialHtml);
  else setPlainEditor(textarea.value);
  root.classList.add('is-enhanced');
  textarea.hidden = true; textarea.required = false;
  root.querySelector('[data-rich-shell]').hidden = false;
  editor.addEventListener('input', () => { sync(); remember(); refreshFormat(); });
  editor.addEventListener('keyup', () => { remember(); refreshFormat(); });
  editor.addEventListener('mouseup', () => { remember(); refreshFormat(); });
  editor.addEventListener('paste', event => {
    event.preventDefault();
    const html = event.clipboardData.getData('text/html');
    if (html) document.execCommand('insertHTML',false,cleanHTML(html));
    else document.execCommand('insertText',false,event.clipboardData.getData('text/plain'));
    sync(); remember();
  });
  // Dropped files belong in the attachment picker, not inside editable HTML.
  editor.addEventListener('drop', event => { event.preventDefault(); status.textContent = 'Dùng Chọn file ở phía dưới để thêm tệp đính kèm.'; });
  textarea.addEventListener('input', () => { if (!rich.checked) sync(); });
  rich.addEventListener('change',toggleRich);
  root.querySelectorAll('[data-format]').forEach(button => {
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => {
      if (button.dataset.format==='link') { remember(); linkDialog.showModal(); return; }
      restore(); document.execCommand('styleWithCSS',false,false);
      document.execCommand(button.dataset.format,false,button.dataset.value || null);
      sync(); remember(); refreshFormat();
    });
  });
  root.querySelector('[data-composer-basic]').addEventListener('click', () => { (rich.checked ? editor : textarea).focus(); });
  form.addEventListener('submit',event => {
    sync();
    const required = form.elements.send_message ? form.elements.send_message.checked : root.dataset.messageRequired==='true';
    if (root.querySelector('[name=media_mode][value=send]').checked && !attachment) {
      event.preventDefault(); status.textContent='Chọn một tệp để gửi hoặc chọn Không gửi file.'; root.querySelector('[data-composer-upload]').focus(); return;
    }
    if (textarea.value.length>2000 || required && !textarea.value.trim()) {
      event.preventDefault();
      status.textContent = textarea.value.length>2000 ? 'Nội dung vượt 2.000 ký tự.' : 'Vui lòng nhập nội dung tin nhắn.';
      const card = root.closest('.wizard-card');
      if (card) { card.querySelector('.wizard-card-body').hidden=false; card.querySelector('[data-wizard-toggle]').setAttribute('aria-expanded','true'); }
      (rich.checked ? editor : textarea).focus();
    }
  });
  const picker = root.querySelector('[data-picker]'), pickerOpen = root.querySelector('[data-picker-open]');
  pickerOpen.addEventListener('mousedown',remember);
  pickerOpen.addEventListener('click', () => { picker.hidden=!picker.hidden; pickerOpen.setAttribute('aria-expanded',String(!picker.hidden)); });
  picker.querySelector('[data-picker-close]').addEventListener('click', () => { picker.hidden=true; pickerOpen.setAttribute('aria-expanded','false'); pickerOpen.focus(); });
  picker.querySelectorAll('[data-token]').forEach(button => button.addEventListener('click', () => insertText(button.dataset.token)));
  picker.querySelector('[data-date-token]').addEventListener('click', () => insertText('#{TODAY('+picker.querySelector('[data-date-format]').value+')}'));
  dialogs.forEach(dialog => dialog.querySelectorAll('[data-close-composer]').forEach(button => button.addEventListener('click', () => dialog.close())));
  linkDialog.querySelector('form').addEventListener('submit', event => {
    event.preventDefault(); const input=linkDialog.querySelector('[name=url]');
    try { const url=new URL(input.value); if (!['http:','https:'].includes(url.protocol)) throw new Error(); linkDialog.close(); insertText(url.href); input.value=''; }
    catch { linkDialog.querySelector('[data-link-status]').textContent='Nhập đường dẫn bắt đầu bằng http:// hoặc https://.'; }
  });
  async function previewMessage() {
    const epoch = ++previewEpoch;
    try {
      const result = await api('/composer/preview',messageData());
      if (epoch !== previewEpoch) return null;
      root.querySelector('[data-message-preview]').innerHTML = result.html || 'Nhập nội dung để xem trước.';
      return result;
    } catch (error) { if (epoch===previewEpoch) status.textContent=error.message; return null; }
  }
  function queuePreview() { clearTimeout(previewTimer); previewEpoch++; previewTimer=setTimeout(() => { if (!root.querySelector('[data-composer-inline-preview]').hidden) previewMessage(); },400); }
  root.querySelector('[data-composer-preview]').addEventListener('click', async () => {
    root.querySelector('[data-composer-inline-preview]').hidden=false;
    await previewMessage(); root.querySelector('[data-composer-inline-preview]').scrollIntoView({block:'nearest'});
  });
  function applyTemplate(item) {
    if (textarea.value.trim() && !window.confirm('Thay nội dung đang soạn bằng mẫu “'+item.name+'”?')) return;
    currentTemplate=String(item.id); rich.checked=Boolean(item.message_html);
    if (rich.checked) editor.innerHTML=cleanHTML(item.message_html); else textarea.value=item.message;
    root.querySelector('[data-rich-shell]').hidden=!rich.checked; textarea.hidden=rich.checked;
    sync(); templateDialog.close(); (rich.checked ? editor : textarea).focus();
  }
  async function loadTemplates() {
    const result=await api('/message-templates'); templates=result.items;
    const group=templateDialog.querySelector('[data-template-group]'), previous=group.value;
    group.replaceChildren(new Option('Tất cả nhóm',''));
    [...new Set(templates.map(item=>item.group_name))].sort().forEach(name=>group.add(new Option(name,name)));
    group.value=previous;
    renderTemplates();
  }
  function renderTemplates() {
    const list=templateDialog.querySelector('[data-template-list]'); list.replaceChildren();
    const query=templateDialog.querySelector('[data-template-search]').value.trim().toLocaleLowerCase('vi');
    const group=templateDialog.querySelector('[data-template-group]').value;
    const filtered=templates.filter(item=>(!group || item.group_name===group) && (item.name+' '+item.message).toLocaleLowerCase('vi').includes(query));
    templateDialog.querySelector('[data-template-status]').textContent=filtered.length ? `${filtered.length} mẫu nội dung` : 'Chưa có mẫu phù hợp. Soạn nội dung rồi bấm Lưu mẫu để tạo mẫu đầu tiên.';
    filtered.forEach(item=>{
      const row=document.createElement('article'), info=document.createElement('div'), title=document.createElement('b'), detail=document.createElement('small'), text=document.createElement('p');
      title.textContent=item.name; detail.textContent=item.group_name; text.textContent=item.message;
      info.append(title,detail,text); row.append(info);
      const actions=document.createElement('div'), use=document.createElement('button');
      actions.className='composer-row-actions'; use.type='button'; use.textContent=management ? 'Dùng / sửa' : 'Dùng mẫu'; use.addEventListener('click',()=>applyTemplate(item)); actions.append(use);
      if (management) {
        const remove=document.createElement('button'); remove.type='button'; remove.className='composer-delete'; remove.textContent='Xóa';
        remove.addEventListener('click',async()=>{
          if (!window.confirm('Xóa mẫu “'+item.name+'”? Nội dung trong chiến dịch đã lưu được giữ nguyên.')) return;
          remove.disabled=true;
          try { const data=new FormData();data.set('csrf',csrf); await api('/message-templates/'+item.id+'/delete',data); if (currentTemplate===String(item.id)) currentTemplate=''; await loadTemplates(); }
          catch (error) { templateDialog.querySelector('[data-template-status]').textContent=error.message; remove.disabled=false; }
        }); actions.append(remove);
      }
      row.append(actions); list.append(row);
    });
  }
  async function openTemplates(manage=false) {
    remember(); management=manage; templateDialog.querySelector('[data-template-title]').textContent=manage ? 'Quản lý mẫu nội dung' : 'Chọn mẫu nội dung';
    templateDialog.querySelector('[data-template-status]').textContent='Đang tải…'; templateDialog.querySelector('[data-template-list]').replaceChildren(); templateDialog.showModal();
    try { await loadTemplates(); } catch(error) { templateDialog.querySelector('[data-template-status]').textContent=error.message; }
  }
  root.querySelectorAll('[data-composer-templates]').forEach(button=>button.addEventListener('click',()=>openTemplates()));
  root.querySelector('[data-composer-manage]').addEventListener('click',()=>openTemplates(true));
  templateDialog.querySelector('[data-template-search]').addEventListener('input',renderTemplates);
  templateDialog.querySelector('[data-template-group]').addEventListener('change',renderTemplates);
  const saveForm=saveDialog.querySelector('form'), saveStatus=saveDialog.querySelector('[data-save-template-status]');
  root.querySelector('[data-composer-save]').addEventListener('click',async()=>{
    sync(); if (!textarea.value.trim()) { status.textContent='Nhập nội dung trước khi lưu mẫu.'; (rich.checked ? editor : textarea).focus(); return; }
    saveStatus.textContent='Đang tải…'; saveDialog.showModal();
    try {
      await loadTemplates(); saveForm.elements.template_id.replaceChildren(new Option('Tạo mẫu mới',''));
      templates.forEach(item=>saveForm.elements.template_id.add(new Option(item.name+' · '+item.group_name,item.id)));
      saveForm.elements.template_id.value=currentTemplate;
      const current=templates.find(item=>String(item.id)===currentTemplate);
      saveForm.elements.name.value=current?.name || ''; saveForm.elements.group_name.value=current?.group_name || 'Chung';
      const groups=saveDialog.querySelector('datalist'); groups.replaceChildren(); [...new Set(templates.map(item=>item.group_name))].forEach(group=>groups.append(new Option(group,group)));
      saveStatus.textContent=''; saveForm.elements.name.focus();
    } catch(error) { saveStatus.textContent=error.message; }
  });
  saveForm.elements.template_id.addEventListener('change',()=>{
    const current=templates.find(item=>String(item.id)===saveForm.elements.template_id.value);
    if(current) { saveForm.elements.name.value=current.name; saveForm.elements.group_name.value=current.group_name; }
  });
  saveForm.addEventListener('submit',async event=>{
    event.preventDefault(); const button=saveForm.querySelector('[type=submit]');button.disabled=true;
    try { const data=messageData(); for(const key of ['template_id','name','group_name']) data.set(key,saveForm.elements[key].value); const result=await api('/message-templates',data);currentTemplate=String(result.id);saveDialog.close();status.textContent='Đã lưu mẫu nội dung.'; }
    catch(error) { saveStatus.textContent=error.message; }
    finally { button.disabled=false; }
  });
  function revokeLocal() { if(localUrl) URL.revokeObjectURL(localUrl); localUrl=null; }
  function clearAttachment() {
    revokeLocal(); attachment=null; fileInput.value='';libraryId.value=''; root.querySelector('[name=media_mode][value=none]').checked=true;
    root.dataset.initialMedia='null';renderAttachment();
  }
  function selectAttachment(item) { attachment=item;root.querySelector('[name=media_mode][value=send]').checked=true;renderAttachment(); }
  function viewAttachment(item) {
    const body=previewDialog.querySelector('[data-composer-preview-body]');body.replaceChildren(); previewDialog.querySelector('[data-composer-preview-title]').textContent=item.filename;
    let element;
    if(item.mime.startsWith('image/')) { element=document.createElement('img');element.alt=item.filename; }
    else if(item.mime==='video/mp4') { element=document.createElement('video');element.controls=true; }
    else { element=document.createElement('p');element.textContent='Tệp PDF · ';const link=document.createElement('a');link.href=item.preview_url;link.target='_blank';link.rel='noopener';link.textContent='Mở / tải tệp PDF ↗';element.append(link); }
    if(['IMG','VIDEO'].includes(element.tagName)) element.src=item.preview_url;
    body.append(element);previewDialog.showModal();
  }
  previewDialog.addEventListener('close',()=>previewDialog.querySelector('[data-composer-preview-body]').replaceChildren());
  function fileIcon(kind) {
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('width','17');svg.setAttribute('height','17');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.7');svg.setAttribute('aria-hidden','true');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',kind==='eye' ? 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12m10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6' : 'M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v8m4-8v8');
    svg.append(path);return svg;
  }
  function renderAttachment() {
    const rows=root.querySelector('[data-composer-file-rows]');rows.replaceChildren();const row=document.createElement('tr');
    if(!attachment) {const cell=document.createElement('td');cell.colSpan=3;cell.className='composer-file-empty';cell.textContent='Chưa chọn file';row.append(cell);}
    else {
      const index=document.createElement('td'), name=document.createElement('td'), actions=document.createElement('td');index.textContent='1';
      const view=document.createElement('button');view.type='button';view.className='composer-file-name';view.append(fileIcon('eye'),document.createTextNode(attachment.filename));view.title='Xem trước '+attachment.filename;view.addEventListener('click',()=>viewAttachment(attachment));name.append(view);
      const remove=document.createElement('button');remove.type='button';remove.className='composer-delete';remove.append(fileIcon('trash'));remove.setAttribute('aria-label','Gỡ tệp đính kèm');remove.title='Gỡ tệp khỏi chiến dịch';remove.addEventListener('click',clearAttachment);actions.append(remove);row.append(index,name,actions);
    }
    rows.append(row);form.dispatchEvent(new Event('change',{bubbles:true}));
  }
  root.querySelector('[data-composer-upload]').addEventListener('click',()=>fileInput.click());
  fileInput.addEventListener('change',()=>{
    const file=fileInput.files[0];if(!file)return;
    if(!/\.(jpe?g|png|webp|pdf|mp4)$/i.test(file.name) || file.size>10*1024*1024 || !file.size) {clearAttachment();status.textContent='Chọn JPG, PNG, WEBP, PDF hoặc MP4 có dữ liệu, tối đa 10 MB.';return;}
    revokeLocal();libraryId.value='';localUrl=URL.createObjectURL(file);
    selectAttachment({filename:file.name,mime:file.type || ({jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',webp:'image/webp',pdf:'application/pdf',mp4:'video/mp4'}[file.name.split('.').pop().toLowerCase()]),size:file.size,preview_url:localUrl});
    status.textContent='';
  });
  root.querySelector('[name=media_mode][value=none]').addEventListener('change',clearAttachment);
  function renderLibrary() {
    const list=libraryDialog.querySelector('[data-library-list]');list.replaceChildren();const query=libraryDialog.querySelector('[data-library-search]').value.toLocaleLowerCase('vi');
    const items=media.filter(item=>item.filename.toLocaleLowerCase('vi').includes(query));libraryDialog.querySelector('[data-library-status]').textContent=items.length ? `${items.length} tệp` : 'Chưa có tệp phù hợp. Dùng Chọn file để tải tệp mới.';
    items.forEach(item=>{
      const row=document.createElement('article'), name=document.createElement('div'), title=document.createElement('b'), detail=document.createElement('small'), actions=document.createElement('div');
      title.textContent=item.filename;detail.textContent=`${item.mime} · ${(item.size/1024).toFixed(1)} KB`;name.append(title,detail);actions.className='composer-row-actions';
      const preview=document.createElement('button');preview.type='button';preview.textContent='Xem';preview.addEventListener('click',()=>viewAttachment(item));
      const choose=document.createElement('button');choose.type='button';choose.textContent='Chọn';choose.addEventListener('click',()=>{revokeLocal();fileInput.value='';libraryId.value=item.id;selectAttachment(item);libraryDialog.close();});actions.append(preview,choose);row.append(name,actions);list.append(row);
    });
  }
  root.querySelector('[data-composer-library]').addEventListener('click',async()=>{
    libraryDialog.querySelector('[data-library-status]').textContent='Đang tải…';libraryDialog.querySelector('[data-library-list]').replaceChildren();libraryDialog.showModal();
    try {const result=await api('/composer/media');media=result.items;renderLibrary();}catch(error){libraryDialog.querySelector('[data-library-status]').textContent=error.message;}
  });
  libraryDialog.querySelector('[data-library-search]').addEventListener('input',renderLibrary);
  function toggleFiles() {
    const enabled=form.elements.send_message ? form.elements.send_message.checked : root.dataset.messageRequired==='true';
    if(!enabled) clearAttachment();
    root.querySelectorAll('.composer-files button,.composer-files input').forEach(input=>input.disabled=!enabled);
    root.querySelector('.composer-files').classList.toggle('is-disabled',!enabled);
  }
  form.elements.send_message?.addEventListener('change',toggleFiles);
  renderAttachment();toggleFiles();sync();
  window.addEventListener('pagehide',revokeLocal);
})();
