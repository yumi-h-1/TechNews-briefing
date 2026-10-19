"""Bounded RSS/Atom collection. Feed content is data, never instructions."""
import hashlib
import json
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

UTC = timezone.utc
KEYWORDS = re.compile(r"인공지능|생성형|반도체|데이터\s?센터|사이버|해킹|보안|소프트웨어|클라우드|로봇|챗봇|오픈AI|네이버|카카오|정보통신|양자|엔비디아|마이크로소프트|구글|애플|삼성전자|SK하이닉스|\bAI\b|\bIT\b", re.I)


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = parsedate_to_datetime(value)
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(UTC)


def clean(value):
    return unescape(re.sub(r"<[^>]*>", " ", value or "")).strip()


def canonical(url):
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "cmp", "cmpid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(sorted(query)), ""))


def allowed(url, domains):
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        return (p.scheme == "https" and not p.username and not p.password
                and p.port in (None, 443)
                and any(host == d or host.endswith("." + d) for d in domains))
    except ValueError:
        return False


def download(source):
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allowed(newurl, source["domains"]):
                raise ValueError("Redirect outside publisher allowlist")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    if not allowed(source["url"], source["domains"]):
        raise ValueError("Feed outside publisher allowlist")
    request = Request(source["url"], headers={"User-Agent": "TechNewsBriefing/0.1"})
    with build_opener(Redirects()).open(request, timeout=20) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Feed exceeds 2 MB")
        return data


def parse(data, source, since, until, limit=50):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML declarations with entities are unsupported")
    root = ET.fromstring(data)
    def name(tag):
        return tag.rsplit("}", 1)[-1]
    if name(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("Response is not an RSS or Atom feed")
    entries = [e for e in root.iter() if name(e.tag) in {"item", "entry"}]
    stats = Counter()
    candidates = []
    for entry in entries:
        fields = {}
        for child in entry:
            key = name(child.tag)
            if key == "link" and child.attrib.get("rel", "alternate") != "alternate":
                continue
            fields.setdefault(key, child.attrib.get("href") or "".join(child.itertext()))
        date = fields.get("pubDate") or fields.get("published") or fields.get("date")
        # updated is deliberately not substituted for an unknown publication date.
        try:
            published = instant(date or "")
        except (ValueError, TypeError, OverflowError):
            stats["unknown_date"] += 1
            continue
        if published <= since:
            stats["old"] += 1
            continue
        if published > until:
            stats["future"] += 1
            continue
        title = clean(fields.get("title"))[:500]
        excerpt = clean(fields.get("description") or fields.get("summary") or fields.get("content"))[:4000]
        try:
            url = canonical(fields.get("link", ""))
        except ValueError:
            url = ""
        if not title or not allowed(url, source["domains"]):
            stats["invalid_article"] += 1
            continue
        if not source["topic_feed"] and not KEYWORDS.search(title + " " + excerpt):
            stats["off_topic"] += 1
            continue
        candidates.append(dict(id=hashlib.sha256(url.encode()).hexdigest(), url=url, title=title,
                               excerpt=excerpt, source=source["name"], language=source["language"],
                               published=published.isoformat(), collected_at=until.isoformat()))
    candidates.sort(key=lambda a: a["published"], reverse=True)
    stats["over_limit"] += max(0, len(candidates) - limit)
    return candidates[:limit], dict(stats), len(entries)


def collect(sources, since, until, fetch=download, limit=50):
    if since.tzinfo is None or until.tzinfo is None or since >= until:
        raise ValueError("Collection requires an aware, increasing time window")
    if limit < 1:
        raise ValueError("Candidate limit must be positive")
    since, until = since.astimezone(UTC), until.astimezone(UTC)
    articles, reports, seen = [], [], set()
    for source in sources:
        report = dict(source=source["name"], feed_url=source["url"], status="ok", accepted=0)
        try:
            batch, excluded, total = parse(fetch(source), source, since, until, limit)
            report.update(entries=total, excluded=excluded)
            if total == 0:
                report["status"] = "empty_feed"
            for article in batch:
                if article["url"] in seen:
                    excluded["duplicate_url"] = excluded.get("duplicate_url", 0) + 1
                    continue
                seen.add(article["url"])
                articles.append(article)
                report["accepted"] += 1
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
        reports.append(report)
    return dict(run_id=uuid.uuid4().hex, since=since.isoformat(), until=until.isoformat(),
                articles=articles, sources=reports,
                notice="Candidates only; event country and factual quality have not been reviewed.")


def save(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript('''
CREATE TABLE IF NOT EXISTS collection_runs (
 id TEXT PRIMARY KEY, since TEXT NOT NULL, until TEXT NOT NULL, report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_candidates (
 run_id TEXT NOT NULL, article_id TEXT NOT NULL,
 PRIMARY KEY (run_id, article_id));
''')
        db.execute("INSERT INTO collection_runs VALUES (?,?,?,?)",
                   (result["run_id"], result["since"], result["until"], json.dumps(result, ensure_ascii=False)))
        for article in result["articles"]:
            db.execute("INSERT INTO candidates VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                       (article["id"], json.dumps(article, ensure_ascii=False)))
            db.execute("INSERT INTO run_candidates VALUES (?,?)", (result["run_id"], article["id"]))
