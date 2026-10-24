(() => {
  const settings = document.querySelector('[data-exclusion-settings]');
  if (!settings) return;
  const ruleDialog = document.querySelector('#exclusion-rule-dialog');
  const listDialog = document.querySelector('#exclusion-list-dialog');
  const rules = settings.querySelector('[data-exclusion-rule-select]');
  const options = settings.querySelector('[data-exclusion-list-options]');
  const catalog = new Map(JSON.parse(settings.dataset.exclusionCatalog).map(item => [String(item.id),item]));
  const editor = listDialog.querySelector('[data-exclusion-list-editor]');
  function selection() {
    const selected = [...options.querySelectorAll('input:checked')].map(input => input.closest('label').querySelector('[data-list-name]').textContent);
    settings.querySelector('[data-exclusion-list-summary]').textContent = selected.length ? selected.join(', ') : 'Chọn một hoặc nhiều danh sách';
  }
  options.addEventListener('change', selection);
  settings.querySelector('[data-open-exclusion-rule]').addEventListener('click', () => ruleDialog.showModal());
  settings.querySelector('[data-open-exclusion-list]').addEventListener('click', () => {
    settings.querySelector('.exclusion-list-picker').open = false;
    listDialog.showModal();
  });
  document.querySelectorAll('[data-close-exclusion-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  editor.addEventListener('change', () => {
    const form = editor.form;
    const item = catalog.get(editor.value);
    form.elements.name.value = item?.name || '';
    form.elements.phones.value = item?.phones || '';
    form.elements.uids.value = item?.uids || '';
  });
  async function save(event, onSuccess) {
    event.preventDefault();
    const form = event.currentTarget;
    const error = form.querySelector('[data-exclusion-error]');
    const button = form.querySelector('[type=submit]');
    error.hidden = true; button.disabled = true;
    try {
      const response = await fetch(form.action, {method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Chưa lưu được. Kiểm tra lại dữ liệu.');
      onSuccess(result,form);
    } catch (failure) {
      error.textContent = failure instanceof SyntaxError ? 'Phiên làm việc hết hạn hoặc máy chủ chưa phản hồi. Tải lại trang sau khi lưu nội dung đang nhập.' : failure.message;
      error.hidden = false;
    } finally { button.disabled = false; }
  }
  ruleDialog.querySelector('form').addEventListener('submit', event => save(event, (item,form) => {
    rules.add(new Option(item.name,String(item.id),false,true));
    settings.querySelector('[data-exclusion-rule-count]').textContent = rules.options.length-1;
    settings.querySelector('[data-exclusion-rule-hint]').textContent = 'Khách hàng khớp ít nhất một điều kiện trong nhóm sẽ được loại trừ.';
    rules.dispatchEvent(new Event('change',{bubbles:true}));
    form.reset(); ruleDialog.close();
  }));
  listDialog.querySelector('form').addEventListener('submit', event => save(event, item => {
    const id = String(item.id);
    const isNew = !catalog.has(id);
    catalog.set(id,item);
    let option = [...editor.options].find(option => option.value===id);
    if (!option) { option = new Option(item.name,id); editor.add(option); }
    option.textContent = item.name; editor.value = id;
    let label = [...options.querySelectorAll('input')].find(input => input.value===id)?.closest('label');
    if (!label) {
      options.querySelector('[data-exclusion-empty-list]')?.remove();
      label = document.createElement('label');
      const input = document.createElement('input'); input.type='checkbox'; input.name='exclusion_list_ids'; input.value=id; input.checked=isNew;
      const name = document.createElement('span'); name.dataset.listName='';
      const count = document.createElement('small'); count.dataset.listTotal='';
      label.append(input,name,count); options.append(label);
    }
    label.querySelector('[data-list-name]').textContent = item.name;
    label.querySelector('[data-list-total]').textContent = `${item.total} số/ID`;
    selection(); options.dispatchEvent(new Event('change',{bubbles:true})); listDialog.close();
  }));
  selection();
})();
