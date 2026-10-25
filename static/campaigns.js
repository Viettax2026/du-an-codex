const dialog = document.querySelector('#campaign-dialog');
const openDialog = () => dialog.showModal();
document.querySelector('#new-campaign').addEventListener('click', openDialog);
document.querySelectorAll('[data-open-campaign]').forEach(button => button.addEventListener('click', openDialog));
['close-dialog', 'cancel-dialog'].forEach(id => document.getElementById(id).addEventListener('click', () => dialog.close()));
if (location.hash === '#new') openDialog();

const filters = document.querySelector('#filters');
filters.querySelectorAll('select').forEach(select => select.addEventListener('change', () => filters.requestSubmit()));
const rows = [...document.querySelectorAll('.row-checkbox')];
const all = document.getElementById('select-all');
function updateSelection() {
  const count = rows.filter(row => row.checked).length;
  all.checked = rows.length > 0 && count === rows.length;
  all.indeterminate = count > 0 && count < rows.length;
  document.getElementById('selection-count').textContent = count ? `Đã chọn ${count}` : '';
  rows.forEach(row => row.closest('tr').classList.toggle('is-checked', row.checked));
}
all.disabled = rows.length === 0;
all.addEventListener('change', () => { rows.forEach(row => row.checked = all.checked); updateSelection(); });
rows.forEach(row => row.addEventListener('change', updateSelection));

const tabs = [...document.querySelectorAll('.progress-tab')];
function activateTab(tab) {
  tabs.forEach(button => {
    const active = button === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    document.getElementById(button.getAttribute('aria-controls')).hidden = !active;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activateTab(tab));
  tab.addEventListener('keydown', event => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + 1) % tabs.length];
      activateTab(next); next.focus();
    }
  });
});
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const status = document.getElementById('copy-status');
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    status.textContent = 'Đã sao chép. Hãy tự chọn đúng người nhận trong Zalo.';
  } catch {
    status.textContent = 'Trình duyệt chưa cho phép sao chép. Bạn có thể chọn và sao chép nội dung bằng tay.';
  }
}));

document.querySelector('[name=log_account_id]')?.addEventListener('change', () => filters.requestSubmit());
document.querySelectorAll('[data-open-guide]').forEach(button => button.addEventListener('click', () => {
  activateTab(document.querySelector('#tab-guide'));
  document.querySelector('[data-guide-title]').textContent = `Trợ lý · ${button.dataset.campaignName}`;
  if (innerWidth <= 850) document.querySelector('.progress-panel').scrollIntoView({behavior:'smooth',block:'start'});
}));
document.querySelector('[data-toggle-campaign-detail]')?.addEventListener('click', event => {
  const button = event.currentTarget;
  const expanded = button.getAttribute('aria-expanded') === 'true';
  button.setAttribute('aria-expanded', String(!expanded));
  document.querySelector('#campaign-detail-content').hidden = expanded;
  button.closest('.campaign-inline-detail').classList.toggle('is-collapsed', expanded);
  button.querySelector('span').textContent = expanded ? '⌃' : '⌄';
});
document.querySelector('[data-toggle-campaign-nav]')?.addEventListener('click', event => {
  const expanded = document.body.classList.toggle('campaign-nav-expanded');
  event.currentTarget.setAttribute('aria-expanded', String(expanded));
  event.currentTarget.setAttribute('aria-label', expanded ? 'Thu gọn menu' : 'Mở rộng menu');
  event.currentTarget.title = expanded ? 'Thu gọn menu' : 'Mở rộng menu';
  event.currentTarget.textContent = expanded ? '‹' : '›';
});
document.querySelectorAll('[data-campaign-url]').forEach(row => row.addEventListener('click', event => {
  if (event.target.closest('button,a,input,select,details')) return;
  location.assign(row.dataset.campaignUrl);
}));

// Detail links work without JavaScript; enhance them to keep the selected row
// and scroll position while replacing only the read-only detail panel.
let detailEpoch=0,detailController,detailLoading=false;
function revealDetailTab() {
  const nav=document.querySelector('.campaign-detail-tabs'),active=nav?.querySelector('[aria-selected=true]');
  if(!nav || !active)return;
  const bounds=nav.getBoundingClientRect(),position=active.getBoundingClientRect();
  if(position.left<bounds.left)nav.scrollLeft-=bounds.left-position.left+12;
  else if(position.right>bounds.right)nav.scrollLeft+=position.right-bounds.right+12;
}
revealDetailTab();
async function loadDetail(href,automatic=false) {
  const root=document.querySelector('#campaign-detail-content');
  if(!root || root.hidden)return;
  const epoch=++detailEpoch;
  const focusKey=root.contains(document.activeElement)?document.activeElement.id:'';
  const previousPanel=root.querySelector('.campaign-detail-panel'),position={top:previousPanel?.scrollTop || 0,left:previousPanel?.scrollLeft || 0,nav:root.querySelector('.campaign-detail-tabs')?.scrollLeft || 0};
  detailLoading=true;
  detailController?.abort();detailController=new AbortController();
  try {
    const response=await fetch(href,{credentials:'same-origin',signal:detailController.signal});
    if(!response.ok)throw new Error('Không tải được chi tiết.');
    const doc=new DOMParser().parseFromString(await response.text(),'text/html');
    const panel=doc.querySelector('#campaign-detail-content');
    if(!panel || !panel.querySelector('[data-detail-current]'))throw new Error('Phiên làm việc đã thay đổi. Tải lại trang.');
    if(epoch!==detailEpoch)return;
    root.replaceChildren(...panel.childNodes);
    const nextPanel=root.querySelector('.campaign-detail-panel'),nextNav=root.querySelector('.campaign-detail-tabs');
    if(nextNav)nextNav.scrollLeft=position.nav;
    if(automatic && nextPanel){nextPanel.scrollTop=position.top;nextPanel.scrollLeft=position.left;}
    revealDetailTab();
    if(!automatic) {
      history.replaceState(null,'',href);
      root.querySelector('[role=tab][aria-selected=true]')?.focus({preventScroll:true});
    } else if(focusKey)root.querySelector('#'+CSS.escape(focusKey))?.focus({preventScroll:true});
    const active=root.querySelector('[data-detail-current]')?.dataset.detailCurrent;
    if(filters.elements.detail_tab)filters.elements.detail_tab.value=active || 'info';
    document.querySelectorAll('[data-campaign-url]').forEach(row=>{
      const url=new URL(row.dataset.campaignUrl,location.origin);url.searchParams.set('detail_tab',active || 'info');url.searchParams.set('detail_page','1');
      row.dataset.campaignUrl=url.href;const name=row.querySelector('.campaign-name');if(name)name.href=url.href;
    });
  } catch(error) {
    if(error.name==='AbortError')return;
    const status=root.querySelector('[data-detail-status]');
    if(status)status.textContent=error.message;
  } finally {
    if(epoch===detailEpoch)detailLoading=false;
  }
}
document.addEventListener('click',event=>{
  const link=event.target.closest('[data-detail-load]');
  if(!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button!==0)return;
  event.preventDefault();loadDetail(link.href);
});
document.addEventListener('keydown',event=>{
  const current=event.target.closest('.campaign-detail-tabs [role=tab]');
  if(!current || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();
  const links=[...current.closest('[role=tablist]').querySelectorAll('[role=tab]')],index=links.indexOf(current);
  const next=event.key==='Home'?0:event.key==='End'?links.length-1:(index+(event.key==='ArrowRight'?1:-1)+links.length)%links.length;
  links[next].focus();
});
setInterval(()=>{
  if(document.hidden || detailLoading || document.querySelector('dialog[open]') || window.getSelection()?.toString())return;
  const active=document.querySelector('[data-detail-current]')?.dataset.detailCurrent;
  if(['history','results'].includes(active))loadDetail(location.href,true);
},15000);

// Keep the user's pane size through tab refreshes and page navigation.
const detailResizer=document.querySelector('[data-detail-resizer]');
const detailSection=document.querySelector('.campaign-inline-detail');
const campaignMain=document.querySelector('.campaign-main');
if(detailResizer && detailSection && campaignMain) {
  let preferredRatio=null,drag=null;
  try {
    const saved=localStorage.getItem(detailResizer.dataset.storageKey);
    const ratio=Number(saved);
    if(saved!==null && Number.isFinite(ratio) && ratio>0 && ratio<1)preferredRatio=ratio;
  } catch { /* Resizing also works when browser storage is disabled. */ }
  function limits() {
    const fixed=[...campaignMain.children].filter(node=>node!==detailSection && !node.classList.contains('campaign-table-scroll'))
      .reduce((total,node)=>total+node.getBoundingClientRect().height,0);
    const list=campaignMain.querySelector('.campaign-table-scroll');
    const listMinimum=parseFloat(getComputedStyle(list).minHeight)||170;
    const maximum=Math.max(0,campaignMain.clientHeight-fixed-listMinimum);
    return {minimum:Math.min(170,maximum),maximum};
  }
  function updateAria(height,bounds) {
    detailResizer.setAttribute('aria-valuemin',Math.round(bounds.minimum));
    detailResizer.setAttribute('aria-valuemax',Math.round(bounds.maximum));
    detailResizer.setAttribute('aria-valuenow',Math.round(height));
    detailResizer.setAttribute('aria-valuetext',`Chiều cao chi tiết chiến dịch: ${Math.round(height)} pixel`);
  }
  function setHeight(height,remember=false) {
    const bounds=limits();
    height=Math.max(bounds.minimum,Math.min(bounds.maximum,height));
    detailSection.classList.add('has-detail-height');
    detailSection.style.setProperty('--campaign-detail-height',`${height}px`);
    updateAria(height,bounds);
    if(remember) {
      preferredRatio=height/campaignMain.clientHeight;
      try {localStorage.setItem(detailResizer.dataset.storageKey,String(preferredRatio));} catch {}
    }
  }
  function syncHeight() {
    if(detailSection.classList.contains('is-collapsed'))return;
    if(preferredRatio!==null)setHeight(preferredRatio*campaignMain.clientHeight);
    else updateAria(detailSection.getBoundingClientRect().height,limits());
  }
  detailResizer.addEventListener('pointerdown',event=>{
    if(event.button!==0 || detailSection.classList.contains('is-collapsed'))return;
    event.preventDefault();detailResizer.focus({preventScroll:true});
    drag={id:event.pointerId,y:event.clientY,height:detailSection.getBoundingClientRect().height};
    detailResizer.setPointerCapture(event.pointerId);
    detailResizer.classList.add('is-dragging');document.body.classList.add('campaign-detail-resizing');
  });
  detailResizer.addEventListener('pointermove',event=>{
    if(drag?.id!==event.pointerId)return;
    setHeight(drag.height+drag.y-event.clientY,true);
  });
  function finishResize(event) {
    if(!drag || (event.pointerId!==undefined && drag.id!==event.pointerId))return;
    const id=drag.id;drag=null;
    detailResizer.classList.remove('is-dragging');document.body.classList.remove('campaign-detail-resizing');
    if(detailResizer.hasPointerCapture(id))detailResizer.releasePointerCapture(id);
  }
  ['pointerup','pointercancel','lostpointercapture'].forEach(name=>detailResizer.addEventListener(name,finishResize));
  window.addEventListener('blur',finishResize);
  detailResizer.addEventListener('keydown',event=>{
    if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    event.preventDefault();
    const bounds=limits(),step=event.shiftKey?50:20;
    const height=event.key==='Home'?bounds.minimum:event.key==='End'?bounds.maximum:
      detailSection.getBoundingClientRect().height+(event.key==='ArrowUp'?step:-step);
    setHeight(height,true);
  });
  const paneObserver=new ResizeObserver(syncHeight);
  paneObserver.observe(campaignMain);paneObserver.observe(detailSection);
  document.querySelector('[data-toggle-campaign-detail]')?.addEventListener('click',syncHeight);
  syncHeight();
}

// POST the intended pause state once; render only the state confirmed by the server.
const pendingRunUpdates=new Set();
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-inline-campaign-pause]');
  if(!form)return;
  event.preventDefault();
  const row=form.closest('[data-campaign-id]'),id=row.dataset.campaignId;
  if(pendingRunUpdates.has(id))return;
  pendingRunUpdates.add(id);
  const button=form.querySelector('button'),notice=document.querySelector('#campaign-run-status');
  button.disabled=true;button.setAttribute('aria-busy','true');
  notice.hidden=false;notice.textContent='Đang cập nhật trạng thái chiến dịch…';
  try {
    const response=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{Accept:'application/json'},body:new URLSearchParams(new FormData(form))});
    if(!response.ok || response.redirected)throw new Error();
    const result=await response.json();
    if(typeof result.paused!=='boolean')throw new Error();
    const refreshed=await fetch(location.href,{credentials:'same-origin',cache:'no-store'});
    if(!refreshed.ok || refreshed.redirected)throw new Error();
    const doc=new DOMParser().parseFromString(await refreshed.text(),'text/html');
    const next=doc.querySelector(`[data-campaign-id="${CSS.escape(id)}"]`);
    // A pause/resume may move this campaign outside the current status filter.
    if(!next){location.assign(location.href);return;}
    row.className=next.className;
    row.classList.toggle('is-checked',row.querySelector('.row-checkbox').checked);
    row.querySelector('.run-mode').replaceChildren(...next.querySelector('.run-mode').childNodes);
    row.querySelector('.status-pill').closest('td').replaceChildren(...next.querySelector('.status-pill').closest('td').childNodes);
    const action=row.querySelector('.campaign-action-menu a'),nextAction=next.querySelector('.campaign-action-menu a');
    if(action && nextAction)action.replaceChildren(...nextAction.childNodes);
    notice.textContent=result.paused?'Đã tạm ngưng chiến dịch.':'Đã tiếp tục chiến dịch theo cấu hình đã lưu.';
    if(new URL(location.href).searchParams.get('selected')===id)loadDetail(location.href,true);
    row.querySelector('.campaign-run-button')?.focus({preventScroll:true});
  } catch {
    notice.textContent='Chưa xác nhận được trạng thái. Làm mới trang để kiểm tra trước khi bấm lại.';
  } finally {
    pendingRunUpdates.delete(id);button.disabled=false;button.removeAttribute('aria-busy');
  }
});
