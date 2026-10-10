const dialog = document.querySelector('#campaign-dialog');
const openDialog = () => dialog.showModal();
document.querySelector('#new-campaign').addEventListener('click', openDialog);
document.querySelectorAll('[data-open-campaign]').forEach(button => button.addEventListener('click', openDialog));
['close-dialog', 'cancel-dialog'].forEach(id => document.getElementById(id).addEventListener('click', () => dialog.close()));
if (location.hash === '#new') openDialog();

const filters = document.querySelector('#filters');
filters.querySelectorAll('select').forEach(select => select.addEventListener('change', () => filters.requestSubmit()));
const rows = [...document.querySelectorAll('.row-checkbox')];
const all = document.getElementById('select-all');
function updateSelection() {
  const count = rows.filter(row => row.checked).length;
  all.checked = rows.length > 0 && count === rows.length;
  all.indeterminate = count > 0 && count < rows.length;
  document.getElementById('selection-count').textContent = count ? `Đã chọn ${count}` : '';
  rows.forEach(row => row.closest('tr').classList.toggle('is-checked', row.checked));
}
all.disabled = rows.length === 0;
all.addEventListener('change', () => { rows.forEach(row => row.checked = all.checked); updateSelection(); });
rows.forEach(row => row.addEventListener('change', updateSelection));

const tabs = [...document.querySelectorAll('.progress-tab')];
function activateTab(tab) {
  tabs.forEach(button => {
    const active = button === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    document.getElementById(button.getAttribute('aria-controls')).hidden = !active;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activateTab(tab));
  tab.addEventListener('keydown', event => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + 1) % tabs.length];
      activateTab(next); next.focus();
    }
  });
});
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const status = document.getElementById('copy-status');
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    status.textContent = 'Đã sao chép. Hãy tự chọn đúng người nhận trong Zalo.';
  } catch {
    status.textContent = 'Trình duyệt chưa cho phép sao chép. Bạn có thể chọn và sao chép nội dung bằng tay.';
  }
}));
