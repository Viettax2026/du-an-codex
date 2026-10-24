const contactChoices = [...document.querySelectorAll('[data-contact-choice]')];
const selectAllContacts = document.querySelector('[data-select-all-contacts]');
if (selectAllContacts) {
  function updateContactSelection() {
    const selected = contactChoices.filter(input => input.checked).map(input => Number(input.value));
    document.querySelector('[data-selected-contact-ids]').value = JSON.stringify(selected);
    document.querySelector('[data-contact-selection-count]').textContent = selected.length>10000 ? 'Chọn tối đa 10.000 khách hàng mỗi lần.' : selected.length ? `Đã chọn ${selected.length.toLocaleString('vi-VN')} khách hàng` : 'Chọn khách hàng để sửa hoặc xóa';
    document.querySelectorAll('[data-contact-bulk]').forEach(button => button.disabled=!selected.length || selected.length>10000);
    selectAllContacts.checked = contactChoices.length>0 && selected.length===contactChoices.length;
    selectAllContacts.indeterminate = selected.length>0 && selected.length<contactChoices.length;
    contactChoices.forEach(input => input.closest('tr').classList.toggle('is-selected',input.checked));
  }
  selectAllContacts.addEventListener('change',()=>{contactChoices.forEach(input=>input.checked=selectAllContacts.checked);updateContactSelection();});
  contactChoices.forEach(input=>input.addEventListener('change',updateContactSelection));
  updateContactSelection();
}
