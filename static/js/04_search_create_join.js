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
