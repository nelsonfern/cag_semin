"""API: estados del motor, chat, streaming SSE, cola, admin y resultados."""

import json
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.api.runtime import ERROR, LOADING, READY, Runtime  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.fakes import REPLIES, make_service  # noqa: E402

INFO = {"model_id": "fake", "cache_id": "abc", "prefix_tokens": 100}


def ready_runtime(delay=0.0, max_pending=4):
    service = make_service(delay=delay)
    runtime = Runtime(factory=lambda model=None, force_rebuild=False: (service, dict(INFO), "modelo"),
                      max_pending=max_pending)
    runtime.start(background=False)
    return runtime


@pytest.fixture()
def client():
    with TestClient(create_app(ready_runtime(), start_engine=False)) as c:
        yield c


def sse_events(response):
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


# --- Estado ---------------------------------------------------------------------------------

def test_health_ready(client):
    body = client.get("/health").json()
    assert body["status"] == READY and body["engine"]["cache_id"] == "abc" and body["pending"] == 0


def test_chat_is_503_while_loading():
    gate = threading.Event()

    def slow_factory(model=None, force_rebuild=False):
        gate.wait(5)
        return make_service(), INFO, None

    runtime = Runtime(factory=slow_factory)
    with TestClient(create_app(runtime)) as c:  # arranca la carga en segundo plano
        assert c.get("/health").json()["status"] == LOADING
        r = c.post("/chat", json={"question": "partida"})
        assert r.status_code == 503 and r.json()["detail"]["status"] == LOADING
        gate.set()
        for _ in range(50):
            if c.get("/health").json()["status"] == READY:
                break
            time.sleep(0.05)
        assert c.post("/chat", json={"question": "partida"}).status_code == 200


def test_failed_load_is_reported():
    def broken(model=None, force_rebuild=False):
        raise RuntimeError("no hay corpus")

    runtime = Runtime(factory=broken)
    runtime.start(background=False)
    with TestClient(create_app(runtime, start_engine=False)) as c:
        body = c.get("/health").json()
        assert body["status"] == ERROR and "no hay corpus" in body["error"]
        assert c.post("/chat", json={"question": "partida"}).status_code == 503


# --- Chat -----------------------------------------------------------------------------------

def test_chat_returns_answer_with_sources(client):
    body = client.post("/chat", json={"question": "partida"}).json()
    assert body["decision"] == "answered"
    assert body["documents"][0]["document_id"] == "rc-partidas"


def test_chat_unsupported_hides_the_text(client):
    body = client.post("/chat", json={"question": "inventa"}).json()
    assert body["decision"] == "unsupported" and "No encontré" in body["text"]


@pytest.mark.parametrize("payload, status", [
    ({"question": ""}, 422),
    ({"question": "x" * 1001}, 422),
    ({"question": "partida", "max_new_tokens": 5000}, 422),
    ({}, 422),
    ({"question": "contexto"}, 400),
])
def test_chat_validation(client, payload, status):
    assert client.post("/chat", json=payload).status_code == status


def test_slot_is_released_after_errors(client):
    client.post("/chat", json={"question": "contexto"})
    assert client.get("/health").json()["pending"] == 0


def test_queue_full_returns_429():
    runtime = ready_runtime(delay=0.01, max_pending=1)
    with TestClient(create_app(runtime, start_engine=False)) as c:
        runtime.acquire_slot()  # alguien ya ocupa el único lugar
        r = c.post("/chat", json={"question": "partida"})
        assert r.status_code == 429 and "ocupada" in r.json()["detail"]["message"]
        runtime.release_slot()
        assert c.post("/chat", json={"question": "partida"}).status_code == 200


# --- Streaming ------------------------------------------------------------------------------

def test_stream_sends_tokens_then_final(client):
    r = client.post("/chat/stream", json={"question": "¿Cuándo entregan el DNI exprés?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r)
    assert events[0] == ("queued", {"ahead": 0})
    streamed = "".join(d["text"] for e, d in events if e == "token")
    assert streamed == REPLIES["¿Cuándo entregan el DNI exprés?"]
    kind, final = events[-1]
    assert kind == "final" and final["decision"] == "answered"
    assert final["documents"][0]["jurisdiction"] == "nacional"


def test_stream_reports_errors_as_events(client):
    events = sse_events(client.post("/chat/stream", json={"question": "explota"}))
    assert events[-1][0] == "error" and events[-1][1]["status"] == 500
    events = sse_events(client.post("/chat/stream", json={"question": "contexto"}))
    assert events[-1] == ("error", {"status": 400, "message": "no entra en el contexto"})
    assert client.get("/health").json()["pending"] == 0


def test_stream_rejects_before_streaming_when_not_ready():
    runtime = Runtime(factory=lambda model=None, force_rebuild=False: (_ for _ in ()).throw(RuntimeError("x")))
    runtime.start(background=False)
    with TestClient(create_app(runtime, start_engine=False)) as c:
        assert c.post("/chat/stream", json={"question": "partida"}).status_code == 503


def test_concurrent_requests_report_queue_position_and_engine_is_used_one_at_a_time():
    runtime = ready_runtime(delay=0.002)
    engine = runtime.service.engine
    lock = threading.Lock()  # el motor real serializa con su propio lock; el falso lo simula aquí
    original = engine.answer

    def serialized(*args, **kwargs):
        with lock:
            return original(*args, **kwargs)

    engine.answer = serialized
    results = []
    with TestClient(create_app(runtime, start_engine=False)) as c:
        def worker():
            results.append(sse_events(c.post("/chat/stream", json={"question": "partida"})))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.get("/health").json()["pending"] == 0
    assert sorted(r[0][1]["ahead"] for r in results) == [0, 1, 2]
    assert all(r[-1][0] == "final" for r in results)
    assert engine.max_concurrent == 1


# --- Fuentes y resultados -------------------------------------------------------------------

def test_sources_lists_real_corpus(client):
    body = client.get("/sources").json()
    ids = {d["document_id"] for d in body["documents"]}
    assert "rc-solicitud-partidas" in ids and "nac-requisitos-dni-pasaporte" in ids
    assert body["corpus_is_current"] is True
    assert body["latest_published_update"] == "2025-10-20"
    law = next(d for d in body["documents"] if d["document_id"] == "ley-10702-impositiva-2024")
    assert law["is_excerpt"] is True


def test_evaluation_results(client):
    names = [r["name"] for r in client.get("/evaluation/results").json()["results"]]
    assert "phase3_kv_demo_20261017_015231.json" in names
    assert client.get("/evaluation/results/phase3_kv_demo_20261017_015231.json").json()["phase"] == 3
    assert client.get("/evaluation/results/..%2Fmanifest.json").status_code == 404
    assert client.get("/evaluation/results/no-existe.json").status_code == 404


# --- Administración -------------------------------------------------------------------------

def test_admin_disabled_without_token(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.post("/admin/rebuild-cache").status_code == 503


def test_admin_requires_the_right_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secreto")
    assert client.post("/admin/rebuild-cache").status_code == 401
    assert client.post("/admin/rebuild-cache", headers={"Authorization": "Bearer otro"}).status_code == 401
    assert client.get("/admin/jobs").status_code == 401


def test_admin_rebuild_runs_in_background_one_at_a_time(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secreto")
    gate = threading.Event()
    calls = []

    def factory(model=None, force_rebuild=False):
        calls.append((model, force_rebuild))
        if force_rebuild:
            gate.wait(5)
        return make_service(), {**INFO, "cache_source": "built" if force_rebuild else "disk"}, "modelo"

    runtime = Runtime(factory=factory)
    runtime.start(background=False)
    auth = {"Authorization": "Bearer secreto"}
    with TestClient(create_app(runtime, start_engine=False)) as c:
        r = c.post("/admin/rebuild-cache", headers=auth)
        assert r.status_code == 202 and r.json()["status"] == "running"
        assert c.post("/admin/rebuild-cache", headers=auth).status_code == 409  # ya hay una en curso
        assert c.get("/health").json()["status"] == LOADING
        gate.set()
        for _ in range(50):
            job = c.get("/admin/jobs", headers=auth).json()["jobs"][0]
            if job["status"] != "running":
                break
            time.sleep(0.05)
        assert job["status"] == "done" and job["result"]["cache_source"] == "built"
        assert c.get("/health").json()["status"] == READY
    assert calls[-1] == ("modelo", True)  # reutiliza el modelo cargado y fuerza la reconstrucción
