# Этап 1: сборка мини-апа (Vite + React + TypeScript)
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Этап 2: рантайм — FastAPI раздаёт /api/v1 и собранную статику мини-апа
FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ core/
COPY server/ server/
COPY bot/ bot/
COPY content/ content/
COPY run_bot.py run_bot.py
COPY --from=web /web/dist web/dist
EXPOSE 8000
CMD ["sh", "-c", "mkdir -p database && uvicorn server.main:app --host 0.0.0.0 --port 8000"]
