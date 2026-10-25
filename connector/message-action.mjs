import { lookupFailure } from './lookup-errors.mjs';

export async function executeMessageAction(api, input, onDispatch = () => {}) {
  if (input.action === 'resolve') {
    const phone = String(input.phone || '').replace(/[\s()+-]/g, '');
    if (!/^\d{8,15}$/.test(phone)) throw new Error('Invalid phone');
    let user;
    try {
      user = await api.findUser(phone.startsWith('0') ? `84${phone.slice(1)}` : phone);
    } catch (error) {
      // SDK's profile lookup documents 216 as no matching user. Transport,
      // session and rate-limit failures must not discard a campaign's data.
      const outcome=lookupFailure(error);
      if (outcome.state==='not_found') return outcome;
      throw error;
    }
    if (user === null || user === undefined) return {state:'not_found'};
    if (typeof user !== 'object' || Array.isArray(user)) throw new Error('Invalid profile');
    if (user.uid === undefined || user.uid === null || user.uid === '' || String(user.uid) === '0') return {state:'not_found'};
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
  const styles = input.styles === undefined ? [] : input.styles;
  const supported = new Set(['b','i','u','s','f_18','lst_1','lst_2','ind_$']);
  const boundaries = new Set([0]);
  let position = 0;
  for (const char of input.message) { position += char.length; boundaries.add(position); }
  if (!Array.isArray(styles) || styles.length > 400 || styles.length && input.action !== 'send' || styles.some(style =>
      !style || !supported.has(style.st) || Object.keys(style).some(key => !['start','len','st','indentSize'].includes(key)) ||
      !Number.isInteger(style.start) || !Number.isInteger(style.len) || style.len <= 0 ||
      !boundaries.has(style.start) || !boundaries.has(style.start+style.len) ||
      style.indentSize !== undefined && (style.st !== 'ind_$' || !Number.isInteger(style.indentSize) || style.indentSize < 1 || style.indentSize > 5))) throw new Error('Invalid text styles');
  onDispatch();
  if (input.action === 'alias') {
    const result = await api.changeFriendAlias(input.message, input.uid);
    return {state: result === '' ? 'renamed' : 'unknown'};
  }
  if (input.action === 'friend') {
    const result = await api.sendFriendRequest(input.message, input.uid);
    return {state: result === '' ? 'friend_requested' : 'unknown'};
  }
  const imageAttachment = attachment && /\.(jpe?g|png|webp)$/i.test(attachment.filename);
  const acceptedAttachments = result => Array.isArray(result?.attachment) && result.attachment.length > 0 && result.attachment.every(item => item?.msgId);
  if (imageAttachment && styles.length) {
    // zca-js 2.2.0 folds a single image's text into `desc` and discards its
    // styles. Send the image without a caption, then use the styled text API.
    // This remains one claimed delivery; partial/uncertain results never retry.
    const imageResult = await api.sendMessage({msg:'', attachments:[attachment]}, input.uid, 0);
    if (!acceptedAttachments(imageResult)) return {state:'unknown'};
    const textResult = await api.sendMessage({msg:input.message, styles}, input.uid, 0);
    if (!textResult?.message?.msgId) return {state:'unknown'};
    return {state:'sent', message_id:[...imageResult.attachment.map(item => item.msgId), textResult.message.msgId].map(String).join(',')};
  }
  const result = await api.sendMessage(attachment || styles.length ? {msg: input.message, ...(attachment ? {attachments:[attachment]} : {}), ...(styles.length ? {styles} : {})} : input.message, input.uid, 0); // ThreadType.User
  if (attachment) {
    // A caption/text acknowledgement alone does not prove that the attachment was accepted.
    if (!acceptedAttachments(result) || !imageAttachment && !result.message?.msgId) return {state: 'unknown'};
    const ids = [result.message?.msgId, ...result.attachment.map(item => item.msgId)].filter(Boolean);
    return {state: 'sent', message_id: ids.map(String).join(',')};
  }
  if (result?.message?.msgId) return {state: 'sent', message_id: String(result.message.msgId)};
  return {state: 'unknown'};
}
