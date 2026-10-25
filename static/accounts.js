const connectDialog = document.getElementById('connect-dialog');
let accountId = null;
let poll = null;
let expiresAt = null;
let pending = false;
const csrf = connectDialog.dataset.csrf;
const image = document.getElementById('qr-image');
const status = document.getElementById('qr-status');
const timer = document.getElementById('qr-timer');
const consent = document.getElementById('qr-consent');
const accept = document.getElementById('accept-unofficial');
const start = document.getElementById('start-qr');
const retry = document.getElementById('retry-qr');
const disconnect = document.getElementById('disconnect-qr');
const instruction = document.getElementById('qr-instruction');
function stopPolling() { clearTimeout(poll); poll = null; }
function clearImage() { image.hidden = true; image.removeAttribute('src'); }
function showError(message) { status.textContent = message; clearImage(); expiresAt = null; timer.textContent = ''; }
function updateAccountCard(id,state) {
  const label=document.querySelector(`[data-account-status="${id}"]`);
  if(!label)return;
  const connected=state==='connected',card=label.closest('.account-card');
  card.classList.toggle('is-connected',connected);card.classList.toggle('is-disconnected',!connected);
  label.textContent=connected?'Đã đăng nhập':'Chưa đăng nhập';
  const badge=card.querySelector('[data-account-ready]');
  badge.textContent=connected?'Sẵn sàng':'Cần đăng nhập';
}
function render(data,updateCard=true) {
  if(updateCard)updateAccountCard(accountId,data.state);
  retry.hidden = true;
  retry.textContent = 'Tạo mã QR mới';
  disconnect.hidden = data.state === 'disconnected';
  instruction.hidden = !['qr', 'scanned'].includes(data.state);
  clearImage(); expiresAt = null; timer.textContent = '';
  if (data.state === 'qr' || data.state === 'scanned') {
    if (data.image) { image.src = `data:image/png;base64,${data.image}`; image.hidden = false; }
    expiresAt = data.expires_at;
    consent.hidden = true;
    status.textContent = data.state === 'scanned' ? 'Đã quét. Hãy xác nhận đăng nhập trên điện thoại.' : 'Mã QR đã sẵn sàng.';
  } else if (data.state === 'loading') {
    consent.hidden = true; status.textContent = 'Đang kết nối Zalo để lấy mã QR…';
  } else if (data.state === 'connected') {
    consent.hidden = true;
    retry.hidden = false; retry.textContent = 'Đăng nhập lại bằng QR';
    status.textContent = `${data.display_name || 'Tài khoản'}: đã đăng nhập.`;
  } else if (['expired', 'error', 'declined'].includes(data.state)) {
    status.textContent = data.message || 'Phiên đăng nhập đã kết thúc.';
    consent.hidden = true; retry.hidden = false;
  } else {
    consent.hidden = false;
    status.textContent = connectDialog.dataset.enabled === 'yes' ? 'Xác nhận để bắt đầu đăng nhập.' : 'VPS chưa bật đăng nhập QR. Cần cập nhật và cài bộ kết nối.';
    disconnect.hidden = true;
  }
}
async function readStatus(id) {
  try {
    const response = await fetch(`/accounts/${id}/qr`, { cache: 'no-store' });
    if (!response.ok || response.redirected) throw new Error();
    const data = await response.json();
    if (id !== accountId || !connectDialog.open) return;
    render(data);
    if (['loading', 'qr', 'scanned'].includes(data.state)) poll = setTimeout(() => readStatus(id), 1500);
  } catch {
    if (id === accountId && connectDialog.open) {
      showError('Không thể cập nhật phiên. Kiểm tra kết nối hoặc đăng nhập lại ứng dụng.');
      retry.hidden = false;
    }
  }
}
async function begin() {
  if (pending || !accept.checked) return;
  pending = true; stopPolling(); start.disabled = true; retry.disabled = true;
  showError('Đang khởi tạo phiên đăng nhập…'); consent.hidden = true;
  const id = accountId;
  try {
    const response = await fetch(`/accounts/${id}/qr`, { method: 'POST',
      body: new URLSearchParams({ csrf, accept_unofficial: 'yes' }) });
    if (response.redirected) throw new Error();
    const data = await response.json();
    if (id !== accountId || !connectDialog.open) return;
    if (!response.ok) { showError(data.error || 'Không thể tạo mã QR.'); retry.hidden = false; return; }
    await readStatus(id);
  } catch { showError('Không thể khởi tạo QR. Vui lòng tải lại trang và thử lại.'); retry.hidden = false; }
  finally { pending = false; start.disabled = !accept.checked; retry.disabled = false; }
}
function openConnect(button) {
  stopPolling(); accountId = button.dataset.accountId; pending = false;
  accept.checked = false; start.disabled = true;
  document.getElementById('connect-name').textContent = button.dataset.connectName;
  render({ state: 'disconnected' },false); connectDialog.showModal();
  readStatus(accountId);
}
document.getElementById('add-account').addEventListener('click', () => document.getElementById('account-dialog').showModal());
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.close).close()));
document.querySelectorAll('[data-account-id]').forEach(button => button.addEventListener('click', () => openConnect(button)));
connectDialog.addEventListener('close', () => { stopPolling(); clearImage(); refreshAccountCards(); });
accept.addEventListener('change', () => start.disabled = !accept.checked);
start.addEventListener('click', begin);
retry.addEventListener('click', () => {
  if (!accept.checked) { consent.hidden = false; retry.hidden = true; return; }
  begin();
});
disconnect.addEventListener('click', async () => {
  const id = accountId; stopPolling(); disconnect.disabled = true;
  try {
    const response = await fetch(`/accounts/${id}/disconnect`, { method: 'POST', body: new URLSearchParams({ csrf }) });
    if (!response.ok || response.redirected) throw new Error();
    if (id === accountId) { accept.checked = false; start.disabled = true; render({ state: 'disconnected' }); }
  } catch { showError('Không thể xóa phiên. Vui lòng thử lại.'); }
  finally { disconnect.disabled = false; }
});
setInterval(() => {
  if (!connectDialog.open || !expiresAt) return;
  const remaining = Math.max(0, Math.ceil(expiresAt - Date.now()/1000));
  timer.textContent = remaining ? `Mã QR hết hạn sau ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}` : 'Mã QR đã hết hạn.';
  if (!remaining) { clearImage(); instruction.hidden = true; retry.hidden = false; }
}, 1000);
if (connectDialog.dataset.autoConnect) {
  const button = document.querySelector(`[data-account-id="${connectDialog.dataset.autoConnect}"]`);
  if (button) openConnect(button);
}

let refreshingAccounts=false;
async function refreshAccountCards() {
  if(document.hidden || connectDialog.open || refreshingAccounts)return;
  refreshingAccounts=true;
  try {
    const response=await fetch('/accounts/status',{cache:'no-store',credentials:'same-origin'});
    if(!response.ok || response.redirected)return;
    const data=await response.json();
    if(connectDialog.open)return;
    for(const account of data.accounts || [])updateAccountCard(account.id,account.state);
  } catch { /* A network error does not prove that a Zalo account logged out. */ }
  finally {refreshingAccounts=false;}
}
setInterval(refreshAccountCards,15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshAccountCards();});

const deleteAccountDialog = document.getElementById('delete-account-dialog');
const deleteAccountForm = document.getElementById('delete-account-form');
document.querySelectorAll('[data-delete-account-id]').forEach(button => {
  button.addEventListener('click', () => {
    document.getElementById('delete-account-name').textContent = button.dataset.deleteAccountName;
    deleteAccountForm.action = button.dataset.deleteUrl;
    deleteAccountDialog.showModal();
  });
});
deleteAccountForm.addEventListener('submit', () => {
  deleteAccountForm.querySelector('[type="submit"]').disabled = true;
});
