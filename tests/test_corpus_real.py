"""Criterio de aprobación de la Fase 1 sobre los documentos realmente descargados.

No accede a la red: valida data/manifest.json y los archivos versionados en data/raw y
data/processed. Si el manifiesto no existe, primero hay que correr la ingesta:
    python -m app.ingestion.ingest run
"""

import pytest

from app.config import MANIFEST_FILE, ROOT_DIR
from app.ingestion.source_registry import STATUS_OK, Manifest, sha256_bytes, sha256_text

pytestmark = pytest.mark.skipif(not MANIFEST_FILE.exists(), reason="Falta data/manifest.json (correr la ingesta)")

OFFICIAL_DOMAINS = (".gob.ar",)


@pytest.fixture(scope="module")
def ok_docs():
    return Manifest().ok_documents()


def test_at_least_five_official_documents(ok_docs):
    assert len(ok_docs) >= 5


def test_required_metadata_present(ok_docs):
    for doc in ok_docs:
        assert doc.source_url.startswith("https://")
        assert any(d in doc.source_url for d in OFFICIAL_DOMAINS), doc.source_url
        assert doc.organism and doc.title and doc.retrieved_at
        assert doc.jurisdiction in {"provincial", "nacional"}
        assert doc.version >= 1


def test_files_exist_and_hashes_match(ok_docs):
    for doc in ok_docs:
        raw = ROOT_DIR / doc.local_path
        txt = ROOT_DIR / doc.processed_path
        assert raw.exists() and txt.exists(), doc.document_id
        assert sha256_bytes(raw.read_bytes()) == doc.raw_hash, f"original alterado: {doc.document_id}"
        text = txt.read_text(encoding="utf-8").rstrip("\n")
        assert sha256_text(text) == doc.content_hash, f"texto alterado: {doc.document_id}"
        assert len(text) == doc.char_count


def test_extracted_text_is_substantive(ok_docs):
    for doc in ok_docs:
        assert doc.char_count >= 500, f"{doc.document_id} tiene muy poco texto ({doc.char_count})"


def test_organism_dates_are_valid_and_not_after_retrieval(ok_docs):
    from datetime import date
    for doc in ok_docs:
        for value in (doc.last_updated_date, doc.publication_date):
            if value:
                # Fecha del organismo: AAAA-MM-DD válida y nunca posterior a la descarga.
                assert date.fromisoformat(value) <= date.fromisoformat(doc.retrieved_at[:10])


# --- Fase 2: corpus construido ------------------------------------------------

def _latest_build():
    import json
    from app.ingestion.corpus_builder import CORPUS_DIR
    pointer = CORPUS_DIR / "latest.json"
    if not pointer.exists():
        pytest.skip("No hay corpus construido (python -m app.ingestion.corpus_builder build)")
    latest = json.loads(pointer.read_text(encoding="utf-8"))
    text = (CORPUS_DIR / latest["text"]).read_text(encoding="utf-8")
    report = json.loads((CORPUS_DIR / latest["report"]).read_text(encoding="utf-8"))
    return text, report


def test_corpus_build_matches_current_manifest_and_hashes():
    text, report = _latest_build()
    assert report["manifest_corpus_version"] == Manifest().corpus_version, "corpus desactualizado: reconstruir"
    assert sha256_text(text) == report["corpus_text_sha256"]
    assert report["totals"]["tokens"] <= report["max_context_tokens"]


def test_corpus_preserves_metadata_of_every_included_document():
    text, report = _latest_build()
    manifest = Manifest()
    for doc in report["documents"]:
        record = manifest.get(doc["document_id"])
        assert doc["content_hash"] == record.content_hash
        if doc["included"]:
            assert f"<<<DOCUMENTO id={doc['document_id']}>>>" in text
            assert f"Fuente oficial: {record.source_url}" in text
        else:
            assert doc["exclusion_reason"], "toda exclusión debe estar justificada"
            assert f"id={doc['document_id']}>>>" not in text


def test_corpus_token_count_matches_real_tokenizer():
    text, report = _latest_build()
    from app.ingestion.corpus_builder import HFTokenizer
    try:
        tok = HFTokenizer(report["tokenizer"]["id"])
    except Exception as exc:  # sin red y sin caché local
        pytest.skip(f"No se pudo cargar el tokenizer: {exc}")
    assert tok.fingerprint == report["tokenizer"]["fingerprint"]
    assert tok.count(text) == report["totals"]["tokens"]


def test_non_downloadable_sources_are_recorded():
    manifest = Manifest()
    pending = [d for d in manifest.documents.values() if d.status != STATUS_OK]
    for doc in pending:
        assert doc.content_hash is None and doc.local_path is None  # nada inventado
