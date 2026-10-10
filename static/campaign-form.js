document.querySelectorAll('.campaign-wizard').forEach(form => {
  const content = form.querySelector('[name=message]');
  const preview = form.querySelector('[data-message-preview]');
  const phones = form.querySelector('[name=phones]');
  const consent = form.querySelector('[name=phones_consent]');
  function update() {
    preview.textContent = content.value.replaceAll('{{name}}', 'Lan') || 'Nhập nội dung để xem trước.';
    consent.required = Boolean(phones.value.trim());
  }
  content.addEventListener('input', update);
  phones.addEventListener('input', update);
  update();
});
