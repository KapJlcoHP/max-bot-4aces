# Деплой «МедМаршрут» на VPS (Ubuntu 24.04, Beget)

Схема: Docker Compose поднимает `app` (FastAPI: REST API + собранный мини-ап),
`caddy` (HTTPS, сертификат Let's Encrypt автоматически) и `bot` (команды,
напоминания и отправка PDF в чат).
База SQLite лежит в папке `database/` на хосте — переживает пересборки.

Команды выполняются по SSH на сервере (Windows: `ssh root@IP_СЕРВЕРА`,
подойдёт PowerShell или утилита из панели Beget).

## 0. DNS

В личном кабинете DuckDNS поддомен `4acesmax` должен
указывать на IPv4-адрес сервера (A-запись). Проверить с компьютера:

```
ping 4acesmax.duckdns.org
```

в ответе должен быть IP сервера.

## 1. Установка Docker (один раз)

```
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

Обе версии должны отобразиться.

## 2. Код

```
apt update && apt install -y git
cd /opt
git clone https://github.com/KapJlcoHP/max-bot-4aces.git zabota
cd zabota
git switch main
git rev-parse HEAD
```

Для зафиксированной версии сдачи вместо обновления ветки используйте её commit hash.

## 3. Конфигурация

```
cp .env.example .env
nano .env
```

Заполнить:

- `MAX_BOT_TOKEN` — реальный токен (нужен серверу для проверки подписи
  initData; в репозиторий и git не попадает);
- `MINIAPP_PUBLIC_URL=https://4acesmax.duckdns.org`;
- `MEDROUTE_DOMAIN=4acesmax.duckdns.org`;
- `DEV_BYPASS_AUTH` — оставить `false` (на сервере вход только по
  подписанному initData из MAX).
- `TEST_API_TOKEN` — задать отдельно, если нужна автоматическая проверка API;
  значение передать проверяющим вне репозитория.

Сохранение в nano: Ctrl+O, Enter, выход: Ctrl+X.

## 4. Запуск

```
docker compose --profile prod --profile bot up -d --build
```

Перед запуском остановите другие экземпляры бота с тем же токеном: long polling
должен работать в одном месте. Первая сборка занимает несколько минут.

## 5. Проверка

```
curl http://127.0.0.1:8000/api/v1/health        # {"status":"ok"} — приложение живо
curl https://4acesmax.duckdns.org/api/v1/health   # то же по HTTPS — Caddy и сертификат работают
```

Сертификат выпускается при первом обращении — если сразу не отвечает,
подождите минуту и повторите.

Затем проверьте `/start` в MAX → кнопку мини-приложения → онбординг → маршрут,
дневники и PDF в чат. В обычном браузере без подписанного initData вход на
продакшене закрыт; демо-режим доступен только при `DEV_BYPASS_AUTH=true` локально.
Проверка `/api/v1/health` сама по себе не подтверждает работу бота и сценария.

## 6. Эксплуатация

```
docker compose --profile prod --profile bot ps             # состояние всех сервисов
docker compose --profile prod --profile bot logs -f app bot caddy
docker compose --profile prod --profile bot restart app    # перезапустить API
docker compose --profile prod --profile bot down           # остановить всё
docker compose --profile prod --profile bot up -d --build  # запустить снова
```

Обновление версии (после git push локально):

```
cd /opt/zabota && git pull --ff-only origin main
docker compose --profile prod --profile bot up -d --build
```

Не редактировать файлы прямо на сервере — код должен совпадать с
репозиторием (после дедлайна версия фиксируется).

## 7. Если бот не отвечает

Убедитесь, что сервис `bot` запущен и другой экземпляр с тем же токеном остановлен.
Для диагностики:

```
docker compose --profile prod --profile bot ps
docker compose --profile prod --profile bot logs --tail=100 bot
```
