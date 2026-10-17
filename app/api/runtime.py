"""Estado del servidor: motor CAG cargado en segundo plano, cola de consultas y tareas de admin.

Cargar el modelo y la caché lleva cerca de un minuto (o varios si hay que construir la caché),
así que el servidor arranca enseguida y el motor se prepara en un hilo aparte. Mientras tanto,
``/health`` informa ``loading`` y ``/chat`` responde 503.

La caché KV es una sola y el motor atiende una consulta por vez. ``Runtime`` cuenta las
consultas en curso para informar la posición en la cola y rechazar (429) cuando hay demasiadas.
"""

from __future__ import annotations

import gc
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

LOADING, READY, ERROR = "loading", "ready", "error"
MAX_PENDING = 4  # consultas en curso + en espera antes de responder 429


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QueueFullError(RuntimeError):
    """Hay demasiadas consultas esperando el motor."""


class NotReadyError(RuntimeError):
    """El motor todavía no está listo (o falló al cargar)."""


@dataclass
class Job:
    """Tarea de administración en segundo plano (ingesta o reconstrucción de la caché)."""

    job_id: str
    kind: str
    status: str = "running"         # running | done | error
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    result: dict | None = None
    error: str | None = None


def default_factory(model=None, force_rebuild: bool = False) -> tuple[object, dict, object]:
    """Crea el motor configurado (``ENGINE`` en el .env), prepara la caché y arma el servicio.

    ``model`` reutiliza un modelo de PyTorch ya cargado (motor transformers). Devuelve
    ``(servicio, info, modelo_reutilizable)``. Si no hay caché válida en disco (o si
    ``force_rebuild``), la construye y la guarda.
    """
    from app.cag.factory import create_engine
    from app.ingestion.corpus_builder import load_latest
    from app.services.answer_service import AnswerService
    from app.services.citations import CitationIndex

    engine, info, reusable = create_engine(transformers_model=model)
    prepared = engine.prepare(force_rebuild=force_rebuild)
    if hasattr(engine, "warmup"):
        info["warmup_seconds"] = round(engine.warmup(), 2)
    corpus_text, report = load_latest()
    service = AnswerService(engine, CitationIndex.from_corpus(corpus_text, report))
    info.update({
        "cache_id": engine.identity.cache_id, "cache_source": prepared["source"],
        "cache_seconds": round(prepared["seconds"], 2), "cache_rejected": prepared["rejected"],
        "prefix_tokens": engine.prefix_len, "context_limit": engine.context_limit,
        "max_new_tokens": engine.max_new_tokens,
        "corpus_build_id": report["build_id"], "corpus_version": engine.identity.corpus_version,
    })
    return service, info, reusable


class Runtime:
    """Contiene el servicio de respuestas y su estado. Una instancia por servidor."""

    def __init__(self, factory: Callable = default_factory, max_pending: int = MAX_PENDING):
        self.factory = factory
        self.max_pending = max_pending
        self.status = LOADING
        self.error: str | None = None
        self.service = None
        self.info: dict = {}
        self.model = None
        self.started_at = _now()
        self.ready_at: str | None = None
        self.jobs: dict[str, Job] = {}
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._admin_lock = threading.Lock()

    # -- Carga ----------------------------------------------------------------------------------

    def start(self, background: bool = True) -> None:
        """Prepara el motor; por defecto en un hilo aparte para no bloquear el arranque."""
        if background:
            threading.Thread(target=self._load, name="engine-loader", daemon=True).start()
        else:
            self._load()

    def _load(self) -> None:
        try:
            self.service, self.info, self.model = self.factory()
            self.status, self.ready_at = READY, _now()
        except Exception as exc:  # se informa por /health en lugar de tirar el servidor
            self.status, self.error = ERROR, f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

    # -- Consultas -----------------------------------------------------------------------------

    def acquire_slot(self) -> int:
        """Reserva un lugar para una consulta y devuelve cuántas hay delante (0 = se atiende ya)."""
        if self.status != READY:
            raise NotReadyError(self.error or "El motor se está cargando")
        with self._pending_lock:
            if self._pending >= self.max_pending:
                raise QueueFullError(f"Hay {self._pending} consultas en curso o en espera")
            ahead = self._pending
            self._pending += 1
            return ahead

    def release_slot(self) -> None:
        with self._pending_lock:
            self._pending = max(0, self._pending - 1)

    @property
    def pending(self) -> int:
        return self._pending

    # -- Administración ------------------------------------------------------------------------

    def run_job(self, kind: str, work: Callable[[], dict]) -> Job:
        """Lanza una tarea de admin en segundo plano; solo una a la vez (si no, ``RuntimeError``)."""
        if not self._admin_lock.acquire(blocking=False):
            raise RuntimeError("Ya hay una tarea de administración en curso")
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind)
        self.jobs[job.job_id] = job

        def target():
            try:
                job.result = work()
                job.status = "done"
            except Exception as exc:
                job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            finally:
                job.finished_at = _now()
                self._admin_lock.release()

        threading.Thread(target=target, name=f"admin-{kind}", daemon=True).start()
        return job

    def rebuild_cache(self) -> dict:
        """Vuelve a leer corpus y prompt, reconstruye la caché y reemplaza el servicio.

        Reutiliza el modelo ya cargado. Mientras se reconstruye, las consultas nuevas reciben
        503 (``loading``) y la que esté en curso termina con el servicio anterior.
        """
        previous = self.status
        self.status = LOADING
        try:
            if self.model is None and self.service is not None:
                # Motor llama.cpp: no hay un modelo reutilizable y el motor nuevo carga el suyo.
                # Se libera el anterior antes, para no tener dos modelos en memoria a la vez.
                self.service = None
                gc.collect()
            service, info, model = self.factory(self.model, force_rebuild=True)
            self.service, self.info, self.model = service, info, model
            self.status, self.error, self.ready_at = READY, None, _now()
            return info
        except Exception:
            self.status = previous if self.service is not None else ERROR
            raise
