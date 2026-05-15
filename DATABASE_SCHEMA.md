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
└─ messages: sender_id/receiver_id → users.id, channel_id → channels.id
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

## Индексы

```sql
idx_channels_username_unique
idx_messages_private
idx_messages_private_receiver
idx_messages_channel
idx_messages_delivery
idx_friend_to
idx_user_blocks_blocker
idx_user_blocks_blocked
idx_hidden_private_chats_user
idx_channel_members_channel_role
idx_channel_join_requests_channel_status
idx_channel_join_requests_user_status
```
