"""HTTP-заголовки для API, SPA и статики, с учётом MAX и Яндекс.Карт."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DOCUMENTATION_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc"}
MAX_FRAMES = ("https://max.ru", "https://web.max.ru")
MAP_SCRIPTS = ("https://api-maps.yandex.ru", "https://*.api-maps.yandex.ru", "https://yastatic.net")
MAP_CONNECTIONS = ("https://api-maps.yandex.ru", "https://*.api-maps.yandex.ru", "https://*.maps.yandex.net")


def content_security_policy(*, maps_enabled: bool, documentation: bool = False) -> str:
    scripts = ["'self'", "https://st.max.ru"]
    styles = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
    connections = ["'self'"]
    workers = ["'self'", "blob:"]
    if maps_enabled:
        # Требования JS API v3: unsafe-eval используется векторным движком.
        # https://yandex.ru/maps-api/docs/js-api/common/connection/csp.html
        scripts.extend((*MAP_SCRIPTS, "'unsafe-eval'"))
        styles.extend(MAP_SCRIPTS)
        connections.extend(MAP_CONNECTIONS)
        workers.extend(("data:", *MAP_SCRIPTS))
    if documentation:
        # Стандартные Swagger/ReDoc FastAPI загружаются с jsDelivr;
        # Swagger и OAuth redirect содержат встроенный код инициализации.
        scripts.extend(("https://cdn.jsdelivr.net", "'unsafe-inline'"))
        styles.append("https://cdn.jsdelivr.net")
    directives = {
        "default-src": ["'self'"],
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
        "script-src": scripts,
        # React и MAX UI используют style-атрибуты; карты добавляют стили.
        "style-src": styles,
        "font-src": ["'self'", "https://fonts.gstatic.com", "data:"],
        # URL аватара приходит в подписанном профиле MAX, хост не фиксирован.
        "img-src": ["'self'", "data:", "blob:", "https:"],
        "connect-src": connections,
        "worker-src": workers,
        "frame-src": ["'self'", *MAX_FRAMES],
        "frame-ancestors": ["'self'", *MAX_FRAMES],
        "form-action": ["'self'"],
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


def security_headers(path: str, *, maps_enabled: bool) -> dict[str, str]:
    return {
        "X-Content-Type-Options": "nosniff",
        # Современные браузеры используют более точный frame-ancestors выше.
        # SAMEORIGIN остаётся защитой для клиентов без поддержки CSP.
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": content_security_policy(
            maps_enabled=maps_enabled, documentation=path in DOCUMENTATION_PATHS,
        ),
    }


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, maps_enabled: bool = False):
        self.app = app
        self.maps_enabled = maps_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = security_headers(scope.get("path", ""), maps_enabled=self.maps_enabled)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
