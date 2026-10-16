import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from briefing.agent import build_graph, normalize_draft, normalize_plan
from briefing.app import deliver, due
from briefing.config import Settings
from briefing.mail import DeliveryUncertain, send_email
from briefing.models import Article, Draft, Pick, Plan, Review, Story
from briefing.news import allowed_url, canonical_url, read_feed
from briefing.render import render_digest
from briefing.storage import Store

NOW = datetime(2026, 10, 16, 7, tzinfo=timezone.utc)


def article(id="a", language="en"):
    return Article(id=id, title="UK team releases AI toolkit", url="https://www.bbc.com/news/" + id,
                   source="BBC Technology", language=language, published=NOW.isoformat(),
                   excerpt="A UK team released an AI evaluation toolkit on Friday.")


def story(id="a", **changes):
    data = dict(article_id=id, country="UK", headline="UK team shares toolkit",
                summary="A UK team released an AI evaluation toolkit.",
                why_it_matters="The toolkit provides a way to evaluate AI systems.",
                evidence_quote="A UK team released", event_key="uk-team-toolkit")
    return Story(**(data | changes))


def plan(*ids):
    return Plan(picks=[Pick(article_id=id, country="UK", country_reason="UK research team") for id in ids], fetch_ids=[])


def test_schedule_accounts_for_british_summer_time(tmp_path):
    settings = Settings(tmp_path)
    assert due(datetime(2026, 7, 1, 7, tzinfo=timezone.utc), settings)
    assert not due(datetime(2026, 7, 1, 8, tzinfo=timezone.utc), settings)
    assert due(datetime(2026, 12, 1, 8, tzinfo=timezone.utc), settings)
    assert not due(datetime(2026, 12, 1, 7, 59, tzinfo=timezone.utc), settings)


def test_schedule_handles_dst_transition_dates(tmp_path):
    settings = Settings(tmp_path)
    assert due(datetime(2026, 10, 25, 8, tzinfo=timezone.utc), settings)
    assert due(datetime(2026, 3, 29, 7, tzinfo=timezone.utc), settings)


def test_korean_sources_are_required_and_caps_enforced():
    articles = [article(str(n)) for n in range(6)]
    raw = plan(*[a.id for a in articles])
    raw.picks.append(Pick(article_id="0", country="KR", country_reason="Korea"))
    raw.fetch_ids = [a.id for a in articles] + ["invented"]
    clean = normalize_plan(raw, articles)
    assert len(clean.picks) == 3
    assert len(clean.fetch_ids) == 3
    assert all(p.country == "UK" for p in clean.picks)
    only_kr = Plan(picks=[Pick(article_id="0", country="KR", country_reason="Korea")], fetch_ids=[])
    assert not normalize_plan(only_kr, articles).picks


@pytest.mark.parametrize("changes", [
    {"evidence_quote": "This statement was never in the source"},
    {"country": "US"}, {"article_id": "invented"},
    {"summary": "한국어로 잘못 생성된 영국 요약"},
])
def test_invalid_or_unsupported_stories_are_removed(changes):
    assert not normalize_draft(Draft(stories=[story(**changes)]), plan("a"), [article()], []).stories


def test_deduplicates_within_edition_and_prior_history():
    draft = Draft(stories=[story(), story()])
    assert len(normalize_draft(draft, plan("a"), [article()], []).stories) == 1
    assert not normalize_draft(draft, plan("a"), [article()], [{"event_key": "uk-team-toolkit"}]).stories


def test_graph_fetches_only_bounded_ids_and_revises_once():
    editor, reader = Mock(), Mock()
    editor.plan.return_value = Plan(picks=plan("a").picks, fetch_ids=["a"])
    editor.compose.return_value = Draft(stories=[story()])
    editor.review.side_effect = [Review(approved_ids=[], feedback=["Revise"]),
                                 Review(approved_ids=["a"], feedback=[])]
    reader.fetch.return_value = "Additional source evidence."
    output = build_graph(editor, reader).invoke({"articles": [article().model_dump()], "history": [],
                                                "warnings": [], "revisions": 0})
    assert editor.compose.call_count == 2
    assert editor.review.call_count == 2
    assert reader.fetch.call_count == 1
    assert output["revisions"] == 1
    assert len(output["draft"]["stories"]) == 1


def test_graph_drops_unapproved_story_after_revision_limit():
    editor, reader = Mock(), Mock()
    editor.plan.return_value = plan("a")
    editor.compose.return_value = Draft(stories=[story()])
    editor.review.return_value = Review(approved_ids=[], feedback=["Unsupported"])
    output = build_graph(editor, reader).invoke({"articles": [article().model_dump()], "history": [],
                                                "warnings": [], "revisions": 0})
    assert output["draft"]["stories"] == []
    assert editor.compose.call_count == 2
    reader.fetch.assert_not_called()


def test_feed_filters_old_undated_future_and_non_it(monkeypatch):
    xml = b'''<rss version="2.0"><channel><title>Feed</title>
<item><title>AI announcement</title><link>https://www.bbc.com/news/a?utm_source=x</link><pubDate>Fri, 16 Oct 2026 06:00:00 GMT</pubDate><description>AI news</description></item>
<item><title>AI old</title><link>https://www.bbc.com/news/b</link><pubDate>Mon, 12 Oct 2026 06:00:00 GMT</pubDate></item>
<item><title>AI undated</title><link>https://www.bbc.com/news/c</link></item>
<item><title>AI future</title><link>https://www.bbc.com/news/d</link><pubDate>Sat, 17 Oct 2026 06:00:00 GMT</pubDate></item>
<item><title>Football</title><link>https://www.bbc.com/news/e</link><pubDate>Fri, 16 Oct 2026 06:00:00 GMT</pubDate></item>
</channel></rss>'''
    monkeypatch.setattr("briefing.news.get_public", lambda *a, **kw: xml)
    source = {"url": "https://www.bbc.com/rss", "domains": ["bbc.com"], "name": "BBC", "language": "en", "topic_feed": False}
    result = read_feed(source, NOW-timedelta(hours=24), NOW)
    assert len(result) == 1
    assert result[0].url == "https://www.bbc.com/news/a"


def test_url_allowlist_and_tracking_removal():
    assert not allowed_url("https://bbc.com.evil.example/news", ["bbc.com"])
    assert not allowed_url("file:///etc/passwd", ["bbc.com"])
    assert not allowed_url("https://user@bbc.com/news", ["bbc.com"])
    assert canonical_url("https://www.bbc.com/a?utm_source=x&id=2#frag") == "https://www.bbc.com/a?id=2"


def payload():
    return {"subject": "Briefing", "html": "<p>Briefing</p>", "text": "Briefing", "stories": [],
            "history": [{"url": article().url, "event_key": "event-a", "headline": "A"}]}


def test_successful_delivery_only_once_and_commits_history(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    generate, send = Mock(return_value=payload()), Mock(return_value="message-123")
    monkeypatch.setattr("briefing.app.generate", generate)
    monkeypatch.setattr("briefing.app.send_email", send)
    assert deliver(settings, NOW) == "sent"
    assert deliver(settings, NOW) == "sent"
    assert send.call_count == 1
    assert generate.call_count == 1
    store = Store(tmp_path)
    assert article().url in store.sent_urls()
    assert store.window(NOW+timedelta(days=1)) == NOW


def test_unknown_delivery_blocks_retry_and_does_not_mark_history(tmp_path, monkeypatch):
    monkeypatch.setattr("briefing.app.generate", Mock(return_value=payload()))
    send = Mock(side_effect=DeliveryUncertain("unknown"))
    monkeypatch.setattr("briefing.app.send_email", send)
    assert deliver(Settings(tmp_path), NOW) == "uncertain"
    assert deliver(Settings(tmp_path), NOW) == "uncertain"
    assert send.call_count == 1
    assert not Store(tmp_path).sent_urls()


def test_crash_after_sending_blocks_resend(tmp_path):
    store = Store(tmp_path)
    assert store.begin("2026-10-16")
    store.prepare("2026-10-16", NOW, payload())
    store.status("2026-10-16", "sending")
    assert not store.begin("2026-10-16")


def test_rejected_mail_reuses_payload_with_three_attempt_limit(tmp_path, monkeypatch):
    generate = Mock(return_value=payload())
    send = Mock(side_effect=RuntimeError("rejected"))
    monkeypatch.setattr("briefing.app.generate", generate)
    monkeypatch.setattr("briefing.app.send_email", send)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            deliver(Settings(tmp_path), NOW)
    assert deliver(Settings(tmp_path), NOW) == "prepared"
    assert send.call_count == 3
    assert generate.call_count == 1


def test_resend_has_stable_idempotency_key_and_one_recipient(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-key-for-offline-test")
    response = Mock(status_code=200)
    response.json.return_value = {"id": "id-1"}
    post = Mock(return_value=response)
    monkeypatch.setattr("briefing.mail.httpx.post", post)
    for _ in range(2):
        assert send_email(Settings(tmp_path), payload(), "2026-10-16", NOW) == "id-1"
    calls = post.call_args_list
    assert calls[0].kwargs["headers"]["Idempotency-Key"] == calls[1].kwargs["headers"]["Idempotency-Key"]
    assert calls[0].kwargs["json"]["to"] == ["yumi.heo.01@gmail.com"]


def test_html_escapes_untrusted_content():
    draft = Draft(stories=[story(headline="<script>alert(1)</script>")])
    result = render_digest(draft, [article()], "2026-10-16", ["<img src=x>"])
    assert "<script>" not in result["html"]
    assert "&lt;script&gt;" in result["html"]
    assert "United Kingdom" in result["html"] and "대한민국" in result["html"]
