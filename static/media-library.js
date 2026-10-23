const mediaGroupDialog = document.querySelector('#media-group-dialog');
document.querySelector('[data-open-media-group]')?.addEventListener('click', () => mediaGroupDialog.showModal());
document.querySelectorAll('[data-close-media-group]').forEach(button => button.addEventListener('click', () => mediaGroupDialog.close()));
document.querySelector('[data-search-media-group]')?.addEventListener('input', event => {
  const query = event.target.value.toLocaleLowerCase('vi');
  document.querySelectorAll('[data-media-group-name]').forEach(link => link.hidden = !link.dataset.mediaGroupName.toLocaleLowerCase('vi').includes(query));
});
document.querySelectorAll('[data-media-auto-filter]').forEach(select => select.addEventListener('change', () => select.form.requestSubmit()));
const uploadForm = document.querySelector('[data-media-upload-form]');
if (uploadForm) {
  const input = uploadForm.elements.file;
  const status = document.querySelector('[data-media-upload-status]');
  let uploading = false;
  function showStatus(message) { status.hidden = false; status.textContent = message; }
  async function uploadFiles(files) {
    if (uploading || !files.length) return;
    uploading = true; input.disabled = true;
    const errors = []; let uploaded = 0;
    try {
      for (const [index, file] of Array.from(files).entries()) {
        showStatus(`Đang tải ${index + 1}/${files.length}: ${file.name}`);
        if (file.size > 10 * 1024 * 1024) { errors.push(`${file.name}: quá 10 MB`); continue; }
        const data = new FormData(uploadForm); data.set('file', file);
        try {
          const response = await fetch(uploadForm.action, {method:'POST',body:data,headers:{Accept:'application/json'}});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Tải lên thất bại');
          uploaded += 1;
        } catch (error) { errors.push(`${file.name}: ${error instanceof SyntaxError ? 'Phiên làm việc hết hạn hoặc máy chủ không trả dữ liệu' : error.message}`); }
      }
      if (!errors.length) {
        const url = new URL('/media', location.origin); if (uploadForm.elements.group.value) url.searchParams.set('group', uploadForm.elements.group.value);
        location.assign(url.href);
      } else showStatus(`Đã tải ${uploaded}/${files.length} tệp. ${errors.join('; ')}. Nhấn Làm mới để xem các tệp đã tải thành công.`);
    } finally { uploading = false; input.disabled = false; input.value = ''; }
  }
  document.querySelector('.media-upload-button').addEventListener('click', () => input.accept='.jpg,.jpeg,.png,.webp,.pdf,.mp4');
  document.querySelectorAll('[data-upload-accept]').forEach(button => button.addEventListener('click', () => { input.accept=button.dataset.uploadAccept; button.closest('details').open=false; input.click(); }));
  input.addEventListener('change', () => uploadFiles(Array.from(input.files)));
  document.querySelector('.media-upload-button').addEventListener('keydown', event => { if (event.key==='Enter' || event.key===' ') { event.preventDefault(); input.click(); } });
  const dropzone = document.querySelector('[data-media-dropzone]');
  ['dragover','dragenter'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add('dragging'); }));
  ['dragleave','drop'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove('dragging'); }));
  dropzone.addEventListener('drop', event => uploadFiles(Array.from(event.dataTransfer.files)));
  document.addEventListener('paste', event => {
    if (document.querySelector('.media-dialog[open]')) return;
    const files = Array.from(event.clipboardData?.files || []).filter(file => file.type.startsWith('image/'));
    if (files.length) { event.preventDefault(); uploadFiles(files); }
  });
  document.querySelector('[data-paste-media]').addEventListener('click', async () => {
    if (!navigator.clipboard?.read) { showStatus('Nhấn Ctrl+V để dán ảnh từ clipboard.'); return; }
    try {
      const items = await navigator.clipboard.read(); const files = [];
      for (const item of items) {
        const type = item.types.find(type => type==='image/png' || type==='image/jpeg' || type==='image/webp');
        if (type) files.push(new File([await item.getType(type)], `clipboard-${Date.now()}.${type.split('/')[1]}`, {type}));
      }
      if (files.length) uploadFiles(files); else showStatus('Clipboard chưa có ảnh. Sao chép ảnh rồi nhấn Ctrl+V.');
    } catch { showStatus('Chưa đọc được clipboard. Bạn có thể nhấn Ctrl+V hoặc chọn Tải lên.'); }
  });
}
const previewDialog = document.querySelector('#library-preview-dialog');
if (previewDialog) {
  const body = previewDialog.querySelector('[data-library-preview-body]');
  document.querySelectorAll('[data-preview-media]').forEach(button => button.addEventListener('click', () => {
    body.replaceChildren();
    previewDialog.querySelector('#library-preview-title').textContent = button.dataset.mediaName;
    const mime = button.dataset.mediaKind;
    const element = document.createElement(mime.startsWith('image/') ? 'img' : mime.startsWith('video/') ? 'video' : 'iframe');
    element.src = button.dataset.previewMedia;
    if (mime.startsWith('image/')) element.alt = button.dataset.mediaName;
    if (mime.startsWith('video/')) element.controls = true;
    if (mime==='application/pdf') element.title = button.dataset.mediaName;
    body.append(element);
    const download = previewDialog.querySelector('[data-library-download]');
    download.href = button.dataset.previewMedia; download.download = button.dataset.mediaName;
    previewDialog.showModal();
  }));
  previewDialog.querySelectorAll('[data-close-library-preview]').forEach(button => button.addEventListener('click', () => previewDialog.close()));
  previewDialog.addEventListener('close', () => body.replaceChildren());
}
const bulkForm = document.querySelector('#media-bulk-form');
if (bulkForm) {
  const choices = Array.from(document.querySelectorAll('[name=media_ids]'));
  function selection() { const count = choices.filter(input => input.checked).length; bulkForm.hidden = count===0; bulkForm.querySelector('[data-media-selected-count]').textContent = `Đã chọn ${count} tệp`; }
  choices.forEach(input => input.addEventListener('change', selection));
  bulkForm.querySelector('[data-clear-media-selection]').addEventListener('click', () => { choices.forEach(input => input.checked=false); selection(); });
}
