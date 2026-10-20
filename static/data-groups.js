const groupDialog = document.querySelector('#create-group-dialog');
if (groupDialog) {
  const opener = document.querySelector('[data-open-group]');
  const nameInput = groupDialog.querySelector('[name=name]');
  const createButton = groupDialog.querySelector('[data-create-group]');
  function updateGroupButton() { createButton.disabled = !nameInput.value.trim(); }
  opener.addEventListener('click', () => { updateGroupButton(); groupDialog.showModal(); });
  groupDialog.querySelectorAll('[data-close-group]').forEach(button => button.addEventListener('click', () => groupDialog.close()));
  nameInput.addEventListener('input', updateGroupButton);
  groupDialog.addEventListener('click', event => { if (event.target === groupDialog) {
    const rect = groupDialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) groupDialog.close();
  }});
  // Use DOM style properties so group colors work with the site's strict CSP.
  document.querySelectorAll('[data-group-color]').forEach(dot => { dot.style.backgroundColor = dot.dataset.groupColor; });
  updateGroupButton();
  if (groupDialog.dataset.reopen === 'yes') groupDialog.showModal();
}

const importDialog = document.querySelector('#import-data-dialog');
if (importDialog) {
  document.querySelector('[data-open-import]').addEventListener('click', () => {
    document.querySelector('.data-import-menu').open = false;
    importDialog.showModal();
  });
  importDialog.querySelectorAll('[data-close-import]').forEach(button => button.addEventListener('click', () => importDialog.close()));
}
const groupSearch = document.querySelector('[data-search-groups]');
if (groupSearch) groupSearch.addEventListener('input', () => {
  document.querySelectorAll('.data-group-link').forEach(link => { link.hidden = !link.textContent.toLocaleLowerCase('vi').includes(groupSearch.value.toLocaleLowerCase('vi')); });
});
const selectPage = document.querySelector('[data-select-page]');
if (selectPage) {
  const choices = Array.from(document.querySelectorAll('[name=contact_ids]'));
  function updateSelection() {
    const count = choices.filter(choice => choice.checked).length;
    document.querySelector('[data-selection-summary]').textContent = count ? `Đã chọn ${count} data` : 'Chọn data để xuất file';
    document.querySelector('[data-export-selected]').disabled = count === 0;
    selectPage.checked = count > 0 && count === choices.length;
    selectPage.indeterminate = count > 0 && count < choices.length;
  }
  selectPage.addEventListener('change', () => { choices.forEach(choice => choice.checked = selectPage.checked); updateSelection(); });
  choices.forEach(choice => choice.addEventListener('change', updateSelection));
}
document.querySelectorAll('[data-copy-id]').forEach(button => button.addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(button.dataset.copyId); button.textContent = 'Đã chép ID'; }
  catch { button.textContent = `ID: ${button.dataset.copyId}`; }
}));
const accountFilter = document.querySelector('[data-account-filter]');
if (accountFilter) accountFilter.addEventListener('change', () => accountFilter.form.requestSubmit());

const fileImportForm = document.querySelector('[data-file-import-form]');
if (fileImportForm) {
  const phones = fileImportForm.elements.phones;
  const spreadsheet = fileImportForm.elements.file;
  const save = fileImportForm.querySelector('[data-save-import]');
  const format = fileImportForm.querySelector('[data-format-import]');
  const status = fileImportForm.querySelector('[data-preview-status]');
  const preview = fileImportForm.querySelector('[data-import-preview]');
  const tabs = Array.from(fileImportForm.querySelectorAll('[data-import-tab]'));
  let revision = 0;
  let ready = false;
  function clearPreview(message = 'Dữ liệu đã thay đổi. Bấm Format chuẩn dữ liệu để xem trước.') {
    revision += 1; ready = false; save.disabled = true;
    preview.replaceChildren();
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 8; cell.textContent = 'Chưa có dữ liệu'; row.append(cell); preview.append(row);
    status.textContent = message;
  }
  function activateTab(tab) {
    fileImportForm.dataset.activeTab = tab.dataset.importTab;
    const isText = tab.dataset.importTab === 'txt';
    tabs.forEach(button => { const active = button === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
    const textPanel = fileImportForm.querySelector('#txt-import-panel');
    const filePanel = fileImportForm.querySelector('#file-import-panel');
    textPanel.hidden = !isText; filePanel.hidden = isText;
    filePanel.setAttribute('aria-labelledby', tab.id);
    phones.disabled = !isText; spreadsheet.disabled = isText;
    const mapped = tab.dataset.importTab === 'file';
    fileImportForm.querySelector('[data-customer-mapping]').hidden = !mapped;
    fileImportForm.querySelector('[data-template-help]').hidden = mapped;
    fileImportForm.querySelector('[data-template-downloads]').hidden = mapped;
    format.hidden = tab.dataset.importTab === 'template';
    fileImportForm.elements.import_mode.disabled = !mapped;
    fileImportForm.elements.skip_header.disabled = !mapped;
    fileImportForm.querySelectorAll('[data-column-field]').forEach(select => select.disabled = !mapped);
    clearPreview();
    if (mapped && spreadsheet.files.length) inspectColumns();
    else if (!isText && spreadsheet.files.length) formatImport();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
      else if (event.key === 'ArrowLeft') next = tabs[(index + tabs.length - 1) % tabs.length];
      else if (event.key === 'Home') next = tabs[0];
      else if (event.key === 'End') next = tabs[tabs.length - 1];
      if (next) { event.preventDefault(); activateTab(next); next.focus(); }
    });
  });
  phones.addEventListener('input', () => clearPreview());
  let sheetColumns = [];
  function fillColumns(autoSelect = false) {
    const aliases = { name: ['name','ten','ho ten','fullname','full name'], phone: ['phone','sdt','so dien thoai','phone number','mobile'] };
    fileImportForm.querySelectorAll('[data-column-field]').forEach(select => {
      const previous = select.value;
      select.replaceChildren(new Option('— Bỏ qua —', ''));
      sheetColumns.forEach(column => {
        const label = `Cột ${column.index + 1}${column.sample ? ': ' + column.sample : ''}`;
        select.add(new Option(label, String(column.index)));
      });
      if (!autoSelect) select.value = previous;
      else if (fileImportForm.elements.skip_header.checked) {
        const field = select.dataset.columnField;
        const found = sheetColumns.find(column => {
          const normalized = column.sample.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim().replace(/đ/g, 'd');
          return (aliases[field] || [field, field.replace('info', 'info ')]).includes(normalized);
        });
        if (found) select.value = String(found.index);
      }
    });
  }
  async function inspectColumns() {
    clearPreview('Đang đọc cột từ tệp…');
    sheetColumns = []; fillColumns(true);
    const current = revision;
    const file = spreadsheet.files[0];
    if (!file) return;
    fileImportForm.querySelector('[data-upload-filename]').textContent = file.name;
    if (file.size > 2 * 1024 * 1024) { status.textContent = 'Tệp không vượt quá 2 MB.'; return; }
    format.disabled = true;
    try {
      const response = await fetch(fileImportForm.dataset.columnsUrl, {method: 'POST', body: new FormData(fileImportForm)});
      const data = await response.json();
      if (current !== revision) return;
      if (!response.ok) throw new Error(data.error || 'Không đọc được cột trong tệp.');
      sheetColumns = data.columns; fillColumns(true);
      status.textContent = 'Đã đọc tệp. Kiểm tra dòng tiêu đề và chọn cột, rồi bấm Format chuẩn dữ liệu.';
    } catch (error) { if (current === revision) status.textContent = error instanceof SyntaxError ? 'Không đọc được phản hồi. Tải lại trang rồi thử lại.' : error.message; }
    finally { format.disabled = false; }
  }
  spreadsheet.addEventListener('change', () => {
    clearPreview();
    fileImportForm.querySelector('[data-upload-filename]').textContent = spreadsheet.files[0]?.name || 'Chưa chọn tệp.';
    if (!fileImportForm.elements.import_mode.disabled) inspectColumns();
    else if (spreadsheet.files.length) formatImport();
  });
  fileImportForm.elements.skip_header.addEventListener('change', () => clearPreview());
  fileImportForm.querySelectorAll('[data-column-field]').forEach(select => select.addEventListener('change', () => clearPreview()));
  fileImportForm.querySelector('[data-txt-upload]').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    clearPreview();
    const current = revision;
    if (file.size > 2 * 1024 * 1024) { status.textContent = 'Tệp TXT không vượt quá 2 MB.'; event.target.value = ''; return; }
    try {
      const text = await file.text();
      if (current !== revision) return;
      if (text.length > 15000) { status.textContent = 'Danh sách số điện thoại quá dài (tối đa 15.000 ký tự).'; return; }
      phones.value = text.replace(/^\uFEFF/, ''); clearPreview('Đã đọc file TXT. Bấm Format chuẩn dữ liệu.');
    } catch { status.textContent = 'Không đọc được file TXT. Vui lòng dùng UTF-8.'; }
    finally { event.target.value = ''; }
  });
  async function formatImport() {
    clearPreview('Đang kiểm tra dữ liệu…');
    const current = revision;
    format.disabled = true;
    try {
      const response = await fetch(fileImportForm.dataset.previewUrl, { method: 'POST', body: new FormData(fileImportForm), headers: { 'Accept': 'application/json' } });
      const data = await response.json();
      if (current !== revision) return;
      if (!response.ok) throw new Error(data.error || 'Không kiểm tra được dữ liệu. Tải lại trang và thử lại.');
      preview.replaceChildren();
      data.rows.forEach((item, index) => {
        const row = document.createElement('tr');
        [index + 1, item.name, item.phone, item.info1, item.info2, item.info3, item.info4, item.info5].forEach(value => {
          const cell = document.createElement('td'); cell.textContent = value || '—'; row.append(cell);
        });
        preview.append(row);
      });
      status.textContent = `${data.total} số hợp lệ · ${data.added} số mới · ${data.existing} số đã có sẽ bỏ qua.`;
      ready = data.total > 0; save.disabled = !ready;
    } catch (error) { if (current === revision) status.textContent = error instanceof SyntaxError ? 'Phiên làm việc hết hạn hoặc máy chủ không trả dữ liệu. Tải lại trang.' : error.message; }
    finally { format.disabled = false; }
  }
  format.addEventListener('click', formatImport);
  const dropzone = fileImportForm.querySelector('[data-spreadsheet-dropzone]');
  dropzone.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); spreadsheet.click(); } });
  ['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove('dragging'); }));
  dropzone.addEventListener('drop', event => {
    if (event.dataTransfer.files.length !== 1) { clearPreview('Chọn một file Excel/CSV mỗi lần.'); return; }
    spreadsheet.files = event.dataTransfer.files; spreadsheet.dispatchEvent(new Event('change'));
  });
  fileImportForm.addEventListener('submit', event => { if (!ready) { event.preventDefault(); status.textContent = 'Bấm Format chuẩn dữ liệu trước khi thêm vào nhóm.'; } });
}
