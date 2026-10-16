"""Pipeline de ingesta: descarga -> extracción -> registro en el manifiesto.

Uso:
    python -m app.ingestion.ingest run                    # ingesta de fuentes automáticas
    python -m app.ingestion.ingest run --only rc-pasaporte
    python -m app.ingestion.ingest import-manual --id nac-portal-tramitar --file pagina.html
    python -m app.ingestion.ingest status

Por cada documento se guardan:
- el original en ``data/raw/<document_id>/v<versión>.<ext>``
- el texto extraído en ``data/processed/<document_id>/v<versión>.txt``
- sus metadatos y su historial de versiones en ``data/manifest.json``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from app.config import MANIFEST_FILE, PROCESSED_DIR, RAW_DIR, ROOT_DIR, SOURCES_FILE
from app.ingestion.downloader import PoliteDownloader, RobotsDisallowed
from app.ingestion.parser import ExtractionError, ParsedDocument, get_parser
from app.ingestion.source_registry import (
    STATUS_BLOCKED, STATUS_ERROR, STATUS_MANUAL, STATUS_OK,
    DocumentRecord, Manifest, SourceSpec, load_sources, sha256_bytes, sha256_text, utc_now_iso,
)

_EXTENSIONS = {"html": "html", "html_js_embedded": "html", "pdf": "pdf"}


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT_DIR).as_posix()


def _base_record(spec: SourceSpec, status: str, retrieved_at: str | None, errors: list[str]) -> DocumentRecord:
    return DocumentRecord(
        document_id=spec.document_id, title=spec.title, organism=spec.organism,
        jurisdiction=spec.jurisdiction, source_url=spec.source_url, local_path=None,
        processed_path=None, document_type=spec.document_type, publication_date=None,
        last_updated_date=None, retrieved_at=retrieved_at, content_hash=None, raw_hash=None,
        status=status, version=0, notes=spec.notes, extraction_errors=errors,
        acquisition=spec.acquisition,
    )


def register_content(
    manifest: Manifest, spec: SourceSpec, content: bytes, encoding: str | None,
    retrieved_at: str, extra_note: str = "",
) -> tuple[str, DocumentRecord]:
    """Extrae el texto de ``content``, lo guarda versionado y lo registra en el manifiesto."""
    parser = get_parser(spec.parser)
    try:
        parsed: ParsedDocument = parser(content, encoding, spec.source_url)
    except ExtractionError as exc:
        record = _base_record(spec, STATUS_ERROR, retrieved_at, [str(exc)])
        return manifest.upsert(record), record

    record = _base_record(spec, STATUS_OK, retrieved_at, parsed.errors)
    record.title = parsed.title or spec.title
    record.last_updated_date = parsed.last_updated_date
    record.publication_date = parsed.publication_date
    record.content_hash = sha256_text(parsed.text)
    record.raw_hash = sha256_bytes(content)
    record.char_count = len(parsed.text)
    if extra_note:
        record.notes = f"{record.notes} | {extra_note}" if record.notes else extra_note

    change = manifest.upsert(record)
    current = manifest.get(spec.document_id)
    if change in ("new", "updated"):
        # Solo se escriben archivos cuando hay una versión nueva: los anteriores se conservan.
        raw_path = RAW_DIR / spec.document_id / f"v{current.version}.{_EXTENSIONS.get(spec.document_type, 'bin')}"
        txt_path = PROCESSED_DIR / spec.document_id / f"v{current.version}.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(content)
        txt_path.write_text(parsed.text + "\n", encoding="utf-8")
        current.local_path = _rel(raw_path)
        current.processed_path = _rel(txt_path)
    return change, current


def ingest_source(manifest: Manifest, spec: SourceSpec, downloader: PoliteDownloader) -> tuple[str, DocumentRecord]:
    if spec.acquisition == "manual":
        existing = manifest.get(spec.document_id)
        if existing and existing.status == STATUS_OK:
            return "unchanged", existing  # ya importado a mano; no se vuelve a descargar
        record = _base_record(spec, STATUS_MANUAL, None, [])
        return manifest.upsert(record), record

    retrieved_at = utc_now_iso()
    try:
        result = downloader.fetch(spec.source_url)
    except RobotsDisallowed as exc:
        record = _base_record(spec, STATUS_BLOCKED, retrieved_at, [str(exc)])
        return manifest.upsert(record), record
    except requests.RequestException as exc:
        record = _base_record(spec, STATUS_ERROR, retrieved_at, [f"Descarga fallida: {exc}"])
        return manifest.upsert(record), record

    note = f"Redirigido a {result.final_url}" if result.final_url != spec.source_url else ""
    return register_content(manifest, spec, result.content, result.encoding, retrieved_at, note)


def run(only: list[str] | None = None, sources_file: Path = SOURCES_FILE, manifest_file: Path = MANIFEST_FILE) -> Manifest:
    specs = load_sources(sources_file)
    if only:
        unknown = set(only) - {s.document_id for s in specs}
        if unknown:
            raise SystemExit(f"document_id desconocidos: {sorted(unknown)}")
        specs = [s for s in specs if s.document_id in only]

    manifest = Manifest(manifest_file)
    downloader = PoliteDownloader()
    for spec in specs:
        change, record = ingest_source(manifest, spec, downloader)
        detail = f"v{record.version} {record.char_count} caracteres" if record.status == STATUS_OK else "; ".join(record.extraction_errors)
        print(f"[{change:>20}] {spec.document_id}: {detail}")

    stale = manifest.mark_stale_caches()
    manifest.save()
    print(f"\ncorpus_version={manifest.corpus_version} documentos_ok={len(manifest.ok_documents())}")
    if stale:
        print(f"Cachés marcadas como desactualizadas: {stale}")
    return manifest


def import_manual(document_id: str, file: Path, retrieved_at: str | None = None) -> None:
    """Importa un archivo obtenido manualmente para una fuente registrada en sources.json."""
    specs = {s.document_id: s for s in load_sources()}
    if document_id not in specs:
        raise SystemExit(f"'{document_id}' no está en {SOURCES_FILE}; registralo primero.")
    if not file.exists():
        raise SystemExit(f"No existe el archivo {file}")
    manifest = Manifest()
    note = f"Importado manualmente desde '{file.name}' el {utc_now_iso()}"
    change, record = register_content(
        manifest, specs[document_id], file.read_bytes(), None, retrieved_at or utc_now_iso(), note
    )
    manifest.mark_stale_caches()
    manifest.save()
    print(f"[{change}] {document_id}: estado={record.status} versión={record.version}")


def status() -> None:
    manifest = Manifest()
    print(f"corpus_version={manifest.corpus_version} generado={manifest.generated_at}")
    for record in manifest.documents.values():
        print(f"- {record.document_id:<30} {record.status:<18} v{record.version} "
              f"actualizado_org={record.last_updated_date or '-'} obtenido={record.retrieved_at or '-'}")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Ingesta de fuentes oficiales de TramitaIA")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="Descarga y registra las fuentes automáticas")
    p_run.add_argument("--only", nargs="*", help="Limitar a estos document_id")
    p_imp = sub.add_parser("import-manual", help="Importa un archivo obtenido a mano")
    p_imp.add_argument("--id", required=True, dest="document_id")
    p_imp.add_argument("--file", required=True, type=Path)
    p_imp.add_argument("--retrieved-at", help="Fecha ISO en que se obtuvo el archivo")
    sub.add_parser("status", help="Muestra el estado del manifiesto")
    args = parser.parse_args(argv)

    if args.command == "run":
        run(args.only)
    elif args.command == "import-manual":
        import_manual(args.document_id, args.file, args.retrieved_at)
    else:
        status()


if __name__ == "__main__":
    main()
