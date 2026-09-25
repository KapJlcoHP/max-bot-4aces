# Деплой «МедМаршрут» на VPS (Ubuntu 24.04, Beget)

Схема: Docker Compose поднимает два сервиса — `app` (FastAPI: REST API +
собранный мини-ап) и `caddy` (HTTPS, сертификат Let's Encrypt автоматически).
База SQLite лежит в папке `database/` на хосте — переживает пересборки.

Команды выполняются по SSH на сервере (Windows: `ssh root@IP_СЕРВЕРА`,
подойдёт PowerShell или утилита из панели Beget).

## 0. DNS

В личном кабинете DuckDNS поддомен (например `medroute-4aces`) должен
указывать на IPv4-адрес сервера (A-запись). Проверить с компьютера:

```
ping medroute-4aces.duckdns.org
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
git checkout MAX_UI
```

## 3. Конфигурация

```
cp .env.example .env
nano .env
```

Заполнить:

- `MAX_BOT_TOKEN` — реальный токен (нужен серверу для проверки подписи
  initData; в репозиторий и git не попадает);
- `MINIAPP_PUBLIC_URL=https://medroute-4aces.duckdns.org`;
- `MEDROUTE_DOMAIN=medroute-4aces.duckdns.org`;
- `DEV_BYPASS_AUTH` — оставить `false` (на сервере вход только по
  подписанному initData из MAX).

Сохранение в nano: Ctrl+O, Enter, выход: Ctrl+X.

## 4. Запуск

```
docker compose --profile prod up -d --build
```

Первая сборка занимает несколько минут. Повторные запуски после правок —
та же команда (кэш ускоряет).

## 5. Проверка

```
curl http://127.0.0.1:8000/api/v1/health        # {"status":"ok"} — приложение живо
curl https://medroute-4aces.duckdns.org/api/v1/health   # то же по HTTPS — Caddy и сертификат работают
```

Сертификат выпускается при первом обращении — если сразу не отвечает,
подождите минуту и повторите.

Затем — чек-лист из пяти слоёв: health → мини-ап в браузере телефона
(баннер «Демо-режим») → /start в MAX и кнопка мини-апа (без баннера,
реальное имя = initData проверен) → полный сценарий → логи при проблемах.

## 6. Эксплуатация

```
docker compose --profile prod logs -f app        # смотреть логи приложения
docker compose --profile prod restart app        # перезапустить приложение
docker compose --profile prod down               # остановить всё
docker compose --profile prod up -d --build      # запустить снова
```

Обновление версии (после git push локально):

```
cd /opt/zabota && git pull
docker compose --profile prod up -d --build
```

Не редактировать файлы прямо на сервере — код должен совпадать с
репозиторием (после дедлайна версия фиксируется).

## 7. Чат-бот на сервере (позже, отдельный шаг)

Перед запуском остановить локальный экземпляр бота (long polling допускает
только один экземпляр — иначе двойные ответы):

```
docker compose --profile bot up -d --build
```
