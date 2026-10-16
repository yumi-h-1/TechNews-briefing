import argparse
import fcntl
import json
import logging
import os
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from briefing.agent import build_graph, live_editor
from briefing.config import Settings
from briefing.demo import demo_content
from briefing.mail import DeliveryUncertain, send_email
from briefing.models import Draft
from briefing.news import NewsReader
from briefing.render import render_digest
from briefing.storage import Store

LOG = logging.getLogger(__name__)


def due(now, settings):
    local = now.astimezone(ZoneInfo(settings.timezone))
    target = local.replace(hour=settings.hour, minute=settings.minute, second=0, microsecond=0)
    return target <= local < target + timedelta(hours=1)


def generate(settings, store, now):
    reader = NewsReader()
    articles, warnings = reader.collect(store.window(now), now, store.sent_urls())
    if len(warnings) == len(reader.sources):
        raise RuntimeError("All news sources failed; refusing to send a misleading empty digest")
    if articles:
        state = build_graph(live_editor(settings), reader).invoke(
            {"articles": [a.model_dump() for a in articles], "history": store.history(now),
             "warnings": warnings, "revisions": 0},
            config={"run_name": "daily-it-editor", "recursion_limit": 15,
                    "tags": ["personal-briefing", "uk-us-kr"],
                    "metadata": {"edition": now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()}},
        )
        draft = Draft.model_validate(state["draft"])
        from briefing.models import Article
        articles = [Article.model_validate(a) for a in state["articles"]]
        warnings = state["warnings"]
    else:
        draft = Draft(stories=[])
    if not draft.stories:
        warnings.append("No stories passed freshness, relevance and evidence checks. / 최신성·관련성·근거 검토를 통과한 기사가 없습니다.")
    day = now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    payload = render_digest(draft, articles, day, warnings)
    by_id = {a.id: a for a in articles}
    payload["history"] = [{"url": by_id[s.article_id].url, "headline": s.headline,
                           "event_key": s.event_key} for s in draft.stories]
    payload["stories"] = draft.model_dump()["stories"]
    return payload


def write_preview(payload, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for key, extension in [("html", "html"), ("text", "txt")]:
        (directory / f"briefing.{extension}").write_text(payload[key], encoding="utf-8")


def deliver(settings, now=None):
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    store = Store(settings.data_dir)
    with (settings.data_dir / "delivery.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info("Another worker is active; skipped")
            return "locked"
        # A single persistent disk and one worker are required across deployments.
        if not store.begin(day):
            row = store.get(day)
            LOG.info("Edition skipped: %s (%s)", day, row["status"])
            return row["status"]
        try:
            row = store.get(day)
            if row["payload"]:
                payload = json.loads(row["payload"])
            else:
                payload = generate(settings, store, now)
                store.prepare(day, now, payload)
            write_preview(payload, settings.data_dir / "latest")
            store.status(day, "sending")
            try:
                provider_id = send_email(settings, payload, day, now)
            except DeliveryUncertain:
                store.status(day, "uncertain", "Provider result unknown. Inspect provider logs before recovery.")
                LOG.error("Delivery uncertain; automatic retries blocked for %s", day)
                return "uncertain"
            except Exception:
                store.status(day, "prepared", "Email rejected or connection/authentication failed")
                raise
            # If the process dies here, 'sending' blocks retries until manually reconciled.
            store.sent(day, provider_id)
            LOG.info("Edition accepted by mail provider: %s", day)
            return "sent"
        except Exception as exc:
            row = store.get(day)
            if row["status"] == "generating":
                store.status(day, "failed", type(exc).__name__)
            LOG.error("Briefing failed (%s); at most three attempts per local day", type(exc).__name__)
            raise


def check(settings, send):
    missing = settings.missing(send=send)
    if missing:
        raise RuntimeError("Missing settings: " + ", ".join(missing))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Private UK/US/Korea IT & AI briefing")
    parser.add_argument("command", choices=["doctor", "sources", "demo", "preview", "send", "serve", "status"])
    args = parser.parse_args(argv)
    settings = Settings.load()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Provider SDK request logs can expose metadata; retain only warnings.
    for name in ["httpx", "httpcore", "openai"]:
        logging.getLogger(name).setLevel(logging.WARNING)
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    if args.command == "doctor":
        print(f"Schedule: {settings.hour:02}:{settings.minute:02} {settings.timezone}; UK/US English, KR Korean")
        print(f"Transport: {settings.transport}; LangSmith: {os.getenv('LANGSMITH_TRACING', 'false')}")
        print("Missing: " + (", ".join(settings.missing(send=True)) or "none"))
        return
    if args.command == "sources":
        reader = NewsReader()
        articles, warnings = reader.collect(now - timedelta(hours=24), now)
        print(f"Fresh candidates: {len(articles)} / feeds: {len(reader.sources)}")
        for warning in warnings:
            print(warning)
        if len(warnings) == len(reader.sources):
            raise RuntimeError("All feeds failed")
        return
    if args.command == "demo":
        # Explicitly prevent any trace/network activity on the offline demo path.
        os.environ["LANGSMITH_TRACING"] = "false"
        draft, articles = demo_content()
        write_preview(render_digest(draft, articles, day, demo=True), settings.data_dir / "demo")
        print(f"Fictional demo: {settings.data_dir / 'demo' / 'briefing.html'}")
        return
    if args.command == "status":
        row = Store(settings.data_dir).get(day)
        print(json.dumps({k: row[k] for k in ("day", "status", "attempts", "error")} if row else
                         {"day": day, "status": "not_started"}, ensure_ascii=False, indent=2))
        return
    check(settings, send=args.command in {"send", "serve"})
    if args.command == "preview":
        payload = generate(settings, Store(settings.data_dir), now)
        write_preview(payload, settings.data_dir / "preview")
        print(f"Preview only: {settings.data_dir / 'preview' / 'briefing.html'}")
    elif args.command == "send":
        print(deliver(settings, now))
    else:
        scheduler = BlockingScheduler(timezone=settings.timezone)

        def tick():
            current = datetime.now(timezone.utc)
            if due(current, settings):
                try:
                    deliver(settings, current)
                except Exception:
                    pass  # Failure type logged above; retry bounded by persistent daily counter.

        scheduler.add_job(tick, "interval", minutes=1, next_run_time=now,
                          max_instances=1, coalesce=True, misfire_grace_time=60)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: scheduler.shutdown(wait=True) if scheduler.running else None)
        LOG.info("Worker ready: daily %02d:%02d %s, one-hour recovery window", settings.hour, settings.minute, settings.timezone)
        scheduler.start()


if __name__ == "__main__":
    main()
