document.querySelectorAll('.campaign-action-menu').forEach(menu => {
  const trigger = document.querySelector(`[popovertarget="${menu.id}"]`);
  function position() {
    const bounds = trigger.getBoundingClientRect();
    const width = Math.min(288, window.innerWidth - 24);
    menu.style.width = `${width}px`;
    const height = Math.min(menu.scrollHeight, window.innerHeight - 24);
    menu.style.left = `${Math.max(12, Math.min(bounds.right - width, window.innerWidth - width - 12))}px`;
    menu.style.top = `${Math.max(12, Math.min(bounds.bottom + 8, window.innerHeight - height - 12))}px`;
  }
  menu.addEventListener('toggle', event => { if (event.newState === 'open') position(); });
  window.addEventListener('resize', () => { if (menu.matches(':popover-open')) position(); });
  document.querySelector('.campaign-table-scroll')?.addEventListener('scroll', () => { if (menu.matches(':popover-open')) position(); });
  window.addEventListener('scroll', () => { if (menu.matches(':popover-open')) position(); }, {passive: true});
});
document.querySelectorAll('[data-copy-campaign]').forEach(button => button.addEventListener('click', async () => {
  const id = button.dataset.copyCampaign;
  try {
    await navigator.clipboard.writeText(id);
    document.getElementById('campaign-action-status').textContent = `Đã sao chép ID chiến dịch: ${id}`;
    button.closest('[popover]').hidePopover();
  } catch {
    document.getElementById('campaign-action-status').textContent = `ID chiến dịch: ${id}. Trình duyệt chưa cho phép sao chép, bạn có thể chọn ID này để sao chép bằng tay.`;
  }
}));
