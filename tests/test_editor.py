import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from briefing.agent import build_graph, normalize_draft, normalize_plan
from briefing.app import deliver
from briefing.config import Settings
from briefing.mail import DeliveryUncertain, send_email
from briefing.models import Article, Draft, Pick, Plan, Review, Story
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
    editor, reader = Mock(max_per_country=3), Mock()
    editor.plan.return_value = Plan(picks=plan("a").picks, fetch_ids=["a"])
    editor.compose.return_value = Draft(stories=[story()])
    editor.review.side_effect = [Review(approved_ids=[], feedback=["Revise"]),
                                 Review(approved_ids=["a"], feedback=[])]
    reader.fetch.return_value = ("Additional source evidence.", "available")
    output = build_graph(editor, reader).invoke({"articles": [article().model_dump()], "history": [],
                                                "warnings": [], "revisions": 0})
    assert editor.compose.call_count == 2
    assert editor.review.call_count == 2
    assert reader.fetch.call_count == 1
    assert output["revisions"] == 1
    assert len(output["draft"]["stories"]) == 1


def test_graph_drops_unapproved_story_after_revision_limit():
    editor, reader = Mock(max_per_country=3), Mock()
    editor.plan.return_value = plan("a")
    editor.compose.return_value = Draft(stories=[story()])
    editor.review.return_value = Review(approved_ids=[], feedback=["Unsupported"])
    output = build_graph(editor, reader).invoke({"articles": [article().model_dump()], "history": [],
                                                "warnings": [], "revisions": 0})
    assert output["draft"]["stories"] == []
    assert editor.compose.call_count == 2
    reader.fetch.assert_not_called()




def test_graph_empty_selection_skips_generation():
    editor, reader = Mock(max_per_country=3), Mock()
    editor.plan.return_value = Plan(picks=[], fetch_ids=[])
    result = build_graph(editor, reader).invoke({"articles": [article().model_dump()], "history": [], "warnings": []})
    assert result["draft"]["stories"] == []
    editor.compose.assert_not_called()
    editor.review.assert_not_called()


def test_material_update_requires_new_source_evidence():
    history = [{"event_key": "uk-team-toolkit", "url": article().url, "evidence": "A UK team announced a toolkit."}]
    updated = story(update_reason="The release is now available", update_quote="released an AI evaluation toolkit")
    assert normalize_draft(Draft(stories=[updated]), plan("a"), [article()], history).stories
    history[0]["evidence"] = article().evidence()
    assert not normalize_draft(Draft(stories=[updated]), plan("a"), [article()], history).stories


def test_html_escapes_untrusted_content():
    result = render_digest(Draft(stories=[story(headline="<script>alert(1)</script>")]), [article()], "2026-10-16", ["<img src=x>"])
    assert "<script>" not in result["html"]
    assert "&lt;script&gt;" in result["html"]
    assert "United Kingdom" in result["html"] and "대한민국" in result["html"]


def test_update_is_compared_to_latest_sent_evidence():
    history = [
        {"event_key": "uk-team-toolkit", "url": "https://example.com/latest", "evidence": article().evidence()},
        {"event_key": "uk-team-toolkit", "url": "https://example.com/old", "evidence": "A team announced plans."},
    ]
    updated = story(update_reason="Release now available", update_quote="released an AI evaluation toolkit")
    assert not normalize_draft(Draft(stories=[updated]), plan("a"), [article()], history).stories
