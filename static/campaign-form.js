
function samplePersonalization(text) {
  const values = {INPUT_FULLNAME:'Lan', FULL_NAME:'Lan', ORIGINAL_NAME:'Lan', PHONE:'0901234567', EMAIL:'lan@example.com'};
  for (let i=1;i<=5;i++) values['INFO'+i]='Thông tin mẫu '+i;
  const parts = new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Bangkok',day:'2-digit',month:'2-digit',year:'numeric'}).formatToParts(new Date());
  const date = Object.fromEntries(parts.map(p=>[p.type,p.value]));
  return text.replace(/\{\{name\}\}|#\{(SEX\{([^{}]*)\}|TODAY\(([^()]*)\)|[A-Z][A-Z0-9_]*)\}/g,(all,key,sex,fmt)=>{
    if(all==='{{name}}') return 'Lan';
    if(sex!==undefined) return sex.split('-')[2] || '[Xưng hô không hợp lệ]';
    if(fmt!==undefined) return {'DD/MM/YYYY':date.day+'/'+date.month+'/'+date.year,'DD-MM-YYYY':date.day+'-'+date.month+'-'+date.year,'YYYY-MM-DD':date.year+'-'+date.month+'-'+date.day}[fmt] || '[Định dạng ngày không hợp lệ]';
    return values[key] || '[Thiếu '+key+']';
  });
}
document.querySelectorAll('.campaign-wizard').forEach(form => {
  const content = form.querySelector('[name=message]');
  const preview = form.querySelector('[data-message-preview]');
  const phones = form.querySelector('[name=phones]');
  const consent = form.querySelector('[name=phones_consent]');
  const messageEnabled = form.querySelector('[name=send_message]');
  const friendEnabled = form.querySelector('[name=send_friend]');
  const invitation = form.querySelector('[name=friend_message]');
  const rename = form.querySelector('[name=rename_enabled]');
  const alias = form.querySelector('[name=rename_template]');
  rename.addEventListener('change', update);
  alias.addEventListener('input', update);
  function update() {
    alias.required = rename.checked;
    alias.disabled = !rename.checked;
    form.querySelector('[data-alias-preview]').textContent = samplePersonalization(alias.value);
    preview.textContent = samplePersonalization(content.value) || 'Nhập nội dung để xem trước.';
    consent.required = Boolean(phones.value.trim());
    content.required = messageEnabled.checked;
    invitation.required = friendEnabled.checked;
    invitation.disabled = !friendEnabled.checked;
    form.querySelector('[data-friend-preview]').textContent = samplePersonalization(invitation.value) || 'Nhập lời mời để xem trước.';
    form.querySelector('[data-friend-count]').textContent = `${invitation.value.length}/150 ký tự`;
  }
  content.addEventListener('input', update);
  phones.addEventListener('input', update);
  [messageEnabled, friendEnabled].forEach(input => input.addEventListener('change', update));
  invitation.addEventListener('input', update);
  update();
});

document.querySelectorAll('.campaign-wizard').forEach(form => {
  form.querySelectorAll('[data-picker]').forEach(picker => {
    const target = picker.dataset.picker;
    const textarea = form.elements[target];
    const opener = form.querySelector('[data-picker-open="'+target+'"]');
    opener.addEventListener('click', () => {
      picker.hidden = !picker.hidden;
      opener.setAttribute('aria-expanded', String(!picker.hidden));
    });
    picker.querySelector('[data-picker-close]').addEventListener('click', () => {
      picker.hidden = true; opener.setAttribute('aria-expanded','false'); opener.focus();
    });
    function insert(token) {
      if (textarea.disabled) return;
      const start = textarea.selectionStart, end = textarea.selectionEnd;
      if (textarea.value.length - (end-start) + token.length > textarea.maxLength) {
        textarea.setCustomValidity('Nội dung sau chèn vượt giới hạn ký tự.');
        textarea.reportValidity(); textarea.setCustomValidity(''); return;
      }
      textarea.setRangeText(token,start,end,'end');
      textarea.dispatchEvent(new Event('input', {bubbles:true}));
      textarea.focus();
    }
    picker.querySelectorAll('[data-token]').forEach(button => button.addEventListener('click', () => insert(button.dataset.token)));
    picker.querySelector('[data-date-token]').addEventListener('click', () => insert('#{TODAY('+picker.querySelector('[data-date-format]').value+')}'));
  });
});
