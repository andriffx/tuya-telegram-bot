"""FastAPI application untuk web dashboard."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Docs Swagger hanya aktif jika explicitly di-enable (hindari expose struktur API)
API_DOCS = os.getenv("API_DOCS", "false").lower() in ("1", "true", "yes")

app = FastAPI(
    title="Tuya Smart Home API",
    description="REST API lokal untuk dashboard & bot Telegram",
    version="1.0.0",
    docs_url="/docs" if API_DOCS else None,
    redoc_url="/redoc" if API_DOCS else None,
    openapi_url="/openapi.json" if API_DOCS else None,
)

app.include_router(router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Dashboard tidak ditemukan. API tersedia di /api/health"}
