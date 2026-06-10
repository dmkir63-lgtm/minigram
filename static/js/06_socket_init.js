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

  socket.on('message_reactions_updated', data => {
    updateMessageReactions(data.message_id, data.reactions || [], data.user_id, data.emoji, data.reacted);
  });

  socket.on('message_deleted', data => {
    removeMessage(data.message_id);
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
      closeEmojiPicker();
      document.querySelectorAll('.reaction-menu').forEach(menu => menu.remove());
    }
  });

  document.addEventListener('click', event => {
    if (dom.emojiPicker && dom.emojiBtn && !dom.emojiPicker.contains(event.target) && !dom.emojiBtn.contains(event.target)) {
      closeEmojiPicker();
    }
    if (!event.target.closest('.bubble-action') && !event.target.closest('.reaction-menu')) {
      document.querySelectorAll('.reaction-menu').forEach(menu => menu.remove());
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
