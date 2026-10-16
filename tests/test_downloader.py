"""robots.txt y Crawl-delay del descargador, sin acceso a la red."""

import pytest

from app.ingestion.downloader import PoliteDownloader, RobotsDisallowed


class FakeResponse:
    def __init__(self, text="", status_code=200, url="", content_type="text/html; charset=utf-8"):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, robots: str):
        self.robots = robots
        self.headers = {}
        self.requested = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(self.robots, url=url)
        return FakeResponse("<html>ok</html>", url=url)


def test_disallowed_url_is_not_downloaded():
    session = FakeSession("User-agent: *\nDisallow: /tramitar\n")
    dl = PoliteDownloader(min_delay=0, session=session)
    with pytest.raises(RobotsDisallowed):
        dl.fetch("https://www.argentina.gob.ar/tramitar")
    assert session.requested == ["https://www.argentina.gob.ar/robots.txt"]


def test_allowed_url_is_downloaded_and_robots_cached():
    session = FakeSession("User-agent: *\nDisallow: /privado/\n")
    dl = PoliteDownloader(min_delay=0, session=session)
    result = dl.fetch("https://sitio.gob.ar/a.html")
    dl.fetch("https://sitio.gob.ar/b.html")
    assert result.status_code == 200 and result.content == b"<html>ok</html>"
    assert session.requested.count("https://sitio.gob.ar/robots.txt") == 1


def test_crawl_delay_is_respected(monkeypatch):
    session = FakeSession("User-agent: *\nCrawl-delay: 10\n")
    dl = PoliteDownloader(min_delay=1, session=session)
    sleeps = []
    monkeypatch.setattr("app.ingestion.downloader.time.sleep", sleeps.append)
    dl.fetch("https://sitio.gob.ar/a.html")
    dl.fetch("https://sitio.gob.ar/b.html")
    assert len(sleeps) == 1 and sleeps[0] > 9  # usa el Crawl-delay (10 s), no el mínimo (1 s)
