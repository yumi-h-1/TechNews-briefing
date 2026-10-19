import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from briefing.collection import allowed, collect, instant, parse, save

SOURCE = dict(name="한국어 언론", url="https://example.com/rss", domains=["example.com"], language="ko", topic_feed=False)
START = instant("2026-10-15T08:00:00Z")
END = instant("2026-10-16T08:00:00Z")


def item(title="AI 반도체", date="Fri, 16 Oct 2026 07:00:00 GMT", url="https://example.com/a"):
    return f"<item><title>{title}</title><link>{url}</link><pubDate>{date}</pubDate></item>"


def feed(*items):
    return ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()


class CollectionTests(unittest.TestCase):
    def test_window_and_exclusion_reasons(self):
        data = feed(item(), item(date=""), item(date="Thu, 15 Oct 2026 08:00:00 GMT"),
                    item(date="Fri, 16 Oct 2026 09:00:00 GMT"), item(title="날씨"), item(url="https://evil.com/a"))
        articles, reasons, count = parse(data, SOURCE, START, END)
        self.assertEqual(len(articles), 1)
        self.assertEqual(count, 6)
        for reason in ("unknown_date", "old", "future", "off_topic", "invalid_article"):
            self.assertEqual(reasons[reason], 1)

    def test_duplicates_and_source_failure(self):
        second = dict(SOURCE, name="broken")
        def fetch(source):
            if source["name"] == "broken":
                raise TimeoutError()
            return feed(item(url="https://example.com/a?utm_source=rss"), item())
        result = collect([SOURCE, second], START, END, fetch)
        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(result["sources"][0]["excluded"]["duplicate_url"], 1)
        self.assertEqual(result["sources"][1]["status"], "failed")

    def test_atom_and_unknown_publication(self):
        data = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI</title><link href="https://example.com/a"/><published>2026-10-16T08:00:00+01:00</published></entry><entry><updated>2026-10-16T07:00:00Z</updated></entry></feed>'
        articles, reasons, _ = parse(data, SOURCE, START, END)
        self.assertEqual(articles[0]["published"], "2026-10-16T07:00:00+00:00")
        self.assertEqual(reasons["unknown_date"], 1)

    def test_limit_and_newest_first(self):
        articles, reasons, _ = parse(feed(item(date="Fri, 16 Oct 2026 06:00:00 GMT"), item()), SOURCE, START, END, limit=1)
        self.assertIn("07:00", articles[0]["published"])
        self.assertEqual(reasons["over_limit"], 1)

    def test_storage_survives_reopen_and_preserves_runs(self):
        result = collect([SOURCE], START, END, lambda _: feed(item()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news.sqlite3"
            save(path, result)
            result2 = collect([SOURCE], START, END, lambda _: feed(item()))
            save(path, result2)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM candidates").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT count(*) FROM run_candidates").fetchone()[0], 2)
                stored = json.loads(db.execute("SELECT report FROM collection_runs WHERE id=?", (result["run_id"],)).fetchone()[0])
                self.assertEqual(stored, result)

    def test_untrusted_xml_and_non_feed_rejected(self):
        for data in (b"<html/>", b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>'):
            result = collect([SOURCE], START, END, lambda _: data)
            self.assertEqual(result["sources"][0]["status"], "failed")

    def test_domains_and_invalid_ports(self):
        for url in ("https://example.com.evil.org/a", "https://example.com:bad", "https://user@example.com/a", "http://example.com/a"):
            self.assertFalse(allowed(url, SOURCE["domains"]))

    def test_requires_aware_window(self):
        with self.assertRaises(ValueError):
            collect([], datetime(2026, 10, 15), END)
        with self.assertRaises(ValueError):
            instant("2026-10-15T08:00:00")


if __name__ == "__main__":
    unittest.main()
