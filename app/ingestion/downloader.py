"""Descarga respetuosa de documentos oficiales.

- Consulta ``robots.txt`` de cada host antes de descargar y respeta ``Crawl-delay``.
- Usa un User-Agent identificable y una pausa mínima entre solicitudes al mismo host.
- No intenta eludir autenticación, CAPTCHA ni controles de acceso: si el sitio no permite
  la descarga automática, el documento queda para importación manual.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.config import REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT


class RobotsDisallowed(Exception):
    """robots.txt no permite descargar la URL con nuestro User-Agent."""


@dataclass
class FetchResult:
    url: str              # URL solicitada
    final_url: str        # URL final tras redirecciones
    status_code: int
    content_type: str
    content: bytes
    encoding: str | None  # codificación declarada o detectada


class PoliteDownloader:
    def __init__(
        self,
        user_agent: str = USER_AGENT,
        min_delay: float = REQUEST_DELAY_SECONDS,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ):
        self.user_agent = user_agent
        self.min_delay = min_delay
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlparse(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            parser = RobotFileParser()
            try:
                resp = self.session.get(f"{host}/robots.txt", timeout=self.timeout)
                # Sin robots.txt (404) se asume permitido; otros errores también se tratan
                # como "sin reglas", igual que hace la mayoría de los rastreadores.
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                parser = None
            self._robots[host] = parser
        return self._robots[host]

    def is_allowed(self, url: str) -> bool:
        robots = self._robots_for(url)
        return True if robots is None else robots.can_fetch(self.user_agent, url)

    def _wait_turn(self, url: str) -> None:
        host = urlparse(url).netloc
        robots = self._robots_for(url)
        crawl_delay = (robots.crawl_delay(self.user_agent) if robots else None) or 0
        delay = max(self.min_delay, float(crawl_delay))
        elapsed = time.monotonic() - self._last_request.get(host, float("-inf"))
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request[host] = time.monotonic()

    def fetch(self, url: str) -> FetchResult:
        if not self.is_allowed(url):
            raise RobotsDisallowed(f"robots.txt no permite descargar {url}")
        self._wait_turn(url)
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        encoding = resp.encoding if "charset" in content_type.lower() else resp.apparent_encoding
        return FetchResult(
            url=url,
            final_url=resp.url,
            status_code=resp.status_code,
            content_type=content_type,
            content=resp.content,
            encoding=encoding,
        )
