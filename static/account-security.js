document.querySelectorAll('.password-toggle').forEach(button => {
  const showLabel = button.getAttribute('aria-label');
  button.addEventListener('click', () => {
    const input = button.parentElement.querySelector('input');
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.textContent = visible ? 'Ẩn' : 'Hiện';
    button.setAttribute('aria-pressed', String(visible));
    button.setAttribute('aria-label', visible ? showLabel.replace('Hiện', 'Ẩn') : showLabel);
  });
});
document.querySelector('[data-download-recovery]')?.addEventListener('click', event => {
  const code = document.getElementById('issued-recovery-code').textContent;
  const username = event.currentTarget.dataset.username;
  const source = event.currentTarget.dataset.source;
  const text = `ZaloFlow — Mã khôi phục tài khoản\nNguồn: ${source}\nTài khoản: ${username}\nMã: ${code}\n\nDùng một lần tại “Quên mật khẩu?”. Giữ riêng tư; không gửi mã cho người khác.\nMã này chỉ dùng cho bản ZaloFlow đã tạo mã.\n`;
  const url = URL.createObjectURL(new Blob([text], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `ZaloFlow-ma-khoi-phuc-${username.replace(/[^a-z0-9_.-]/gi, '_')}.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
