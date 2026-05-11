let activeChat = null;
let searchTimer = null;
let socket = null;
let adminSearchTimer = null;
let collapsedSections = JSON.parse(localStorage.getItem('minigram_collapsed_sections') || '{"private":false,"channels":false}');

const dom = {};

function initDom() {
  dom.chatList = document.getElementById('chat-list');
  dom.searchInput = document.getElementById('search-input');
  dom.searchDropdown = document.getElementById('search-dropdown');
  dom.noChat = document.getElementById('no-chat');
  dom.chatView = document.getElementById('chat-view');
  dom.headerAvatar = document.getElementById('chat-header-avatar');
  dom.headerName = document.getElementById('chat-header-name');
  dom.headerSub = document.getElementById('chat-header-sub');
  dom.inviteBtn = document.getElementById('invite-btn');
  dom.addFriendBtn = document.getElementById('add-friend-btn');
  dom.removeFriendBtn = document.getElementById('remove-friend-btn');
  dom.blockUserBtn = document.getElementById('block-user-btn');
  dom.deleteChatBtn = document.getElementById('delete-chat-btn');
  dom.settingsBtn = document.getElementById('settings-btn');
  dom.leaveChannelBtn = document.getElementById('leave-channel-btn');
  dom.joinRequestsBtn = document.getElementById('join-requests-btn');
  dom.messages = document.getElementById('messages');
  dom.msgInput = document.getElementById('msg-input');
  dom.sendBtn = document.getElementById('send-btn');
  dom.toast = document.getElementById('toast');
  dom.reqBadge = document.getElementById('req-badge');
}

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function linkifyText(value) {
  const text = String(value ?? '');
  const urlRe = /(https?:\/\/[^\s<]+|www\.[^\s<]+)/gi;
  let result = '';
  let lastIndex = 0;
  let match;

  while ((match = urlRe.exec(text)) !== null) {
    let rawUrl = match[0];
    const start = match.index;

    result += esc(text.slice(lastIndex, start));

    let trailing = '';
    while (/[.,!?;:)\]]$/.test(rawUrl)) {
      trailing = rawUrl.slice(-1) + trailing;
      rawUrl = rawUrl.slice(0, -1);
    }

    const href = rawUrl.toLowerCase().startsWith('www.') ? `https://${rawUrl}` : rawUrl;
    result += `<a class="chat-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(rawUrl)}</a>${esc(trailing)}`;
    lastIndex = start + match[0].length;
  }

  result += esc(text.slice(lastIndex));
  return result;
}

function firstLetter(value) {
  const s = String(value || '?').trim();
  return (s[0] || '?').toUpperCase();
}

function roleText(role) {
  if (role === 'owner') return 'владелец';
  if (role === 'admin') return 'админ';
  return 'подписчик';
}

function formatChatTime(value) {
  if (!value) return '';
  const text = String(value);
  return text.length >= 16 ? text.slice(11, 16) : text;
}

function statusIcon(status) {
  if (status === 'read') return '✓✓';
  if (status === 'delivered') return '✓✓';
  return '✓';
}

function statusTitle(status) {
  if (status === 'read') return 'прочитано';
  if (status === 'delivered') return 'доставлено';
  return 'отправлено';
}

function isSectionCollapsed(key) {
  return Boolean(collapsedSections[key]);
}

function saveCollapsedSections() {
  localStorage.setItem('minigram_collapsed_sections', JSON.stringify(collapsedSections));
}

function toggleSection(key) {
  collapsedSections[key] = !collapsedSections[key];
  saveCollapsedSections();
  loadSidebar().catch(error => showToast(error.message));
}

function privateListSubtitle(user) {
  const blockedPrefix = (user.is_blocked_by_me || user.has_blocked_me) ? '🚫 ' : '';
  if (user.last_message) {
    const prefix = user.last_message_sender_id === window.ME.id ? 'Ты: ' : '';
    return `${blockedPrefix}${prefix}${user.last_message}`;
  }
  if (user.is_blocked_by_me) return '@' + user.username + ' · вы заблокировали';
  if (user.has_blocked_me) return '@' + user.username + ' · вас заблокировали';
  if (user.is_friend) return '@' + user.username + ' · друг' + (user.online ? ' · онлайн' : '');
  if (!user.can_message) return '@' + user.username + ' · писать нельзя';
  return '@' + user.username + ' · ' + (user.online ? 'онлайн' : 'пользователь');
}

function channelListSubtitle(channel) {
  if (channel.last_message) {
    const author = channel.last_message_author || 'пост';
    return `${author}: ${channel.last_message}`;
  }
  return `@${channel.username} · ${channel.is_private ? 'закрытый' : 'открытый'} · ${roleText(channel.role)} · ${channel.subscriber_count} участник(ов)`;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'Ошибка запроса');
  }
  return data;
}

function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.remove('hidden');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => dom.toast.classList.add('hidden'), 2500);
}

function setModalMessage(id, text, ok = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = ok ? 'modal-msg ok' : 'modal-msg';
}

function toggleMenu() {
  document.getElementById('menu-overlay').classList.remove('hidden');
}

function closeMenu() {
  document.getElementById('menu-overlay').classList.add('hidden');
}

function openCreateChannel() {
  closeMenu();
  setModalMessage('create-ch-msg', '');
  document.getElementById('create-channel-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('ch-name').focus(), 0);
}

function openJoinChannel() {
  closeMenu();
  setModalMessage('join-ch-msg', '');
  document.getElementById('join-channel-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('join-invite-input').focus(), 0);
}

async function openFriendRequests() {
  closeMenu();
  await loadFriendRequests();
  document.getElementById('friend-requests-modal').classList.remove('hidden');
}

async function openBlockedUsers() {
  closeMenu();
  await loadBlockedUsers();
  document.getElementById('blocked-users-modal').classList.remove('hidden');
}

async function loadBlockedUsers() {
  const list = document.getElementById('blocked-users-list');
  list.innerHTML = '<div class="no-requests">Загрузка...</div>';
  try {
    const users = await api('/blocks');
    if (!users.length) {
      list.innerHTML = '<div class="no-requests">Заблокированных пользователей нет</div>';
      return;
    }
    list.innerHTML = '';
    users.forEach(user => {
      const row = document.createElement('div');
      row.className = 'fr-item';
      row.innerHTML = `
        <div class="chat-avatar small">${esc(firstLetter(user.display_name))}</div>
        <div class="fr-name">${esc(user.display_name)}<br><span class="muted-small">@${esc(user.username)} · с ${esc(user.created_at)}</span></div>
        <div class="fr-actions">
          <button class="btn-accept" onclick="unblockFromList(${user.id})">Разблокировать</button>
        </div>
      `;
      list.appendChild(row);
    });
  } catch (error) {
    list.innerHTML = `<div class="no-requests">${esc(error.message)}</div>`;
  }
}

async function unblockFromList(userId) {
  try {
    await api(`/blocks/${userId}`, { method: 'DELETE' });
    showToast('Пользователь разблокирован');
    await loadBlockedUsers();
    await loadSidebar();
    if (activeChat && activeChat.type === 'private' && activeChat.id === userId) {
      await refreshPrivateStatus();
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function openProfileSettings() {
  closeMenu();
  setModalMessage('profile-settings-msg', '');
  document.getElementById('profile-settings-modal').classList.remove('hidden');
  try {
    const settings = await api('/me/settings');
    document.getElementById('profile-display-name').value = settings.display_name || window.ME.display_name || '';
    document.getElementById('profile-pm-privacy').value = settings.pm_privacy || 'everyone';
  } catch (error) {
    setModalMessage('profile-settings-msg', error.message);
  }
}

async function saveProfileSettings() {
  const displayName = document.getElementById('profile-display-name').value.trim();
  const pmPrivacy = document.getElementById('profile-pm-privacy').value;

  if (!displayName) {
    setModalMessage('profile-settings-msg', 'Введите ник');
    return;
  }

  try {
    const result = await api('/me/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName, pm_privacy: pmPrivacy }),
    });
    window.ME.display_name = result.display_name;
    document.querySelectorAll('.menu-username').forEach(el => { el.textContent = result.display_name; });
    document.querySelectorAll('.menu-avatar').forEach(el => { el.textContent = firstLetter(result.display_name); });
    if (activeChat && activeChat.type === 'private' && activeChat.id === window.ME.id) {
      dom.headerName.textContent = result.display_name;
    }
    setModalMessage('profile-settings-msg', 'Настройки сохранены', true);
    await loadSidebar();
  } catch (error) {
    setModalMessage('profile-settings-msg', error.message);
  }
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

function sectionTitle(text, key, count) {
  const div = document.createElement('button');
  div.type = 'button';
  div.className = 'list-section list-section-toggle';
  const collapsed = isSectionCollapsed(key);
  div.innerHTML = `<span>${collapsed ? '▶' : '▼'} ${esc(text)}</span><span>${count}</span>`;
  div.addEventListener('click', () => toggleSection(key));
  return div;
}

function emptyList(text) {
  return `<div class="list-empty">${esc(text)}</div>`;
}

async function loadSidebar() {
  const [friends, channels] = await Promise.all([
    api('/friends'),
    api('/channels'),
  ]);

  dom.chatList.innerHTML = '';

  if (!friends.length && !channels.length) {
    dom.chatList.innerHTML = '<div class="list-empty">Нет чатов.<br>Найдите друга или создайте канал.</div>';
    return;
  }

  if (friends.length) {
    dom.chatList.appendChild(sectionTitle('Личные чаты', 'private', friends.length));
    if (!isSectionCollapsed('private')) {
      friends.forEach(friend => dom.chatList.appendChild(renderChatItem({
        type: 'private',
        id: friend.id,
        name: friend.display_name,
        subtitle: privateListSubtitle(friend),
        time: formatChatTime(friend.last_message_at),
        avatar: firstLetter(friend.display_name),
        online: friend.online,
        data: friend,
      })));
    }
  }

  if (channels.length) {
    dom.chatList.appendChild(sectionTitle('Мои каналы', 'channels', channels.length));
    if (!isSectionCollapsed('channels')) {
      channels.forEach(channel => dom.chatList.appendChild(renderChatItem({
        type: 'channel',
        id: channel.id,
        name: channel.name,
        subtitle: channelListSubtitle(channel),
        time: formatChatTime(channel.last_message_at),
        avatar: '#',
        online: false,
        data: channel,
      })));
    }
  }
}

function renderChatItem({ type, id, name, subtitle, time, avatar, online, data }) {
  const item = document.createElement('div');
  item.className = 'chat-item';
  item.dataset.type = type;
  item.dataset.id = id;
  item.innerHTML = `
    <div class="chat-avatar">
      ${esc(avatar)}
      ${online ? '<span class="avatar-online"></span>' : ''}
    </div>
    <div class="chat-item-body">
      <div class="chat-item-top">
        <div class="chat-item-name">${esc(name)}</div>
        <div class="chat-item-time">${esc(time || '')}</div>
      </div>
      <div class="chat-item-preview">${esc(subtitle)}</div>
    </div>
  `;
  item.addEventListener('click', () => {
    if (type === 'private') openPrivateChat(data);
    else openChannelChat(data);
  });
  return item;
}

function markActive(type, id) {
  document.querySelectorAll('.chat-item').forEach(item => {
    item.classList.toggle('active', item.dataset.type === type && String(item.dataset.id) === String(id));
  });
}

function showChat() {
  dom.noChat.classList.add('hidden');
  dom.chatView.classList.remove('hidden');
}

function closeChat() {
  activeChat = null;
  dom.chatView.classList.add('hidden');
  dom.noChat.classList.remove('hidden');
  document.querySelectorAll('.chat-item').forEach(item => item.classList.remove('active'));
}

function privateStatusText(chat) {
  const parts = [`@${chat.username}`];
  if (chat.is_blocked_by_me) parts.push('вы заблокировали');
  else if (chat.has_blocked_me) parts.push('вас заблокировали');
  else parts.push(chat.is_friend ? 'друг' : 'не в друзьях');
  if (chat.online) parts.push('онлайн');
  return parts.join(' · ');
}

function updatePrivateControls() {
  if (!activeChat || activeChat.type !== 'private') return;

  dom.inviteBtn.classList.add('hidden');
  dom.settingsBtn.classList.add('hidden');
  dom.leaveChannelBtn.classList.add('hidden');
  dom.joinRequestsBtn.classList.add('hidden');
  dom.deleteChatBtn.classList.remove('hidden');

  const blocked = Boolean(activeChat.is_blocked_by_me || activeChat.has_blocked_me);
  dom.addFriendBtn.classList.toggle('hidden', activeChat.is_friend || blocked);
  dom.removeFriendBtn.classList.toggle('hidden', !activeChat.is_friend);
  dom.blockUserBtn.classList.remove('hidden');

  if (activeChat.is_blocked_by_me) {
    dom.blockUserBtn.textContent = '✅';
    dom.blockUserBtn.title = 'Разблокировать пользователя';
  } else {
    dom.blockUserBtn.textContent = '🚫';
    dom.blockUserBtn.title = 'Заблокировать пользователя';
  }

  dom.headerSub.textContent = privateStatusText(activeChat);
  dom.msgInput.disabled = !activeChat.can_message;
  dom.sendBtn.disabled = !activeChat.can_message;
  dom.msgInput.placeholder = activeChat.can_message ? 'Сообщение…' : (activeChat.block_reason || 'Писать нельзя');
}

async function refreshPrivateStatus() {
  if (!activeChat || activeChat.type !== 'private') return null;
  const state = await api(`/private/status/${activeChat.id}`);
  activeChat = { ...activeChat, ...state };
  updatePrivateControls();
  return state;
}

async function openPrivateChat(user) {
  activeChat = {
    type: 'private',
    id: user.id,
    username: user.username,
    display_name: user.display_name,
    online: Boolean(user.online),
    is_friend: Boolean(user.is_friend),
    is_blocked_by_me: Boolean(user.is_blocked_by_me),
    has_blocked_me: Boolean(user.has_blocked_me),
    can_message: user.can_message !== false,
    block_reason: user.block_reason || '',
  };
  markActive('private', user.id);
  showChat();

  dom.headerAvatar.textContent = firstLetter(user.display_name);
  dom.headerName.textContent = user.display_name;
  dom.messages.innerHTML = emptyList('Загрузка сообщений...');
  updatePrivateControls();

  socket.emit('join_private', { other_id: user.id });

  try {
    await refreshPrivateStatus();
    const messages = await api(`/private/messages/${user.id}`);
    renderMessages(messages);
    markPrivateRead(user.id);
    if (!activeChat.can_message && !messages.length) {
      dom.messages.innerHTML = emptyList(activeChat.block_reason || 'Писать в этот чат нельзя');
    }
  } catch (error) {
    dom.messages.innerHTML = emptyList(error.message);
    dom.msgInput.disabled = true;
    dom.sendBtn.disabled = true;
    dom.msgInput.placeholder = error.message;
  }
}

async function openChannelChat(channel) {
  activeChat = { type: 'channel', ...channel };
  markActive('channel', channel.id);
  showChat();

  dom.headerAvatar.textContent = '#';
  dom.headerName.textContent = channel.name;
  dom.headerSub.textContent = `@${channel.username} · ${channel.is_private ? 'закрытый' : 'открытый'} · ${roleText(channel.role)} · ${channel.subscriber_count || 1} участник(ов)`;
  dom.addFriendBtn.classList.add('hidden');
  dom.removeFriendBtn.classList.add('hidden');
  dom.blockUserBtn.classList.add('hidden');
  dom.deleteChatBtn.classList.add('hidden');
  dom.inviteBtn.classList.remove('hidden');
  dom.settingsBtn.classList.toggle('hidden', channel.role !== 'owner');
  dom.leaveChannelBtn.classList.toggle('hidden', channel.role === 'owner');
  dom.joinRequestsBtn.classList.toggle('hidden', !(channel.role === 'owner' || channel.role === 'admin'));

  const canWrite = channel.role === 'owner' || channel.role === 'admin';
  dom.msgInput.disabled = !canWrite;
  dom.sendBtn.disabled = !canWrite;
  dom.msgInput.placeholder = canWrite ? 'Пост в канал…' : 'Писать в канал может только владелец или админ';
  dom.messages.innerHTML = emptyList('Загрузка сообщений...');

  socket.emit('join_channel', { channel_id: channel.id });

  try {
    const messages = await api(`/channels/${channel.id}/messages`);
    renderMessages(messages);
  } catch (error) {
    dom.messages.innerHTML = emptyList(error.message);
  }
}

function renderMessages(messages) {
  dom.messages.innerHTML = '';

  if (!messages.length) {
    dom.messages.innerHTML = emptyList('Пока нет сообщений');
    return;
  }

  messages.forEach(appendMessage);
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function appendMessage(message) {
  const placeholder = dom.messages.querySelector('.list-empty');
  if (placeholder) placeholder.remove();

  const isOwn = message.sender_id === window.ME.id;
  const authorName = message.display_name || message.username;
  const isPrivate = message.chat_type === 'private' || activeChat?.type === 'private';
  const status = message.delivery_status || 'sent';
  const row = document.createElement('div');
  row.className = `msg-row ${isOwn ? 'out' : ''}`;
  if (message.id) row.dataset.messageId = message.id;
  row.innerHTML = `
    <div class="bubble">
      <div class="bubble-meta">
        ${!isOwn ? `<span class="bubble-author">${esc(authorName)}</span>` : ''}
        ${!isOwn && message.username ? `<span class="bubble-tag">@${esc(message.username)}</span>` : ''}
        <span class="bubble-time">${esc(message.created_at)}</span>
        ${isOwn && isPrivate ? `<span class="bubble-status ${status === 'read' ? 'read' : ''}" title="${statusTitle(status)}">${statusIcon(status)}</span>` : ''}
      </div>
      <div class="bubble-text">${linkifyText(message.text)}</div>
    </div>
  `;
  dom.messages.appendChild(row);
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function updateMessageStatuses(ids, status) {
  (ids || []).forEach(id => {
    const row = dom.messages.querySelector(`.msg-row[data-message-id="${id}"]`);
    if (!row) return;
    const el = row.querySelector('.bubble-status');
    if (!el) return;
    el.textContent = statusIcon(status);
    el.title = statusTitle(status);
    el.classList.toggle('read', status === 'read');
  });
}

function markPrivateRead(otherId) {
  if (socket && socket.connected && otherId) {
    socket.emit('mark_private_read', { other_id: otherId });
  }
}

function sendMessage() {
  if (!activeChat) return;
  if (dom.msgInput.disabled || activeChat.can_message === false) {
    showToast(activeChat.block_reason || 'Писать нельзя');
    return;
  }

  const text = dom.msgInput.value.trim();
  if (!text) return;

  if (activeChat.type === 'private') {
    socket.emit('send_private_message', { other_id: activeChat.id, text });
  } else if (activeChat.type === 'channel') {
    socket.emit('send_channel_message', { channel_id: activeChat.id, text });
  }

  dom.msgInput.value = '';
}

function onSearchInput() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(doSearch, 250);
}

async function doSearch() {
  const q = dom.searchInput.value.trim();
  if (!q) {
    dom.searchDropdown.classList.add('hidden');
    dom.searchDropdown.innerHTML = '';
    return;
  }

  try {
    const result = await api(`/search?q=${encodeURIComponent(q)}`);
    renderSearch(result);
  } catch (error) {
    dom.searchDropdown.innerHTML = `<div class="search-empty">${esc(error.message)}</div>`;
    dom.searchDropdown.classList.remove('hidden');
  }
}

function renderSearch(result) {
  dom.searchDropdown.innerHTML = '';
  dom.searchDropdown.classList.remove('hidden');

  const users = result.users || [];
  const channels = result.channels || [];

  if (!users.length && !channels.length) {
    dom.searchDropdown.innerHTML = '<div class="search-empty">Ничего не найдено</div>';
    return;
  }

  if (users.length) {
    dom.searchDropdown.appendChild(searchLabel('Пользователи'));
    users.forEach(user => dom.searchDropdown.appendChild(renderUserSearchItem(user)));
  }

  if (channels.length) {
    dom.searchDropdown.appendChild(searchLabel('Каналы'));
    channels.forEach(channel => dom.searchDropdown.appendChild(renderChannelSearchItem(channel)));
  }
}

function searchLabel(text) {
  const div = document.createElement('div');
  div.className = 'search-label';
  div.textContent = text;
  return div;
}

function renderUserSearchItem(user) {
  const item = document.createElement('div');
  item.className = 'search-item';

  const actions = document.createElement('div');
  actions.className = 'search-item-actions';

  const messageBtn = document.createElement('button');
  messageBtn.className = 'search-item-action';
  messageBtn.textContent = user.can_message ? 'Написать' : 'Открыть';
  messageBtn.addEventListener('click', event => {
    event.stopPropagation();
    dom.searchInput.value = '';
    dom.searchDropdown.classList.add('hidden');
    openPrivateChat(user);
  });
  actions.appendChild(messageBtn);

  const friendBtn = document.createElement('button');
  friendBtn.className = 'search-item-action secondary';
  if (user.is_blocked_by_me || user.has_blocked_me) {
    friendBtn.textContent = 'Блок';
    friendBtn.disabled = true;
  } else if (user.is_friend) {
    friendBtn.textContent = 'Друг';
    friendBtn.disabled = true;
  } else if (user.request_sent) {
    friendBtn.textContent = 'Отправлено';
    friendBtn.disabled = true;
  } else if (user.request_in) {
    friendBtn.textContent = 'Ответить';
    friendBtn.addEventListener('click', event => {
      event.stopPropagation();
      openFriendRequests();
    });
  } else {
    friendBtn.textContent = 'В друзья';
    friendBtn.addEventListener('click', event => {
      event.stopPropagation();
      sendFriendRequest(user.id);
    });
  }
  actions.appendChild(friendBtn);

  const userStatus = user.is_blocked_by_me
    ? 'вы заблокировали'
    : user.has_blocked_me
      ? 'вас заблокировали'
      : user.pm_privacy === 'friends'
        ? 'пишут только друзья'
        : 'можно написать';

  item.innerHTML = `
    <div class="chat-avatar small">${esc(firstLetter(user.display_name))}</div>
    <div class="search-item-info">
      <div class="search-item-name">${esc(user.display_name)}</div>
      <div class="search-item-sub">@${esc(user.username)} · ${userStatus}</div>
    </div>
  `;
  item.appendChild(actions);
  item.addEventListener('click', () => {
    dom.searchInput.value = '';
    dom.searchDropdown.classList.add('hidden');
    openPrivateChat(user);
  });
  return item;
}


function renderChannelSearchItem(channel) {
  const item = document.createElement('div');
  item.className = 'search-item';

  let button = '';
  if (channel.is_member) {
    button = '<button class="search-item-action" disabled>Вы внутри</button>';
  } else if (channel.request_pending) {
    button = '<button class="search-item-action" disabled>Заявка отправлена</button>';
  } else if (channel.is_private) {
    button = `<button class="search-item-action" onclick="joinChannelById(${channel.id})">Подать заявку</button>`;
  } else {
    button = `<button class="search-item-action" onclick="joinChannelById(${channel.id})">Войти</button>`;
  }

  item.innerHTML = `
    <div class="chat-avatar small">#</div>
    <div class="search-item-info">
      <div class="search-item-name">${esc(channel.name)}</div>
      <div class="search-item-sub">@${esc(channel.username)} · ${channel.is_private ? 'закрытый' : 'открытый'} · ${esc(channel.description || 'канал')} · ${channel.subscriber_count} участник(ов)</div>
    </div>
    ${button}
  `;
  return item;
}

async function sendFriendRequest(userId) {
  try {
    await api('/friends/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_id: userId }),
    });
    showToast('Заявка отправлена');
    if (activeChat && activeChat.type === 'private' && activeChat.id === userId) {
      dom.addFriendBtn.classList.add('hidden');
    }
    await doSearch();
  } catch (error) {
    showToast(error.message);
  }
}

async function joinChannelById(channelId) {
  try {
    const result = await api(`/channels/${channelId}/join`, { method: 'POST' });
    if (result.pending) {
      showToast(result.message || 'Заявка отправлена');
      await doSearch();
      return;
    }
    showToast(result.already_member ? 'Вы уже в канале' : 'Вы вошли в канал');
    dom.searchInput.value = '';
    dom.searchDropdown.classList.add('hidden');
    await loadSidebar();
    if (result.channel) openChannelChat(result.channel);
  } catch (error) {
    showToast(error.message);
  }
}

async function doCreateChannel() {
  const name = document.getElementById('ch-name').value.trim();
  const username = document.getElementById('ch-username').value.trim().replace(/^@/, '');
  const description = document.getElementById('ch-desc').value.trim();
  const isPrivate = document.getElementById('ch-private').checked;
  const button = document.querySelector('#create-channel-modal .btn-primary');

  setModalMessage('create-ch-msg', '');

  if (!name || !username) {
    setModalMessage('create-ch-msg', 'Введите название и тег канала');
    return;
  }

  button.disabled = true;
  button.textContent = 'Создаём…';

  try {
    const result = await api('/channels/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, username, description, is_private: isPrivate }),
    });

    document.getElementById('ch-name').value = '';
    document.getElementById('ch-username').value = '';
    document.getElementById('ch-desc').value = '';
    document.getElementById('ch-private').checked = false;
    setModalMessage('create-ch-msg', 'Канал создан', true);
    await loadSidebar();
    closeModal('create-channel-modal');
    openChannelChat(result.channel);
  } catch (error) {
    setModalMessage('create-ch-msg', error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Создать';
  }
}

async function doJoinChannel() {
  const input = document.getElementById('join-invite-input');
  const inviteCode = input.value.trim().split('/').filter(Boolean).pop() || '';
  const button = document.querySelector('#join-channel-modal .btn-primary');

  setModalMessage('join-ch-msg', '');

  if (!inviteCode) {
    setModalMessage('join-ch-msg', 'Введите код или ссылку');
    return;
  }

  button.disabled = true;
  button.textContent = 'Входим…';

  try {
    const result = await api('/channels/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invite_code: inviteCode }),
    });
    input.value = '';
    if (result.pending) {
      setModalMessage('join-ch-msg', result.message || 'Заявка отправлена', true);
      showToast(result.message || 'Заявка отправлена');
      return;
    }
    setModalMessage('join-ch-msg', 'Готово', true);
    await loadSidebar();
    closeModal('join-channel-modal');
    openChannelChat(result.channel);
  } catch (error) {
    setModalMessage('join-ch-msg', error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Войти';
  }
}

function showInvite() {
  if (!activeChat || activeChat.type !== 'channel') return;
  const link = `${location.origin}/?invite=${activeChat.invite_code}`;
  document.getElementById('invite-box').textContent = link;
  document.getElementById('invite-modal').classList.remove('hidden');
}

async function copyInvite() {
  const text = document.getElementById('invite-box').textContent;
  try {
    await navigator.clipboard.writeText(text);
    showToast('Ссылка скопирована');
  } catch (_) {
    showToast('Скопируйте ссылку вручную');
  }
}

async function openChannelSettingsModal() {
  if (!activeChat || activeChat.type !== 'channel' || activeChat.role !== 'owner') return;
  setModalMessage('admins-msg', '');
  document.getElementById('settings-channel-name').value = activeChat.name || '';
  document.getElementById('settings-channel-private').checked = Boolean(activeChat.is_private);
  document.getElementById('channel-settings-modal').classList.remove('hidden');
  await loadAdmins();
}

async function saveChannelSettings() {
  if (!activeChat || activeChat.type !== 'channel' || activeChat.role !== 'owner') return;
  const name = document.getElementById('settings-channel-name').value.trim();
  const isPrivate = document.getElementById('settings-channel-private').checked;

  if (!name) {
    setModalMessage('admins-msg', 'Введите название канала');
    return;
  }

  try {
    const result = await api(`/channels/${activeChat.id}/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, is_private: isPrivate }),
    });
    activeChat = { type: 'channel', ...result.channel };
    setModalMessage('admins-msg', 'Настройки канала сохранены', true);
    await loadSidebar();
    dom.headerName.textContent = activeChat.name;
    dom.headerSub.textContent = `@${activeChat.username} · ${activeChat.is_private ? 'закрытый' : 'открытый'} · ${roleText(activeChat.role)} · ${activeChat.subscriber_count || 1} участник(ов)`;
  } catch (error) {
    setModalMessage('admins-msg', error.message);
  }
}

async function leaveChannel() {
  if (!activeChat || activeChat.type !== 'channel') return;
  if (activeChat.role === 'owner') {
    showToast('Владелец не может выйти из своего канала');
    return;
  }
  const ok = confirm(`Убрать канал «${activeChat.name}» из своих каналов?`);
  if (!ok) return;
  try {
    await api(`/channels/${activeChat.id}/leave`, { method: 'POST' });
    showToast('Канал убран из ваших каналов');
    closeChat();
    await loadSidebar();
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteActivePrivateChat() {
  if (!activeChat || activeChat.type !== 'private') return;
  const ok = confirm(`Удалить чат с ${activeChat.display_name}? Вся история личных сообщений между вами будет стерта из базы данных.`);
  if (!ok) return;

  try {
    await api(`/private/chats/${activeChat.id}`, { method: 'DELETE' });
    showToast('Чат удалён, история очищена');
    closeChat();
    await loadSidebar();
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteActiveChannel() {
  if (!activeChat || activeChat.type !== 'channel' || activeChat.role !== 'owner') return;
  const ok = confirm(`Удалить канал «${activeChat.name}»? Канал, участники, заявки и все посты будут стерты из базы данных.`);
  if (!ok) return;
  try {
    await api(`/channels/${activeChat.id}`, { method: 'DELETE' });
    showToast('Канал удалён');
    closeModal('channel-settings-modal');
    closeChat();
    await loadSidebar();
  } catch (error) {
    setModalMessage('admins-msg', error.message);
  }
}

async function addActiveFriend() {
  if (!activeChat || activeChat.type !== 'private' || activeChat.is_friend) return;
  await sendFriendRequest(activeChat.id);
}

async function removeActiveFriend() {
  if (!activeChat || activeChat.type !== 'private' || !activeChat.is_friend) return;
  const ok = confirm(`Убрать ${activeChat.display_name} из друзей? Чат останется, но если пользователь принимает сообщения только от друзей, писать ему будет нельзя.`);
  if (!ok) return;
  try {
    await api(`/friends/${activeChat.id}`, { method: 'DELETE' });
    showToast('Пользователь убран из друзей');
    await refreshPrivateStatus();
    await loadSidebar();
  } catch (error) {
    showToast(error.message);
  }
}

async function toggleActiveBlock() {
  if (!activeChat || activeChat.type !== 'private') return;
  try {
    if (activeChat.is_blocked_by_me) {
      await api(`/blocks/${activeChat.id}`, { method: 'DELETE' });
      showToast('Пользователь разблокирован');
    } else {
      const ok = confirm(`Заблокировать ${activeChat.display_name}? Чат останется, но писать в него будет нельзя.`);
      if (!ok) return;
      await api(`/blocks/${activeChat.id}`, { method: 'POST' });
      showToast('Пользователь заблокирован');
    }
    await refreshPrivateStatus();
    await loadSidebar();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadAdmins() {
  const adminsList = document.getElementById('admins-list');
  const candidatesList = document.getElementById('admin-candidates-list');
  const searchInput = document.getElementById('admin-search-input');

  adminsList.innerHTML = '<div class="no-requests">Загрузка...</div>';
  candidatesList.innerHTML = '<div class="no-requests">Начните вводить ник или @тег подписчика</div>';
  if (searchInput) searchInput.value = '';

  try {
    const data = await api(`/channels/${activeChat.id}/admins`);
    renderAdminList(data.admins || []);
  } catch (error) {
    adminsList.innerHTML = `<div class="no-requests">${esc(error.message)}</div>`;
  }
}

function renderAdminList(admins) {
  const adminsList = document.getElementById('admins-list');

  if (!admins.length) {
    adminsList.innerHTML = '<div class="no-requests">Админов пока нет</div>';
    return;
  }

  adminsList.innerHTML = '';
  admins.forEach(user => {
    const row = document.createElement('div');
    row.className = 'admin-item';
    const removeButton = user.role === 'admin'
      ? `<button class="btn-decline" onclick="removeAdmin(${user.id})">Снять</button>`
      : '<span class="admin-owner-label">owner</span>';
    row.innerHTML = `
      <div class="chat-avatar small">${esc(firstLetter(user.display_name))}</div>
      <div class="admin-user">
        <div class="admin-name">${esc(user.display_name)}</div>
        <div class="admin-tag">@${esc(user.username)} · ${roleText(user.role)}</div>
      </div>
      ${removeButton}
    `;
    adminsList.appendChild(row);
  });
}

function onAdminSearchInput() {
  clearTimeout(adminSearchTimer);
  adminSearchTimer = setTimeout(() => {
    loadAdminCandidates().catch(error => setModalMessage('admins-msg', error.message));
  }, 250);
}

async function loadAdminCandidates() {
  if (!activeChat || activeChat.type !== 'channel') return;

  const input = document.getElementById('admin-search-input');
  const candidatesList = document.getElementById('admin-candidates-list');
  const query = (input?.value || '').trim();

  if (query.length < 2) {
    candidatesList.innerHTML = '<div class="no-requests">Введите минимум 2 символа для поиска</div>';
    return;
  }

  candidatesList.innerHTML = '<div class="no-requests">Ищем подписчика...</div>';
  const data = await api(`/channels/${activeChat.id}/admins?q=${encodeURIComponent(query)}`);
  renderAdminCandidates(data.candidates || [], query, Boolean(data.candidates_more));
}

function renderAdminCandidates(candidates, query, hasMore) {
  const candidatesList = document.getElementById('admin-candidates-list');

  if (!candidates.length) {
    candidatesList.innerHTML = `<div class="no-requests">Подписчики по запросу «${esc(query)}» не найдены</div>`;
    return;
  }

  candidatesList.innerHTML = '';
  candidates.forEach(user => {
    const row = document.createElement('div');
    row.className = 'admin-item';
    row.innerHTML = `
      <div class="chat-avatar small">${esc(firstLetter(user.display_name))}</div>
      <div class="admin-user">
        <div class="admin-name">${esc(user.display_name)}</div>
        <div class="admin-tag">@${esc(user.username)}</div>
      </div>
      <button class="btn-accept" onclick="addAdmin(${user.id})">Назначить</button>
    `;
    candidatesList.appendChild(row);
  });

  if (hasMore) {
    const more = document.createElement('div');
    more.className = 'no-requests admin-more-hint';
    more.textContent = 'Показаны первые 30 совпадений. Уточните поиск, если нужного пользователя нет.';
    candidatesList.appendChild(more);
  }
}

async function addAdmin(userId) {
  if (!activeChat) return;
  try {
    await api(`/channels/${activeChat.id}/admins`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    setModalMessage('admins-msg', 'Админ добавлен', true);
    await loadAdmins();
  } catch (error) {
    setModalMessage('admins-msg', error.message);
  }
}

async function removeAdmin(userId) {
  if (!activeChat) return;
  try {
    await api(`/channels/${activeChat.id}/admins/${userId}`, { method: 'DELETE' });
    setModalMessage('admins-msg', 'Админ снят', true);
    await loadAdmins();
  } catch (error) {
    setModalMessage('admins-msg', error.message);
  }
}

async function openJoinRequestsModal() {
  if (!activeChat || activeChat.type !== 'channel' || !(activeChat.role === 'owner' || activeChat.role === 'admin')) return;
  setModalMessage('channel-join-requests-msg', '');
  document.getElementById('join-requests-modal').classList.remove('hidden');
  await loadChannelJoinRequests();
}

async function loadChannelJoinRequests() {
  const list = document.getElementById('channel-join-requests-list');
  list.innerHTML = '<div class="no-requests">Загрузка...</div>';

  try {
    const requests = await api(`/channels/${activeChat.id}/join-requests`);
    renderChannelJoinRequests(requests);
  } catch (error) {
    list.innerHTML = `<div class="no-requests">${esc(error.message)}</div>`;
  }
}

function renderChannelJoinRequests(requests) {
  const list = document.getElementById('channel-join-requests-list');

  if (!requests.length) {
    list.innerHTML = '<div class="no-requests">Заявок пока нет</div>';
    return;
  }

  list.innerHTML = '';
  requests.forEach(req => {
    const div = document.createElement('div');
    div.className = 'fr-item';
    div.innerHTML = `
      <div class="chat-avatar small">${esc(firstLetter(req.display_name))}</div>
      <div class="fr-name">${esc(req.display_name)}<br><span class="muted-small">@${esc(req.username)} · ${esc(req.created_at)}</span></div>
      <div class="fr-actions">
        <button class="btn-accept" onclick="respondChannelJoinRequest(${req.id}, 'accept')">Принять</button>
        <button class="btn-decline" onclick="respondChannelJoinRequest(${req.id}, 'decline')">Отклонить</button>
      </div>
    `;
    list.appendChild(div);
  });
}

async function respondChannelJoinRequest(requestId, action) {
  if (!activeChat) return;
  try {
    await api(`/channels/${activeChat.id}/join-requests/${requestId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    setModalMessage('channel-join-requests-msg', action === 'accept' ? 'Заявка принята' : 'Заявка отклонена', true);
    await loadChannelJoinRequests();
    await loadSidebar();
  } catch (error) {
    setModalMessage('channel-join-requests-msg', error.message);
  }
}

async function loadFriendRequests() {
  const list = document.getElementById('friend-requests-list');
  const requests = await api('/friends/requests');

  if (dom.reqBadge) {
    dom.reqBadge.textContent = requests.length;
    dom.reqBadge.classList.toggle('hidden', requests.length === 0);
  }

  if (!requests.length) {
    list.innerHTML = '<div class="no-requests">Новых заявок нет</div>';
    return;
  }

  list.innerHTML = '';
  requests.forEach(req => {
    const div = document.createElement('div');
    div.className = 'fr-item';
    div.innerHTML = `
      <div class="chat-avatar small">${esc(firstLetter(req.display_name))}</div>
      <div class="fr-name">${esc(req.display_name)}<br><span class="muted-small">@${esc(req.username)}</span></div>
      <div class="fr-actions">
        <button class="btn-accept" onclick="respondFriendRequest(${req.id}, 'accept')">Принять</button>
        <button class="btn-decline" onclick="respondFriendRequest(${req.id}, 'decline')">Отклонить</button>
      </div>
    `;
    list.appendChild(div);
  });
}

async function respondFriendRequest(requestId, action) {
  try {
    await api('/friends/respond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, action }),
    });
    await loadFriendRequests();
    await loadSidebar();
    showToast(action === 'accept' ? 'Теперь вы друзья' : 'Заявка отклонена');
  } catch (error) {
    showToast(error.message);
  }
}

function setupSocket() {
  socket = io();

  socket.on('connect', () => {
    loadSidebar().catch(error => showToast(error.message));
    loadFriendRequests().catch(() => {});
  });

  socket.on('online_update', () => {
    loadSidebar().catch(() => {});
  });

  socket.on('friend_request_in', data => {
    showToast(`Новая заявка от ${data.display_name || '@' + data.username}`);
    loadFriendRequests().catch(() => {});
  });

  socket.on('friend_accepted', data => {
    showToast(`${data.display_name || '@' + data.username} принял заявку`);
    loadSidebar().catch(() => {});
  });

  socket.on('channel_join_request', data => {
    showToast(`Новая заявка в ${data.channel_name} от ${data.display_name || '@' + data.username}`);
    if (activeChat && activeChat.type === 'channel' && activeChat.id === data.channel_id) {
      loadChannelJoinRequests().catch(() => {});
    }
  });

  socket.on('channel_join_approved', data => {
    showToast(`Заявка в ${data.channel_name} одобрена`);
    loadSidebar().then(() => {
      if (data.channel) openChannelChat(data.channel);
    }).catch(() => {});
  });

  socket.on('channel_join_declined', data => {
    showToast(`Заявка в ${data.channel_name} отклонена`);
    doSearch().catch(() => {});
  });

  socket.on('new_private_message', message => {
    const partnerId = message.sender_id === window.ME.id ? message.receiver_id : message.sender_id;
    if (activeChat && activeChat.type === 'private' && activeChat.id === partnerId) {
      appendMessage(message);
      if (message.sender_id !== window.ME.id) {
        markPrivateRead(partnerId);
      }
    } else if (message.sender_id !== window.ME.id) {
      showToast(`Новое сообщение от ${message.display_name || '@' + message.username}`);
    }
    loadSidebar().catch(() => {});
  });

  socket.on('private_messages_status', data => {
    updateMessageStatuses(data.message_ids || [], data.status);
    loadSidebar().catch(() => {});
  });

  socket.on('new_channel_message', message => {
    if (activeChat && activeChat.type === 'channel' && activeChat.id === message.channel_id) {
      appendMessage(message);
    }
    loadSidebar().catch(() => {});
  });

  socket.on('channel_deleted', data => {
    showToast(`Канал «${data.name}» удалён`);
    if (activeChat && activeChat.type === 'channel' && activeChat.id === data.channel_id) {
      closeModal('channel-settings-modal');
      closeChat();
    }
    loadSidebar().catch(() => {});
  });

  socket.on('private_chat_deleted', data => {
    loadSidebar().catch(() => {});
    if (activeChat && activeChat.type === 'private' && activeChat.id === data.peer_id) {
      dom.messages.innerHTML = emptyList('Чат удалён, история очищена');
      refreshPrivateStatus().catch(() => {});
    }
  });

  socket.on('relationship_changed', data => {
    loadSidebar().catch(() => {});
    if (activeChat && activeChat.type === 'private' && activeChat.id === data.user_id) {
      refreshPrivateStatus().catch(() => {});
    }
  });

  socket.on('app_error', data => {
    showToast(data.error || 'Ошибка');
    if (activeChat && activeChat.type === 'private') {
      refreshPrivateStatus().catch(() => {});
    }
  });
}

function setupEvents() {
  dom.msgInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') sendMessage();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      document.querySelectorAll('.modal-overlay').forEach(modal => modal.classList.add('hidden'));
      dom.searchDropdown.classList.add('hidden');
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initDom();
  setupSocket();
  setupEvents();

  const invite = new URLSearchParams(location.search).get('invite');
  if (invite) {
    document.getElementById('join-invite-input').value = invite;
    document.getElementById('join-channel-modal').classList.remove('hidden');
  }
});
