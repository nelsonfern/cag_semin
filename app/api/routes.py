"""Rutas HTTP de TramitaIA.

Públicas: ``/health``, ``/sources``, ``/chat``, ``/chat/stream`` y ``/evaluation/results``.
Administrativas (requieren ``ADMIN_TOKEN``): ``/admin/ingest``, ``/admin/rebuild-cache`` y
``/admin/jobs``. Si ``ADMIN_TOKEN`` no está definido, las rutas de admin quedan deshabilitadas.
"""

from __future__ import annotations

import json
import os
import queue
import re
import secrets
import threading
from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.runtime import NotReadyError, QueueFullError, Runtime
from app.api.schemas import ChatRequest
from app.cag.engine import ContextLimitError, QuestionError
from app.config import DATA_DIR

router = APIRouter()
RESULTS_DIR = DATA_DIR / "results"
_RESULT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _slot_or_http_error(runtime: Runtime) -> int:
    """Reserva lugar en la cola o traduce el motivo del rechazo a un código HTTP."""
    try:
        return runtime.acquire_slot()
    except NotReadyError as exc:
        raise HTTPException(503, detail={"status": runtime.status, "message": str(exc)}) from exc
    except QueueFullError as exc:
        raise HTTPException(429, detail={"message": f"TramitaIA está ocupada: {exc}. Probá en unos minutos."}) from exc


# -- Públicas ------------------------------------------------------------------------------

@router.get("/health")
def health(runtime: Runtime = Depends(get_runtime)) -> dict:
    """Estado del motor (``loading``, ``ready`` o ``error``), modelo, caché y cola."""
    return {"status": runtime.status, "error": runtime.error, "started_at": runtime.started_at,
            "ready_at": runtime.ready_at, "pending": runtime.pending, "engine": runtime.info}


@router.get("/sources")
def sources() -> dict:
    """Documentos del corpus en uso, con sus metadatos y la fecha de actualización conocida."""
    from app.ingestion.corpus_builder import load_latest
    from app.ingestion.source_registry import Manifest

    _, report = load_latest()
    docs = []
    for d in report["documents"]:
        statuses = {s["status"] for s in d["sections"]}
        docs.append({
            "document_id": d["document_id"], "title": d["title"], "organism": d["organism"],
            "jurisdiction": d["jurisdiction"], "source_url": d["source_url"],
            "last_updated_date": d.get("last_updated_date"), "retrieved_at": d.get("retrieved_at"),
            "version": d["version"], "included": d["included"],
            "is_excerpt": statuses != {"included"}, "tokens": d.get("tokens"),
        })
    published = [d["last_updated_date"] for d in docs if d["included"] and d["last_updated_date"]]
    retrieved = [d["retrieved_at"] for d in docs if d["included"] and d["retrieved_at"]]
    manifest_version = Manifest().corpus_version
    return {
        "corpus_build_id": report["build_id"],
        "corpus_version": report["manifest_corpus_version"],
        "corpus_is_current": report["manifest_corpus_version"] == manifest_version,
        "latest_published_update": max(published) if published else None,
        "oldest_published_update": min(published) if published else None,
        "retrieved_at": max(retrieved)[:10] if retrieved else None,
        "documents": docs,
    }


@router.post("/chat")
def chat(body: ChatRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    """Responde una pregunta y devuelve la respuesta completa (puede tardar un par de minutos)."""
    _slot_or_http_error(runtime)
    try:
        return runtime.service.answer(body.question, max_new_tokens=body.max_new_tokens).to_dict()
    except (QuestionError, ContextLimitError) as exc:
        raise HTTPException(400, detail={"message": str(exc)}) from exc
    finally:
        runtime.release_slot()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def chat_stream(body: ChatRequest, runtime: Runtime = Depends(get_runtime)):
    """Responde por Server-Sent Events.

    Eventos: ``queued`` (consultas delante), ``token`` (texto nuevo), ``replace`` (texto completo,
    si la decodificación parcial cambió), ``final`` (respuesta con decisión y fuentes) y
    ``error``. El texto que llega por ``token`` es un borrador: la decisión final (por ejemplo,
    no mostrarlo por falta de citas) llega en ``final``.
    """
    ahead = _slot_or_http_error(runtime)
    service = runtime.service
    tokenizer = service.engine.tokenizer
    events: queue.Queue = queue.Queue()
    done = object()

    def on_token(token_id: int) -> None:
        events.put(("token", token_id))

    def work() -> None:
        # La consulta corre en su propio hilo y libera su lugar al terminar, aunque el cliente
        # se haya desconectado: así la cola refleja lo que de verdad ocupa el motor.
        try:
            answer = service.answer(body.question, on_token=on_token, max_new_tokens=body.max_new_tokens)
            events.put(("final", answer.to_dict()))
        except (QuestionError, ContextLimitError) as exc:
            events.put(("error", {"status": 400, "message": str(exc)}))
        except Exception as exc:
            events.put(("error", {"status": 500, "message": f"{type(exc).__name__}: {exc}"}))
        finally:
            runtime.release_slot()
            events.put((done, None))

    threading.Thread(target=work, name="chat-stream", daemon=True).start()

    def stream():
        yield _sse("queued", {"ahead": ahead})
        ids, shown = [], ""
        while True:
            kind, payload = events.get()
            if kind is done:
                return
            if kind == "token":
                ids.append(payload)
                text = tokenizer.decode(ids, skip_special_tokens=True)
                if text.endswith("�"):
                    continue  # carácter partido entre tokens: esperar al siguiente
                if text.startswith(shown):
                    if len(text) > len(shown):
                        yield _sse("token", {"text": text[len(shown):]})
                else:
                    yield _sse("replace", {"text": text})
                shown = text
            else:
                yield _sse(kind, payload)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/evaluation/results")
def evaluation_results() -> dict:
    """Resultados de demos, evaluaciones y benchmarks guardados en ``data/results``."""
    files = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            phase = data.get("phase")
        except (json.JSONDecodeError, OSError):
            phase = None
        files.append({"name": path.name, "phase": phase, "bytes": path.stat().st_size})
    return {"results": files}


@router.get("/evaluation/results/{name}")
def evaluation_result(name: str) -> dict:
    """Contenido de un resultado. Solo nombres simples de ``data/results`` (sin rutas)."""
    if not _RESULT_NAME_RE.match(name) or not (RESULTS_DIR / name).is_file():
        raise HTTPException(404, detail={"message": "Resultado inexistente"})
    return json.loads((RESULTS_DIR / name).read_text(encoding="utf-8"))


# -- Administración ------------------------------------------------------------------------

def require_admin(authorization: str | None = Header(None)) -> None:
    """Exige ``Authorization: Bearer <ADMIN_TOKEN>``. Sin token configurado, admin queda apagado."""
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, detail={"message": "Las rutas de administración están deshabilitadas (ADMIN_TOKEN vacío)"})
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, detail={"message": "Token de administración inválido"})


def _start_job(runtime: Runtime, kind: str, work) -> JSONResponse:
    try:
        job = runtime.run_job(kind, work)
    except RuntimeError as exc:
        raise HTTPException(409, detail={"message": str(exc)}) from exc
    return JSONResponse(asdict(job), status_code=202)


@router.post("/admin/ingest", dependencies=[Depends(require_admin)])
def admin_ingest(runtime: Runtime = Depends(get_runtime)):
    """Descarga las fuentes automáticas (respetando robots.txt y pausas) y actualiza el manifiesto.

    No reconstruye el corpus: si cambió algún documento, la respuesta lo indica y hay que
    revisar y construir el corpus (``corpus_builder build``) antes de ``/admin/rebuild-cache``.
    """
    def work() -> dict:
        from app.ingestion import ingest
        from app.ingestion.corpus_builder import load_latest

        manifest = ingest.run()
        _, report = load_latest()
        stale = [c["cache_id"] for c in manifest.caches if c.get("stale")]
        return {"corpus_version": manifest.corpus_version,
                "corpus_needs_rebuild": manifest.corpus_version != report["manifest_corpus_version"],
                "stale_caches": stale}

    return _start_job(runtime, "ingest", work)


@router.post("/admin/rebuild-cache", dependencies=[Depends(require_admin)])
def admin_rebuild_cache(runtime: Runtime = Depends(get_runtime)):
    """Reconstruye la caché KV con el corpus y el prompt actuales (varios minutos en CPU)."""
    return _start_job(runtime, "rebuild-cache", runtime.rebuild_cache)


@router.get("/admin/jobs", dependencies=[Depends(require_admin)])
def admin_jobs(runtime: Runtime = Depends(get_runtime)) -> dict:
    """Tareas de administración lanzadas desde que arrancó el servidor."""
    return {"jobs": [asdict(j) for j in runtime.jobs.values()]}
