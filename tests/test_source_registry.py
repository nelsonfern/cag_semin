"""Versionado del manifiesto, detección de cambios e invalidación de cachés."""

import json

import pytest

from app.ingestion.source_registry import (
    STATUS_ERROR, STATUS_OK, DocumentRecord, Manifest, load_sources, sha256_text,
)


def make_record(doc_id="doc-a", text="contenido", status=STATUS_OK, **overrides):
    base = dict(
        document_id=doc_id, title="Título", organism="Organismo", jurisdiction="provincial",
        source_url="https://ejemplo.gob.ar/a", local_path=None, processed_path=None,
        document_type="html", publication_date=None, last_updated_date=None,
        retrieved_at="2026-10-16T00:00:00+00:00",
        content_hash=sha256_text(text) if status == STATUS_OK else None,
        raw_hash=None, status=status, version=0,
    )
    base.update(overrides)
    return DocumentRecord(**base)


def test_new_unchanged_updated(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    assert m.upsert(make_record(text="v1")) == "new"
    assert m.get("doc-a").version == 1

    assert m.upsert(make_record(text="v1", retrieved_at="2026-10-17T00:00:00+00:00")) == "unchanged"
    assert m.get("doc-a").version == 1
    assert m.get("doc-a").retrieved_at == "2026-10-17T00:00:00+00:00"

    assert m.upsert(make_record(text="v2")) == "updated"
    assert m.get("doc-a").version == 2
    assert [h["change"] for h in m.history] == ["new", "updated"]


def test_failure_keeps_previous_good_version(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.upsert(make_record(text="bueno"))
    result = m.upsert(make_record(status=STATUS_ERROR, extraction_errors=["timeout"]))
    assert result == "failed_kept_previous"
    assert m.get("doc-a").status == STATUS_OK
    assert "timeout" in m.get("doc-a").last_error


def test_corpus_version_changes_only_with_content(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.upsert(make_record("a", "uno"))
    m.upsert(make_record("b", "dos"))
    v1 = m.corpus_version
    m.upsert(make_record("a", "uno", retrieved_at="2027-01-01T00:00:00+00:00"))
    assert m.corpus_version == v1, "una re-descarga sin cambios no debe cambiar la versión"
    m.upsert(make_record("a", "uno modificado"))
    assert m.corpus_version != v1


def test_dates_unknown_stay_empty_and_retrieved_at_is_separate(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.upsert(make_record())
    rec = m.get("doc-a")
    assert rec.publication_date is None and rec.last_updated_date is None
    assert rec.retrieved_at is not None


def test_stale_caches_are_marked_when_corpus_changes(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.upsert(make_record(text="v1"))
    m.register_cache("cache-1")
    assert m.mark_stale_caches() == []
    m.upsert(make_record(text="v2"))
    assert m.mark_stale_caches() == ["cache-1"]
    assert m.caches[0]["stale"] is True


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest(path)
    m.upsert(make_record(text="hola"))
    m.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["corpus_version"] == m.corpus_version
    reloaded = Manifest(path)
    assert reloaded.get("doc-a").content_hash == m.get("doc-a").content_hash
    assert reloaded.corpus_version == m.corpus_version


def test_sync_spec_updates_curated_fields_without_new_version(tmp_path):
    from app.ingestion.source_registry import SourceSpec
    m = Manifest(tmp_path / "manifest.json")
    m.upsert(make_record(text="x"))
    version = m.corpus_version
    spec = SourceSpec(document_id="doc-a", title="t", organism="Nuevo organismo", jurisdiction="nacional",
                      source_url="https://a", document_type="html", parser="pdf", notes="nota nueva")
    m.sync_spec(spec)
    rec = m.get("doc-a")
    assert (rec.organism, rec.jurisdiction, rec.notes, rec.version) == ("Nuevo organismo", "nacional", "nota nueva", 1)
    assert m.corpus_version == version


def test_remove_keeps_history_and_changes_corpus_version(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.upsert(make_record("a", "uno"))
    m.upsert(make_record("b", "dos"))
    version = m.corpus_version
    m.remove("b", "ya no se usa")
    assert m.get("b") is None
    assert m.history[-1]["change"] == "removed"
    assert m.corpus_version != version


def test_load_sources_rejects_duplicated_ids(tmp_path):
    entry = dict(document_id="x", title="t", organism="o", jurisdiction="provincial",
                 source_url="https://a", document_type="html", parser="pdf")
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicados"):
        load_sources(path)


def test_project_sources_file_is_valid():
    from app.ingestion.parser import PARSERS
    specs = load_sources()
    assert specs, "data/sources.json no puede estar vacío"
    for spec in specs:
        assert spec.parser in PARSERS
        assert spec.jurisdiction in {"provincial", "nacional"}
        assert spec.acquisition in {"auto", "manual"}
        assert spec.source_url.startswith("https://")
