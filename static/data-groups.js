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
