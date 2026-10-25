"""Единый FastAPI-процесс: /api/v1 (мини-ап) + статика собранного мини-апа (web/dist)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from core.config import get_settings
from core.db.seed import seed_organizations
from core.db.session import SessionLocal, init_db
from server.api.v1.api import router as api_router
from server.security import SecurityHeadersMiddleware, security_headers

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        # справочник организаций (модельные данные кейса) — засеиваем один раз
        seed_organizations(db)
    finally:
        db.close()
    yield


settings = get_settings()

app = FastAPI(title="МедМаршрут API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in settings.allowed_origins.split(",") if o],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware, maps_enabled=bool(settings.yandex_maps_api_key))


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # ServerErrorMiddleware находится снаружи пользовательских middleware:
    # его ответ 500 иначе обошёл бы добавление заголовков.
    return JSONResponse(
        {"detail": "Internal Server Error"}, status_code=500,
        headers=security_headers(request.url.path, maps_enabled=bool(settings.yandex_maps_api_key)),
    )

app.include_router(api_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


if (WEB_DIST / "index.html").exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Статика мини-апа; API и небезопасные пути не попадают в SPA fallback."""
        candidate = (WEB_DIST / full_path).resolve()
        web_root = WEB_DIST.resolve()
        try:
            candidate.relative_to(web_root)
        except ValueError:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
else:

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index_stub():
        return (
            "<!doctype html><meta charset='utf-8'><title>МедМаршрут</title>"
            "<p>Мини-ап не собран. Выполните <code>npm run build</code> в папке <code>web/</code>"
            " или запустите dev-сервер на :5173 (run_web.bat).</p>"
        )
