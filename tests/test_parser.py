"""Parsers sobre fragmentos mínimos con la misma estructura que las páginas oficiales.

Los fragmentos son sintéticos y solo prueban la lógica de extracción; el contenido real
se valida en tests/test_corpus_real.py.
"""

import pytest

from app.ingestion.parser import (
    ExtractionError, extract_js_literal, normalize_text, parse_argentina_gob,
    parse_ddmmyyyy, parse_justicia_spa, parse_pdf, parse_registro_civil,
)

RC_HTML = """<html><head><title>X</title></head><body>
<header>menu</header>
<main><nav class="breadcrumb-nav">Inicio / Guía</nav>
<section class="tramite-header"><h1 class="tramite-title">Trámite de prueba</h1>
<p class="tramite-updated">Última actualización: 5/3/2025</p></section>
<section class="tramite-content"><h2>Requisitos</h2><ul><li>Requisito&nbsp;uno</li><li>Requisito dos​</li></ul></section>
<section class="tramite-actions"><a>Volver a Guía</a></section>
<script>var x = 1;</script></main><footer>pie</footer></body></html>"""


def test_registro_civil_extracts_title_date_and_text():
    doc = parse_registro_civil(RC_HTML.encode("utf-8"), "utf-8", "https://rc")
    assert doc.title == "Trámite de prueba"
    assert doc.last_updated_date == "2025-03-05"
    assert "Requisito uno" in doc.text and "Requisito dos" in doc.text
    for noise in ("Volver a Guía", "var x", "Inicio / Guía", "menu", "pie", "​"):
        assert noise not in doc.text


def test_registro_civil_without_main_fails_loudly():
    with pytest.raises(ExtractionError):
        parse_registro_civil(b"<html><body><p>hola</p></body></html>", "utf-8", "https://rc")


def test_registro_civil_bad_date_is_reported_not_invented():
    html = RC_HTML.replace("5/3/2025", "35/13/2025")
    doc = parse_registro_civil(html.encode("utf-8"), "utf-8", "https://rc")
    assert doc.last_updated_date is None
    assert doc.errors


JUSTICIA_HTML = """<html><head><title>Secretaría</title></head><body><script>
const AREAS = { rc: {nombre:"Registro Civil", short:"RC"}, aj: {nombre:"Acceso a la Justicia"} };
const TRAMITES = [
  // comentario con ] y { que no debe cortar el literal
  {area:"rc", nombre:"DNI", desc:"Nuevo \\"ejemplar\\"", req:["Llevar DNI [si lo tenés]", "Partida"],},
  {area:"aj", nombre:"Mediación", pdfs:[{label:"Instructivo", url:"requisitos/aj/mediacion.pdf"}]},
];
const FAQ = [ {q:"¿Turno?", a:"Ver <a href='x'>sitio</a>"} ];
const CONTACTOS = [ {area:"rc", dir:"Calle 1", hor:"8 a 13"} ];
</script></body></html>"""


def test_extract_js_literal_respects_strings_and_comments():
    literal = extract_js_literal(JUSTICIA_HTML, "TRAMITES")
    assert literal.startswith("[") and literal.endswith("]")
    assert "Mediación" in literal


def test_justicia_spa_parses_embedded_data():
    doc = parse_justicia_spa(JUSTICIA_HTML.encode("utf-8"), "utf-8", "https://sj.gob.ar/")
    assert "## DNI" in doc.text
    assert "Repartición: Registro Civil" in doc.text
    assert "- Llevar DNI [si lo tenés]" in doc.text
    assert 'Nuevo "ejemplar"' in doc.text
    assert "Atención: Calle 1 · 8 a 13" in doc.text
    assert "Documento adjunto: Instructivo (https://sj.gob.ar/requisitos/aj/mediacion.pdf)" in doc.text
    assert "R: Ver sitio" in doc.text  # HTML de la FAQ convertido a texto
    assert doc.errors == []


def test_justicia_spa_missing_data_fails():
    with pytest.raises(ExtractionError):
        parse_justicia_spa(b"<html><body>sin datos</body></html>", "utf-8", "https://sj")


AR_HTML = """<html><head>
<meta property="article:modified_time" content="2023-07-18T14:09:30-03:00">
<meta property="article:published_time" content="2021-09-13T10:00:00-03:00"></head><body>
<form id="buscador"><input name="q"></form>
<main><ol class="breadcrumb"><li>Inicio</li></ol><h1>Requisitos DNI</h1>
<a>Compartir en Facebook</a><span>Redes Sociales</span>
<form class="webform"><select><option>- Ninguno -</option><option>DNI Primer Ejemplar</option></select>
<div><h3>DNI Primer Ejemplar</h3><p>Partida de nacimiento certificada.</p></div>
<label>Dejar en blanco</label><input name="honeypot"></form></main></body></html>"""


def test_argentina_gob_keeps_form_content_and_dates():
    doc = parse_argentina_gob(AR_HTML.encode("utf-8"), "utf-8", "https://www.argentina.gob.ar/x")
    assert doc.title == "Requisitos DNI"
    assert doc.last_updated_date == "2023-07-18"
    assert doc.publication_date == "2021-09-13"
    assert "Partida de nacimiento certificada." in doc.text
    assert doc.text.count("DNI Primer Ejemplar") == 1  # la opción del <select> no se duplica
    for noise in ("Compartir en", "Redes Sociales", "Dejar en blanco", "- Ninguno -", "Inicio"):
        assert noise not in doc.text


def test_pdf_invalid_bytes_raise_extraction_error():
    with pytest.raises(ExtractionError):
        parse_pdf(b"esto no es un pdf", None, "https://x/doc.pdf")


def test_pdf_without_text_is_reported():
    from io import BytesIO
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(ExtractionError, match="texto"):
        parse_pdf(buffer.getvalue(), None, "https://x/vacio.pdf")


@pytest.mark.parametrize("value,expected", [
    ("20/10/2025", "2025-10-20"), ("1/2/2024", "2024-02-01"), ("32/01/2024", None), ("2024-01-01", None),
])
def test_parse_ddmmyyyy(value, expected):
    assert parse_ddmmyyyy(value) == expected


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  a \t b\n\n\n c​ ") == "a b\n\nc"
