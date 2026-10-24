document.querySelectorAll('[data-duplicate-settings]').forEach(root=>{
  const form=root.closest('form'),enabled=form.elements.duplicate_enabled,days=form.elements.duplicate_days,all=form.elements.duplicate_all_accounts;
  function update(){
    days.disabled=!enabled.checked;days.required=enabled.checked;all.disabled=!enabled.checked;
    root.classList.toggle('duplicate-is-off',!enabled.checked);
    root.dataset.duplicateValid=String(!enabled.checked || days.validity.valid);
    form.dispatchEvent(new Event('input',{bubbles:true}));
  }
  root.addEventListener('input',update);root.addEventListener('change',update);update();
});
