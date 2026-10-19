# TechNews Briefing

TechNews Briefing is a personal email digest of IT and AI developments in the United Kingdom, the United States, and South Korea. It brings regional news into one morning briefing, with English summaries for the UK and US and Korean summaries from Korean-language publishers for South Korea.

The system is designed to run on a server and target **08:00 Europe/London every day**, including weekends, without requiring a personal computer to stay on.

## What the briefing contains

Each country section includes selected stories with a headline, a concise summary, an explanation of why the story matters, the publisher, publication time, and a link to the original article. The default limit is three stories per country. Sections can contain fewer stories when suitable evidence is unavailable.

Stories are assigned to countries by the event's direct geographic relevance, rather than the publisher's location. The editorial workflow checks for repeated coverage and uses previously sent evidence to assess whether an existing event has a material update.

## How it works

1. **Collect:** Read configured RSS feeds, normalize URLs and timestamps, and filter out stale, undated, or ineligible entries. Store candidates and source-level collection reports in SQLite.
2. **Select:** Use an OpenAI model within a LangGraph workflow to assess IT/AI relevance, country relevance, and story selection.
3. **Gather evidence:** When the model requests more context, attempt a bounded lookup of the selected article on its publisher's allowed domains, subject to robots.txt access rules.
4. **Write and review:** Draft summaries from the supplied evidence, review them, and allow one revision pass. Exclude stories that do not pass review.
5. **Prepare:** Render HTML and plain-text email bodies and persist the edition before sending.
6. **Deliver:** Submit the saved edition to Resend and record its acceptance status. Ambiguous delivery results stop automatic retries until manually reconciled.

LangSmith tracing can be enabled to inspect the graph and model calls. Local execution metrics record token usage, elapsed editorial time, and candidate and approved-story counts.

AI review and evidence checks reduce errors but do not guarantee factual accuracy. Original article links remain part of every story.

## Schedule and reliability

By default, generation starts at **07:30**, with scheduled sending beginning at **08:00** in the `Europe/London` time zone, including British Summer Time changes. If preparation runs late, the worker can send once the edition is ready, until the automatic recovery window closes at 09:00. Exact inbox arrival at 08:00 is not guaranteed.

Prepared content is reused for delivery retries. Persistent edition records, a worker lock, atomic send-state changes, and a stable delivery idempotency key help prevent duplicate sends. Provider acceptance is tracked separately from confirmed inbox delivery.

The application is currently restricted to one configured recipient. It uses a single worker and a persistent SQLite database.

## Technology

| Component | Purpose |
|---|---|
| Python 3.11+ | Collection, scheduling, storage, and command-line tools |
| LangGraph | Conditional selection, evidence lookup, writing, and review |
| OpenAI | Structured editorial decisions and summaries |
| LangSmith | Optional graph and model tracing |
| SQLite | Collection reports, prepared editions, and delivery history |
| Resend | HTML and plain-text email delivery |
| Docker / Render | Containerized server deployment configuration |

Configured feeds include BBC, The Guardian, CNBC, NPR, Yonhap, Hankyoreh, and SBS. Their URLs and filtering settings are maintained in [`sources.json`](sources.json).

## Getting started

Run these commands from the repository root on macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
cp .env.example .env
```

If a `.env` file already exists, keep it and update its settings instead of overwriting it. Configure the following locally or through your hosting provider's secret settings:

| Setting | Purpose |
|---|---|
| `OPENAI_API_KEY` | Access to the editorial model |
| `OPENAI_MODEL` | Model name; defaults to `gpt-4.1-mini` |
| `RESEND_API_KEY` | Email delivery credentials |
| `MAIL_FROM` | An authorized Resend sender address |
| `LANGSMITH_TRACING` | Enable or disable tracing |
| `LANGSMITH_API_KEY` | Required when tracing is enabled |
| `LANGSMITH_PROJECT` | Trace project name |
| `DATA_DIR` | Persistent storage directory; defaults to `var` |
| `PREPARATION_MINUTES` | Minutes before 08:00 to begin generation; defaults to `30` |
| `MAX_PER_COUNTRY` | Maximum selected stories per section; defaults to `3` |

Keep credentials out of version control. `.env` is excluded from Git and Docker build context.

### Commands

```sh
python -m briefing doctor   # Check configuration without exposing key values
python -m briefing collect  # Collect RSS candidates without AI or email
python -m briefing demo     # Generate an offline preview with fictional stories
python -m briefing preview  # Generate a real-news AI preview without sending
python -m briefing prepare  # Generate and save today's edition without sending
python -m briefing status   # Inspect today's delivery state
python -m briefing serve    # Run daily preparation and scheduled delivery
```

`python -m briefing send` immediately submits an already prepared edition to the configured recipient; this manual command does not wait until 08:00.

Preview files are written under `DATA_DIR`: `demo/briefing.html` for fictional examples, `preview/briefing.html` for real-news previews, and `latest/briefing.html` for the prepared edition. Plain-text versions are also generated.

## Deployment and testing

[`render.yaml`](render.yaml) defines a Docker worker with a persistent `/data` disk. Deployment requires service credentials, an authorized sender, and a paid hosting configuration. Keep one worker and preserve the database across restarts and deployments.

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
docker build -t technews-briefing:local .
```

Collection, editorial branching, scheduling, delivery-state handling, and recovery have automated tests. Local Docker build and offline startup checks have passed. Live AI quality, LangSmith connectivity, inbox delivery, and unattended server operation still require end-to-end verification. Bounded calls and retries do not enforce a monthly spending cap.

See the [operations guide](docs/06-operations.md) (Korean) for delivery reconciliation, configuration details, and deployment verification.
