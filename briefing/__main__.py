import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from briefing.collection import collect, instant, save


def main():
    parser = argparse.ArgumentParser(description="Private UK/US/Korea IT & AI briefing")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect", help="Public RSS collection; no model or email")
    collect_parser.add_argument("--sources", type=Path, default=Path("sources.json"))
    collect_parser.add_argument("--database", type=Path, default=Path("var/briefing.sqlite3"))
    collect_parser.add_argument("--since", type=instant)
    collect_parser.add_argument("--until", type=instant)
    collect_parser.add_argument("--limit", type=int, default=50)
    for name in ("doctor", "demo", "preview", "prepare", "send", "serve", "status"):
        sub.add_parser(name)
    recovery = sub.add_parser("recover", help="Reconcile provider logs; never automatically resends")
    recovery.add_argument("--day", required=True)
    recovery.add_argument("--action", choices=["accepted", "not-accepted"], required=True)
    recovery.add_argument("--note", required=True, help="Evidence from provider logs, no credentials")
    recovery.add_argument("--provider-id")
    args = parser.parse_args()
    if args.command == "collect":
        until = args.until or datetime.now(timezone.utc)
        result = collect(json.loads(args.sources.read_text()), args.since or until-timedelta(hours=24), until, limit=args.limit)
        save(args.database, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["sources"] or all(s["status"] == "failed" for s in result["sources"]):
            raise SystemExit(2)
        return
    from briefing.config import Settings
    from briefing.storage import Store
    from briefing.app import deliver, generate, prepare, schedule, serve, worker_lock, write_preview
    settings = Settings.load()
    now = datetime.now(timezone.utc)
    day, prepare_at, send_at = schedule(now, settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if args.command == "doctor":
        print(json.dumps({"model": settings.model, "prepare_at": prepare_at.isoformat(), "send_at": send_at.isoformat(),
                          "missing": settings.missing(send=True), "tracing": os.getenv("LANGSMITH_TRACING", "false"),
                          "budget": "Not configured; bounded calls do not guarantee a monthly spend cap"}, indent=2))
        return
    if args.command == "status":
        row = Store(settings.data_dir).get(day)
        print(json.dumps({k: row[k] for k in ("day", "status", "generation_attempts", "send_attempts", "provider_id", "error")}
                         if row else {"day": day, "status": "not_started"}, indent=2))
        return
    if args.command == "recover":
        store = Store(settings.data_dir)
        with worker_lock(store):
            store.recover(args.day, args.action, args.note, now, args.provider_id)
        print("Reconciled; email was not sent by this command")
        return
    if args.command == "demo":
        os.environ["LANGSMITH_TRACING"] = "false"
        from briefing.demo import demo_content
        from briefing.render import render_digest
        draft, articles = demo_content()
        write_preview(render_digest(draft, articles, day, demo=True), settings.data_dir / "demo")
        print(settings.data_dir / "demo" / "briefing.html")
        return
    # Sending a prepared edition does not require another OpenAI call.
    missing = settings.missing(send=args.command in {"send", "serve"})
    if args.command == "send":
        missing = [name for name in ("RESEND_API_KEY", "MAIL_FROM") if not os.getenv(name)]
    if missing:
        parser.error("Missing secret settings: " + ", ".join(missing))
    if args.command == "preview":
        payload = generate(settings, Store(settings.data_dir), now)
        write_preview(payload, settings.data_dir / "preview")
        print(settings.data_dir / "preview" / "briefing.html")
    elif args.command == "prepare":
        print(prepare(settings, now))
    elif args.command == "send":
        print(deliver(settings, now))
    elif args.command == "serve":
        serve(settings)


if __name__ == "__main__":
    main()
