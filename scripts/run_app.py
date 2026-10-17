"""Lanza TramitaIA: la API y la interfaz web en un solo servidor (uvicorn).

    .venv\\Scripts\\python scripts\\run_app.py            # http://127.0.0.1:8000
    .venv\\Scripts\\python scripts\\run_app.py --abrir    # además abre el navegador cuando el motor está listo

Equivale a ``python -m uvicorn app.main:app --port 8000``. El motor (modelo + caché KV) se prepara
en segundo plano: la página muestra «Preparando el asistente…» hasta que está listo.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _abrir_cuando_este_listo(url: str) -> None:
    """Espera a que /health diga «ready» y abre la página."""
    for _ in range(600):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=3) as r:
                if json.load(r).get("status") == "ready":
                    webbrowser.open(url)
                    return
        except OSError:
            pass
        time.sleep(2)


def main() -> None:
    """Arranca uvicorn y, si se pide, abre el navegador cuando el motor termina de prepararse."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRAMITAIA_PORT", "8000")))
    parser.add_argument("--abrir", action="store_true", help="abrir el navegador cuando esté listo")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    print(f"TramitaIA: {url}  (documentación de la API: {url}/docs)", flush=True)
    if args.abrir:
        threading.Thread(target=_abrir_cuando_este_listo, args=(url,), daemon=True).start()
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                        "--port", str(args.port)], cwd=ROOT, env=env, check=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
