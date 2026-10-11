document.querySelectorAll('.campaign-wizard').forEach(form => {
  const content = form.querySelector('[name=message]');
  const preview = form.querySelector('[data-message-preview]');
  const phones = form.querySelector('[name=phones]');
  const consent = form.querySelector('[name=phones_consent]');
  const messageEnabled = form.querySelector('[name=send_message]');
  const friendEnabled = form.querySelector('[name=send_friend]');
  const invitation = form.querySelector('[name=friend_message]');
  function update() {
    preview.textContent = content.value.replaceAll('{{name}}', 'Lan') || 'Nhập nội dung để xem trước.';
    consent.required = Boolean(phones.value.trim());
    content.required = messageEnabled.checked;
    invitation.required = friendEnabled.checked;
    invitation.disabled = !friendEnabled.checked;
    form.querySelector('[data-friend-preview]').textContent = invitation.value.replaceAll('{{name}}', 'Lan') || 'Nhập lời mời để xem trước.';
    form.querySelector('[data-friend-count]').textContent = `${invitation.value.length}/150 ký tự`;
  }
  content.addEventListener('input', update);
  phones.addEventListener('input', update);
  [messageEnabled, friendEnabled].forEach(input => input.addEventListener('change', update));
  invitation.addEventListener('input', update);
  update();
});
