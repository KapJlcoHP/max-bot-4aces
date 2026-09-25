"""Единый FastAPI-процесс: /api/v1 (мини-ап) + статика собранного мини-апа (web/dist)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from core.config import get_settings
from core.db.seed import seed_organizations
from core.db.session import SessionLocal, init_db
from server.api.v1.api import router as api_router

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

app.include_router(api_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


if (WEB_DIST / "index.html").exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Статика собранного мини-апа; неизвестные пути отдаём index.html (SPA-роутинг)."""
        candidate = (WEB_DIST / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(WEB_DIST.resolve())):
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
