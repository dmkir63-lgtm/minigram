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
    loadFriendRequests().catch(() => { });
  });

  socket.on('online_update', () => {
    loadSidebar().catch(() => { });
  });

  socket.on('friend_request_in', data => {
    showToast(`Новая заявка от ${data.display_name || '@' + data.username}`);
    loadFriendRequests().catch(() => { });
  });

  socket.on('friend_accepted', data => {
    showToast(`${data.display_name || '@' + data.username} принял заявку`);
    loadSidebar().catch(() => { });
  });

  socket.on('channel_join_request', data => {
    showToast(`Новая заявка в ${data.channel_name} от ${data.display_name || '@' + data.username}`);
    if (activeChat && activeChat.type === 'channel' && activeChat.id === data.channel_id) {
      loadChannelJoinRequests().catch(() => { });
    }
  });

  socket.on('channel_join_approved', data => {
    showToast(`Заявка в ${data.channel_name} одобрена`);
    loadSidebar().then(() => {
      if (data.channel) openChannelChat(data.channel);
    }).catch(() => { });
  });

  socket.on('channel_join_declined', data => {
    showToast(`Заявка в ${data.channel_name} отклонена`);
    doSearch().catch(() => { });
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
    loadSidebar().catch(() => { });
  });

  socket.on('private_messages_status', data => {
    updateMessageStatuses(data.message_ids || [], data.status);
    loadSidebar().catch(() => { });
  });

  socket.on('new_channel_message', message => {
    if (activeChat && activeChat.type === 'channel' && activeChat.id === message.channel_id) {
      appendMessage(message);
    }
    loadSidebar().catch(() => { });
  });

  socket.on('channel_deleted', data => {
    showToast(`Канал «${data.name}» удалён`);
    if (activeChat && activeChat.type === 'channel' && activeChat.id === data.channel_id) {
      closeModal('channel-settings-modal');
      closeChat();
    }
    loadSidebar().catch(() => { });
  });

  socket.on('private_chat_deleted', data => {
    loadSidebar().catch(() => { });
    if (activeChat && activeChat.type === 'private' && activeChat.id === data.peer_id) {
      dom.messages.innerHTML = emptyList('Чат удалён, история очищена');
      refreshPrivateStatus().catch(() => { });
    }
  });

  socket.on('relationship_changed', data => {
    loadSidebar().catch(() => { });
    if (activeChat && activeChat.type === 'private' && activeChat.id === data.user_id) {
      refreshPrivateStatus().catch(() => { });
    }
  });

  socket.on('app_error', data => {
    showToast(data.error || 'Ошибка');
    if (activeChat && activeChat.type === 'private') {
      refreshPrivateStatus().catch(() => { });
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
