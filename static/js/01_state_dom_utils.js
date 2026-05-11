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
