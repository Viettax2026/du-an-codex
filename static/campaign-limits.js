document.querySelectorAll('[data-campaign-limits]').forEach(root=>{
  const form=root.closest('form'),fields=form.elements;
  let usage=JSON.parse(root.dataset.usage),timer,epoch=0;
  const cards=[...root.querySelectorAll('[data-limit-card]')],status=root.querySelector('[data-limits-status]');
  function update(){
    cards.forEach(card=>{
      const count=usage[card.dataset.limitCard],day=Number(card.querySelector('[data-limit-day]').value),hour=Number(card.querySelector('[data-limit-hour]').value);
      const unit=card.dataset.limitUnit,minutes=card.querySelector('[data-limit-window]').value;
      card.querySelector('[data-limit-used]').textContent=`đã chạy ${count.day_used}/${day || '∞'}`;
      card.querySelector('[data-limit-day-label]').textContent=fields.limits_day_mode.value==='calendar'?'Giới hạn trong ngày (đến 24h)':'Giới hạn 24 giờ gần nhất';
      card.querySelector('[data-limit-minutes]').textContent=minutes;
      card.querySelector('[data-limit-remaining]').textContent=day?`còn ${Math.max(0,day-count.day_used)} ${unit}`:'Không giới hạn';
      card.querySelector('[data-limit-hour-used]').textContent=`Đã chạy ${count.hour_used}/${hour || '∞'} ${unit} trong khung giờ`;
      const progress=card.querySelector('progress');progress.max=day || 1;progress.value=day?Math.min(count.day_used,day):0;
      card.classList.toggle('limit-reached',Boolean(day && count.day_used>=day || hour && count.hour_used>=hour));
    });
    root.dataset.limitsValid=String([...root.querySelectorAll('input[type=number]')].every(input=>input.validity.valid));
    form.dispatchEvent(new Event('input',{bubbles:true}));
  }
  async function refresh(){
    if(!root.dataset.usageUrl || document.visibilityState==='hidden')return;
    const dialog=root.closest('dialog');if(dialog && !dialog.open)return;
    const id=++epoch;
    const params=new URLSearchParams({mode:fields.limits_day_mode.value,message_window_minutes:fields.message_window_minutes.value,friend_window_minutes:fields.friend_window_minutes.value});
    try{
      const response=await fetch(root.dataset.usageUrl+'?'+params,{credentials:'same-origin'});
      const data=await response.json();if(!response.ok)throw new Error(data.error || 'Không tải được hạn mức hiện tại.');
      if(id!==epoch)return;usage=data.usage;status.textContent='';update();
    }catch(error){if(id===epoch)status.textContent='Không tải được số lượt hiện tại. Lưu giới hạn vẫn được kiểm tra trên máy chủ.';}
  }
  cards.forEach(card=>{
    const button=card.querySelector('[data-limit-change-window]'),editor=card.querySelector('[data-limit-window-editor]'),input=editor.querySelector('input');
    button.addEventListener('click',()=>{editor.hidden=!editor.hidden;button.setAttribute('aria-expanded',String(!editor.hidden));if(!editor.hidden)input.focus();});
    input.addEventListener('invalid',()=>{editor.hidden=false;button.setAttribute('aria-expanded','true');});
  });
  root.addEventListener('input',event=>{
    update();
    if(event.target.matches('[data-limit-window]')){epoch++;clearTimeout(timer);timer=setTimeout(refresh,350);}
  });
  fields.limits_day_mode.addEventListener('change',()=>{epoch++;update();refresh();});
  root.addEventListener('change',update);
  root.addEventListener('invalid',event=>{const details=event.target.closest('details');if(details)details.open=true;},true);
  update();
  const polling=setInterval(refresh,15000);
  window.addEventListener('pagehide',()=>{clearInterval(polling);clearTimeout(timer);});
});
