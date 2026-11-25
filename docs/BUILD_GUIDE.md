# TKO Tech Markets — build guide and runbook

How this dashboard was built, stage by stage: what each part does, why it is built that way, and how to run, change and fix it.
Built on 25 November 2026 on a Windows laptop, a GitHub personal account and a Snowflake trial account.

---

## 1. The system at a glance

```
            every 5 min, Mon–Fri 13:00–21:59 UTC (GitHub Actions: ingest.yml)
 ┌──────────────┐   HTTPS + API key    ┌──────────────────────────────┐
 │ Finnhub API  │ ───────────────────► │ ingest/  (Python)            │
 │ quotes, news,│                      │ run_ingest.py                │
 │ profiles     │                      └──────────────┬───────────────┘
 └──────────────┘                                     │ key-pair JWT, role TKO_INGESTER
                                                      ▼
                         ┌─────────────────────────────────────────────┐
                         │ Snowflake  TKO_DB                           │
                         │  RAW : QUOTES, COMPANY_NEWS, COMPANY_PROFILE│
                         │  MART: V_LATEST_QUOTES, V_PRICE_HISTORY,    │
                         │        V_NEWS_FEED, V_NEWS_VOLUME,          │
                         │        V_PIPELINE_FRESHNESS                 │
                         └──────────────┬──────────────────────────────┘
                                        │ publish/export_snapshot.py (same job)
                                        ▼
                         ┌─────────────────────────────────────────────┐
                         │ GitHub branch `data`  (always 1 commit)     │
                         │ manifest.json + 5 JSON files                │
                         └───────┬──────────────────────────┬──────────┘
          hourly, Claude         │                          │  weekdays 22:10 UTC + manual
          scheduled task         ▼                          ▼  (publish-site.yml)
             ┌───────────────────────────────┐  ┌───────────────────────────────────┐
             │ Claude dashboard (private)    │  │ Customer website (public)         │
             │ claude.ai/artifact/9EQRU4W5…  │  │ gilkroin.github.io/tko-dashboard  │
             │ same page code ───────────────┼──┼─► + site/shell.html adapter       │
             └───────────────────────────────┘  └───────────────────────────────────┘
```

| Output | Where | Freshness | Who can open it |
|---|---|---|---|
| Claude dashboard | https://claude.ai/artifact/9EQRU4W5hXLbPMbSk6619M | within ~1 hour in market hours | you, and anyone you share it with in Claude |
| Customer website | https://gilkroin.github.io/tko-dashboard/ | one snapshot per weekday after US close, or on demand | anyone with the link |
| Raw data | Snowflake `TKO_DB` | every 5 minutes in market hours | Snowflake users with the roles below |

---

## 2. Accounts, identities and secrets

Every arrow in the diagram has its own identity with the smallest possible permissions.

| Identity | Used by | Signs in with | Can do | Secret lives in |
|---|---|---|---|---|
| Your GitHub user | you, on the laptop | `gh auth login` (browser OAuth), scopes `repo`, `workflow` | push code, set secrets, run workflows | Windows Credential Manager |
| `GITHUB_TOKEN` | each Actions run | created by GitHub per run, expires at run end | push the `data` branch (`contents: write`), deploy Pages | nowhere (temporary) |
| Finnhub API key | ingestion | header `X-Finnhub-Token` | read market data, 60 calls/min | `.env` (laptop), secret `FINNHUB_API_KEY` |
| `TKO_INGEST_SVC` (Snowflake service user) | ingestion + export | RSA key pair (no password, `TYPE = SERVICE`) | role `TKO_INGESTER`: SELECT/INSERT on RAW, SELECT on MART | `keys/tko_ingest_rsa_key.p8` (laptop), secret `SNOWFLAKE_PRIVATE_KEY` |
| Your Snowflake user via Claude | Claude connector "TKO SnowFlake" | OAuth (`TKO_CLAUDE_OAUTH`, public client) | role `TKO_DASHBOARD_READER`: read MART only. **Blocked on trial accounts** | claude.ai connector token |
| Claude scheduled task | hourly dashboard refresh | your Claude account | read the public `data` branch, update the dashboard's data files | none |

Rules that kept secrets safe:
- `.gitignore` excludes `.env`, `keys/`, `*.p8`, `*.pem`, `.venv/`, `snapshot/`, `site/dist/`.
- Secrets were set from `.env` through a PowerShell variable, never typed into chat or committed.
- GitHub masks secret values as `***` in logs.
- `snowflake/02_…sql` with your pasted public key is deliberately left uncommitted (the repo keeps the template).

---

## 3. Stage by stage

### Stage 0 — Decisions
- **Data API: Finnhub (free tier).** One API for quotes, company news and profiles; 60 calls/minute is enough for 7 tickers every 5 minutes (≈14–21 calls per run).
- **Tickers:** AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA (GitHub variable `TICKERS`).
- **Scheduler: GitHub Actions** (free for public repos, code and schedule in one place).
- **Customer hosting: GitHub Pages.**
- **Cost guardrail:** Snowflake bills at least 60 s each time a warehouse wakes. 5-minute runs only in market hours + an X-Small warehouse that suspends after 60 s + a 40-credit monthly resource monitor.

### Stage 1 — Laptop
1. Folder `C:\Users\Gil\tko-dashboard`, connected to Claude through the desktop app.
2. GitHub CLI: `winget install --id GitHub.cli -e`, then `gh auth login --scopes "repo,workflow"`.
3. Git identity: `git config --global user.name / user.email`.
4. Python virtual environment: `py -m venv .venv`, `.\.venv\Scripts\Activate.ps1`, `pip install -r requirements.txt`.

Note: `C:\Users\Gil` is itself a Git repository. `git init` inside the project folder makes the project its own repository.

### Stage 2 — GitHub repository
```powershell
git init -b main
git add . ; git commit -m "Initial skeleton"
gh repo create tko-dashboard --public --source . --remote origin --push
```
Branches: `main` holds code; `data` holds only the latest snapshot and is force-pushed by the workflow (so `main` history stays clean).

### Stage 3 — Snowflake
Run in Snowsight, role ACCOUNTADMIN, **Run All** (Ctrl/Cmd + Shift + Enter):

| Script | Creates |
|---|---|
| `01_foundation_and_claude_connector.sql` | warehouse `TKO_WH`, resource monitor `TKO_MONTHLY_CAP`, database `TKO_DB` with schemas RAW / CORE / MART / APP, RAW tables, MART views, role `TKO_DASHBOARD_READER`, MCP server `TKO_DB.APP.TKO_MCP`, OAuth integration `TKO_CLAUDE_OAUTH` |
| `02_ingest_role_and_service_user.sql` | role `TKO_INGESTER`, service user `TKO_INGEST_SVC` with your public key (from `python scripts/generate_keypair.py`) |
| `03_snapshot_export_grants.sql` | lets `TKO_INGESTER` read MART views for the export |

Data layers: **RAW** keeps what the API returned (with the full JSON in `raw_payload` for audits); **MART** has one view per dashboard card, so a card can change without touching ingestion.

### Stage 4 — Ingestion
- `ingest/finnhub_client.py`: `/quote`, `/company-news` (last 2 days), `/stock/profile2`; retries on HTTP 429, clear message on 401/403.
- `ingest/snowflake_loader.py`: quotes appended every run; news **MERGEd** on `(news_id, ticker)` so an article is stored once; profiles at most every 20 h.
- Test locally: `python -m ingest.run_ingest --dry-run`, `--check-snowflake`, then a full run.
- GitHub secrets: `FINNHUB_API_KEY`, `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_PRIVATE_KEY`; variable `TICKERS`.

### Stage 5 — Claude dashboard
- **Why a snapshot:** Snowflake trial accounts can't use the Snowflake-managed MCP server ("Access denied for trial accounts"), so Claude can't query Snowflake live.
- `publish/export_snapshot.py` writes the five MART views to JSON; the workflow force-pushes them to the `data` branch.
- The Claude dashboard reads uploaded copies of those files. Scheduled task **"TKO dashboard hourly refresh"** (cron `0 13-22 * * 1-5` UTC) uploads the newest snapshot and deletes the copy it replaced.
- Page code: `claude-dashboard/index.html`. Each card is its own drawing with its own controls; the headline sentence uses a calculation (`breadth`) that Sources shows.

### Stage 6 — Customer website
- `site/shell.html` provides design tokens, d3 and a ~40-line `dash` adapter that loads `data/*.json` **once** (no timers).
- `publish/build_site.py` combines `claude-dashboard/index.html` with the shell, changes three sentences that only apply to the live Claude version, and copies the data.
- `publish-site.yml` builds and deploys to GitHub Pages weekdays at 22:10 UTC and on demand.

### Stage 7 — Verification (25 Nov 2026)
| Check | Result |
|---|---|
| `main` has all 20 source files, no secrets | ✓ |
| `data` branch, Claude dashboard and public site hold the same snapshot (09:27:11 UTC, row counts 7 / 21 / 200 / 21 / 3) | ✓ |
| NVDA in the snapshot ($155.38, −5.86%, prev. close $165.05) vs independent press reports of the 24 Nov close | ✓ exact match |
| Claude dashboard self-check | ✓ passed (after fixing overlapping bar labels) |
| Customer site rendered at 1280 px and 420 px; sort, filter, search work; no console errors | ✓ |
| Hourly scheduled task exists and is enabled | ✓ first run 25 Nov 13:06 UTC — verify after it runs |

---

## 4. Runbook

### Everyday commands (PowerShell, in the project folder)
```powershell
.\.venv\Scripts\Activate.ps1                       # start every session with this
gh run list --workflow ingest --limit 5            # recent loads
$id = gh run list --workflow ingest --limit 1 --json databaseId --jq '.[0].databaseId'
gh run view $id --log-failed | Select-Object -Last 30   # why did it fail?
gh workflow run ingest                             # load now
gh workflow run publish-site                       # republish the customer site now
```

### Change the tracked companies
```powershell
gh variable set TICKERS --body "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,AVGO,AMD"
```
Also update `TICKERS` in `.env` for local runs. Mind the Finnhub limit: about 3 calls per ticker per run, 60 calls/minute.

### Change a card
Ask Claude to change the Claude dashboard, then copy the page code into `claude-dashboard/index.html` and commit, so the customer site picks it up on its next publish.

### Pause everything (e.g. holidays, cost)
```powershell
gh workflow disable ingest
gh workflow disable publish-site
```
Pause the Claude scheduled task in claude.ai → Scheduled tasks. Re-enable with `gh workflow enable …`.

### Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` / "Finnhub refused the API key" | wrong key in `.env` or GitHub secret | re-set the secret from `.env` (see §2) |
| `JWT token is invalid` / Snowflake auth error | secret `SNOWFLAKE_PRIVATE_KEY` doesn't match the public key on `TKO_INGEST_SVC` | `Get-Content keys\tko_ingest_rsa_key.p8 -Raw \| gh secret set SNOWFLAKE_PRIVATE_KEY` |
| `Insufficient privileges` in export | script 03 not run | run `03_snapshot_export_grants.sql` |
| Warehouse suspended, loads fail | resource monitor reached 100 % | raise `CREDIT_QUOTA` or wait for next month |
| Schedule stopped by itself | GitHub disables schedules in public repos after 60 days without commits | `gh workflow enable ingest` |
| Claude dashboard shows "stale" | hourly task failed or market closed | check its last run in claude.ai → Scheduled tasks |
| `git push` says "Everything up-to-date" | nothing was committed | `git status`, `git add …`, `git commit` |
| Claude can't write `.github/...` | protected path for remote tools | Claude stages the file in `setup\`; move it with `Move-Item` |

### Costs to watch
- **Snowflake:** Admin → Cost management, or `SHOW RESOURCE MONITORS;`.
- **GitHub Actions:** free for public repositories.
- **Finnhub:** free tier.

---

## 5. Possible next steps
1. **Live Claude dashboard:** upgrade Snowflake to a paid account; the existing connector and MCP server then allow live queries from the Claude dashboard every time it opens.
2. **dbt for MART views:** move the view SQL into dbt models with tests (a `.dbt` folder already exists on the laptop).
3. **Alerting:** a workflow step that fails when `V_PIPELINE_FRESHNESS` is older than 30 minutes in market hours.
4. **More content:** earnings calendar, analyst recommendations, or sentiment scores (other Finnhub endpoints).
