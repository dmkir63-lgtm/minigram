# MiniGram

Учебный веб-мессенджер на Flask, Socket.IO и SQLite/SQLCipher.

## Запуск через Docker

### 1. Склонировать проект

```bash
git clone <https://github.com/jaruccky/minigram.git>
cd minigram
```

### 2. Создать `.env`

```bash
cp .env.example .env
nano .env
```

Пример `.env`:

```env
SECRET_KEY=your-secret-key
DB_ENCRYPTION_KEY=your-db-encryption-key

DB_PATH=/app/data/mini_telegram_encrypted.db

SMTP_USER=
SMTP_PASS=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587

APP_HOST=0.0.0.0
APP_PORT=5000
PUBLIC_PORT=5000

FLASK_DEBUG=0
```

Сгенерировать ключи можно так:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Создать папку для базы

```bash
mkdir -p data
```

### 4. Запустить проект

```bash
sudo docker-compose up --build
```

### 5. Открыть сайт


На сервере:

```text
http://IP_СЕРВЕРА:5000
```

Если нужно изменить внешний порт, поменяйте в `.env`:

```env
PUBLIC_PORT=8080
```

Тогда сайт будет доступен по адресу:

```text
http://localhost:8080
```

## SMTP

SMTP нужен для отправки кодов подтверждения на email.

Для Gmail нужно создать App Password и указать:

```env
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

Если `SMTP_USER` и `SMTP_PASS` пустые, код подтверждения будет выводиться в консоль Docker.
