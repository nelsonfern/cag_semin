"""Construcción reproducible del corpus que se cargará en la caché KV (Fase A del CAG).

Pasos:
1. Toma del manifiesto los documentos en estado ``ok`` (texto ya extraído y versionado).
2. Divide cada documento en secciones con ID estable (``<document_id>#s<n>`` o
   ``<document_id>#art-<n>``), que luego sirven para las citas.
3. Aplica la selección de ``data/corpus_config.json`` (p. ej. solo algunos artículos de una
   ley) y limpia líneas de ruido declaradas (pies de página del PDF).
4. Controla duplicados: una sección cuyo texto normalizado ya apareció no se repite, pero queda
   registrada indicando de qué sección es copia (no se pierde la trazabilidad).
5. Ordena de forma determinista (grupo provincial -> nacional -> normativa, luego por ID) y
   antepone a cada documento una cabecera con sus metadatos.
6. Cuenta tokens con el tokenizer real del modelo y verifica el presupuesto de contexto.
   Si no alcanza, excluye documentos completos por prioridad y lo informa. Nunca trunca en
   silencio.

Salidas (en ``data/processed/corpus/``):
- ``<build_id>.txt``: el texto exacto que se procesará para construir la caché.
- ``<build_id>.json``: reporte con lo incluido, lo excluido, los duplicados y los tokens.
- ``latest.json``: puntero a la última construcción.

``build_id`` es el hash del texto del corpus, del tokenizer y de la configuración. La misma
entrada produce siempre los mismos bytes y el mismo ``build_id``.

Uso:
    python -m app.ingestion.corpus_builder build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from app.config import DATA_DIR, MANIFEST_FILE, PROCESSED_DIR, ROOT_DIR
from app.ingestion.source_registry import DocumentRecord, Manifest, utc_now_iso

CORPUS_CONFIG_FILE = DATA_DIR / "corpus_config.json"
CORPUS_DIR = PROCESSED_DIR / "corpus"
CORPUS_FORMAT_VERSION = 1

# Secciones con menos caracteres que esto no se deduplican: textos como "Sin cargo" o
# "DNI vigente" se repiten legítimamente en trámites distintos.
MIN_DEDUP_CHARS = 80


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class Tokenizer(Protocol):
    tokenizer_id: str
    fingerprint: str  # hash del vocabulario/reglas: si cambia, cambian los conteos

    def count(self, text: str) -> int: ...


class HFTokenizer:
    """Tokenizer de Hugging Face (solo los archivos del tokenizer, sin pesos del modelo)."""

    def __init__(self, tokenizer_id: str):
        from transformers import AutoTokenizer  # import diferido: es pesado

        self.tokenizer_id = tokenizer_id
        self._tok = AutoTokenizer.from_pretrained(tokenizer_id)
        backend = getattr(self._tok, "backend_tokenizer", None)
        serialized = backend.to_str() if backend is not None else json.dumps(self._tok.get_vocab(), sort_keys=True)
        self.fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def count(self, text: str) -> int:
        # Sin tokens especiales: es el conteo del texto del corpus. La plantilla de chat y el
        # prompt de sistema se suman en la Fase 3, cuando se arma la entrada del modelo.
        return len(self._tok.encode(text, add_special_tokens=False))


# ---------------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------------

@dataclass
class Section:
    section_id: str
    heading: str | None
    text: str                 # cuerpo de la sección tal como entra al corpus
    char_start: int           # posición en el texto procesado del documento (trazabilidad)
    char_end: int
    status: str = "included"  # included | duplicate | excluded_by_selection
    duplicate_of: str | None = None
    tokens: int = 0


def split_markdown(doc_id: str, text: str) -> list[Section]:
    """Divide en los títulos ``## ``. Lo anterior al primer título es la sección ``s0``."""
    sections: list[Section] = []
    starts = [m.start() for m in re.finditer(r"(?m)^## ", text)]
    bounds = [0] + starts + [len(text)]
    for i in range(len(bounds) - 1):
        start, end = bounds[i], bounds[i + 1]
        chunk = text[start:end].strip("\n")
        if not chunk:
            continue
        heading = None
        if chunk.startswith("## "):
            first, _, rest = chunk.partition("\n")
            heading, chunk = first[3:].strip(), rest.strip("\n")
        sections.append(Section(f"{doc_id}#s{len(sections)}", heading, chunk, start, end))
    return sections


_ARTICLE_RE = re.compile(r"(?m)^ART[IÍ]CULO\s*((?:\d\s?){1,3}?)\s*[º°]")


def _is_heading_line(line: str) -> bool:
    """Título en mayúsculas de un capítulo o repartición ("DIRECCIÓN GENERAL DEL ...")."""
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and len(line) <= 100 and all(c.isupper() for c in letters) and "$" not in line


def split_articles(doc_id: str, text: str) -> list[Section]:
    """Divide una norma por artículos (``#art-<n>``); el texto previo es ``#preambulo``.

    La extracción del PDF a veces separa dígitos ("ARTÍCULO 1 6º"), por eso el número se
    reconstruye quitando espacios. Los títulos de capítulo que quedan al final de un artículo
    se mueven al comienzo del siguiente, que es al que pertenecen.
    """
    matches = list(_ARTICLE_RE.finditer(text))
    if not matches:
        return [Section(f"{doc_id}#s0", None, text.strip(), 0, len(text))]
    raw: list[tuple[str, int, int]] = []
    if text[: matches[0].start()].strip():
        raw.append(("preambulo", 0, matches[0].start()))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        number = re.sub(r"\s", "", m.group(1))
        raw.append((f"art-{number}", m.start(), end))

    sections: list[Section] = []
    carry, carry_start = "", 0
    for i, (key, start, end) in enumerate(raw):
        lines = text[start:end].split("\n")
        cut = len(lines)
        if i + 1 < len(raw):  # el último artículo no tiene a quién pasarle títulos
            while cut > 0 and (not lines[cut - 1].strip() or _is_heading_line(lines[cut - 1].strip())):
                cut -= 1
        body = "\n".join(lines[:cut]).strip("\n")
        body_end = start + len("\n".join(lines[:cut]))
        content = f"{carry}\n{body}" if carry else body
        sections.append(Section(f"{doc_id}#{key}", None, content, carry_start if carry else start, body_end))
        carry = "\n".join(lines[cut:]).strip("\n")
        carry_start = body_end + 1
    return sections


SPLITTERS = {"markdown": split_markdown, "articles": split_articles}


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------

@dataclass
class DocumentPlan:
    record: DocumentRecord
    group: str
    priority: int
    sections: list[Section]
    selection_reason: str | None = None
    dropped_lines: int = 0
    block: str = ""
    tokens: int = 0
    included: bool = True
    exclusion_reason: str | None = None


@dataclass
class CorpusBuild:
    build_id: str
    text: str
    report: dict
    warnings: list[str] = field(default_factory=list)


def _dedup_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _render_block(plan: DocumentPlan) -> str:
    r = plan.record
    lines = [
        f"<<<DOCUMENTO id={r.document_id}>>>",
        f"Título: {r.title}",
        f"Organismo: {r.organism}",
        f"Jurisdicción: {r.jurisdiction}",
        f"Fuente oficial: {r.source_url}",
        f"Última actualización publicada por el organismo: {r.last_updated_date or 'no publicada'}",
        f"Fecha de obtención: {r.retrieved_at[:10] if r.retrieved_at else 'desconocida'}",
        f"Versión del documento: v{r.version}",
    ]
    if plan.selection_reason:
        kept = [s.section_id.split("#", 1)[1] for s in plan.sections if s.status != "excluded_by_selection"]
        lines.append(f"Extracto: solo se incluyen las secciones {', '.join(kept)}. {plan.selection_reason}")
    for s in plan.sections:
        if s.status == "excluded_by_selection":
            continue
        marker = f"[{s.section_id}]" + (f" {s.heading}" if s.heading else "")
        lines.append("")
        if s.status == "duplicate":
            lines.append(f"{marker} (contenido idéntico a [{s.duplicate_of}]; se omite para no repetirlo)")
        else:
            lines += [marker, s.text]
    lines += ["", f"<<<FIN DOCUMENTO id={r.document_id}>>>"]
    return "\n".join(lines)


def load_config(path: Path = CORPUS_CONFIG_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_corpus(manifest: Manifest, config: dict, tokenizer: Tokenizer) -> CorpusBuild:
    doc_cfgs: dict[str, dict] = config["documents"]
    group_order = {g: i for i, g in enumerate(config["group_order"])}
    budget = int(config["max_context_tokens"])
    warnings: list[str] = []
    excluded: list[dict] = []

    # 1. Documentos candidatos
    plans: list[DocumentPlan] = []
    for record in manifest.ok_documents():
        cfg = doc_cfgs.get(record.document_id)
        if cfg is None:
            excluded.append({"document_id": record.document_id, "reason": "No figura en corpus_config.json"})
            continue
        text = (ROOT_DIR / record.processed_path).read_text(encoding="utf-8").rstrip("\n")
        patterns = [re.compile(p) for p in cfg.get("drop_line_patterns", [])]
        dropped = 0
        if patterns:
            kept_lines = []
            for line in text.split("\n"):
                if any(p.search(line.strip()) for p in patterns):
                    dropped += 1
                else:
                    kept_lines.append(line)
            text = "\n".join(kept_lines)
        sections = SPLITTERS[cfg.get("splitter", "markdown")](record.document_id, text)
        # Selección por ID (artículos de una norma: "art-39") o por título de sección. El título
        # es más estable que "s7" cuando el organismo agrega o quita secciones en su página.
        include_ids = cfg.get("include_sections")
        include_headings = cfg.get("include_headings")
        selective = bool(include_ids or include_headings)
        if include_ids:
            found = {s.section_id.split("#", 1)[1] for s in sections}
            for missing in sorted(set(include_ids) - found):
                warnings.append(f"{record.document_id}: la sección '{missing}' de include_sections no existe")
        if include_headings:
            found_headings = {s.heading for s in sections}
            for missing in [h for h in include_headings if h not in found_headings]:
                warnings.append(f"{record.document_id}: no hay sección con el título '{missing}'")
        if selective:
            for s in sections:
                keep = (include_ids and s.section_id.split("#", 1)[1] in include_ids) or \
                       (include_headings and s.heading in include_headings)
                if not keep:
                    s.status = "excluded_by_selection"
        plans.append(DocumentPlan(
            record=record, group=cfg["group"], priority=int(cfg["priority"]), sections=sections,
            selection_reason=cfg.get("selection_reason") if selective else None, dropped_lines=dropped,
        ))
    for doc_id in sorted(set(doc_cfgs) - {p.record.document_id for p in plans}):
        rec = manifest.get(doc_id)
        state = rec.status if rec else "ausente del manifiesto"
        warnings.append(f"{doc_id}: configurado pero no disponible ({state})")

    # 2. Orden determinista
    plans.sort(key=lambda p: (group_order.get(p.group, len(group_order)), p.record.document_id))

    # 3. Duplicados (en orden: la primera aparición se conserva)
    seen: dict[str, str] = {}
    duplicates: list[dict] = []
    for plan in plans:
        for s in plan.sections:
            if s.status != "included" or len(s.text) < MIN_DEDUP_CHARS:
                continue
            key = _dedup_key(s.text)
            if key in seen:
                s.status, s.duplicate_of = "duplicate", seen[key]
                duplicates.append({"section_id": s.section_id, "duplicate_of": seen[key]})
            else:
                seen[key] = s.section_id

    # 4. Tokens y presupuesto
    for plan in plans:
        plan.block = _render_block(plan)
        plan.tokens = tokenizer.count(plan.block)
        for s in plan.sections:
            s.tokens = tokenizer.count(s.text) if s.status == "included" else 0

    def total_tokens() -> int:
        return tokenizer.count(_join([p for p in plans if p.included]))

    current = total_tokens()
    # Se excluye primero lo de menor prioridad (número mayor); a igual prioridad, el último en el orden.
    dropped: list[DocumentPlan] = []
    for plan in sorted(plans, key=lambda p: (-p.priority, -plans.index(p))):
        if current <= budget:
            break
        plan.included = False
        dropped.append(plan)
        current = total_tokens()
    # Segunda pasada: un documento excluido antes puede caber después de excluir otro más grande.
    for plan in sorted(dropped, key=lambda p: (p.priority, plans.index(p))):
        plan.included = True
        if total_tokens() > budget:
            plan.included = False
    for plan in plans:
        if not plan.included:
            plan.exclusion_reason = (
                f"Excede el presupuesto de {budget} tokens: se excluye el documento completo "
                f"(prioridad {plan.priority}, {plan.tokens} tokens) en lugar de truncarlo"
            )
            excluded.append({"document_id": plan.record.document_id, "reason": plan.exclusion_reason})
    current = total_tokens()
    if current > budget:
        warnings.append(f"Aun excluyendo documentos, el corpus ocupa {current} tokens (> {budget})")

    corpus_text = _join([p for p in plans if p.included])
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    text_hash = hashlib.sha256(corpus_text.encode("utf-8")).hexdigest()
    build_id = hashlib.sha256(
        f"{CORPUS_FORMAT_VERSION}|{text_hash}|{tokenizer.tokenizer_id}|{tokenizer.fingerprint}|{config_hash}".encode("utf-8")
    ).hexdigest()[:16]

    report = {
        "build_id": build_id,
        "format_version": CORPUS_FORMAT_VERSION,
        "manifest_corpus_version": manifest.corpus_version,
        "config_sha256": config_hash,
        "corpus_text_sha256": text_hash,
        "tokenizer": {"id": tokenizer.tokenizer_id, "fingerprint": tokenizer.fingerprint},
        "max_context_tokens": budget,
        "totals": {
            "documents_included": sum(p.included for p in plans),
            "documents_excluded": len(excluded),
            "sections_included": sum(s.status == "included" for p in plans if p.included for s in p.sections),
            "sections_duplicate": len(duplicates),
            "sections_excluded_by_selection": sum(s.status == "excluded_by_selection" for p in plans for s in p.sections),
            "chars": len(corpus_text),
            "tokens": current,
            "budget_remaining": budget - current,
        },
        "documents": [_plan_report(p) for p in plans],
        "excluded_documents": excluded,
        "duplicates": duplicates,
        "warnings": warnings,
    }
    return CorpusBuild(build_id=build_id, text=corpus_text, report=report, warnings=warnings)


def _join(plans: list[DocumentPlan]) -> str:
    return "\n\n".join(p.block for p in plans) + "\n"


def _plan_report(plan: DocumentPlan) -> dict:
    r = plan.record
    return {
        "document_id": r.document_id,
        "title": r.title,
        "organism": r.organism,
        "jurisdiction": r.jurisdiction,
        "source_url": r.source_url,
        "version": r.version,
        "content_hash": r.content_hash,
        "last_updated_date": r.last_updated_date,
        "retrieved_at": r.retrieved_at,
        "group": plan.group,
        "priority": plan.priority,
        "included": plan.included,
        "exclusion_reason": plan.exclusion_reason,
        "tokens": plan.tokens,
        "dropped_noise_lines": plan.dropped_lines,
        "sections": [
            {k: v for k, v in asdict(s).items() if k != "text"} | {"chars": len(s.text)}
            for s in plan.sections
        ],
    }


def write_build(build: CorpusBuild, out_dir: Path = CORPUS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = out_dir / f"{build.build_id}.txt"
    rep = out_dir / f"{build.build_id}.json"
    # newline="" evita que Windows convierta \n en \r\n: los bytes deben ser reproducibles.
    with open(txt, "w", encoding="utf-8", newline="") as fh:
        fh.write(build.text)
    with open(rep, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(build.report, ensure_ascii=False, indent=2) + "\n")
    with open(out_dir / "latest.json", "w", encoding="utf-8", newline="") as fh:
        # Rutas relativas a la carpeta del corpus.
        fh.write(json.dumps({"build_id": build.build_id, "built_at": utc_now_iso(),
                             "text": txt.name, "report": rep.name}, indent=2) + "\n")
    return txt, rep


def load_latest(out_dir: Path = CORPUS_DIR) -> tuple[str, dict]:
    """Texto y reporte del último build (``latest.json``). Lee los bytes tal cual se escribieron."""
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    with open(out_dir / latest["text"], encoding="utf-8", newline="") as fh:
        text = fh.read()
    report = json.loads((out_dir / latest["report"]).read_text(encoding="utf-8"))
    return text, report


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Construye el corpus CAG de TramitaIA")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Construye el corpus a partir del manifiesto")
    args = parser.parse_args(argv)

    if args.command == "build":
        config = load_config()
        build = build_corpus(Manifest(MANIFEST_FILE), config, HFTokenizer(config["tokenizer_id"]))
        txt, rep = write_build(build)
        t = build.report["totals"]
        print(f"build_id={build.build_id}  tokens={t['tokens']}/{build.report['max_context_tokens']}  "
              f"documentos={t['documents_included']}  secciones={t['sections_included']}  "
              f"duplicadas={t['sections_duplicate']}  excluidas_por_selección={t['sections_excluded_by_selection']}")
        for d in build.report["documents"]:
            flag = "OK " if d["included"] else "EXC"
            print(f"  {flag} {d['document_id']:<30} {d['tokens']:>6} tokens")
        for e in build.report["excluded_documents"]:
            print(f"  excluido: {e['document_id']}: {e['reason']}")
        for w in build.warnings:
            print(f"  AVISO: {w}")
        print(f"\n{txt.relative_to(ROOT_DIR)}\n{rep.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
