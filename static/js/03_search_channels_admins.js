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
