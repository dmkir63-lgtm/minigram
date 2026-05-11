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
