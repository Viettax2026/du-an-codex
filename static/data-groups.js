const groupDialog = document.querySelector('#create-group-dialog');
if (groupDialog) {
  const opener = document.querySelector('[data-open-group]');
  const nameInput = groupDialog.querySelector('[name=name]');
  const createButton = groupDialog.querySelector('[data-create-group]');
  function updateGroupButton() { createButton.disabled = !nameInput.value.trim(); }
  const groupForm = groupDialog.querySelector('form');
  function setGroupMode(editing, name = '', type = 'all', color = '#6860f6') {
    groupForm.action = editing ? groupForm.dataset.editUrl : groupForm.dataset.createUrl;
    groupForm.elements.original_group.value = editing ? name : '';
    nameInput.value = name; groupForm.elements.data_type.value = type; groupForm.elements.color.value = color;
    groupDialog.querySelector('#group-dialog-title').textContent = editing ? 'Sửa nhóm data' : 'Tạo nhóm data';
    createButton.textContent = editing ? 'Lưu thay đổi' : 'Tạo nhóm';
    updateGroupButton(); groupDialog.showModal();
  }
  opener.addEventListener('click', () => setGroupMode(false));
  document.querySelectorAll('[data-edit-group]').forEach(button => button.addEventListener('click', () => setGroupMode(true, button.dataset.editGroup, button.dataset.groupType, button.dataset.groupEditColor)));
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
  document.querySelectorAll('.data-group-row').forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase('vi').includes(groupSearch.value.toLocaleLowerCase('vi')); });
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
  const feedback = document.querySelector('[data-copy-feedback]');
  try { await navigator.clipboard.writeText(button.dataset.copyId); if (feedback) { feedback.textContent = `Đã sao chép ID ${button.dataset.copyId}`; feedback.hidden = false; } }
  catch { if (feedback) { feedback.textContent = `ID nhóm: ${button.dataset.copyId} — bạn có thể sao chép số này.`; feedback.hidden = false; } }
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
  let invalidCount = 0;
  const invalidPanel = fileImportForm.querySelector('[data-import-invalid]');
  const invalidBody = fileImportForm.querySelector('[data-import-invalid-rows]');
  const skipInvalid = fileImportForm.elements.skip_invalid;
  function updateSaveButton() { save.disabled = !ready || (invalidCount > 0 && !skipInvalid.checked); }
  skipInvalid.addEventListener('change', updateSaveButton);
  let normalizedRows = [];
  let normalizedPage = 1;
  const normalizedPageSize = 100;
  const range = fileImportForm.querySelector('[data-import-range]');
  const pager = fileImportForm.querySelector('[data-import-pagination]');
  const previousPage = fileImportForm.querySelector('[data-import-prev]');
  const nextPage = fileImportForm.querySelector('[data-import-next]');
  function renderNormalizedPage() {
    const pages = Math.max(1, Math.ceil(normalizedRows.length / normalizedPageSize));
    normalizedPage = Math.max(1, Math.min(normalizedPage, pages));
    const start = (normalizedPage - 1) * normalizedPageSize;
    const end = Math.min(start + normalizedPageSize, normalizedRows.length);
    preview.replaceChildren();
    normalizedRows.slice(start, end).forEach((item, index) => {
      const row = document.createElement('tr');
      [start + index + 1, item.name, item.phone, item.info1, item.info2, item.info3, item.info4, item.info5].forEach(value => {
        const cell = document.createElement('td'); cell.textContent = value || ''; row.append(cell);
      });
      preview.append(row);
    });
    range.textContent = `Hiển thị ${normalizedRows.length ? start + 1 : 0}–${end} / ${normalizedRows.length} data`;
    range.hidden = false; pager.hidden = false;
    fileImportForm.querySelector('[data-import-page]').textContent = `Trang ${normalizedPage}/${pages}`;
    previousPage.disabled = normalizedPage === 1;
    nextPage.disabled = normalizedPage === pages;
    preview.closest('.data-import-preview').scrollTop = 0;
  }
  previousPage.addEventListener('click', () => { normalizedPage -= 1; renderNormalizedPage(); });
  nextPage.addEventListener('click', () => { normalizedPage += 1; renderNormalizedPage(); });
  function clearPreview(message = 'Dữ liệu đã thay đổi. Bấm Format chuẩn dữ liệu để xem trước.') {
    revision += 1; ready = false; save.disabled = true;
    format.disabled = false;
    invalidCount = 0; invalidPanel.hidden = true; invalidBody.replaceChildren(); skipInvalid.checked = false;
    normalizedRows = []; normalizedPage = 1; range.hidden = true; pager.hidden = true;
    preview.replaceChildren();
    const row = document.createElement('tr'); const cell = document.createElement('td');
    cell.colSpan = 8; cell.textContent = 'Chưa có dữ liệu'; row.append(cell); preview.append(row);
    status.textContent = message;
  }
  function activateTab(tab) {
    inspectionRevision += 1;
    fileImportForm.dataset.activeTab = tab.dataset.importTab;
    const isText = tab.dataset.importTab === 'txt';
    tabs.forEach(button => { const active = button === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
    const textPanel = fileImportForm.querySelector('#txt-import-panel');
    const filePanel = fileImportForm.querySelector('#file-import-panel');
    textPanel.hidden = !isText; filePanel.hidden = isText;
    filePanel.setAttribute('aria-labelledby', tab.id);
    phones.disabled = !isText; spreadsheet.disabled = isText;
    const mapped = tab.dataset.importTab === 'file';
    fileImportForm.querySelector('[data-customer-mapping]').hidden = !mapped || !sheetColumns.length;
    sheetSelect.disabled = !mapped || !sheetSelect.options.length;
    fileImportForm.querySelector('[data-template-help]').hidden = mapped;
    fileImportForm.querySelector('[data-template-downloads]').hidden = mapped;
    format.hidden = tab.dataset.importTab === 'template';
    fileImportForm.elements.import_mode.disabled = !mapped;
    fileImportForm.elements.skip_header.disabled = !mapped;
    fileImportForm.querySelectorAll('[data-column-field]').forEach(select => select.disabled = !mapped);
    clearPreview();
    renderRawPreview();
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
  let sheetPreviewRows = [];
  let inspectionRevision = 0;
  const sheetChoice = fileImportForm.querySelector('[data-sheet-choice]');
  const sheetSelect = fileImportForm.elements.sheet;
  const rawPreview = fileImportForm.querySelector('[data-raw-sheet-preview]');
  function columnLetter(index) {
    let value = index + 1; let label = '';
    while (value > 0) { value -= 1; label = String.fromCharCode(65 + value % 26) + label; value = Math.floor(value / 26); }
    return label;
  }
  function renderRawPreview() {
    const head = fileImportForm.querySelector('[data-raw-sheet-head]');
    const body = fileImportForm.querySelector('[data-raw-sheet-body]');
    head.replaceChildren(); body.replaceChildren();
    rawPreview.hidden = sheetColumns.length === 0 || fileImportForm.elements.import_mode.disabled;
    if (rawPreview.hidden) return;
    const header = document.createElement('tr');
    sheetColumns.forEach(column => { const cell = document.createElement('th'); cell.textContent = columnLetter(column.index); header.append(cell); });
    head.append(header);
    const start = fileImportForm.elements.skip_header.checked ? 1 : 0;
    const rows = sheetPreviewRows.slice(start, start + 5);
    rows.forEach(values => {
      const row = document.createElement('tr');
      sheetColumns.forEach(column => { const cell = document.createElement('td'); cell.textContent = values[column.index] || ''; row.append(cell); });
      body.append(row);
    });
    if (!rows.length) { const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = sheetColumns.length; cell.textContent = 'Không có dòng data sau khi bỏ tiêu đề.'; row.append(cell); body.append(row); }
  }
  function fillColumns(mapping = {}) {
    fileImportForm.querySelectorAll('[data-column-field]').forEach(select => {
      select.replaceChildren(new Option('— Bỏ qua —', ''));
      sheetColumns.forEach(column => {
        const option = new Option(columnLetter(column.index), String(column.index));
        option.title = column.sample; select.add(option);
      });
      select.value = mapping[select.dataset.columnField] || '';
    });
  }
  async function inspectColumns() {
    const inspection = ++inspectionRevision;
    clearPreview('Đang đọc cột từ tệp…');
    sheetColumns = []; sheetPreviewRows = []; renderRawPreview(); fillColumns();
    fileImportForm.querySelector('[data-customer-mapping]').hidden = true;
    const file = spreadsheet.files[0];
    if (!file) return;
    fileImportForm.querySelector('[data-upload-filename]').textContent = file.name;
    if (file.size > 2 * 1024 * 1024) { status.textContent = 'Tệp không vượt quá 2 MB.'; return; }
    format.disabled = true;
    try {
      const response = await fetch(fileImportForm.dataset.columnsUrl, {method: 'POST', body: new FormData(fileImportForm)});
      const data = await response.json();
      if (inspection !== inspectionRevision || spreadsheet.files[0] !== file || fileImportForm.elements.import_mode.disabled) return;
      if (!response.ok) throw new Error(data.error || 'Không đọc được cột trong tệp.');
      sheetColumns = data.columns; sheetPreviewRows = data.preview_rows;
      sheetSelect.replaceChildren(...data.sheets.map(name => new Option(name, name)));
      sheetSelect.value = data.sheet; sheetSelect.disabled = !data.sheets.length; sheetChoice.hidden = !data.sheets.length;
      fileImportForm.elements.skip_header.checked = data.skip_header;
      fillColumns(data.mapping);
      fileImportForm.querySelector('[data-customer-mapping]').hidden = false;
      renderRawPreview();
      status.textContent = 'Đã đọc tệp và chọn cột Số điện thoại. Kiểm tra dữ liệu nguồn, rồi bấm Format chuẩn dữ liệu.';
    } catch (error) { if (inspection === inspectionRevision && spreadsheet.files[0] === file && !fileImportForm.elements.import_mode.disabled) status.textContent = error instanceof SyntaxError ? 'Không đọc được phản hồi. Tải lại trang rồi thử lại.' : error.message; }
    finally { if (inspection === inspectionRevision) format.disabled = false; }
  }
  sheetSelect.addEventListener('change', inspectColumns);
  spreadsheet.addEventListener('change', () => {
    inspectionRevision += 1; sheetSelect.replaceChildren(); sheetSelect.disabled = true; sheetChoice.hidden = true;
    clearPreview();
    sheetColumns = []; sheetPreviewRows = []; renderRawPreview();
    fileImportForm.querySelector('[data-upload-filename]').textContent = spreadsheet.files[0]?.name || 'Chưa chọn tệp.';
    if (!fileImportForm.elements.import_mode.disabled) inspectColumns();
    else if (spreadsheet.files.length) formatImport();
  });
  fileImportForm.elements.skip_header.addEventListener('change', () => { clearPreview(); renderRawPreview(); });
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
      normalizedRows = data.rows;
      normalizedPage = 1;
      renderNormalizedPage();
      invalidCount = data.invalid || 0;
      invalidPanel.hidden = invalidCount === 0;
      (data.invalid_rows || []).forEach(item => {
        const row = document.createElement('tr');
        [item.row, item.phone || '(trống)', item.reason].forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); });
        invalidBody.append(row);
      });
      status.textContent = `${data.total} số hợp lệ · ${data.added} số cần thêm vào nhóm · ${data.existing} số đã có trong nhóm · ${invalidCount} dòng lỗi.`;
      ready = data.total > 0; updateSaveButton();
    } catch (error) { if (current === revision) status.textContent = error instanceof SyntaxError ? 'Phiên làm việc hết hạn hoặc máy chủ không trả dữ liệu. Tải lại trang.' : error.message; }
    finally { if (current === revision) format.disabled = false; }
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
  fileImportForm.addEventListener('submit', event => { if (!ready || (invalidCount > 0 && !skipInvalid.checked)) { event.preventDefault(); status.textContent = !ready ? 'Bấm Format chuẩn dữ liệu để có số hợp lệ trước khi thêm vào nhóm.' : 'Xác nhận bỏ qua dòng lỗi hoặc sửa tệp trước khi thêm vào nhóm.'; } });
}

const sourceHistoryDialog = document.querySelector('#source-history-dialog');
if (sourceHistoryDialog) {
  const body = sourceHistoryDialog.querySelector('[data-source-history-body]');
  const title = sourceHistoryDialog.querySelector('#source-history-title');
  let sourceRequest = 0;
  sourceHistoryDialog.querySelectorAll('[data-close-source-history]').forEach(button => button.addEventListener('click', () => sourceHistoryDialog.close()));
  sourceHistoryDialog.addEventListener('close', () => { sourceRequest += 1; });
  document.querySelectorAll('[data-source-history]').forEach(button => button.addEventListener('click', async () => {
    const request = ++sourceRequest;
    body.textContent = 'Đang tải lịch sử nguồn…'; title.textContent = 'Lịch sử nguồn';
    sourceHistoryDialog.showModal();
    try {
      const response = await fetch(button.dataset.sourceHistory, {headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('Không tải được lịch sử nguồn. Vui lòng tải lại trang.');
      const data = await response.json();
      if (request !== sourceRequest) return;
      title.textContent = `Lịch sử nguồn: ${data.phone}`;
      body.replaceChildren();
      if (!data.sources.length) {
        body.textContent = 'Dữ liệu cũ chưa ghi nhận nguồn. Nhập lại tệp gốc vào nhóm này để bổ sung nguồn; thông tin khách hàng được giữ nguyên.';
      }
      data.sources.forEach(source => {
        const card = document.createElement('section'); card.className = 'source-history-card' + (source.current ? ' current' : '');
        const heading = document.createElement('div'); heading.className = 'source-history-card-heading';
        const name = document.createElement('b'); name.textContent = source.source_type === 'scan' ? 'Quét Zalo' : source.source_type === 'file' ? 'Tải file lên' : source.source_type === 'api' ? 'Nhập qua API' : source.source_type === 'direct' ? 'Nhập trực tiếp' : 'Nguồn đã ghi nhận'; heading.append(name);
        if (source.current) { const badge = document.createElement('span'); badge.className = 'data-badge'; badge.textContent = 'Đang dùng'; heading.append(badge); }
        const filename = document.createElement('p'); filename.textContent = source.filename || source.label;
        const details = document.createElement('p'); details.className = 'source-history-time';
        details.textContent = `Thời điểm: ${source.created_at || 'Chưa ghi nhận'}${source.group_id ? ' · Danh sách #' + String(source.group_id).padStart(4, '0') : ''}${source.batch_id ? ' · Lô #' + source.batch_id : ''}`;
        card.append(heading); card.append(filename); card.append(details); body.append(card);
      });
    } catch (error) { if (request === sourceRequest) body.textContent = error instanceof SyntaxError ? 'Phiên làm việc hết hạn. Tải lại trang và đăng nhập.' : error.message; }
  }));
}

const kindFilter = document.querySelector('[data-kind-filter]');
if (kindFilter) kindFilter.addEventListener('change', () => kindFilter.form.requestSubmit());
