# colivingfam

Telegram-бот для коливинга: учёт жителей (комнаты **F1–F12**), привязка Telegram, выдача **ссылки подписки** и **QR** для **VLESS** через панель **3x-ui**. Лимит жителей по умолчанию — **50**.

## Безопасность

- Токен бота и пароль панели храните только в `.env` на сервере. При утечке — [отозвать токен](https://t.me/BotFather) и сменить пароль в панели.
- Файл `.env` не коммитится. В репозитории есть [.env.example](.env.example).

## Требования

- Аккаунт в 3x-ui с доступом к API (логин по HTTPS).
- В панели настроен **VLESS inbound**; его числовой **ID** указать в `XUI_INBOUND_ID`.
- У бота в Telegram задан **@username** (нужен для ссылок привязки).

## Переменные окружения

См. [.env.example](.env.example). Кратко:

| Переменная | Назначение |
|------------|------------|
| `BOT_TOKEN` | Токен Telegram-бота |
| `TELEGRAM_ADMIN_IDS` | ID админов через запятую |
| `DATABASE_PATH` | Путь к SQLite (в Docker: `/data/app.db`) |
| `MAX_RESIDENTS` | Лимит записей (по умолчанию 50) |
| `XUI_BASE_URL` | Базовый URL панели **с WebBasePath**, без завершающего `/` |
| `XUI_USERNAME`, `XUI_PASSWORD` | Учётная запись панели |
| `XUI_INBOUND_ID` | ID inbound (VLESS) |
| `XUI_VLESS_FLOW` | Необязательно, например `xtls-rprx-vision` |
| `SUBSCRIPTION_BASE_URL` | Публичный префикс subscription-сервера 3x-ui, **с завершающим /** (если пусто — `{XUI_BASE_URL}/sub/{subId}`) |
| `XUI_VERIFY_TLS` | `true` / `false` (только для отладки с self-signed) |

## Запуск в Docker (рекомендуется)

```bash
cp .env.example .env
# отредактируйте .env

docker compose build
docker compose up -d
docker compose logs -f
```

База SQLite сохраняется в named volume `bot_data`, путь в контейнере задайте `DATABASE_PATH=/data/app.db`.

### Доступ бота к панели с Docker

Если панель доступна по домену (например `https://colivingfam.icu:2254/<WebBasePath>`), укажите этот URL в `XUI_BASE_URL` — контейнер ходит наружу по HTTPS так же, как ваш ноутбук.

## Локальная разработка

Один и тот же `BOT_TOKEN` нельзя одновременно использовать в двух процессах (конфликт long polling). Остановите контейнер на VPS или заведите второго бота для разработки.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)   # или вручную
python -m vpn_bot
```

## Роли в Telegram

**Админ** (ID в `TELEGRAM_ADMIN_IDS`):

- `/start` или `/admin` — меню.
- Список жителей, добавление (имя → фамилия → комната), удаление, выдача **кода привязки** (ссылка для жителя).

**Житель**: переходит по ссылке с `start=link_...` или вводит код после `/start`, затем пользуется кнопками «Ссылка подписки» и «QR».

## Бэкап SQLite

На хосте (где лежит файл БД или том Docker):

```bash
chmod +x scripts/backup_sqlite.sh
# пример: путь к файлу на хосте после docker volume inspect
./scripts/backup_sqlite.sh /var/lib/docker/volumes/.../_data/app.db /var/backups/colivingfam-bot
```

Копирование на свой ПК: `scp` / `rsync` с ключом SSH (секреты не храните в репозитории).

## systemd (опционально)

Пример unit, который поднимает compose из каталога проекта:

```ini
[Unit]
Description=Colivingfam VPN Telegram bot
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/colivingfam
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Уточните путь к `docker compose` и каталогу репозитория на вашем сервере.
