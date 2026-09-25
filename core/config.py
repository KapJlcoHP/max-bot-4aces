"""Общие настройки проекта — единственная точка чтения .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str = ""

    database_url: str = "sqlite:///./database/app.db"

    # Публичный https-адрес мини-апа (заполняется после деплоя на VPS).
    # Используется ботом в подсказках, пока кнопка open_app ссылается
    # на мини-ап, привязанный к боту в настройках business.max.ru.
    miniapp_public_url: str = ""

    # ТОЛЬКО для локальной разработки в обычном браузере (вне MAX):
    # принимать запросы без подписанного initData и работать под демо-пользователем.
    dev_bypass_auth: bool = False

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
