import json
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from briefing.collection import collect, download
from briefing.config import ROOT
from briefing.models import Article


class NewsReader:
    def __init__(self):
        self.sources = json.loads((ROOT / "sources.json").read_text())
        self.report = None

    def collect(self, since, now, sent_urls=()):
        # Retain already-seen URLs: an updated story can have the same canonical URL.
        self.report = collect(self.sources, since, now)
        warnings = []
        for report in self.report["sources"]:
            if report["status"] != "ok":
                warnings.append(f"Source {report['status']}: {report['source']}")
            elif not report["accepted"]:
                warnings.append(f"No dated, eligible candidates: {report['source']}")
        return [Article.model_validate(a) for a in self.report["articles"]], warnings

    def fetch(self, article):
        source = next(s for s in self.sources if s["name"] == article.source)
        parts = urlsplit(article.url)
        robots = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            parser = RobotFileParser()
            parser.parse(download(source | {"url": robots}).decode("utf-8", "replace").splitlines())
            if not parser.can_fetch("TechNewsBriefing/0.1", article.url):
                return "", "robots_denied"
            soup = BeautifulSoup(download(source | {"url": article.url}), "html.parser")
            if soup.select_one('[class*="paywall"], [id*="paywall"]'):
                return "", "paywall"
            for element in soup(["script", "style", "nav", "footer", "aside", "header"]):
                element.decompose()
            main = soup.find("article") or soup.find("main")
            if main is None:
                return "", "no_article_body"
            text = "\n".join(p.get_text(" ", strip=True) for p in main.find_all("p"))[:6000]
            return (text, "available") if text else ("", "empty_body")
        except Exception:
            return "", "unavailable"
