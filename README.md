# Londo Family — Discord Bot + Web Panel

Система заявок в семью с Discord-ботом и веб-панелью для рассмотрения.

## Возможности

- **Discord-бот**: команда `/заявка` → выбор сервера → модальное окно → загрузка скриншота
- **Два кабинета**: Memphis и Phoenix — раздельное рассмотрение заявок
- **Веб-панель**: рассмотрение заявок рекрутами и кураторами
- **4 действия**: одобрить, отклонить (с выбором причины), на обзвон
- **DM-уведомления**: красивые embed-сообщения в личку после каждого действия
- **Логи**: старший состав видит историю всех действий
- **Настройки**: все значения загружаются из ENV-файла

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка ENV

```dotenv
DISCORD_TOKEN=ВАШ_ТОКЕН_БОТА
DISCORD_GUILD_ID=123456789
WEB_SECRET_KEY=случайная_строка
WEB_API_SECRET=другая_случайная_строка
DISCORD_OAUTH_CLIENT_ID=ID_ПРИЛОЖЕНИЯ
DISCORD_OAUTH_CLIENT_SECRET=СЕКРЕТ_ПРИЛОЖЕНИЯ
DISCORD_OAUTH_REDIRECT_URI=http://localhost:8080/auth/callback
```

Загрузчик ищет `.env`, а если его нет, использует локальный `1.env`. Оба файла не должны попадать в Git.

### 3. Создание Discord-приложения

1. Перейдите на [Discord Developer Portal](https://discord.com/developers/applications)
2. Создайте приложение → Bot → скопируйте токен
3. Включите **Privileged Gateway Intents**: `Message Content`, `Server Members`
4. OAuth2 → добавьте redirect URI: `http://localhost:8080/auth/callback`
5. Scopes для OAuth: `identify`, `guilds.members.read`
6. Пригласите бота на сервер с правами: `Send Messages`, `Manage Roles`, `Use Slash Commands`

### 4. Запуск

Сайт и бот можно запустить одной командой:

```bash
python run.py
```

Отдельный запуск тоже доступен:

```bash
python run_web.py  # только сайт
python run_bot.py  # только бот
```

Сайт: http://localhost:8080

## Как это работает

```
Пользователь                    Сайт                         Discord
     │                            │                              │
     ├── /заявка ─────────────────┼─────────────────────────────►│
     │   (модал + скриншот)       │                              │
     │                            │◄── POST /api/applications ───┤
     │                            │                              │
     │◄── DM: заявка отправлена ──┼──────────────────────────────┤
     │                            │                              │
     │                     Рекрут рассматривает                  │
     │                     на сайте или в Discord                │
     │                            │                              │
     │◄── DM: результат ──────────┼──────────────────────────────┤
```

## Роли и доступ

| Роль | Discord | Сайт |
|------|---------|------|
| Рекрут | Кнопки рассмотрения | Одобрение/отклонение/обзвон |
| Куратор рекрутов | Кнопки рассмотрения | Одобрение/отклонение/обзвон |
| Старший состав | — | Просмотр логов |

## Структура проекта

```
├── config.yaml          # Все настройки
├── run_bot.py           # Запуск бота
├── run_web.py           # Запуск сайта
├── bot/
│   ├── main.py          # Discord-бот
│   ├── views.py         # Модалы, кнопки, select
│   └── notifications.py # Embed-шаблоны DM
├── web/
│   ├── main.py          # FastAPI приложение
│   ├── templates/       # HTML-шаблоны
│   └── static/css/      # Стили
└── shared/
    ├── config.py        # Загрузка config.yaml
    ├── models.py        # БД (SQLAlchemy)
    ├── services.py      # Бизнес-логика
    ├── schemas.py       # Pydantic-схемы
    ├── discord_api.py   # Discord REST API
    └── notify.py        # Уведомления пользователей
```
