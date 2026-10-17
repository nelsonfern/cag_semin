"""Interfaz web: FastAPI sirve la página y sus archivos; el formateo del texto del modelo es seguro."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import WEB_DIR, create_app
from tests.test_api import ready_runtime

APP_JS = WEB_DIR / "app.js"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(ready_runtime(), start_engine=False)) as c:
        yield c


def test_index_is_served_with_the_main_parts(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "No es un sitio oficial" in html          # aviso visible: TramitaIA no es un sitio del gobierno
    assert 'id="consulta"' in html and 'for="pregunta"' in html
    assert "Fuentes (" in html and "Sobre TramitaIA" in html and "Nueva consulta" in html
    assert "Documentos consultables" in html and "puede equivocarse" in html
    assert '/static/vendor/alpine.min.js' in html


def test_static_files_are_served(client):
    for path, kind in [("/static/styles.css", "text/css"), ("/static/app.js", "javascript"),
                       ("/static/vendor/alpine.min.js", "javascript"), ("/static/icon.svg", "image/svg")]:
        r = client.get(path)
        assert r.status_code == 200 and kind in r.headers["content-type"], path


def test_page_does_not_load_anything_from_the_internet():
    # La demo tiene que funcionar sin conexión: nada de CDN ni fuentes externas.
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?://', html)
    assert "@import" not in css and "url(http" not in css


def test_api_routes_still_work_next_to_the_page(client):
    assert client.get("/health").json()["status"] == "ready"


# --- Formateo del texto del modelo (JavaScript, con Node) ---------------------------------

NODE = shutil.which("node")


def formatear(texto: str) -> str:
    script = f"const m = require({json.dumps(str(APP_JS))}); process.stdout.write(m.formatear({json.dumps(texto)}));"
    return subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout


@pytest.mark.skipif(NODE is None, reason="Node no está instalado")
class TestFormatear:
    def test_html_from_the_model_is_escaped(self):
        out = formatear('<script>alert(1)</script> <img src=x onerror="alert(2)">')
        assert "<script>" not in out and "<img" not in out
        assert "&lt;script&gt;" in out

    def test_no_links_are_created_from_the_model_text(self):
        out = formatear("Mirá [acá](https://falso.com) o https://otro.com y www.tercero.com")
        assert "<a " not in out and "href" not in out

    def test_lists_bold_and_citations(self):
        out = formatear("**Requisitos:**\n- DNI [rc-a#s1, rc-a#s2]\n- Partida\n**Pasos:**\n1. Pedir turno")
        assert "<strong>Requisitos:</strong>" in out
        assert "<ul><li>DNI" in out and '<span class="cita">rc-a#s1</span><span class="cita">rc-a#s2</span>' in out
        assert "</ul><p><strong>Pasos:</strong></p><ol><li>Pedir turno</li></ol>" in out

    def test_citation_markup_cannot_be_abused(self):
        out = formatear('[<b>x</b>#s1] y [rc-a#s1"onmouseover="x]')
        assert "<b>" not in out and 'onmouseover="' not in out
