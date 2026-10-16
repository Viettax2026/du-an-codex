export async function executeMessageAction(api, input, onDispatch = () => {}) {
  if (input.action === 'resolve') {
    const phone = String(input.phone || '').replace(/[\s()+-]/g, '');
    if (!/^\d{8,15}$/.test(phone)) throw new Error('Invalid phone');
    const user = await api.findUser(phone.startsWith('0') ? `84${phone.slice(1)}` : phone);
    if (!/^\d{1,30}$/.test(String(user.uid))) throw new Error('Invalid recipient');
    return {state: 'resolved', uid: String(user.uid), name: String(user.display_name || user.zalo_name || '').slice(0,100),
      original_name: String(user.zalo_name || '').slice(0,100), gender: [0,1].includes(user.gender) ? user.gender : null};
  }
  if (!['send','friend','alias'].includes(input.action) || !/^\d{1,30}$/.test(input.uid) || typeof input.message !== 'string' || !input.message || input.message.length > (input.action === 'friend' ? 150 : input.action === 'alias' ? 100 : 2000)) throw new Error('Invalid message');
  let attachment = null;
  if (input.attachment) {
    attachment = input.attachment;
    if (input.action !== 'send' || !Buffer.isBuffer(attachment.data) ||
        !/\.(jpe?g|png|webp|pdf|mp4)$/i.test(attachment.filename || '') ||
        !attachment.data.length || attachment.data.length > 10 * 1024 * 1024 ||
        attachment.metadata?.totalSize !== attachment.data.length) throw new Error('Invalid attachment');
    if (/\.(jpe?g|png|webp)$/i.test(attachment.filename) &&
        (![attachment.metadata.width, attachment.metadata.height].every(value => Number.isInteger(value) && value > 0) ||
         attachment.metadata.width * attachment.metadata.height > 25_000_000)) throw new Error('Invalid image dimensions');
  }
  onDispatch();
  if (input.action === 'alias') {
    const result = await api.changeFriendAlias(input.message, input.uid);
    return {state: result === '' ? 'renamed' : 'unknown'};
  }
  if (input.action === 'friend') {
    const result = await api.sendFriendRequest(input.message, input.uid);
    return {state: result === '' ? 'friend_requested' : 'unknown'};
  }
  const result = await api.sendMessage(attachment ? {msg: input.message, attachments: [attachment]} : input.message, input.uid, 0); // ThreadType.User
  if (attachment) {
    // A caption/text acknowledgement alone does not prove that the attachment was accepted.
    if (!result.attachment?.length || !result.attachment.every(item => item.msgId)) return {state: 'unknown'};
    const ids = [result.message?.msgId, ...result.attachment.map(item => item.msgId)].filter(Boolean);
    return {state: 'sent', message_id: ids.map(String).join(',')};
  }
  if (result.message?.msgId) return {state: 'sent', message_id: String(result.message.msgId)};
  return {state: 'unknown'};
}
