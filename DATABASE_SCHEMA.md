# Схема БД MiniGram

## Связи

```text
users
├─ email_codes
├─ friend_requests: from_id, to_id → users.id
├─ user_blocks: blocker_id, blocked_id → users.id
├─ hidden_private_chats: user_id, peer_id → users.id
├─ channels: owner_id → users.id
├─ channel_members: channel_id → channels.id, user_id → users.id
├─ channel_join_requests: channel_id → channels.id, user_id/responded_by → users.id
├─ messages: sender_id/receiver_id → users.id, channel_id → channels.id
├─ message_reactions: message_id → messages.id, user_id → users.id
├─ telegram_links: user_id → users.id
├─ telegram_link_tokens: user_id → users.id
└─ api_tokens: user_id → users.id
```

## Таблицы

### `users`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID пользователя |
| `username` | `TEXT UNIQUE NOT NULL` | уникальный тег |
| `display_name` | `TEXT` | имя в интерфейсе |
| `email` | `TEXT UNIQUE NOT NULL` | email |
| `password_hash` | `TEXT NOT NULL` | хеш пароля |
| `pm_privacy` | `TEXT NOT NULL DEFAULT 'everyone'` | кто может писать |
| `email_notifications_mode` | `TEXT NOT NULL DEFAULT 'disabled'` | пересылка личных сообщений на email |
| `created_at` | `TEXT NOT NULL` | дата создания |

---

### `email_codes`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID кода |
| `email` | `TEXT NOT NULL` | email |
| `code` | `TEXT NOT NULL` | код подтверждения |
| `username` | `TEXT NOT NULL` | тег пользователя |
| `display_name` | `TEXT` | имя |
| `password_hash` | `TEXT NOT NULL` | хеш пароля |
| `expires_at` | `TEXT NOT NULL` | срок действия |

---

### `friend_requests`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID заявки |
| `from_id` | `INTEGER NOT NULL` | кто отправил |
| `to_id` | `INTEGER NOT NULL` | кому отправили |
| `status` | `TEXT NOT NULL DEFAULT 'pending'` | `pending` / `accepted` |
| `created_at` | `TEXT NOT NULL` | дата создания |

Ограничение:

```sql
UNIQUE(from_id, to_id)
```

---

### `user_blocks`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID блокировки |
| `blocker_id` | `INTEGER NOT NULL` | кто заблокировал |
| `blocked_id` | `INTEGER NOT NULL` | кого заблокировали |
| `created_at` | `TEXT NOT NULL` | дата блокировки |

Ограничение:

```sql
UNIQUE(blocker_id, blocked_id)
```

---

### `hidden_private_chats`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID записи |
| `user_id` | `INTEGER NOT NULL` | кто скрыл чат |
| `peer_id` | `INTEGER NOT NULL` | с кем чат |
| `hidden_at` | `TEXT NOT NULL` | дата скрытия |

Ограничение:

```sql
UNIQUE(user_id, peer_id)
```

---

### `channels`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID канала |
| `name` | `TEXT NOT NULL` | название |
| `username` | `TEXT` | тег канала |
| `description` | `TEXT` | описание |
| `owner_id` | `INTEGER NOT NULL` | владелец |
| `invite_code` | `TEXT UNIQUE NOT NULL` | инвайт-код |
| `is_private` | `INTEGER NOT NULL DEFAULT 0` | приватность |
| `created_at` | `TEXT NOT NULL` | дата создания |

---

### `channel_members`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID записи |
| `channel_id` | `INTEGER NOT NULL` | ID канала |
| `user_id` | `INTEGER NOT NULL` | ID пользователя |
| `role` | `TEXT NOT NULL DEFAULT 'subscriber'` | `owner` / `admin` / `subscriber` |
| `joined_at` | `TEXT NOT NULL` | дата вступления |

Ограничение:

```sql
UNIQUE(channel_id, user_id)
```

---

### `channel_join_requests`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID заявки |
| `channel_id` | `INTEGER NOT NULL` | ID канала |
| `user_id` | `INTEGER NOT NULL` | кто подал заявку |
| `status` | `TEXT NOT NULL DEFAULT 'pending'` | `pending` / `accepted` / `declined` |
| `created_at` | `TEXT NOT NULL` | дата создания |
| `responded_at` | `TEXT` | дата ответа |
| `responded_by` | `INTEGER` | кто ответил |

Ограничение:

```sql
UNIQUE(channel_id, user_id)
```

---

### `messages`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID сообщения |
| `chat_type` | `TEXT NOT NULL` | `private` / `channel` |
| `channel_id` | `INTEGER` | канал |
| `sender_id` | `INTEGER NOT NULL` | отправитель |
| `receiver_id` | `INTEGER` | получатель личного сообщения |
| `username` | `TEXT NOT NULL` | username отправителя |
| `text` | `TEXT NOT NULL` | текст |
| `delivery_status` | `TEXT NOT NULL DEFAULT 'sent'` | `sent` / `delivered` / `read` |
| `delivered_at` | `TEXT` | дата доставки |
| `read_at` | `TEXT` | дата прочтения |
| `created_at` | `TEXT NOT NULL` | дата создания |

---

### `message_reactions`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID реакции |
| `message_id` | `INTEGER NOT NULL` | сообщение |
| `user_id` | `INTEGER NOT NULL` | кто поставил реакцию |
| `emoji` | `TEXT NOT NULL` | эмодзи реакции |
| `created_at` | `TEXT NOT NULL` | дата создания |

Ограничение:

```sql
UNIQUE(message_id, user_id, emoji)
```

---

### `telegram_links`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID привязки |
| `user_id` | `INTEGER UNIQUE NOT NULL` | пользователь MiniGram |
| `telegram_chat_id` | `TEXT UNIQUE NOT NULL` | chat id Telegram |
| `telegram_user_id` | `TEXT` | user id Telegram |
| `telegram_username` | `TEXT` | username Telegram |
| `notifications_mode` | `TEXT NOT NULL DEFAULT 'offline'` | `disabled` / `offline` / `all` |
| `last_peer_id` | `INTEGER` | последний собеседник для ответа из Telegram |
| `linked_at` | `TEXT NOT NULL` | дата привязки |
| `updated_at` | `TEXT NOT NULL` | дата обновления |

---

### `telegram_link_tokens`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID токена |
| `user_id` | `INTEGER NOT NULL` | пользователь MiniGram |
| `token` | `TEXT UNIQUE NOT NULL` | одноразовый токен `/start` |
| `created_at` | `TEXT NOT NULL` | дата создания |
| `expires_at` | `TEXT NOT NULL` | срок действия |

---

### `api_tokens`

| Поле | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ID токена |
| `user_id` | `INTEGER NOT NULL` | владелец токена |
| `name` | `TEXT` | имя токена для клиента |
| `token_hash` | `TEXT UNIQUE NOT NULL` | SHA-256 хеш токена |
| `created_at` | `TEXT NOT NULL` | дата создания |
| `last_used_at` | `TEXT` | дата последнего использования |

## Индексы

```sql
idx_channels_username_unique
idx_messages_private
idx_messages_private_receiver
idx_messages_channel
idx_messages_delivery
idx_message_reactions_message
idx_message_reactions_user
idx_friend_to
idx_user_blocks_blocker
idx_user_blocks_blocked
idx_hidden_private_chats_user
idx_channel_members_channel_role
idx_channel_join_requests_channel_status
idx_channel_join_requests_user_status
idx_telegram_links_chat
idx_telegram_tokens_token
idx_telegram_tokens_user
idx_api_tokens_hash
idx_api_tokens_user
```
