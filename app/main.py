"""Aplicación FastAPI de TramitaIA.

    uvicorn app.main:app --port 8000

Al arrancar, el motor CAG (modelo + caché KV) se prepara en segundo plano; ``/health`` informa
cuándo está listo. La interfaz web (``frontend/web``: HTML, CSS y Alpine.js, sin compilación) se
sirve desde la misma app en ``/``: es solo un cliente de la API.
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env, incluido HF_HOME, antes de importar transformers)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.runtime import Runtime
from app.config import ROOT_DIR

WEB_DIR = ROOT_DIR / "frontend" / "web"


def create_app(runtime: Runtime | None = None, start_engine: bool = True) -> FastAPI:
    """Crea la app. Los tests pasan un ``Runtime`` con un motor falso."""
    runtime = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_engine:
            runtime.start(background=True)
        yield

    app = FastAPI(
        title="TramitaIA",
        description="Asistente de trámites de La Rioja con Cache-Augmented Generation. No es asesoría legal.",
        version="0.5.0",
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Interfaz web de TramitaIA."""
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
