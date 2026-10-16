"""Configuración central de TramitaIA: rutas del proyecto y parámetros de entorno."""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SOURCES_FILE = DATA_DIR / "sources.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"


def _load_dotenv(path: Path) -> None:
    """Carga un .env simple (CLAVE=valor) sin pisar variables ya definidas."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT_DIR / ".env")

USER_AGENT = os.environ.get("USER_AGENT") or "TramitaIA/0.1 (proyecto universitario)"
REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS") or 2)
REQUEST_TIMEOUT_SECONDS = 30
