document.querySelectorAll('[data-schedule-fields]').forEach(root=>{
  const form=root.closest('form'),fields=form.elements;
  const enabled=fields.schedule_enabled,options=root.querySelector('[data-schedule-options]');
  const status=root.querySelector('[data-schedule-error]'),footer=form.querySelector('[data-schedule-footer]');
  const weekdays=root.querySelector('[data-schedule-weekdays]'),monthday=root.querySelector('[data-schedule-monthday]');
  function update(){
    const on=enabled.checked,kind=fields.schedule_kind.value;
    options.querySelectorAll('input').forEach(input=>input.disabled=!on);
    fields.schedule_time.required=on;fields.schedule_date.required=on;
    if(fields.account_id) fields.account_id.required=on;
    weekdays.hidden=kind!=='weekly';monthday.hidden=kind!=='monthly';
    weekdays.querySelectorAll('input').forEach(input=>input.disabled=!on || kind!=='weekly');
    fields.schedule_monthday.disabled=!on || kind!=='monthly';fields.schedule_monthday.required=on && kind==='monthly';
    fields.schedule_stop.disabled=!on || !fields.schedule_stop_enabled.checked;fields.schedule_stop.required=on && fields.schedule_stop_enabled.checked;
    let error='';
    const validTime=value=>/^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(value);
    if(on && kind==='weekly' && !root.querySelector('[name=schedule_weekdays]:checked')) error='Chọn ít nhất một ngày trong tuần.';
    if(on && fields.schedule_time.value && !validTime(fields.schedule_time.value)) error='Giờ chạy cần đúng HH:MM trong khoảng 00:00–23:59.';
    if(on && fields.schedule_stop_enabled.checked && fields.schedule_stop.value && !validTime(fields.schedule_stop.value)) error='Giờ dừng cần đúng HH:MM trong khoảng 00:00–23:59.';
    if(on && !fields.schedule_stop_enabled.checked && fields.schedule_time.value==='23:59') error='Giờ chạy cần trước 23:59 khi không bật giờ dừng.';
    if(on && fields.schedule_stop_enabled.checked && validTime(fields.schedule_stop.value) && validTime(fields.schedule_time.value) && fields.schedule_stop.value<=fields.schedule_time.value) error='Giờ dừng phải sau giờ chạy trong cùng ngày (UTC+7).';
    fields.schedule_time.setCustomValidity(error.startsWith('Giờ chạy')?error:'');
    fields.schedule_stop.setCustomValidity(error.startsWith('Giờ dừng')?error:'');
    status.textContent=error;
    root.dataset.scheduleValid=String(!error);
    if(footer) footer.textContent=on?`Sau khi lưu: bắt đầu ${fields.schedule_time.value || 'HH:MM'}, dừng ${fields.schedule_stop_enabled.checked?fields.schedule_stop.value:'23:59'} (24 giờ, giờ Việt Nam · UTC+7).`:'Lưu chiến dịch chưa gửi tin đến Zalo.';
    root.classList.toggle('is-off',!on);
    form.dispatchEvent(new Event('input',{bubbles:true}));
  }
  root.addEventListener('input',update);root.addEventListener('change',update);
  form.addEventListener('submit',event=>{
    update();
    if(enabled.checked && root.dataset.scheduleValid==='false'){
      event.preventDefault();const card=root.closest('.wizard-card');if(card){card.querySelector('.wizard-card-body').hidden=false;card.querySelector('[data-wizard-toggle]').setAttribute('aria-expanded','true');}
      status.scrollIntoView({block:'nearest'});root.querySelector('[name=schedule_kind]:checked').focus();
    }
  });
  // When switching to weekly, start with the weekday of the selected start date.
  root.querySelector('[name=schedule_kind][value=weekly]').addEventListener('change',()=>{
    if(!root.querySelector('[name=schedule_weekdays]:checked') && fields.schedule_date.value){const date=new Date(fields.schedule_date.value+'T12:00:00');const day=(date.getDay()+6)%7;root.querySelector(`[name=schedule_weekdays][value="${day}"]`).checked=true;update();}
  });
  update();
});
