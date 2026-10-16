import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
from bs4 import BeautifulSoup

from briefing.config import ROOT
from briefing.models import Article

LOG = logging.getLogger(__name__)
AGENT = "YumiPersonalBriefing/0.1"
KEYWORDS = re.compile(
    r"인공지능|생성형|반도체|데이터센터|데이터 센터|사이버|해킹|보안|소프트웨어|"
    r"클라우드|로봇|챗봇|챗지피티|오픈AI|네이버|카카오|디지털|정보통신|양자|"
    r"엔비디아|마이크로소프트|구글|애플|삼성전자|SK하이닉스|\bAI\b|\bIT\b",
    re.IGNORECASE,
)


def plain(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def canonical_url(url):
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "cmp", "cmpid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(pairs)), ""))


def allowed_url(url, domains):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (parts.scheme in {"http", "https"} and not parts.username and not parts.password
            and parts.port in {None, 80, 443}
            and any(host == d or host.endswith("." + d) for d in domains))


def get_public(url, domains, limit=2_000_000):
    """Only publisher domains and their redirects; no arbitrary URLs from the LLM."""
    with httpx.Client(timeout=20, headers={"User-Agent": AGENT}, follow_redirects=False) as client:
        for _ in range(5):
            if not allowed_url(url, domains):
                raise ValueError("URL outside configured publisher domains")
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers["location"]))
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Response exceeded size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise ValueError("Too many redirects")


def read_feed(source, since, now):
    data = get_public(source["url"], source["domains"])
    feed = feedparser.parse(data)
    if not feed.entries:
        raise ValueError("Feed returned no entries")
    articles = []
    for entry in feed.entries:
        date = entry.get("published_parsed") or entry.get("updated_parsed")
        if not date:
            continue  # Cannot establish freshness: do not invent a publication date.
        published = datetime(*date[:6], tzinfo=timezone.utc)
        if not since < published <= now:
            continue
        title = plain(entry.get("title", ""))[:300]
        excerpt = plain(entry.get("summary", ""))[:1200]
        if not source["topic_feed"] and not KEYWORDS.search(title + " " + excerpt):
            continue
        url = canonical_url(entry.get("link", ""))
        if not title or not allowed_url(url, source["domains"]):
            continue
        articles.append(Article(
            id=hashlib.sha256(url.encode()).hexdigest()[:16], title=title, url=url,
            source=source["name"], language=source["language"],
            published=published.isoformat(), excerpt=excerpt,
        ))
    return sorted(articles, key=lambda a: a.published, reverse=True)[:12]


class NewsReader:
    def __init__(self):
        self.sources = json.loads((ROOT / "sources.json").read_text())

    def collect(self, since, now, sent_urls=()):
        warnings, articles = [], {}

        def read(source):
            try:
                return source, read_feed(source, since, now), None
            except Exception as exc:
                LOG.warning("Feed unavailable: %s (%s)", source["name"], type(exc).__name__)
                return source, [], f"Source temporarily unavailable: {source['name']}"

        with ThreadPoolExecutor(max_workers=7) as pool:
            for source, batch, error in pool.map(read, self.sources):
                if error:
                    warnings.append(error)
                for article in batch:
                    if article.url not in sent_urls:
                        articles[article.id] = article
        return list(articles.values()), warnings

    def fetch(self, article):
        source = next(s for s in self.sources if s["name"] == article.source)
        parts = urlsplit(article.url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            parser = RobotFileParser()
            parser.parse(get_public(robots_url, source["domains"], limit=200_000).decode("utf-8", "replace").splitlines())
            if not parser.can_fetch(AGENT, article.url):
                return ""
            soup = BeautifulSoup(get_public(article.url, source["domains"]), "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
                tag.decompose()
            main = soup.find("article") or soup.find("main")
            if not main:
                return ""
            return "\n".join(p.get_text(" ", strip=True) for p in main.find_all("p"))[:6000]
        except Exception as exc:
            LOG.info("Article detail unavailable (%s); using RSS evidence only", type(exc).__name__)
            return ""
