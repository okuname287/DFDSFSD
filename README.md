# Londo Family — Discord Bot + Web Panel

Система заявок в семью с Discord-ботом и веб-панелью для рассмотрения.

## Возможности

- **Discord-бот**: команда `/заявка` → выбор сервера → модальное окно → загрузка скриншота
- **Два кабинета**: Memphis и Phoenix — раздельное рассмотрение заявок
- **Веб-панель**: рассмотрение заявок рекрутами и кураторами
- **4 действия**: одобрить, отклонить (с выбором причины), на обзвон
- **DM-уведомления**: красивые embed-сообщения в личку после каждого действия
- **Логи**: старший состав видит историю всех действий
- **Настройки**: всё в одном файле `config.yaml`

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка `config.yaml`

```yaml
discord:
  token: "ВАШ_ТОКЕН_БОТА"
  guild_id: 123456789          # ID Discord-сервера
  review_channel_id: 123456789 # Канал для новых заявок
  roles:
    recruiter: 123456789       # Роль рекрута
    recruit_curator: 123456789 # Роль куратора рекрутов
    senior_staff: 123456789    # Роль старшего состава
  approved_roles:
    memphis: 123456789         # Роль при одобрении (Memphis)
    phoenix: 123456789         # Роль при одобрении (Phoenix)

web:
  secret_key: "случайная_строка"
  api_secret: "другая_случайная_строка"
  oauth:
    client_id: "ID приложения Discord"
    client_secret: "Secret приложения Discord"
    redirect_uri: "http://localhost:8080/auth/callback"
```

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
