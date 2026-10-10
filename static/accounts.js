document.getElementById('add-account').addEventListener('click', () => document.getElementById('account-dialog').showModal());
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.close).close()));
document.querySelectorAll('[data-connect-name]').forEach(button => button.addEventListener('click', () => {
  document.getElementById('connect-name').textContent = button.dataset.connectName;
  document.getElementById('connect-dialog').showModal();
}));
