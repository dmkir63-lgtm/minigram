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
