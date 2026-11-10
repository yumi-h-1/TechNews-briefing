# TechNews Briefing

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![OpenAI](https://img.shields.io/badge/GPT--4.1_mini-412991?style=flat&logo=openai&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat&logo=langchain&logoColor=white)
![LangSmith](https://img.shields.io/badge/LangSmith-1C3C3C?style=flat&logo=langchain&logoColor=white)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup4-43B02A?style=flat&logo=python&logoColor=white)
![HTTPX](https://img.shields.io/badge/HTTPX-0A6FB5?style=flat&logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)
![Resend](https://img.shields.io/badge/Resend-000000?style=flat&logo=resend&logoColor=white)
![uv](https://img.shields.io/badge/uv-DE5FE9?style=flat&logo=uv&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat&logo=githubactions&logoColor=white)

TechNews Briefing is a personal email digest of IT and AI developments in the United Kingdom, the United States, and South Korea. It brings regional news into one morning briefing, with English summaries for the UK and US and Korean summaries from Korean-language publishers for South Korea.

It runs on **GitHub Actions** and targets **08:00 Europe/London every day**, including weekends, so no server or personal computer needs to stay on.

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

The workflow sets `PREPARATION_MINUTES=60`, so generation starts at **07:00** and sending begins no earlier than **08:00** in the `Europe/London` time zone, including British Summer Time changes. Several cron triggers start the workflow each day because GitHub often starts scheduled jobs late. A run that starts up to two hours before 07:00 waits for it; otherwise the first run of the day prepares and sends that day's edition however late it starts, and later runs do nothing. Exact inbox arrival at 08:00 is not guaranteed.

Prepared content is reused for delivery retries. Persistent edition records, a worker lock, atomic send-state changes, and a stable delivery idempotency key help prevent duplicate sends. A workflow concurrency group stops two runs from overlapping. Provider acceptance is tracked separately from confirmed inbox delivery.

The application is currently restricted to one configured recipient. Its SQLite database is carried between runs in the GitHub Actions cache.

## Technology

| Component | Purpose |
|---|---|
| Python 3.11+ | Collection, scheduling, storage, and command-line tools |
| LangGraph | Conditional selection, evidence lookup, writing, and review |
| OpenAI | Structured editorial decisions and summaries |
| LangSmith | Optional graph and model tracing |
| SQLite | Collection reports, prepared editions, and delivery history |
| Resend | HTML and plain-text email delivery |
| uv | Locked dependency installation and command execution |
| GitHub Actions | Daily scheduled runs and secret management |

Configured feeds include BBC, The Guardian, CNBC, NPR, Yonhap, Hankyoreh, and SBS. Their URLs and filtering settings are maintained in [`sources.json`](sources.json).

## Getting started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run these commands from the repository root on macOS or Linux:

```sh
uv sync --locked
cp .env.example .env
```

`.python-version` selects Python 3.13 for local development. `uv sync` creates the project’s `.venv` and installs the locked application and development dependencies. There is no need to activate the environment manually.

If a `.env` file already exists, keep it and update its settings instead of overwriting it. Configure the following locally, or as GitHub Actions secrets and variables (see [Deployment](#deployment)):

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
| `PREPARATION_MINUTES` | Minutes before 08:00 to begin generation; defaults to `30` (the workflow uses `60`) |
| `MAX_PER_COUNTRY` | Maximum selected stories per section; defaults to `3` |

Keep credentials out of version control. `.env` is excluded from Git.

### Commands

```sh
uv run --locked python -m briefing doctor   # Check configuration without exposing key values
uv run --locked python -m briefing collect  # Collect RSS candidates without AI or email
uv run --locked python -m briefing demo     # Generate an offline preview with fictional stories
uv run --locked python -m briefing preview  # Generate a real-news AI preview without sending
uv run --locked python -m briefing prepare  # Generate and save today's edition without sending
uv run --locked python -m briefing status   # Inspect today's delivery state
uv run --locked python -m briefing serve    # Run as an always-on worker (not used by GitHub Actions)
uv run --locked python -m briefing once     # One cron attempt: send today's edition (not before 08:00), once per day
```

`uv run --locked python -m briefing send` immediately submits an already prepared edition to the configured recipient; this manual command does not wait until 08:00.

Preview files are written under `DATA_DIR`: `demo/briefing.html` for fictional examples, `preview/briefing.html` for real-news previews, and `latest/briefing.html` for the prepared edition. Plain-text versions are also generated.

## Dependency management

`pyproject.toml` declares application dependencies and the `dev` dependency group. `uv.lock` records the resolved versions for reproducible installation and is committed to Git.

```sh
uv add package-name          # Add an application dependency
uv add --dev package-name    # Add a development dependency
uv lock --upgrade-package package-name  # Update a specific dependency
```

Commit both `pyproject.toml` and `uv.lock` when dependencies change. Normal setup and execution use `--locked` to detect an outdated lockfile. The workflow installs only application dependencies with `uv sync --locked --no-dev`.

## Deployment

[`.github/workflows/daily-briefing.yml`](.github/workflows/daily-briefing.yml) runs `briefing once` every morning on GitHub's servers. It is free for public repositories.

1. In the repository on GitHub, open **Settings → Secrets and variables → Actions** and add the secrets `OPENAI_API_KEY`, `RESEND_API_KEY`, and `MAIL_FROM`. Add `LANGSMITH_API_KEY` as well if you set the variable `LANGSMITH_TRACING` to `true`. The variables `OPENAI_MODEL` and `LANGSMITH_PROJECT` are optional.
2. Open **Actions → Daily briefing → Run workflow** and run `doctor`; the `missing` list should be empty.
3. From then on the scheduled triggers run the workflow each day. To send today's edition by hand, run the workflow with `once`; it does nothing if today's edition was already sent.

Limitations:

- GitHub often starts scheduled jobs hours late (delays of 4–9 hours were observed), so the email may arrive in the afternoon rather than at 08:00. For punctual delivery, have an external cron service call the workflow's `workflow_dispatch` API with `command: once` at about 07:05 London time.
- The SQLite state is kept in the Actions cache, which GitHub deletes after 7 days without use.
- GitHub disables scheduled workflows in public repositories after 60 days without repository activity; re-enable it from the Actions tab when GitHub emails you.

### Why GitHub Actions instead of Docker on Render

The project was first prepared as a Docker container running `briefing serve` as an always-on Render worker, with a persistent disk for SQLite. That setup needs a paid worker and a paid disk. The goal is for the email to arrive with no personal computer switched on, at no hosting cost, so in November 2026 deployment moved to a daily GitHub Actions workflow. OpenAI usage is now the only running cost.

The move trades punctuality for cost. A Render worker checks the clock every 30 seconds and sends close to 08:00. GitHub's scheduled jobs can start hours late, so the 09:00 automatic cut-off was dropped for `briefing once`: a late email is preferred over adding another external service. The persistent disk is replaced by the Actions cache, which has the 7-day eviction noted above.

[`Dockerfile`](Dockerfile), [`.dockerignore`](.dockerignore), and [`render.yaml`](render.yaml) are kept, unused, as a paid alternative for when on-time delivery matters more than cost. The workflow does not use them. To switch back, follow the Render section of the [operations guide](docs/06-operations.md).

## Testing

```sh
uv sync --locked
uv run --locked pytest -q
```

Collection, editorial branching, scheduling, delivery-state handling, and recovery have automated tests. Live AI quality, LangSmith connectivity, and inbox delivery still require end-to-end verification. Bounded calls and retries do not enforce a monthly spending cap.

See the [operations guide](docs/06-operations.md) (Korean) for delivery reconciliation, configuration details, and deployment verification.
