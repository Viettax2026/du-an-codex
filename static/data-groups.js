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
