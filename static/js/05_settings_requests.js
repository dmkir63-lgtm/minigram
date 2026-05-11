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
