"""Registro de fuentes oficiales y manifiesto documental.

Dos piezas distintas:

- ``SourceSpec``: entrada curada de ``data/sources.json``. Dice qué documento oficial
  queremos, de qué organismo es y cómo obtenerlo (descarga automática o importación manual).
- ``DocumentRecord``: lo que efectivamente se obtuvo. Vive en ``data/manifest.json`` junto
  con su hash, versión y fechas, para saber con exactitud qué versión del corpus se usó al
  construir una caché KV.

Las fechas desconocidas se guardan como ``None``. ``retrieved_at`` es la fecha de descarga
y nunca reemplaza a ``publication_date`` ni a ``last_updated_date`` (fechas del organismo).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from app.config import MANIFEST_FILE, SOURCES_FILE

MANIFEST_SCHEMA_VERSION = 1

# Estados posibles de un documento en el manifiesto.
STATUS_OK = "ok"                      # obtenido y con texto extraído
STATUS_ERROR = "error"                # falló la descarga o la extracción
STATUS_BLOCKED = "blocked_by_robots"  # robots.txt no permite la descarga automática
STATUS_MANUAL = "manual_pending"      # requiere importación manual y todavía no se hizo


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


@dataclass(frozen=True)
class SourceSpec:
    document_id: str
    title: str
    organism: str
    jurisdiction: str          # "provincial" | "nacional"
    source_url: str
    document_type: str         # "html" | "html_js_embedded" | "pdf"
    parser: str                # nombre del parser en app.ingestion.parser.PARSERS
    acquisition: str = "auto"  # "auto" | "manual"
    notes: str = ""


@dataclass
class DocumentRecord:
    document_id: str
    title: str
    organism: str
    jurisdiction: str
    source_url: str
    local_path: str | None          # original descargado (relativo a la raíz del proyecto)
    processed_path: str | None      # texto extraído
    document_type: str
    publication_date: str | None    # fecha publicada por el organismo, si existe
    last_updated_date: str | None   # "última actualización" publicada por el organismo
    retrieved_at: str | None        # cuándo lo descargamos/importamos nosotros
    content_hash: str | None        # sha256 del texto extraído (detecta cambios reales)
    raw_hash: str | None            # sha256 de los bytes originales
    status: str
    version: int
    notes: str = ""
    char_count: int = 0
    extraction_errors: list[str] = field(default_factory=list)
    acquisition: str = "auto"
    last_error: str | None = None   # último intento fallido, sin pisar la versión buena
    ingest_note: str = ""           # cómo se obtuvo (redirección, importación manual...)

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentRecord":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def load_sources(path: Path = SOURCES_FILE) -> list[SourceSpec]:
    """Lee el registro curado de fuentes y valida que los ids sean únicos."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    specs = [SourceSpec(**entry) for entry in raw["sources"]]
    ids = [s.document_id for s in specs]
    duplicated = {i for i in ids if ids.count(i) > 1}
    if duplicated:
        raise ValueError(f"document_id duplicados en {path}: {sorted(duplicated)}")
    return specs


class Manifest:
    """Manifiesto documental versionado.

    ``corpus_version`` es un hash de los pares (document_id, content_hash) de los documentos
    en estado ``ok``. Si cambia cualquier documento, cambia la versión del corpus, y las
    cachés registradas con otra versión quedan marcadas como desactualizadas.
    """

    def __init__(self, path: Path = MANIFEST_FILE):
        self.path = path
        self.documents: dict[str, DocumentRecord] = {}
        self.history: list[dict] = []
        self.caches: list[dict] = []
        self.generated_at: str | None = None
        if path.exists():
            self._load()

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.documents = {
            doc_id: DocumentRecord.from_dict(rec) for doc_id, rec in data.get("documents", {}).items()
        }
        self.history = data.get("history", [])
        self.caches = data.get("caches", [])
        self.generated_at = data.get("generated_at")

    @property
    def corpus_version(self) -> str:
        pairs = sorted(
            (r.document_id, r.content_hash)
            for r in self.documents.values()
            if r.status == STATUS_OK and r.content_hash
        )
        return sha256_text(json.dumps(pairs))[:16]

    def ok_documents(self) -> list[DocumentRecord]:
        return [r for _, r in sorted(self.documents.items()) if r.status == STATUS_OK]

    def get(self, document_id: str) -> DocumentRecord | None:
        return self.documents.get(document_id)

    def upsert(self, record: DocumentRecord) -> str:
        """Registra un documento y devuelve qué pasó.

        Resultados: ``new``, ``updated``, ``unchanged``, ``failed_kept_previous`` o, para
        documentos sin contenido, su propio estado (``error``, ``blocked_by_robots``...).

        Si el contenido extraído no cambió, se conserva la versión y solo se actualiza
        ``retrieved_at``. Si cambió, se incrementa la versión y queda asentado en ``history``.
        """
        previous = self.documents.get(record.document_id)
        if record.status != STATUS_OK:
            # Un fallo no borra la última versión buena: se conserva y se anota el error.
            if previous and previous.status == STATUS_OK:
                previous.last_error = f"{utc_now_iso()} {record.status}: {'; '.join(record.extraction_errors)}"
                return "failed_kept_previous"
            record.version = previous.version if previous else 0
            self.documents[record.document_id] = record
            return record.status

        if previous and previous.status == STATUS_OK and previous.content_hash == record.content_hash:
            previous.retrieved_at = record.retrieved_at
            previous.last_error = None
            return "unchanged"

        change = "updated" if previous and previous.status == STATUS_OK else "new"
        record.version = (previous.version if previous else 0) + 1
        self.documents[record.document_id] = record
        self.history.append({
            "document_id": record.document_id,
            "version": record.version,
            "content_hash": record.content_hash,
            "retrieved_at": record.retrieved_at,
            "last_updated_date": record.last_updated_date,
            "change": change,
        })
        return change

    def sync_spec(self, spec: "SourceSpec") -> None:
        """Copia al manifiesto los datos curados de sources.json (organismo, notas...).

        Son datos nuestros, no del documento: cambiarlos no crea una versión nueva.
        """
        record = self.documents.get(spec.document_id)
        if record is None:
            return
        record.organism = spec.organism
        record.jurisdiction = spec.jurisdiction
        record.notes = spec.notes
        record.acquisition = spec.acquisition

    def remove(self, document_id: str, reason: str) -> None:
        """Quita un documento que ya no está en el registro, dejando constancia en el historial."""
        record = self.documents.pop(document_id)
        self.history.append({
            "document_id": document_id,
            "version": record.version,
            "content_hash": record.content_hash,
            "retrieved_at": utc_now_iso(),
            "last_updated_date": record.last_updated_date,
            "change": "removed",
            "reason": reason,
        })

    def register_cache(self, cache_id: str, details: dict | None = None) -> dict:
        """Asocia una caché KV con la versión actual del corpus (se usa desde la Fase 3)."""
        entry = {
            "cache_id": cache_id,
            "corpus_version": self.corpus_version,
            "created_at": utc_now_iso(),
            "stale": False,
            **(details or {}),
        }
        self.caches.append(entry)
        return entry

    def mark_stale_caches(self) -> list[str]:
        """Marca como desactualizada toda caché construida con otra versión del corpus."""
        current = self.corpus_version
        marked = []
        for cache in self.caches:
            if not cache.get("stale") and cache.get("corpus_version") != current:
                cache["stale"] = True
                cache["stale_since"] = utc_now_iso()
                marked.append(cache["cache_id"])
        return marked

    def to_dict(self) -> dict:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "corpus_version": self.corpus_version,
            "documents": {k: asdict(v) for k, v in sorted(self.documents.items())},
            "history": self.history,
            "caches": self.caches,
        }

    def save(self) -> None:
        self.generated_at = utc_now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

