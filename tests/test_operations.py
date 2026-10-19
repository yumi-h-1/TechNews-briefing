import json
from datetime import datetime, timezone
from unittest.mock import Mock
import httpx
import pytest
from briefing.app import deliver, prepare, schedule, tick, worker_lock
from briefing.config import Settings
from briefing.mail import DeliveryUncertain, send_email
from briefing.storage import Store

NOW = datetime(2026, 10, 16, 7, tzinfo=timezone.utc)


def payload():
    return {"subject": "test", "html": "<p>test</p>", "text": "test", "history": [
        {"url": "https://example.com/a", "event_key": "event", "headline": "Headline", "evidence": "Evidence"}]}


@pytest.mark.parametrize("date,send_hour", [("2026-07-01", 7), ("2026-12-01", 8), ("2026-03-29", 7), ("2026-10-25", 8)])
def test_local_preparation_and_send_across_dst(tmp_path, date, send_hour):
    now = datetime.fromisoformat(date+"T06:00:00+00:00")
    day, preparation, sending = schedule(now, Settings(tmp_path))
    assert day == date
    assert sending.astimezone(timezone.utc).hour == send_hour
    assert preparation.hour == 7 and preparation.minute == 30
    assert sending.hour == 8 and sending.minute == 0


def test_prepare_then_send_only_once(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    generation = Mock(return_value=payload())
    sending = Mock(return_value="provider-123")
    monkeypatch.setattr("briefing.app.generate", generation)
    monkeypatch.setattr("briefing.mail.send_email", sending)
    before = NOW.replace(hour=6, minute=30)
    assert tick(settings, before, clock=lambda: before) == "prepared"
    sending.assert_not_called()
    assert tick(settings, NOW, clock=lambda: NOW) == "accepted"
    assert tick(settings, NOW, clock=lambda: NOW) == "accepted"
    assert generation.call_count == 1 and sending.call_count == 1
    store = Store(tmp_path)
    assert store.window(NOW) == before
    assert store.history(NOW)[0]["event_key"] == "event"


def test_retries_reuse_body_and_have_separate_limits(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    generation = Mock(return_value=payload())
    sending = Mock(side_effect=RuntimeError("rejected"))
    monkeypatch.setattr("briefing.app.generate", generation)
    monkeypatch.setattr("briefing.mail.send_email", sending)
    assert prepare(settings, NOW) == "prepared"
    for _ in range(3):
        with pytest.raises(RuntimeError):
            deliver(settings, NOW)
    assert deliver(settings, NOW) == "prepared"
    assert sending.call_count == 3 and generation.call_count == 1
    assert Store(tmp_path).get("2026-10-16")["generation_attempts"] == 1


def test_generation_failure_is_bounded(tmp_path, monkeypatch):
    generation = Mock(side_effect=RuntimeError("model unavailable"))
    monkeypatch.setattr("briefing.app.generate", generation)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            prepare(Settings(tmp_path), NOW)
    assert prepare(Settings(tmp_path), NOW) == "failed"
    assert generation.call_count == 3


def test_uncertain_requires_provider_reconciliation(tmp_path, monkeypatch):
    monkeypatch.setattr("briefing.app.generate", Mock(return_value=payload()))
    sending = Mock(side_effect=DeliveryUncertain("timeout"))
    monkeypatch.setattr("briefing.mail.send_email", sending)
    settings = Settings(tmp_path)
    prepare(settings, NOW)
    assert deliver(settings, NOW) == "uncertain"
    assert deliver(settings, NOW) == "uncertain"
    assert sending.call_count == 1
    store = Store(tmp_path)
    assert not store.history(NOW)
    with worker_lock(store):
        store.recover("2026-10-16", "accepted", "Provider log confirms acceptance", NOW, "provider-123")
    assert deliver(settings, NOW) == "accepted"
    assert store.history(NOW)


def test_crash_after_request_blocks_resend_and_recovery_is_audited(tmp_path):
    store = Store(tmp_path)
    store.begin_generation("2026-10-16")
    store.prepare("2026-10-16", NOW, payload())
    assert store.begin_send("2026-10-16")
    assert not store.begin_send("2026-10-16")
    store.recover("2026-10-16", "not-accepted", "No request accepted per provider log", NOW)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM recovery_audit").fetchone()[0] == 1
    assert store.begin_send("2026-10-16")


def test_two_store_instances_cannot_claim_same_send(tmp_path):
    a, b = Store(tmp_path), Store(tmp_path)
    a.begin_generation("2026-10-16")
    a.prepare("2026-10-16", NOW, payload())
    assert a.begin_send("2026-10-16")
    assert not b.begin_send("2026-10-16")


def test_resend_stable_payload_and_idempotency_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "offline-test-key")
    response = Mock(status_code=200)
    response.json.return_value = {"id": "provider-123"}
    post = Mock(return_value=response)
    monkeypatch.setattr("briefing.mail.httpx.post", post)
    settings = Settings(tmp_path, sender="News <news@example.com>")
    for _ in range(2):
        assert send_email(settings, payload(), "2026-10-16", NOW) == "provider-123"
    first, second = [call.kwargs for call in post.call_args_list]
    assert first == second
    assert first["json"]["to"] == [settings.recipient]


@pytest.mark.parametrize("status", [409, 500, 503])
def test_ambiguous_resend_response_is_not_retried(tmp_path, monkeypatch, status):
    monkeypatch.setenv("RESEND_API_KEY", "offline-test-key")
    monkeypatch.setattr("briefing.mail.httpx.post", Mock(return_value=Mock(status_code=status)))
    with pytest.raises(DeliveryUncertain):
        send_email(Settings(tmp_path, sender="news@example.com"), payload(), "2026-10-16", NOW)


def test_no_early_or_expired_scheduled_send(tmp_path, monkeypatch):
    prepare_mock = Mock()
    monkeypatch.setattr("briefing.app.prepare", prepare_mock)
    settings = Settings(tmp_path)
    assert tick(settings, NOW.replace(hour=5)) == "outside_window"
    assert tick(settings, NOW.replace(hour=8)) == "outside_window"
    prepare_mock.assert_not_called()


def test_only_owner_and_fixed_timezone_are_allowed(tmp_path):
    with pytest.raises(ValueError):
        Settings(tmp_path, recipient="someone@example.com")
    with pytest.raises(ValueError):
        Settings(tmp_path, timezone="UTC")


def test_generation_trace_input_excludes_mail_and_secrets(tmp_path, monkeypatch):
    from briefing.app import generate
    from briefing.models import Article
    monkeypatch.setenv("OPENAI_API_KEY", "secret-not-for-traces")
    candidate = Article(id="a", title="AI news", url="https://example.com/a", source="Publisher",
                        language="en", published=NOW.isoformat(), excerpt="An AI research announcement.")
    reader = Mock()
    reader.collect.return_value = ([candidate], [])
    reader.sources = [{"name": "Publisher"}]
    reader.report = {"run_id": "run-a", "since": "2026-10-15T07:00:00+00:00", "until": NOW.isoformat(),
                     "sources": [{"status": "ok"}], "articles": [candidate.model_dump()]}
    graph = Mock()
    graph.invoke.return_value = {"articles": [candidate.model_dump()], "draft": {"stories": []},
                                 "plan": {"picks": []}, "warnings": []}
    monkeypatch.setattr("briefing.news.NewsReader", Mock(return_value=reader))
    monkeypatch.setattr("briefing.agent.live_editor", Mock())
    monkeypatch.setattr("briefing.agent.build_graph", Mock(return_value=graph))
    result = generate(Settings(tmp_path, sender="sender@example.com"), Store(tmp_path), NOW)
    state = graph.invoke.call_args.args[0]
    trace_input = json.dumps(state, ensure_ascii=False)
    assert "secret-not-for-traces" not in trace_input
    assert "sender@example.com" not in trace_input
    assert "yumi.heo.01@gmail.com" not in trace_input
    assert result["metrics"]["result"] == "no_relevant_candidates"
