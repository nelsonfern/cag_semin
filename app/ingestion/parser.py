"""Extracción de texto de documentos oficiales.

Cada fuente declara su parser en ``data/sources.json``. Todos devuelven un
``ParsedDocument`` con el título publicado, el texto limpio, las fechas que el propio
organismo publica (si existen) y los errores de extracción, que nunca se ocultan.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin

import json5
from bs4 import BeautifulSoup
from pypdf import PdfReader


@dataclass
class ParsedDocument:
    title: str | None
    text: str
    last_updated_date: str | None = None
    publication_date: str | None = None
    errors: list[str] = field(default_factory=list)


class ExtractionError(Exception):
    """El documento no tiene texto utilizable con el parser elegido."""


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿­"), None)


def normalize_text(text: str) -> str:
    """NFC, sin caracteres invisibles, espacios colapsados y sin líneas vacías repetidas."""
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def decode_html(content: bytes, encoding: str | None) -> str:
    return content.decode(encoding or "utf-8", errors="replace")


def parse_ddmmyyyy(value: str) -> str | None:
    """'20/10/2025' -> '2025-10-20'. Devuelve None si no es una fecha válida."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _block_text(node) -> str:
    """Texto de un nodo HTML con un salto de línea por bloque."""
    return node.get_text("\n", strip=True)


# ---------------------------------------------------------------------------
# Registro Civil de La Rioja (páginas tramite-*.html)
# ---------------------------------------------------------------------------

_RC_BOILERPLATE = {"Volver a Guía", "Encontrar Delegación", "Iniciar trámite digital"}


def parse_registro_civil(content: bytes, encoding: str | None, source_url: str) -> ParsedDocument:
    soup = BeautifulSoup(decode_html(content, encoding), "html.parser")
    main = soup.find("main")
    if main is None:
        raise ExtractionError("No se encontró <main> en la página del Registro Civil")
    for tag in main(["script", "style", "nav", "form", "button"]):
        tag.decompose()

    h1 = main.find("h1")
    title = normalize_text(h1.get_text(" ", strip=True)) if h1 else None

    last_updated = None
    errors: list[str] = []
    updated = main.find(class_="tramite-updated")
    if updated is not None:
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", updated.get_text())
        last_updated = parse_ddmmyyyy(m.group(1)) if m else None
        if last_updated is None:
            errors.append(f"No se pudo interpretar la fecha de actualización: {updated.get_text(strip=True)!r}")

    lines = [l for l in normalize_text(_block_text(main)).splitlines() if l not in _RC_BOILERPLATE]
    text = normalize_text("\n".join(lines))
    if not text:
        raise ExtractionError("La página del Registro Civil no tiene texto")
    return ParsedDocument(title=title, text=text, last_updated_date=last_updated, errors=errors)


# ---------------------------------------------------------------------------
# Secretaría de Justicia (sitio de una página; datos incrustados en JavaScript)
# ---------------------------------------------------------------------------

def extract_js_literal(source: str, name: str) -> str:
    """Devuelve el literal ``[...]`` o ``{...}`` asignado a ``const <name> =``.

    Recorre el código respetando cadenas y comentarios de línea para encontrar el cierre
    correcto; no ejecuta JavaScript.
    """
    match = re.search(rf"\bconst\s+{re.escape(name)}\s*=\s*([\[{{])", source)
    if not match:
        raise ExtractionError(f"No se encontró 'const {name} =' en la página")
    start = match.start(1)
    opener = source[start]
    closer = "]" if opener == "[" else "}"
    depth, quote, i = 0, None, start
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif source.startswith("//", i):
            i = source.find("\n", i)
            if i == -1:
                break
        elif source.startswith("/*", i):
            i = source.find("*/", i) + 1
            if i == 0:
                break
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    raise ExtractionError(f"Literal '{name}' sin cierre")


def _html_to_text(fragment: str) -> str:
    return BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True)


def parse_justicia_spa(content: bytes, encoding: str | None, source_url: str) -> ParsedDocument:
    html = decode_html(content, encoding)
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_text(soup.title.get_text(strip=True)) if soup.title else None

    try:
        areas = json5.loads(extract_js_literal(html, "AREAS"))
        tramites = json5.loads(extract_js_literal(html, "TRAMITES"))
    except ValueError as exc:  # json5 lanza ValueError ante sintaxis no soportada
        raise ExtractionError(f"No se pudieron interpretar los datos de trámites: {exc}") from exc

    errors: list[str] = []
    contactos: list = []
    faq: list = []
    for name, target in (("CONTACTOS", contactos), ("FAQ", faq)):
        try:
            target.extend(json5.loads(extract_js_literal(html, name)))
        except (ExtractionError, ValueError) as exc:
            errors.append(f"{name}: {exc}")

    contact_by_area = {c.get("area"): c for c in contactos}
    lines: list[str] = [
        "Guía de trámites de la Secretaría de Justicia de La Rioja.",
        "Reparticiones: " + ", ".join(a.get("nombre", k) for k, a in areas.items()) + ".",
    ]
    for tramite in tramites:
        area = areas.get(tramite.get("area"), {})
        lines += ["", f"## {tramite.get('nombre', '').strip()}"]
        lines.append(f"Repartición: {area.get('nombre', tramite.get('area'))}")
        for key, label in (("subtitulo", "Subtítulo"), ("desc", "Descripción"),
                           ("modalidad", "Modalidad"), ("tiempo", "Tiempo / turno"),
                           ("lugar", "Lugar"), ("costo", "Costo"), ("whatsapp", "WhatsApp")):
            value = tramite.get(key)
            if value:
                lines.append(f"{label}: {_html_to_text(str(value))}")
        requisitos = tramite.get("req") or []
        if requisitos:
            lines.append("Requisitos:")
            lines += [f"- {_html_to_text(str(r))}" for r in requisitos]
        pdfs = [p for p in (tramite.get("pdfs") or []) if p] + ([tramite["pdfUrl"]] if tramite.get("pdfUrl") else [])
        for pdf in pdfs:
            # Entradas {label, url} o una URL suelta; las rutas son relativas al sitio.
            label = (pdf.get("label") or "Documento") if isinstance(pdf, dict) else "Documento"
            url = urljoin(source_url, pdf.get("url", "") if isinstance(pdf, dict) else pdf)
            lines.append(f"Documento adjunto: {label} ({url})")
        contact = contact_by_area.get(tramite.get("area"))
        if contact:
            parts = [contact.get("dir"), contact.get("hor"), contact.get("tel"), contact.get("mail")]
            lines.append("Atención: " + " · ".join(p for p in parts if p))

    if faq:
        lines += ["", "## Preguntas frecuentes"]
        for item in faq:
            lines += [f"P: {_html_to_text(item.get('q', ''))}", f"R: {_html_to_text(item.get('a', ''))}"]

    return ParsedDocument(title=title, text=normalize_text("\n".join(lines)), errors=errors)


# ---------------------------------------------------------------------------
# argentina.gob.ar (sitio Drupal del Gobierno nacional)
# ---------------------------------------------------------------------------

_AR_BOILERPLATE_PREFIXES = ("Compartir en ",)
# "Dejar en blanco" es la etiqueta del campo anti-spam (honeypot) del formulario.
_AR_BOILERPLATE = {"Redes Sociales", "- Ninguno -", "Dejar en blanco"}


def parse_argentina_gob(content: bytes, encoding: str | None, source_url: str) -> ParsedDocument:
    soup = BeautifulSoup(decode_html(content, encoding), "html.parser")
    modified = soup.find("meta", attrs={"property": "article:modified_time"})
    published = soup.find("meta", attrs={"property": "article:published_time"})
    main = soup.find("main") or soup.body
    if main is None:
        raise ExtractionError("Página sin contenido principal")
    # Los requisitos están dentro de un <form> de Drupal (secciones condicionales), así que el
    # formulario se conserva; solo se quita el <select>, cuyas opciones repiten los títulos.
    for tag in main(["script", "style", "nav", "select", "input", "button", "footer"]):
        tag.decompose()
    for crumb in main.select(".breadcrumb, ol.breadcrumb"):
        crumb.decompose()

    h1 = main.find("h1")
    title = normalize_text(h1.get_text(" ", strip=True)) if h1 else None
    lines = [
        l for l in normalize_text(_block_text(main)).splitlines()
        if l not in _AR_BOILERPLATE and not l.startswith(_AR_BOILERPLATE_PREFIXES)
    ]
    text = normalize_text("\n".join(lines))
    if not text:
        raise ExtractionError("La página no tiene texto")
    return ParsedDocument(
        title=title,
        text=text,
        last_updated_date=modified["content"][:10] if modified and modified.get("content") else None,
        publication_date=published["content"][:10] if published and published.get("content") else None,
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def parse_pdf(content: bytes, encoding: str | None, source_url: str) -> ParsedDocument:
    errors: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # pypdf lanza varios tipos según el daño del archivo
        raise ExtractionError(f"No se pudo abrir el PDF: {exc}") from exc
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            errors.append(f"Página {number}: {exc}")
            continue
        if not page_text.strip():
            errors.append(f"Página {number}: sin texto extraíble (¿escaneada? requiere OCR)")
        pages.append(page_text)
    text = normalize_text("\n\n".join(pages))
    if not text:
        raise ExtractionError("El PDF no contiene texto extraíble")
    # El /Title de los PDF suele ser la primera línea que puso Word (p. ej. "LA CÁMARA DE
    # DIPUTADOS ... SANCIONA CON FUERZA DE"), no el nombre de la norma: se usa el de sources.json.
    return ParsedDocument(title=None, text=text, errors=errors)


# ---------------------------------------------------------------------------

Parser = Callable[[bytes, "str | None", str], ParsedDocument]

PARSERS: dict[str, Parser] = {
    "registro_civil": parse_registro_civil,
    "justicia_spa": parse_justicia_spa,
    "argentina_gob": parse_argentina_gob,
    "pdf": parse_pdf,
}


def get_parser(name: str) -> Parser:
    try:
        return PARSERS[name]
    except KeyError:
        raise ValueError(f"Parser desconocido: {name!r}. Disponibles: {sorted(PARSERS)}") from None
