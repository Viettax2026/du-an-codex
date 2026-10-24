
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
    consent.required = form.elements.data_mode.value === 'direct' && Boolean(phones.value.trim() || form.elements.data_file.files.length);
    content.required = messageEnabled.checked && !form.querySelector('[data-message-composer].is-enhanced');
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
    if (picker.closest('[data-message-composer]')) return;
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

document.querySelectorAll('.campaign-wizard').forEach(form => {
  const phones = form.elements.phones;
  const direct = form.querySelector('[data-direct-data]');
  const group = form.querySelector('[data-group-data]');
  function updateDataSource() {
    const isDirect = form.elements.data_mode.value === 'direct';
    direct.hidden = !isDirect;
    group.hidden = isDirect;
    direct.querySelectorAll('input,select,textarea,button').forEach(el => el.disabled = !isDirect || el.dataset.snapshotDisabled === 'true');
    group.querySelectorAll('select').forEach(el => { el.disabled = isDirect; el.required = !isDirect; });
    form.elements.phones_consent.required = isDirect && Boolean(phones.value.trim() || form.elements.data_file.files.length);
    const count = new Set(phones.value.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean)).size;
    let snapshotCount = 0;
    try { snapshotCount = JSON.parse(form.elements.source_contact_ids.value || '[]').length; } catch { /* Server validates malformed IDs. */ }
    form.querySelector('[data-phone-count]').textContent = `${count} số nhập tay · ${snapshotCount} data từ nhóm`;
  }
  form.querySelectorAll('[name=data_mode]').forEach(el => el.addEventListener('change', updateDataSource));
  phones.addEventListener('input', updateDataSource);
  form.elements.data_file.addEventListener('change', updateDataSource);
  form.elements.source_contact_ids.addEventListener('change', updateDataSource);
  form.querySelector('[data-focus-phones]').addEventListener('click', () => phones.focus());
  form.querySelector('[data-clear-data]').addEventListener('click', () => {
    if (!window.confirm('Xóa danh sách nhập, tệp và nhóm đã chọn trong biểu mẫu này?')) return;
    phones.value = ''; form.elements.data_file.value = '';
    form.dispatchEvent(new Event('campaign-clear-snapshot'));
    updateDataSource();
  });
  updateDataSource();
});

// Summarize the fields in each step without changing submission requirements.
document.querySelectorAll('.campaign-wizard').forEach(form => {
  const sections = form.querySelector('.wizard-sections');
  const steps = [...form.querySelectorAll('[data-wizard-step]')];
  const cards = [...sections.querySelectorAll('.wizard-card')];
  function activate(target) {
    steps.forEach(step => {
      const active = step.dataset.wizardStep === target;
      step.classList.toggle('is-active', active);
      if (active) step.setAttribute('aria-current', 'step');
      else step.removeAttribute('aria-current');
    });
  }
  function openCard(card) {
    card.querySelector('[data-wizard-toggle]').setAttribute('aria-expanded', 'true');
    card.querySelector('.wizard-card-body').hidden = false;
  }
  function goToCard(card) {
    openCard(card);
    const top = card.getBoundingClientRect().top - sections.getBoundingClientRect().top + sections.scrollTop - 8;
    sections.scrollTo({top:Math.max(0,top),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    activate(card.id.replace('wizard-', ''));
  }
  steps.forEach(step => step.addEventListener('click', event => {
    event.preventDefault();
    goToCard(form.querySelector(step.getAttribute('href')));
  }));
  form.querySelectorAll('[data-wizard-toggle]').forEach(button => button.addEventListener('click', () => {
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    form.querySelector('#' + button.getAttribute('aria-controls')).hidden = expanded;
  }));
  let scrollFrame = null;
  sections.addEventListener('scroll', () => {
    if (scrollFrame !== null) return;
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = null;
      const top = sections.getBoundingClientRect().top + 40;
      let active = cards[0];
      cards.forEach(card => { if (card.getBoundingClientRect().top <= top) active = card; });
      activate(active.id.replace('wizard-', ''));
    });
  }, {passive:true});
  function hasValidPhones() {
    const raw = form.elements.phones.value.trim();
    if (!raw) return false;
    const phones = raw.split(/[\n,;]+/).map(value => {
      let phone = value.replace(/[\s().+-]/g, '');
      if (phone.startsWith('84')) phone = '0' + phone.slice(2);
      return phone;
    }).filter(Boolean);
    return phones.length>0 && new Set(phones).size<=500 && phones.every(phone => /^0[0-9]{9}$/.test(phone));
  }
  function completion() {
    const fields = form.elements;
    const direct = fields.data_mode.value === 'direct';
    const validPhones = hasValidPhones();
    let snapshotCount = 0;
    try { snapshotCount = JSON.parse(fields.source_contact_ids.value || '[]').length; } catch { /* Server validates IDs. */ }
    const hasData = (!fields.phones.value.trim() || validPhones) && (validPhones || fields.data_file.files.length>0 || snapshotCount>0);
    const needsConsent = Boolean(fields.phones.value.trim() || fields.data_file.files.length);
    const actionsValid = (fields.send_message.checked || fields.send_friend.checked) &&
      (!fields.send_friend.checked || (fields.friend_message.value.trim().length>0 && fields.friend_message.validity.valid)) &&
      (!fields.rename_enabled.checked || (fields.rename_template.value.trim().length>0 && fields.rename_template.validity.valid));
    const states = {
      action:Boolean(fields.action.value), account:Boolean(fields.account_id.value),
      name:Boolean(fields.name.value.trim()) && fields.name.validity.valid, actions:actionsValid,
      source:['direct','group'].includes(fields.data_mode.value),
      phones:direct ? hasData && (!needsConsent || fields.phones_consent.checked) : Boolean(fields.tag.value),
      media:fields.media_mode?.value === 'none' || Boolean(fields.media.files.length || fields.library_media_id.value || form.querySelector('[data-message-composer]').dataset.initialMedia !== 'null'),
      message:!fields.send_message.checked || (Boolean(fields.message.value.trim()) && fields.message.validity.valid)
    };
    steps.forEach(step => {
      const items = [...step.querySelectorAll('[data-wizard-check]')];
      let count = 0;
      items.forEach(item => {
        const done = Boolean(states[item.dataset.wizardCheck]);
        item.classList.toggle('is-done', done);
        if (done) count += 1;
      });
      const complete = count===items.length;
      step.classList.toggle('is-complete', complete);
      const marker = step.querySelector('[data-step-number]');
      marker.textContent = complete ? '✓' : marker.dataset.stepNumber;
      const badge = step.querySelector('[data-step-count]');
      badge.textContent = `${count} / ${items.length}`;
      badge.setAttribute('aria-label', `Đã điền ${count} trên ${items.length} mục`);
    });
  }
  form.addEventListener('input', completion);
  form.addEventListener('change', completion);
  form.querySelector('[data-clear-data]')?.addEventListener('click', completion);
  // Required fields remain reachable even when their section is collapsed.
  let invalidFrame = null;
  form.addEventListener('invalid', event => {
    const card = event.target.closest('.wizard-card');
    if (!card) return;
    openCard(card);
    if (invalidFrame === null) invalidFrame = requestAnimationFrame(() => {
      invalidFrame = null;
      goToCard(card);
      event.target.focus({preventScroll:true});
    });
  }, true);
  completion();
});
