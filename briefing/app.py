import fcntl
import json
import logging
import os
import signal
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from briefing.collection import save
from briefing.config import Settings
from briefing.storage import Store

LOG = logging.getLogger(__name__)


def schedule(now, settings):
    local = now.astimezone(ZoneInfo(settings.timezone))
    send_at = local.replace(hour=8, minute=0, second=0, microsecond=0)
    prepare_at = send_at - timedelta(minutes=settings.preparation_minutes)
    return local.date().isoformat(), prepare_at, send_at


@contextmanager
def worker_lock(store):
    with (store.directory / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another worker is active") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def generate(settings, store, now):
    from briefing.agent import build_graph, live_editor
    from briefing.models import Article, Draft
    from briefing.news import NewsReader
    from briefing.render import render_digest
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    reader = NewsReader()
    articles, warnings = reader.collect(store.window(now), now)
    save(store.path, reader.report)
    if all(s["status"] == "failed" for s in reader.report["sources"]):
        raise RuntimeError("All sources failed")
    # Round-robin gives each source a share of the model's bounded candidate input.
    grouped = [[a for a in articles if a.source == s["name"]] for s in reader.sources]
    selected = [group[i] for i in range(50) for group in grouped if len(group) > i][:70]
    if len(selected) < len(articles):
        warnings.append(f"Editorial input capped: {len(selected)} of {len(articles)} candidates")
    day, _, _ = schedule(now, settings)
    usage = UsageMetadataCallbackHandler()
    started = time.monotonic()
    reason = "no_fresh_candidates"
    if selected:
        state = build_graph(live_editor(settings), reader).invoke(
            {"articles": [a.model_dump() for a in selected], "history": store.history(now),
             "warnings": warnings, "revisions": 0},
            config={"run_name": "daily-it-editor", "recursion_limit": 15,
                    "tags": ["uk-us-kr"], "metadata": {"edition": day}, "callbacks": [usage]})
        draft = Draft.model_validate(state["draft"])
        articles = [Article.model_validate(a) for a in state["articles"]]
        warnings = state["warnings"]
        reason = "approved" if draft.stories else ("review_rejected" if state["plan"]["picks"] else "no_relevant_candidates")
    else:
        draft = Draft(stories=[])
    if not draft.stories:
        warnings.append(f"No approved stories ({reason}) / 승인된 기사가 없습니다.")
    payload = render_digest(draft, articles, day, warnings)
    by_id = {a.id: a for a in articles}
    payload["history"] = [{"url": by_id[s.article_id].url, "headline": s.headline, "event_key": s.event_key,
                           "evidence": by_id[s.article_id].evidence()} for s in draft.stories]
    payload["stories"] = draft.model_dump()["stories"]
    payload["metrics"] = {"model": settings.model, "usage": usage.usage_metadata,
                          "seconds": round(time.monotonic()-started, 3), "result": reason,
                          "candidate_count": len(selected), "approved_count": len(draft.stories)}
    return payload


def write_preview(payload, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for key, extension in [("html", "html"), ("text", "txt"), ("metrics", "json")]:
        content = payload.get(key, {})
        (directory / f"briefing.{extension}").write_text(
            content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(settings, now=None):
    now = now or datetime.now(timezone.utc)
    store = Store(settings.data_dir)
    day, _, _ = schedule(now, settings)
    with worker_lock(store):
        if not store.begin_generation(day):
            return store.get(day)["status"]
        try:
            payload = generate(settings, store, now)
            store.prepare(day, now, payload)
            write_preview(payload, settings.data_dir / "latest")
            return "prepared"
        except Exception as exc:
            store.status(day, "failed", type(exc).__name__)
            raise


def deliver(settings, now=None):
    from briefing.mail import DeliveryUncertain, send_email
    now = now or datetime.now(timezone.utc)
    day, _, _ = schedule(now, settings)
    store = Store(settings.data_dir)
    with worker_lock(store):
        if not store.begin_send(day):
            row = store.get(day)
            return row["status"] if row else "not_prepared"
        payload = json.loads(store.get(day)["payload"])
        try:
            provider_id = send_email(settings, payload, day, now)
        except DeliveryUncertain:
            store.status(day, "uncertain", "Inspect provider logs before reconciliation")
            return "uncertain"
        except Exception as exc:
            store.status(day, "prepared", type(exc).__name__)
            raise
        store.accepted(day, provider_id)
        return "accepted"


def tick(settings, now, clock=None):
    day, prepare_at, send_at = schedule(now, settings)
    local = now.astimezone(ZoneInfo(settings.timezone))
    # Do not silently send a late edition after this provisional one-hour window.
    if not prepare_at <= local < send_at + timedelta(hours=1):
        return "outside_window"
    store = Store(settings.data_dir)
    row = store.get(day)
    if row and row["status"] in {"accepted", "sending", "uncertain"}:
        return row["status"]
    if not row or not row["payload"]:
        prepare(settings, now)
    # Generation can take minutes; use the actual clock before deciding to send.
    current = max(now, (clock or (lambda: datetime.now(timezone.utc)))())
    if schedule(current, settings)[0] != day:
        return "expired"
    if current.astimezone(ZoneInfo(settings.timezone)) >= send_at + timedelta(hours=1):
        return "expired"
    if current >= send_at:
        return deliver(settings, current)
    return "prepared"


def serve(settings):
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            result = tick(settings, datetime.now(timezone.utc))
            if result not in {"outside_window", "prepared", "accepted"}:
                LOG.warning("Worker state: %s", result)
        except Exception as exc:
            LOG.error("Worker attempt failed (%s)", type(exc).__name__)
        stop.wait(30)
