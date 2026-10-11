export async function executeMessageAction(api, input, onDispatch = () => {}) {
  if (input.action === 'resolve') {
    const phone = String(input.phone || '').replace(/[\s()+-]/g, '');
    if (!/^\d{8,15}$/.test(phone)) throw new Error('Invalid phone');
    const user = await api.findUser(phone.startsWith('0') ? `84${phone.slice(1)}` : phone);
    if (!/^\d{1,30}$/.test(String(user.uid))) throw new Error('Invalid recipient');
    return {state: 'resolved', uid: String(user.uid), name: String(user.display_name || user.zalo_name || '').slice(0,100),
      original_name: String(user.zalo_name || '').slice(0,100), gender: [0,1].includes(user.gender) ? user.gender : null};
  }
  if (!['send','friend'].includes(input.action) || !/^\d{1,30}$/.test(input.uid) || typeof input.message !== 'string' || !input.message || input.message.length > (input.action === 'friend' ? 150 : 2000)) throw new Error('Invalid message');
  onDispatch();
  if (input.action === 'friend') {
    const result = await api.sendFriendRequest(input.message, input.uid);
    return {state: result === '' ? 'friend_requested' : 'unknown'};
  }
  const result = await api.sendMessage(input.message, input.uid, 0); // ThreadType.User
  if (result.message?.msgId) return {state: 'sent', message_id: String(result.message.msgId)};
  return {state: 'unknown'};
}
