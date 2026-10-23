const copyKey = document.querySelector('[data-copy-api-key]');
copyKey?.addEventListener('click', async () => {
  const input = document.querySelector('[data-new-api-key]');
  const status = document.querySelector('[data-key-copy-status]');
  try {
    await navigator.clipboard.writeText(input.value);
    status.textContent = ' Đã sao chép.';
  } catch {
    input.focus(); input.select();
    status.textContent = ' Nhấn Ctrl+C để sao chép khóa đã chọn.';
  }
});
